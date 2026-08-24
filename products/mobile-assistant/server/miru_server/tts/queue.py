"""TTS 句队列：保序合成 + 预取 1 句（合成第 N+1 句与手机播放第 N 句并行）。

每轮对话一个 TTSQueue 实例；enqueue 句子，drain 等全部发完。
句子合成失败：自动切兜底 provider（格式元信息按兜底实际输出上报，如 edge=mp3/24k）；
再失败只记日志（文字已在手机屏上，不丢信息）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from ..core.events import EventSink, sentence as sentence_event
from .base import TTSProvider, VoiceConfig

logger = logging.getLogger(__name__)

SENTINEL = None  # drain 信号


class TTSQueue:
    def __init__(
        self,
        sink: EventSink,
        provider: TTSProvider | None,
        fallback: TTSProvider | None,
        voice: VoiceConfig,
        audio_format: str,
        sample_rate: int,
        record_cost: Callable[[str, int], None] | None = None,
    ):
        self._sink = sink
        self._provider = provider
        self._fallback = fallback
        self._voice = voice
        self._fmt = audio_format
        self._rate = sample_rate
        self._record_cost = record_cost
        self._q: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None   # 惰性启动（构造时可能没有运行中的事件循环）
        self.enabled = provider is not None

    def _ensure_worker(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    def enqueue(self, text: str) -> None:
        text = text.strip()
        if text:
            self._q.put_nowait(text)   # 纯入队，不创建任务（可在同步上下文调用）

    async def drain(self) -> None:
        self._ensure_worker()          # 一定在运行中的事件循环内
        self._q.put_nowait(SENTINEL)
        await self._worker

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    async def _run(self) -> None:
        while True:
            item = await self._q.get()
            if item is SENTINEL:
                return
            # 预取：下一句的合成与当前句的发送并行。
            # 注意：预取若拿到哨兵必须放回队尾，留给下一轮循环退出（否则队列空等，drain 永远不返回）。
            nxt: str | None = None
            try:
                nxt = self._q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            if nxt is SENTINEL:
                self._q.put_nowait(SENTINEL)
                nxt = None
            prefetch = asyncio.create_task(self._synth(nxt)) if nxt is not None else None

            audio = await self._synth(item)
            if audio[0] is not None:
                await self._emit(item, audio)

            if prefetch is not None:
                try:
                    nxt_audio = await prefetch
                except Exception as e:
                    logger.warning("TTS 预取失败: %s", e)
                    nxt_audio = None
                if nxt_audio is not None and nxt_audio[0] is not None:
                    await self._emit(nxt, nxt_audio)

    async def _synth(self, text: str) -> tuple[bytes | None, str, int]:
        """返回 (音频, 实际格式, 实际采样率)。失败走兜底，兜底也失败返回 (None, ...)。

        合成成功即按实际使用的 provider 入账（MiniMax 花钱，edge 记 0 元可见"省了多少"）。
        """
        if self._provider is None:
            return None, self._fmt, self._rate
        try:
            audio = await self._provider.synthesize(text, self._voice)
            fmt, rate = getattr(self._provider, "output_format", (self._fmt, self._rate))
            if self._record_cost is not None:
                self._record_cost(self._provider.name, len(text))
            return audio, fmt, rate
        except Exception as e:
            logger.warning("TTS 合成失败（%s）: %s，尝试兜底", self._provider.name, e)
            if self._fallback is not None:
                try:
                    audio = await self._fallback.synthesize(text, self._voice)
                    fmt, rate = getattr(self._fallback, "output_format", ("mp3", 24000))
                    if self._record_cost is not None:
                        self._record_cost(self._fallback.name, len(text))
                    return audio, fmt, rate
                except Exception as e2:
                    logger.warning("兜底 TTS 也失败: %s", e2)
            return None, self._fmt, self._rate

    async def _emit(self, text: str, audio: tuple[bytes, str, int]) -> None:
        data, fmt, rate = audio
        await self._sink.send_json(sentence_event(text, fmt, rate))
        await self._sink.send_audio(data)
