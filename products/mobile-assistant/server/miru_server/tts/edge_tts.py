"""edge-tts 免费兜底（微软 Edge 音色，无 key）。可选依赖：pip install edge-tts。"""
from __future__ import annotations

import logging

from ..config import TTSConfig
from .base import TTSUnavailable, VoiceConfig

logger = logging.getLogger(__name__)

try:
    import edge_tts
    EDGE_AVAILABLE = True
except ImportError:
    edge_tts = None
    EDGE_AVAILABLE = False


class EdgeTTS:
    name = "edge"
    output_format = ("mp3", 24000)   # edge-tts 固定输出 24kHz mp3

    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg

    async def synthesize(self, text: str, voice: VoiceConfig) -> bytes:
        if not EDGE_AVAILABLE:
            raise TTSUnavailable("edge-tts 未安装（pip install edge-tts）")
        try:
            communicate = edge_tts.Communicate(text, voice=self.cfg.edge.voice)
            data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    data.extend(chunk["data"])
            return bytes(data)
        except Exception as e:
            raise TTSUnavailable(f"edge-tts 失败: {e}") from e
