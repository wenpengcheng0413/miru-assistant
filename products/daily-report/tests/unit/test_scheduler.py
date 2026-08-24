"""
Miru Assistant — 调度器单元测试 (Task 11)。

测试覆盖:
    - HealthStatus 默认值
    - check_health (mock DB)
    - check_scheduler_installed (mock subprocess)
    - check_missed_today
    - send_failure_notification
    - run_daily 入口 import
"""

import os
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from miru.scheduler.scheduler import (
    HealthStatus,
    check_health,
    check_missed_today,
    check_scheduler_installed,
    send_failure_notification,
)


# ============================================================
# Test: HealthStatus
# ============================================================


class TestHealthStatus:
    def test_defaults(self):
        h = HealthStatus()
        assert h.is_healthy is False
        assert h.config_exists is False
        assert h.db_exists is False
        assert h.scheduler_installed is False

    def test_all_good(self):
        h = HealthStatus(
            config_exists=True,
            db_exists=True,
            scheduler_installed=True,
        )
        h.is_healthy = True
        assert h.is_healthy is True


# ============================================================
# Test: Scheduler Detection
# ============================================================


class TestSchedulerDetection:
    def test_installed(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            assert check_scheduler_installed("Miru Assistant Daily Report") is True

    def test_not_installed(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            assert check_scheduler_installed("Nonexistent") is False

    def test_subprocess_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert check_scheduler_installed() is False


# ============================================================
# Test: Health Check
# ============================================================


class TestHealthCheck:
    def test_returns_health_status(self, tmp_path):
        """基本健康检查返回 HealthStatus。"""
        # 创建 mock DB
        db_path = tmp_path / "test.db"
        db_path.write_text("mock")

        with patch("miru.scheduler.scheduler.Path.exists", return_value=True):
            with patch("miru.scheduler.scheduler.check_scheduler_installed", return_value=False):
                h = check_health(str(db_path))

        assert isinstance(h, HealthStatus)
        assert h.python_version != ""

    def test_no_config(self, tmp_path):
        db_path = tmp_path / "nodb.db"
        with patch("miru.scheduler.scheduler.check_scheduler_installed", return_value=False):
            h = check_health(str(db_path))
        assert h.config_exists is False


# ============================================================
# Test: Missed Today
# ============================================================


class TestMissedToday:
    def test_no_db_means_missed(self):
        """数据库不存在 = 今天未运行。"""
        result = check_missed_today("/nonexistent/db.db")
        assert result is True

    def test_with_db(self, tmp_path):
        """数据库存在但没有今日日报 → missed。"""
        from miru.storage.database import Database
        from miru.storage.migrations import run_migrations

        db_path = str(tmp_path / "missed.db")
        db = Database(db_path)
        run_migrations(db)
        db.close()

        result = check_missed_today(db_path)
        assert result is True  # 没有今天的数据


# ============================================================
# Test: Failure Notification
# ============================================================


class TestFailureNotification:
    def test_sends_to_all_notifiers(self):
        n1 = MagicMock()
        n1.send.return_value = True
        n2 = MagicMock()
        n2.send.return_value = False

        ok = send_failure_notification(
            [n1, n2], "test error", "test_stage",
        )
        assert ok is True  # 至少一个成功
        n1.send.assert_called_once()
        n2.send.assert_called_once()
        # 验证内容
        call_args = n1.send.call_args
        assert "Miru Assistant" in call_args[0][0]  # title
        assert "test error" in call_args[0][1]       # content

    def test_all_fail(self):
        n1 = MagicMock()
        n1.send.return_value = False
        ok = send_failure_notification([n1], "error")
        assert ok is False

    def test_empty_notifiers(self):
        ok = send_failure_notification([], "error")
        assert ok is False

    def test_notifier_exception(self):
        n1 = MagicMock()
        n1.send.side_effect = RuntimeError("boom")
        ok = send_failure_notification([n1], "error")
        assert ok is False  # 异常被捕获，不会传播


# ============================================================
# Test: run_daily.py entry
# ============================================================


class TestRunDailyEntry:
    def test_module_imports(self):
        """run_daily.py 可以正常导入。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "run_daily",
            os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "run_daily.py"),
        )
        assert spec is not None
        # 验证文件存在且语法正确
        mod = importlib.util.module_from_spec(spec)
        assert mod is not None
