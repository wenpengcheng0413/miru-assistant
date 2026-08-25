"""WS 会话入口：/ws/session（协议见 docs/02 §3）。

上行：二进制帧 = 16kHz PCM16 语音；文本帧 = JSON 控制消息（hello/text_input/audio_end/interrupt/ping）
下行：JSON 事件 + TTS 音频二进制帧
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core import events
from ..core.pipeline import AgentPipeline, SessionContext, new_conversation_id
from ..db.models import TurnTrace
from ..stt.base import STTUnavailable
from ..stt.vad import EnergyVAD
from .deps import check_token

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class _ActiveRun:
    ctx: SessionContext
    task: asyncio.Task


# 任务生命周期独立于某一条手机 WebSocket。服务器进程仍在时，切后台/回前台
# 或短暂断网都不会取消 DeepSeek 请求；新连接会接管同一 ctx 的事件输出。
_active_runs: dict[str, _ActiveRun] = {}


async def _safe_send(websocket: WebSocket, payload: dict) -> None:
    """发送 JSON 事件；连接已断时静默。"""
    try:
        await websocket.send_text(events.dumps(payload))
    except Exception:
        logger.debug("WS 发送失败（连接可能已断）")


class VoiceSession:
    """单个连接的语音处理状态：VAD 断句 + 部分识别 + 最终识别。

    协议闸门：只有客户端先发 audio_start、后发 audio_end 的音频才会被识别。
    未声明录音的音频帧一律丢弃——从根源上杜绝"客户端失控导致环境音被转成文字"。
    """

    def __init__(self, ctx: SessionContext, stt, websocket: WebSocket, cfg,
                 recording_timeout: float = 65.0):
        # 服务端窗口 65s > 客户端 60s 上限：服务端绝不在用户松手前抢先关窗
        self.ctx = ctx
        self.stt = stt
        self.ws = websocket
        self.cfg = cfg
        self.vad = EnergyVAD(cfg.stt.vad)
        self._partial_task: asyncio.Task | None = None
        self._stt_error_sent = False
        self._recording = False
        self._recording_task: asyncio.Task | None = None
        self._recording_timeout = recording_timeout
        self._ignored_audio_bytes = 0
        self._segments: list[str] = []   # 本次按键已识别的片段（松手时合并成一轮）

    def start_recording(self) -> None:
        """客户端按下录音键：打开音频闸门 + 重置 VAD + 启动看门狗。"""
        if self._recording:
            return
        self._recording = True
        self._ignored_audio_bytes = 0
        self._segments = []
        self.vad = EnergyVAD(self.cfg.stt.vad)   # 新会话从干净状态开始
        self._recording_task = asyncio.create_task(self._recording_watchdog())

    async def _recording_watchdog(self) -> None:
        """录音窗口超时兜底：客户端崩溃/手势丢失时，丢弃缓冲并关上闸门。"""
        await asyncio.sleep(self._recording_timeout)
        if self._recording:
            logger.warning("录音窗口超过 %.0fs 未收到 audio_end，强制丢弃", self._recording_timeout)
            self._recording = False
            self.vad = EnergyVAD(self.cfg.stt.vad)

    async def on_audio(self, pcm: bytes) -> None:
        if not self._recording:
            self._ignored_audio_bytes += len(pcm)
            if self._ignored_audio_bytes == len(pcm):
                logger.warning("收到未声明录音的音频帧，已丢弃（客户端需先发 audio_start）")
            return
        ev = self.vad.process(pcm)
        if ev.kind == "speech_started":
            await self._start_partial_loop()
        elif ev.kind == "speech_ended":
            await self._finalize(ev.speech_pcm)

    async def on_audio_end(self, attachment_ids: list[str] | None = None) -> None:
        """按键说话：松手强制断句，并把本次按键的所有片段合并成一轮发送。"""
        if not self._recording:
            return
        self._recording = False
        if self._recording_task and not self._recording_task.done():
            self._recording_task.cancel()
            self._recording_task = None
        ev = self.vad.force_end()
        if ev.kind == "speech_ended":
            await self._finalize(ev.speech_pcm)
        combined = " ".join(self._segments).strip()
        self._segments = []
        if not combined:
            await _safe_send(self.ws, events.server_note("没听清，再说一次？"))
            return
        await _safe_send(self.ws, events.stt_final(combined, self.ctx.stt_latency_ms))
        # 一次按键 = 一轮对话（由上层启动 run 任务）
        await self._on_final_text(combined, attachment_ids or [])

    async def _finalize(self, pcm: bytes) -> None:
        """识别一个 VAD 片段，累积到当前按键会话；实时把累计文本发给客户端显示。"""
        if self._partial_task:
            self._partial_task.cancel()
            self._partial_task = None
        # 不足 300ms 的"语音段"大概率是噪声误触发，不识别（SenseVoice 会对静音幻觉出词）
        if len(pcm) // 2 * 1000 // 16000 < 300:
            return
        started = time.monotonic()
        try:
            text = await asyncio.to_thread(self.stt.transcribe, pcm)
        except STTUnavailable as e:
            if not self._stt_error_sent:
                self._stt_error_sent = True
                await _safe_send(self.ws, events.error("stt_unavailable", str(e)))
            return
        self.ctx.stt_latency_ms = int((time.monotonic() - started) * 1000)
        text = (text or "").strip()
        if text:
            self._segments.append(text)
            await _safe_send(self.ws, events.stt_partial(" ".join(self._segments)))

    async def _start_partial_loop(self) -> None:
        interval = max(self.cfg.stt.partial_interval_ms, 300) / 1000
        if self._partial_task:
            self._partial_task.cancel()

        async def loop():
            try:
                while True:
                    await asyncio.sleep(interval)
                    pcm = self.vad.current_speech()
                    if len(pcm) // 2 * 1000 // 16000 < 600:  # <0.6s 不值得识别
                        continue
                    try:
                        text = await asyncio.to_thread(self.stt.transcribe, pcm)
                    except Exception:
                        continue
                    if text:
                        await _safe_send(self.ws, events.stt_partial(text))
            except asyncio.CancelledError:
                pass

        self._partial_task = asyncio.create_task(loop())

    async def _on_final_text(self, text: str, attachment_ids: list[str]) -> None:
        raise NotImplementedError  # 由 WS 处理器注入


@router.websocket("/ws/session")
async def ws_session(websocket: WebSocket) -> None:
    await websocket.accept()
    services = websocket.app.state.services
    cfg = services.config

    # 握手：首帧必须是 hello
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        hello = json.loads(raw)
    except Exception:
        await websocket.close(code=4400, reason="首帧必须是 hello JSON")
        return
    if hello.get("type") != "hello" or not check_token(hello.get("token", ""), cfg.server.token):
        await websocket.close(code=4401, reason="token 无效")
        return

    persona_name = hello.get("persona") or cfg.persona.default
    persona = services.persona.load(persona_name)
    mode = hello.get("mode", "text")
    ctx = SessionContext(
        conversation_id=hello.get("conversation_id") or new_conversation_id(),
        persona_name=persona_name,
        persona=persona,
        mode=mode,
        synth_tts=bool(hello.get("synth_tts", mode == "voice")),
        auto_run=bool(hello.get("auto_run", True)),
        tts_format=hello.get("tts_format", cfg.tts.format),
        tts_sample_rate=int(hello.get("tts_sample_rate", cfg.tts.sample_rate)),
        send_json=lambda p: _safe_send(websocket, p),
        send_audio=websocket.send_bytes,
    )
    active = _active_runs.get(ctx.conversation_id)
    if active is not None and not active.task.done():
        ctx = active.ctx
        ctx.send_json = lambda p: _safe_send(websocket, p)
        ctx.send_audio = websocket.send_bytes
        logger.info("重新接管运行中的会话: %s", ctx.conversation_id)
    await _safe_send(websocket, events.hello_ok(
        ctx.conversation_id, persona_name, ctx.tts_format, ctx.tts_sample_rate
    ))
    logger.info("会话建立: %s (mode=%s, persona=%s)", ctx.conversation_id, mode, persona_name)

    pipeline = AgentPipeline(services)
    voice = VoiceSession(ctx, services.stt, websocket, cfg)
    run_task: asyncio.Task | None = active.task if active is not None and not active.task.done() else None

    if run_task is not None:
        await _safe_send(websocket, events.progress("正在继续后台任务…"))
        # 新连接接管后台任务时回放已持久化的步骤，避免用户只看到“重连中”。
        if ctx.turn_id:
            with services.db() as db:
                trace = db.get(TurnTrace, ctx.turn_id)
            if trace is not None:
                try:
                    steps = json.loads(trace.steps_json or "[]")
                except json.JSONDecodeError:
                    steps = []
                for item in steps:
                    if not isinstance(item, dict):
                        continue
                    await _safe_send(websocket, events.process_step(
                        ctx.turn_id,
                        int(item.get("seq", 0)),
                        str(item.get("phase", "process")),
                        str(item.get("title", "处理中")),
                        str(item.get("detail", "")),
                        str(item.get("status", "done")),
                    ))

    def start_run(text: str, attachment_ids: list[str] | None = None) -> None:
        nonlocal run_task
        run_task = asyncio.create_task(pipeline.run(ctx, text, attachment_ids))
        _active_runs[ctx.conversation_id] = _ActiveRun(ctx, run_task)

        def _forget(done: asyncio.Task) -> None:
            current = _active_runs.get(ctx.conversation_id)
            if current is not None and current.task is done:
                _active_runs.pop(ctx.conversation_id, None)

        run_task.add_done_callback(_forget)

    async def on_final_text(text: str, attachment_ids: list[str]) -> None:
        # 静音/噪声幻觉兜底：纯标点或空白（如 "."、"。"）不当成输入
        t = (text or "").strip()
        if not t or not any(ch.isalnum() for ch in t):
            await _safe_send(websocket, events.server_note("没听清，再说一次？"))
            return
        if not ctx.auto_run:
            # 识别文本已通过 stt_final 送达客户端；等客户端确认/修改后发 text_input
            return
        if ctx.turn_running:
            await _safe_send(websocket, events.server_note("上一轮还没结束，先说一句打断再继续。"))
            return
        start_run(text, attachment_ids)

    voice._on_final_text = on_final_text  # 注入回调

    try:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            if frame.get("bytes") is not None:
                if mode == "voice":
                    await voice.on_audio(frame["bytes"])
                continue
            try:
                msg = json.loads(frame.get("text", "{}"))
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                await _safe_send(websocket, events.pong())
            elif mtype == "text_input":
                text = (msg.get("text") or "").strip()
                attachment_ids = msg.get("attachment_ids") or []
                if not isinstance(attachment_ids, list):
                    attachment_ids = []
                if not text:
                    if attachment_ids:
                        await _safe_send(
                            websocket,
                            events.server_note("请先输入或说出你希望如何处理附件，再一起发送"),
                        )
                    continue
                if ctx.turn_running:
                    await _safe_send(websocket, events.server_note("上一轮还没结束。"))
                    continue
                start_run(text, attachment_ids)
            elif mtype == "audio_start":
                voice.start_recording()
            elif mtype == "audio_end":
                attachment_ids = msg.get("attachment_ids") or []
                if not isinstance(attachment_ids, list):
                    attachment_ids = []
                await voice.on_audio_end(attachment_ids)
            elif mtype == "interrupt":
                if run_task and not run_task.done():
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                await _safe_send(websocket, events.server_note("已打断"))
            elif mtype == "user_action":
                await _safe_send(websocket, events.server_note("工具确认功能将在 MVP2 提供。"))
    except WebSocketDisconnect:
        pass
    finally:
        if run_task and not run_task.done():
            logger.info("连接断开，后台任务继续运行: %s", ctx.conversation_id)
        else:
            logger.info("会话结束: %s", ctx.conversation_id)
