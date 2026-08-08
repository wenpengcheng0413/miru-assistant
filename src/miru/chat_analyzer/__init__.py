"""Miru Assistant — Chat Analyzer (v2).

独立于 Daily Report 的联系人聊天记录导出与分析模块。

Phase 1: 联系人聊天记录导出 TXT（在线 ChatExporter / 离线 ContactFullExporter）。
Phase 2: DeepSeek AI 聊天分析。
Phase 3: 聊天统计 statistics.json。
Phase 4: 事件时间线 timeline.json。
"""

from miru.chat_analyzer.analyzer import ChatAnalyzer
from miru.chat_analyzer.contacts import ContactAlias, load_contact_aliases, resolve_via_aliases
from miru.chat_analyzer.exporter import ChatExporter, export_chat
from miru.chat_analyzer.models import (
    AnalysisResult,
    ChatAnalysisError,
    ChatExportError,
    ChatMessage,
    ContactInfo,
    ContactNotFoundError,
    ExportResult,
    StatisticsResult,
    TimelineEvent,
    TimelineResult,
)
from miru.chat_analyzer.offline_exporter import ContactFullExporter, export_contact_full
from miru.chat_analyzer.offline_reader import OfflineWeChatDB, session_table_md5, summarize_content
from miru.chat_analyzer.statistics import ChatStatistics
from miru.chat_analyzer.timeline import TimelineAnalyzer

__all__ = [
    "ChatAnalyzer",
    "ChatExporter",
    "ChatStatistics",
    "TimelineAnalyzer",
    "ContactAlias",
    "ContactFullExporter",
    "OfflineWeChatDB",
    "load_contact_aliases",
    "resolve_via_aliases",
    "export_chat",
    "export_contact_full",
    "session_table_md5",
    "summarize_content",
    "AnalysisResult",
    "ChatAnalysisError",
    "ChatExportError",
    "ChatMessage",
    "ContactInfo",
    "ContactNotFoundError",
    "ExportResult",
    "StatisticsResult",
    "TimelineEvent",
    "TimelineResult",
]
