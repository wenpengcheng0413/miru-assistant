"""
Miru Assistant — Chat Analyzer 聊天统计器 (Phase 3)。

读取导出的聊天记录 TXT，计算聊天统计指标，输出 statistics.json。

统计指标:
    - 消息总数 / 发送者分布 (我 vs 对方)
    - 每日消息数 / 每小时消息数 / 星期分布
    - 平均消息长度 / 最长消息
    - 响应时间 (对方消息后我的回复耗时)
    - 主动发起对话比例
    - 高频词 (停用词过滤)

不依赖 Daily Report 任何模块。
纯计算 — 只读取 chat.txt，输出 statistics.json。

用法:
    stats = ChatStatistics()
    result = stats.analyze(
        contact_name="张三",
        chat_file="output/张三/chat.txt",
        output_dir="output/张三",
    )
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.models import StatisticsResult

# 常用停用词 (统计高频词时过滤)
STOP_WORDS = {
    "的",
    "了",
    "吗",
    "啊",
    "吧",
    "呢",
    "哦",
    "嗯",
    "是",
    "我",
    "你",
    "在",
    "有",
    "个",
    "就",
    "不",
    "都",
    "也",
    "这",
    "那",
    "好",
    "行",
    "好的",
    "可以",
    "没事",
    "知道",
    "什么",
    "怎么",
    "这样",
    "那样",
    "一下",
    "现在",
    "今天",
    "明天",
    "昨天",
    "咱们",
    "我们",
    "你们",
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "and",
    "or",
    "for",
}

# token 分割: 非中英文数字字符作为分隔符
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9一-鿿]+")


@dataclass
class ChatMessageRecord:
    """解析后的单条消息（统计用）。"""

    timestamp: datetime
    sender: str  # "我" 或对方显示名
    content: str
    is_self: bool


class ChatStatistics:
    """
    聊天统计器。

    流程:
        1. 读取导出聊天记录 (chat.txt)
        2. 解析为结构化消息列表
        3. 计算统计指标
        4. 写入 statistics.json

    用法:
        stats = ChatStatistics()
        result = stats.analyze(
            contact_name="张三",
            chat_file="output/张三/chat.txt",
        )
    """

    # ---- 主入口 ----

    def analyze(
        self,
        contact_name: str,
        chat_file: str | Path,
        output_dir: str | Path = "output",
    ) -> StatisticsResult:
        """
        分析聊天记录并生成 statistics.json。

        Args:
            contact_name: 联系人显示名称。
            chat_file: 导出的聊天记录 TXT 路径。
            output_dir: 输出目录根路径（statistics.json 写入此目录）。

        Returns:
            StatisticsResult — 统计结果（含 statistics.json 路径）。
        """
        result = StatisticsResult(contact_name=contact_name)
        chat_path = Path(chat_file)

        if not chat_path.exists():
            result.errors.append(f"聊天记录文件不存在: {chat_path}")
            return result

        # ---- 1. 读取并解析 ----
        text = chat_path.read_text(encoding="utf-8")
        messages = parse_chat_file(text)
        logger.info(f"从聊天记录中解析出 {len(messages)} 条消息")

        if not messages:
            result.errors.append("聊天记录为空，无法统计")
            return result

        # ---- 2. 计算统计指标 ----
        stats = compute_statistics(messages, contact_name=contact_name)

        # ---- 3. 写入 statistics.json ----
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        stats_file = output_root / "statistics.json"
        stats_file.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result.statistics_file = str(stats_file.resolve())
        result.total_messages = len(messages)
        logger.info(f"聊天统计完成 → {stats_file} ({len(messages)} 条消息)")
        return result


# ============================================================
# 解析
# ============================================================


def parse_chat_file(text: str) -> list[ChatMessageRecord]:
    """
    解析 chat.txt 为结构化消息列表。

    chat.txt 格式:
        [2026-07-26 17:33] 我：
        明天考试加油

    Args:
        text: chat.txt 完整内容。

    Returns:
        ChatMessageRecord 列表（按时间排序）。
    """
    lines = text.splitlines()
    records: list[ChatMessageRecord] = []

    current_header: str | None = None
    current_content: list[str] = []

    def _flush() -> None:
        """将当前积累的消息追加到 records。"""
        nonlocal current_header
        if current_header is None:
            return
        content = " ".join(p.strip() for p in current_content if p.strip())
        if content:
            parsed = _parse_header(current_header)
            if parsed is not None:
                ts, sender, is_self = parsed
                records.append(
                    ChatMessageRecord(
                        timestamp=ts,
                        sender=sender,
                        content=content,
                        is_self=is_self,
                    )
                )
        current_header = None
        current_content.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 消息头部: "[YYYY-MM-DD HH:MM] 发送者："
        if stripped.startswith("[") and "] " in stripped:
            _flush()
            current_header = stripped
        elif (
            stripped.startswith("===")
            or stripped.startswith("联系人")
            or stripped.startswith("导出时间")
            or stripped.startswith("消息数量")
        ):
            continue  # 文件头信息，跳过
        elif current_header is not None:
            current_content.append(stripped)

    _flush()

    return records


def _parse_header(header: str) -> tuple[datetime, str, bool] | None:
    """
    解析消息头部: "[2026-07-26 17:33] 我：" → (datetime, sender, is_self)。

    Returns:
        (timestamp, sender_name, is_self)。解析失败返回 None。
    """
    match = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*(.+?)[：:]$", header)
    if not match:
        return None

    ts_str, sender = match.group(1), match.group(2).strip()
    try:
        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return None

    is_self = sender == "我"
    return ts, sender, is_self


# ============================================================
# 统计计算
# ============================================================


def compute_statistics(
    messages: list[ChatMessageRecord],
    contact_name: str = "",
) -> dict:
    """
    计算聊天统计指标。

    Args:
        messages: 解析后的消息列表。
        contact_name: 联系人显示名称（为空时从消息推断对方名称）。

    Returns:
        统计结果 dict（可直接序列化为 JSON）。
    """
    # 确定联系人名称: 优先调用方传入；否则取消息中非"我"的发送者
    if not contact_name:
        them_names = [m.sender for m in messages if not m.is_self]
        contact_name = them_names[0] if them_names else "unknown"
    total = len(messages)
    sent_by_me = sum(1 for m in messages if m.is_self)
    sent_by_them = total - sent_by_me

    # ---- 时间分布 ----
    by_day: Counter = Counter(m.timestamp.strftime("%Y-%m-%d") for m in messages)
    by_hour: Counter = Counter(str(m.timestamp.hour) for m in messages)
    by_weekday: Counter = Counter(str(m.timestamp.weekday()) for m in messages)

    # ---- 消息长度 ----
    lengths = [len(m.content) for m in messages]
    avg_length = round(sum(lengths) / total, 1) if total else 0.0
    max_msg = max(messages, key=lambda m: len(m.content))
    max_length = len(max_msg.content)

    # ---- 响应时间 (相邻异发送者消息的间隔) ----
    response_gaps: list[int] = []
    for i in range(1, len(messages)):
        prev, cur = messages[i - 1], messages[i]
        if prev.is_self != cur.is_self:
            gap = int((cur.timestamp - prev.timestamp).total_seconds())
            # 过滤超过 24 小时的空档（跨天不视为"回复"）
            if 0 < gap <= 24 * 3600:
                response_gaps.append(gap)

    response_stats: dict = {"count": len(response_gaps)}
    if response_gaps:
        response_stats["avg_seconds"] = round(sum(response_gaps) / len(response_gaps))
        response_stats["median_seconds"] = _median(response_gaps)
    else:
        response_stats["avg_seconds"] = 0
        response_stats["median_seconds"] = 0

    # ---- 发起对话比例 (每日第一条消息的发送者) ----
    init_me = 0
    init_them = 0
    by_day_sorted = sorted(by_day.keys())
    for day in by_day_sorted:
        day_msgs = [m for m in messages if m.timestamp.strftime("%Y-%m-%d") == day]
        if day_msgs:
            if day_msgs[0].is_self:
                init_me += 1
            else:
                init_them += 1

    # ---- 高频词 ----
    word_counts = count_words(messages)

    # ---- 组装结果 ----
    return {
        "contact_name": contact_name,
        "period": {
            "start": messages[0].timestamp.strftime("%Y-%m-%d"),
            "end": messages[-1].timestamp.strftime("%Y-%m-%d"),
        },
        "total_messages": total,
        "sent_by_me": sent_by_me,
        "sent_by_them": sent_by_them,
        "message_length": {
            "avg_chars": avg_length,
            "max_chars": max_length,
            "max_message": max_msg.content[:100],
        },
        "messages_by_day": dict(by_day),
        "messages_by_hour": dict(sorted(by_hour.items(), key=lambda x: int(x[0]))),
        "messages_by_weekday": dict(sorted(by_weekday.items(), key=lambda x: int(x[0]))),
        "response_times": response_stats,
        "initiation": {
            "me_days": init_me,
            "them_days": init_them,
        },
        "top_words": word_counts[:15],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def count_words(messages: list[ChatMessageRecord], top_n: int = 15) -> list[dict]:
    """统计高频词（过滤停用词）。"""
    counter: Counter = Counter()
    for m in messages:
        tokens = _TOKEN_PATTERN.findall(m.content.lower())
        for token in tokens:
            if token in STOP_WORDS:
                continue
            if len(token) < 2:
                continue
            counter[token] += 1

    return [{"word": word, "count": count} for word, count in counter.most_common(top_n)]


def _median(values: list[int]) -> int:
    """计算中位数。"""
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) // 2
