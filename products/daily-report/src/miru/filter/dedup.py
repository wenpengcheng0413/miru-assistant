"""
Miru Assistant — 消息去重器。

基于 server_id 去重:
    - 同一次运行内: 内存 set 去重
    - 跨运行: 支持外部提供历史 server_id 集合（兼容 Repository 查询）
"""

from miru.collector.wechat_reader import WeChatMessage


def deduplicate(
    messages: list[WeChatMessage],
    known_ids: set[int] | None = None,
) -> tuple[list[WeChatMessage], int]:
    """
    基于 server_id 去重。

    Args:
        messages: 输入消息列表。
        known_ids: 已知/已处理的 server_id 集合（如从数据库加载）。

    Returns:
        (去重后消息列表, 被移除的重复消息数量)
    """
    if not messages:
        return [], 0

    seen: set[int] = set(known_ids) if known_ids else set()
    unique: list[WeChatMessage] = []
    dup_count = 0

    for msg in messages:
        if msg.server_id and msg.server_id in seen:
            dup_count += 1
            continue
        if msg.server_id:
            seen.add(msg.server_id)
        unique.append(msg)

    return unique, dup_count
