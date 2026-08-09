"""
Miru Assistant — Chat Analyzer 语音提取。

从 media_0.db 的 VoiceInfo 表提取微信语音数据并解码为 PCM/WAV。

已验证的事实（微信 4.x）:
    - VoiceInfo 表结构: (chat_name_id, create_time, local_id, svr_id, voice_data, data_index)
    - VoiceInfo.svr_id = 消息表 server_id（全量交叉验证命中率 99.99%）
    - voice_data 是 SILK_V3 编码（微信版头部多 0x02 字节），
      用 pysilk 直接解码（pysilk 兼容微信格式）
    - 无需任何密钥，离线可读

用法:
    extractor = VoiceExtractor(db)
    pcm = extractor.decode_to_pcm(silk_bytes)   # PCM s16le 16kHz mono
"""

import io
import wave
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.offline_reader import OfflineWeChatDB

# VoiceInfo 所在数据库（相对 db_storage）
VOICE_DB_REL = "message/media_0.db"

# 转写用标准采样率（Whisper 输入要求）
PCM_SAMPLE_RATE = 16000


class VoiceExtractor:
    """从 media_0.db 提取语音数据并解码。"""

    def __init__(self, db: OfflineWeChatDB):
        """
        Args:
            db: 已定位账号目录的 OfflineWeChatDB。
        """
        self.db = db
        self._pcm_cache: dict[int, bytes] = {}  # svr_id → PCM（进程内缓存）

    # ---- 提取 ----

    def get_voice_data(self, server_id: int) -> bytes | None:
        """按 server_id 查询 VoiceInfo 返回原始 SILK 数据（无则 None）。"""
        try:
            conn = self.db.open(VOICE_DB_REL)
        except FileNotFoundError as e:
            logger.warning(f"media_0.db 不可用: {e}")
            return None
        try:
            row = conn.execute(
                "SELECT voice_data FROM VoiceInfo WHERE svr_id = ? LIMIT 1",
                (server_id,),
            ).fetchone()
        except Exception as e:
            logger.debug(f"VoiceInfo 查询失败 (svr_id={server_id}): {e}")
            return None
        if not row or not row[0]:
            return None
        return row[0]

    def iter_voice_ids(self, server_ids: list[int]) -> dict[int, bytes]:
        """
        批量查询多个 server_id 的语音数据。

        单次 SQL 批量查询，避免逐条往返。

        Returns:
            {server_id: voice_data}（仅含命中的）。
        """
        if not server_ids:
            return {}
        try:
            conn = self.db.open(VOICE_DB_REL)
        except FileNotFoundError:
            return {}
        result: dict[int, bytes] = {}
        # 分批 IN 查询（避免 SQL 过长）
        for i in range(0, len(server_ids), 500):
            chunk = server_ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            try:
                rows = conn.execute(
                    f"SELECT svr_id, voice_data FROM VoiceInfo WHERE svr_id IN ({marks})",
                    chunk,
                ).fetchall()
                for sid, data in rows:
                    if data:
                        result[sid] = data
            except Exception as e:
                logger.debug(f"VoiceInfo 批量查询失败: {e}")
        return result

    # ---- 解码 ----

    @staticmethod
    def decode_to_pcm(silk_data: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
        """
        SILK V3 → PCM s16le（单声道，指定采样率）。

        微信版 SILK 头部多 0x02 字节、尾部无 \\xff\\xff，
        pysilk 兼容该格式，直接解码即可。

        Raises:
            ImportError: pysilk 未安装。
            RuntimeError: 解码失败。
        """
        try:
            import pysilk
        except ImportError as e:
            raise ImportError("pysilk 未安装。请运行: pip install pysilk") from e

        out = io.BytesIO()
        try:
            pysilk.decode(io.BytesIO(silk_data), out, sample_rate)
        except Exception as e:
            raise RuntimeError(f"SILK 解码失败: {e}") from e
        return out.getvalue()

    def decode_to_pcm_cached(self, server_id: int, silk_data: bytes) -> bytes | None:
        """解码并缓存 PCM（同一次导出内重复消息只解一次）。"""
        if server_id in self._pcm_cache:
            return self._pcm_cache[server_id]
        try:
            pcm = self.decode_to_pcm(silk_data)
        except Exception as e:
            logger.debug(f"语音解码失败 (svr_id={server_id}): {e}")
            return None
        self._pcm_cache[server_id] = pcm
        return pcm

    # ---- 输出 ----

    @staticmethod
    def pcm_to_wav_bytes(pcm: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> bytes:
        """PCM s16le → WAV 文件字节（供 faster-whisper 直接读取）。"""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def save_wav(self, pcm: bytes, path: str | Path, sample_rate: int = PCM_SAMPLE_RATE) -> None:
        """PCM → WAV 文件（keep_voice_files 选项用）。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.pcm_to_wav_bytes(pcm, sample_rate))
