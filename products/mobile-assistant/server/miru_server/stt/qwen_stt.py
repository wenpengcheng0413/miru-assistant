"""Cloud STT using Alibaba Model Studio's Qwen ASR OpenAI-compatible API.

The mobile client sends raw mono PCM16.  Qwen accepts a base64 data URL, so
this adapter wraps the bytes as an in-memory WAV and never writes user audio
to disk.  Provider failures are deliberately redacted from logs and clients.
"""
from __future__ import annotations

import base64
import io
import logging
import wave

from openai import OpenAI

from ..config import STTConfig
from .base import STTUnavailable

logger = logging.getLogger(__name__)


def _pcm16_wav(pcm16: bytes, sample_rate: int) -> bytes:
    if not 8_000 <= sample_rate <= 48_000:
        raise STTUnavailable("音频采样率不受支持，请重新录音。")
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(pcm16)
        return buffer.getvalue()


class QwenSTT:
    name = "qwen3-asr-flash"
    # The selected HTTP model is utterance-level. Re-sending the growing audio
    # every 800 ms would multiply cost and leak partial provider failures.
    supports_partial = False
    is_local = False

    def __init__(self, cfg: STTConfig):
        provider = cfg.qwen
        if not provider.api_key or not provider.base_url:
            raise STTUnavailable("云端 STT Provider 尚未配置。")
        self._language = (cfg.language or "auto").strip().lower()
        self._enable_itn = provider.enable_itn
        self._model = provider.model
        self._client = OpenAI(
            api_key=provider.api_key,
            base_url=provider.base_url.rstrip("/"),
            timeout=provider.timeout_s,
            max_retries=1,
        )

    def transcribe(self, pcm16: bytes, sample_rate: int = 16_000) -> str:
        if not pcm16:
            return ""
        wav = _pcm16_wav(pcm16, sample_rate)
        data_url = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
        options: dict[str, object] = {"enable_itn": self._enable_itn}
        if self._language != "auto":
            options["language"] = self._language
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [{
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    }],
                }],
                stream=False,
                extra_body={"asr_options": options},
            )
            content = response.choices[0].message.content
            return content.strip() if isinstance(content, str) else ""
        except STTUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK exceptions vary by version
            logger.warning(
                "Cloud STT request failed: provider=qwen exception_type=%s",
                type(exc).__name__,
            )
            raise STTUnavailable("云端语音识别暂时不可用，请稍后重试。") from None
