"""REST 管理接口（docs/06 §2）。全部 Bearer 鉴权。"""
from __future__ import annotations

import asyncio
import io
import json
import uuid
import wave
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from ..attachments import save_upload
from ..db.models import ApiUsage, Attachment, Conversation, Message, TurnTrace
from ..documents import extract as extract_document
from ..stt.base import STTUnavailable
from ..tts.base import VoiceConfig
from .deps import verify_rest_token

router = APIRouter(prefix="/api", dependencies=[Depends(verify_rest_token)])


def _svc(request: Request):
    return request.app.state.services


def _attachment_json(row: Attachment) -> dict:
    return {
        "id": row.id, "filename": row.filename, "media_type": row.media_type,
        "kind": row.kind, "size_bytes": row.size_bytes, "status": row.status,
        "error": row.error, "preview_count": len(json.loads(row.preview_paths or "[]")),
        "created_at": row.created_at.isoformat(),
    }


# ---------------------------------------------------------------- 健康与状态

@router.get("/health")
async def health(request: Request):
    s = _svc(request)
    return {
        "status": "ok",
        "llm_model": s.config.llm.model,
        "stt_engine": s.stt.name,
        "tts_provider": s.tts_provider.name if s.tts_provider else "none",
        "wechat_tools": any(n.startswith("wechat_") for n in s.tools.enabled_names),
        "version": __import__("miru_server").__version__,
    }


@router.get("/tools")
async def list_tools(request: Request):
    return {"tools": _svc(request).tools.list_all()}


# ---------------------------------------------------------------- 会话

@router.get("/conversations")
async def list_conversations(request: Request, limit: int = 50, q: str = ""):
    """侧边栏会话列表；单人部署下按最近更新时间排序。"""
    s = _svc(request)
    limit = max(1, min(limit, 100))
    with s.db() as db:
        stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        if q.strip():
            like = f"%{q.strip()}%"
            matching_ids = select(Message.conversation_id).where(Message.content.ilike(like))
            stmt = (
                select(Conversation)
                .where(or_(Conversation.title.ilike(like), Conversation.id.in_(matching_ids)))
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
            )
        rows = db.scalars(stmt).all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "persona": r.persona,
                "updated_at": r.updated_at.isoformat(),
                "message_count": db.scalar(
                    select(func.count(Message.id)).where(Message.conversation_id == r.id)
                ) or 0,
            }
            for r in rows
        ]


class ConversationCreate(BaseModel):
    persona: str = "miru"


@router.post("/conversations", status_code=201)
async def create_conversation(request: Request, body: ConversationCreate):
    s = _svc(request)
    conversation = Conversation(id=uuid.uuid4().hex, persona=body.persona)
    with s.db() as db:
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return {
        "id": conversation.id, "title": conversation.title,
        "persona": conversation.persona, "updated_at": conversation.updated_at.isoformat(),
    }


class ConversationUpdate(BaseModel):
    title: str


@router.patch("/conversations/{conv_id}")
async def update_conversation(request: Request, conv_id: str, body: ConversationUpdate):
    title = body.title.strip()[:120]
    if not title:
        raise HTTPException(400, "标题不能为空")
    with _svc(request).db() as db:
        conversation = db.get(Conversation, conv_id)
        if conversation is None:
            raise HTTPException(404, "会话不存在")
        conversation.title = title
        db.commit()
        db.refresh(conversation)
    return {"id": conversation.id, "title": conversation.title}


@router.get("/conversations/{conv_id}/messages")
async def conversation_messages(request: Request, conv_id: str, limit: int = 200):
    s = _svc(request)
    limit = max(1, min(limit, 500))
    with s.db() as db:
        rows = (
            db.query(Message)
            .filter(Message.conversation_id == conv_id)
            .order_by(Message.id.desc()).limit(limit).all()
        )
        turn_ids = {row.turn_id for row in rows if row.turn_id}
        traces = {
            row.id: row for row in db.query(TurnTrace).filter(TurnTrace.id.in_(turn_ids)).all()
        } if turn_ids else {}

        def trace_json(turn_id: str | None) -> dict | None:
            if not turn_id or turn_id not in traces:
                return None
            trace = traces[turn_id]
            try:
                steps = json.loads(trace.steps_json or "[]")
            except json.JSONDecodeError:
                steps = []
            return {
                "status": trace.status,
                "steps": steps,
                "duration_ms": trace.duration_ms,
                "prompt_tokens": trace.prompt_tokens,
                "completion_tokens": trace.completion_tokens,
                "cost_rmb": round(trace.cost_rmb, 4),
            }

        return [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "turn_id": r.turn_id,
                "trace": trace_json(r.turn_id),
                "created_at": r.created_at.isoformat(),
            }
            for r in reversed(rows)
        ]


@router.delete("/conversations/{conv_id}")
async def delete_conversation(request: Request, conv_id: str):
    s = _svc(request)
    with s.db() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            raise HTTPException(404, "会话不存在")
        db.delete(conv)
        db.commit()
    return {"deleted": conv_id}


# ---------------------------------------------------------------- 附件

@router.post("/conversations/{conv_id}/attachments", status_code=201)
async def upload_attachment(request: Request, conv_id: str, file: UploadFile = File(...)):
    """手机先把附件落到本机服务器；分析在发送消息时路由到合适的模型。"""
    s = _svc(request)
    with s.db() as db:
        if db.get(Conversation, conv_id) is None:
            raise HTTPException(404, "会话不存在")
    saved = await save_upload(file, s.config.resolve(s.config.attachments.dir), s.config.attachments)
    attachment = Attachment(conversation_id=conv_id, status="processing", **saved)
    with s.db() as db:
        db.add(attachment)
        db.commit()
        db.refresh(attachment)
    if attachment.kind != "image":
        result = await asyncio.to_thread(
            extract_document, attachment.local_path, attachment.kind, s.config.attachments.max_preview_pages
        )
        with s.db() as db:
            row = db.get(Attachment, attachment.id)
            if row is not None:
                row.extracted_text = result.text
                row.preview_paths = json.dumps(result.previews, ensure_ascii=False)
                row.error = result.error
                row.status = "ready"
                db.commit()
                db.refresh(row)
                attachment = row
    else:
        with s.db() as db:
            row = db.get(Attachment, attachment.id)
            if row is not None:
                row.status = "ready"
                db.commit()
                db.refresh(row)
                attachment = row
    
    return _attachment_json(attachment)


@router.get("/conversations/{conv_id}/attachments")
async def list_attachments(request: Request, conv_id: str):
    with _svc(request).db() as db:
        rows = db.scalars(
            select(Attachment)
            .where(Attachment.conversation_id == conv_id)
            .order_by(Attachment.created_at.desc())
        ).all()
        return [_attachment_json(row) for row in rows]


# ---------------------------------------------------------------- 记忆

MEMORY_SCOPES = {"profile", "preferences", "projects", "knowledge", "episodes"}


@router.get("/memory")
async def memory_list(request: Request, scope: str = "profile", q: str = ""):
    s = _svc(request)
    if scope not in MEMORY_SCOPES:
        raise HTTPException(400, f"scope 必须是 {sorted(MEMORY_SCOPES)}")
    if q:
        return {"entries": await asyncio.to_thread(s.memory.search, q)}
    return {"entries": await asyncio.to_thread(s.memory.list, scope)}


class MemoryPut(BaseModel):
    value: str


@router.put("/memory/{scope}/{key:path}")
async def memory_put(request: Request, scope: str, key: str, body: MemoryPut):
    s = _svc(request)
    if scope not in MEMORY_SCOPES:
        raise HTTPException(400, "scope 非法")
    await asyncio.to_thread(s.memory.set, scope, key, body.value, "user")
    return {"ok": True, "scope": scope, "key": key}


@router.delete("/memory/{scope}/{key:path}")
async def memory_delete(request: Request, scope: str, key: str):
    s = _svc(request)
    removed = await asyncio.to_thread(s.memory.delete, scope, key)
    return {"removed": removed}


# ---------------------------------------------------------------- Persona

@router.get("/persona")
async def persona_get(request: Request, name: str = ""):
    s = _svc(request)
    persona = s.persona.load(name or s.config.persona.default)
    return {
        "name": persona.name, "role": persona.role, "personality": persona.personality,
        "speaking_style": persona.speaking_style, "response_style": persona.response_style,
        "address_user": persona.address_user, "prohibitions": persona.prohibitions,
        "voice": {
            "voice_id": persona.voice.voice_id, "speed": persona.voice.speed,
            "emotion": persona.voice.emotion,
        },
    }


class PersonaPut(BaseModel):
    name: str
    yaml: str


@router.put("/persona")
async def persona_put(request: Request, body: PersonaPut):
    s = _svc(request)
    try:
        persona = s.persona.save(body.name, body.yaml)
    except Exception as e:
        raise HTTPException(400, f"persona 保存失败: {e}")
    return {"ok": True, "name": persona.name}


@router.get("/persona/list")
async def persona_list(request: Request):
    return {"names": _svc(request).persona.list_names()}


# ---------------------------------------------------------------- 成本

@router.get("/cost/report")
async def cost_report(request: Request, days: int = 7):
    s = _svc(request)
    return await asyncio.to_thread(s.cost.daily_report, days)


@router.get("/cost/budget")
async def cost_budget_get(request: Request, provider: str = "total"):
    s = _svc(request)
    return await asyncio.to_thread(s.cost.budget_status, provider)


class BudgetPut(BaseModel):
    provider: str = "total"
    month: str | None = None
    limit_rmb: float


@router.put("/cost/budget")
async def cost_budget_put(request: Request, body: BudgetPut):
    s = _svc(request)
    if body.limit_rmb <= 0:
        raise HTTPException(400, "limit_rmb 必须 > 0")
    await asyncio.to_thread(s.cost.set_budget, body.provider, body.month, body.limit_rmb)
    return {"ok": True}


# ---------------------------------------------------------------- 调试端点

@router.post("/debug/tts")
async def debug_tts(request: Request, body: MemoryPut):
    """text → 整段音频（验证 TTS 链路）。"""
    s = _svc(request)
    if s.tts_provider is None:
        raise HTTPException(503, "TTS provider 未配置")
    voice = s.persona.load(s.config.persona.default).voice
    try:
        audio = await s.tts_provider.synthesize(body.value, voice)
    except Exception as e:
        raise HTTPException(502, f"TTS 失败: {e}")
    media = "audio/mpeg" if s.config.tts.format == "mp3" else "audio/pcm"
    return Response(content=audio, media_type=media)


@router.post("/debug/stt")
async def debug_stt(request: Request, file: UploadFile = File(...)):
    """上传 16bit 单声道 wav → 识别文本（验证 STT 链路）。"""
    s = _svc(request)
    data = await file.read()
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            sample_rate = w.getframerate()
            pcm = w.readframes(w.getnframes())
    except Exception as e:
        raise HTTPException(400, f"wav 解析失败（需 16bit 单声道）: {e}")
    try:
        text = await asyncio.to_thread(s.stt.transcribe, pcm, sample_rate)
    except STTUnavailable as e:
        raise HTTPException(503, str(e))
    return {"text": text}
