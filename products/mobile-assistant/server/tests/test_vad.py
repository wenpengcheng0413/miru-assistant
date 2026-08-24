"""能量法 VAD 测试：静音校准 → 说话开始 → 尾静音断句。"""
import math
import struct

from miru_server.stt.vad import EnergyVAD


def gen_silence(ms: int) -> bytes:
    return b"\x00\x00" * (ms * 16)


def gen_tone(ms: int, freq: float = 440.0, amp: int = 8000) -> bytes:
    n = ms * 16
    return struct.pack(f"<{n}h", *[
        int(amp * math.sin(2 * math.pi * freq * i / 16000)) for i in range(n)
    ])


def test_silence_then_speech_then_end():
    vad = EnergyVAD()
    cfg = vad.cfg
    # 前 600ms 静音校准
    assert vad.process(gen_silence(100)).kind == "none"
    assert vad.process(gen_silence(200)).kind == "none"
    assert vad.process(gen_silence(300)).kind == "none"
    # 说话 ≥ min_speech_ms
    ev = vad.process(gen_tone(400))
    assert ev.kind == "speech_started"
    # 尾静音 ≥ min_silence_ms → 断句
    ev = vad.process(gen_silence(cfg.min_silence_ms + 100))
    assert ev.kind == "speech_ended"
    assert len(ev.speech_pcm) >= 400 * 32   # 0.4s × 16k × 2 字节


def test_too_short_utterance_ignored():
    vad = EnergyVAD()
    vad.process(gen_silence(500))          # 校准
    ev = vad.process(gen_tone(100))        # < min_speech_ms 不起振
    assert ev.kind == "none"


def test_force_end():
    vad = EnergyVAD()
    vad.process(gen_silence(500))
    vad.process(gen_tone(400))
    ev = vad.force_end()
    assert ev.kind == "speech_ended"


def test_force_end_without_speech_is_none():
    vad = EnergyVAD()
    vad.process(gen_silence(500))
    assert vad.force_end().kind == "none"
