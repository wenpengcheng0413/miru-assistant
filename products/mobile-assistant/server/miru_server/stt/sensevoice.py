"""SenseVoice-Small 本地识别（sherpa-onnx，官方支持 Windows x64）。

单模型覆盖普通话/粤语/英语/日语/韩语，language="auto" 自动检测中粤英混合。
模型下载：scripts/download_sensevoice.py（走 hf-mirror 国内镜像）。

依赖：pip install sherpa-onnx numpy
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..config import STTConfig
from .base import STTUnavailable

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import sherpa_onnx
    SHERPA_AVAILABLE = True
except ImportError:
    np = None
    sherpa_onnx = None
    SHERPA_AVAILABLE = False


class SenseVoiceSTT:
    name = "sensevoice"

    def __init__(self, cfg: STTConfig):
        if not SHERPA_AVAILABLE:
            raise STTUnavailable("sherpa-onnx 未安装（pip install sherpa-onnx numpy）")
        model_dir = Path(cfg.model_dir)
        model_file = model_dir / "model.onnx"
        tokens_file = model_dir / "tokens.txt"
        if not model_file.exists() or not tokens_file.exists():
            raise STTUnavailable(
                f"SenseVoice 模型缺失: {model_dir}。"
                "运行 scripts/download_sensevoice.py 下载。"
            )
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_file),
            tokens=str(tokens_file),
            num_threads=cfg.num_threads,
            use_itn=True,
            language=cfg.language,
        )
        self._sample_rate = 16000
        logger.info("SenseVoice 模型已加载: %s（language=%s）", model_dir, cfg.language)

    def transcribe(self, pcm16: bytes, sample_rate: int = 16000) -> str:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != self._sample_rate:
            # 简化处理：非 16k 输入线性重采样（上行链路固定 16k，此分支为保险）
            samples = np.interp(
                np.linspace(0, len(samples) - 1, int(len(samples) * self._sample_rate / sample_rate)),
                np.arange(len(samples)), samples,
            ).astype(np.float32)
        stream = self._recognizer.create_stream()
        stream.accept_waveform(self._sample_rate, samples)
        self._recognizer.decode_stream(stream)
        return stream.result.text.strip()
