"""
Miru Assistant — LLM 层单元测试 (Task 7)。

测试覆盖:
    - Pydantic Schema 序列化/反序列化
    - Prompt 模板渲染
    - DeepSeekClient 配置初始化
    - API 响应解析 (mock)
    - 重试逻辑 (mock)
    - Token 统计
    - 错误处理
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from miru.llm.client import DeepSeekClient
from miru.llm.schemas import (
    Deadline,
    FileItem,
    GroupAnalysis,
    LLMCallResult,
    Notice,
    TokenUsage,
    UrgentTask,
)


# ============================================================
# Test: Schemas
# ============================================================


class TestSchemas:
    """Pydantic Schema 测试。"""

    def test_group_analysis_minimal(self):
        """最小有效 JSON。"""
        data = {
            "group_name": "测试群",
            "total_messages": 10,
            "valid_messages": 3,
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "今日无重要信息",
            "ignored_topics": "闲聊",
        }
        ga = GroupAnalysis(**data)
        assert ga.group_name == "测试群"
        assert ga.summary == "今日无重要信息"

    def test_group_analysis_full(self):
        """包含所有字段的完整 JSON。"""
        data = {
            "group_name": "班群",
            "total_messages": 50,
            "valid_messages": 5,
            "urgent_tasks": [
                {
                    "content": "完成实验报告",
                    "source_group": "班群",
                    "source_sender": "助教",
                    "deadline": "2026-07-28",
                }
            ],
            "deadlines": [
                {
                    "content": "环境工程考试",
                    "date": "2026-08-15",
                    "source_group": "课程群",
                    "source_sender": "老师",
                }
            ],
            "notices": [
                {
                    "content": "明天调课",
                    "source_group": "班群",
                    "source_sender": "班主任",
                }
            ],
            "files": [
                {
                    "content": "课件PDF",
                    "source_group": "课程群",
                    "source_sender": "老师",
                }
            ],
            "summary": "有作业和考试安排需要关注",
            "ignored_topics": "日常闲聊、表情包",
        }
        ga = GroupAnalysis(**data)
        assert len(ga.urgent_tasks) == 1
        assert ga.urgent_tasks[0].deadline == "2026-07-28"
        assert len(ga.deadlines) == 1
        assert len(ga.notices) == 1
        assert len(ga.files) == 1

    def test_group_analysis_empty_lists(self):
        """空数组可以正确反序列化。"""
        data = {
            "group_name": "空群",
            "total_messages": 0,
            "valid_messages": 0,
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "",
            "ignored_topics": "",
        }
        ga = GroupAnalysis(**data)
        assert ga.total_messages == 0

    def test_token_usage_defaults(self):
        tu = TokenUsage()
        assert tu.prompt_tokens == 0
        assert tu.total_tokens == 0

    def test_llm_call_result_defaults(self):
        r = LLMCallResult()
        assert r.success is False
        assert r.group_name == ""

    def test_invalid_type_raises(self):
        """字段类型错误时抛出 ValidationError。"""
        with pytest.raises(ValidationError):
            GroupAnalysis.model_validate({
                "group_name": "test",
                "total_messages": "not_a_number",  # 应该是 int
                "valid_messages": 0,
                "urgent_tasks": [],
                "deadlines": [],
                "notices": [],
                "files": [],
                "summary": "",
                "ignored_topics": "",
            })

    def test_urgent_task_null_deadline(self):
        """deadline 可以为 None。"""
        task = UrgentTask(
            content="测试",
            source_group="群",
            source_sender="人",
            deadline=None,
        )
        assert task.deadline is None


# ============================================================
# Test: Prompt Rendering
# ============================================================


class TestPromptRendering:
    """Prompt 模板渲染。"""

    def test_render_system_prompt(self):
        client = DeepSeekClient(api_key="test-key")
        sp = client.render_system_prompt()
        assert "个人学习助手" in sp
        assert len(sp) > 50

    def test_render_user_prompt(self):
        client = DeepSeekClient(api_key="test-key")
        msgs = "[09:30] 老师: 明天考试\n[09:31] 学生: 收到"
        up = client.render_user_prompt("班群", "2026-07-24", msgs)
        assert "班群" in up
        assert "2026-07-24" in up
        assert "明天考试" in up
        assert "[09:30]" in up

    def test_render_prompt_with_empty_messages(self):
        client = DeepSeekClient(api_key="test-key")
        up = client.render_user_prompt("空群", "2026-07-24", "")
        assert "空群" in up


# ============================================================
# Test: Client Configuration
# ============================================================


class TestClientConfig:
    """客户端配置。"""

    def test_default_values(self):
        client = DeepSeekClient(api_key="sk-test")
        assert client.model == "deepseek-v4-flash"
        assert client.temperature == 0.3
        assert client.max_tokens == 4096
        assert client.timeout == 60
        assert client.max_retries == 2

    def test_custom_values(self):
        client = DeepSeekClient(
            api_key="sk-custom",
            model="deepseek-v4-pro",
            temperature=0.5,
            max_tokens=1024,
            timeout=30,
            max_retries=1,
            retry_delays=[1],
        )
        assert client.model == "deepseek-v4-pro"
        assert client.temperature == 0.5
        assert client.max_retries == 1


# ============================================================
# Test: API Call (Mock)
# ============================================================


class TestAPICall:
    """API 调用测试 (mock OpenAI SDK)。"""

    def _make_mock_response(self, content_dict: dict):
        """创建模拟的 OpenAI API 响应。"""
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(content_dict, ensure_ascii=False)
        mock_resp.choices = [mock_choice]
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 500
        mock_usage.completion_tokens = 200
        mock_usage.total_tokens = 700
        mock_resp.usage = mock_usage
        return mock_resp

    def test_successful_call(self):
        """成功调用返回结构化结果。"""
        client = DeepSeekClient(api_key="sk-test")

        mock_resp = self._make_mock_response({
            "group_name": "测试群",
            "total_messages": 10,
            "valid_messages": 3,
            "urgent_tasks": [
                {
                    "content": "交报告",
                    "source_group": "测试群",
                    "source_sender": "老师",
                    "deadline": "2026-07-30",
                }
            ],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "有报告要交",
            "ignored_topics": "闲聊",
        })

        with patch.object(client._client.chat.completions, "create", return_value=mock_resp):
            result = client.analyze_group("测试群", "测试消息", "2026-07-24")

        assert result.success is True
        assert result.analysis is not None
        assert result.analysis.group_name == "测试群"
        assert len(result.analysis.urgent_tasks) == 1
        assert result.analysis.urgent_tasks[0].content == "交报告"
        assert result.usage.prompt_tokens == 500
        assert result.usage.completion_tokens == 200
        assert result.duration_ms >= 0  # mock 调用可能瞬间完成

    def test_token_stats_accumulate(self):
        """Token 统计累加。"""
        client = DeepSeekClient(api_key="sk-test")

        mock_resp = self._make_mock_response({
            "group_name": "群1",
            "total_messages": 5,
            "valid_messages": 1,
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "无",
            "ignored_topics": "",
        })

        with patch.object(client._client.chat.completions, "create", return_value=mock_resp):
            client.analyze_group("群1", "msg1")
            client.analyze_group("群2", "msg2")

        assert client.total_successful_calls == 2
        assert client.total_prompt_tokens == 1000
        assert client.total_completion_tokens == 400
        assert client.total_tokens == 1400

    def test_reset_stats(self):
        """统计重置。"""
        client = DeepSeekClient(api_key="sk-test")
        client.total_successful_calls = 10
        client.reset_stats()
        assert client.total_successful_calls == 0

    def test_retry_on_json_error(self):
        """JSON 解析失败时重试。"""
        client = DeepSeekClient(api_key="sk-test", max_retries=2, retry_delays=[0.01, 0.01])

        bad_resp = MagicMock()
        bad_choice = MagicMock()
        bad_choice.message.content = "not valid json {{{"
        bad_resp.choices = [bad_choice]
        bad_resp.usage = None

        good_resp = self._make_mock_response({
            "group_name": "群",
            "total_messages": 1,
            "valid_messages": 1,
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "ok",
            "ignored_topics": "",
        })

        with patch.object(
            client._client.chat.completions, "create",
            side_effect=[bad_resp, good_resp],
        ):
            result = client.analyze_group("群", "msg")

        assert result.success is True
        assert result.retry_count == 1

    def test_all_retries_exhausted(self):
        """所有重试失败。"""
        client = DeepSeekClient(api_key="sk-test", max_retries=1, retry_delays=[0.01])

        bad_resp = MagicMock()
        bad_choice = MagicMock()
        bad_choice.message.content = "bad json"
        bad_resp.choices = [bad_choice]
        bad_resp.usage = None

        with patch.object(
            client._client.chat.completions, "create",
            side_effect=[bad_resp, bad_resp],
        ):
            result = client.analyze_group("群", "msg")

        assert result.success is False
        assert result.retry_count == 1
        assert "重试" in result.error

    def test_network_error_retry(self):
        """网络错误可重试。"""
        client = DeepSeekClient(api_key="sk-test", max_retries=1, retry_delays=[0.01])

        good_resp = self._make_mock_response({
            "group_name": "群",
            "total_messages": 1,
            "valid_messages": 1,
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "ok",
            "ignored_topics": "",
        })

        with patch.object(
            client._client.chat.completions, "create",
            side_effect=[Exception("Connection timeout"), good_resp],
        ):
            result = client.analyze_group("群", "msg")

        assert result.success is True
        assert result.retry_count == 1

    def test_non_retryable_error(self):
        """不可重试的错误立即返回（如 invalid API key）。"""
        client = DeepSeekClient(api_key="sk-invalid", max_retries=2, retry_delays=[0.01, 0.01])

        with patch.object(
            client._client.chat.completions, "create",
            side_effect=Exception("401 Unauthorized: Invalid API key"),
        ):
            result = client.analyze_group("群", "msg")

        assert result.success is False
        assert result.retry_count == 0  # 不应重试


# ============================================================
# Test: Multiple Groups
# ============================================================


class TestMultiGroup:
    """多群分析。"""

    def test_analyze_groups(self):
        """批量分析多个群。"""
        client = DeepSeekClient(api_key="sk-test")

        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "group_name": "test",
            "total_messages": 1,
            "valid_messages": 1,
            "urgent_tasks": [],
            "deadlines": [],
            "notices": [],
            "files": [],
            "summary": "ok",
            "ignored_topics": "",
        })
        mock_resp.choices = [mock_choice]
        mock_resp.usage = None

        contexts = {"群A": "msgA", "群B": "msgB", "群C": "msgC"}

        with patch.object(client._client.chat.completions, "create", return_value=mock_resp):
            results = client.analyze_groups(contexts, "2026-07-24")

        assert len(results) == 3
        assert all(r.success for r in results)
