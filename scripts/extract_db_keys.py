#!/usr/bin/env python
"""
Miru Assistant — Chat Analyzer 微信数据库密钥提取工具。

从微信进程内存中提取所有数据库分片的 SQLCipher 密钥，
保存到 config/database_keys.yaml。

原理:
    微信 4.x 每个数据库 (message_0.db, message_1.db, ...) 有独立密钥。
    密钥以 x'<64hex key><32hex salt>' 形式驻留在 Weixin.exe 主进程内存中。
    通过遍历进程可读内存页 + 正则匹配提取 key+salt 对，
    再与数据库文件头的 salt 比对确认归属。

用法:
    python scripts/extract_db_keys.py              # 提取并保存
    python scripts/extract_db_keys.py --dry-run    # 只显示不保存

退出码:
    0 = 成功（保存）
    2 = 失败（微信未运行 / 无权限 / 提取失败）
"""

import argparse
import ctypes
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# x'<key64><salt32>' 特征模式
KEY_PATTERN = re.compile(rb"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'")

MEM_COMMIT = 0x1000
READABLE_PROTECTS = {
    0x02,
    0x04,
    0x20,
    0x40,
}  # PAGE_READONLY / READWRITE / EXECUTE_READ / EXECUTE_READWRITE


def _get_shard_salts() -> dict[str, str]:
    """读取所有微信数据库文件的 salt (文件头前 16 字节)。"""
    from miru.collector.diagnostics import find_wechat_data_dir
    from miru.utils.config import load_config

    cfg = load_config("config/settings.yaml")
    data_dir = find_wechat_data_dir(cfg.miru.wechat.data_dir)
    dp = Path(data_dir.path)

    salts: dict[str, str] = {}
    # 扫描 db_storage 下所有子目录的 .db 文件
    storage = dp / "db_storage"
    if storage.exists():
        for f in sorted(storage.rglob("*.db")):
            try:
                with open(f, "rb") as fh:
                    salts[f.name] = fh.read(16).hex()
            except Exception:
                continue
    return salts


def _find_weixin_processes() -> list[int]:
    """查找所有 Weixin.exe 主进程 PID。"""
    import psutil

    pids: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() == "weixin.exe":
                pids.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def _scan_process(pid: int) -> list[tuple[str, str]]:
    """
    扫描进程内存，返回 [(key_hex, salt_hex)] 列表。

    Args:
        pid: 目标进程 PID。

    Returns:
        (key, salt) 匹配对列表。
    """
    import pymem

    pm = pymem.Pymem()
    pm.open_process_from_id(pid)

    kernel32 = ctypes.windll.kernel32

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", ctypes.c_ulong),
            ("RegionSize", ctypes.c_size_t),
            ("State", ctypes.c_ulong),
            ("Protect", ctypes.c_ulong),
            ("Type", ctypes.c_ulong),
        ]

    matches: list[tuple[str, str]] = []
    addr = 0
    max_addr = 0x7FFFFFFFFFFF

    while addr < max_addr:
        mbi = MBI()
        ret = kernel32.VirtualQueryEx(
            pm.process_handle,
            ctypes.c_void_p(addr),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi),
        )
        if ret == 0:
            break
        sz = mbi.RegionSize
        if sz == 0:
            addr += 0x10000
            continue

        if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in READABLE_PROTECTS:
            try:
                chunk = 8 * 1024 * 1024
                off = 0
                while off < sz:
                    read_size = min(chunk, sz - off)
                    data = pm.read_bytes(mbi.BaseAddress + off, read_size)
                    for m in KEY_PATTERN.finditer(data):
                        matches.append((m.group(1).decode(), m.group(2).decode()))
                    off += read_size
            except Exception:
                pass  # 不可读区域跳过
        addr += sz

    return matches


def main() -> int:
    """主入口。返回退出码。"""
    parser = argparse.ArgumentParser(
        description="Miru Chat Analyzer — 提取微信数据库密钥",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示提取结果，不写入配置文件",
    )
    parser.add_argument(
        "--output",
        default="config/database_keys.yaml",
        help="密钥保存路径（默认: config/database_keys.yaml）",
    )
    args = parser.parse_args()

    import yaml
    from loguru import logger

    from miru.collector.diagnostics import detect_wechat_process

    # ---- 1. 确认微信运行 ----
    proc = detect_wechat_process()
    if not proc.found:
        print("[错误] 微信未运行 — 请先启动微信 PC 客户端")
        return 2

    # ---- 2. 读取所有数据库 salt ----
    salts = _get_shard_salts()
    if not salts:
        print("[错误] 未找到微信数据库文件")
        return 2
    salt_to_name = {v: k for k, v in salts.items()}
    print(f"找到 {len(salts)} 个数据库文件")

    # ---- 3. 扫描所有 Weixin 主进程 ----
    pids = _find_weixin_processes()
    print(f"Weixin 进程: {pids}")

    found_keys: dict[str, str] = {}
    for pid in pids:
        try:
            matches = _scan_process(pid)
            print(f"  PID={pid}: 找到 {len(matches)} 个密钥模式")
            for key_hex, salt_hex in matches:
                name = salt_to_name.get(salt_hex)
                if name and name not in found_keys:
                    found_keys[name] = key_hex
        except Exception as e:
            logger.debug(f"进程 {pid} 扫描失败: {e}")

    if not found_keys:
        print("[错误] 未匹配到任何数据库密钥")
        return 2

    print()
    print(f"成功提取 {len(found_keys)}/{len(salts)} 个数据库密钥:")
    for name in sorted(found_keys):
        key = found_keys[name]
        print(f"  {name}: {key[:16]}...{key[-8:]}")

    # ---- 4. 保存 ----
    if args.dry_run:
        print("\n(dry-run 模式，未写入)")
        return 0

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(
            {"keys": {k: found_keys[k] for k in sorted(found_keys)}},
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    print(f"\n密钥已保存 → {output}")

    missing = [n for n in salts if n not in found_keys]
    if missing:
        print(f"[警告] 以下数据库未提取到密钥: {missing}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
