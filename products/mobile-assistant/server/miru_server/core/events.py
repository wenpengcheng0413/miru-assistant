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


def user_text(text: str) -> dict:
    return event({"type": "user_text", "text": text})


def llm_delta(text: str) -> dict:
    return event({"type": "llm_delta", "text": text})


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


def tool_end(call_id: str, name: str, ok: bool, summary: str, duration_ms: int) -> dict:
    return event({
        "type": "tool_end",
        "id": call_id, "name": name,
        "ok": ok, "summary": summary, "duration_ms": duration_ms,
    })


def turn_end(usage: dict, cost_rmb: float) -> dict:
    return event({"type": "turn_end", "usage": usage, "cost_rmb": round(cost_rmb, 4)})


def server_note(text: str, level: str = "info") -> dict:
    return event({"type": "server_note", "text": text, "level": level})


def error(code: str, message: str) -> dict:
    return event({"type": "error", "code": code, "message": message})


def pong() -> dict:
    return event({"type": "pong"})


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
