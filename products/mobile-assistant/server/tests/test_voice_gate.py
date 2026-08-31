"""语音协议闸门测试：没有 audio_start 的音频一律丢弃，不触发识别。"""
import asyncio
import math
import struct
from types import SimpleNamespace

import pytest

from miru_server.api.ws import VoiceSession
from miru_server.config import AppConfig
from miru_server.core.pipeline import SessionContext
from miru_server.stt.base import NoneSTT, STTUnavailable


class _FakeWS:
    """VoiceSession 只用到 send_json/send_bytes，两处都不需要真的发。"""

    async def send_json(self, payload: dict) -> None:
        pass

    async def send_bytes(self, data: bytes) -> None:
        pass


class _FakeSTT:
    name = "fake"
    supports_partial = True

    def __init__(self):
        self.calls = 0

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        self.calls += 1
        return "测试"


def _sine_pcm(seconds: float = 1.5, freq: float = 440.0) -> bytes:
    """16kHz 单声道 PCM16 正弦波（响亮，足以触发能量 VAD）。"""
    rate = 16000
    n = int(rate * seconds)
    frames = []
    for i in range(n):
        frames.append(struct.pack("<h", int(20000 * math.sin(2 * math.pi * freq * i / rate))))
    return b"".join(frames)


def _make_session(timeout: float = 20.0):
    cfg = AppConfig()
    ctx = SessionContext(conversation_id="t", persona_name="p", persona=None, mode="voice")
    stt = _FakeSTT()
    voice = VoiceSession(ctx, stt, _FakeWS(), cfg, recording_timeout=timeout)

    async def _noop_final(text: str, attachment_ids: list[str]) -> None:
        pass

    voice._on_final_text = _noop_final   # 生产环境由 WS 处理器注入
    return stt, voice


async def test_audio_ignored_until_audio_start():
    stt, voice = _make_session()
    pcm = _sine_pcm()
    # 未发 audio_start：音频帧全部丢弃，绝不识别
    await voice.on_audio(pcm)
    await voice.on_audio_end()
    assert stt.calls == 0
    assert voice._recording is False


async def test_recording_window_transcribes():
    stt, voice = _make_session()
    pcm = _sine_pcm()
    voice.start_recording()
    assert voice._recording is True
    await voice.on_audio(pcm)
    await voice.on_audio_end()
    assert stt.calls == 1
    assert voice._recording is False
    # 松手后的野音频继续被忽略
    await voice.on_audio(pcm)
    assert stt.calls == 1


async def test_watchdog_closes_window_and_discards():
    stt, voice = _make_session(timeout=0.2)
    pcm = _sine_pcm()
    voice.start_recording()
    await voice.on_audio(pcm)
    await asyncio.sleep(0.35)          # 超过看门狗时限，客户端"消失"了
    assert voice._recording is False   # 闸门已自动关闭
    assert stt.calls == 0              # 缓冲被丢弃，不识别
    await voice.on_audio_end()         # 迟到的 audio_end 也无害
    assert stt.calls == 0


async def test_hold_merges_segments_into_one_turn():
    """一次按键 = 一轮对话：中间停顿断句不触发多轮，全部片段松手时合并。"""
    stt, voice = _make_session()
    finals = []

    async def collect(text: str, attachment_ids: list[str]) -> None:
        finals.append((text, attachment_ids))

    voice._on_final_text = collect
    voice.start_recording()
    await voice.on_audio(_sine_pcm(1.0))        # 第一段
    await voice.on_audio(b"\x00\x00" * 8000)    # 0.5s 静音 → 断句
    await voice.on_audio(_sine_pcm(1.0))        # 第二段
    assert finals == []                          # 按住期间不触发任何一轮
    await voice.on_audio_end(["attachment-1"])
    assert len(finals) == 1                      # 松手合并成一轮
    assert finals[0] == ("测试 测试", ["attachment-1"])


async def test_non_streaming_cloud_stt_does_not_start_repeated_partial_calls():
    stt, voice = _make_session()
    stt.supports_partial = False
    await voice._start_partial_loop()
    assert voice._partial_task is None


async def test_home_node_stt_is_used_when_cloud_provider_is_unavailable():
    cfg = AppConfig()
    ctx = SessionContext(conversation_id="t", persona_name="p", persona=None, mode="voice")

    class Registry:
        def snapshot(self):
            return SimpleNamespace(state="online", capabilities=("speech_to_text",))

    class Rpc:
        async def execute(self, tool_name, args, *, timeout_s):
            assert tool_name == "speech_to_text"
            assert args["sample_rate"] == 16_000
            assert timeout_s == 45
            return {"ok": True, "data": {"text": "家庭节点识别成功"}}

    voice = VoiceSession(
        ctx,
        NoneSTT(),
        _FakeWS(),
        cfg,
        node_rpc=Rpc(),
        home_node=Registry(),
    )
    assert await voice._transcribe(b"\x01\x00" * 1600) == "家庭节点识别成功"


async def test_stt_reports_stable_error_when_cloud_and_node_are_unavailable():
    cfg = AppConfig()
    ctx = SessionContext(conversation_id="t", persona_name="p", persona=None, mode="voice")
    voice = VoiceSession(ctx, NoneSTT(), _FakeWS(), cfg)
    with pytest.raises(STTUnavailable, match="家庭节点"):
        await voice._transcribe(b"\x01\x00" * 1600)
