"""Static safety checks for the host-level Phase 10 backup scheduler."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SYSTEMD = REPO_ROOT / "deploy" / "systemd"


def _read(name: str) -> str:
    return (SYSTEMD / name).read_text(encoding="utf-8")


def test_phase10_systemd_files_exist():
    for name in (
        "miru-backup.service",
        "miru-backup.timer",
        "miru-backup-failure@.service",
        "README.md",
    ):
        assert (SYSTEMD / name).is_file()


def test_backup_service_uses_bounded_verified_cli():
    text = _read("miru-backup.service")
    assert "WorkingDirectory=/opt/miru/app/current" in text
    assert "/usr/bin/docker compose -p miru-prod" in text
    assert "exec -T miru-api python /app/scripts/backup_admin.py create" in text
    assert "--database /app/data/miru_server.db" in text
    assert "--destination /app/data/backups" in text
    assert "--attachments /app/data/attachments" in text
    assert "--daily 14 --weekly 8" in text
    assert "OnFailure=miru-backup-failure@%n.service" in text
    assert "TimeoutStartSec=15min" in text
    assert "NoNewPrivileges=true" in text


def test_backup_timer_is_persistent_and_jittered():
    text = _read("miru-backup.timer")
    assert "OnCalendar=*-*-* 03:17:00 Asia/Shanghai" in text
    assert "RandomizedDelaySec=15m" in text
    assert "AccuracySec=1m" in text
    assert "Persistent=true" in text
    assert "Unit=miru-backup.service" in text


def test_failure_marker_is_content_free_and_local_only():
    text = _read("miru-backup-failure@.service")
    assert "MIRU_BACKUP_ALERT=backup_failed" in text
    forbidden = (
        "curl ",
        "wget ",
        "http://",
        "https://",
        "restic",
        "rclone",
        "server_token",
        "api_key",
        "secret",
        "/app/data",
    )
    assert not any(marker in text.lower() for marker in forbidden)
