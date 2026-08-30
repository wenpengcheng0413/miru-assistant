"""Resilient outbound WSS client for the Windows Home Node."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid

import websockets

from .config import NodeClientConfig
from .credentials import load_token
from .journal import JobJournal

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = 1


def reconnect_delay(attempt: int, *, maximum: float, jitter: float = 0.0) -> float:
    base = min(maximum, float(2 ** max(0, min(attempt, 10))))
    return min(maximum, base + max(0.0, jitter))


class HomeNodeClient:
    def __init__(self, config: NodeClientConfig) -> None:
        self.config = config
        self.instance_id = str(uuid.uuid4())
        self.journal = JobJournal(config.journal_path)

    async def connect_once(self) -> None:
        token = load_token(self.config.token_path)
        async with websockets.connect(
            self.config.cloud_url,
            open_timeout=self.config.connect_timeout_s,
            close_timeout=5,
            max_size=65_536,
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            await websocket.send(json.dumps({
                "type": "node.hello",
                "protocol_version": PROTOCOL_VERSION,
                "node_id": self.config.node_id,
                "device_token": token,
                "client_instance_id": self.instance_id,
                "capabilities": self.config.capabilities,
                "last_completed_job_ids": self.journal.completed_ids(),
            }, separators=(",", ":")))
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            welcome = json.loads(raw)
            if welcome.get("type") != "node.welcome" or welcome.get("protocol_version") != PROTOCOL_VERSION:
                raise RuntimeError("Home Node handshake rejected")
            interval = int(welcome.get("heartbeat_interval_s", 20))
            interval = max(5, min(interval, 60))
            logger.info(
                "Home Node online: protocol=%d capabilities=%d",
                PROTOCOL_VERSION,
                len(welcome.get("allowed_capabilities", [])),
            )
            while True:
                await asyncio.sleep(interval)
                await websocket.send(json.dumps({
                    "type": "node.heartbeat",
                    "protocol_version": PROTOCOL_VERSION,
                    "node_id": self.config.node_id,
                }, separators=(",", ":")))
                raw = await asyncio.wait_for(websocket.recv(), timeout=interval)
                reply = json.loads(raw)
                if reply.get("type") != "node.heartbeat_ack":
                    raise RuntimeError("unexpected Home Node frame")

    async def run_forever(self) -> None:
        attempt = 0
        while True:
            try:
                await self.connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = reconnect_delay(
                    attempt,
                    maximum=self.config.max_backoff_s,
                    jitter=random.uniform(0.0, 0.5),
                )
                logger.warning(
                    "Home Node disconnected: error_type=%s retry_in_s=%.1f",
                    type(exc).__name__,
                    delay,
                )
                attempt += 1
                await asyncio.sleep(delay)
