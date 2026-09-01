"""edge-tts 免费在线语音（微软 Edge 音色，无 key、无计费凭据）。"""
from __future__ import annotations

import asyncio

from ..config import TTSConfig
from .base import TTSUnavailable, VoiceConfig

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
        if not EDGE_AVAILABLE:
            raise TTSUnavailable("edge-tts 依赖未安装")
        self.cfg = cfg

    async def synthesize(self, text: str, voice: VoiceConfig) -> bytes:
        text = text.strip()
        if not text:
            raise TTSUnavailable("TTS 文本为空")
        try:
            communicate = edge_tts.Communicate(text, voice=self.cfg.edge.voice)
            data = bytearray()
            async with asyncio.timeout(self.cfg.edge.timeout_s):
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        data.extend(chunk["data"])
            if not data:
                raise TTSUnavailable("edge-tts 返回空音频")
            return bytes(data)
        except TTSUnavailable:
            raise
        except Exception:
            # 第三方异常可能携带请求细节；不要把文本或远端消息带进日志/API。
            raise TTSUnavailable("edge-tts 暂时不可用") from None
