from pathlib import Path

import pytest
from miru_server.config import AttachmentConfig
from miru_server.operations import capacity_snapshot, pressure_state
from pydantic import ValidationError


def test_pressure_thresholds_match_phase10_policy():
    assert pressure_state(69.9) == "normal"
    assert pressure_state(70) == "warning"
    assert pressure_state(85) == "restricted"
    assert pressure_state(90) == "critical"


def test_capacity_snapshot_is_bounded_and_has_no_path(tmp_path):
    snapshot = capacity_snapshot(tmp_path / "not-created-yet")

    assert snapshot["disk"]["state"] in {
        "normal", "warning", "restricted", "critical", "unknown"
    }
    assert set(snapshot["disk"]) == {"state", "used_percent", "free_mb"}
    assert set(snapshot["process"]) == {
        "rss_mb", "swap_used_mb", "memory_available_mb", "load_1m"
    }
    assert str(tmp_path) not in str(snapshot)


def test_attachment_pressure_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        AttachmentConfig(
            disk_warning_percent=85,
            disk_preview_stop_percent=70,
            disk_upload_stop_percent=90,
        )


def test_phase10_overlay_and_production_policy_are_wired():
    repo = Path(__file__).resolve().parents[4]
    overlay = (repo / "deploy" / "Dockerfile.phase10-overlay").read_text("utf-8")
    settings = (repo / "deploy" / "production" / "settings.production.yaml").read_text("utf-8")

    for required in (
        "miru_server/api/ws.py",
        "miru_server/attachments.py",
        "miru_server/db/backup.py",
        "miru_server/operations.py",
        "miru_server/persona/builder.py",
        "scripts/backup_admin.py",
    ):
        assert required in overlay
    assert "enabled: true" in settings
    assert "retention_days: 14" in settings
    assert "weekly_retention_weeks: 8" in settings
    assert "soft_quota_gb: 10" in settings
    assert "disk_upload_stop_percent: 90" in settings
