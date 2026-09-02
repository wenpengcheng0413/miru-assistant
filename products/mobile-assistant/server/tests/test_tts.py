"""TTS 句队列与 MiniMax SSE 解析测试（FakeProvider，不联网）。"""
import asyncio
from types import SimpleNamespace

import pytest

from miru_server.config import TTSConfig
from miru_server.tts import edge_tts as edge_module
from miru_server.tts.base import TTSUnavailable, VoiceConfig
from miru_server.tts.edge_tts import EdgeTTS
from miru_server.tts.minimax_tts import MiniMaxTTS
from miru_server.tts.queue import TTSQueue
from miru_server.api.ws import _safe_send_audio


class FakeProvider:
    def __init__(self, outputs=None, fail=False, delay=0.0):
        self.name = "fake"
        self.calls: list[str] = []
        self.outputs = outputs or {}
        self.fail = fail
        self.delay = delay

    async def synthesize(self, text, voice):
        self.calls.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return self.outputs.get(text, text.encode())


class FakeSink:
    def __init__(self):
        self.json_events: list[dict] = []
        self.audio: list[bytes] = []

    async def send_json(self, payload):
        self.json_events.append(payload)

    async def send_audio(self, data):
        self.audio.append(data)


def run(coro):
    return asyncio.run(coro)


def test_closed_websocket_does_not_abort_background_tts_delivery():
    class ClosedWebSocket:
        async def send_bytes(self, _payload):
            raise RuntimeError('Cannot call send after close')

    # A transient iPhone disconnect must not turn a completed text response
    # into an unhandled background task failure.
    run(_safe_send_audio(ClosedWebSocket(), b'mp3'))


def test_queue_order_and_emit():
    provider = FakeProvider(delay=0.01)
    sink = FakeSink()
    q = TTSQueue(sink, provider, None, VoiceConfig(), "mp3", 32000)
    q.enqueue("第一句。")
    q.enqueue("第二句。")
    q.enqueue("第三句。")
    run(q.drain())
    texts = [e["text"] for e in sink.json_events if e["type"] == "sentence"]
    assert texts == ["第一句。", "第二句。", "第三句。"]   # 保序
    assert len(sink.audio) == 3
    assert sink.json_events[0]["audio_format"] == "mp3"
    assert provider.calls == ["第一句。", "第二句。", "第三句。"]


def test_queue_fallback_on_failure():
    fallback = FakeProvider(outputs={"你好。": b"edge-audio"})
    q = TTSQueue(FakeSink(), FakeProvider(fail=True), fallback, VoiceConfig(), "mp3", 32000)
    q.enqueue("你好。")
    run(q.drain())
    assert fallback.calls == ["你好。"]


def test_queue_no_provider_is_noop():
    sink = FakeSink()
    q = TTSQueue(sink, None, None, VoiceConfig(), "mp3", 32000)
    q.enqueue("没人听。")
    run(q.drain())
    assert sink.json_events == [] and sink.audio == []


def test_minimax_sse_hex_parsing():
    class FakeResp:
        async def aiter_lines(self):
            yield 'data: {"data":{"audio":"68656c6c6f"}}'
            yield "not-data-line"
            yield 'data: {"data":{"audio":"776f726c64","status":1}}'

    cfg = TTSConfig.model_validate({
        "provider": "minimax",
        "minimax": {"api_key": "k", "group_id": "g"},
    })
    tts = MiniMaxTTS(cfg)
    chunks = run(_collect(tts._iter_audio(FakeResp())))
    assert b"".join(chunks) == b"helloworld"


def test_edge_tts_fails_closed_when_dependency_is_missing(monkeypatch):
    monkeypatch.setattr(edge_module, "EDGE_AVAILABLE", False)
    with pytest.raises(TTSUnavailable, match="依赖未安装"):
        EdgeTTS(TTSConfig(provider="edge"))


def test_edge_tts_returns_bounded_audio_without_logging_text(monkeypatch):
    class FakeCommunicate:
        def __init__(self, text, voice):
            assert text == "这是敏感测试文本。"
            assert voice == "zh-CN-XiaoxiaoNeural"

        async def stream(self):
            yield {"type": "WordBoundary", "data": b"ignored"}
            yield {"type": "audio", "data": b"mp3-audio"}

    monkeypatch.setattr(edge_module, "EDGE_AVAILABLE", True)
    monkeypatch.setattr(
        edge_module,
        "edge_tts",
        SimpleNamespace(Communicate=FakeCommunicate),
    )
    provider = EdgeTTS(TTSConfig(provider="edge"))
    assert run(provider.synthesize("这是敏感测试文本。", VoiceConfig())) == b"mp3-audio"


def test_edge_tts_rejects_empty_audio_and_redacts_provider_error(monkeypatch):
    class EmptyCommunicate:
        def __init__(self, text, voice):
            pass

        async def stream(self):
            if False:
                yield {}

    class FailingCommunicate:
        def __init__(self, text, voice):
            pass

        async def stream(self):
            raise RuntimeError("SENSITIVE_REMOTE_RESPONSE")
            yield {}

    monkeypatch.setattr(edge_module, "EDGE_AVAILABLE", True)
    monkeypatch.setattr(
        edge_module,
        "edge_tts",
        SimpleNamespace(Communicate=EmptyCommunicate),
    )
    provider = EdgeTTS(TTSConfig(provider="edge"))
    with pytest.raises(TTSUnavailable, match="返回空音频"):
        run(provider.synthesize("你好", VoiceConfig()))

    monkeypatch.setattr(
        edge_module,
        "edge_tts",
        SimpleNamespace(Communicate=FailingCommunicate),
    )
    with pytest.raises(TTSUnavailable, match="暂时不可用") as exc:
        run(provider.synthesize("不要泄露", VoiceConfig()))
    assert "SENSITIVE_REMOTE_RESPONSE" not in str(exc.value)


def test_production_manifest_activates_free_edge_tts():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[4]
    settings = (repo / "deploy/production/settings.production.yaml").read_text("utf-8")
    requirements = (repo / "deploy/requirements-cloud.txt").read_text("utf-8")
    overlay = (repo / "deploy/Dockerfile.phase9-overlay").read_text("utf-8")
    assert "provider: edge" in settings
    assert "voice: zh-CN-XiaoxiaoNeural" in settings
    assert "timeout_s: 20" in settings
    assert "edge-tts==7.2.8" in requirements
    assert "edge-tts==7.2.8" in overlay
    assert "miru_server/tts/edge_tts.py" in overlay


async def _collect(gen):
    return [c async for c in gen]
