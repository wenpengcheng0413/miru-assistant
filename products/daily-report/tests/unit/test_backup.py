"""
Miru Assistant — 数据库备份测试 (V1.1 Phase 3)。

测试覆盖:
    - 备份创建
    - 保留数量限制
    - 旧文件清理
    - 数据库不存在时安全跳过
"""

import time
from pathlib import Path

from miru.storage.backup import (
    backup_database,
    get_backup_count,
    _cleanup_old_backups,
)


class TestBackup:
    """备份功能测试。"""

    def test_creates_backup(self, tmp_path):
        """创建数据库备份。"""
        db_path = tmp_path / "miru.db"
        db_path.write_bytes(b"test data" * 100)

        backup_dir = tmp_path / "backups"
        result = backup_database(str(db_path), str(backup_dir))

        assert result is not None
        assert result.exists()
        assert result.name.startswith("miru_backup_")

    def test_missing_db_skips(self, tmp_path):
        """数据库不存在时跳过。"""
        result = backup_database(
            str(tmp_path / "nonexistent.db"),
            str(tmp_path / "backups"),
        )
        assert result is None

    def test_max_backups_limit(self, tmp_path):
        """超过限制时清理旧备份。"""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(parents=True)

        db_path = tmp_path / "miru.db"
        db_path.write_bytes(b"data")

        # 创建 5 个备份
        for i in range(5):
            dst = backup_dir / f"miru_backup_20260101_12000{i}.db"
            dst.write_bytes(b"data")
            time.sleep(0.01)  # 确保 mtime 不同

        # 限制 3 个
        result = backup_database(str(db_path), str(backup_dir), max_backups=3)
        assert result is not None

        count = get_backup_count(str(backup_dir))
        assert count <= 3

    def test_cleanup_empty_dir(self):
        """空目录清理安全。"""
        _cleanup_old_backups(Path("/nonexistent/backups"), 30)
        # 不抛异常 = 通过

    def test_get_backup_count_zero(self, tmp_path):
        """没有备份时返回 0。"""
        empty_dir = tmp_path / "empty_backups"
        # 目录不存在时也应返回 0
        assert get_backup_count(str(empty_dir)) == 0
        # 目录存在但无备份文件时返回 0
        empty_dir.mkdir()
        assert get_backup_count(str(empty_dir)) == 0
