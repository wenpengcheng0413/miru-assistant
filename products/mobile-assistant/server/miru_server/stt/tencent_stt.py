"""Tencent Cloud one-sentence ASR using the official TC3 signature protocol."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from ..config import STTConfig
from .base import STTUnavailable

logger = logging.getLogger(__name__)

_ACTION = "SentenceRecognition"
_VERSION = "2019-06-14"
_SERVICE = "asr"
_CONTENT_TYPE = "application/json; charset=utf-8"
_MAX_PCM_BYTES = 1_920_000  # 60 seconds of mono PCM16 at 16 kHz


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _authorization(
    *, secret_id: str, secret_key: str, host: str, payload: bytes, timestamp: int
) -> str:
    date = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d")
    canonical_headers = f"content-type:{_CONTENT_TYPE}\nhost:{host}\n"
    signed_headers = "content-type;host"
    canonical_request = (
        f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{_sha256(payload)}"
    )
    credential_scope = f"{date}/{_SERVICE}/tc3_request"
    string_to_sign = (
        "TC3-HMAC-SHA256\n"
        f"{timestamp}\n{credential_scope}\n"
        f"{_sha256(canonical_request.encode('utf-8'))}"
    )
    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, _SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


class TencentSTT:
    name = "tencent-sentence-recognition"
    supports_partial = False
    is_local = False

    def __init__(self, cfg: STTConfig):
        provider = cfg.tencent
        parsed = urlparse(provider.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
        ):
            raise STTUnavailable("腾讯云 STT 接口地址无效。")
        if not provider.secret_id or not provider.secret_key:
            raise STTUnavailable("腾讯云 STT 凭据尚未配置。")
        if provider.billing_guard != "postpay-disabled":
            raise STTUnavailable("腾讯云 STT 尚未确认关闭后付费。")
        self._endpoint = provider.endpoint.rstrip("/")
        self._host = parsed.hostname
        self._secret_id = provider.secret_id
        self._secret_key = provider.secret_key
        self._engine_model = provider.engine_model
        self._client = httpx.Client(timeout=provider.timeout_s)

    def transcribe(self, pcm16: bytes, sample_rate: int = 16_000) -> str:
        if not pcm16:
            return ""
        if sample_rate != 16_000:
            raise STTUnavailable("腾讯云免费识别链路仅接受 16kHz 录音。")
        if len(pcm16) > _MAX_PCM_BYTES:
            raise STTUnavailable("录音超过 60 秒限制，请缩短后重试。")
        body = {
            "EngSerViceType": self._engine_model,
            "SourceType": 1,
            "VoiceFormat": "pcm",
            "Data": base64.b64encode(pcm16).decode("ascii"),
            "DataLen": len(pcm16),
        }
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        timestamp = int(time.time())
        headers = {
            "Authorization": _authorization(
                secret_id=self._secret_id,
                secret_key=self._secret_key,
                host=self._host,
                payload=payload,
                timestamp=timestamp,
            ),
            "Content-Type": _CONTENT_TYPE,
            "Host": self._host,
            "X-TC-Action": _ACTION,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": _VERSION,
        }
        try:
            response = self._client.post(
                self._endpoint, content=payload, headers=headers
            )
            response.raise_for_status()
            result = response.json().get("Response", {})
            if not isinstance(result, dict):
                raise TypeError("invalid_response")
            error = result.get("Error")
            if isinstance(error, dict):
                logger.warning(
                    "Cloud STT request failed: provider=tencent error_code=%s",
                    str(error.get("Code") or "unknown")[:96],
                )
                raise STTUnavailable("腾讯云免费语音识别暂时不可用，正在尝试本地节点。")
            text = result.get("Result", "")
            return text.strip() if isinstance(text, str) else ""
        except STTUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - HTTP/JSON failures share a safe client error
            logger.warning(
                "Cloud STT request failed: provider=tencent exception_type=%s",
                type(exc).__name__,
            )
            raise STTUnavailable(
                "腾讯云免费语音识别暂时不可用，正在尝试本地节点。"
            ) from None
