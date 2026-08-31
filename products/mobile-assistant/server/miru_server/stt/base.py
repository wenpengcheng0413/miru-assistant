"""STT engine protocol and factory for local and explicit cloud providers."""
from __future__ import annotations

import logging
from typing import Protocol

from ..config import STTConfig

logger = logging.getLogger(__name__)


class STTUnavailable(Exception):
    pass


class STTEngine(Protocol):
    name: str
    supports_partial: bool
    is_local: bool

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str: ...


class NoneSTT:
    """纯文本模式：无语音识别能力。"""

    name = "none"
    supports_partial = False
    is_local = True

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        raise STTUnavailable(
            "STT 未启用或 Provider 未配置。请在服务端配置可用的语音识别 Provider。"
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
    if cfg.engine == "qwen":
        from .qwen_stt import QwenSTT
        return QwenSTT(cfg)
    if cfg.engine == "tencent":
        from .tencent_stt import TencentSTT
        return TencentSTT(cfg)
    logger.warning("未知 stt.engine=%s，回退到 none", cfg.engine)
    return NoneSTT()
