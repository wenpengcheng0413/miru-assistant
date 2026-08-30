"""Authenticated outbound-only Home Node WebSocket endpoint."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .deps import check_token

logger = logging.getLogger(__name__)
router = APIRouter()
PROTOCOL_VERSION = 1


def _bounded_capabilities(value: object) -> list[str] | None:
    if not isinstance(value, list) or len(value) > 32:
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 64:
            return None
        result.append(item)
    return result


@router.websocket("/ws/node")
async def node_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    services = websocket.app.state.services
    cfg = services.config.home_node
    registry = services.home_node
    connection_id: str | None = None
    if not cfg.enabled:
        await websocket.close(code=4404, reason="Home Node disabled")
        return
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(raw) > 32_768:
            raise ValueError("hello_too_large")
        hello = json.loads(raw)
    except Exception:
        await websocket.close(code=4400, reason="invalid node hello")
        return
    if hello.get("type") != "node.hello" or hello.get("protocol_version") != PROTOCOL_VERSION:
        await websocket.close(code=4400, reason="unsupported node protocol")
        return
    if hello.get("node_id") != cfg.node_id:
        await websocket.close(code=4403, reason="unknown node_id")
        return
    if not check_token(str(hello.get("device_token") or ""), cfg.token):
        await websocket.close(code=4401, reason="node token invalid")
        return
    instance_id = hello.get("client_instance_id")
    if not isinstance(instance_id, str) or not (8 <= len(instance_id) <= 128):
        await websocket.close(code=4400, reason="invalid client_instance_id")
        return
    capabilities = _bounded_capabilities(hello.get("capabilities"))
    completed = hello.get("last_completed_job_ids", [])
    if capabilities is None or not isinstance(completed, list) or len(completed) > 100:
        await websocket.close(code=4400, reason="invalid node hello bounds")
        return

    connection_id = registry.register(
        protocol_version=PROTOCOL_VERSION,
        capabilities=capabilities,
    )
    accepted = list(registry.snapshot().capabilities)
    await websocket.send_json({
        "type": "node.welcome",
        "protocol_version": PROTOCOL_VERSION,
        "node_id": cfg.node_id,
        "heartbeat_interval_s": cfg.heartbeat_interval_s,
        "allowed_capabilities": accepted,
    })
    logger.info("Home Node connected: protocol=%s capabilities=%d", PROTOCOL_VERSION, len(accepted))
    try:
        while True:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=cfg.offline_after_s,
            )
            if len(raw) > 32_768:
                await websocket.close(code=4400, reason="node frame too large")
                break
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.close(code=4400, reason="invalid node frame")
                break
            if message.get("type") != "node.heartbeat":
                await websocket.close(code=4400, reason="unsupported phase6 frame")
                break
            if message.get("node_id") != cfg.node_id or not registry.heartbeat(connection_id):
                await websocket.close(code=4409, reason="node connection replaced")
                break
            await websocket.send_json({
                "type": "node.heartbeat_ack",
                "protocol_version": PROTOCOL_VERSION,
                "received_at": datetime.now(timezone.utc).isoformat(),
            })
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        if connection_id is not None:
            registry.disconnect(connection_id)
        logger.info("Home Node disconnected")
