"""按需加载 / 闲置卸载的 STT 包装器。

SenseVoice 模型常驻内存约 0.9GB——服务器空闲时没必要一直扛着。
首次 transcribe 时才真正加载（第一次识别会多等 1~3 秒），
连续 idle_unload_seconds 没有使用后由后台任务调用 maybe_unload() 卸载，
把内存还给系统（再说话时自动重新加载）。
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Callable

from .base import STTEngine

logger = logging.getLogger(__name__)


class LazySTT:
    """包装真实 STT 引擎：延迟创建 + 闲置卸载。对外只暴露 transcribe/maybe_unload。"""

    name = "lazy"
    supports_partial = True
    is_local = True

    def __init__(
        self,
        factory: Callable[[], STTEngine],
        idle_unload_seconds: float = 300.0,
    ):
        self._factory = factory
        self._idle = idle_unload_seconds
        self._engine: STTEngine | None = None
        self._lock = threading.Lock()
        self._last_used = 0.0

    def _load(self) -> STTEngine:
        with self._lock:
            if self._engine is None:
                t0 = time.monotonic()
                self._engine = self._factory()
                logger.info(
                    "STT 引擎已加载（%.1fs，首次识别会慢一点）",
                    time.monotonic() - t0,
                )
            return self._engine

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        engine = self._load()
        self._last_used = time.monotonic()
        return engine.transcribe(pcm16, sample_rate)

    def maybe_unload(self) -> bool:
        """闲置超过阈值则卸载引擎（释放 ~0.9GB）；返回是否发生了卸载。"""
        if self._engine is None:
            return False
        if time.monotonic() - self._last_used <= self._idle:
            return False
        with self._lock:
            if self._engine is None:  # 双检：拿到锁时可能已被其他路径处理
                return False
            self._engine = None
        gc.collect()
        logger.info("STT 引擎已闲置卸载，内存已释放")
        return True
