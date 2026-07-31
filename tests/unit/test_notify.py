"""
Miru Assistant — 推送层单元测试 (Task 9)。

测试覆盖:
    - PushPlusNotifier send (mock HTTP)
    - 重试逻辑
    - 超长内容截断
    - token 检查
    - ConsoleNotifier
    - Dispatcher 集成
    - DB 状态更新
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from miru.notify.base import Notifier
from miru.notify.console import ConsoleNotifier
from miru.notify.dispatcher import DispatchResult, dispatch_report, retry_failed_pushes
from miru.notify.pushplus import (
    MAX_CONTENT_LENGTH,
    PUSHPLUS_API_URL,
    PushPlusNotifier,
)
from miru.storage.models import DailyReport, now_ts


# ============================================================
# Helpers
# ============================================================

def _mock_response(code=200, msg="success"):
    resp = MagicMock()
    resp.json.return_value = {"code": code, "msg": msg}
    resp.status_code = code
    return resp


# ============================================================
# Test: PushPlusNotifier
# ============================================================


class TestPushPlusNotifier:
    def test_is_healthy_with_token(self):
        n = PushPlusNotifier(token="abc123")
        assert n.is_healthy() is True

    def test_is_healthy_without_token(self):
        n = PushPlusNotifier(token="")
        assert n.is_healthy() is False

    def test_is_healthy_with_env_var_placeholder(self):
        n = PushPlusNotifier(token="${MIRU_PUSHPLUS_TOKEN}")
        assert n.is_healthy() is False

    def test_send_success(self):
        n = PushPlusNotifier(token="test-token")
        with patch.object(n.client, "post", return_value=_mock_response(200)):
            ok = n.send("Test Title", "Test Content")
            assert ok is True

    def test_send_failure_401(self):
        n = PushPlusNotifier(token="bad-token")
        with patch.object(n.client, "post", return_value=_mock_response(401, "invalid token")):
            ok = n.send("Title", "Content")
            assert ok is False

    def test_send_retries_on_500(self):
        n = PushPlusNotifier(token="test", max_retries=2)
        responses = [
            _mock_response(500, "server error"),
            _mock_response(500, "server error"),
            _mock_response(200, "ok"),
        ]
        with patch.object(n.client, "post", side_effect=responses) as mock_post:
            ok = n.send("Title", "Content")
            assert ok is True
            assert mock_post.call_count == 3

    def test_send_all_retries_fail(self):
        n = PushPlusNotifier(token="test", max_retries=1)
        responses = [
            _mock_response(500, "err"),
            _mock_response(500, "err"),
        ]
        with patch.object(n.client, "post", side_effect=responses):
            ok = n.send("Title", "Content")
            assert ok is False

    def test_truncates_long_content(self):
        n = PushPlusNotifier(token="test")
        long_content = "x" * (MAX_CONTENT_LENGTH + 500)
        with patch.object(n.client, "post", return_value=_mock_response(200)) as mock_post:
            ok = n.send("Title", long_content)
            assert ok is True
            sent_content = mock_post.call_args[1]["json"]["content"]
            assert len(sent_content) <= MAX_CONTENT_LENGTH
            assert "截断" in sent_content

    def test_no_token_skips_send(self):
        n = PushPlusNotifier(token="")
        ok = n.send("Title", "Content")
        assert ok is False

    def test_uses_correct_api_params(self):
        n = PushPlusNotifier(token="tok123")
        with patch.object(n.client, "post", return_value=_mock_response(200)) as mock_post:
            n.send("My Title", "# Markdown Content")
            call_args = mock_post.call_args
            assert call_args[0][0] == PUSHPLUS_API_URL
            json_data = call_args[1]["json"]
            assert json_data["token"] == "tok123"
            assert json_data["title"] == "My Title"
            assert json_data["template"] == "markdown"
            assert json_data["channel"] == "wechat"

    def test_close(self):
        n = PushPlusNotifier(token="test")
        with patch.object(n.client, "post", return_value=_mock_response(200)):
            n.send("T", "C")
        n.close()
        assert n._client is None


# ============================================================
# Test: ConsoleNotifier
# ============================================================


class TestConsoleNotifier:
    def test_is_healthy(self):
        n = ConsoleNotifier()
        assert n.is_healthy() is True

    def test_send_always_true(self, capsys):
        n = ConsoleNotifier()
        ok = n.send("Title", "Content")
        assert ok is True
        captured = capsys.readouterr()
        assert "Title" in captured.out
        assert "Content" in captured.out


# ============================================================
# Test: Dispatcher
# ============================================================


class TestDispatcher:
    def test_dispatch_all_success(self, tmp_path):
        """所有渠道成功。"""
        db_path = str(tmp_path / "dispatch.db")
        n1 = ConsoleNotifier()
        n2 = ConsoleNotifier()

        result = dispatch_report(
            "# Report", [n1, n2], "2026-07-24", db_path,
        )
        assert result.total == 2
        assert result.success == 2
        assert result.failed == 0

    def test_dispatch_partial_failure(self, tmp_path):
        """部分渠道失败。"""
        db_path = str(tmp_path / "partial.db")
        good = ConsoleNotifier()
        bad = PushPlusNotifier(token="")  # 无 token → 必然失败

        result = dispatch_report("# R", [good, bad], "2026-07-24", db_path)
        assert result.success == 1
        assert result.failed == 1

    def test_dispatch_empty_notifiers(self, tmp_path):
        """空渠道列表。"""
        db_path = str(tmp_path / "empty.db")
        result = dispatch_report("# R", [], "", db_path)
        assert result.total == 0

    def test_retry_failed_no_db(self):
        """没有数据库时返回 0。"""
        count = retry_failed_pushes(
            [ConsoleNotifier()],
            "/nonexistent/db.db",
        )
        assert count == 0

    def test_retry_failed_with_db(self, tmp_path):
        """数据库中有失败记录时补推。"""
        from miru.storage.database import Database
        from miru.storage.migrations import run_migrations
        from miru.storage.repository import ReportRepository

        db_path = str(tmp_path / "retry.db")

        # 创建一条 failed 日报
        db = Database(db_path)
        run_migrations(db)
        repo = ReportRepository(db)
        report = DailyReport(
            report_date="2026-07-24",
            content_md="# Test",
            push_status="failed",
            push_error="timeout",
            generated_at=now_ts(),
        )
        repo.insert_report(report)
        # 设置 push_status 为 failed (INSERT OR REPLACE 会保持 pending)
        repo.update_push_status_by_date("2026-07-24", "failed", "timeout")
        db.close()

        count = retry_failed_pushes(
            [ConsoleNotifier()],
            db_path,
            max_days=30,
        )
        assert count == 1


# ============================================================
# Test: DispatchResult
# ============================================================


class TestDispatchResult:
    def test_defaults(self):
        r = DispatchResult()
        assert r.total == 0
        assert r.success == 0
        assert r.failed == 0
