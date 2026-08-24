"""TTS 句队列与 MiniMax SSE 解析测试（FakeProvider，不联网）。"""
import asyncio

from miru_server.config import TTSConfig
from miru_server.tts.base import VoiceConfig
from miru_server.tts.minimax_tts import MiniMaxTTS
from miru_server.tts.queue import TTSQueue


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


async def _collect(gen):
    return [c async for c in gen]
