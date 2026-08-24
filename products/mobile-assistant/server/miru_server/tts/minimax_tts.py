"""MiniMax T2A v2 流式合成（HTTP SSE，音频块为 hex 编码）。

接口要点（2026-08）：
- POST {base_url}/v1/t2a_v2，Authorization: Bearer <api_key>?GroupId=<group_id>
- stream: true 时响应为 SSE 行：data: {"data":{"audio":"<hex>","status":1},...}
  最后一个块的 status=2（配 stream_options.exclude_aggregated_audio 后无整段重复）
- audio_setting.format: mp3 / pcm / flac；mp3 为手机端 MVP 格式
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from ..config import TTSConfig
from .base import TTSUnavailable, VoiceConfig

logger = logging.getLogger(__name__)


class MiniMaxTTS:
    name = "minimax"

    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg
        m = cfg.minimax
        self.base_url = m.base_url.rstrip("/")
        self.model = m.model
        self.api_key = m.api_key
        self.group_id = m.group_id
        self.output_format = (cfg.format, cfg.sample_rate)

    def _headers(self) -> dict:
        # MiniMax 特有：GroupId 拼在 Authorization 里（以官方当前文档为准，见 README 注记）
        return {"Authorization": f"Bearer {self.api_key}?GroupId={self.group_id}"}

    def _payload(self, text: str, voice: VoiceConfig, fmt: str, sample_rate: int) -> dict:
        payload = {
            "model": self.model,
            "text": text,
            "stream": True,
            "stream_options": {"exclude_aggregated_audio": True},
            "audio_setting": {
                "format": fmt,
                "sample_rate": sample_rate,
                "bitrate": 128000,
                "channel": 1,
                "voice_id": voice.voice_id,
            },
            "voice_setting": {"speed": voice.speed, "emotion": voice.emotion},
        }
        return payload

    async def synthesize(self, text: str, voice: VoiceConfig) -> bytes:
        if not self.api_key:
            raise TTSUnavailable("MiniMax API key 未配置")
        fmt = self.cfg.format
        sample_rate = self.cfg.sample_rate
        url = f"{self.base_url}/v1/t2a_v2"
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream(
                "POST", url, headers=self._headers(),
                json=self._payload(text, voice, fmt, sample_rate),
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise TTSUnavailable(f"MiniMax HTTP {resp.status_code}: {body}")
                chunks = [c async for c in self._iter_audio(resp)]
        if not chunks:
            raise TTSUnavailable("MiniMax 返回空音频")
        return b"".join(chunks)

    async def _iter_audio(self, resp: httpx.Response) -> AsyncIterator[bytes]:
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
                audio_hex = (obj.get("data") or {}).get("audio")
                if audio_hex:
                    yield bytes.fromhex(audio_hex)
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug("无法解析 SSE 行: %s (%s)", line[:80], e)
