"""TTS Provider 接口与工厂。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..config import TTSConfig


@dataclass
class VoiceConfig:
    """音色参数（来自 persona.voice + 全局默认）。"""
    voice_id: str = "Calm_Woman"
    speed: float = 1.0
    emotion: str = "neutral"
    provider: str = ""   # persona 级 TTS 提供商标识（预留，当前用全局 tts.provider）


class TTSProvider(Protocol):
    """按句合成。返回整句音频 bytes；失败抛 TTSUnavailable。"""

    name: str
    output_format: tuple[str, int]   # (格式, 采样率)，如 ("mp3", 32000)

    async def synthesize(self, text: str, voice: VoiceConfig) -> bytes: ...


class TTSUnavailable(Exception):
    pass


def create_provider(cfg: TTSConfig) -> TTSProvider | None:
    """按配置创建主 Provider；provider=none 返回 None（纯文字模式）。"""
    if cfg.provider == "minimax":
        from .minimax_tts import MiniMaxTTS
        return MiniMaxTTS(cfg)
    if cfg.provider == "edge":
        from .edge_tts import EdgeTTS
        return EdgeTTS(cfg)
    return None


def create_fallback_provider(cfg: TTSConfig) -> TTSProvider | None:
    """兜底 Provider：minimax 挂了切 edge-tts。"""
    if cfg.provider == "minimax" and cfg.fallback_to_edge:
        from .edge_tts import EdgeTTS
        return EdgeTTS(cfg)
    return None
