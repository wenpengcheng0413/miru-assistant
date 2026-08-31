"""Phase 9 Cloud STT provider tests. All provider calls stay offline."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from miru_server.api.rest import build_safe_status
from miru_server.config import AppConfig
from miru_server.services import create_services
from miru_server.stt.base import STTUnavailable
from miru_server.stt.qwen_stt import QwenSTT
from miru_server.stt.tencent_stt import TencentSTT


def _qwen_config(tmp_path: Path | None = None) -> AppConfig:
    cfg = AppConfig.model_validate(
        {
            "profile": "cloud",
            "server": {"token": "test-token", "advertise_lan": True},
            "llm": {"api_key": "test-llm-key"},
            "stt": {
                "engine": "qwen",
                "language": "auto",
                "qwen": {
                    "base_url": "https://workspace.example.invalid/compatible-mode/v1",
                    "api_key": "test-stt-key",
                    "model": "qwen3-asr-flash",
                },
            },
            "tts": {"provider": "none"},
            "db": {"path": str((tmp_path / "test.db") if tmp_path else "test.db")},
        }
    )
    if tmp_path:
        cfg.project_dir = tmp_path
        cfg.config_dir = Path(__file__).resolve().parents[1] / "config"
    return cfg


def _tencent_config(tmp_path: Path | None = None) -> AppConfig:
    cfg = AppConfig.model_validate(
        {
            "profile": "cloud",
            "server": {"token": "test-token"},
            "llm": {"api_key": "test-llm-key"},
            "stt": {
                "engine": "tencent",
                "tencent": {
                    "endpoint": "https://asr.tencentcloudapi.com",
                    "secret_id": "AKID_TEST_ONLY",
                    "secret_key": "SECRET_TEST_ONLY",
                    "engine_model": "16k_zh-PY",
                    "billing_guard": "postpay-disabled",
                },
            },
            "tts": {"provider": "none"},
            "db": {"path": str((tmp_path / "test.db") if tmp_path else "test.db")},
        }
    )
    if tmp_path:
        cfg.project_dir = tmp_path
        cfg.config_dir = Path(__file__).resolve().parents[1] / "config"
    return cfg


def test_cloud_profile_preserves_external_stt_and_builds_lightweight_client(tmp_path):
    cfg = _qwen_config(tmp_path)
    assert cfg.stt.engine == "qwen"
    assert cfg.server.advertise_lan is False
    services = create_services(cfg)
    assert services.stt.name == "qwen3-asr-flash"
    assert services.stt.supports_partial is False
    assert services.stt.is_local is False
    status = build_safe_status(services)
    assert status["capabilities"]["stt"] == {
        "available": True,
        "location": "cloud",
        "provider": "qwen3-asr-flash",
        "reason": "",
    }


def test_cloud_stt_without_provider_credentials_is_unavailable(tmp_path):
    values = _qwen_config(tmp_path).model_dump(exclude={"config_dir", "project_dir"})
    values["stt"]["qwen"]["api_key"] = ""
    cfg = AppConfig.model_validate(values)
    cfg.project_dir = tmp_path
    cfg.config_dir = Path(__file__).resolve().parents[1] / "config"
    services = create_services(cfg)
    assert services.stt.name == "none"


def test_tencent_requires_credentials_and_explicit_postpay_guard(tmp_path):
    values = _tencent_config(tmp_path).model_dump(exclude={"config_dir", "project_dir"})
    values["stt"]["tencent"]["billing_guard"] = ""
    cfg = AppConfig.model_validate(values)
    cfg.project_dir = tmp_path
    cfg.config_dir = Path(__file__).resolve().parents[1] / "config"
    services = create_services(cfg)
    assert services.stt.name == "none"


def test_tencent_cloud_profile_builds_free_first_provider(tmp_path):
    services = create_services(_tencent_config(tmp_path))
    assert services.stt.name == "tencent-sentence-recognition"
    assert services.stt.supports_partial is False
    assert build_safe_status(services)["capabilities"]["stt"] == {
        "available": True,
        "location": "cloud",
        "provider": "tencent-sentence-recognition",
        "reason": "",
    }


def test_tencent_stt_signs_pcm_request_and_returns_text(monkeypatch):
    engine = TencentSTT(_tencent_config().stt)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Response": {"Result": "  腾讯云识别成功。  ", "RequestId": "safe-id"}
            }

    def fake_post(url, *, content, headers):
        captured.update(url=url, content=content, headers=headers)
        return Response()

    monkeypatch.setattr(engine._client, "post", fake_post)
    pcm = b"\x01\x00" * 1600
    assert engine.transcribe(pcm) == "腾讯云识别成功。"
    body = json.loads(captured["content"])
    assert base64.b64decode(body["Data"]) == pcm
    assert body["DataLen"] == len(pcm)
    assert body["VoiceFormat"] == "pcm"
    assert body["EngSerViceType"] == "16k_zh-PY"
    assert captured["headers"]["X-TC-Action"] == "SentenceRecognition"
    assert captured["headers"]["Authorization"].startswith("TC3-HMAC-SHA256 ")
    assert "SECRET_TEST_ONLY" not in captured["headers"]["Authorization"]


def test_tencent_stt_redacts_provider_failure(monkeypatch, caplog):
    engine = TencentSTT(_tencent_config().stt)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "Response": {
                    "Error": {
                        "Code": "FailedOperation.ServiceIsolate",
                        "Message": "SENSITIVE_PROVIDER_RESPONSE",
                    }
                }
            }

    monkeypatch.setattr(engine._client, "post", lambda *args, **kwargs: Response())
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(STTUnavailable, match="正在尝试本地节点"),
    ):
        engine.transcribe(b"\x01\x00" * 1600)
    assert "SENSITIVE_PROVIDER_RESPONSE" not in caplog.text


def test_qwen_stt_wraps_pcm_as_in_memory_wav_and_returns_text(monkeypatch):
    engine = QwenSTT(_qwen_config().stt)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="  欢迎使用 Miru。  ")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(engine._client.chat.completions, "create", fake_create)
    assert engine.transcribe(b"\x01\x00" * 1600) == "欢迎使用 Miru。"

    data_url = captured["messages"][0]["content"][0]["input_audio"]["data"]
    assert data_url.startswith("data:audio/wav;base64,")
    wav = base64.b64decode(data_url.split(",", 1)[1])
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav[:16]
    assert captured["extra_body"] == {"asr_options": {"enable_itn": True}}


def test_qwen_stt_redacts_provider_failure(monkeypatch, caplog):
    engine = QwenSTT(_qwen_config().stt)

    def fail(**kwargs):
        raise RuntimeError("SENSITIVE_PROVIDER_RESPONSE")

    monkeypatch.setattr(engine._client.chat.completions, "create", fail)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(STTUnavailable, match="云端语音识别暂时不可用"),
    ):
        engine.transcribe(b"\x01\x00" * 1600)
    assert "SENSITIVE_PROVIDER_RESPONSE" not in caplog.text


def test_production_manifest_does_not_activate_paid_stt_before_console_gate():
    repo = Path(__file__).resolve().parents[4]
    settings = (repo / "deploy/production/settings.production.yaml").read_text("utf-8")
    compose = (repo / "deploy/production/compose.production.yaml").read_text("utf-8")
    overlay = (repo / "deploy/Dockerfile.phase9-overlay").read_text("utf-8")
    assert "engine: none" in settings
    assert "engine: qwen" not in settings
    assert "stt_api_key" not in compose
    assert "speech_to_text" in settings
    assert "miru_server/stt/tencent_stt.py" in overlay
    assert "miru_server/api/ws.py" in overlay
    assert "miru_server/node_rpc.py" in overlay
