"""
Miru Assistant — Chat Analyzer 数据模型。

定义聊天导出和分析过程中使用的数据结构。
"""

from dataclasses import dataclass, field

# ============================================================
# 异常
# ============================================================


class ChatExportError(Exception):
    """Chat Analyzer 基础异常。"""

    def __init__(self, message: str, suggestion: str = ""):
        super().__init__(message)
        self.suggestion = suggestion


class ContactNotFoundError(ChatExportError):
    """指定联系人不存在。"""

    def __init__(self, contact_name: str, available_count: int = 0):
        msg = f"未找到联系人: {contact_name}"
        sug = ""
        if available_count > 0:
            sug = f"数据库中有 {available_count} 个联系人。请使用完整昵称、备注或微信号重试。"
        else:
            sug = "请确认联系人数据库已正确解密，或微信已登录。"
        super().__init__(msg, suggestion=sug)


class ChatAnalysisError(ChatExportError):
    """聊天分析失败（如 API key 未配置）。"""


# ============================================================
# 数据模型
# ============================================================


@dataclass
class ContactInfo:
    """解析后的联系人信息。"""

    username: str = ""  # 微信内部 ID (e.g. "wxid_abc123")
    nickname: str = ""  # 昵称
    remark: str = ""  # 备注名
    alias: str = ""  # 微信号
    display_name: str = ""  # 最佳显示名

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.remark or self.nickname or self.alias or self.username


@dataclass
class ExportResult:
    """一次聊天导出操作的完整结果。"""

    contact_name: str = ""  # 联系人显示名称
    contact_username: str = ""  # 联系人微信内部 ID
    output_file: str = ""  # 输出 TXT 文件路径
    raw_output_file: str = ""  # 原始完整版 TXT 路径（离线导出时存在）
    total_messages: int = 0  # 导出消息总数
    text_messages: int = 0  # 文本消息数
    image_messages: int = 0  # 图片消息数
    voice_messages: int = 0  # 语音消息数
    date_range_start: str = ""  # 第一条消息日期
    date_range_end: str = ""  # 最后一条消息日期
    export_time: str = ""  # 导出时间
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class ExportedMessage:
    """格式化后的单条导出消息。"""

    timestamp: str = ""  # "YYYY-MM-DD HH:MM"
    sender: str = ""  # "我" 或联系人显示名
    content: str = ""  # 消息文本内容
    is_self: bool = False  # 是否为自己发送


@dataclass
class ChatMessage:
    """
    统一聊天消息模型（群聊与私聊共用）。

    由导出器生成，供统计/分析/时间线等下游消费；
    序列化为 chat.txt 时保留 sender/content 两个核心字段。
    """

    timestamp: int = 0  # Unix 时间戳（秒）
    sender: str = ""  # 显示名称（"我" 或参与者名称）
    sender_id: int = 0  # 分片 Name2Id rowid（0 = 未知）
    sender_username: str = ""  # 发送者原始 wxid（身份判定的可靠依据）
    content: str = ""  # 消息内容（文本原样；非文本为摘要或占位）
    raw_content: str = ""  # 原始完整内容（含 XML/压缩前文本）
    msg_type: int = 1  # 微信消息类型 (1=文本, 3=图片, 34=语音, ...)
    conversation: str = ""  # 会话标识（wxid 或 @chatroom）
    source: str = ""  # 数据来源（如 "message_1.db/Msg_xxx"）

    @property
    def is_text(self) -> bool:
        return self.msg_type == 1


@dataclass
class AnalysisResult:
    """一次聊天分析的完整结果。"""

    contact_name: str = ""  # 联系人显示名称
    analysis_file: str = ""  # 输出的 analysis.md 路径
    total_messages: int = 0  # 分析的消息总数
    llm_success: bool = False  # LLM 调用是否成功
    token_usage: dict = field(default_factory=dict)  # {prompt, completion, total}
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class StatisticsResult:
    """一次聊天统计的完整结果。"""

    contact_name: str = ""  # 联系人显示名称
    statistics_file: str = ""  # 输出的 statistics.json 路径
    total_messages: int = 0  # 统计的消息总数
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class TimelineEvent:
    """时间线上的一个事件（会话）。"""

    date: str = ""  # 事件日期 "YYYY-MM-DD"
    start_time: str = ""  # 开始时间 "HH:MM"
    end_time: str = ""  # 结束时间 "HH:MM"
    message_count: int = 0  # 消息数量
    participants: list[str] = field(default_factory=list)  # 参与者（去重）
    keywords: list[str] = field(default_factory=list)  # 高频关键词
    summary: str = ""  # 事件摘要


@dataclass
class TimelineResult:
    """一次时间线分析的完整结果。"""

    contact_name: str = ""  # 联系人显示名称
    timeline_file: str = ""  # 输出的 timeline.json 路径
    total_events: int = 0  # 事件总数
    events: list[TimelineEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0
