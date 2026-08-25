"""WS 事件模型：服务端 → 手机端的下行事件（协议见 docs/02-流式管线与通信协议.md §3.3）。"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Protocol

# 事件发送接口：WS 适配层实现（send_json→文本帧，send_audio→二进制帧）
EventSinkFn = Callable[[dict], Awaitable[None]]


class EventSink(Protocol):
    async def send_json(self, payload: dict) -> None: ...
    async def send_audio(self, data: bytes) -> None: ...


def event(payload: dict) -> dict:
    """带 type 字段的 JSON 事件构造。"""
    return payload


def hello_ok(session_id: str, persona: str, tts_format: str, sample_rate: int) -> dict:
    return event({
        "type": "hello_ok",
        "session_id": session_id,
        "persona": persona,
        "tts": {"format": tts_format, "sample_rate": sample_rate},
    })


def stt_partial(text: str) -> dict:
    return event({"type": "stt_partial", "text": text})


def stt_final(text: str, latency_ms: int) -> dict:
    return event({"type": "stt_final", "text": text, "latency_ms": latency_ms})


def user_text(text: str, turn_id: str = "") -> dict:
    return event({"type": "user_text", "text": text, "turn_id": turn_id})


def llm_delta(text: str) -> dict:
    return event({"type": "llm_delta", "text": text})


def progress(text: str, phase: str = "thinking") -> dict:
    """可重放的运行状态；用于在模型暂时没有 token 时证明任务仍在运行。"""
    return event({"type": "progress", "text": text, "phase": phase})


def process_step(
    turn_id: str,
    seq: int,
    phase: str,
    title: str,
    detail: str = "",
    status: str = "running",
) -> dict:
    return event({
        "type": "process_step",
        "turn_id": turn_id,
        "seq": seq,
        "phase": phase,
        "title": title,
        "detail": detail,
        "status": status,
    })


def sentence(text: str, audio_format: str, sample_rate: int, channels: int = 1) -> dict:
    return event({
        "type": "sentence",
        "text": text,
        "audio_format": audio_format,
        "sample_rate": sample_rate,
        "channels": channels,
    })


def tool_start(call_id: str, name: str, args: dict) -> dict:
    return event({"type": "tool_start", "id": call_id, "name": name, "args": args})


def tool_end(
    call_id: str,
    name: str,
    ok: bool,
    summary: str,
    duration_ms: int,
    error: str = "",
) -> dict:
    payload = {
        "type": "tool_end",
        "id": call_id, "name": name,
        "ok": ok, "summary": summary, "duration_ms": duration_ms,
    }
    if error:
        payload["error"] = error
    return event(payload)


def turn_end(
    usage: dict,
    cost_rmb: float,
    turn_id: str = "",
    duration_ms: int = 0,
) -> dict:
    return event({
        "type": "turn_end",
        "turn_id": turn_id,
        "usage": usage,
        "duration_ms": duration_ms,
        "cost_rmb": round(cost_rmb, 4),
    })


def server_note(text: str, level: str = "info") -> dict:
    return event({"type": "server_note", "text": text, "level": level})


def error(code: str, message: str) -> dict:
    return event({"type": "error", "code": code, "message": message})


def pong() -> dict:
    return event({"type": "pong"})


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
