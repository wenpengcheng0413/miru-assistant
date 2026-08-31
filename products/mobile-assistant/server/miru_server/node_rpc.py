"""Bounded Cloud-to-Home-Node RPC manager for read-only jobs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import uuid
from typing import Any, Awaitable, Callable

from .node_registry import HomeNodeRegistry


SendJson = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class NodeRpcError(Exception):
    error_code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class HomeNodeRpc:
    """Own the active node transport and bounded in-flight job futures."""

    def __init__(self, registry: HomeNodeRegistry, *, max_inflight: int = 2) -> None:
        self.registry = registry
        self.max_inflight = max(1, min(int(max_inflight), 2))
        self._connection_id: str | None = None
        self._send: SendJson | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()

    async def attach(self, connection_id: str, send: SendJson) -> None:
        await self.detach(self._connection_id)
        self._connection_id = connection_id
        self._send = send

    async def detach(self, connection_id: str | None) -> None:
        if connection_id is None or connection_id != self._connection_id:
            return
        self._connection_id = None
        self._send = None
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(NodeRpcError(
                    "node_disconnected",
                    "Home Node 连接已中断",
                    True,
                ))

    async def _safe_send(self, payload: dict[str, Any]) -> None:
        sender = self._send
        if sender is None:
            raise NodeRpcError("node_offline", "Home Node 当前离线", True)
        async with self._send_lock:
            await sender(payload)

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        timeout_s: float,
        job_id: str = "",
    ) -> dict[str, Any]:
        snapshot = self.registry.snapshot()
        if snapshot.state != "online" or self._send is None:
            raise NodeRpcError("node_offline", "Home Node 当前离线", True)
        if tool_name not in snapshot.capabilities:
            raise NodeRpcError(
                "node_capability_unavailable",
                f"Home Node 未注册能力 {tool_name}",
                False,
            )
        if len(self._pending) >= self.max_inflight:
            raise NodeRpcError("node_busy", "Home Node 正在处理其他任务", True)
        if not isinstance(args, dict) or len(json.dumps(args, ensure_ascii=False)) > 8_192:
            raise NodeRpcError("invalid_tool_arguments", "节点工具参数超限", False)
        value = job_id if isinstance(job_id, str) and 1 <= len(job_id) <= 128 else str(uuid.uuid4())
        if value in self._pending:
            raise NodeRpcError("duplicate_inflight_job", "节点任务正在执行", True)
        future = asyncio.get_running_loop().create_future()
        self._pending[value] = future
        try:
            await self._safe_send({
                "type": "job.request",
                "protocol_version": 1,
                "job_id": value,
                "tool": tool_name,
                "args": args,
                "deadline_ms": max(1_000, min(int(timeout_s * 1_000), 60_000)),
            })
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout_s)
            except asyncio.TimeoutError as exc:
                await self._send_cancel(value)
                raise NodeRpcError("node_timeout", "Home Node 工具执行超时", True) from exc
            except asyncio.CancelledError:
                await self._send_cancel(value)
                raise
        finally:
            current = self._pending.pop(value, None)
            if current is not None and not current.done():
                current.cancel()

    async def _send_cancel(self, job_id: str) -> None:
        try:
            await self._safe_send({
                "type": "job.cancel",
                "protocol_version": 1,
                "job_id": job_id,
            })
        except Exception:
            pass

    def accept_result(self, connection_id: str, message: dict[str, Any]) -> bool:
        if connection_id != self._connection_id:
            return False
        job_id = message.get("job_id")
        if not isinstance(job_id, str):
            return False
        future = self._pending.get(job_id)
        if future is None or future.done():
            return False
        result = message.get("result")
        if not isinstance(result, dict):
            future.set_exception(NodeRpcError("invalid_node_result", "节点返回无效结果", False))
            return True
        future.set_result(result)
        return True
