"""
Miru Assistant — 过滤层单元测试 (Task 6)。

测试覆盖:
    - 去重 (server_id)
    - 清洗 (系统消息/空/非文本/短消息)
    - 预分类 (关键词规则)
    - 分组 (按群名)
    - 完整 Pipeline
    - LLM 上下文构建
"""

import time

import pytest

from miru.collector.wechat_reader import WeChatMessage
from miru.filter.cleaner import clean, is_meaningless_short
from miru.filter.classifier import classify_all, classify_message
from miru.filter.dedup import deduplicate
from miru.filter.group_filter import group_by_group_name
from miru.filter.models import CleanMessage, FilterResult
from miru.filter.pipeline import build_llm_context, process


# ============================================================
# Helpers
# ============================================================

def _make_msg(
    server_id: int,
    content: str = "测试消息",
    local_type: int = 1,
    sender_name: str = "张三",
    group_name: str = "测试群",
    create_time: int | None = None,
    is_system: bool = False,
) -> WeChatMessage:
    """创建测试用的 WeChatMessage。"""
    if is_system:
        local_type = 10000
    return WeChatMessage(
        server_id=server_id,
        content=content,
        local_type=local_type,
        sender_name=sender_name,
        group_name=group_name,
        create_time=create_time or int(time.time()),
        time_str="14:30",
        is_text=(local_type == 1),
        is_system=(local_type == 10000),
    )


# ============================================================
# Test: Dedup
# ============================================================


class TestDedup:
    def test_no_duplicates(self):
        msgs = [_make_msg(i, f"消息{i}") for i in range(5)]
        result, removed = deduplicate(msgs)
        assert len(result) == 5
        assert removed == 0

    def test_removes_duplicates(self):
        msgs = [
            _make_msg(1, "A"),
            _make_msg(2, "B"),
            _make_msg(1, "A again"),  # dup
            _make_msg(3, "C"),
            _make_msg(2, "B again"),  # dup
        ]
        result, removed = deduplicate(msgs)
        assert len(result) == 3
        assert removed == 2
        assert result[0].content == "A"
        assert result[1].content == "B"
        assert result[2].content == "C"

    def test_with_known_ids(self):
        msgs = [
            _make_msg(10, "新消息"),
            _make_msg(5, "旧消息"),
        ]
        known = {5, 6, 7}
        result, removed = deduplicate(msgs, known)
        assert len(result) == 1
        assert result[0].server_id == 10
        assert removed == 1

    def test_empty_list(self):
        result, removed = deduplicate([])
        assert result == []
        assert removed == 0

    def test_zero_server_id_kept(self):
        """server_id=0 的消息不被去重（可能是异常数据）。"""
        msgs = [_make_msg(0, "A"), _make_msg(0, "B")]
        result, removed = deduplicate(msgs)
        assert len(result) == 2
        assert removed == 0


# ============================================================
# Test: Cleaner
# ============================================================


class TestCleaner:
    def test_removes_system_messages(self):
        msgs = [
            _make_msg(1, "正常消息"),
            _make_msg(2, "某某加入群聊", is_system=True),
            _make_msg(3, "另一条"),
        ]
        result, stats = clean(msgs)
        assert len(result) == 2
        assert stats["system"] == 1

    def test_removes_non_text(self):
        msgs = [
            _make_msg(1, "文本", local_type=1),
            _make_msg(2, "图片", local_type=3),
            _make_msg(3, "语音", local_type=34),
        ]
        result, stats = clean(msgs)
        assert len(result) == 1
        assert stats["non_text"] == 2

    def test_removes_empty(self):
        msgs = [
            _make_msg(1, "正常"),
            _make_msg(2, ""),
            _make_msg(3, "   "),
            _make_msg(4, "\n"),
        ]
        result, stats = clean(msgs)
        assert len(result) == 1
        assert stats["empty"] == 3

    def test_removes_short_noise(self):
        msgs = [
            _make_msg(1, "重要通知：明天考试"),
            _make_msg(2, "收到"),
            _make_msg(3, "好的"),
            _make_msg(4, "谢谢"),
            _make_msg(5, "ok"),
        ]
        result, stats = clean(msgs)
        assert len(result) == 1
        assert stats["short_noise"] == 4
        assert result[0].content == "重要通知：明天考试"

    def test_is_meaningless_short(self):
        assert is_meaningless_short("收到") is True
        assert is_meaningless_short("好的") is True
        assert is_meaningless_short("明天考试") is False
        assert is_meaningless_short("这是一个重要通知") is False

    def test_removes_emoji_only(self):
        msgs = [
            _make_msg(1, "正常消息"),
            _make_msg(2, "😀😂🤣"),
        ]
        result, stats = clean(msgs)
        assert len(result) == 1


# ============================================================
# Test: Classifier
# ============================================================


class TestClassifier:
    def test_classifies_deadline(self):
        msg = _make_msg(1, "实验报告截止日期是下周五")
        cm = classify_message(msg, "课程群")
        assert cm.category in ("deadline", "作业")
        assert cm.importance == "high"
        assert cm.has_deadline_keyword is True

    def test_classifies_homework(self):
        msg = _make_msg(1, "第三章习题1-5题，下周一交")
        cm = classify_message(msg, "课程群")
        assert cm.category == "作业"
        assert cm.importance == "high"

    def test_classifies_notice_from_teacher(self):
        msg = _make_msg(1, "同学们请注意：明天下午的课调到周五", sender_name="班主任-张老师")
        cm = classify_message(msg, "班群")
        assert cm.category == "通知"
        assert cm.importance == "high"

    def test_classifies_notice_from_student(self):
        msg = _make_msg(1, "提醒大家一下明天有考试", sender_name="普通学生")
        cm = classify_message(msg, "班群")
        assert cm.category == "通知"
        assert cm.importance == "medium"  # 非权威发送者

    def test_classifies_file(self):
        msg = _make_msg(1, "我把课件PDF发群文件了")
        cm = classify_message(msg, "课程群")
        assert cm.category == "文件"
        assert cm.has_file_indicator is True

    def test_classifies_discussion(self):
        msg = _make_msg(1, "有人知道这个题目怎么做吗？")
        cm = classify_message(msg, "AI交流群")
        assert cm.category == "讨论"
        assert cm.importance == "low"

    def test_short_message_flag(self):
        msg = _make_msg(1, "短")
        cm = classify_message(msg, "群")
        assert cm.is_short is True

    def test_batch_classify(self):
        msgs = [
            _make_msg(1, "提交实验报告", sender_name="助教-小李"),
            _make_msg(2, "好的知道了"),
            _make_msg(3, "新论文推荐：GPT-5发布"),
        ]
        results = classify_all(msgs, "测试群")
        assert len(results) == 3
        assert results[0].category == "作业"
        assert results[2].category == "讨论"


# ============================================================
# Test: Group Filter
# ============================================================


class TestGroupFilter:
    def test_groups_by_name(self):
        msgs = [
            CleanMessage(server_id=1, group_name="群A", content="A1"),
            CleanMessage(server_id=2, group_name="群B", content="B1"),
            CleanMessage(server_id=3, group_name="群A", content="A2"),
        ]
        grouped = group_by_group_name(msgs)
        assert len(grouped) == 2
        assert len(grouped["群A"]) == 2
        assert len(grouped["群B"]) == 1

    def test_empty_group_name(self):
        msgs = [CleanMessage(server_id=1, group_name="", content="test")]
        grouped = group_by_group_name(msgs)
        assert "未知群" in grouped

    def test_empty_list(self):
        grouped = group_by_group_name([])
        assert grouped == {}


# ============================================================
# Test: Full Pipeline
# ============================================================


class TestPipeline:
    def test_full_pipeline(self):
        """完整 Pipeline: 去重→清洗→分类→分组。"""
        msgs = [
            _make_msg(1, "明天下午考试", sender_name="老师"),
            _make_msg(2, "收到"),
            _make_msg(3, "第三章作业", sender_name="助教"),
            _make_msg(2, "收到"),               # dup
            _make_msg(4, "", is_system=False),  # empty
            _make_msg(5, "某某加入群聊", is_system=True),
            _make_msg(6, "😀😂"),                # emoji only
            _make_msg(7, "有人知道AI的最新进展吗？"),
            _make_msg(8, "老师通知：下周一交实验报告", sender_name="班主任"),
        ]

        result = process(msgs)

        # 统计
        assert result.total_input == 9
        assert result.removed_duplicates == 1
        assert result.removed_system == 1
        assert result.removed_empty == 2   # empty + emoji
        assert result.removed_short == 1   # "收到"
        assert result.total_output == 4

        # 分组
        assert "测试群" in result.grouped
        assert len(result.grouped["测试群"]) == 4

        # 分类统计
        cats = result.category_counts
        # msg1("考试")=通知, msg3("作业")=作业, msg8("AI")=讨论, msg9("报告+交")=作业
        assert cats.get("通知", 0) >= 1
        assert cats.get("作业", 0) >= 2
        assert cats.get("讨论", 0) >= 1

    def test_pipeline_empty_input(self):
        result = process([])
        assert result.total_input == 0
        assert result.total_output == 0
        assert result.grouped == {}

    def test_pipeline_with_known_ids(self):
        msgs = [
            _make_msg(100, "新消息"),
            _make_msg(200, "另一条"),
        ]
        known = {200}
        result = process(msgs, known_ids=known)
        assert result.total_output == 1
        assert result.removed_duplicates == 1


# ============================================================
# Test: LLM Context Builder
# ============================================================


class TestLLMContext:
    def test_builds_formatted_text(self):
        grouped = {
            "班群": [
                CleanMessage(
                    server_id=1, group_name="班群",
                    sender_name="老师", content="明天考试",
                    time_str="09:30",
                ),
                CleanMessage(
                    server_id=2, group_name="班群",
                    sender_name="学生A", content="收到",
                    time_str="09:31",
                ),
            ],
            "AI群": [
                CleanMessage(
                    server_id=3, group_name="AI群",
                    sender_name="大佬", content="推荐一篇Paper",
                    time_str="15:00",
                ),
            ],
        }

        contexts = build_llm_context(grouped, "2026-07-24")

        assert len(contexts) == 2
        assert "班群" in contexts
        assert "AI群" in contexts
        # 检查格式
        assert "[09:30] 老师: 明天考试" in contexts["班群"]
        assert "[09:31] 学生A: 收到" in contexts["班群"]
        assert "[15:00] 大佬: 推荐一篇Paper" in contexts["AI群"]
        assert "--- 消息记录开始 ---" in contexts["班群"]
        assert "--- 消息记录结束 ---" in contexts["班群"]

    def test_empty_group(self):
        contexts = build_llm_context({})
        assert contexts == {}


# ============================================================
# Test: FilterResult
# ============================================================


class TestFilterResult:
    def test_total_removed(self):
        fr = FilterResult(
            removed_duplicates=2,
            removed_system=1,
            removed_non_text=3,
            removed_short=4,
        )
        assert fr.total_removed == 10

    def test_defaults(self):
        fr = FilterResult()
        assert fr.total_input == 0
        assert fr.total_output == 0
        assert fr.grouped == {}
