"""
Miru Assistant — Chat Analyzer 统计器单元测试 (Phase 3)。

测试覆盖:
    - parse_chat_file 消息解析
    - compute_statistics 各统计指标
    - ChatStatistics.analyze() 完整流程
    - 空聊天记录处理

不依赖真实微信环境 — 全部使用模拟 chat.txt。
"""

import json
from datetime import datetime
from pathlib import Path

from miru.chat_analyzer.models import StatisticsResult
from miru.chat_analyzer.statistics import (
    ChatMessageRecord,
    ChatStatistics,
    _parse_header,
    compute_statistics,
    parse_chat_file,
)

# ============================================================
# Test Data
# ============================================================


def _sample_chat_text() -> str:
    """模拟一份 6 条消息的 chat.txt。"""
    return """============================================================
联系人：张三
导出时间：2026-08-08 10:00:00
消息数量：6
============================================================


[2026-07-01 10:00] 我：
今天考试怎么样？


[2026-07-01 10:02] 张三：
还可以 你呢


[2026-07-02 09:30] 我：
明天有空吗 一起吃饭


[2026-07-02 09:35] 张三：
有空的 好的


[2026-07-03 20:00] 张三：
那家餐厅不错


[2026-07-03 20:05] 我：
那下次一起去
"""


def _make_records() -> list[ChatMessageRecord]:
    """构造结构化消息（对应 _sample_chat_text 的 6 条消息）。"""
    return [
        ChatMessageRecord(
            timestamp=datetime(2026, 7, 1, 10, 0),
            sender="我",
            content="今天考试怎么样？",
            is_self=True,
        ),
        ChatMessageRecord(
            timestamp=datetime(2026, 7, 1, 10, 2),
            sender="张三",
            content="还可以 你呢",
            is_self=False,
        ),
        ChatMessageRecord(
            timestamp=datetime(2026, 7, 2, 9, 30),
            sender="我",
            content="明天有空吗 一起吃饭",
            is_self=True,
        ),
        ChatMessageRecord(
            timestamp=datetime(2026, 7, 2, 9, 35),
            sender="张三",
            content="有空的 好的",
            is_self=False,
        ),
        ChatMessageRecord(
            timestamp=datetime(2026, 7, 3, 20, 0),
            sender="张三",
            content="那家餐厅不错",
            is_self=False,
        ),
        ChatMessageRecord(
            timestamp=datetime(2026, 7, 3, 20, 5),
            sender="我",
            content="那下次一起去",
            is_self=True,
        ),
    ]


# ============================================================
# Test: parse_chat_file
# ============================================================


class TestParseChatFile:
    """chat.txt 消息解析。"""

    def test_parse_basic(self):
        """基本解析。"""
        records = parse_chat_file(_sample_chat_text())
        assert len(records) == 6
        assert records[0].sender == "我"
        assert records[0].is_self is True
        assert records[0].content == "今天考试怎么样？"
        assert records[1].is_self is False
        assert records[1].sender == "张三"

    def test_parse_timestamps(self):
        """时间戳正确。"""
        records = parse_chat_file(_sample_chat_text())
        assert records[0].timestamp == datetime(2026, 7, 1, 10, 0)
        assert records[-1].timestamp == datetime(2026, 7, 3, 20, 5)

    def test_parse_multiline_content(self):
        """多行内容合并。"""
        text = """[2026-07-01 10:00] 我：
第一行
第二行


[2026-07-01 10:05] 张三：
回复
"""
        records = parse_chat_file(text)
        assert len(records) == 2
        assert records[0].content == "第一行 第二行"

    def test_parse_empty(self):
        """空聊天记录。"""
        text = """============================================================
联系人：张三
消息数量：0
============================================================
"""
        records = parse_chat_file(text)
        assert records == []

    def test_parse_invalid_header(self):
        """无效头部被跳过。"""
        text = """[not-a-date] 我：
内容

[2026-07-01 10:05] 张三：
有效
"""
        records = parse_chat_file(text)
        assert len(records) == 1
        assert records[0].sender == "张三"


# ============================================================
# Test: _parse_header
# ============================================================


class TestParseHeader:
    """消息头部解析。"""

    def test_self_header(self):
        """ "我" 头部。"""
        result = _parse_header("[2026-07-01 10:00] 我：")
        assert result is not None
        ts, sender, is_self = result
        assert ts == datetime(2026, 7, 1, 10, 0)
        assert sender == "我"
        assert is_self is True

    def test_contact_header(self):
        """联系人头部。"""
        result = _parse_header("[2026-07-01 10:00] 张三：")
        assert result is not None
        ts, sender, is_self = result
        assert sender == "张三"
        assert is_self is False

    def test_invalid_header(self):
        """无效头部返回 None。"""
        assert _parse_header("这不是头部") is None
        assert _parse_header("[2026-07-01] 张三：") is None  # 缺分钟


# ============================================================
# Test: compute_statistics
# ============================================================


class TestComputeStatistics:
    """统计指标计算。"""

    def test_basic_counts(self):
        """消息总数和发送者分布。"""
        stats = compute_statistics(_make_records())
        assert stats["total_messages"] == 6
        assert stats["sent_by_me"] == 3
        assert stats["sent_by_them"] == 3

    def test_period(self):
        """时间段。"""
        stats = compute_statistics(_make_records())
        assert stats["period"] == {"start": "2026-07-01", "end": "2026-07-03"}

    def test_messages_by_day(self):
        """每日消息数。"""
        stats = compute_statistics(_make_records())
        assert stats["messages_by_day"] == {
            "2026-07-01": 2,
            "2026-07-02": 2,
            "2026-07-03": 2,
        }

    def test_messages_by_hour(self):
        """每小时消息数。"""
        stats = compute_statistics(_make_records())
        assert stats["messages_by_hour"] == {"9": 2, "10": 2, "20": 2}

    def test_message_length(self):
        """消息长度。"""
        stats = compute_statistics(_make_records())
        assert stats["message_length"]["max_chars"] == len("明天有空吗 一起吃饭")
        assert stats["message_length"]["avg_chars"] > 0

    def test_response_times(self):
        """响应时间（相邻异发送者消息间隔）。"""
        stats = compute_statistics(_make_records())
        response = stats["response_times"]
        # 4 个异发送者相邻对（均 < 24h，全部计入）:
        #   10:00→10:02 (120s), 07-01 10:02→07-02 09:30 (84480s),
        #   09:30→09:35 (300s), 20:00→20:05 (300s)
        assert response["count"] == 4
        assert response["avg_seconds"] == 21300
        assert response["median_seconds"] == 300

    def test_response_time_filtered(self):
        """超过 24 小时的间隔不计入响应时间。"""
        records = [
            ChatMessageRecord(
                timestamp=datetime(2026, 7, 1, 10, 0),
                sender="我",
                content="a",
                is_self=True,
            ),
            ChatMessageRecord(
                timestamp=datetime(2026, 7, 3, 10, 0),
                sender="张三",
                content="b",
                is_self=False,  # 间隔 48h
            ),
        ]
        stats = compute_statistics(records)
        assert stats["response_times"]["count"] == 0

    def test_initiation(self):
        """发起对话比例。"""
        stats = compute_statistics(_make_records())
        # 每天第一条: 07-01 我, 07-02 我, 07-03 张三
        assert stats["initiation"] == {"me_days": 2, "them_days": 1}

    def test_top_words(self):
        """高频词。"""
        stats = compute_statistics(_make_records())
        words = stats["top_words"]
        assert len(words) > 0
        # "好的" 出现 1 次 (停用词在 STOP_WORDS 中 — 确认被过滤)
        word_list = [w["word"] for w in words]
        assert "好的" not in word_list
        # 有效词应该出现
        assert all(w["count"] >= 1 for w in words)

    def test_weekday_distribution(self):
        """星期分布。"""
        stats = compute_statistics(_make_records())
        # 2026-07-01 是周三 (weekday=2), 07-02 周四 (3), 07-03 周五 (4)
        assert stats["messages_by_weekday"] == {"2": 2, "3": 2, "4": 2}


# ============================================================
# Test: ChatStatistics.analyze()
# ============================================================


class TestChatStatisticsAnalyze:
    """ChatStatistics 完整流程。"""

    def test_analyze_success(self, tmp_path):
        """成功路径 — 生成 statistics.json。"""
        chat_file = tmp_path / "chat.txt"
        chat_file.write_text(_sample_chat_text(), encoding="utf-8")

        stats = ChatStatistics()
        result = stats.analyze(
            contact_name="张三",
            chat_file=chat_file,
            output_dir=tmp_path / "out",
        )

        assert result.success is True
        assert result.total_messages == 6

        stats_file = Path(result.statistics_file)
        assert stats_file.exists()
        data = json.loads(stats_file.read_text(encoding="utf-8"))
        assert data["total_messages"] == 6
        assert data["period"]["start"] == "2026-07-01"
        assert "messages_by_day" in data
        assert "top_words" in data

    def test_analyze_missing_file(self, tmp_path):
        """聊天记录文件不存在。"""
        stats = ChatStatistics()
        result = stats.analyze(
            contact_name="张三",
            chat_file=tmp_path / "nonexistent.txt",
        )
        assert result.success is False
        assert "不存在" in result.errors[0]

    def test_analyze_empty_chat(self, tmp_path):
        """空聊天记录。"""
        chat_file = tmp_path / "empty.txt"
        chat_file.write_text(
            "============================================================\n"
            "联系人：张三\n"
            "消息数量：0\n"
            "============================================================\n",
            encoding="utf-8",
        )
        stats = ChatStatistics()
        result = stats.analyze(contact_name="张三", chat_file=chat_file)
        assert result.success is False
        assert "为空" in result.errors[0]

    def test_statistics_result_model(self):
        """StatisticsResult 模型。"""
        result = StatisticsResult(contact_name="张三")
        assert result.success is True
        result.errors.append("err")
        assert result.success is False
