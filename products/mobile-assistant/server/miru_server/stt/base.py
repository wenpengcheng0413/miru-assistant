"""STT 引擎接口与工厂。全部本地运行（用户语音不出本机）。"""
from __future__ import annotations

import logging
from typing import Protocol

from ..config import STTConfig

logger = logging.getLogger(__name__)


class STTUnavailable(Exception):
    pass


class STTEngine(Protocol):
    name: str

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str: ...


class NoneSTT:
    """纯文本模式：无语音识别能力。"""

    name = "none"

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        raise STTUnavailable(
            "本地 STT 未启用（settings.yaml → stt.engine: none）。"
            "运行 scripts/download_sensevoice.py 下载模型后设为 sensevoice。"
        )


def create_stt(cfg: STTConfig) -> STTEngine:
    if cfg.engine == "none":
        return NoneSTT()
    if cfg.engine == "sensevoice":
        from .sensevoice import SenseVoiceSTT
        return SenseVoiceSTT(cfg)
    if cfg.engine == "whisper":
        from .whisper_stt import WhisperSTT
        return WhisperSTT(cfg)
    logger.warning("未知 stt.engine=%s，回退到 none", cfg.engine)
    return NoneSTT()
