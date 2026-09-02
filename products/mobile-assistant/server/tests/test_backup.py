import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from miru_server.db.backup import (
    backup_database,
    create_verified_backup,
    restore_to_staging,
    verify_backup,
)


def _database(path: Path) -> Path:
    import sqlite3

    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
        db.execute("INSERT INTO conversations VALUES ('safe-id')")
        db.execute("INSERT INTO messages VALUES (1, 'private body')")
        db.execute("PRAGMA user_version=2")
        db.commit()
    return path


def test_backup_database_keeps_daily_snapshot(tmp_path: Path):
    import sqlite3

    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE test (value TEXT)")
        db.execute("INSERT INTO test VALUES ('safe')")
        db.commit()

    target = backup_database(source, tmp_path / "backups", retention_days=30)
    assert target.exists()
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM test").fetchone()[0] == "safe"


def test_verified_backup_has_content_free_attachment_manifest(tmp_path: Path):
    source = _database(tmp_path / "source.db")
    attachments = tmp_path / "attachments"
    attachment = attachments / "record-id" / "private-filename.txt"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"attachment bytes")

    result = create_verified_backup(
        source,
        tmp_path / "backups",
        attachment_dir=attachments,
        now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
    )
    payload = json.loads(result.manifest.read_text(encoding="utf-8"))
    rendered = result.manifest.read_text(encoding="utf-8")

    assert result.created is True
    assert result.weekly_database.exists()
    assert payload["database"]["integrity"] == "ok"
    assert payload["database"]["user_version"] == 2
    assert payload["database"]["row_counts"] == {"conversations": 1, "messages": 1}
    assert payload["attachments"]["file_count"] == 1
    assert payload["attachments"]["total_bytes"] == len(b"attachment bytes")
    assert "private-filename" not in rendered
    assert "private body" not in rendered
    assert verify_backup(
        result.database,
        result.manifest,
        attachment_dir=attachments,
    )["integrity"] == "ok"


def test_verified_backup_detects_tampering(tmp_path: Path):
    result = create_verified_backup(
        _database(tmp_path / "source.db"),
        tmp_path / "backups",
        now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
    )
    with result.database.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(RuntimeError, match="size mismatch"):
        verify_backup(result.database, result.manifest)


def test_restore_only_uses_new_staging_directory(tmp_path: Path):
    source = _database(tmp_path / "source.db")
    attachments = tmp_path / "attachments"
    attachment = attachments / "id" / "file.bin"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"safe")
    result = create_verified_backup(
        source,
        tmp_path / "backups",
        attachment_dir=attachments,
        now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
    )

    staging = tmp_path / "restore-staging"
    restored = restore_to_staging(
        result.database,
        result.manifest,
        staging,
        attachment_dir=attachments,
    )
    assert restored["staged"] is True
    assert (staging / "miru_server.db").exists()
    assert (staging / "attachments" / "id" / "file.bin").read_bytes() == b"safe"

    with pytest.raises(FileExistsError):
        restore_to_staging(result.database, result.manifest, staging)


def test_daily_and_weekly_retention_are_bounded(tmp_path: Path):
    source = _database(tmp_path / "source.db")
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in range(1, 6):
        (backups / f"miru-2026-08-{day:02d}.db").write_bytes(b"old")
    weekly = backups / "weekly"
    weekly.mkdir()
    for week in range(1, 11):
        (weekly / f"miru-2026-W{week:02d}.db").write_bytes(b"old")

    create_verified_backup(
        source,
        backups,
        retention_days=2,
        weekly_retention_weeks=8,
        now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
    )

    assert not list(backups.glob("miru-2026-08-??.db"))
    assert len(list(weekly.glob("miru-????-W??.db"))) == 8


def test_backup_admin_verify_output_is_safe(tmp_path: Path):
    result = create_verified_backup(
        _database(tmp_path / "source.db"),
        tmp_path / "backups",
        now=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
    )
    server_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(server_root / "scripts" / "backup_admin.py"),
            "verify",
            "--database",
            str(result.database),
            "--manifest",
            str(result.manifest),
        ],
        cwd=server_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["ok"] is True
    assert str(tmp_path) not in completed.stdout
    assert "private body" not in completed.stdout
