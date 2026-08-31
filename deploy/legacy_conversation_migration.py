"""Export and merge only legacy Miru conversation history.

The export package intentionally excludes memory, WeChat indexes, credentials,
cost records, and logs. Commands print counts and hashes only, never content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

TABLES = ("conversations", "turn_traces", "messages", "attachments")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_with_hash(source: Path, destination: Path) -> bool:
    """Copy one payload and report whether this call created the destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(source) != _sha256(destination):
            raise RuntimeError(f"destination collision: {destination.name}")
        return False
    shutil.copy2(source, destination)
    return True


def export_package(source_db: Path, package_db: Path, media_dir: Path) -> dict:
    if package_db.exists() or media_dir.exists():
        raise RuntimeError("export destinations must not already exist")
    package_db.parent.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True)
    source = sqlite3.connect(f"file:{source_db.resolve()}?mode=ro", uri=True)
    target = sqlite3.connect(package_db)
    try:
        for table in TABLES:
            schema = source.execute(
                "select sql from sqlite_master where type='table' and name=?", (table,)
            ).fetchone()
            if not schema or not schema[0]:
                raise RuntimeError(f"missing source table: {table}")
            target.execute(schema[0])
            columns = [row[1] for row in source.execute(f"pragma table_info({table})")]
            placeholders = ",".join("?" for _ in columns)
            rows = source.execute(f"select {','.join(columns)} from {table}").fetchall()
            target.executemany(
                f"insert into {table} ({','.join(columns)}) values ({placeholders})",
                rows,
            )

        attachment_rows = target.execute(
            "select id,local_path,preview_paths from attachments"
        ).fetchall()
        attachment_columns = {
            row[1] for row in target.execute("pragma table_info(attachments)")
        }
        copied = 0
        for attachment_id, raw_path, raw_previews in attachment_rows:
            source_path = Path(raw_path)
            if not source_path.is_file():
                continue
            suffix = source_path.suffix.lower()[:12]
            name = f"{attachment_id}{suffix}"
            _copy_with_hash(source_path, media_dir / name)
            previews = []
            try:
                source_previews = json.loads(raw_previews or "[]")
            except json.JSONDecodeError:
                source_previews = []
            for index, preview in enumerate(source_previews):
                preview_path = Path(str(preview))
                if not preview_path.is_file():
                    continue
                preview_name = f"{attachment_id}-preview-{index}{preview_path.suffix.lower()[:12]}"
                _copy_with_hash(preview_path, media_dir / preview_name)
                previews.append(preview_name)
            if "storage_key" in attachment_columns:
                target.execute(
                    "update attachments set local_path=?,storage_key=?,preview_paths=? where id=?",
                    (name, name, json.dumps(previews, ensure_ascii=False), attachment_id),
                )
            else:
                # Phase 0 predates the storage_key migration.  Keep the export
                # package faithful to that schema; merge_package writes the
                # normalized key into the already-migrated Cloud database.
                target.execute(
                    "update attachments set local_path=?,preview_paths=? where id=?",
                    (name, json.dumps(previews, ensure_ascii=False), attachment_id),
                )
            copied += 1
        target.commit()
        counts = {
            table: target.execute(f"select count(1) from {table}").fetchone()[0]
            for table in TABLES
        }
        counts["attachment_files"] = copied
        counts["integrity"] = target.execute("pragma integrity_check").fetchone()[0]
    finally:
        target.close()
        source.close()
    counts["package_sha256"] = _sha256(package_db)
    return counts


def _row_dicts(db: sqlite3.Connection, table: str) -> list[dict]:
    cursor = db.execute(f"select * from {table}")
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def merge_package(
    package_db: Path,
    target_db: Path,
    package_media: Path,
    target_media: Path,
    container_media: str,
    backup_db: Path,
) -> dict:
    source = sqlite3.connect(f"file:{package_db.resolve()}?mode=ro", uri=True)
    target = sqlite3.connect(target_db)
    target.row_factory = sqlite3.Row
    copied_paths: list[Path] = []
    try:
        unexpected = {
            row[0]
            for row in source.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        } - set(TABLES)
        if unexpected:
            raise RuntimeError("package contains unexpected tables")
        backup_db.parent.mkdir(parents=True, exist_ok=True)
        if backup_db.exists():
            raise RuntimeError("backup destination already exists")
        backup = sqlite3.connect(backup_db)
        try:
            target.backup(backup)
            if backup.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("backup integrity check failed")
        finally:
            backup.close()

        target.execute("pragma foreign_keys=on")
        target.execute("begin immediate")
        inserted_conversations = inserted_messages = inserted_traces = inserted_attachments = 0

        for row in _row_dicts(source, "conversations"):
            current = target.execute(
                "select * from conversations where id=?", (row["id"],)
            ).fetchone()
            if current is None:
                target.execute(
                    "insert into conversations(id,title,persona,created_at,updated_at) values(?,?,?,?,?)",
                    tuple(row[key] for key in ("id", "title", "persona", "created_at", "updated_at")),
                )
                inserted_conversations += 1
            else:
                title = current["title"] or row["title"]
                persona = current["persona"] or row["persona"]
                created_at = min(str(current["created_at"]), str(row["created_at"]))
                updated_at = max(str(current["updated_at"]), str(row["updated_at"]))
                target.execute(
                    "update conversations set title=?,persona=?,created_at=?,updated_at=? where id=?",
                    (title, persona, created_at, updated_at, row["id"]),
                )

        trace_map: dict[str, str] = {}
        for row in _row_dicts(source, "turn_traces"):
            trace_id = str(row["id"])
            existing = target.execute(
                "select conversation_id from turn_traces where id=?", (trace_id,)
            ).fetchone()
            mapped = trace_id
            if existing is not None and existing[0] != row["conversation_id"]:
                mapped = f"legacy-{uuid.uuid4().hex}"
            trace_map[trace_id] = mapped
            if existing is not None and mapped == trace_id:
                continue
            row["id"] = mapped
            columns = list(row)
            target.execute(
                f"insert into turn_traces({','.join(columns)}) values({','.join('?' for _ in columns)})",
                tuple(row[key] for key in columns),
            )
            inserted_traces += 1

        existing_messages = {
            hashlib.sha256("\0".join(str(row[key] or "") for key in (
                "conversation_id", "role", "content", "created_at"
            )).encode("utf-8")).digest()
            for row in target.execute(
                "select conversation_id,role,content,created_at from messages"
            )
        }
        for row in _row_dicts(source, "messages"):
            fingerprint = hashlib.sha256("\0".join(str(row[key] or "") for key in (
                "conversation_id", "role", "content", "created_at"
            )).encode("utf-8")).digest()
            if fingerprint in existing_messages:
                continue
            turn_id = row.get("turn_id")
            target.execute(
                "insert into messages(conversation_id,turn_id,role,content,created_at) values(?,?,?,?,?)",
                (
                    row["conversation_id"],
                    trace_map.get(str(turn_id), turn_id) if turn_id else None,
                    row["role"], row["content"], row["created_at"],
                ),
            )
            existing_messages.add(fingerprint)
            inserted_messages += 1

        target_media.mkdir(parents=True, exist_ok=True)
        for row in _row_dicts(source, "attachments"):
            source_path = package_media / Path(str(row["local_path"])).name
            if not source_path.is_file():
                continue
            attachment_id = str(row["id"])
            existing = target.execute(
                "select conversation_id,sha256 from attachments where id=?", (attachment_id,)
            ).fetchone()
            if existing is not None:
                if (
                    str(existing[0]) == str(row["conversation_id"])
                    and str(existing[1]) == str(row["sha256"])
                ):
                    continue
                attachment_id = uuid.uuid4().hex
            suffix = source_path.suffix.lower()[:12]
            file_name = f"{attachment_id}{suffix}"
            destination = target_media / file_name
            if _copy_with_hash(source_path, destination):
                copied_paths.append(destination)
            previews = []
            try:
                raw_previews = json.loads(row.get("preview_paths") or "[]")
            except json.JSONDecodeError:
                raw_previews = []
            for index, preview in enumerate(raw_previews):
                source_preview = package_media / Path(str(preview)).name
                if not source_preview.is_file():
                    continue
                preview_name = f"{attachment_id}-preview-{index}{source_preview.suffix.lower()[:12]}"
                preview_destination = target_media / preview_name
                if _copy_with_hash(source_preview, preview_destination):
                    copied_paths.append(preview_destination)
                previews.append(f"{container_media.rstrip('/')}/{preview_name}")
            target.execute(
                """insert into attachments(
                    id,conversation_id,filename,media_type,kind,size_bytes,sha256,
                    local_path,status,extracted_text,error,preview_paths,created_at,storage_key
                ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    attachment_id, row["conversation_id"], row["filename"], row["media_type"],
                    row["kind"], row["size_bytes"], row["sha256"],
                    f"{container_media.rstrip('/')}/{file_name}", row["status"],
                    row["extracted_text"], row["error"], json.dumps(previews, ensure_ascii=False),
                    row["created_at"], file_name,
                ),
            )
            inserted_attachments += 1

        integrity = target.execute("pragma integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("post-merge integrity check failed")
        target.commit()
        return {
            "inserted_conversations": inserted_conversations,
            "inserted_messages": inserted_messages,
            "inserted_turn_traces": inserted_traces,
            "inserted_attachments": inserted_attachments,
            "final_conversations": target.execute("select count(1) from conversations").fetchone()[0],
            "final_messages": target.execute("select count(1) from messages").fetchone()[0],
            "integrity": integrity,
            "backup_sha256": _sha256(backup_db),
        }
    except Exception:
        target.rollback()
        for path in copied_paths:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    finally:
        target.close()
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--source-db", type=Path, required=True)
    export.add_argument("--package-db", type=Path, required=True)
    export.add_argument("--media-dir", type=Path, required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--package-db", type=Path, required=True)
    merge.add_argument("--target-db", type=Path, required=True)
    merge.add_argument("--package-media", type=Path, required=True)
    merge.add_argument("--target-media", type=Path, required=True)
    merge.add_argument("--container-media", default="/app/data/attachments")
    merge.add_argument("--backup-db", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = export_package(args.source_db, args.package_db, args.media_dir)
    else:
        result = merge_package(
            args.package_db, args.target_db, args.package_media,
            args.target_media, args.container_media, args.backup_db,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
