"""VAD 断句：能量法（零依赖）。引擎字段预留 silero（升级位）。

状态机：SILENCE → (连续 min_speech_ms 高于阈值) → SPEECH
        SPEECH → (连续 min_silence_ms 低于阈值 或 超 max_utterance_ms) → 断句
"""
from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from enum import Enum

from ..config import VADConfig

logger = logging.getLogger(__name__)


class VADState(Enum):
    SILENCE = "silence"
    SPEECH = "speech"


@dataclass
class VADEvent:
    kind: str                      # speech_started | speech_ended(带 text 缓冲) | none
    speech_pcm: bytes = b""        # 本次说话片段的全部 PCM（16k）

    @classmethod
    def none(cls) -> "VADEvent":
        return cls(kind="none")


@dataclass
class EnergyVAD:
    cfg: VADConfig = field(default_factory=VADConfig)
    sample_rate: int = 16000
    _state: VADState = field(default=VADState.SILENCE, init=False)
    _speech_ms: int = field(default=0, init=False)      # 当前连续说话时长
    _silence_ms: int = field(default=0, init=False)     # 当前连续静音时长
    _noise_floor: float = field(default=1e-6, init=False)  # 自适应噪声底
    _calibrated: int = field(default=0, init=False)     # 已校准帧数
    _speech_buf: list[bytes] = field(default_factory=list, init=False)

    def process(self, pcm16: bytes) -> VADEvent:
        if not pcm16:
            return VADEvent.none()
        frame_ms = len(pcm16) // 2 * 1000 // self.sample_rate
        rms = self._rms(pcm16)

        # 前 500ms 校准噪声底（指数平均）
        if self._calibrated * frame_ms < 500:
            self._noise_floor = 0.9 * self._noise_floor + 0.1 * rms
            self._calibrated += 1
        threshold = self._noise_floor * (10 ** (self.cfg.threshold_db / 20))
        voiced = rms > threshold

        if self._state is VADState.SILENCE:
            if voiced:
                self._speech_ms += frame_ms
                self._silence_ms = 0
                self._speech_buf.append(pcm16)
                if self._speech_ms >= self.cfg.min_speech_ms:
                    self._state = VADState.SPEECH
                    return VADEvent(kind="speech_started", speech_pcm=b"".join(self._speech_buf))
            else:
                self._speech_ms = 0
            return VADEvent.none()

        # SPEECH 状态
        if voiced:
            self._speech_ms += frame_ms
            self._silence_ms = 0
            self._speech_buf.append(pcm16)
            if self._speech_ms >= self.cfg.max_utterance_ms:   # 上限强制断句
                return self._end()
            return VADEvent.none()

        self._silence_ms += frame_ms
        if self._silence_ms >= self.cfg.min_silence_ms:
            return self._end()
        # 停顿期间音频也算说话内容（保留自然停顿），继续收集
        self._speech_ms += frame_ms
        self._speech_buf.append(pcm16)
        return VADEvent.none()

    def force_end(self) -> VADEvent:
        """按键式说话：松手强制断句（有语音内容才返回 ended）。"""
        if self._state is VADState.SPEECH:
            return self._end()
        return VADEvent.none()

    def current_speech(self) -> bytes:
        """当前正在说的话（部分识别用）。"""
        return b"".join(self._speech_buf)

    def _end(self) -> VADEvent:
        pcm = b"".join(self._speech_buf)
        self._speech_buf = []
        self._speech_ms = 0
        self._silence_ms = 0
        self._state = VADState.SILENCE
        if len(pcm) // 2 * 1000 // self.sample_rate < self.cfg.min_speech_ms:
            return VADEvent.none()   # 太短，误触
        return VADEvent(kind="speech_ended", speech_pcm=pcm)

    @staticmethod
    def _rms(pcm16: bytes) -> float:
        count = len(pcm16) // 2
        if count == 0:
            return 0.0
        samples = struct.unpack(f"<{count}h", pcm16)
        return (sum(s * s for s in samples) / count) ** 0.5
