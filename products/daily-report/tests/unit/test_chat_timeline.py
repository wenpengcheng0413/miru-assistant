"""
Miru Assistant — Chat Analyzer 时间线单元测试 (Phase 4)。

测试覆盖:
    - 空聊天记录
    - 单日消息
    - 多天聊天
    - 连续消息 session 合并
    - 时间排序
    - 关键词提取
    - JSON 输出
    - 参与者去重

不依赖真实微信环境 — 全部使用模拟 chat.txt。
"""

import json
from datetime import datetime
from pathlib import Path

from miru.chat_analyzer.models import TimelineEvent, TimelineResult
from miru.chat_analyzer.statistics import ChatMessageRecord
from miru.chat_analyzer.timeline import (
    TimelineAnalyzer,
    build_timeline_events,
    merge_sessions,
)

# ============================================================
# Test Data
# ============================================================


def _make_record(
    ts: str,
    sender: str,
    content: str,
) -> ChatMessageRecord:
    """构造一条消息记录。"""
    return ChatMessageRecord(
        timestamp=datetime.strptime(ts, "%Y-%m-%d %H:%M"),
        sender=sender,
        content=content,
        is_self=sender == "我",
    )


def _write_chat_file(tmp_path: Path, content: str) -> Path:
    """写入模拟 chat.txt 并返回路径。"""
    chat_file = tmp_path / "chat.txt"
    chat_file.write_text(content, encoding="utf-8")
    return chat_file


def _sample_chat_text() -> str:
    """模拟多天聊天记录（含连续与分散消息）。"""
    return """============================================================
联系人：张三
导出时间：2026-08-08 10:00:00
消息数量：8
============================================================


[2026-07-01 10:00] 我：
今天考试怎么样


[2026-07-01 10:02] 张三：
还可以


[2026-07-01 10:30] 我：
那作业呢


[2026-07-02 09:30] 我：
明天有空吗


[2026-07-02 09:35] 张三：
有空的


[2026-07-02 09:40] 我：
那一起吃饭吧


[2026-07-03 20:00] 张三：
餐厅不错


[2026-07-03 20:05] 我：
下次再去
"""


# ============================================================
# Test: merge_sessions
# ============================================================


class TestMergeSessions:
    """session 合并。"""

    def test_single_session(self):
        """10 分钟内连续消息 → 1 个 session。"""
        messages = [
            _make_record("2026-07-01 10:00", "我", "a"),
            _make_record("2026-07-01 10:02", "张三", "b"),
            _make_record("2026-07-01 10:05", "我", "c"),
        ]
        sessions = merge_sessions(messages)
        assert len(sessions) == 1
        assert len(sessions[0]) == 3

    def test_split_by_gap(self):
        """间隔超过 10 分钟 → 分开。"""
        messages = [
            _make_record("2026-07-01 10:00", "我", "a"),
            _make_record("2026-07-01 10:02", "张三", "b"),
            _make_record("2026-07-01 10:20", "我", "c"),  # 间隔 18 分钟
        ]
        sessions = merge_sessions(messages)
        assert len(sessions) == 2
        assert len(sessions[0]) == 2
        assert len(sessions[1]) == 1

    def test_custom_gap(self):
        """自定义阈值。"""
        messages = [
            _make_record("2026-07-01 10:00", "我", "a"),
            _make_record("2026-07-01 10:15", "张三", "b"),
        ]
        # 默认阈值 600s → 15 分钟 > 10 分钟 → 分开
        sessions = merge_sessions(messages)
        assert len(sessions) == 2
        # 自定义阈值 1200s → 合并
        sessions = merge_sessions(messages, gap_seconds=1200)
        assert len(sessions) == 1

    def test_empty(self):
        """空消息列表。"""
        assert merge_sessions([]) == []


# ============================================================
# Test: build_timeline_events
# ============================================================


class TestBuildTimelineEvents:
    """事件构建。"""

    def test_event_fields(self):
        """事件字段正确。"""
        sessions = merge_sessions(
            [
                _make_record("2026-07-01 10:00", "我", "今天考试怎么样"),
                _make_record("2026-07-01 10:02", "张三", "还可以"),
            ]
        )
        events = build_timeline_events(sessions)
        assert len(events) == 1
        event = events[0]
        assert event.date == "2026-07-01"
        assert event.start_time == "10:00"
        assert event.end_time == "10:02"
        assert event.message_count == 2
        assert event.participants == ["我", "张三"]

    def test_time_sorting(self):
        """已排序消息 → 事件按时间排序。"""
        messages = [
            _make_record("2026-07-01 10:00", "我", "第一天的"),
            _make_record("2026-07-02 09:30", "我", "第二天的"),
            _make_record("2026-07-03 20:00", "张三", "第三天的"),
        ]
        sessions = merge_sessions(messages)
        events = build_timeline_events(sessions)
        assert [e.date for e in events] == ["2026-07-01", "2026-07-02", "2026-07-03"]

    def test_participants_dedup(self):
        """参与者去重。"""
        sessions = [
            [
                _make_record("2026-07-01 10:00", "我", "a"),
                _make_record("2026-07-01 10:01", "我", "b"),
                _make_record("2026-07-01 10:02", "张三", "c"),
                _make_record("2026-07-01 10:03", "我", "d"),
            ]
        ]
        events = build_timeline_events(sessions)
        assert events[0].participants == ["我", "张三"]

    def test_keywords_extraction(self):
        """关键词提取（停用词过滤）。"""
        sessions = [
            [
                _make_record("2026-07-01 10:00", "我", "暑假计划去爬山"),
                _make_record("2026-07-01 10:01", "张三", "爬山不错"),
                _make_record("2026-07-01 10:02", "我", "那就爬山"),
            ]
        ]
        events = build_timeline_events(sessions)
        keywords = events[0].keywords
        # 无分词依赖: 中文短语作为 token（按标点/空格分割）
        assert len(keywords) > 0
        assert keywords[0] in ("暑假计划去爬山", "爬山不错", "那就爬山")
        # 停用词被过滤（纯停用词不会出现）
        assert "的" not in keywords

    def test_summary_with_keywords(self):
        """摘要包含关键词。"""
        sessions = [
            [
                _make_record("2026-07-01 10:00", "我", "暑假计划去爬山"),
                _make_record("2026-07-01 10:01", "张三", "爬山不错"),
            ]
        ]
        events = build_timeline_events(sessions)
        assert "爬山" in events[0].summary

    def test_empty_sessions(self):
        """空 session 列表。"""
        assert build_timeline_events([]) == []


# ============================================================
# Test: TimelineAnalyzer.analyze()
# ============================================================


class TestTimelineAnalyzer:
    """TimelineAnalyzer 完整流程。"""

    def test_analyze_success(self, tmp_path):
        """成功路径 — 生成 timeline.json。"""
        chat_file = _write_chat_file(tmp_path, _sample_chat_text())

        timeline = TimelineAnalyzer()
        result = timeline.analyze(
            contact_name="张三",
            chat_file=chat_file,
            output_dir=tmp_path / "out",
        )

        assert result.success is True
        assert result.total_events == 4  # 07-01×2 + 07-02×1 + 07-03×1

        tl_file = Path(result.timeline_file)
        assert tl_file.exists()
        data = json.loads(tl_file.read_text(encoding="utf-8"))
        assert data["contact"] == "张三"
        assert data["period"] == {"start": "2026-07-01", "end": "2026-07-03"}
        assert data["total_events"] == 4

        # 事件字段验证
        events = data["events"]
        assert len(events) == 4
        first = events[0]
        assert first["date"] == "2026-07-01"
        assert first["type"] == "topic"
        # 07-01: 10:00→10:02 合并 (120s < 600s), 10:02→10:30 分开 (28min > 600s)
        # → 两个事件: (10:00,10:02) 2 条 和 (10:30) 1 条
        assert first["messages"] == 2
        assert first["start_time"] == "10:00"
        assert first["end_time"] == "10:02"

    def test_analyze_single_day(self, tmp_path):
        """单日消息。"""
        content = """============================================================
联系人：张三
消息数量：2
============================================================


[2026-07-01 10:00] 我：
你好


[2026-07-01 10:05] 张三：
你好呀
"""
        chat_file = _write_chat_file(tmp_path, content)
        timeline = TimelineAnalyzer()
        result = timeline.analyze(contact_name="张三", chat_file=chat_file)

        assert result.success is True
        assert result.total_events == 1
        assert result.events[0].date == "2026-07-01"

    def test_analyze_multiple_days(self, tmp_path):
        """多天聊天。"""
        chat_file = _write_chat_file(tmp_path, _sample_chat_text())
        timeline = TimelineAnalyzer()
        result = timeline.analyze(contact_name="张三", chat_file=chat_file)

        dates = [e.date for e in result.events]
        assert dates == sorted(dates)
        assert len(set(dates)) == 3  # 3 天

    def test_analyze_empty_chat(self, tmp_path):
        """空聊天记录。"""
        chat_file = _write_chat_file(
            tmp_path,
            "============================================================\n"
            "联系人：张三\n"
            "消息数量：0\n"
            "============================================================\n",
        )
        timeline = TimelineAnalyzer()
        result = timeline.analyze(contact_name="张三", chat_file=chat_file)

        assert result.success is False
        assert "为空" in result.errors[0]

    def test_analyze_missing_file(self, tmp_path):
        """文件不存在。"""
        timeline = TimelineAnalyzer()
        result = timeline.analyze(
            contact_name="张三",
            chat_file=tmp_path / "nonexistent.txt",
        )
        assert result.success is False
        assert "不存在" in result.errors[0]


# ============================================================
# Test: Models
# ============================================================


class TestModels:
    """Timeline 模型。"""

    def test_timeline_event(self):
        """TimelineEvent dataclass。"""
        event = TimelineEvent(
            date="2026-07-01",
            start_time="10:00",
            end_time="10:02",
            message_count=2,
            participants=["我", "张三"],
            keywords=["爬山"],
            summary="围绕「爬山」的对话",
        )
        assert event.date == "2026-07-01"
        assert event.message_count == 2

    def test_timeline_result(self):
        """TimelineResult dataclass。"""
        result = TimelineResult(contact_name="张三")
        assert result.success is True
        result.errors.append("err")
        assert result.success is False
