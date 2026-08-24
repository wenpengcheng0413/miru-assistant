"""
Miru Assistant — Chat Analyzer 分析器单元测试 (Phase 2)。

测试覆盖:
    - ChatAnalysis schema 解析
    - DeepSeekClient.analyze_chat() 成功路径 (mock OpenAI client)
    - DeepSeekClient.analyze_chat() 失败路径
    - ChatAnalyzer.analyze() 完整流程 (mock DeepSeekClient)
    - 消息提取 extract_messages()
    - 截断 truncate_recent()
    - 空聊天记录处理

不发起真实 API 调用 — 全部使用 mock。
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from miru.chat_analyzer.analyzer import (
    ChatAnalyzer,
    extract_messages,
    truncate_recent,
)
from miru.chat_analyzer.models import AnalysisResult
from miru.llm.client import DeepSeekClient
from miru.llm.schemas import ChatAnalysis, ChatAnalysisResult, KeyConversation, TokenUsage

# ============================================================
# Helpers
# ============================================================


def _sample_analysis_json(contact_name: str = "张三") -> str:
    """构造一个合法的 ChatAnalysis JSON 响应。"""
    return json.dumps(
        {
            "contact_name": contact_name,
            "total_messages_analyzed": 10,
            "period_start": "2026-07-01",
            "period_end": "2026-07-10",
            "communication_style": "日常亲切，回复简短",
            "main_topics": ["日常问候", "生活安排"],
            "emotional_tone": "轻松友好",
            "relationship_insights": "亲密关系，日常联络频繁",
            "key_conversations": [
                {"date": "2026-07-05", "summary": "讨论周末安排"},
            ],
            "overall_summary": "整体沟通顺畅，关系稳定。",
        },
        ensure_ascii=False,
    )


def _mock_openai_response(content: str, finish: str = "stop") -> MagicMock:
    """构造模拟 OpenAI 响应对象。"""
    mock_response = MagicMock()
    choice = MagicMock()
    choice.finish_reason = finish
    choice.message.content = content
    mock_response.choices = [choice]
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    mock_response.usage.total_tokens = 150
    return mock_response


def _make_chat_file(tmp_path: Path, content: str | None = None) -> Path:
    """创建模拟 chat.txt 文件。"""
    if content is None:
        content = """============================================================
联系人：张三
导出时间：2026-08-08 10:00:00
消息数量：4
============================================================


[2026-07-01 10:00] 我：
今天考试怎么样？


[2026-07-01 10:05] 张三：
还可以


[2026-07-02 09:30] 我：
明天有空吗？


[2026-07-02 09:35] 张三：
有空的
"""
    chat_file = tmp_path / "chat.txt"
    chat_file.write_text(content, encoding="utf-8")
    return chat_file


# ============================================================
# Test: ChatAnalysis Schema
# ============================================================


class TestChatAnalysisSchema:
    """ChatAnalysis Pydantic 模型。"""

    def test_parse_valid(self):
        """合法 JSON 解析为模型。"""
        data = json.loads(_sample_analysis_json())
        analysis = ChatAnalysis(**data)
        assert analysis.contact_name == "张三"
        assert analysis.total_messages_analyzed == 10
        assert len(analysis.main_topics) == 2
        assert analysis.key_conversations[0].date == "2026-07-05"
        assert analysis.overall_summary != ""

    def test_defaults(self):
        """字段默认值。"""
        analysis = ChatAnalysis(contact_name="李四")
        assert analysis.main_topics == []
        assert analysis.key_conversations == []
        assert analysis.communication_style == ""

    def test_key_conversation_model(self):
        """KeyConversation 模型。"""
        conv = KeyConversation(date="2026-07-05", summary="周末安排")
        assert conv.date == "2026-07-05"
        assert conv.summary == "周末安排"


# ============================================================
# Test: DeepSeekClient.analyze_chat()
# ============================================================


class TestAnalyzeChat:
    """DeepSeekClient.analyze_chat() 方法。"""

    def test_success_path(self):
        """成功路径 — 返回 ChatAnalysisResult。"""
        client = DeepSeekClient(api_key="test-key", max_retries=1, retry_delays=[0])
        mock_response = _mock_openai_response(_sample_analysis_json())

        with patch.object(client._client.chat.completions, "create") as mock_create:
            mock_create.return_value = mock_response
            result = client.analyze_chat("张三", "[2026-07-01 10:00] 我：你好")

        assert result.success is True
        assert result.analysis is not None
        assert result.analysis.contact_name == "张三"
        assert result.usage.total_tokens == 150
        assert result.duration_ms >= 0

        # 验证请求参数
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == "deepseek-v4-flash"
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        # 检查 prompt 包含联系人
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "聊天记录分析助手" in messages[0]["content"]

    def test_failure_path(self):
        """网络错误 — 返回 error 结果。"""
        client = DeepSeekClient(api_key="test-key", max_retries=1, retry_delays=[0])

        with patch.object(
            client._client.chat.completions, "create", side_effect=Exception("connection error")
        ):
            result = client.analyze_chat("张三", "messages")

        assert result.success is False
        assert "connection" in result.error

    def test_prompt_too_long(self):
        """超长 prompt — 跳过分析。"""
        client = DeepSeekClient(api_key="test-key", max_retries=1, retry_delays=[0])
        long_text = "x" * 30_000

        with patch.object(client._client.chat.completions, "create") as mock_create:
            result = client.analyze_chat("张三", long_text)

        assert result.success is False
        assert "Prompt too long" in result.error
        mock_create.assert_not_called()

    def test_json_parse_failure_retries(self):
        """JSON 解析失败 — 重试后成功。"""
        client = DeepSeekClient(api_key="test-key", max_retries=2, retry_delays=[0, 0])

        responses = [
            _mock_openai_response("这不是JSON内容"),
            _mock_openai_response(_sample_analysis_json()),
        ]
        mock_create = MagicMock(side_effect=responses)

        with patch.object(client._client.chat.completions, "create", mock_create):
            result = client.analyze_chat("张三", "messages")

        assert result.success is True
        assert result.retry_count == 1
        assert mock_create.call_count == 2

    def test_render_chat_prompt(self):
        """Prompt 渲染包含联系人名称和消息。"""
        client = DeepSeekClient(api_key="test-key")
        user_prompt = client.render_chat_user_prompt(
            "张三",
            "[2026-07-01 10:00] 我：你好",
        )
        assert "张三" in user_prompt
        assert "[2026-07-01 10:00] 我：你好" in user_prompt


# ============================================================
# Test: extract_messages
# ============================================================


class TestExtractMessages:
    """chat.txt 消息解析。"""

    def test_extract_basic(self):
        """解析标准格式。"""
        text = """============================================================
联系人：张三
导出时间：2026-08-08
消息数量：2
============================================================


[2026-07-01 10:00] 我：
今天考试怎么样？


[2026-07-01 10:05] 张三：
还可以
"""
        messages_text, count = extract_messages(text)
        assert count == 2
        assert "[2026-07-01 10:00] 我：今天考试怎么样？" in messages_text
        assert "[2026-07-01 10:05] 张三：还可以" in messages_text

    def test_extract_multiline_content(self):
        """多行内容合并为一行。"""
        text = """[2026-07-01 10:00] 我：
第一行
第二行


[2026-07-01 10:05] 张三：
回复
"""
        messages_text, count = extract_messages(text)
        assert count == 2
        assert "我：第一行 第二行" in messages_text

    def test_extract_empty(self):
        """空聊天记录。"""
        text = """============================================================
联系人：张三
消息数量：0
============================================================
"""
        messages_text, count = extract_messages(text)
        assert count == 0
        assert messages_text == ""

    def test_extract_no_content_message(self):
        """有头无内容的消息被跳过。"""
        text = """[2026-07-01 10:00] 我：

[2026-07-01 10:05] 张三：
有内容
"""
        messages_text, count = extract_messages(text)
        assert count == 1
        assert "有内容" in messages_text


# ============================================================
# Test: truncate_recent
# ============================================================


class TestTruncateRecent:
    """长文本截断。"""

    def test_short_text_not_truncated(self):
        """短文本不截断。"""
        text = "\n".join(f"line{i}" for i in range(10))
        result = truncate_recent(text, 10_000)
        assert result == text

    def test_long_text_truncated(self):
        """长文本截断保留最近部分。"""
        lines = [f"msg_{i}_" + "x" * 50 for i in range(100)]
        text = "\n".join(lines)
        result = truncate_recent(text, 300)
        assert len(result) <= 300
        # 保留最新消息
        assert "msg_99_" in result
        # 最早消息被截断
        assert "msg_0_" not in result

    def test_truncation_note_added(self):
        """截断时添加说明。"""
        lines = [f"msg_{i}" for i in range(100)]
        text = "\n".join(lines)
        result = truncate_recent(text, 50)
        assert "已截断" in result


# ============================================================
# Test: ChatAnalyzer.analyze()
# ============================================================


class TestChatAnalyzer:
    """ChatAnalyzer 完整流程 (mock DeepSeekClient)。"""

    def test_analyze_success(self, tmp_path):
        """成功路径 — 生成 analysis.md。"""
        chat_file = _make_chat_file(tmp_path)
        analysis_data = json.loads(_sample_analysis_json())
        mock_analysis = ChatAnalysis(**analysis_data)

        mock_llm_result = ChatAnalysisResult(
            contact_name="张三",
            success=True,
            analysis=mock_analysis,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )

        analyzer = ChatAnalyzer(config_path="config/settings.yaml")
        with patch("miru.chat_analyzer.analyzer.DeepSeekClient") as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.analyze_chat.return_value = mock_llm_result

            result = analyzer.analyze(
                contact_name="张三",
                chat_file=chat_file,
                output_dir=tmp_path / "out",
            )

        assert result.success is True
        assert result.total_messages == 4
        assert result.llm_success is True
        assert result.token_usage["total"] == 150

        analysis_file = Path(result.analysis_file)
        assert analysis_file.exists()
        content = analysis_file.read_text(encoding="utf-8")
        assert "聊天分析报告" in content
        assert "张三" in content
        assert "日常亲切" in content
        assert "周末安排" in content

        # 验证传给 analyze_chat 的消息文本
        sent_text = mock_client.analyze_chat.call_args.args[1]
        assert "今天考试怎么样" in sent_text

    def test_analyze_missing_file(self, tmp_path):
        """聊天记录文件不存在。"""
        analyzer = ChatAnalyzer()
        result = analyzer.analyze(
            contact_name="张三",
            chat_file=tmp_path / "nonexistent.txt",
        )
        assert result.success is False
        assert "不存在" in result.errors[0]

    def test_analyze_empty_chat(self, tmp_path):
        """空聊天记录 — 无法分析。"""
        chat_file = tmp_path / "empty.txt"
        chat_file.write_text(
            "============================================================\n"
            "联系人：张三\n"
            "消息数量：0\n"
            "============================================================\n",
            encoding="utf-8",
        )
        analyzer = ChatAnalyzer()
        with patch("miru.chat_analyzer.analyzer.DeepSeekClient") as mock_client_class:
            result = analyzer.analyze(
                contact_name="张三",
                chat_file=chat_file,
            )
            mock_client_class.assert_not_called()
        assert result.success is False
        assert "为空" in result.errors[0]

    def test_analyze_llm_failure(self, tmp_path):
        """LLM 调用失败。"""
        chat_file = _make_chat_file(tmp_path)
        mock_llm_result = ChatAnalysisResult(contact_name="张三", success=False, error="API down")

        analyzer = ChatAnalyzer()
        with patch("miru.chat_analyzer.analyzer.DeepSeekClient") as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.analyze_chat.return_value = mock_llm_result

            result = analyzer.analyze(contact_name="张三", chat_file=chat_file)

        assert result.success is False
        assert "API down" in result.errors[0]

    def test_analyze_no_api_key(self, tmp_path):
        """API key 未配置 — 抛出 ChatAnalysisError。"""
        chat_file = _make_chat_file(tmp_path)
        analyzer = ChatAnalyzer(config_path="config/nonexistent.yaml")

        with patch("miru.chat_analyzer.analyzer.DeepSeekClient") as mock_client_class:
            # _build_client 返回 None (config 加载失败)
            mock_client_class.side_effect = None
            from miru.chat_analyzer.models import ChatAnalysisError

            with pytest.raises(ChatAnalysisError):
                analyzer.analyze(contact_name="张三", chat_file=chat_file)

    def test_analysis_result_model(self):
        """AnalysisResult 模型。"""
        result = AnalysisResult(contact_name="张三")
        assert result.success is True
        result.errors.append("err")
        assert result.success is False
