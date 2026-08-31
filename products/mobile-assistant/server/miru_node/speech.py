"""Bounded local SenseVoice transcription shared by Home Node capabilities."""

from __future__ import annotations

import threading
from typing import Any

_LOCK = threading.Lock()
_ENGINES: dict[str, Any] = {}


def sensevoice_engine(model_dir: str):
    with _LOCK:
        engine = _ENGINES.get(model_dir)
        if engine is not None:
            return engine
        from miru_server.config import STTConfig
        from miru_server.stt.sensevoice import SenseVoiceSTT

        engine = SenseVoiceSTT(
            STTConfig(
                engine="sensevoice",
                model_dir=model_dir,
                language="auto",
                num_threads=4,
            )
        )
        _ENGINES[model_dir] = engine
        return engine


def transcribe_pcm(pcm16: bytes, *, sample_rate: int, model_dir: str) -> str:
    if sample_rate != 16_000:
        raise ValueError("unsupported sample rate")
    if not pcm16 or len(pcm16) > 1_920_000:
        raise ValueError("invalid audio size")
    engine = sensevoice_engine(model_dir)
    # sherpa-onnx recognizers are not assumed to be thread-safe.
    with _LOCK:
        return str(engine.transcribe(pcm16, sample_rate) or "").strip()
