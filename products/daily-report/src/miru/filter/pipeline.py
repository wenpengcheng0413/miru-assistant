"""
Miru Assistant — 过滤 Pipeline 编排器。

将各阶段串联:
    去重 → 清洗 → 预分类 → 分组

输出 FilterResult — 可直接用于 LLM 上下文构建。
"""

from collections import Counter

from miru.collector.wechat_reader import WeChatMessage
from miru.filter.cleaner import clean
from miru.filter.classifier import classify_all
from miru.filter.dedup import deduplicate
from miru.filter.group_filter import group_by_group_name
from miru.filter.models import CleanMessage, FilterResult


def process(
    messages: list[WeChatMessage],
    known_ids: set[int] | None = None,
) -> FilterResult:
    """
    执行完整的过滤 Pipeline。

    Args:
        messages: 从 Task 5C 读取的原始 WeChatMessage 列表。
        known_ids: 已知/已处理的 server_id 集合（用于跨运行去重）。

    Returns:
        FilterResult — 包含分组消息和完整统计。
    """
    result = FilterResult()
    result.total_input = len(messages)

    if not messages:
        return result

    # ----------------------------------------------------------
    # Stage 1: 去重
    # ----------------------------------------------------------
    unique, dup_count = deduplicate(messages, known_ids)
    result.removed_duplicates = dup_count

    # ----------------------------------------------------------
    # Stage 2: 清洗
    # ----------------------------------------------------------
    cleaned, clean_stats = clean(unique)
    result.removed_system = clean_stats["system"]
    result.removed_empty = clean_stats["empty"]
    result.removed_non_text = clean_stats["non_text"]
    result.removed_short = clean_stats["short_noise"]

    # ----------------------------------------------------------
    # Stage 3: 预分类
    # ----------------------------------------------------------
    classified = classify_all(cleaned)

    # 分类统计
    cats = Counter(m.category for m in classified)
    result.category_counts = dict(cats)

    # ----------------------------------------------------------
    # Stage 4: 按群分组
    # ----------------------------------------------------------
    result.grouped = group_by_group_name(classified)
    result.total_output = len(classified)

    return result


def build_llm_context(
    grouped: dict[str, list[CleanMessage]],
    date_str: str = "",
) -> dict[str, str]:
    """
    将分组消息转换为 LLM 输入文本。

    每个群生成一段格式化的消息流文本。

    Args:
        grouped: 按群分组后的消息字典。
        date_str: 日期字符串（用于 LLM prompt）。

    Returns:
        {group_name: formatted_text} — 每个群的 LLM 输入文本。
    """
    outputs: dict[str, str] = {}

    for group_name, msgs in grouped.items():
        lines = [f"群名：{group_name}"]
        if date_str:
            lines.append(f"日期：{date_str}")
        lines.append("")
        lines.append("--- 消息记录开始 ---")

        for msg in msgs:
            lines.append(f"[{msg.time_str}] {msg.sender_name}: {msg.content}")

        lines.append("--- 消息记录结束 ---")

        outputs[group_name] = "\n".join(lines)

    return outputs
