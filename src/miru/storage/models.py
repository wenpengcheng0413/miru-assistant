"""
Miru Assistant — 数据模型。

轻量级 dataclass，用于在 Repository 层与业务层之间传递数据。
所有时间戳均为 Unix 时间戳（整数），所有日期为 ISO 8601 字符串。

V1 表格:
    chat_groups     — 关注的微信群
    raw_messages    — 原始消息存档
    daily_reports   — 日报主表
    report_items    — 日报条目
    run_log         — 运行日志
    config_store    — 配置快照

V2 预留 (DDL 定义存在但未创建):
    todos           — 待办事项
    important_notices — 重要通知归档
"""

import time
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 时间工具
# ============================================================

def now_ts() -> int:
    """当前 Unix 时间戳。"""
    return int(time.time())


# ============================================================
# V1 数据模型
# ============================================================

@dataclass
class ChatGroup:
    """关注的微信群。"""

    id: Optional[int] = None
    group_name: str = ""                 # 群显示名称
    wechat_username: str = ""            # 微信内部 ID (如 123456789@chatroom)
    is_active: int = 1                   # 是否启用 (1=启用, 0=停用)
    member_count: int = 0                # 群成员数量
    first_seen_at: Optional[int] = None  # 首次发现时间
    last_seen_at: Optional[int] = None   # 最后发现时间
    notes: str = ""                      # 备注
    created_at: int = field(default_factory=now_ts)
    updated_at: int = field(default_factory=now_ts)


@dataclass
class RawMessage:
    """原始微信消息。"""

    id: Optional[int] = None
    msg_svr_id: int = 0                  # 微信服务端消息 ID (去重主键)
    group_id: int = 0                    # FK → chat_groups.id
    sender_name: str = ""                # 发送者显示名称
    content_text: str = ""               # 消息文本内容
    msg_type: int = 1                    # 消息类型 (1=文本, 3=图片, ...)
    create_time: int = 0                 # 微信消息原始时间戳
    is_processed: int = 0                # 是否已处理 (0=未处理, 1=已处理)
    processed_in: Optional[int] = None   # FK → daily_reports.id
    collected_at: int = field(default_factory=now_ts)
    created_at: int = field(default_factory=now_ts)


@dataclass
class DailyReport:
    """日报主表。"""

    id: Optional[int] = None
    report_date: str = ""                # 日报日期 (ISO 8601: "2026-07-24")
    content_md: str = ""                 # 日报 Markdown 完整内容
    stats_json: str = "{}"               # 统计数据 (JSON)
    groups_covered: str = "[]"           # 覆盖哪些群 (JSON Array)
    message_count: int = 0               # 处理的消息总数
    generated_at: int = field(default_factory=now_ts)
    push_status: str = "pending"         # pending | sent | failed
    pushed_at: Optional[int] = None      # 推送完成时间
    push_error: str = ""                 # 推送失败原因
    created_at: int = field(default_factory=now_ts)


@dataclass
class ReportItem:
    """日报条目（细粒度）。"""

    id: Optional[int] = None
    report_id: int = 0                   # FK → daily_reports.id
    category: str = ""                   # 通知 | 作业 | Deadline | 文件 | 待办 | 推荐
    content: str = ""                    # 条目内容
    source_group: str = ""               # 来源群名
    source_sender: str = ""              # 来源发送者
    importance: str = "low"              # low | medium | high
    deadline: Optional[str] = None       # 截止日期 (ISO 8601)
    action_required: int = 0             # 是否需要行动 (0/1)
    sort_order: int = 0                  # 排序
    created_at: int = field(default_factory=now_ts)


@dataclass
class RunLog:
    """运行日志。"""

    id: Optional[int] = None
    run_id: str = ""                     # 运行批次 ID (UUID)
    phase: str = ""                      # collect | filter | summarize | report | notify
    status: str = ""                     # success | error | skip
    message: str = ""                    # 详细信息
    duration_ms: int = 0                 # 耗时（毫秒）
    error_traceback: str = ""            # 异常堆栈
    created_at: int = field(default_factory=now_ts)


@dataclass
class ConfigStore:
    """配置快照。"""

    id: Optional[int] = None
    config_hash: str = ""                # SHA256
    config_snapshot: str = ""            # 配置完整副本 (JSON)
    created_at: int = field(default_factory=now_ts)


# ============================================================
# V2 预留模型 (仅供参考，V1 不建表)
# ============================================================

@dataclass
class Todo:
    """待办事项 — V2 使用。"""

    id: Optional[int] = None
    content: str = ""
    source_msg_id: Optional[int] = None   # FK → raw_messages.id
    source_group: str = ""
    status: str = "pending"              # pending | done | cancelled
    priority: str = "medium"             # low | medium | high | urgent
    deadline: Optional[str] = None       # ISO 8601
    reminder_at: Optional[str] = None    # ISO 8601
    completed_at: Optional[int] = None
    notes: str = ""
    created_at: int = field(default_factory=now_ts)
    updated_at: int = field(default_factory=now_ts)


@dataclass
class ImportantNotice:
    """重要通知 — V2 使用。"""

    id: Optional[int] = None
    content: str = ""
    source_group: str = ""
    source_sender: str = ""
    notice_date: str = ""                # ISO 8601
    tags: str = "[]"                     # JSON Array
    keywords: str = ""                   # 空格分隔
    created_at: int = field(default_factory=now_ts)
