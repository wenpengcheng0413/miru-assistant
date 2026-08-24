"""SQLite 的一致性备份与保留策略。"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path


def backup_database(source: str | Path, destination_dir: str | Path, retention_days: int = 30) -> Path:
    """用 SQLite backup API 生成当天快照；WAL 模式下也不会复制出半截数据库。"""
    source = Path(source)
    destination_dir = Path(destination_dir)
    if not source.exists():
        raise FileNotFoundError(f"数据库不存在: {source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / f"miru-{date.today():%Y-%m-%d}.db"
    if not target.exists():
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)

    cutoff = date.today() - timedelta(days=max(retention_days, 1))
    for old in destination_dir.glob("miru-????-??-??.db"):
        try:
            day = date.fromisoformat(old.stem.removeprefix("miru-"))
        except ValueError:
            continue
        if day < cutoff:
            old.unlink()
    return target
