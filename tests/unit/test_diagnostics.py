"""
Miru Assistant — 环境诊断模块单元测试 (Task 5A)。

测试覆盖:
    - Windows 环境检测
    - 微信进程检测 (模拟运行/未运行)
    - 数据目录自动发现
    - 数据库文件扫描
    - 权限检查
    - 依赖检查
    - Report 综合评估逻辑
    - JSON 序列化
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from miru.collector.diagnostics import (
    DBFileInfo,
    DataDirInfo,
    DependencyStatus,
    DiagnosticReport,
    PermissionInfo,
    ProcessInfo,
    _evaluate_report,
    _scan_wechat_dir,
    check_dependencies,
    check_permissions,
    detect_windows,
    scan_db_files,
)


# ============================================================
# Test: Windows Detection
# ============================================================

class TestDetectWindows:
    """测试 Windows 环境检测。"""

    def test_returns_tuple(self):
        """返回 (hostname, version, arch) 三元组。"""
        result = detect_windows()
        assert len(result) == 3
        hostname, version, arch = result
        assert isinstance(hostname, str)
        assert "Windows" in version
        assert arch in ("AMD64", "x86_64", "ARM64")


# ============================================================
# Test: WeChat Process Detection
# ============================================================

class TestDetectWeChatProcess:
    """测试微信进程检测。"""

    def test_wechat_not_running(self):
        """微信未运行时返回 found=False。"""
        with patch("miru.collector.diagnostics.psutil.process_iter") as mock_iter:
            mock_iter.return_value = []  # 无任何进程
            from miru.collector.diagnostics import detect_wechat_process
            result = detect_wechat_process()
            assert result.found is False
            assert "未运行" in result.status

    def test_wechat_running(self):
        """微信运行时返回 found=True + PID + 路径。"""
        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 12345,
            "name": "WeChat.exe",
            "exe": "C:\\Program Files\\Tencent\\WeChat\\WeChat.exe",
        }
        with patch("miru.collector.diagnostics.psutil.process_iter") as mock_iter:
            mock_iter.return_value = [mock_proc]
            # Mock 版本读取
            with patch(
                "miru.collector.diagnostics._get_file_version",
                return_value="4.0.3.29",
            ):
                from miru.collector.diagnostics import detect_wechat_process
                result = detect_wechat_process()
                assert result.found is True
                assert result.pid == 12345
                assert result.version_major == 4
                assert result.version_raw == "4.0.3.29"
                assert "4.x" in result.status

    def test_wechat_v3_detected(self):
        """微信 3.x 版本检测。"""
        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 9999,
            "name": "WeChat.exe",
            "exe": "C:\\WeChat\\WeChat.exe",
        }
        with patch("miru.collector.diagnostics.psutil.process_iter") as mock_iter:
            mock_iter.return_value = [mock_proc]
            with patch(
                "miru.collector.diagnostics._get_file_version",
                return_value="3.9.12.45",
            ):
                from miru.collector.diagnostics import detect_wechat_process
                result = detect_wechat_process()
                assert result.version_major == 3
                assert "3.x" in result.status

    def test_wechat_unknown_version(self):
        """版本读取失败时的处理。"""
        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 5555,
            "name": "WeChat.exe",
            "exe": "C:\\WeChat\\WeChat.exe",
        }
        with patch("miru.collector.diagnostics.psutil.process_iter") as mock_iter:
            mock_iter.return_value = [mock_proc]
            with patch(
                "miru.collector.diagnostics._get_file_version",
                return_value="",
            ):
                from miru.collector.diagnostics import detect_wechat_process
                result = detect_wechat_process()
                assert result.found is True
                assert result.version_major == 0

    def test_multiple_wechat_procs(self):
        """多个 WeChat.exe 进程时取第一个。"""
        proc1 = MagicMock()
        proc1.info = {"pid": 100, "name": "WeChat.exe", "exe": "C:\\WX1\\WeChat.exe"}
        proc2 = MagicMock()
        proc2.info = {"pid": 200, "name": "WeChat.exe", "exe": "C:\\WX2\\WeChat.exe"}
        with patch("miru.collector.diagnostics.psutil.process_iter") as mock_iter:
            mock_iter.return_value = [proc1, proc2]
            with patch(
                "miru.collector.diagnostics._get_file_version",
                return_value="4.0.0.1",
            ):
                from miru.collector.diagnostics import detect_wechat_process
                result = detect_wechat_process()
                assert result.pid == 100  # 第一个


# ============================================================
# Test: Data Directory Scanning
# ============================================================

class TestDataDirScanning:
    """测试数据目录发现。"""

    def test_nonexistent_directory(self):
        """不存在的目录返回 found=False。"""
        result = _scan_wechat_dir(Path("/nonexistent/path/12345"), "test")
        assert result.found is False

    def test_v4_structure_detected(self):
        """检测微信 4.x 目录结构。"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "xwechat_files" / "wxid_abc123"
            db_dir = base / "db"
            db_dir.mkdir(parents=True)
            (db_dir / "message_0.db").touch()

            result = _scan_wechat_dir(Path(tmp) / "xwechat_files", "4.x")
            assert result.found is True
            assert "wxid_abc123" in result.wxid
            assert "4.x" in result.source

    def test_v3_structure_detected(self):
        """检测微信 3.x 目录结构。"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "WeChat Files" / "wxid_xyz789"
            msg_dir = base / "Msg"
            msg_dir.mkdir(parents=True)
            (msg_dir / "MSG0.db").touch()

            result = _scan_wechat_dir(Path(tmp) / "WeChat Files", "3.x")
            assert result.found is True
            assert "wxid_xyz789" in result.wxid
            assert "3.x" in result.source

    def test_empty_directory(self):
        """只有目录但没有数据库文件的跳过。"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "WeChat Files" / "empty_user"
            base.mkdir(parents=True)
            # 没有 Msg 子目录

            result = _scan_wechat_dir(Path(tmp) / "WeChat Files", "3.x")
            assert result.found is False

    def test_finds_first_valid_wxid(self):
        """多个 wxid 时返回第一个包含 DB 的。"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "xwechat_files"
            # 第一个: 无 db
            user1 = base / "wxid_empty"
            user1.mkdir(parents=True)
            # 第二个: 有 db
            user2 = base / "wxid_has_db"
            (user2 / "db").mkdir(parents=True)
            (user2 / "db" / "message_0.db").touch()

            result = _scan_wechat_dir(base, "4.x")
            assert result.found is True
            assert result.wxid == "wxid_has_db"


# ============================================================
# Test: DB File Scanning
# ============================================================

class TestScanDBFiles:
    """测试数据库文件扫描。"""

    def test_v4_scan_creates_correct_list(self):
        """微信 4.x 扫描生成正确的文件列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "wxid_test"
            db_dir = data_dir / "db"
            db_dir.mkdir(parents=True)
            # 创建部分文件
            (db_dir / "message_0.db").write_bytes(b"\x00" * 1024)
            (db_dir / "contact.db").write_bytes(b"\x00" * 500)

            files = scan_db_files(str(data_dir), version_major=4)

            # 应该有 9 个条目（微信 4.x 的文件列表）
            assert len(files) == 9
            # 存在的
            msg0 = next(f for f in files if f.name == "message_0.db")
            assert msg0.exists is True
            assert msg0.size_bytes == 1024
            assert msg0.is_encrypted is True

            contact = next(f for f in files if f.name == "contact.db")
            assert contact.exists is True

            # 不存在的
            fav = next(f for f in files if f.name == "favorite.db")
            assert fav.exists is False

    def test_v3_scan_creates_correct_list(self):
        """微信 3.x 扫描生成正确的文件列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "wxid_old"
            msg_dir = data_dir / "Msg"
            msg_dir.mkdir(parents=True)
            (msg_dir / "MSG0.db").write_bytes(b"\x00" * 2048)

            files = scan_db_files(str(data_dir), version_major=3)

            assert len(files) == 6
            msg0 = next(f for f in files if f.name == "MSG0.db")
            assert msg0.exists is True
            assert msg0.size_bytes == 2048

    def test_empty_data_dir(self, tmp_path):
        """空目录返回带标记的文件列表（均标记为不存在）。"""
        empty = tmp_path / "empty_wx"
        empty.mkdir()
        files = scan_db_files(str(empty), version_major=4)
        assert len(files) > 0
        for f in files:
            assert f.exists is False


# ============================================================
# Test: Permissions
# ============================================================

class TestCheckPermissions:
    """测试权限检查。"""

    def test_returns_permission_info(self):
        """返回 PermissionInfo 对象。"""
        result = check_permissions()
        assert isinstance(result, PermissionInfo)
        assert isinstance(result.is_admin, bool)
        # 权限错误信息在非管理员时有内容
        if not result.is_admin:
            assert len(result.error) > 0


# ============================================================
# Test: Dependencies
# ============================================================

class TestCheckDependencies:
    """测试依赖检查。"""

    def test_returns_list(self):
        """返回 DependencyStatus 列表。"""
        deps = check_dependencies()
        assert len(deps) >= 5
        for d in deps:
            assert isinstance(d, DependencyStatus)
            assert d.name

    def test_critical_deps_present(self):
        """关键依赖已安装。"""
        deps = check_dependencies()
        dep_map = {d.name: d.installed for d in deps}

        # 这些应该在 Task 0 环境中已安装
        assert dep_map.get("psutil") is True
        assert dep_map.get("loguru") is True

    def test_pycryptodome_import_mapped(self):
        """pycryptodome 通过 Crypto 导入名正确检测。"""
        deps = check_dependencies()
        crypto = next(d for d in deps if d.name == "pycryptodome")
        assert crypto.installed is True
        assert crypto.version != "MISSING"


# ============================================================
# Test: Report Evaluation
# ============================================================

class TestEvaluateReport:
    """测试综合评估逻辑。"""

    def test_ready_when_all_good(self):
        """所有条件满足时 ready=True。"""
        report = DiagnosticReport()
        report.wechat_process = ProcessInfo(
            found=True, pid=12345, version_major=4,
            version_raw="4.0.3.29", status="OK",
        )
        report.wechat_data_dir = DataDirInfo(
            found=True, path="/tmp/wx", source="auto-detect",
        )
        report.db_files = [
            DBFileInfo(name="message_0.db", exists=True, size_mb=10.0),
        ]
        report.permissions = PermissionInfo(
            is_admin=True, can_read_process_memory=True,
        )
        report.dependencies = [
            DependencyStatus(name="psutil", installed=True, version="1.0"),
        ]

        _evaluate_report(report)

        assert report.ready_for_decryption is True
        assert len(report.issues) == 0

    def test_not_ready_when_wechat_not_running(self):
        """微信未运行时 ready=False。"""
        report = DiagnosticReport()
        report.wechat_process = ProcessInfo(found=False)
        report.wechat_data_dir = DataDirInfo(found=True, path="/tmp")
        report.db_files = [DBFileInfo(name="message_0.db", exists=True)]
        report.permissions = PermissionInfo(is_admin=True)
        report.dependencies = [DependencyStatus(name="psutil", installed=True)]

        _evaluate_report(report)

        assert report.ready_for_decryption is False
        assert any("未运行" in i for i in report.issues)

    def test_not_ready_when_no_admin(self):
        """没有管理员权限时 ready=False。"""
        report = DiagnosticReport()
        report.wechat_process = ProcessInfo(found=True, version_major=4)
        report.wechat_data_dir = DataDirInfo(found=True, path="/tmp")
        report.db_files = [DBFileInfo(name="message_0.db", exists=True)]
        report.permissions = PermissionInfo(is_admin=False)
        report.dependencies = [DependencyStatus(name="psutil", installed=True)]

        _evaluate_report(report)

        assert report.ready_for_decryption is False
        assert any("管理员" in i for i in report.issues)

    def test_not_ready_when_missing_critical_db(self):
        """关键数据库缺失时 ready=False。"""
        report = DiagnosticReport()
        report.wechat_process = ProcessInfo(found=True, version_major=4)
        report.wechat_data_dir = DataDirInfo(found=True, path="/tmp")
        report.db_files = [
            DBFileInfo(name="message_0.db", exists=False),  # 缺失!
            DBFileInfo(name="contact.db", exists=False),     # 缺失!
        ]
        report.permissions = PermissionInfo(is_admin=True)
        report.dependencies = [DependencyStatus(name="psutil", installed=True)]

        _evaluate_report(report)

        assert report.ready_for_decryption is False
        assert any("缺失" in i or "message_0" in i for i in report.issues)

    def test_warnings_for_non_critical_missing(self):
        """非关键 DB 缺失产生警告但不阻止就绪。"""
        report = DiagnosticReport()
        report.wechat_process = ProcessInfo(found=True, version_major=4)
        report.wechat_data_dir = DataDirInfo(found=True, path="/tmp")
        report.db_files = [
            DBFileInfo(name="message_0.db", exists=True),
            DBFileInfo(name="contact.db", exists=True),
            DBFileInfo(name="favorite.db", exists=False),  # 非关键
        ]
        report.permissions = PermissionInfo(is_admin=True)
        report.dependencies = [DependencyStatus(name="psutil", installed=True)]

        _evaluate_report(report)

        assert report.ready_for_decryption is True
        # 非关键缺失产生 warning
        assert any("favorite" in w for w in report.warnings)


# ============================================================
# Test: Report Serialization
# ============================================================

class TestReportSerialization:
    """测试报告序列化。"""

    def test_to_dict(self):
        """to_dict 返回完整 JSON 兼容的字典。"""
        report = DiagnosticReport()
        report.hostname = "test-pc"
        report.windows_version = "Windows 10"
        report.wechat_process = ProcessInfo(
            found=True, pid=9999, version_major=4,
            version_raw="4.0.0", status="OK",
        )
        report.permissions = PermissionInfo(is_admin=True, can_read_process_memory=True)

        d = report.to_dict()

        assert d["hostname"] == "test-pc"
        assert d["wechat"]["running"] is True
        assert d["wechat"]["pid"] == 9999
        assert d["wechat"]["version_major"] == 4
        assert d["permissions"]["is_admin"] is True
        assert "ready" in d
        assert "issues" in d
        assert "next_steps" in d

    def test_to_dict_with_no_wechat(self):
        """微信未运行时的序列化兼容。"""
        report = DiagnosticReport()
        report.wechat_process = ProcessInfo(found=False)

        d = report.to_dict()

        assert d["wechat"]["running"] is False
        assert d["wechat"]["pid"] is None  # None, not 0


# ============================================================
# Test: Full Diagnostics (Integration)
# ============================================================

class TestFullDiagnostics:
    """测试完整诊断流程。"""

    def test_run_without_wechat(self):
        """微信未运行时诊断仍可正常完成。"""
        with patch("miru.collector.diagnostics.psutil.process_iter") as mock_iter:
            mock_iter.return_value = []
            from miru.collector.diagnostics import run_full_diagnostics
            report = run_full_diagnostics()

            assert isinstance(report, DiagnosticReport)
            assert report.timestamp != ""
            assert report.hostname != ""
            assert "Windows" in report.windows_version
            assert report.wechat_process.found is False
            assert report.ready_for_decryption is False
            # 所有检查都应完成
            assert report.permissions is not None
            assert len(report.dependencies) > 0
