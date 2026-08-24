"""
Miru Assistant — Chat Analyzer 媒体处理编排。

将语音转写与图片导出串起来，供 offline_exporter 调用。

对一批 ChatMessage：
    1. 语音消息 (34): VoiceInfo 取 SILK → PCM → STT → 文本
    2. 图片消息 (3): 定位 .dat → 解密 → 复制到 media/img/
    3. 返回每条消息的渲染文本映射（导出器替换摘要行）
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.media.image import ImageExtractor
from miru.chat_analyzer.media.models import MediaExportResult, VoiceResult
from miru.chat_analyzer.media.transcribe import STTEngine
from miru.chat_analyzer.media.voice import VoiceExtractor
from miru.chat_analyzer.models import ChatMessage

# 图片消息类型
MSG_TYPE_IMAGE = 3
MSG_TYPE_VOICE = 34

# 每批转写的最大条数（进度显示粒度）
_BATCH_LOG = 50


@dataclass
class MediaConfig:
    """媒体处理配置（来自 settings.yaml miru.export.media）。"""

    enabled: bool = True
    images: bool = True
    voice_transcribe: bool = True
    stt_model: str = "small"
    stt_cache: bool = True
    keep_voice_files: bool = False
    convert_wxgf: bool = True  # 微信 HEVC 私有图 → jpg（需要 ffmpeg）

    @classmethod
    def from_dict(cls, d: dict | None) -> "MediaConfig":
        d = d or {}
        return cls(
            enabled=bool(d.get("enabled", True)),
            images=bool(d.get("images", True)),
            voice_transcribe=bool(d.get("voice_transcribe", True)),
            stt_model=str(d.get("stt_model", "small")),
            stt_cache=bool(d.get("stt_cache", True)),
            keep_voice_files=bool(d.get("keep_voice_files", False)),
            convert_wxgf=bool(d.get("convert_wxgf", True)),
        )


class MediaProcessor:
    """一次联系人导出的媒体处理。"""

    _STT_UNSET = object()  # 区分"未传入"与"显式 None 禁用"

    def __init__(
        self,
        account_dir: str | Path,
        db,
        config: MediaConfig,
        stt: STTEngine | None = _STT_UNSET,
    ):
        """
        Args:
            account_dir: 微信账号目录（attach 图片定位）。
            db: OfflineWeChatDB 实例（media_0.db 语音提取）。
            config: 媒体处理配置。
            stt: 注入的 STT 引擎；默认按配置自动创建；
                显式传 None 可禁用转写（测试用）。
        """
        self.account_dir = Path(account_dir)
        self.config = config
        self.voice = VoiceExtractor(db)
        self.stt: STTEngine | None
        if stt is self._STT_UNSET:
            self.stt = (
                STTEngine(
                    model_name=config.stt_model,
                    cache_enabled=config.stt_cache,
                )
                if config.voice_transcribe
                else None
            )
        else:
            self.stt = stt
        self.images = ImageExtractor(account_dir)
        self._img_cursor: dict[str, int] = {}  # 图片目录 → 已分配游标（实例级，线程安全）

    # ---- 语音 ----

    def _transcribe_voice(
        self,
        msg: ChatMessage,
        media_dir: Path,
    ) -> tuple[str, VoiceResult]:
        """处理单条语音消息 → (渲染文本, VoiceResult)。"""
        result = VoiceResult(
            server_id=msg.server_id,
            create_time=msg.timestamp,
        )
        silk = self.voice.get_voice_data(msg.server_id) if msg.server_id else None
        if not silk:
            result.error = "VoiceInfo 无数据"
            logger.debug(f"语音数据缺失 (svr_id={msg.server_id})")
            return self._voice_fallback(msg), result

        result.duration_ms = _parse_voice_length(msg.content)
        pcm = self.voice.decode_to_pcm_cached(msg.server_id, silk)
        if not pcm:
            result.error = "SILK 解码失败"
            return self._voice_fallback(msg), result

        if self.stt is not None:
            wav = self.voice.pcm_to_wav_bytes(pcm)
            text = self.stt.transcribe(wav, duration_s=pcm_duration_s(pcm))
            if text:
                result.text = text
                result.ok = True

        if self.config.keep_voice_files:
            voice_dir = media_dir / "voice"
            self.voice.save_wav(pcm, voice_dir / f"voice_{msg.server_id}.wav")

        if result.ok:
            dur = _format_duration(result.duration_ms)
            return f"[语音转文字] {text}" + (f"（时长 {dur}）" if dur else ""), result
        result.error = result.error or "转写失败"
        return self._voice_fallback(msg), result

    @staticmethod
    def _voice_fallback(msg: ChatMessage) -> str:
        """语音处理失败时的占位文本（与导出器原有格式一致）。"""
        dur = _format_duration(_parse_voice_length(msg.content))
        return f"[语音] (时长 {dur})" if dur else "[语音]"

    # ---- 图片 ----

    def _process_image(
        self,
        msg: ChatMessage,
        target_wxid: str,
        media_dir: Path,
    ) -> tuple[str, bool]:
        """处理单条图片消息 → (渲染文本, ok)。

        策略:
            1. 缩略图 _t.dat（标准 jpg，颜色正确）→ 导出 xxx.jpg
            2. 高清原图（wxgf/HEVC 私有格式）→ 解密保留 xxx.wxgf 备份
               （标准解码器色度不可恢复，微信客户端可正常查看）
            3. 无缩略图时用原图（解密成功为标准格式则直接导出）
        """
        md5 = _parse_image_md5(msg.content)
        stem = _image_stem(md5, msg, None)
        img_dir = self.images._month_dir(target_wxid, msg.timestamp)
        cursor_key = str(img_dir)

        # ---- 1. 缩略图（标准 jpg，可查看） ----
        thumb = self._next_thumb(target_wxid, msg.timestamp, md5, cursor_key)
        if thumb is not None:
            data = self.images.decrypt(thumb)
            if data:
                ext = self.images.sniff_format(data)
                if ext != "unknown":
                    saved = media_dir / "img" / f"{stem}.{ext}"
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_bytes(data)
                    # 高清原图备份
                    self._backup_original(target_wxid, msg.timestamp, md5, cursor_key, media_dir, stem)
                    return f"[图片] media/img/{saved.name}", True

        # ---- 2. 高清原图（无缩略图时） ----
        dat_path = self._next_dat(target_wxid, msg.timestamp, cursor_key)
        if dat_path is None:
            return "[图片]", False

        data = self.images.decrypt(dat_path)
        if not data:
            target = media_dir / "img" / f"{dat_path.stem}.dat"
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dat_path, target)
            except OSError as e:
                logger.debug(f"复制 .dat 失败: {e}")
                return "[图片]", False
            return f"[图片未解密] media/img/{target.name}", False

        ext = self.images.sniff_format(data)
        if ext == "unknown":
            target = media_dir / "img" / f"{dat_path.stem}.dat"
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dat_path, target)
            except OSError:
                pass
            return f"[图片未解密] media/img/{target.name}", False

        saved = media_dir / "img" / f"{stem}.{ext}"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(data)
        return f"[图片] media/img/{saved.name}", True

    def _next_thumb(self, target_wxid: str, create_time: int, md5: str, cursor_key: str):
        """缩略图按目录顺序分配（与消息一一对应）。"""
        candidates = self.images.locate_thumb(target_wxid, create_time, md5)
        if not candidates:
            return None
        k = self._img_cursor.get(f"{cursor_key}#thumb", 0)
        self._img_cursor[f"{cursor_key}#thumb"] = k + 1
        return candidates[k % len(candidates)]

    def _backup_original(self, target_wxid, create_time, md5, cursor_key, media_dir, stem):
        """高清原图（wxgf）解密保留为备份。"""
        try:
            dat_path = self._next_dat(target_wxid, create_time, cursor_key)
            if dat_path is None:
                return
            data = self.images.decrypt(dat_path)
            if not data:
                return
            ext = self.images.sniff_format(data)
            if ext == "wxgf":  # 微信私有格式 → 保留原件
                saved = media_dir / "img" / f"{stem}.wxgf"
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(data)
        except Exception as e:
            logger.debug(f"原图备份失败: {e}")

    def _next_dat(self, target_wxid: str, create_time: int, cursor_key: str):
        """同目录候选按顺序分配（避免时间启发式重复选同一文件）。"""
        candidates = self.images.locate_files(target_wxid, create_time, md5="")
        if not candidates:
            return None
        k = self._img_cursor.get(cursor_key, 0)
        self._img_cursor[cursor_key] = k + 1
        return candidates[k % len(candidates)]

    # ---- 编排 ----

    def process(
        self,
        msgs: list[ChatMessage],
        target_wxid: str,
        media_dir: str | Path,
    ) -> tuple[MediaExportResult, dict[int, str]]:
        """
        处理一批消息。

        Args:
            msgs: 待导出的消息列表（已排序）。
            target_wxid: 会话 wxid（attach 目录定位用）。
            media_dir: 媒体附件根目录（如 output/Krista/media）。

        Returns:
            (MediaExportResult, {消息在 msgs 中的下标: 渲染文本})。
        """
        media_dir = Path(media_dir)
        result = MediaExportResult(media_dir=str(media_dir))
        overrides: dict[int, str] = {}
        if not self.config.enabled:
            return result, overrides

        # ---- 图片（先处理，简单） ----
        if self.config.images:
            for i, m in enumerate(msgs):
                if m.msg_type != MSG_TYPE_IMAGE:
                    continue
                result.image_total += 1
                text, ok = self._process_image(m, target_wxid, media_dir)
                if ok:
                    result.image_exported += 1
                else:
                    result.image_failed += 1
                overrides[i] = text

        # ---- 语音 ----
        if self.config.voice_transcribe or self.config.keep_voice_files:
            voice_msgs = [
                (i, m) for i, m in enumerate(msgs) if m.msg_type == MSG_TYPE_VOICE
            ]
            result.voice_total = len(voice_msgs)
            if self.config.voice_transcribe and self.stt is not None:
                # 预加载模型（避免逐条加载抖动）
                try:
                    self.stt.model
                except Exception as e:
                    logger.warning(f"STT 模型加载失败，语音转写跳过: {e}")
                    self.stt = None
            done = 0
            for i, m in voice_msgs:
                text, vres = self._transcribe_voice(m, media_dir)
                overrides[i] = text
                if vres.ok:
                    result.voice_transcribed += 1
                else:
                    result.voice_failed += 1
                    if vres.error:
                        result.warnings.append(
                            f"语音失败 (svr_id={m.server_id}): {vres.error}"
                        )
                done += 1
                if done % _BATCH_LOG == 0 or done == result.voice_total:
                    logger.info(f"语音转写进度: {done}/{result.voice_total}")

        return result, overrides


# ============================================================
# 工具函数
# ============================================================


def _parse_voice_length(content: str) -> int:
    """从语音 XML 提取 voicelength（毫秒）；无则 0。"""
    if not content:
        return 0
    try:
        start = content.find("voicelength")
        if start < 0:
            return 0
        seg = content[start : start + 40]
        m = __import__("re").search(r'voicelength\s*=\s*"?(\d+)"?', seg)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def _format_duration(ms: int) -> str:
    """毫秒 → "Ns"（不足 1s 按 1s）。"""
    if ms <= 0:
        return ""
    return f"{max(1, round(ms / 1000))}s"


def pcm_duration_s(pcm: bytes) -> float:
    """PCM 时长（秒）。"""
    return len(pcm) / 2 / 16000


def _parse_image_md5(content: str) -> str:
    """从图片 XML 提取 md5。"""
    if not content:
        return ""
    m = __import__("re").search(r'md5="([0-9a-f]{32})"', content)
    return m.group(1) if m else ""


def _image_stem(md5: str, msg: ChatMessage, dat_path: Path | None) -> str:
    """图片导出文件名主干。"""
    if md5:
        return md5[:16]
    if dat_path is not None:
        return dat_path.stem
    return f"img_{msg.timestamp}"


def _convert_wxgf_to_jpg(wxgf_path: Path) -> Path | None:
    """
    微信 WXGF（HEVC 私有容器）→ jpg。

    提取 HEVC NAL 流（跳过 wxgf 容器头）后用 ffmpeg 转第一帧。

    Returns:
        转换后的 jpg 路径；失败返回 None。
    """
    import subprocess

    try:
        data = wxgf_path.read_bytes()
        idx = data.find(b"\x00\x00\x00\x01")
        if idx < 0:
            return None
        hevc = data[idx:]
        # 检查 ffmpeg 可用
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"WXGF 转换跳过: {e}")
        return None

    jpg_path = wxgf_path.with_suffix(".jpg")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "hevc", "-i", "-",
                "-frames:v", "1", str(jpg_path),
            ],
            input=hevc,
            capture_output=True,
            timeout=60,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"WXGF → jpg 转换失败: {e}")
        return None
    return jpg_path if jpg_path.exists() else None
