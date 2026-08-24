"""
Miru Assistant — SQLite 数据库连接管理。

提供数据库生命周期管理：
- 自动创建数据库文件
- WAL 模式（并发读写性能更高）
- 外键约束
- 连接上下文管理器
"""

import sqlite3
from pathlib import Path
from typing import Optional

from loguru import logger


class Database:
    """SQLite 数据库连接管理器。

    单例模式 — 整个应用共享一个连接。
    """

    def __init__(self, db_path: str = "data/miru.db"):
        """
        Args:
            db_path: SQLite 数据库文件路径（相对于项目根目录或绝对路径）。
        """
        self.db_path = Path(db_path)
        self._connection: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        """获取数据库连接（懒初始化）。"""
        if self._connection is None:
            self._connection = self._connect()
        return self._connection

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接并配置。"""
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            # 5 秒超时，避免微信写入时立即失败
            timeout=5.0,
        )

        # 启用 WAL 模式 — 读写并发性能更好
        conn.execute("PRAGMA journal_mode=WAL;")
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys=ON;")
        # 性能优化
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA cache_size=-8000;")  # 8MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")

        # 返回 dict-like rows
        conn.row_factory = sqlite3.Row

        logger.debug(f"数据库连接已建立: {self.db_path} (WAL mode)")
        return conn

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.debug("数据库连接已关闭")

    def is_connected(self) -> bool:
        """检查数据库是否已连接。"""
        return self._connection is not None

    # --- Context Manager ---

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# 全局数据库实例（应用启动时初始化）
_db_instance: Optional[Database] = None


def get_db(db_path: Optional[str] = None) -> Database:
    """获取全局数据库实例。

    Args:
        db_path: 数据库路径。仅在首次调用时生效。

    Returns:
        Database 实例。
    """
    global _db_instance
    if _db_instance is None:
        if db_path is None:
            db_path = "data/miru.db"
        _db_instance = Database(db_path)
    return _db_instance
