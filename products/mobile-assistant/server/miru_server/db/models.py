"""SQLAlchemy 2.0 模型 —— 与 docs/06-数据库与API设计.md §1.2 DDL 一一对应。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, REAL, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    persona: Mapped[str] = mapped_column(Text, default="miru")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    role: Mapped[str] = mapped_column(Text)  # user / assistant / tool / system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TurnTrace(Base):
    """可安全展示的执行阶段摘要，不保存模型隐藏推理链。"""

    __tablename__ = "turn_traces"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(Text, default="running")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_rmb: Mapped[float] = mapped_column(REAL, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Attachment(Base):
    """原文件保存在 data/attachments，数据库仅保存安全元数据和解析结果。"""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)  # image / document / spreadsheet / presentation / text
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text, index=True)
    local_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="ready")  # ready / processing / failed
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    preview_paths: Mapped[str] = mapped_column(Text, default="[]")  # JSON，PDF/Office 页面的 PNG 预览
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WechatVoiceTranscript(Base):
    """微信语音的本机转写缓存；原始音频不复制进 Miru 数据库。"""

    __tablename__ = "wechat_voice_transcripts"

    server_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(Text, default="sensevoice")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WechatSync(Base):
    """微信离线快照同步记录；源数据库永远不由 Miru 修改。"""

    __tablename__ = "wechat_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_dir: Mapped[str] = mapped_column(Text)
    source_dir: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="running")
    wx_version: Mapped[str] = mapped_column(Text, default="")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    contact_count: Mapped[int] = mapped_column(Integer, default=0)
    message_shard_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WechatContact(Base):
    __tablename__ = "wechat_contacts"

    username: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, default="", index=True)
    nickname: Mapped[str] = mapped_column(Text, default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    is_group: Mapped[int] = mapped_column(Integer, default=0, index=True)
    sync_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class WechatMessageIndex(Base):
    __tablename__ = "wechat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, index=True)
    server_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    timestamp: Mapped[int] = mapped_column(Integer, index=True)
    msg_type: Mapped[int] = mapped_column(Integer, default=1, index=True)
    sender: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    sync_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    args: Mapped[str] = mapped_column(Text, default="{}")   # JSON
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON（按可见档位过滤后）
    ok: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiUsage(Base):
    """成本账本：LLM/TTS/VLM/本地 全部调用记录于此。"""

    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(Text)   # deepseek / minimax / dashscope / edge / local
    model: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)       # llm / tts / stt / vlm
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=1)
    cost_rmb: Mapped[float] = mapped_column(REAL, default=0.0)
    peak: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Budget(Base):
    __tablename__ = "budgets"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)  # deepseek / minimax / total
    month: Mapped[str] = mapped_column(Text, primary_key=True)     # YYYY-MM
    limit_rmb: Mapped[float] = mapped_column(REAL)


class MemoryProfile(Base):
    __tablename__ = "memory_profile"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="auto")   # auto / user
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MemoryPreference(Base):
    __tablename__ = "memory_preferences"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="auto")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MemoryProject(Base):
    __tablename__ = "memory_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MemoryKnowledge(Base):
    __tablename__ = "memory_knowledge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[bytes | None] = mapped_column(Text, nullable=True)  # 预留：向量（升级位）
    source: Mapped[str] = mapped_column(Text, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryEpisode(Base):
    __tablename__ = "memory_episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
