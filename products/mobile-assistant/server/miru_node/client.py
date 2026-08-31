"""Resilient outbound WSS client for the Windows Home Node."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import urllib.request
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

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
        self._device_token = ""

    async def connect_once(self) -> None:
        token = load_token(self.config.token_path)
        self._device_token = token
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
            jobs: dict[str, asyncio.Task] = {}
            last_ack = asyncio.get_running_loop().time()
            while True:
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=interval)
                except asyncio.TimeoutError:
                    if asyncio.get_running_loop().time() - last_ack > interval * 2.5:
                        raise RuntimeError("Home Node heartbeat acknowledgement timed out")
                    await websocket.send(json.dumps({
                        "type": "node.heartbeat",
                        "protocol_version": PROTOCOL_VERSION,
                        "node_id": self.config.node_id,
                    }, separators=(",", ":")))
                    continue
                reply = json.loads(raw)
                message_type = reply.get("type")
                if message_type == "node.heartbeat_ack":
                    last_ack = asyncio.get_running_loop().time()
                elif message_type == "job.request":
                    job_id = reply.get("job_id")
                    if not isinstance(job_id, str) or not (1 <= len(job_id) <= 128):
                        raise RuntimeError("invalid node job id")
                    cached = self.journal.get_result(job_id)
                    if cached is not None:
                        await self._send_result(websocket, job_id, cached, duplicate=True)
                        continue
                    if len(jobs) >= 2:
                        result = self._failure("node_busy", "Home Node 正在处理其他任务", True)
                        await self._send_result(websocket, job_id, result)
                        continue
                    task = asyncio.create_task(self._run_job(reply))
                    jobs[job_id] = task
                    task.add_done_callback(
                        lambda completed, jid=job_id: asyncio.create_task(
                            self._finish_job(websocket, jobs, jid, completed)
                        )
                    )
                elif message_type == "job.cancel":
                    job_id = reply.get("job_id")
                    task = jobs.get(job_id) if isinstance(job_id, str) else None
                    if task is not None and not task.done():
                        task.cancel()
                    await websocket.send(json.dumps({
                        "type": "job.cancel_ack",
                        "protocol_version": PROTOCOL_VERSION,
                        "job_id": job_id,
                    }, separators=(",", ":")))
                else:
                    raise RuntimeError("unexpected Home Node frame")

    @staticmethod
    def _failure(error_code: str, message: str, retryable: bool) -> dict:
        return {
            "ok": False,
            "data": None,
            "error": message,
            "error_code": error_code,
            "retryable": retryable,
        }

    async def _run_job(self, request: dict) -> dict:
        tool = request.get("tool")
        args = request.get("args")
        if tool not in self.config.capabilities:
            return self._failure("node_capability_unavailable", "节点能力未启用", False)
        if tool == "home_node_ping":
            if args != {}:
                return self._failure("invalid_tool_arguments", "home_node_ping 不接受参数", False)
            return {
                "ok": True,
                "data": {
                    "node_id": self.config.node_id,
                    "protocol_version": PROTOCOL_VERSION,
                    "state": "ok",
                    "node_time": datetime.now(timezone.utc).isoformat(),
                },
            }
        if tool in {
            "wechat_search_messages",
            "wechat_conversation_messages",
            "wechat_transcribe_voice",
            "wechat_original_images",
        }:
            if not isinstance(args, dict):
                return self._failure("invalid_tool_arguments", "微信搜索参数无效", False)
            from .wechat_adapter import WeChatAdapterError, WeChatNodeAdapter

            adapter = WeChatNodeAdapter(
                self.config.wechat_data_root,
                max_days=self.config.wechat_max_days,
                max_results=self.config.wechat_max_results,
                stt_model_dir=self.config.wechat_stt_model_dir,
            )
            try:
                method = {
                    "wechat_search_messages": adapter.search_messages,
                    "wechat_conversation_messages": adapter.conversation_messages,
                    "wechat_transcribe_voice": adapter.transcribe_voice,
                    "wechat_original_images": adapter.extract_original_images,
                }[tool]
                call_args = dict(args)
                conversation_id = str(call_args.pop("conversation_id", ""))
                if tool == "wechat_original_images" and not conversation_id:
                    return self._failure("invalid_tool_arguments", "缺少媒体目标会话", False)
                data = await asyncio.to_thread(method, **call_args)
                if tool == "wechat_original_images":
                    uploaded = []
                    for row in data.get("images", []):
                        image_bytes = row.pop("_bytes", b"")
                        extension = row.pop("_extension", "")
                        if image_bytes:
                            try:
                                remote = await asyncio.to_thread(
                                    self._upload_node_media,
                                    image_bytes,
                                    extension=extension,
                                    conversation_id=conversation_id,
                                    message_time=str(row.get("time") or ""),
                                    sender=str(row.get("sender") or ""),
                                )
                                row.update(remote)
                            except Exception:
                                row["error"] = "media_upload_failed"
                        uploaded.append(row)
                    data["images"] = uploaded
            except WeChatAdapterError as exc:
                return self._failure(exc.error_code, exc.message, exc.retryable)
            except (TypeError, ValueError):
                return self._failure("invalid_tool_arguments", "微信读取参数无效", False)
            except Exception:
                return self._failure("wechat_read_failed", "微信消息读取失败", False)
            return {"ok": True, "data": data}
        return self._failure("node_capability_unavailable", "节点能力未启用", False)

    def _upload_node_media(
        self,
        data: bytes,
        *,
        extension: str,
        conversation_id: str,
        message_time: str,
        sender: str,
    ) -> dict:
        if not data or len(data) > 10 * 1024 * 1024:
            raise ValueError("invalid media size")
        if not self._device_token:
            raise RuntimeError("node token unavailable")
        parsed = urlparse(self.config.cloud_url)
        upload_url = parsed._replace(
            scheme="https",
            path="/api/node/media",
            params="",
            query="",
            fragment="",
        ).geturl()
        encoded_sender = base64.urlsafe_b64encode(sender.encode("utf-8")[:240]).decode("ascii").rstrip("=")
        request = urllib.request.Request(
            upload_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._device_token}",
                "Content-Type": "application/octet-stream",
                "X-Miru-Conversation-Id": conversation_id,
                "X-Miru-Image-Ext": extension,
                "X-Miru-Message-Time": message_time[:40],
                "X-Miru-Sender": encoded_sender,
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError("media response too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not payload.get("download_path"):
            raise ValueError("invalid media response")
        return payload

    async def _finish_job(self, websocket, jobs: dict, job_id: str, task: asyncio.Task) -> None:
        jobs.pop(job_id, None)
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception:
            result = self._failure("node_job_failed", "节点任务执行失败", False)
        self.journal.record_result(job_id, result)
        try:
            await self._send_result(websocket, job_id, result)
        except Exception:
            pass

    @staticmethod
    async def _send_result(websocket, job_id: str, result: dict, duplicate: bool = False) -> None:
        await websocket.send(json.dumps({
            "type": "job.result",
            "protocol_version": PROTOCOL_VERSION,
            "job_id": job_id,
            "duplicate": duplicate,
            "result": result,
        }, separators=(",", ":")))

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
