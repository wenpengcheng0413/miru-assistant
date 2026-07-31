"""
Miru Assistant — 群消息分组器。

按 group_name 将消息分组到 dict 中。
"""

from miru.filter.models import CleanMessage


def group_by_group_name(
    messages: list[CleanMessage],
) -> dict[str, list[CleanMessage]]:
    """
    按群名分组。

    Args:
        messages: 已清洗+分类的消息列表。

    Returns:
        {group_name: [messages]} 字典。
    """
    grouped: dict[str, list[CleanMessage]] = {}

    for msg in messages:
        key = msg.group_name or "未知群"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(msg)

    return grouped
