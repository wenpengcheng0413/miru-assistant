"""faster-whisper 兜底引擎（本机 V2 已有模型 data/models/faster-whisper-{small,tiny}）。

依赖：pip install faster-whisper（若本机 venv 已装则可直接使用）
"""
from __future__ import annotations

import io
import logging
import wave
from pathlib import Path

from ..config import STTConfig
from .base import STTUnavailable

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WhisperModel = None
    WHISPER_AVAILABLE = False


class WhisperSTT:
    name = "whisper"
    supports_partial = True
    is_local = True

    def __init__(self, cfg: STTConfig):
        if not WHISPER_AVAILABLE:
            raise STTUnavailable("faster-whisper 未安装（pip install faster-whisper）")
        model_dir = Path(cfg.whisper_model_dir) / f"faster-whisper-{cfg.whisper_model}"
        try:
            self._model = WhisperModel(
                str(model_dir), device="cpu", compute_type="int8", cpu_threads=cfg.num_threads
            )
        except Exception as e:
            raise STTUnavailable(f"faster-whisper 模型加载失败（{model_dir}）: {e}") from e
        self._model_name = cfg.whisper_model
        logger.info("faster-whisper-%s 已加载: %s", cfg.whisper_model, model_dir)

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        # faster-whisper 输入为 16k 单声道 PCM；直接喂 numpy 免写文件
        try:
            import numpy as np
            samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        except ImportError as e:
            raise STTUnavailable("numpy 未安装") from e
        segments, _ = self._model.transcribe(
            samples, language="zh", beam_size=1, vad_filter=True
        )
        return "".join(seg.text for seg in segments).strip()
