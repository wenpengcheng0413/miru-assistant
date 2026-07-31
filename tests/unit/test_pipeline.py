"""
Miru Assistant — Pipeline 编排器单元测试 (Task 10)。

测试覆盖:
    - 完整成功流程 (mock 所有阶段)
    - Dry-run 模式 (不推送)
    - 微信未运行 (终止)
    - 部分 LLM 失败 (继续)
    - 空消息处理
    - PipelineContext
"""

from unittest.mock import MagicMock, patch

import pytest

from miru.core.context import PipelineContext
from miru.core.pipeline import MiruPipeline


# ============================================================
# Helpers
# ============================================================

def _make_mock_config(data_dir: str = "/mock/wechat"):
    return {
        "miru": {
            "groups": ["测试群"],
            "scheduler": {"daily_report_time": "21:00", "timezone": "Asia/Shanghai", "misfire_grace_time": 1800},
            "llm": {"provider": "deepseek", "api_key": "sk-test", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash", "temperature": 0.3, "max_tokens": 2048, "timeout": 60, "max_retries": 1, "retry_delay": [1]},
            "notifiers": [{"type": "console", "enabled": True, "token": ""}],
            "storage": {"db_path": ":memory:", "log_path": "./data/logs", "log_level": "INFO", "log_retention": "30 days", "log_rotation": "10 MB"},
            "wechat": {"data_dir": data_dir, "tested_version": "4.0.x", "on_version_mismatch": "warn"},
        }
    }


def _setup_wechat_files(tmp_path):
    """在临时目录创建模拟微信文件结构。"""
    db_dir = tmp_path / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "contact.db").write_bytes(b"\x00" * 4096)
    (db_dir / "message_0.db").write_bytes(b"\x00" * 4096 * 3)
    return tmp_path


def _make_mock_decrypt_result(tmp_path):
    r = MagicMock()
    r.success = True
    r.is_decrypted = True
    r.db_path = str(tmp_path / "db" / "contact.db")  # point to actual file
    return r


def _make_mock_reader(groups, messages):
    r = MagicMock()
    r.get_groups.return_value = groups
    r.get_messages.return_value = messages
    return r


def _make_mock_group(name="测试群", username="test@chatroom"):
    g = MagicMock()
    g.username = username
    g.nickname = name
    g.remark = ""
    return g


def _make_mock_msg(server_id=1, content="测试消息", sender="张三", group="测试群"):
    from miru.collector.wechat_reader import WeChatMessage
    return WeChatMessage(
        server_id=server_id, content=content, sender_name=sender,
        group_name=group, create_time=1711800000, time_str="09:00",
        local_type=1, is_text=True, is_system=False,
    )


def _make_mock_llm_results(success_count=1, fail_count=0):
    from miru.llm.schemas import GroupAnalysis, LLMCallResult, TokenUsage
    results = []
    for i in range(success_count):
        results.append(LLMCallResult(
            group_name=f"群{i+1}",
            analysis=GroupAnalysis(
                group_name=f"群{i+1}", total_messages=1, valid_messages=1,
                urgent_tasks=[], deadlines=[], notices=[], files=[],
                summary="ok", ignored_topics="",
            ),
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            success=True,
        ))
    for i in range(fail_count):
        results.append(LLMCallResult(
            group_name=f"失败群{i+1}", success=False, error="timeout",
        ))
    return results


# ============================================================
# Test: PipelineContext
# ============================================================


class TestPipelineContext:
    def test_defaults(self):
        ctx = PipelineContext()
        assert ctx.run_id != ""
        assert ctx.dry_run is False
        assert ctx.has_errors is False
        assert ctx.is_success is True

    def test_with_errors(self):
        ctx = PipelineContext()
        ctx.errors.append("test error")
        assert ctx.has_errors is True
        assert ctx.is_success is False


# ============================================================
# Test: Full Pipeline (Mock)
# ============================================================


class TestPipelineFull:
    """完整 Pipeline 流程 (mock 微信 + LLM)。"""

    def test_full_success(self, tmp_path):
        import yaml

        wx_dir = _setup_wechat_files(tmp_path)
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(yaml.dump(_make_mock_config(str(wx_dir))), encoding="utf-8")

        pipeline = MiruPipeline(str(config_path))

        mock_proc = MagicMock(found=True, pid=12345, version_raw="4.0.3.29")
        mock_dd = MagicMock(found=True, path=str(wx_dir))
        mock_group = _make_mock_group("测试群")
        mock_msg = _make_mock_msg()
        mock_result = _make_mock_decrypt_result(tmp_path)
        mock_reader = _make_mock_reader([mock_group], [mock_msg])
        mock_llm = _make_mock_llm_results(1)

        with (
            patch("miru.collector.diagnostics.detect_wechat_process", return_value=mock_proc),
            patch("miru.collector.diagnostics.find_wechat_data_dir", return_value=mock_dd),
            patch("miru.collector.wechat_db_decrypt.extract_keys_from_process", return_value=[]),
            patch("miru.collector.wechat_db_decrypt.try_decrypt_wechat_db", return_value=mock_result),
            patch("miru.collector.wechat_reader.WeChatDBReader", return_value=mock_reader),
            patch("miru.llm.DeepSeekClient.analyze_groups", return_value=mock_llm),
        ):
            ctx = pipeline.run(dry_run=False)

        assert ctx.raw_messages_count == 1
        assert ctx.groups_summarized == 1
        assert len(ctx.report_md) > 0

    def test_wechat_not_running(self, tmp_path):
        import yaml
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(yaml.dump(_make_mock_config()), encoding="utf-8")
        pipeline = MiruPipeline(str(config_path))
        mock_proc = MagicMock(found=False)

        with patch("miru.collector.diagnostics.detect_wechat_process", return_value=mock_proc):
            ctx = pipeline.run()
        assert ctx.has_errors
        assert "未运行" in ctx.errors[0]

    def test_dry_run_skips_push(self, tmp_path):
        import yaml

        wx_dir = _setup_wechat_files(tmp_path)
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(yaml.dump(_make_mock_config(str(wx_dir))), encoding="utf-8")
        pipeline = MiruPipeline(str(config_path))

        mock_proc = MagicMock(found=True, pid=12345, version_raw="4.0.3.29")
        mock_dd = MagicMock(found=True, path=str(wx_dir))
        mock_group = _make_mock_group("测试群")
        mock_msg = _make_mock_msg()
        mock_result = _make_mock_decrypt_result(tmp_path)
        mock_reader = _make_mock_reader([mock_group], [mock_msg])
        mock_llm = _make_mock_llm_results(1)

        with (
            patch("miru.collector.diagnostics.detect_wechat_process", return_value=mock_proc),
            patch("miru.collector.diagnostics.find_wechat_data_dir", return_value=mock_dd),
            patch("miru.collector.wechat_db_decrypt.extract_keys_from_process", return_value=[]),
            patch("miru.collector.wechat_db_decrypt.try_decrypt_wechat_db", return_value=mock_result),
            patch("miru.collector.wechat_reader.WeChatDBReader", return_value=mock_reader),
            patch("miru.llm.DeepSeekClient.analyze_groups", return_value=mock_llm),
            patch("miru.notify.dispatcher.dispatch_report") as mock_dispatch,
        ):
            ctx = pipeline.run(dry_run=True)

        assert ctx.push_status == "skipped"
        mock_dispatch.assert_not_called()

    def test_partial_llm_failure(self, tmp_path):
        import yaml

        wx_dir = _setup_wechat_files(tmp_path)
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(yaml.dump(_make_mock_config(str(wx_dir))), encoding="utf-8")
        pipeline = MiruPipeline(str(config_path))

        mock_proc = MagicMock(found=True, pid=12345, version_raw="4.0.3.29")
        mock_dd = MagicMock(found=True, path=str(wx_dir))
        mock_group = _make_mock_group("测试群")
        mock_msg = _make_mock_msg()
        mock_result = _make_mock_decrypt_result(tmp_path)
        mock_reader = _make_mock_reader([mock_group], [mock_msg])
        mock_llm = _make_mock_llm_results(1, 1)  # 1 success + 1 fail

        with (
            patch("miru.collector.diagnostics.detect_wechat_process", return_value=mock_proc),
            patch("miru.collector.diagnostics.find_wechat_data_dir", return_value=mock_dd),
            patch("miru.collector.wechat_db_decrypt.extract_keys_from_process", return_value=[]),
            patch("miru.collector.wechat_db_decrypt.try_decrypt_wechat_db", return_value=mock_result),
            patch("miru.collector.wechat_reader.WeChatDBReader", return_value=mock_reader),
            patch("miru.llm.DeepSeekClient.analyze_groups", return_value=mock_llm),
        ):
            ctx = pipeline.run(dry_run=True)

        assert ctx.groups_summarized == 1
        assert ctx.groups_failed == 1
        assert len(ctx.report_md) > 0

    def test_no_messages_generates_empty_report(self, tmp_path):
        import yaml

        wx_dir = _setup_wechat_files(tmp_path)
        config_path = tmp_path / "settings.yaml"
        config_path.write_text(yaml.dump(_make_mock_config(str(wx_dir))), encoding="utf-8")
        pipeline = MiruPipeline(str(config_path))

        mock_proc = MagicMock(found=True, pid=12345, version_raw="4.0.3.29")
        mock_dd = MagicMock(found=True, path=str(wx_dir))
        mock_group = _make_mock_group("测试群")
        mock_result = _make_mock_decrypt_result(tmp_path)
        mock_reader = _make_mock_reader([mock_group], [])  # 无消息

        with (
            patch("miru.collector.diagnostics.detect_wechat_process", return_value=mock_proc),
            patch("miru.collector.diagnostics.find_wechat_data_dir", return_value=mock_dd),
            patch("miru.collector.wechat_db_decrypt.extract_keys_from_process", return_value=[]),
            patch("miru.collector.wechat_db_decrypt.try_decrypt_wechat_db", return_value=mock_result),
            patch("miru.collector.wechat_reader.WeChatDBReader", return_value=mock_reader),
        ):
            ctx = pipeline.run(dry_run=True)

        assert ctx.raw_messages_count == 0
        assert ctx.warnings
