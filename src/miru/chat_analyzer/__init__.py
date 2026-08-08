"""Miru Assistant — Chat Analyzer (v2).

独立于 Daily Report 的联系人聊天记录导出与分析模块。

Phase 1: 联系人聊天记录导出 TXT。
Phase 2: DeepSeek AI 聊天分析。
Phase 3: 聊天统计 statistics.json。
Phase 4: 事件时间线 timeline.json。
"""

from miru.chat_analyzer.analyzer import ChatAnalyzer
from miru.chat_analyzer.exporter import ChatExporter, export_chat
from miru.chat_analyzer.models import (
    AnalysisResult,
    ChatAnalysisError,
    ChatExportError,
    ContactInfo,
    ContactNotFoundError,
    ExportResult,
    StatisticsResult,
    TimelineEvent,
    TimelineResult,
)
from miru.chat_analyzer.statistics import ChatStatistics
from miru.chat_analyzer.timeline import TimelineAnalyzer

__all__ = [
    "ChatAnalyzer",
    "ChatExporter",
    "ChatStatistics",
    "TimelineAnalyzer",
    "export_chat",
    "AnalysisResult",
    "ChatAnalysisError",
    "ChatExportError",
    "ContactInfo",
    "ContactNotFoundError",
    "ExportResult",
    "StatisticsResult",
    "TimelineEvent",
    "TimelineResult",
]
