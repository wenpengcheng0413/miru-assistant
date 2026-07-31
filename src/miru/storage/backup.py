"""
Miru Assistant — SQLite 自动备份 (V1.1 Phase 3)。

每次 Pipeline 成功后自动备份数据库。
保留最近 30 份备份，自动清理旧文件。
"""

import shutil
import time
from pathlib import Path
from typing import Optional

from loguru import logger

MAX_BACKUPS = 30


def backup_database(
    db_path: str = "data/miru.db",
    backup_dir: str = "data/backups",
    max_backups: int = MAX_BACKUPS,
) -> Optional[Path]:
    """
    备份 SQLite 数据库。

    Args:
        db_path: 源数据库路径。
        backup_dir: 备份目录。
        max_backups: 最大保留备份数。

    Returns:
        备份文件路径，失败返回 None。
    """
    src = Path(db_path)
    if not src.exists():
        logger.warning(f"备份跳过 — 数据库不存在: {src}")
        return None

    dst_dir = Path(backup_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dst = dst_dir / f"miru_backup_{timestamp}.db"

    try:
        shutil.copy2(src, dst)
        size_kb = dst.stat().st_size / 1024
        logger.info(f"数据库已备份: {dst.name} ({size_kb:.1f} KB)")
    except Exception as e:
        logger.error(f"数据库备份失败: {e}")
        return None

    # 清理旧备份
    _cleanup_old_backups(dst_dir, max_backups)

    return dst


def _cleanup_old_backups(backup_dir: Path, max_backups: int) -> None:
    """删除超过数量限制的旧备份。"""
    backups = sorted(
        backup_dir.glob("miru_backup_*.db"),
        key=lambda p: p.stat().st_mtime,
    )
    excess = len(backups) - max_backups
    if excess > 0:
        for old in backups[:excess]:
            try:
                old.unlink()
                logger.debug(f"已删除旧备份: {old.name}")
            except Exception as e:
                logger.warning(f"删除旧备份失败: {old.name} — {e}")


def get_backup_count(backup_dir: str = "data/backups") -> int:
    """获取当前备份数量。"""
    p = Path(backup_dir)
    if not p.exists():
        return 0
    return len(list(p.glob("miru_backup_*.db")))
