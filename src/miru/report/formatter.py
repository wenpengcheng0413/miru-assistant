"""
Miru Assistant — Markdown 格式化工具。

处理内容截断、特殊字符转义、长度限制。
"""

MAX_CONTENT_LENGTH = 200     # 单条内容最大字符数
MAX_REPORT_LENGTH = 10000    # 整篇日报最大字符数 (PushPlus 限制约 10KB)
TRUNCATION_SUFFIX = "..."


def truncate(text: str, max_len: int = MAX_CONTENT_LENGTH) -> str:
    """
    截断过长文本。

    Args:
        text: 原始文本。
        max_len: 最大字符数。

    Returns:
        截断后文本（过长时添加 "..." 后缀）。
    """
    if len(text) <= max_len:
        return text
    return text[:max_len - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


def safe_md(text: str) -> str:
    """
    转义 Markdown 特殊字符。

    Args:
        text: 原始文本。

    Returns:
        转义后的安全文本。
    """
    # 转义可能破坏 Markdown 格式的字符
    chars = ["*", "_", "`", "[", "]"]
    result = text
    for c in chars:
        result = result.replace(c, "\\" + c)
    return result


def truncate_report(full_md: str, max_len: int = MAX_REPORT_LENGTH) -> str:
    """
    截断超长日报，保留精华内容。

    如果完整日报超过 max_len:
        1. 在最后一个完整段落边界截断
        2. 追加提示信息

    Args:
        full_md: 完整 Markdown 日报。
        max_len: 最大长度。

    Returns:
        可能被截断的 Markdown 日报。
    """
    if len(full_md) <= max_len:
        return full_md

    # 在限制前找最后一个完整段落
    truncated = full_md[:max_len - 200]
    last_section = truncated.rfind("\n## ")
    if last_section > 0:
        truncated = truncated[:last_section]

    notice = (
        "\n\n---\n"
        "> ⚠️ 日报内容过长，已截断。完整版请查看本地日志。\n"
    )
    return truncated + notice


def count_chars(text: str) -> int:
    """统计字符数（含中文）。"""
    return len(text)
