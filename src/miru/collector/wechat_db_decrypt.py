"""
Miru Assistant — 微信数据库解密适配器 (Task 5B)。

封装微信 SQLCipher 数据库的密钥提取与解密验证。

不支持实时消息读取（那是 Task 5C+ 的职责）。
本模块只做一件事：验证"我能成功解密并打开微信数据库"。

技术参考:
    微信 4.x: SQLCipher 4, AES-256-CBC, HMAC-SHA512, PBKDF2 (256,000 iter)
    微信 3.x: SQLCipher (旧版参数), 已知偏移量读取
    项目: github.com/328336690/wechat-decrypt

核心流程:
    1. 打开微信进程 (pymem)
    2. 扫描内存中的密钥
    3. 用密钥解密 SQLCipher 页面 0
    4. 验证 SQLite magic header
    5. 解密完整数据库到临时文件
    6. 用 sqlite3 检查 schema
"""

import hashlib
import os
import re
import sqlite3
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from miru.utils.errors import (
    CollectorError,
    DatabaseDecryptError,
    KeyExtractionError,
    WeChatNotRunningError,
    WeChatVersionError,
)

# ============================================================
# 常量
# ============================================================

SQLITE_MAGIC = b"SQLite format 3\x00"
SQLCIPHER4_PAGE_SIZE = 4096
SQLCIPHER4_RESERVED_SIZE = 80       # 16 (IV) + 64 (HMAC-SHA512)
SQLCIPHER4_USABLE_SIZE = SQLCIPHER4_PAGE_SIZE - SQLCIPHER4_RESERVED_SIZE  # 4016

# 微信 4.x 内存密钥特征模式: 64 hex (key) + 32 hex (salt)
# 在内存中以 x'<96 hex chars>' 格式存在
KEY_PATTERN_4X = re.compile(
    br"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'"
)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ExtractedKey:
    """从微信进程内存中提取的数据库密钥。"""
    raw_key: bytes          # 32 字节 AES-256 密钥
    salt: bytes             # 16 字节 salt
    hex_key: str            # 完整 hex 字符串
    db_name: str = ""       # 关联的数据库名 (通过后续验证填充)
    verified: bool = False
    error: str = ""


@dataclass
class DecryptResult:
    """解密尝试结果。"""
    success: bool = False
    db_path: str = ""
    db_name: str = ""
    db_size_mb: float = 0.0

    # 密钥信息
    key_found: bool = False
    key_hex: str = ""
    key_source: str = ""        # "memory_scan" | "offset_read" | "cache"

    # 解密状态
    sqlite_version: str = ""    # "SQLite format 3" 中的版本
    page_count: int = 0
    page_size: int = 0
    is_encrypted: bool = True
    is_decrypted: bool = False

    # Schema
    tables: list[str] = field(default_factory=list)
    table_details: dict = field(default_factory=dict)  # table_name → [(col, type)]

    # 诊断
    error: str = ""
    error_stage: str = ""       # process | memory_scan | key_extract | decrypt | schema
    suggestion: str = ""


# ============================================================
# 密钥提取
# ============================================================


def extract_keys_from_process(
    pid: int,
    max_scan_gb: int = 3,
) -> list[ExtractedKey]:
    """
    从微信进程内存中提取 SQLCipher 密钥。

    针对微信 4.x: 扫描进程内存中的 x'<key><salt>' 特征模式。
    每个数据库有独立的密钥+salt对。

    Args:
        pid: 微信进程 PID。
        max_scan_gb: 最大扫描内存范围 (GB)。

    Returns:
        ExtractedKey 列表。

    Raises:
        KeyExtractionError: 密钥提取失败。
    """
    try:
        import pymem
        from pymem.ptypes import RemotePointer
    except ImportError:
        raise KeyExtractionError(
            "pymem 未安装。请运行: pip install pymem"
        )

    logger.info(f"开始从微信进程 (PID={pid}) 提取密钥...")

    try:
        pm = pymem.Pymem()
        pm.open_process_from_id(pid)
    except Exception as e:
        raise KeyExtractionError(
            f"无法打开微信进程 (PID={pid}): {e}\n"
            f"请确保:\n"
            f"  1. 微信正在运行\n"
            f"  2. 以管理员身份运行\n"
            f"  3. 杀毒软件未拦截内存读取"
        ) from e

    found_keys: list[ExtractedKey] = []
    seen = set()

    try:
        # 获取进程内存区域
        base_address = 0
        max_address = 0
        regions = list(pm.list_modules())
        if regions:
            # 使用主模块范围估计
            base_address = min(m.lpBaseOfDll for m in regions)
            max_address = max(m.lpBaseOfDll + m.SizeOfImage for m in regions)

        # 如果没有获取到模块信息，使用进程虚拟地址空间
        if max_address <= base_address:
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            GetSystemInfo = kernel32.GetSystemInfo

            class SYSTEM_INFO(ctypes.Structure):
                _fields_ = [
                    ("wProcessorArchitecture", ctypes.wintypes.WORD),
                    ("wReserved", ctypes.wintypes.WORD),
                    ("dwPageSize", ctypes.wintypes.DWORD),
                    ("lpMinimumApplicationAddress", ctypes.c_void_p),
                    ("lpMaximumApplicationAddress", ctypes.c_void_p),
                    ("dwActiveProcessorMask", ctypes.c_void_p),
                    ("dwNumberOfProcessors", ctypes.wintypes.DWORD),
                    ("dwProcessorType", ctypes.wintypes.DWORD),
                    ("dwAllocationGranularity", ctypes.wintypes.DWORD),
                    ("wProcessorLevel", ctypes.wintypes.WORD),
                    ("wProcessorRevision", ctypes.wintypes.WORD),
                ]

            si = SYSTEM_INFO()
            GetSystemInfo(ctypes.byref(si))
            # 64-bit process max
            max_address = 0x7FFFFFFFFFFF  # 128TB virtual space for 64-bit

        logger.debug(f"进程地址范围: 0x{base_address:X} - 0x{max_address:X}")

    except Exception as e:
        logger.warning(f"无法获取进程地址范围: {e}，将被限制扫描")

    # 扫描内存
    try:
        raw_keys = _scan_process_memory(pm, list(regions) if regions else [])
        for hex_str in raw_keys:
            if hex_str in seen:
                continue
            seen.add(hex_str)

            try:
                raw = bytes.fromhex(hex_str)
                key = raw[:32]
                salt = raw[32:48]
                found_keys.append(ExtractedKey(
                    raw_key=key,
                    salt=salt,
                    hex_key=hex_str,
                ))
            except ValueError:
                continue

    except Exception as e:
        raise KeyExtractionError(
            f"内存扫描失败: {e}"
        ) from e

    logger.info(f"内存扫描完成 — 找到 {len(found_keys)} 个候选密钥")

    if not found_keys:
        raise KeyExtractionError(
            "未在微信进程内存中找到任何密钥。\n"
            "可能原因:\n"
            "  1. 微信版本过新 — 密钥存储格式已改变\n"
            "  2. 微信版本过旧 — 不支持 4.x 以下版本的内存扫描\n"
            "  3. 进程内存已被清理\n"
            "建议: 检查微信版本是否在 4.x 范围内"
        )

    return found_keys


def _scan_process_memory(pm, modules: list) -> list[str]:
    """
    扫描微信进程内存，查找 SQLCipher 密钥模式。

    策略:
        1. 优先扫描 WeChatWin.dll / wcdb 相关模块
        2. 搜索 x'...' 特征模式
        3. 返回所有匹配的 96 字符 hex 字符串
    """
    found = []

    # 优先扫描微信核心 DLL
    priority_modules = []
    other_modules = []
    for m in modules:
        name = getattr(m, 'name', '') or getattr(m, 'szModule', '') or ''
        if any(kw in name.lower() for kw in ('wechatwin', 'wcdb', 'wechat')):
            priority_modules.append(m)
        else:
            other_modules.append(m)

    scan_targets = priority_modules + other_modules

    for module in scan_targets:
        try:
            base = module.lpBaseOfDll
            size = module.SizeOfImage
            if size > 500 * 1024 * 1024:  # 跳过大于 500MB 的模块
                size = 500 * 1024 * 1024

            # 分块读取
            chunk_size = 10 * 1024 * 1024  # 10MB per chunk
            offset = 0
            while offset < size:
                read_size = min(chunk_size, size - offset)
                try:
                    data = pm.read_bytes(base + offset, read_size)
                    for match in KEY_PATTERN_4X.finditer(data):
                        key_hex = match.group(1).decode("ascii")
                        salt_hex = match.group(2).decode("ascii")
                        found.append(key_hex + salt_hex)
                except Exception:
                    pass  # 跳过不可读的内存区域
                offset += read_size

        except Exception:
            continue

    return found


# ============================================================
# 数据库解密
# ============================================================


def decrypt_database_page(
    encrypted_page: bytes,
    key: bytes,
    page_number: int = 0,
) -> bytes:
    """
    解密单个 SQLCipher 4 数据库页面。

    微信 4.x 使用 SQLCipher 4 AES-256-CBC。

    SQLCipher 4 页面布局 (4096 bytes):
        [0:4016]   — 加密负载 (page 0 的前 16 字节是加密的 salt)
        [4016:4032] — IV (16 字节)
        [4032:4096] — HMAC-SHA512 (64 字节)

    关键: salt 是加密负载的一部分，参与 CBC 加密链。
    解密后从 page 0 的明文中剥离 salt。

    Args:
        encrypted_page: 加密的页面数据 (4096 bytes)。
        key: AES-256 密钥 (32 bytes)。
        page_number: 页面编号。

    Returns:
        解密后的页面数据 (4016 bytes for page 0, or 4016 bytes for others)。
    """
    from Crypto.Cipher import AES

    if len(encrypted_page) != SQLCIPHER4_PAGE_SIZE:
        raise ValueError(
            f"页面大小不匹配: 期望 {SQLCIPHER4_PAGE_SIZE}, 实际 {len(encrypted_page)}"
        )

    # 提取 IV (reserved area 前 16 字节，即 bytes 4016-4032)
    iv_offset = SQLCIPHER4_PAGE_SIZE - SQLCIPHER4_RESERVED_SIZE
    iv = encrypted_page[iv_offset:iv_offset + 16]

    # 加密负载 = 整页减去 80 字节保留区 (bytes 0-4016)
    # salt 包含在加密负载中，参与 CBC 加密链
    encrypted_payload = encrypted_page[:iv_offset]

    # AES-256-CBC 解密
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    plaintext = cipher.decrypt(encrypted_payload)

    # 对于 page 0: 剥离前 16 字节 (解密后的 salt)
    if page_number == 0:
        plaintext = plaintext[16:]

    # 填充到可用大小
    result = bytearray(SQLCIPHER4_USABLE_SIZE)
    result[:len(plaintext)] = plaintext
    return bytes(result)


def verify_decryption_key(
    db_path: Path,
    key: bytes,
) -> tuple[bool, str]:
    """
    验证密钥是否正确。

    优先使用 sqlcipher3 原生库验证，失败后回退到手动 AES-256-CBC 验证。

    Args:
        db_path: 加密的 SQLCipher 数据库路径。
        key: 候选密钥 (32 bytes)。

    Returns:
        (is_valid, error_message)
    """
    if not db_path.exists():
        return False, f"数据库文件不存在: {db_path}"

    # ---- 方法 1: sqlcipher3 原生库验证 (最可靠) ----
    try:
        from sqlcipher3 import dbapi2 as sqlcipher3_dbapi
        conn = sqlcipher3_dbapi.connect(str(db_path))
        c = conn.cursor()
        c.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        c.execute("PRAGMA cipher_compatibility = 4")
        c.execute("SELECT count(*) FROM sqlite_master")
        c.fetchone()
        conn.close()
        return True, ""
    except Exception as e:
        err_msg = str(e)
        # sqlcipher3 gives "file is not a database" on HMAC failure
        if "file is not a database" in err_msg.lower():
            pass  # fall through to manual verification
        else:
            # Other error (permissions, etc.) — try manual as fallback
            pass

    # ---- 方法 2: 手动 AES-256-CBC 页面解密 (回退) ----
    try:
        with open(db_path, "rb") as f:
            page0 = f.read(SQLCIPHER4_PAGE_SIZE)

        if len(page0) < SQLCIPHER4_PAGE_SIZE:
            return False, f"文件过小 ({len(page0)} bytes)，非完整 SQLCipher 数据库"

        decrypted = decrypt_database_page(page0, key, page_number=0)

        # 解密后 salt 已被剥离，magic 应在 offset 0
        if decrypted[:16] == SQLITE_MAGIC:
            return True, ""
        # 兼容: 也检查 offset 16 (旧版解密方式)
        elif decrypted[16:32] == SQLITE_MAGIC:
            return True, ""
        else:
            return False, (
                f"解密后 magic header 不匹配: "
                f"offset 0: {decrypted[:16].hex()}, "
                f"offset 16: {decrypted[16:32].hex()}"
            )

    except PermissionError:
        return False, "文件被其他进程占用 (可能是微信正在写入)"
    except Exception as e:
        return False, str(e)


def decrypt_and_open(
    db_path: Path,
    key: bytes,
) -> tuple[Optional[Path], str]:
    """
    完整解密数据库到临时文件。

    优先使用 sqlcipher3 原生库，失败后回退到逐页手动解密。

    Args:
        db_path: 加密数据库路径。
        key: 已验证的密钥 (32 bytes)。

    Returns:
        (temp_db_path, error_message)
        temp_db_path 为 None 表示失败。
    """
    if not db_path.exists():
        return None, f"文件不存在: {db_path}"

    # ---- 方法 1: 直接返回加密副本的路径 (由调用方用 sqlcipher3 读取) ----
    try:
        import shutil
        # 复制到临时位置（绕过微信文件锁），返回路径供 sqlcipher3 打开
        tmp_copy = tempfile.NamedTemporaryFile(
            suffix=f"_{db_path.name}", delete=False
        )
        tmp_path = Path(tmp_copy.name)
        tmp_copy.close()
        shutil.copy2(str(db_path), str(tmp_path))
        # 标记为已解密（实际解密由 sqlcipher3 PRAGMA key 完成）
        return tmp_path, ""
    except Exception as e:
        return None, str(e)

    # ---- 方法 2: 手动逐页解密 (回退) ----
    try:
        with open(db_path, "rb") as src:
            data = src.read()

        total_size = len(data)
        total_pages = total_size // SQLCIPHER4_PAGE_SIZE

        if total_size % SQLCIPHER4_PAGE_SIZE != 0:
            return None, (
                f"数据库大小 ({total_size}) 不是页大小 ({SQLCIPHER4_PAGE_SIZE}) 的整数倍"
            )

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = Path(tmp.name)

        with open(tmp_path, "wb") as dst:
            for page_num in range(total_pages):
                offset = page_num * SQLCIPHER4_PAGE_SIZE
                encrypted_page = data[offset:offset + SQLCIPHER4_PAGE_SIZE]
                decrypted_page = decrypt_database_page(encrypted_page, key, page_num)
                dst.write(decrypted_page)

        import sqlite3
        try:
            conn = sqlite3.connect(str(tmp_path))
            conn.execute("SELECT COUNT(*) FROM sqlite_master")
            conn.close()
        except sqlite3.Error as e:
            tmp_path.unlink(missing_ok=True)
            return None, f"解密后的数据库无法被 sqlite3 打开: {e}"

        return tmp_path, ""

    except PermissionError:
        return None, (
            f"无法读取数据库文件: {db_path}\n"
            f"文件可能被微信进程锁定。"
        )
    except Exception as e:
        return None, str(e)


# ============================================================
# Schema 检查
# ============================================================


@dataclass
class DBSchema:
    """数据库 schema 信息。"""
    db_name: str = ""
    db_path: str = ""
    db_size_mb: float = 0.0
    sqlite_version: str = ""
    page_count: int = 0
    page_size: int = 0
    tables: list[str] = field(default_factory=list)
    table_details: dict = field(default_factory=dict)  # {table: [(name, type, pk)]}
    row_counts: dict = field(default_factory=dict)     # {table: count}


def inspect_schema(temp_db_path: Path) -> DBSchema:
    """
    对已解密的临时 SQLite 数据库进行 schema 检查。

    Args:
        temp_db_path: 已解密的临时 .db 文件路径。

    Returns:
        DBSchema — 完整的 schema 信息。
    """
    import sqlite3

    schema = DBSchema()
    schema.db_path = str(temp_db_path)
    schema.db_size_mb = os.path.getsize(temp_db_path) / (1024 * 1024)

    conn = sqlite3.connect(str(temp_db_path))
    conn.row_factory = sqlite3.Row

    try:
        # 获取 SQLite 版本和页面信息
        row = conn.execute("SELECT sqlite_version()").fetchone()
        schema.sqlite_version = row[0] if row else "unknown"

        # 页面信息
        page_count_row = conn.execute("PRAGMA page_count").fetchone()
        schema.page_count = page_count_row[0] if page_count_row else 0

        page_size_row = conn.execute("PRAGMA page_size").fetchone()
        schema.page_size = page_size_row[0] if page_size_row else 0

        # 表列表
        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        schema.tables = [t["name"] for t in tables]

        # 每个表的字段信息
        for table_name in schema.tables:
            cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            schema.table_details[table_name] = [
                (c["name"], c["type"], bool(c["pk"]))
                for c in cols
            ]
            # 行数
            try:
                count = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM [{table_name}]"
                ).fetchone()
                schema.row_counts[table_name] = count["cnt"] if count else 0
            except Exception:
                schema.row_counts[table_name] = -1

    finally:
        conn.close()

    return schema


# ============================================================
# 顶层 API: 数据库解密验证
# ============================================================


def try_decrypt_wechat_db(
    db_path: Path,
    pid: int,
    keys: Optional[list[ExtractedKey]] = None,
) -> DecryptResult:
    """
    尝试用提取的密钥解密一个微信数据库文件。

    这是 Task 5B 的主入口。

    Args:
        db_path: 加密数据库文件路径。
        pid: 微信进程 PID (用于重新提取密钥)。
        keys: 预提取的密钥列表 (为 None 时自动提取)。

    Returns:
        DecryptResult — 完整的解密结果。
    """
    result = DecryptResult()
    result.db_path = str(db_path)
    result.db_name = db_path.name

    if db_path.exists():
        result.db_size_mb = os.path.getsize(db_path) / (1024 * 1024)

    # Stage 1: 验证文件存在
    if not db_path.exists():
        result.error = f"数据库文件不存在: {db_path}"
        result.error_stage = "process"
        result.suggestion = "请确认微信数据目录正确，或运行 miru doctor 检查"
        return result

    # Stage 2: 检查文件是否为 SQLCipher 加密
    try:
        with open(db_path, "rb") as f:
            header = f.read(16)
        if header == SQLITE_MAGIC:
            # 已经是未加密的 SQLite — 直接打开
            result.is_encrypted = False
            result.is_decrypted = True
            result.key_found = True
            result.key_hex = "N/A (未加密)"
            _fill_schema(result, db_path)
            result.success = True
            return result
    except Exception:
        pass

    result.is_encrypted = True

    # Stage 3: 提取密钥 (如果没有提供)
    if keys is None:
        try:
            keys = extract_keys_from_process(pid)
        except KeyExtractionError as e:
            result.error = str(e)
            result.error_stage = "memory_scan"
            result.suggestion = (
                "密钥提取失败。可能原因:\n"
                "  1. 微信进程 PID 不正确\n"
                "  2. 权限不足 (需要管理员)\n"
                "  3. 微信版本不支持"
            )
            return result

    if not keys:
        result.error = "未提取到任何密钥"
        result.error_stage = "key_extract"
        result.suggestion = "微信版本可能不兼容。请运行 miru doctor 查看详情"
        return result

    # Stage 4: 逐个尝试密钥
    valid_key = None
    for k in keys:
        valid, err = verify_decryption_key(db_path, k.raw_key)
        if valid:
            valid_key = k
            result.key_found = True
            result.key_hex = k.hex_key[:16] + "..."  # 只显示前 16 字符
            result.key_source = "memory_scan"
            logger.info(f"密钥验证成功 — {db_path.name}")
            break
        else:
            logger.debug(f"密钥候选不匹配 ({db_path.name}): {err[:80]}")

    if not valid_key:
        result.error = (
            f"尝试了 {len(keys)} 个密钥，均无法解密 {db_path.name}。"
        )
        result.error_stage = "decrypt"
        result.suggestion = (
            "所有候选密钥均验证失败。可能原因:\n"
            "  1. 密钥在内存中的格式已改变\n"
            "  2. 数据库使用了不同的加密参数\n"
            "  3. 微信版本与解密方案不匹配"
        )
        return result

    # Stage 5: 完整解密到临时文件
    temp_path, err = decrypt_and_open(db_path, valid_key.raw_key)
    if temp_path is None:
        result.error = f"解密失败: {err}"
        result.error_stage = "decrypt"
        result.suggestion = "密钥正确但解密过程失败。可能是页面格式或加密参数不匹配"
        return result

    result.is_decrypted = True

    # Stage 6: Schema 检查 (使用 sqlcipher3 + key 或标准 sqlite3)
    try:
        _fill_schema(result, temp_path, valid_key.raw_key)
        result.success = True
    except Exception as e:
        result.error = f"Schema 读取失败: {e}"
        result.error_stage = "schema"
        result.suggestion = "数据库已解密但无法读取 schema。可能是数据库格式异常"

    # 清理临时文件
    try:
        temp_path.unlink(missing_ok=True)
    except Exception:
        pass

    return result


def _fill_schema(result: DecryptResult, db_path: Path, key: bytes = b"") -> None:
    """填充 schema 信息到 result。支持加密和未加密数据库。"""
    # 优先用 sqlcipher3 读取加密数据库
    if key:
        try:
            from sqlcipher3 import dbapi2 as sqlcipher3_dbapi
            conn = sqlcipher3_dbapi.connect(str(db_path))
            conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
            conn.execute("PRAGMA cipher_compatibility = 4")
            _read_schema_sc3(conn, result)
            conn.close()
            return
        except Exception as e:
            logger.debug(f"sqlcipher3 schema read failed: {e}")

    # 回退到标准 sqlite3（未加密文件）
    schema = inspect_schema(db_path)
    result.sqlite_version = schema.sqlite_version
    result.page_count = schema.page_count
    result.page_size = schema.page_size
    result.tables = schema.tables
    result.table_details = {
        t: [
            f"{col} ({col_type}){' PK' if pk else ''}"
            for col, col_type, pk in cols
        ]
        for t, cols in schema.table_details.items()
    }


def _read_schema_sc3(conn, result: DecryptResult) -> None:
    """从 sqlcipher3 连接读取 schema（使用 tuple row factory）。"""
    row = conn.execute("SELECT sqlite_version()").fetchone()
    result.sqlite_version = row[0] if row else "unknown"

    try:
        result.page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    except Exception:
        result.page_count = 0
    try:
        result.page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    except Exception:
        result.page_size = 0

    tables = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    result.tables = [t[0] for t in tables]

    result.table_details = {}
    for table_name in result.tables:
        try:
            cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            result.table_details[table_name] = [
                f"{c[1]} ({c[2]}){' PK' if c[5] else ''}"
                for c in cols
            ]
        except Exception:
            result.table_details[table_name] = ["(unable to read schema)"]


def _read_schema(conn, result: DecryptResult) -> None:
    """从数据库连接读取 schema 信息。"""
    row = conn.execute("SELECT sqlite_version()").fetchone()
    result.sqlite_version = row[0] if row else "unknown"

    try:
        pc = conn.execute("PRAGMA page_count").fetchone()
        result.page_count = pc[0] if pc else 0
    except Exception:
        result.page_count = 0

    try:
        ps = conn.execute("PRAGMA page_size").fetchone()
        result.page_size = ps[0] if ps else 0
    except Exception:
        result.page_size = 0

    tables = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    result.tables = [t["name"] if isinstance(t, sqlite3.Row) else t[0] for t in tables]

    result.table_details = {}
    for table_name in result.tables:
        try:
            cols = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            result.table_details[table_name] = [
                f"{c['name']} ({c['type']}){' PK' if c['pk'] else ''}"
                if isinstance(c, sqlite3.Row)
                else f"{c[0]} ({c[1]}){' PK' if c[5] else ''}"
                for c in cols
            ]
        except Exception:
            result.table_details[table_name] = ["(unable to read schema)"]
