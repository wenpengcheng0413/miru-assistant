"""
Miru Assistant — Chat Analyzer 图片提取与解密。

微信 4.x 图片存储（已验证）:
    msg/attach/{MD5(wxid)}/{YYYY-MM}/Img/{name}.dat
    第一层目录 = 会话 wxid 的 MD5（与 Msg_{MD5(wxid)} 会话表同名哈希）。

.dat 文件格式（V1 / V2）:
    [6B 签名 07 08 56 31|32 08 07]
    [4B aes_size LE][4B xor_size LE][1B padding]
    [AES-128-ECB 段（PKCS7 对齐 16）]
    [明文段]
    [XOR 段（单字节循环）]

    密钥:
        V1: 固定 key (cfcd208495d565ef, ASCII 16B) + XOR 0x88
        V2: AES key 从微信进程内存提取（media/v2key.py）

文件级关联策略:
    XML md5（CDN 原始 md5）与本地 .dat 文件名不完全一致
    （本地为压缩后重新计算的内容哈希）。采用:
        1. 会话目录定位（MD5(wxid) 完全可靠）
        2. 年月目录（create_time → YYYY-MM）
        3. 同目录下与消息时间最近的文件（启发式）
        4. 解密成功后用 XML md5 无法直接核对时，以文件名时间为准
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.media.models import (
    DAT_SIG_V1,
    DAT_SIG_V2,
    DAT_V1_AES_KEY,
    DAT_V1_XOR_KEY,
)
from miru.chat_analyzer.media.v2key import get_v2_keys


class ImageExtractor:
    """微信 4.x 图片 .dat 定位与解密。"""

    def __init__(self, account_dir: str | Path, v2_keys: list[bytes] | None = None):
        """
        Args:
            account_dir: 微信账号目录（含 msg/attach）。
            v2_keys: 已验证的 V2 AES 密钥（None = 需要时自动扫描）。
        """
        self.account_dir = Path(account_dir)
        self.attach_root = self.account_dir / "msg" / "attach"
        self.v2_keys = v2_keys or []
        self._v2_scanned = False  # 惰性扫描标记

    # ---- 定位 ----

    @staticmethod
    def _session_dir(wxid: str) -> str:
        """会话 attach 目录名 = MD5(wxid)。"""
        return hashlib.md5(wxid.encode()).hexdigest()

    def _month_dir(self, wxid: str, create_time: int) -> Path:
        """会话 + 年月 → 图片目录。"""
        month = datetime.fromtimestamp(create_time).strftime("%Y-%m")
        return self.attach_root / self._session_dir(wxid) / month / "Img"

    def locate_files(self, wxid: str, create_time: int, md5: str = "") -> list[Path]:
        """
        定位某条图片消息对应的 .dat 文件候选。

        优先级:
            1. 文件名 == md5（仅当 XML md5 与本地文件名一致时）
            2. 同目录全部文件（调用方按时间最近挑选）

        Returns:
            候选 .dat 文件路径列表（按修改时间降序）。
        """
        img_dir = self._month_dir(wxid, create_time)
        if not img_dir.exists():
            return []
        candidates = [p for p in img_dir.glob("*.dat") if not p.name.endswith("_t.dat")]
        if md5:
            exact = [p for p in candidates if p.stem == md5]
            if exact:
                return exact
        # 按修改时间降序（近期文件优先）
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates

    def locate_thumb(self, wxid: str, create_time: int, md5: str = "") -> list[Path]:
        """
        定位缩略图 _t.dat 候选（标准 jpg，颜色正确——微信 HEVC 原图
        的标准解码器色度不可恢复，缩略图是可查看的可靠版本）。

        Returns:
            _t.dat 路径列表（按修改时间降序）。
        """
        img_dir = self._month_dir(wxid, create_time)
        if not img_dir.exists():
            return []
        candidates = list(img_dir.glob("*_t.dat"))
        if md5:
            exact = [p for p in candidates if p.stem.startswith(md5)]
            if exact:
                return exact
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates

    @staticmethod
    def pick_by_time(candidates: list[Path], create_time: int, window_s: int = 3600) -> Path | None:
        """
        从候选文件中挑选与消息时间最接近的（±window_s 内）。

        文件修改时间可能是迁移/复制时间（不完全可靠），
        故返回时间差最小者，但仅当差距 < window_s。
        """
        best: tuple[float, Path] | None = None
        for p in candidates:
            try:
                delta = abs(os.path.getmtime(p) - create_time)
            except OSError:
                continue
            if best is None or delta < best[0]:
                best = (delta, p)
        if best is None or best[0] > window_s:
            return None
        return best[1]

    # ---- 解密 ----

    @staticmethod
    def parse_header(data: bytes) -> tuple[str, int, int] | None:
        """解析 .dat 文件头 → (sig_type, aes_size, xor_size)；非已知格式返回 None。"""
        if len(data) < 15:
            return None
        sig = data[:6]
        if sig == DAT_SIG_V1:
            stype = "v1"
        elif sig == DAT_SIG_V2:
            stype = "v2"
        else:
            return None
        aes_size = int.from_bytes(data[6:10], "little")
        xor_size = int.from_bytes(data[10:14], "little")
        return stype, aes_size, xor_size

    def decrypt(self, dat_path: str | Path) -> bytes | None:
        """
        解密 .dat 文件 → 图片原始字节。

        按 V1 → V2(内存 key) 顺序尝试；失败返回 None。

        V2 密钥需要时惰性扫描内存（微信需运行）。
        """
        try:
            data = Path(dat_path).read_bytes()
        except OSError as e:
            logger.debug(f"读取 .dat 失败: {e}")
            return None

        parsed = self.parse_header(data)
        if parsed is None:
            logger.debug(f"未知 .dat 格式: {Path(dat_path).name}")
            return None
        stype, aes_size, xor_size = parsed

        # AES 段实际长度: aes_size 对齐 16；若 aes_size 恰好 16 倍数，
        # PKCS7 会额外追加一个完整填充块（实测微信文件 aes_size=1024 → 密文 1040）
        aligned = (aes_size + 15) // 16 * 16
        aes_len = aligned + (16 if aes_size % 16 == 0 else 0)
        aes_seg = data[15 : 15 + aes_len]
        raw_seg = data[15 + aes_len : len(data) - xor_size]
        if len(raw_seg) < 0:
            raw_seg = b""
        xor_seg = data[len(data) - xor_size :] if xor_size else b""

        # 候选 AES key
        if stype == "v1":
            keys: list[tuple[bytes, int]] = [(DAT_V1_AES_KEY, DAT_V1_XOR_KEY)]
        else:
            if not self.v2_keys and not self._v2_scanned:
                self._v2_scanned = True
                logger.info("V2 图片密钥缺失，从磁盘派生（无需微信运行）...")
                self.v2_keys = get_v2_keys(
                    dat_paths=[Path(dat_path)],
                    account_dir=self.account_dir,
                )
            keys = [(k, DAT_V1_XOR_KEY) for k in self.v2_keys]

        if not keys:
            logger.debug(f"无可用密钥: {Path(dat_path).name}")
            return None

        for aes_key, default_xor in keys:
            from Crypto.Cipher import AES

            try:
                dec = AES.new(aes_key, AES.MODE_ECB).decrypt(aes_seg)
                # 去 PKCS7 填充
                if dec and dec[-1] <= 16:
                    dec = dec[: len(dec) - dec[-1]]
            except Exception:
                continue
            if not dec:
                continue
            # XOR 段：尝试默认 key 或按已知格式推断
            xor_key = self._guess_xor_key(xor_seg, default_xor)
            if xor_key is not None:
                xor_out = bytes(b ^ xor_key for b in xor_seg)
            else:
                xor_out = xor_seg
            return dec + raw_seg + xor_out
        return None

    @staticmethod
    def _guess_xor_key(xor_seg: bytes, default: int) -> int | None:
        """
        推断 XOR 段密钥。

        XOR 段是图片文件的末尾部分（JPEG 结尾 FF D9 / PNG 结尾 IEND AE 42 60 82），
        用末尾魔数反推 key；反推失败回退默认值。
        """
        if not xor_seg:
            return default
        # JPEG 结尾: FF D9
        if len(xor_seg) >= 2:
            k = xor_seg[-2] ^ 0xFF
            if xor_seg[-1] ^ k == 0xD9:
                return k
            k = xor_seg[-1] ^ 0xD9
            if xor_seg[-2] ^ k == 0xFF:
                return k
        # PNG 结尾: 49 45 4E 44 AE 42 60 82 (IEND)
        if len(xor_seg) >= 8:
            tail = xor_seg[-8:]
            for k in range(256):
                if bytes(b ^ k for b in tail) == b"IEND\xaeB`\x82":
                    return k
        return default

    @staticmethod
    def sniff_format(data: bytes) -> str:
        """按魔数嗅探图片格式。"""
        if data.startswith(b"\xff\xd8\xff"):
            return "jpg"
        if data.startswith(b"\x89PNG"):
            return "png"
        if data.startswith(b"GIF8"):
            return "gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "webp"
        if data[:2] == b"BM":
            return "bmp"
        if data[:4] == b"wxgf":
            # 微信私有 HEVC 格式（动画/高压缩图），解密后原样保留
            return "wxgf"
        return "unknown"

    def export(
        self,
        wxid: str,
        create_time: int,
        md5: str,
        export_dir: str | Path,
        filename_stem: str = "",
    ) -> tuple[bytes, str, Path | None]:
        """
        定位 + 解密 + 返回图片数据与建议扩展名。

        Args:
            wxid: 会话 wxid（用于 attach 目录定位）。
            create_time: 消息时间戳。
            md5: 图片 XML md5（用于文件名优先匹配）。
            export_dir: 导出附件根目录（media/img）。
            filename_stem: 导出文件名主干（默认用 md5 或时间）。

        Returns:
            (image_bytes, ext, source_dat_path)；解密失败 (None, "", dat_path)。
        """
        candidates = self.locate_files(wxid, create_time, md5)
        dat_path: Path | None = None
        if candidates:
            dat_path = self.pick_by_time(candidates, create_time)
            if dat_path is None:
                dat_path = candidates[0]  # 无时间匹配也试第一个（内容校验兜底）
        if dat_path is None:
            return b"", "", None

        data = self.decrypt(dat_path)
        if not data:
            return b"", "", dat_path

        ext = self.sniff_format(data)
        if ext == "unknown":
            # 解密成功但格式未知 → 保留 .dat 原件
            return b"", "", dat_path

        stem = filename_stem or md5 or dat_path.stem
        out_dir = Path(export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{stem}.{ext}"
        out_file.write_bytes(data)
        return data, ext, dat_path
