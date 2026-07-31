"""
Miru Assistant — 消息清洗器。

过滤规则:
    - 系统消息 (local_type=10000)
    - 空消息/空白消息
    - 非文本消息 (图片/语音/视频/表情)
    - 无意义短消息 ("收到""好的""谢谢" 等)
"""

import re

from miru.collector.wechat_reader import WeChatMessage

# 无意义短回复列表
_SHORT_NOISE = {
    "收到", "好的", "谢谢", "ok", "OK", "Ok",
    "好", "嗯", "哦", "对", "是", "行",
    "1", "2", "3",
    "哈哈", "呵呵", "嘿嘿",
    "。。。", "...", "……",
    "[表情]", "[图片]", "[动画表情]",
}

# 仅表情/URL 的模式
_EMOJI_ONLY = re.compile(r"^[\U0001F300-\U0001F9FF☀-⛿✀-➿]+$")
_URL_ONLY = re.compile(r"^https?://\S+$")


def clean(
    messages: list[WeChatMessage],
) -> tuple[list[WeChatMessage], dict[str, int]]:
    """
    清洗消息列表。

    Args:
        messages: 去重后的消息列表。

    Returns:
        (清洗后消息列表, 各类移除计数)
    """
    cleaned: list[WeChatMessage] = []
    stats = {
        "system": 0,
        "empty": 0,
        "non_text": 0,
        "short_noise": 0,
    }

    for msg in messages:
        # 1. 系统消息
        if msg.is_system:
            stats["system"] += 1
            continue

        # 2. 非文本消息
        if not msg.is_text:
            stats["non_text"] += 1
            continue

        # 3. 空消息/仅空白
        content = msg.content.strip() if msg.content else ""
        if not content or content in ("", "\n", "\r\n"):
            stats["empty"] += 1
            continue

        # 4. 仅表情符号的消息
        if _EMOJI_ONLY.match(content):
            stats["empty"] += 1
            continue

        # 5. 仅 URL（不带任何文字说明）
        if _URL_ONLY.match(content):
            stats["non_text"] += 1
            continue

        # 6. 无意义短回复
        stripped = content.rstrip("。.!！?？~～…")
        if stripped in _SHORT_NOISE or (
            len(stripped) <= 2 and stripped.isascii() and not stripped.isalnum()
        ):
            stats["short_noise"] += 1
            continue

        cleaned.append(msg)

    return cleaned, stats


def is_meaningless_short(content: str) -> bool:
    """检查单条消息是否为无意义短回复。"""
    stripped = content.strip().rstrip("。.!！?？~～…")
    return stripped in _SHORT_NOISE
