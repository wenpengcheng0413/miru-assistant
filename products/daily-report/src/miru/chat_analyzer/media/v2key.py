"""
Miru Assistant — Chat Analyzer 微信 4.x 图片 V2 密钥提取。

V2 格式 (.dat 签名 07 08 56 32 08 07) 的 AES-128 密钥仅存在于
微信进程内存中（用户查看图片时临时加载）。扫描策略移植自
开源工具 weixin-decrypte-script (ZedeX/weixin-decrypte-script)：

    1. 遍历进程完整虚拟内存（RW 区域优先，含堆/栈）
    2. 提取 16/32 字符任意字母数字字符串（带边界断言）
       —— key 可能以 ASCII 字符串或原始字节形式存在
    3. 用 .dat 前 16 字节 AES 密文验证候选（JPEG/PNG/WEBP/WXGF/GIF 魔数）
    4. 命中后完整解密 .dat 二次确认（防误命中）

注意:
    - 需要微信进程运行 + 管理员权限
    - 未在微信中打开过的图片对应的密钥可能不在内存中
    - 扫描约 1-3 分钟（取决于进程大小），结果缓存到磁盘

用法:
    keys = get_v2_keys(dat_samples)  # list[bytes]
"""

import ctypes
import ctypes.wintypes
import json
import re
from pathlib import Path

from loguru import logger

from miru.chat_analyzer.media.models import DAT_SIG_V2

# 16/32 字符任意字母数字（带边界断言，避免长 token 的子串误匹配）
_HEX32_RE = re.compile(rb"(?<![a-zA-Z0-9])[a-zA-Z0-9]{32}(?![a-zA-Z0-9])")
_HEX16_RE = re.compile(rb"(?<![a-zA-Z0-9])[a-zA-Z0-9]{16}(?![a-zA-Z0-9])")

# 密钥缓存文件（相对项目根）
KEY_CACHE_FILE = Path(__file__).resolve().parents[4] / "data" / "media_keys.json"

# 内存区域保护标志
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
_RW_FLAGS = (
    PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY
)
MEM_COMMIT = 0x1000


class _MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.wintypes.DWORD),
        ("PartitionId", ctypes.wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.wintypes.DWORD),
        ("Protect", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
    ]


def _find_wechat_pids() -> list[int]:
    """查找运行中的 Weixin.exe 进程 PID（按内存占用降序，主进程优先）。"""
    import psutil

    procs: list[tuple[int, int]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in ("weixin.exe", "wechat.exe"):
                procs.append((proc.info["pid"], proc.memory_info().rss))
        except Exception:
            continue
    procs.sort(key=lambda t: t[1], reverse=True)
    return [p for p, _ in procs]


def _extract_ciphertext(dat_paths: list[Path]) -> bytes | None:
    """从 .dat 提取前 16 字节 AES 密文（文件头 15 字节之后）。"""
    for p in dat_paths:
        try:
            with open(p, "rb") as f:
                header = f.read(31)
        except OSError:
            continue
        if header[:6] == DAT_SIG_V2 and len(header) >= 31:
            return header[15:31]
    return None


def _guess_format(dec: bytes) -> str | None:
    """解密首段 → 图片格式（弱验证，与社区工具一致）。"""
    if dec[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if dec[:4] == b"\x89PNG":
        return "PNG"
    if dec[:4] == b"RIFF":
        return "WEBP"
    if dec[:4] == b"wxgf":
        return "WXGF"
    if dec[:3] == b"GIF":
        return "GIF"
    return None


def _is_rw_protect(protect: int) -> bool:
    return (protect & _RW_FLAGS) != 0


def _scan_process_memory(pid: int, ciphertext: bytes) -> str | None:
    """扫描单个进程内存找 key（移植社区工具逻辑）。"""
    from Crypto.Cipher import AES

    kernel32 = ctypes.windll.kernel32
    kernel32.VirtualQueryEx.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(_MBI),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = ctypes.c_int

    h_process = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h_process:
        logger.warning(f"无法打开微信进程 (PID={pid})，需要管理员权限")
        return None
    try:
        address = 0
        rw_regions: list[tuple[int, int, int]] = []
        all_regions: list[tuple[int, int, int]] = []
        while address < 0x7FFFFFFFFFFF:
            mbi = _MBI()
            result = kernel32.VirtualQueryEx(
                h_process, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if result == 0:
                break
            if (
                mbi.State == MEM_COMMIT
                and mbi.Protect != PAGE_NOACCESS
                and (mbi.Protect & PAGE_GUARD) == 0
                and mbi.RegionSize <= 50 * 1024 * 1024
            ):
                region = (mbi.BaseAddress, mbi.RegionSize, mbi.Protect)
                all_regions.append(region)
                if _is_rw_protect(mbi.Protect):
                    rw_regions.append(region)
            next_addr = address + mbi.RegionSize
            if next_addr <= address:
                break
            address = next_addr

        rw_mb = sum(r[1] for r in rw_regions) / 1024 / 1024
        all_mb = sum(r[1] for r in all_regions) / 1024 / 1024
        logger.info(
            f"PID={pid}: RW 区域 {len(rw_regions)} ({rw_mb:.0f}MB), "
            f"全部 {len(all_regions)} ({all_mb:.0f}MB)"
        )

        # Phase 1: RW 区域优先（key 最可能在这里）
        result = _scan_regions(h_process, rw_regions, ciphertext)
        if result:
            return result
        # Phase 2: 其余区域
        rw_set = set((r[0], r[1]) for r in rw_regions)
        other = [r for r in all_regions if (r[0], r[1]) not in rw_set]
        result = _scan_regions(h_process, other, ciphertext)
        if result:
            return result
        return None
    finally:
        kernel32.CloseHandle(h_process)


def _scan_regions(h_process, regions, ciphertext: bytes) -> str | None:
    """在区域集合中扫描 16/32 字符候选并验证。"""
    from Crypto.Cipher import AES

    kernel32 = ctypes.windll.kernel32
    for base_addr, region_size, _protect in regions:
        buf = ctypes.create_string_buffer(region_size)
        bytes_read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            h_process,
            ctypes.c_void_p(base_addr),
            buf,
            region_size,
            ctypes.byref(bytes_read),
        )
        if not ok or bytes_read.value < 32:
            continue
        data = buf.raw[: bytes_read.value]

        # 32 字符候选: 前 16 字节作 key
        for m in _HEX32_RE.finditer(data):
            key_bytes = m.group()
            fmt = _try_key_once(AES, key_bytes[:16], ciphertext)
            if fmt:
                logger.info(f"找到 32 字符 key ({fmt}): {key_bytes.decode('ascii')[:20]}...")
                return key_bytes[:16].decode("ascii")
        # 16 字符候选: 整个字符串作 key
        for m in _HEX16_RE.finditer(data):
            key_bytes = m.group()
            fmt = _try_key_once(AES, key_bytes, ciphertext)
            if fmt:
                logger.info(f"找到 16 字符 key ({fmt}): {key_bytes.decode('ascii')}")
                return key_bytes.decode("ascii")
    return None


def _try_key_once(aes_module, key_bytes: bytes, ciphertext: bytes) -> str | None:
    """用单个密文快速验证候选 key。"""
    try:
        dec = aes_module.new(key_bytes, aes_module.MODE_ECB).decrypt(ciphertext)
    except Exception:
        return None
    return _guess_format(dec)


def scan_for_v2_key(dat_paths: list[Path], pids: list[int] | None = None) -> list[bytes]:
    """
    扫描微信进程内存提取 V2 AES key（16 字节）。

    移植社区工具扫描逻辑；找到的 key 再做完整 .dat 解密二次确认。

    Returns:
        确认过的 16 字节 key 列表（可能为空）。
    """
    ciphertext = _extract_ciphertext(dat_paths)
    if ciphertext is None:
        logger.warning("没有可用的 V2 .dat 样本（无法提取验证密文）")
        return []

    if not pids:
        pids = _find_wechat_pids()
    if not pids:
        logger.warning("未找到运行中的微信进程（图片 V2 解密需要微信运行）")
        return []

    for pid in pids:
        logger.info(f"扫描微信进程内存 (PID={pid})...")
        key_str = _scan_process_memory(pid, ciphertext)
        if key_str:
            key = key_str.encode("ascii")
            # 二次确认: 完整解密 2 个样本
            if _confirm_full_decrypt(key, dat_paths):
                return [key]
            logger.warning(f"候选 key {key_str} 未通过完整解密确认，继续扫描")
    return []


def _confirm_full_decrypt(key: bytes, dat_paths: list[Path]) -> bool:
    """完整解密 2 个 .dat 样本确认 key 有效（防误命中）。"""
    hits = 0
    for p in dat_paths[:6]:
        try:
            img = _decrypt_full(p.read_bytes(), key)
        except Exception:
            continue
        if img and _is_complete_image(img):
            hits += 1
            if hits >= 2:
                return True
    return False


def _decrypt_full(data: bytes, aes_key: bytes) -> bytes | None:
    """完整解密 .dat（AES-ECB 段 + 明文段 + XOR 段）。"""
    from Crypto.Cipher import AES

    if len(data) < 15 or data[:6] != DAT_SIG_V2:
        return None
    aes_size = int.from_bytes(data[6:10], "little")
    xor_size = int.from_bytes(data[10:14], "little")
    aligned = (aes_size + 15) // 16 * 16
    aes_len = aligned + (16 if aes_size % 16 == 0 else 0)
    aes_seg = data[15 : 15 + aes_len]
    raw_seg = data[15 + aes_len : len(data) - xor_size]
    xor_seg = data[len(data) - xor_size :] if xor_size else b""

    dec = AES.new(aes_key, AES.MODE_ECB).decrypt(aes_seg)
    if dec and dec[-1] <= 16:
        dec = dec[: len(dec) - dec[-1]]
    if not dec:
        return None
    xk = _guess_xor_key(xor_seg)
    xor_out = bytes(b ^ xk for b in xor_seg) if xor_seg else b""
    return dec + raw_seg + xor_out


def _guess_xor_key(xor_seg: bytes) -> int:
    """推断 XOR 段密钥（JPEG 尾 FFD9 / PNG 尾 IEND，失败回退 0x88）。"""
    if len(xor_seg) >= 2:
        k = xor_seg[-2] ^ 0xFF
        if xor_seg[-1] ^ k == 0xD9:
            return k
        k = xor_seg[-1] ^ 0xD9
        if xor_seg[-2] ^ k == 0xFF:
            return k
    if len(xor_seg) >= 8:
        tail = xor_seg[-8:]
        for k in range(256):
            if bytes(b ^ k for b in tail) == b"IEND\xaeB`\x82":
                return k
    return 0x88


def _is_complete_image(img: bytes) -> bool:
    """完整图片校验：开头魔数 + 结尾标记。"""
    if len(img) < 16:
        return False
    if img.startswith(b"\xff\xd8\xff"):  # JPEG（含无 JFIF 头变体）
        return img.rstrip(b"\x00").endswith(b"\xff\xd9")
    if img.startswith(b"\x89PNG"):
        return img.endswith(b"IEND\xaeB`\x82")
    if img.startswith(b"GIF8"):
        return img.rstrip(b"\x00").endswith(b"\x3b")
    if img[:4] == b"RIFF" and img[8:12] == b"WEBP":
        return len(img) > 12
    if img[:2] == b"BM":
        return len(img) > 14
    if img[:4] == b"wxgf":  # 微信私有 HEVC 格式
        return len(img) > 16
    return False


def derive_key_from_disk(account_dir: str | Path) -> list[bytes]:
    """
    从磁盘派生 V2 图片密钥（无需读微信进程内存）。

    算法（移植自 Bryan-Cyf/WeChatDaily find_image_key_macos.py）:
        - xor_key = uin & 0xFF（从 _t.dat 尾部投票推断）
        - aes_key = MD5(str(uin) + wxid).hex()[:16]（ASCII 16 字节）
        - 账号目录后 4 位 hex == md5(str(uin))[:4]（约束枚举空间）

    本机已验证: 100 个 .dat 中 29 个成功解密为真实 jpg/png。

    Returns:
        确认过的 16 字节 key 列表（可能为空）。
    """
    import hashlib
    from Crypto.Cipher import AES

    acct = Path(account_dir)
    dirname = acct.name
    if not dirname.startswith("wxid_"):
        return []

    # wxid 归一化: wxid_xxx_abcd → wxid_xxx（目录后缀 _abcd 非 wxid 部分）
    m = re.match(r"^(wxid_[^_]+)", dirname, re.IGNORECASE)
    wxid_norm = m.group(1) if m else dirname
    # 目录后 4 位 hex（= md5(str(uin))[:4]）
    suffix_m = re.search(r"([0-9a-fA-F]{4})$", dirname)
    if not suffix_m:
        return []
    suffix = suffix_m.group(1).lower()
    if wxid_norm == dirname:
        return []  # 无账号后缀，无法约束 uin 枚举

    attach_root = acct / "msg" / "attach"
    if not attach_root.exists():
        return []

    # ---- 1. xor_key 投票（_t.dat 尾部: JPEG EOI 0xFFD9 推断） ----
    tail_counts: dict[tuple[int, int], int] = {}
    for p in list(attach_root.rglob("*_t.dat"))[:32]:
        try:
            with open(p, "rb") as f:
                head = f.read(6)
                f.seek(-2, 2)
                tail = f.read(2)
            if head == DAT_SIG_V2 and len(tail) == 2:
                k = (tail[0], tail[1])
                tail_counts[k] = tail_counts.get(k, 0) + 1
        except OSError:
            continue
    if not tail_counts:
        return []
    x, y = max(tail_counts, key=tail_counts.get)
    xor_key = x ^ 0xFF
    if y ^ 0xD9 != xor_key:
        return []  # 投票不一致，无法确认 XOR 密钥

    # ---- 2. 模板密文（_t.dat 前 16 字节 AES 密文） ----
    ciphertexts: list[bytes] = []
    for p in attach_root.rglob("*_t.dat"):
        if len(ciphertexts) >= 3:
            break
        try:
            with open(p, "rb") as f:
                h = f.read(31)
        except OSError:
            continue
        if h[:6] == DAT_SIG_V2 and len(h) >= 31:
            ciphertexts.append(h[15:31])
    if not ciphertexts:
        return []

    # ---- 3. 枚举 uin（低 8 位 = xor_key，md5 前缀约束） ----
    lo = xor_key
    candidates: list[int] = []
    for hi in range(0x1000000):
        uin = (hi << 8) | lo
        if hashlib.md5(str(uin).encode()).hexdigest()[:4] == suffix:
            candidates.append(uin)
    logger.info(f"uin 候选: {len(candidates)} 个")

    # ---- 4. 派生 aes_key 并模板验证 ----
    wxid_variants = {wxid_norm, dirname}
    for uin in candidates:
        for wxid in wxid_variants:
            aes = hashlib.md5(f"{uin}{wxid}".encode()).hexdigest()[:16].encode("ascii")
            hits = 0
            for ct in ciphertexts:
                try:
                    dec = AES.new(aes, AES.MODE_ECB).decrypt(ct)
                except Exception:
                    break
                if _guess_format(dec):
                    hits += 1
                else:
                    break
            if hits >= 2:  # 至少 2 个模板命中
                logger.info(
                    f"磁盘派生 V2 密钥成功: uin={uin}, "
                    f"aes={aes.decode()}, xor=0x{xor_key:02x}"
                )
                return [aes]
    return []


def get_v2_keys(
    dat_paths: list[Path] | None = None,
    cache: bool = True,
    pids: list[int] | None = None,
    account_dir: str | Path | None = None,
) -> list[bytes]:
    """
    一站式获取 V2 密钥：缓存 → 磁盘派生 → 内存扫描。

    优先离线磁盘派生（不依赖微信运行）；
    失败回退进程内存扫描（需要微信运行 + 管理员权限）。

    Args:
        dat_paths: 用于验证的 .dat 文件（None 时用缓存 key）。
        cache: 是否使用/更新磁盘缓存。
        pids: 微信进程 PID（None = 自动检测）。
        account_dir: 微信账号目录（磁盘派生用；None 时尝试从
            dat_paths 推断）。

    Returns:
        确认过的密钥列表（可能为空）。
    """
    if cache and KEY_CACHE_FILE.exists():
        try:
            cached = json.loads(KEY_CACHE_FILE.read_text(encoding="utf-8"))
            keys = [bytes.fromhex(k) for k in cached]
            if keys:
                logger.info(f"使用缓存的 V2 密钥 ({len(keys)} 个)")
                return keys
        except Exception:
            pass

    # 磁盘派生（离线，首选）
    if account_dir is None and dat_paths:
        # 从 attach 路径推断: msg/attach/<hash>/... → 账号目录
        for p in dat_paths:
            parts = p.parts
            for i, seg in enumerate(parts):
                if seg == "attach" and i >= 2 and parts[i - 1] == "msg":
                    parent = Path(*parts[: i - 1])
                    if parent.name.startswith("wxid_"):
                        account_dir = parent
                        break
            if account_dir:
                break
    if account_dir:
        keys = derive_key_from_disk(account_dir)
        if keys:
            _save_key_cache(keys, cache)
            return keys

    # 内存扫描（需要微信运行）
    if not dat_paths:
        return []
    keys = scan_for_v2_key(dat_paths, pids=pids)
    if keys:
        _save_key_cache(keys, cache)
    return keys


def _save_key_cache(keys: list[bytes], cache: bool) -> None:
    """持久化密钥缓存。"""
    if not cache:
        return
    try:
        KEY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_CACHE_FILE.write_text(
            json.dumps([k.hex() for k in keys], ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
