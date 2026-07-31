"""
Miru Assistant — 微信环境诊断工具 (Task 5A)。

纯只读检测。不读取聊天内容、不修改微信、不注入进程、不实现 Hook。

功能:
    - 检测 Windows 版本与架构
    - 检测微信进程状态 (PID / 路径 / 版本)
    - 自动定位微信数据目录
    - 扫描数据库文件 (.db)
    - 检查管理员权限
    - 检查 Python 依赖是否就绪
    - 输出结构化诊断报告
"""

import ctypes
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
from loguru import logger

# ============================================================
# 数据模型
# ============================================================


@dataclass
class ProcessInfo:
    """微信进程信息。"""
    found: bool = False
    pid: int = 0
    exe_path: str = ""
    version: str = ""
    version_major: int = 0          # 3 or 4
    version_raw: str = ""            # 完整版本号 e.g. "4.0.3.29"
    status: str = ""
    error: str = ""


@dataclass
class DataDirInfo:
    """微信数据目录信息。"""
    found: bool = False
    path: str = ""
    wxid: str = ""                   # 微信用户 ID 前缀
    source: str = ""                 # "auto-detect" | "config" | "not found"


@dataclass
class DBFileInfo:
    """单个数据库文件信息。"""
    name: str = ""
    path: str = ""
    exists: bool = False
    size_bytes: int = 0
    size_mb: float = 0.0
    is_encrypted: bool = True        # 微信数据库必然是加密的
    note: str = ""


@dataclass
class PermissionInfo:
    """权限信息。"""
    is_admin: bool = False
    can_read_process_memory: bool = False  # 是否有 SeDebugPrivilege
    error: str = ""


@dataclass
class DependencyStatus:
    """Python 依赖包状态。"""
    name: str = ""
    installed: bool = False
    version: str = ""
    required: bool = True


@dataclass
class DiagnosticReport:
    """完整诊断报告。"""

    # 元数据
    timestamp: str = ""
    hostname: str = ""
    windows_version: str = ""
    windows_arch: str = ""
    python_version: str = ""

    # 微信检测
    wechat_process: ProcessInfo = field(default_factory=ProcessInfo)
    wechat_data_dir: DataDirInfo = field(default_factory=DataDirInfo)
    db_files: list[DBFileInfo] = field(default_factory=list)

    # 权限
    permissions: PermissionInfo = field(default_factory=PermissionInfo)

    # 依赖
    dependencies: list[DependencyStatus] = field(default_factory=list)

    # 结论
    ready_for_decryption: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转为可序列化的字典（供 CLI 输出和日志）。"""
        return {
            "timestamp": self.timestamp,
            "hostname": self.hostname,
            "windows": f"{self.windows_version} ({self.windows_arch})",
            "python": self.python_version,
            "wechat": {
                "running": self.wechat_process.found,
                "pid": self.wechat_process.pid or None,
                "version": self.wechat_process.version,
                "version_major": self.wechat_process.version_major,
                "exe_path": self.wechat_process.exe_path,
                "status": self.wechat_process.status,
            },
            "data_dir": {
                "found": self.wechat_data_dir.found,
                "path": self.wechat_data_dir.path,
                "wxid": self.wechat_data_dir.wxid,
                "source": self.wechat_data_dir.source,
            },
            "db_files": [
                {
                    "name": f.name,
                    "exists": f.exists,
                    "size_mb": round(f.size_mb, 2) if f.exists else None,
                    "note": f.note,
                }
                for f in self.db_files
            ],
            "permissions": {
                "is_admin": self.permissions.is_admin,
                "can_read_memory": self.permissions.can_read_process_memory,
            },
            "dependencies": [
                {"name": d.name, "installed": d.installed, "version": d.version}
                for d in self.dependencies
            ],
            "ready": self.ready_for_decryption,
            "issues": self.issues,
            "warnings": self.warnings,
            "next_steps": self.next_steps,
        }


# ============================================================
# 检测函数
# ============================================================


def detect_windows() -> tuple[str, str, str]:
    """
    检测 Windows 版本、架构和主机名。

    Returns:
        (hostname, windows_version, arch)
    """
    hostname = platform.node()
    version = f"Windows {platform.release()} ({platform.version()})"
    arch = platform.machine()
    logger.info(f"Windows 检测: {version}, arch={arch}")
    return hostname, version, arch


def detect_wechat_process() -> ProcessInfo:
    """
    检测微信 PC 客户端进程。

    通过进程名 "WeChat.exe" 搜索进程列表。
    读取其可执行文件路径，获取版本信息。

    Returns:
        ProcessInfo — 微信进程详细信息。
    """
    info = ProcessInfo()

    # Step 1: 查找进程
    # 微信 PC 进程名可能是 WeChat.exe (英文版) 或 Weixin.exe (中文版)
    wechat_procs = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name in ("wechat.exe", "weixin.exe"):
                wechat_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not wechat_procs:
        info.status = "微信未运行"
        info.error = "请先启动微信并登录"
        logger.warning("未检测到 WeChat.exe 进程")
        return info

    if len(wechat_procs) > 1:
        logger.warning(f"检测到 {len(wechat_procs)} 个 WeChat.exe 进程，使用第一个")

    proc = wechat_procs[0]
    info.found = True
    info.pid = proc.info["pid"]
    info.exe_path = proc.info["exe"] or ""

    if not info.exe_path:
        info.status = "微信已运行但无法获取可执行文件路径"
        info.error = "权限不足 (需要管理员权限)"
        return info

    # Step 2: 获取版本号
    info.version_raw = _get_file_version(info.exe_path)
    if info.version_raw:
        info.version = f"微信 v{info.version_raw}"
        try:
            info.version_major = int(info.version_raw.split(".")[0])
        except (ValueError, IndexError):
            pass
    else:
        info.version = "微信 (版本未知)"
        info.error = "无法读取微信版本信息"

    # Step 3: 状态判定
    if info.version_major == 4:
        info.status = f"微信 4.x 已运行 (PID={info.pid}) — 支持内存扫描方案"
    elif info.version_major == 3:
        info.status = f"微信 3.x 已运行 (PID={info.pid}) — 支持偏移读取方案"
    elif info.version_major == 0:
        info.status = f"微信已运行 (PID={info.pid}) — 版本未知，将尝试内存扫描"
    else:
        info.status = f"微信 {info.version_major}.x (PID={info.pid}) — 版本可能不兼容"

    logger.info(f"微信进程: PID={info.pid}, version={info.version_raw}, path={info.exe_path}")
    return info


def _get_file_version(exe_path: str) -> str:
    """
    从 PE 文件中读取 FileVersion。

    使用 PowerShell 获取 (兼容性好，无额外依赖)。
    """
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"(Get-Item '{exe_path}').VersionInfo.FileVersion",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip()
        if version:
            return version
    except Exception as e:
        logger.debug(f"PowerShell 版本读取失败: {e}")

    # Fallback: 尝试直接解析 PE 文件
    try:
        return _get_file_version_from_pe(exe_path)
    except Exception:
        pass

    return ""


def _get_file_version_from_pe(exe_path: str) -> str:
    """
    从 PE 文件头读取 VS_FIXEDFILEINFO 中的版本号。

    不使用 pywin32/pefile 等第三方库。
    直接解析 PE 结构。
    """
    import struct

    with open(exe_path, "rb") as f:
        # 读取 DOS header
        dos_header = f.read(64)
        if dos_header[:2] != b"MZ":
            return ""

        # PE header offset (at byte 60)
        pe_offset = struct.unpack("<I", dos_header[60:64])[0]
        f.seek(pe_offset)
        pe_sig = f.read(4)
        if pe_sig != b"PE\0\0":
            return ""

        # Optional header (after 20-byte COFF header)
        coff = f.read(20)
        # SizeOfOptionalHeader at byte 16 of COFF
        optional_size = struct.unpack("<H", coff[16:18])[0]
        optional_start = f.tell()

        # Read the optional header
        optional = f.read(optional_size)
        magic = struct.unpack("<H", optional[0:2])[0]

        # PE32 vs PE32+: Resource table RVA at different offsets
        if magic == 0x10B:  # PE32
            # NumberOfRvaAndSizes at offset 92, then first entry at 96
            num_data_dirs = struct.unpack("<I", optional[92:96])[0]
            # DataDirectory[2] = Resource Table (at offset 112 in PE32)
            if num_data_dirs >= 3:
                resource_rva = struct.unpack("<I", optional[112:116])[0]
                resource_size = struct.unpack("<I", optional[116:120])[0]
            else:
                return ""
        elif magic == 0x20B:  # PE32+
            num_data_dirs = struct.unpack("<I", optional[108:112])[0]
            if num_data_dirs >= 3:
                resource_rva = struct.unpack("<I", optional[128:132])[0]
                resource_size = struct.unpack("<I", optional[132:136])[0]
            else:
                return ""
        else:
            return ""

        if resource_rva == 0 or resource_size == 0:
            return ""

    return ""  # PE 版本解析仅供 fallback，不完整实现


def find_wechat_data_dir(manual_path: str = "") -> DataDirInfo:
    """
    自动定位微信数据目录。

    检测顺序:
        1. 用户手动指定的路径 (settings.yaml wechat.data_dir)
        2. 微信 4.x 默认路径: Documents/xwechat_files/
        3. 微信 3.x 默认路径: Documents/WeChat Files/
        4. 进程工作目录分析

    Returns:
        DataDirInfo — 数据目录信息。
    """
    info = DataDirInfo()

    # Step 1: 手动路径
    if manual_path:
        manual = Path(manual_path)
        if manual.exists():
            info.found = True
            info.path = str(manual)
            info.source = "config"
            logger.info(f"使用手动指定的数据目录: {info.path}")
            return info
        else:
            logger.warning(f"手动指定的数据目录不存在: {manual}")

    # Step 2: 微信 4.x 默认路径
    home = Path.home()
    search_paths = [
        (home / "Documents" / "xwechat_files", "4.x (Documents)"),
        (Path("E:/wechatfiles/xwechat_files"), "4.x (E:)"),
        (Path("C:/wechatfiles/xwechat_files"), "4.x (C:)"),
    ]

    for search_path, label in search_paths:
        result = _scan_wechat_dir(search_path, label)
        if result.found:
            logger.info(f"自动检测到微信数据目录 ({label}): {result.path}")
            return result

    # Step 3: 微信 3.x 默认路径
    wechat_dir = home / "Documents" / "WeChat Files"
    result = _scan_wechat_dir(wechat_dir, "3.x")
    if result.found:
        logger.info(f"自动检测到微信 3.x 数据目录: {result.path}")
        return result

    # Step 4: 未找到
    info.source = "not found"
    info.error = (
        f"未找到微信数据目录。已检查:\n"
        f"  - {home / 'Documents' / 'xwechat_files'}\n"
        f"  - E:/wechatfiles/xwechat_files\n"
        f"  - {wechat_dir}\n"
        f"请在 settings.yaml 中手动指定 wechat.data_dir"
    )
    logger.warning("未找到微信数据目录")
    return info


def _scan_wechat_dir(base: Path, label: str) -> DataDirInfo:
    """扫描微信数据目录，返回第一个包含数据库文件的 wxid 子目录。"""
    info = DataDirInfo()

    if not base.exists():
        return info

    try:
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            # 微信用户目录通常包含 wxid_ 前缀
            # 4.x (新版): xwechat_files/<wxid>/db_storage/contact/contact.db
            # 4.x (旧版): xwechat_files/<wxid>/db/message_0.db
            # 3.x:       WeChat Files/<wxid>/Msg/MSG0.db
            new_db = entry / "db_storage" / "contact" / "contact.db"
            old_db = entry / "db" / "message_0.db"
            msg_path = entry / "Msg" / "MSG0.db"
            if new_db.exists() or old_db.exists() or msg_path.exists():
                info.found = True
                info.path = str(entry)
                info.wxid = entry.name
                info.source = f"auto-detect ({label})"
                return info
    except PermissionError:
        pass

    return info


def scan_db_files(data_dir: str, version_major: int = 4) -> list[DBFileInfo]:
    """
    扫描微信数据目录下的数据库文件。

    Args:
        data_dir: 微信数据目录路径。
        version_major: 微信主版本号 (3 or 4)。

    Returns:
        数据库文件列表 (含大小、存在与否)。
    """
    db_files: list[DBFileInfo] = []

    if not data_dir or not Path(data_dir).exists():
        return db_files

    base = Path(data_dir)

    # 检测实际目录布局（新版 vs 旧版 vs V3）
    if (base / "db_storage" / "message").exists():
        # 新版微信 4.x: db_storage/<type>/<name>.db
        specs = [
            ("message", "message_0.db", "消息数据库 (主)"),
            ("message", "message_1.db", "消息数据库 (分片1)"),
            ("contact", "contact.db", "联系人数据库"),
            ("contact", "session.db", "会话列表"),
            ("message", "media_0.db", "媒体数据库"),
            ("favorite", "favorite.db", "收藏夹"),
            ("general", "general.db", "通用配置"),
            ("message", "message_fts.db", "全文搜索索引"),
            ("contact", "contact_fts.db", "联系人搜索索引"),
        ]
        for subdir, filename, description in specs:
            filepath = base / "db_storage" / subdir / filename
            dbf = DBFileInfo(name=f"{subdir}/{filename}", path=str(filepath),
                             exists=filepath.exists(), note=description)
            if filepath.exists():
                size = filepath.stat().st_size
                dbf.size_bytes = size
                dbf.size_mb = round(size / (1024 * 1024), 2)
                dbf.is_encrypted = True
            db_files.append(dbf)
        return db_files

    if version_major >= 4:
        # 旧版微信 4.x: db/<name>.db
        db_subdir = base / "db"
        specs = [
            ("message_0.db", "消息数据库 (主)"),
            ("message_1.db", "消息数据库 (分片1)"),
            ("contact.db", "联系人数据库"),
            ("session.db", "会话列表"),
            ("media_0.db", "媒体数据库"),
            ("favorite.db", "收藏夹"),
            ("key_info.db", "登录认证"),
            ("message_fts.db", "全文搜索索引"),
            ("contact_fts.db", "联系人搜索索引"),
        ]
    else:
        # 微信 3.x 数据库结构
        db_subdir = base / "Msg"
        specs = [
            ("MSG0.db", "消息数据库 (主)"),
            ("MSG1.db", "消息数据库 (分片1)"),
            ("MSG2.db", "消息数据库 (分片2)"),
            ("MicroMsg.db", "联系人/会话"),
            ("MediaMSG.db", "媒体消息"),
            ("HardLink.db", "文件索引"),
        ]

    for filename, description in specs:
        filepath = db_subdir / filename
        dbf = DBFileInfo(name=filename, path=str(filepath),
                         exists=filepath.exists(), note=description)
        if filepath.exists():
            size = filepath.stat().st_size
            dbf.size_bytes = size
            dbf.size_mb = round(size / (1024 * 1024), 2)
            dbf.is_encrypted = True
        db_files.append(dbf)

    return db_files


def check_permissions() -> PermissionInfo:
    """
    检查当前进程权限。

    - 是否以管理员身份运行？
    - 是否具有调试权限 (SeDebugPrivilege)?

    Returns:
        PermissionInfo — 权限详情。
    """
    info = PermissionInfo()

    # 检查管理员权限
    try:
        info.is_admin = (ctypes.windll.shell32.IsUserAnAdmin() != 0)
    except Exception:
        info.is_admin = False

    if info.is_admin:
        info.can_read_process_memory = True
        logger.info("检测到管理员权限 — 可读取微信进程内存")
    else:
        info.can_read_process_memory = False
        info.error = (
            "当前未以管理员身份运行。\n"
            "后续密钥提取需要管理员权限来读取微信进程内存。\n"
            "请以管理员身份运行终端或配置 Windows 任务计划。"
        )
        logger.warning("未检测到管理员权限")

    return info


def check_dependencies() -> list[DependencyStatus]:
    """
    检查关键 Python 依赖是否已安装。

    Returns:
        DependencyStatus 列表。
    """
    # (display_name, required, import_name)
    # import_name 可能与 pip 包名不同 (e.g. pip: pycryptodome → import: Crypto)
    deps: list[tuple[str, bool, str]] = [
        ("psutil", True, "psutil"),
        ("pymem", True, "pymem"),
        ("pycryptodome", True, "Crypto"),
        ("zstandard", True, "zstandard"),
        ("openai", True, "openai"),
        ("loguru", True, "loguru"),
        ("typer", True, "typer"),
        ("pydantic", True, "pydantic"),
        ("jinja2", True, "jinja2"),
        ("httpx", True, "httpx"),
    ]

    results = []
    for name, required, import_name in deps:
        ds = DependencyStatus(name=name, required=required)
        try:
            mod = __import__(import_name)
            ds.installed = True
            ds.version = getattr(mod, "__version__", "installed")
        except ImportError:
            ds.installed = False
            ds.version = "MISSING"
        results.append(ds)

    return results


# ============================================================
# 诊断编排
# ============================================================


def run_full_diagnostics(
    manual_data_dir: str = "",
) -> DiagnosticReport:
    """
    运行完整的环境诊断。

    纯只读 — 不读取聊天内容，不修改任何文件。

    Args:
        manual_data_dir: 手动指定的微信数据目录路径（来自配置文件）。

    Returns:
        DiagnosticReport — 完整诊断报告。
    """
    logger.info("=" * 60)
    logger.info("Miru Assistant — 微信环境诊断开始")
    logger.info("=" * 60)

    report = DiagnosticReport()
    report.timestamp = datetime.now().isoformat()

    # 1. Windows 环境
    report.hostname, report.windows_version, report.windows_arch = detect_windows()
    report.python_version = (
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )

    # 2. 微信进程
    report.wechat_process = detect_wechat_process()

    # 3. 数据目录
    report.wechat_data_dir = find_wechat_data_dir(manual_data_dir)

    # 4. 数据库文件
    data_path = report.wechat_data_dir.path if report.wechat_data_dir.found else ""
    version_major = report.wechat_process.version_major or 4
    report.db_files = scan_db_files(data_path, version_major)

    # 5. 权限
    report.permissions = check_permissions()

    # 6. 依赖
    report.dependencies = check_dependencies()

    # 7. 综合分析
    _evaluate_report(report)

    logger.info("=" * 60)
    logger.info(f"诊断完成 — ready={report.ready_for_decryption}")
    logger.info("=" * 60)

    return report


def _evaluate_report(report: DiagnosticReport) -> None:
    """
    综合评估诊断结果，生成问题和建议列表。
    """
    issues: list[str] = []
    warnings: list[str] = []
    next_steps: list[str] = []

    # --- 微信进程 ---
    if not report.wechat_process.found:
        issues.append("微信未运行 — 请启动并登录微信 PC 客户端")
        next_steps.append("① 启动微信 PC 客户端并登录")
    elif report.wechat_process.version_major not in (3, 4):
        warnings.append(
            f"微信版本 {report.wechat_process.version_raw or '未知'} 未经测试。"
            f"支持的版本: 3.x / 4.x"
        )

    # --- 数据目录 ---
    if not report.wechat_data_dir.found:
        issues.append("未找到微信数据目录 — 请在 settings.yaml 中手动指定 wechat.data_dir")
        next_steps.append("② 在 config/settings.yaml 中设置 wechat.data_dir")
    else:
        next_steps.append("② 数据目录已定位，无需额外操作")

    # --- 数据库文件 ---
    missing_dbs = [f for f in report.db_files if not f.exists]
    critical_dbs = [f for f in missing_dbs if f.name in (
        "message_0.db", "MSG0.db", "contact.db", "MicroMsg.db",
    )]
    if critical_dbs:
        db_names = ", ".join(f.name for f in critical_dbs)
        issues.append(f"关键数据库文件缺失: {db_names}")
    elif missing_dbs:
        db_names = ", ".join(f.name for f in missing_dbs)
        warnings.append(f"部分数据库文件缺失 (非关键): {db_names}")

    # --- 权限 ---
    if not report.permissions.is_admin:
        issues.append("缺少管理员权限 — 后续密钥提取需要管理员权限")
        next_steps.append("③ 以管理员身份重新运行或配置 Windows 任务计划 (最高权限)")
    else:
        next_steps.append("③ 管理员权限已就绪")

    # --- 依赖 ---
    missing_deps = [d for d in report.dependencies if not d.installed and d.required]
    if missing_deps:
        dep_names = ", ".join(d.name for d in missing_deps)
        issues.append(f"缺少依赖: {dep_names}")
        next_steps.append(f"④ 安装缺失依赖: pip install {' '.join(d.name for d in missing_deps)}")
    else:
        next_steps.append("④ Python 依赖已全部就绪")

    # --- 最终判定 ---
    ready = (
        report.wechat_process.found
        and report.wechat_data_dir.found
        and not critical_dbs
        and report.permissions.is_admin
        and not missing_deps
    )

    report.ready_for_decryption = ready
    report.issues = issues
    report.warnings = warnings
    report.next_steps = next_steps

    if ready:
        next_steps.append("⑤ 所有检查通过！可以开始 Task 5B — 数据库解密。")
    else:
        next_steps.append("⑤ 请先解决以上问题，然后重新运行 miru doctor 确认。")
