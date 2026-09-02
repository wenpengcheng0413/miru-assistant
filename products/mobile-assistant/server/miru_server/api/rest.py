"""REST 管理接口（docs/06 §2）。全部 Bearer 鉴权。"""
from __future__ import annotations

import asyncio
import io
import json
import uuid
import wave
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text

from ..attachments import save_upload
from ..db.models import Attachment, Conversation, Message, TurnTrace
from ..documents import extract as extract_document
from ..operations import capacity_snapshot
from ..stt.base import STTUnavailable
from ..wechat_runtime import sync_snapshot, sync_status
from .deps import verify_rest_token

router = APIRouter(prefix="/api", dependencies=[Depends(verify_rest_token)])
public_router = APIRouter()


def _svc(request: Request):
    return request.app.state.services


def _attachment_json(row: Attachment) -> dict:
    return {
        "id": row.id, "filename": row.filename, "media_type": row.media_type,
        "kind": row.kind, "size_bytes": row.size_bytes, "status": row.status,
        "storage_key": row.storage_key,
        "error": row.error, "preview_count": len(json.loads(row.preview_paths or "[]")),
        "created_at": row.created_at.isoformat(),
    }


# ---------------------------------------------------------------- 健康与状态


@public_router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe: no services, files, providers, or Home Node checks."""
    return {"status": "ok"}


@public_router.get("/readyz")
async def readyz(request: Request):
    """Readiness probe for core config, SQLite, and service initialization only."""
    services = getattr(request.app.state, "services", None)
    if services is None:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "error_code": "services_not_initialized"},
        )
    checks = {
        "config": bool(services.config.server.token and services.config.llm.api_key),
        "sqlite": False,
        "services": True,
    }
    try:
        with services.db() as db:
            db.execute(text("SELECT 1"))
        checks["sqlite"] = True
    except Exception:
        checks["sqlite"] = False
    ready = all(checks.values())
    body = {"status": "ready" if ready else "not_ready", "checks": checks}
    if not ready:
        body["error_code"] = "core_not_ready"
    return JSONResponse(status_code=200 if ready else 503, content=body)


def build_safe_status(services) -> dict:
    cfg = services.config
    backup_status = getattr(services, "backup_status", {
        "enabled": cfg.backup.enabled,
        "state": "pending" if cfg.backup.enabled else "disabled",
        "last_success_at": None,
        "last_error_code": "",
        "database_bytes": 0,
        "attachment_file_count": 0,
        "attachment_bytes": 0,
    })
    cloud_tools = services.tools.enabled_names
    voice_available = services.tts_provider is not None
    voice_reason = "" if voice_available else "provider_not_configured"
    node = services.home_node.snapshot()
    node_online = node.state == "online"
    node_capabilities = set(node.capabilities)
    cloud_stt_available = services.stt.name != "none"
    node_stt_available = node_online and "speech_to_text" in node_capabilities
    stt_available = cloud_stt_available or node_stt_available
    stt_provider = (
        services.stt.name if cloud_stt_available
        else "home-node-sensevoice" if node_stt_available
        else ""
    )
    stt_location = "cloud" if cloud_stt_available and cfg.is_cloud else (
        "home_node" if node_stt_available else "server"
    )
    wechat_available = node_online and any(
        item.startswith(("wechat.", "wechat_")) for item in node_capabilities
    )
    gpu_available = node_online and any(
        item.startswith("gpu.") for item in node_capabilities
    )
    node_reason = f"node_{node.state}" if not node_online else "capability_not_registered"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cloud": {
            "state": "ready",
            "profile": cfg.profile,
            "version": __import__("miru_server").__version__,
        },
        "home_node": node.public_dict(),
        "operations": {
            "backup": dict(backup_status),
            "capacity": capacity_snapshot(cfg.resolve(cfg.attachments.dir)),
        },
        "capabilities": {
            "chat": "available" if cfg.llm.api_key else "unavailable",
            "streaming": "available" if cfg.llm.api_key else "unavailable",
            "history": "available",
            "memory": "available",
            "persona": "available",
            "cost": "available",
            "cloud_tool": "available" if cloud_tools else "unavailable",
            "attachments_metadata": "available",
            "stt": {
                "available": stt_available,
                "location": stt_location,
                "provider": stt_provider,
                "reason": "" if stt_available else (
                    "disabled" if cfg.stt.engine == "none" else "provider_not_configured"
                ),
            },
            "tts": "available" if voice_available else "unavailable",
            "voice_reason": voice_reason,
            "wechat": "available" if wechat_available else "unavailable",
            "wechat_reason": "" if wechat_available else node_reason,
            "gpu": "available" if gpu_available else "unavailable",
            "gpu_reason": "" if gpu_available else node_reason,
        },
    }


@router.get("/status")
async def api_status(request: Request) -> dict:
    """Authenticated, bounded capability status; never expose local paths/keys."""
    return build_safe_status(_svc(request))

@router.get("/health")
async def health(request: Request):
    s = _svc(request)
    # Kept as a compatibility endpoint for existing clients. It is now
    # bounded and does not run WeChat diagnostics or expose local paths.
    node = s.home_node.snapshot()
    wechat_available = node.state == "online" and any(
        item.startswith("wechat.") for item in node.capabilities
    )
    wechat = {
        "available": wechat_available,
        "error_code": "" if wechat_available else f"node_{node.state}",
        "reason": "" if wechat_available else "Home Node capability is unavailable",
    }
    return {
        "status": "ok",
        "build_id": __import__("miru_server").__version__,
        "started_at": getattr(request.app.state, "started_at", None),
        "llm_model": s.config.llm.model,
        "vision_model": s.config.llm.vision_model,
        "stt_engine": s.stt.name,
        "tts_provider": s.tts_provider.name if s.tts_provider else "none",
        "wechat_tools": any(n.startswith("wechat_") for n in s.tools.enabled_names),
        "wechat_image_analysis": "wechat_image_analysis" in s.tools.enabled_names,
        "wechat": wechat,
        "version": __import__("miru_server").__version__,
        "profile": s.config.profile,
    }


@router.post("/wechat/sync")
async def wechat_sync(request: Request):
    """把当前已同步到电脑的微信数据复制为 Miru 离线快照。"""
    s = _svc(request)
    try:
        return await asyncio.to_thread(sync_snapshot, s.config, s.db)
    except Exception as exc:
        raise HTTPException(503, f"微信离线同步失败: {exc}") from exc


@router.get("/wechat/sync/status")
async def wechat_sync_status(request: Request):
    s = _svc(request)
    return await asyncio.to_thread(sync_status, s.config, s.db)


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
    notes: str | None = None


@router.put("/memory/{scope}/{key:path}")
async def memory_put(request: Request, scope: str, key: str, body: MemoryPut):
    s = _svc(request)
    if scope not in MEMORY_SCOPES:
        raise HTTPException(400, "scope 非法")
    await asyncio.to_thread(s.memory.set, scope, key, body.value, "user", body.notes)
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
