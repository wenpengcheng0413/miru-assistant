"""
Miru Assistant — Chat Analyzer 语音转写引擎。

faster-whisper 封装（本地推理，CPU int8）+ 磁盘缓存。

模型文件位置（从 HuggingFace 镜像下载后放置）:
    data/models/faster-whisper-<name>/model.bin ...

首次使用需要模型文件。提供 download_model() 便捷函数
从 hf-mirror.com 下载（新版 huggingface_hub 会拒绝镜像域名的
重定向校验，故用 curl 直下）。

用法:
    engine = STTEngine(model_name="small")
    text = engine.transcribe(wav_path, duration_s=3.0)
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.media.voice import PCM_SAMPLE_RATE

# 模型根目录（相对项目根）
MODEL_ROOT = Path(__file__).resolve().parents[4] / "data" / "models"
# 转写缓存文件（相对项目根）
CACHE_FILE = Path(__file__).resolve().parents[4] / "data" / "stt_cache.json"

# 跨实例缓存文件锁（多个 STTEngine 并行写同一缓存文件时保护）
_CACHE_FILE_LOCK = threading.Lock()

# 模型在 HuggingFace 的仓库名
_HF_REPO = "Systran/faster-whisper-{name}"

# 需要下载的模型文件
_MODEL_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


def model_dir(model_name: str = "small") -> Path:
    """faster-whisper 模型本地目录。"""
    return MODEL_ROOT / f"faster-whisper-{model_name}"


def download_model(model_name: str = "small", endpoint: str = "https://hf-mirror.com") -> Path:
    """
    从镜像下载 faster-whisper 模型到 data/models/。

    用 curl 直下（huggingface_hub 对镜像域有重定向校验限制）。

    Returns:
        模型目录路径。
    """
    dst = model_dir(model_name)
    dst.mkdir(parents=True, exist_ok=True)
    repo = _HF_REPO.format(name=model_name)
    for fname in _MODEL_FILES:
        target = dst / fname
        if target.exists() and target.stat().st_size > 0:
            logger.info(f"模型文件已存在: {fname}")
            continue
        url = f"{endpoint}/{repo}/resolve/main/{fname}"
        logger.info(f"下载 {fname} ← {url}")
        subprocess.run(
            ["curl", "-s", "-o", str(target), "-L", url],
            check=True,
        )
        if not target.exists() or target.stat().st_size == 0:
            raise RuntimeError(f"模型文件下载失败: {fname}")
    logger.info(f"模型就绪: {dst}")
    return dst


class STTEngine:
    """
    本地语音转写引擎（faster-whisper）。

    懒加载模型 + 转写结果磁盘缓存（避免重复转写）。
    """

    def __init__(
        self,
        model_name: str = "small",
        cache_file: str | Path = CACHE_FILE,
        cache_enabled: bool = True,
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
    ):
        self.model_name = model_name
        self.cache_file = Path(cache_file)
        self.cache_enabled = cache_enabled
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model = None  # 懒加载
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()  # 并行导出共享实例时的缓存保护
        if cache_enabled and self.cache_file.exists():
            with _CACHE_FILE_LOCK:
                try:
                    self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"STT 缓存读取失败（忽略）: {e}")
                    self._cache = {}

    # ---- 模型 ----

    @property
    def model(self):
        """懒加载 faster-whisper 模型。"""
        if self._model is None:
            from faster_whisper import WhisperModel

            local = model_dir(self.model_name)
            if not local.exists() or not (local / "model.bin").exists():
                logger.info(f"模型不存在，自动下载 {self.model_name} ...")
                local = download_model(self.model_name)
            self._model = WhisperModel(
                str(local),
                device=self.device,
                compute_type=self.compute_type,
                local_files_only=True,
            )
            logger.info(f"STT 模型已加载: {self.model_name} ({self.device}/{self.compute_type})")
        return self._model

    # ---- 转写 ----

    def _cache_key(self, wav_bytes: bytes) -> str:
        return hashlib.md5(wav_bytes).hexdigest()

    def transcribe(
        self,
        wav_bytes: bytes,
        duration_s: float = 0.0,
        language: str = "zh",
        beam_size: int | None = None,
    ) -> str:
        """
        转写 WAV 字节 → 文本。

        Args:
            wav_bytes: WAV 文件字节（16kHz mono s16le）。
            duration_s: 语音时长（秒，日志用）。
            language: 语言提示（zh = 中文）。
            beam_size: 解码束宽（越大越准越慢）。

        Returns:
            转写文本；失败返回空串（不抛出，调用方按失败处理）。
        """
        key = self._cache_key(wav_bytes)
        with self._lock:
            if self.cache_enabled and key in self._cache:
                return self._cache[key]

        try:
            model = self.model
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name
            try:
                segments, _info = model.transcribe(
                    tmp_path,
                    language=language,
                    beam_size=self.beam_size if beam_size is None else beam_size,
                    vad_filter=True,  # 静音段跳过，提升速度与质量
                )
                text = "".join(s.text.strip() for s in segments).strip()
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"语音转写失败 (时长 {duration_s:.1f}s): {e}")
            return ""

        with self._lock:
            if self.cache_enabled:
                self._cache[key] = text
                self._save_cache()
        return text

    def _save_cache(self) -> None:
        """持久化转写缓存（限制条目数防止无限增长）。"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with _CACHE_FILE_LOCK:
                # 合并磁盘上其他实例写入的条目（并行导出时）
                merged = {}
                try:
                    merged = json.loads(self.cache_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
                merged.update(self._cache)
                # 只保留最近 5000 条
                items = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
                if len(items) > 5000:
                    merged = dict(items[:5000])
                self.cache_file.write_text(
                    json.dumps(merged, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                self._cache = merged
        except Exception as e:
            logger.debug(f"STT 缓存保存失败: {e}")
