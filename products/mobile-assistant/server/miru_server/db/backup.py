"""Verified SQLite and attachment backup primitives.

The application creates a consistent SQLite snapshot and a content-free
attachment manifest. Restores are deliberately limited to a new staging
directory; switching the production volume remains an operator action.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_COUNT_TABLES = (
    "conversations",
    "messages",
    "attachments",
    "memory_profile",
    "memory_preferences",
    "memory_projects",
    "memory_knowledge",
    "memory_episodes",
)


@dataclass(frozen=True)
class BackupResult:
    database: Path
    manifest: Path
    weekly_database: Path
    created: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_metadata(path: Path) -> dict:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("backup integrity check failed")
        user_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        counts = {
            name: int(db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in _COUNT_TABLES
            if name in tables
        }
    return {"integrity": "ok", "user_version": user_version, "row_counts": counts}


def _attachment_manifest(root: Path | None) -> dict:
    if root is None or not root.exists():
        return {"file_count": 0, "total_bytes": 0, "files": []}
    if root.is_symlink():
        raise RuntimeError("attachment backup refuses a symbolic-link root")
    root = root.resolve()
    files: list[dict] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("attachment backup refuses symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        files.append(
            {
                # Do not expose user filenames in manifests or monitoring.
                "path_id": hashlib.sha256(relative.encode("utf-8")).hexdigest(),
                "size_bytes": size,
                "sha256": _sha256(path),
            }
        )
    return {"file_count": len(files), "total_bytes": total_bytes, "files": files}


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_atomic(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _rotate_daily(directory: Path, today: date, retention_days: int) -> None:
    cutoff = today - timedelta(days=max(retention_days, 1) - 1)
    for old in directory.glob("miru-????-??-??.db"):
        try:
            day = date.fromisoformat(old.stem.removeprefix("miru-"))
        except ValueError:
            continue
        if day < cutoff:
            old.unlink()
            old.with_suffix(".manifest.json").unlink(missing_ok=True)


def _rotate_weekly(directory: Path, retention_weeks: int) -> None:
    snapshots = sorted(directory.glob("miru-????-W??.db"), reverse=True)
    for old in snapshots[max(retention_weeks, 1):]:
        old.unlink()
        old.with_suffix(".manifest.json").unlink(missing_ok=True)


def create_verified_backup(
    source: str | Path,
    destination_dir: str | Path,
    *,
    attachment_dir: str | Path | None = None,
    retention_days: int = 14,
    weekly_retention_weeks: int = 8,
    now: datetime | None = None,
) -> BackupResult:
    """Create one verified daily DB snapshot and an attachment manifest."""
    source_input = Path(source)
    destination_input = Path(destination_dir)
    attachments = Path(attachment_dir) if attachment_dir is not None else None
    if source_input.is_symlink():
        raise RuntimeError("backup refuses a symbolic-link database source")
    if destination_input.is_symlink():
        raise RuntimeError("backup refuses a symbolic-link destination")
    source = source_input.resolve()
    destination = destination_input.resolve()
    if not source.is_file():
        raise FileNotFoundError("source database does not exist")
    destination.mkdir(parents=True, exist_ok=True)

    timestamp = now or datetime.now(timezone.utc)
    day = timestamp.date()
    target = destination / f"miru-{day:%Y-%m-%d}.db"
    manifest_path = target.with_suffix(".manifest.json")
    created = False
    if target.is_symlink() or manifest_path.is_symlink():
        raise RuntimeError("backup refuses symbolic-link snapshot files")

    if not target.exists():
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        try:
            with (
                closing(sqlite3.connect(source)) as src,
                closing(sqlite3.connect(temporary)) as dst,
            ):
                src.backup(dst)
            _sqlite_metadata(temporary)
            os.replace(temporary, target)
            created = True
        finally:
            temporary.unlink(missing_ok=True)

    database_meta = _sqlite_metadata(target)
    if not manifest_path.exists():
        manifest = {
            "schema_version": 1,
            "created_at": timestamp.astimezone(timezone.utc).isoformat(),
            "database": {
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
                **database_meta,
            },
            "attachments": _attachment_manifest(attachments),
        }
        _atomic_json(manifest_path, manifest)
    verify_backup(target, manifest_path)

    iso_year, iso_week, _ = day.isocalendar()
    weekly_dir = destination / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly = weekly_dir / f"miru-{iso_year:04d}-W{iso_week:02d}.db"
    weekly_manifest = weekly.with_suffix(".manifest.json")
    if weekly.is_symlink() or weekly_manifest.is_symlink():
        raise RuntimeError("backup refuses symbolic-link weekly snapshot files")
    if not weekly.exists():
        _copy_atomic(target, weekly)
        _copy_atomic(manifest_path, weekly_manifest)
    verify_backup(weekly, weekly_manifest)

    _rotate_daily(destination, day, retention_days)
    _rotate_weekly(weekly_dir, weekly_retention_weeks)
    return BackupResult(target, manifest_path, weekly, created)


def verify_backup(
    database: str | Path,
    manifest: str | Path,
    *,
    attachment_dir: str | Path | None = None,
) -> dict:
    """Verify a snapshot without returning paths, filenames, or content."""
    database = Path(database)
    manifest = Path(manifest)
    if database.is_symlink() or manifest.is_symlink():
        raise RuntimeError("backup verification refuses symbolic links")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    expected = payload.get("database", {})
    if database.stat().st_size != expected.get("bytes"):
        raise RuntimeError("backup size mismatch")
    if _sha256(database) != expected.get("sha256"):
        raise RuntimeError("backup hash mismatch")
    metadata = _sqlite_metadata(database)
    if metadata["user_version"] != expected.get("user_version"):
        raise RuntimeError("backup schema version mismatch")
    if metadata["row_counts"] != expected.get("row_counts"):
        raise RuntimeError("backup row-count mismatch")
    if attachment_dir is not None:
        actual_attachments = _attachment_manifest(Path(attachment_dir))
        if actual_attachments != payload.get("attachments"):
            raise RuntimeError("attachment manifest mismatch")
    return {
        "integrity": "ok",
        "user_version": metadata["user_version"],
        "database_bytes": database.stat().st_size,
        "attachment_file_count": int(payload.get("attachments", {}).get("file_count", 0)),
        "attachment_bytes": int(payload.get("attachments", {}).get("total_bytes", 0)),
    }


def restore_to_staging(
    database: str | Path,
    manifest: str | Path,
    staging_dir: str | Path,
    *,
    attachment_dir: str | Path | None = None,
) -> dict:
    """Restore only into a new directory and verify the staged copy."""
    database_input = Path(database)
    manifest_input = Path(manifest)
    staging_input = Path(staging_dir)
    if database_input.is_symlink() or manifest_input.is_symlink() or staging_input.is_symlink():
        raise RuntimeError("restore refuses symbolic links")
    database = database_input.resolve()
    manifest = manifest_input.resolve()
    staging = staging_input.resolve()
    if staging.exists():
        raise FileExistsError("restore staging directory already exists")
    verify_backup(database, manifest, attachment_dir=attachment_dir)
    staging.mkdir(parents=True, exist_ok=False)
    staged_database = staging / "miru_server.db"
    staged_manifest = staging / "backup.manifest.json"
    _copy_atomic(database, staged_database)
    _copy_atomic(manifest, staged_manifest)
    if attachment_dir is not None:
        source_attachments = Path(attachment_dir).resolve()
        target_attachments = staging / "attachments"
        if source_attachments.exists():
            shutil.copytree(source_attachments, target_attachments, symlinks=False)
        else:
            target_attachments.mkdir()
    result = verify_backup(
        staged_database,
        staged_manifest,
        attachment_dir=(staging / "attachments") if attachment_dir is not None else None,
    )
    result["staged"] = True
    return result


def backup_database(
    source: str | Path,
    destination_dir: str | Path,
    retention_days: int = 30,
) -> Path:
    """Backward-compatible DB-only wrapper used by existing callers."""
    return create_verified_backup(
        source,
        destination_dir,
        retention_days=retention_days,
    ).database
