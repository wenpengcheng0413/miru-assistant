"""Short-lived authenticated Home Node media relay."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..attachments import detect_type
from ..db.models import Conversation
from .deps import check_token, verify_rest_token


router = APIRouter()
_MEDIA_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_TTL = timedelta(hours=24)


def _root(request: Request) -> Path:
    services = request.app.state.services
    return services.config.resolve(services.config.attachments.dir) / "node-media"


def _cleanup(root: Path) -> None:
    now = datetime.now(timezone.utc)
    if not root.exists():
        return
    for meta_path in root.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(str(meta.get("expires_at") or ""))
        except Exception:
            expires = datetime.min.replace(tzinfo=timezone.utc)
        if expires > now:
            continue
        media_id = meta_path.stem
        for candidate in root.glob(f"{media_id}.*"):
            try:
                candidate.unlink()
            except OSError:
                pass


def _meta_path(root: Path, media_id: str) -> Path:
    if not _MEDIA_ID.fullmatch(media_id):
        raise HTTPException(404, "媒体不存在或已过期")
    return root / f"{media_id}.json"


def _load_meta(root: Path, media_id: str) -> dict:
    path = _meta_path(root, media_id)
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        expires = datetime.fromisoformat(str(meta["expires_at"]))
    except Exception as exc:
        raise HTTPException(404, "媒体不存在或已过期") from exc
    if expires <= datetime.now(timezone.utc):
        _cleanup(root)
        raise HTTPException(410, "媒体已过期，请重新向 Miru 请求原图")
    return meta


def _node_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.startswith("Bearer ") else ""
    expected = request.app.state.services.config.home_node.token
    if not check_token(supplied, expected):
        raise HTTPException(401, "Home Node token 无效")


@router.post("/api/node/media", dependencies=[Depends(_node_token)])
async def upload_node_media(request: Request) -> dict:
    conversation_id = request.headers.get("X-Miru-Conversation-Id", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", conversation_id):
        raise HTTPException(400, "无效会话")
    with request.app.state.services.db() as db:
        if db.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "会话不存在")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > _MAX_IMAGE_BYTES:
            raise HTTPException(413, "原图超过 10MB 限制")
    if not data:
        raise HTTPException(400, "原图为空")
    try:
        media_type, kind, extension = detect_type(bytes(data[:64]), f"image{request.headers.get('X-Miru-Image-Ext', '')}")
    except HTTPException as exc:
        raise HTTPException(415, "只接受可直接显示的微信原图") from exc
    if kind != "image":
        raise HTTPException(415, "只接受图片")
    sender = ""
    try:
        encoded_sender = request.headers.get("X-Miru-Sender", "")
        padding = "=" * (-len(encoded_sender) % 4)
        sender = base64.urlsafe_b64decode(encoded_sender + padding).decode("utf-8")[:80]
    except Exception:
        sender = ""
    message_time = request.headers.get("X-Miru-Message-Time", "")[:40]
    now = datetime.now(timezone.utc)
    expires = now + _TTL
    media_id = uuid.uuid4().hex
    root = _root(request)
    root.mkdir(parents=True, exist_ok=True)
    _cleanup(root)
    media_path = root / f"{media_id}{extension}"
    meta_path = root / f"{media_id}.json"
    media_path.write_bytes(bytes(data))
    meta = {
        "id": media_id,
        "conversation_id": conversation_id,
        "media_type": media_type,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "file_name": media_path.name,
        "sender": sender,
        "message_time": message_time,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "download_path": f"/api/node-media/{media_id}",
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {key: meta[key] for key in (
        "id", "media_type", "size_bytes", "sender", "message_time", "expires_at", "download_path"
    )}


@router.get("/api/node-media/{media_id}", dependencies=[Depends(verify_rest_token)])
async def download_node_media(request: Request, media_id: str):
    root = _root(request)
    meta = _load_meta(root, media_id)
    path = root / str(meta.get("file_name") or "")
    if not path.is_file() or path.parent.resolve() != root.resolve():
        raise HTTPException(404, "媒体不存在或已过期")
    return FileResponse(
        path,
        media_type=str(meta.get("media_type") or "application/octet-stream"),
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get(
    "/api/conversations/{conversation_id}/node-media",
    dependencies=[Depends(verify_rest_token)],
)
async def list_node_media(request: Request, conversation_id: str) -> dict:
    root = _root(request)
    _cleanup(root)
    items = []
    if root.exists():
        for path in root.glob("*.json"):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if meta.get("conversation_id") == conversation_id:
                items.append({key: meta.get(key) for key in (
                    "id", "media_type", "size_bytes", "sender", "message_time",
                    "created_at", "expires_at", "download_path",
                )})
    items.sort(key=lambda item: str(item.get("created_at") or ""))
    return {"items": items[-20:]}
