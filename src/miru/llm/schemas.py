"""
Miru Assistant — LLM 输出结构定义。

使用 Pydantic 定义 DeepSeek API 返回的 JSON Schema。
确保 LLM 输出可被程序化处理。
"""

from pydantic import BaseModel, Field


class UrgentTask(BaseModel):
    """需要用户立即行动的事项。"""

    content: str = Field(..., description="任务内容描述")
    source_group: str = Field(..., description="来源群名")
    source_sender: str = Field(default="", description="发送者")
    deadline: str | None = Field(default=None, description="截止时间 (ISO 8601 或自然语言)")


class Deadline(BaseModel):
    """截止日期/时间节点。"""

    content: str = Field(..., description="截止事项描述")
    date: str = Field(..., description="截止日期 (尽量 ISO 8601 格式)")
    source_group: str = Field(..., description="来源群名")
    source_sender: str = Field(default="", description="发送者")


class Notice(BaseModel):
    """通知公告。"""

    content: str = Field(..., description="通知内容")
    source_group: str = Field(..., description="来源群名")
    source_sender: str = Field(default="", description="发送者")


class FileItem(BaseModel):
    """分享的文件/资料。"""

    content: str = Field(..., description="文件或资料描述")
    source_group: str = Field(..., description="来源群名")
    source_sender: str = Field(default="", description="发送者")


class GroupAnalysis(BaseModel):
    """
    单个群的消息分析结果。

    这是 DeepSeek API 针对每个群返回的 JSON 结构。
    """

    group_name: str = Field(..., description="群名")
    total_messages: int = Field(default=0, description="该群今日消息总数")
    valid_messages: int = Field(default=0, description="有效消息数（非闲聊）")

    urgent_tasks: list[UrgentTask] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)
    notices: list[Notice] = Field(default_factory=list)
    files: list[FileItem] = Field(default_factory=list)

    summary: str = Field(default="", description="该群今日一句话总结")
    ignored_topics: str = Field(default="", description="已忽略的闲聊话题")


# ============================================================
# Token 统计
# ============================================================


class TokenUsage(BaseModel):
    """单次 API 调用的 token 使用量。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMCallResult(BaseModel):
    """单次 LLM 调用的完整结果。"""

    group_name: str = ""
    analysis: GroupAnalysis | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    raw_response: str = ""
    duration_ms: int = 0
    success: bool = False
    error: str = ""
    retry_count: int = 0


# ============================================================
# Chat Analysis — 联系人聊天分析 (Chat Analyzer V2)
# ============================================================


class KeyConversation(BaseModel):
    """聊天记录中的关键对话节点。"""

    date: str = Field(..., description="对话日期 (ISO 8601)")
    summary: str = Field(..., description="该对话的主要内容")


class ChatAnalysis(BaseModel):
    """单个联系人的聊天分析结果 (Chat Analyzer Phase 2)。"""

    contact_name: str = Field(..., description="联系人名称")
    total_messages_analyzed: int = Field(default=0, description="分析的消息总数")
    period_start: str = Field(default="", description="分析时间段起始 (YYYY-MM-DD)")
    period_end: str = Field(default="", description="分析时间段结束 (YYYY-MM-DD)")
    communication_style: str = Field(default="", description="对话风格分析")
    main_topics: list[str] = Field(default_factory=list, description="主要话题")
    emotional_tone: str = Field(default="", description="情感基调")
    relationship_insights: str = Field(default="", description="关系洞察")
    key_conversations: list[KeyConversation] = Field(default_factory=list)
    overall_summary: str = Field(default="", description="总体总结")


class ChatAnalysisResult(BaseModel):
    """单次聊天分析调用的完整结果。"""

    contact_name: str = ""
    analysis: ChatAnalysis | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    raw_response: str = ""
    duration_ms: int = 0
    success: bool = False
    error: str = ""
    retry_count: int = 0
