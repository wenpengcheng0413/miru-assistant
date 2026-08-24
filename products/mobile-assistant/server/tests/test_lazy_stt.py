"""LazySTT：按需加载 + 闲置卸载（内存优化核心）。"""
import time

from miru_server.stt.lazy import LazySTT


class _FakeEngine:
    name = "fake"

    def __init__(self):
        self.loaded = True

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        return "你好"


def test_lazy_load_and_transcribe():
    created = []

    def factory():
        e = _FakeEngine()
        created.append(e)
        return e

    stt = LazySTT(factory, idle_unload_seconds=60)
    # 未加载时卸载调用是空操作
    assert stt.maybe_unload() is False
    # 首次 transcribe 才真正加载；之后复用同一个引擎
    assert stt.transcribe(b"") == "你好"
    assert len(created) == 1
    assert stt.transcribe(b"") == "你好"
    assert len(created) == 1


def test_idle_unload_and_reload():
    created = []

    def factory():
        e = _FakeEngine()
        created.append(e)
        return e

    stt = LazySTT(factory, idle_unload_seconds=0.05)
    stt.transcribe(b"")
    assert stt._engine is not None
    time.sleep(0.08)
    # 闲置超时 → 卸载
    assert stt.maybe_unload() is True
    assert stt._engine is None
    # 卸载后再次卸载是空操作
    assert stt.maybe_unload() is False
    # 再说话 → 自动重新加载
    assert stt.transcribe(b"") == "你好"
    assert len(created) == 2
