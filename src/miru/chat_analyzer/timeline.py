"""
Miru Assistant — Chat Analyzer 事件时间线 (Phase 4)。

基于聊天记录生成事件时间线，输出 timeline.json。

第一阶段: 规则型时间线（不调用 AI）。
    - 按日期聚合消息
    - 自动识别连续聊天窗口 (session: 相邻消息间隔 ≤ 10 分钟)
    - 每个 session 提取: 日期 / 时间范围 / 消息数量 / 参与者 / 高频关键词 / 摘要

复用:
    - statistics.parse_chat_file()  → 解析 chat.txt 为结构化消息
    - statistics.count_words()      → session 关键词提取

不依赖 Daily Report 任何模块。
纯计算 — 只读取 chat.txt，输出 timeline.json。

用法:
    timeline = TimelineAnalyzer()
    result = timeline.analyze(
        contact_name="张三",
        chat_file="output/张三/chat.txt",
        output_dir="output/张三",
    )
"""

import json
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.models import TimelineEvent, TimelineResult
from miru.chat_analyzer.statistics import (
    ChatMessageRecord,
    count_words,
    parse_chat_file,
)

# 连续聊天窗口判定: 相邻消息间隔超过此值 (秒) 视为新 session
SESSION_GAP_SECONDS = 600  # 10 分钟

# 每个 session 提取的关键词数量
KEYWORDS_PER_EVENT = 5


class TimelineAnalyzer:
    """
    事件时间线分析器。

    流程:
        1. 读取导出聊天记录 (chat.txt)
        2. 解析为结构化消息列表
        3. 合并连续消息为 session
        4. 每个 session 提取事件特征
        5. 写入 timeline.json

    用法:
        timeline = TimelineAnalyzer()
        result = timeline.analyze(
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
    ) -> TimelineResult:
        """
        分析聊天记录并生成 timeline.json。

        Args:
            contact_name: 联系人显示名称。
            chat_file: 导出的聊天记录 TXT 路径。
            output_dir: 输出目录根路径（timeline.json 写入此目录）。

        Returns:
            TimelineResult — 时间线结果（含 timeline.json 路径）。
        """
        result = TimelineResult(contact_name=contact_name)
        chat_path = Path(chat_file)

        if not chat_path.exists():
            result.errors.append(f"聊天记录文件不存在: {chat_path}")
            return result

        # ---- 1. 读取并解析 ----
        text = chat_path.read_text(encoding="utf-8")
        messages = parse_chat_file(text)
        logger.info(f"从聊天记录中解析出 {len(messages)} 条消息")

        if not messages:
            result.errors.append("聊天记录为空，无法生成时间线")
            return result

        # ---- 2. 合并 session + 构建事件 ----
        sessions = merge_sessions(messages)
        events = build_timeline_events(sessions)
        result.events = events
        result.total_events = len(events)
        logger.info(f"识别出 {len(events)} 个聊天事件 (session)")

        # ---- 3. 组装 JSON 并写入 ----
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        timeline_file = output_root / "timeline.json"

        payload = {
            "contact": contact_name,
            "period": {
                "start": messages[0].timestamp.strftime("%Y-%m-%d"),
                "end": messages[-1].timestamp.strftime("%Y-%m-%d"),
            },
            "total_events": len(events),
            "events": [_event_to_dict(e) for e in events],
        }
        timeline_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result.timeline_file = str(timeline_file.resolve())
        logger.info(f"时间线生成完成 → {timeline_file} ({len(events)} 个事件)")
        return result


# ============================================================
# Session 合并
# ============================================================


def merge_sessions(
    messages: list[ChatMessageRecord],
    gap_seconds: int = SESSION_GAP_SECONDS,
) -> list[list[ChatMessageRecord]]:
    """
    将消息合并为连续聊天窗口 (session)。

    规则: 相邻消息间隔超过 gap_seconds 视为新 session。
    消息必须按时间升序排列（parse_chat_file 保证）。

    Args:
        messages: 解析后的消息列表（已排序）。
        gap_seconds: 合并阈值（秒）。

    Returns:
        session 列表，每个 session 是消息子列表（保持时间顺序）。
    """
    if not messages:
        return []

    sessions: list[list[ChatMessageRecord]] = []
    current: list[ChatMessageRecord] = [messages[0]]

    for msg in messages[1:]:
        prev = current[-1]
        gap = (msg.timestamp - prev.timestamp).total_seconds()
        if gap > gap_seconds:
            sessions.append(current)
            current = [msg]
        else:
            current.append(msg)

    sessions.append(current)
    return sessions


# ============================================================
# 事件构建
# ============================================================


def build_timeline_events(
    sessions: list[list[ChatMessageRecord]],
) -> list[TimelineEvent]:
    """
    将 session 列表转换为 TimelineEvent 列表。

    每个 session 提取:
        - date / start_time / end_time
        - message_count
        - participants (发送者去重)
        - keywords (高频词 top 5)
        - summary (规则生成)

    Args:
        sessions: merge_sessions() 的输出。

    Returns:
        TimelineEvent 列表（按时间排序）。
    """
    events: list[TimelineEvent] = []
    for session in sessions:
        if not session:
            continue

        first = session[0]
        last = session[-1]

        # 参与者去重（保持出现顺序）
        participants: list[str] = []
        seen: set[str] = set()
        for m in session:
            if m.sender not in seen:
                seen.add(m.sender)
                participants.append(m.sender)

        # 关键词提取
        keywords = [item["word"] for item in count_words(session, top_n=KEYWORDS_PER_EVENT)]

        events.append(
            TimelineEvent(
                date=first.timestamp.strftime("%Y-%m-%d"),
                start_time=first.timestamp.strftime("%H:%M"),
                end_time=last.timestamp.strftime("%H:%M"),
                message_count=len(session),
                participants=participants,
                keywords=keywords,
                summary=_generate_summary(len(session), keywords),
            )
        )

    return events


def _generate_summary(message_count: int, keywords: list[str]) -> str:
    """
    规则生成事件摘要（第一阶段不调用 AI）。

    Args:
        message_count: session 消息数。
        keywords: session 高频关键词。

    Returns:
        摘要文本。
    """
    if keywords:
        top_kw = "、".join(keywords[:2])
        return f"围绕「{top_kw}」的对话（{message_count} 条消息）"
    return f"连续对话（{message_count} 条消息）"


def _event_to_dict(event: TimelineEvent) -> dict:
    """TimelineEvent → JSON dict（字段名与需求格式一致）。"""
    return {
        "date": event.date,
        "type": "topic",
        "start_time": event.start_time,
        "end_time": event.end_time,
        "messages": event.message_count,
        "participants": event.participants,
        "keywords": event.keywords,
        "summary": event.summary,
    }
