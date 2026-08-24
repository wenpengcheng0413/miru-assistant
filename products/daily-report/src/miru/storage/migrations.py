"""
Miru Assistant — 数据库迁移机制。

设计原则:
    1. 版本号追踪 — db_metadata 表记录当前 schema_version。
    2. 幂等迁移 — 每个迁移脚本可安全重复执行。
    3. 纯 SQL — 迁移以 SQL 字符串定义，不依赖 ORM。
    4. 自动备份 — 迁移前创建数据库备份。

迁移版本:
    V1 (schema_version=1): chat_groups, raw_messages, daily_reports,
                           report_items, run_log, config_store
    V2 (schema_version=2): 添加 todos, important_notices (未来)
"""

import hashlib
import shutil
import time
from pathlib import Path
from typing import Callable

from loguru import logger

from miru.storage.database import Database

# ============================================================
# 迁移定义
# ============================================================

# 每个版本号对应一个迁移函数: (db) → None
# 迁移函数应使用 IF NOT EXISTS 确保幂等性
_MIGRATIONS: dict[int, Callable[[Database], None]] = {}


def migration(version: int):
    """装饰器：注册迁移函数。"""
    def decorator(func: Callable[[Database], None]):
        _MIGRATIONS[version] = func
        return func
    return decorator


@migration(1)
def migrate_v1(db: Database) -> None:
    """V1 初始 schema。"""
    conn = db.conn

    # --- 元数据表 ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS db_metadata (
            key     TEXT PRIMARY KEY,
            value   TEXT
        )
    """)

    # --- chat_groups ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_groups (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name      TEXT NOT NULL,
            wechat_username TEXT NOT NULL UNIQUE,
            is_active       INTEGER NOT NULL DEFAULT 1,
            member_count    INTEGER DEFAULT 0,
            first_seen_at   INTEGER,
            last_seen_at    INTEGER,
            notes           TEXT DEFAULT '',
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_groups_active
        ON chat_groups(is_active)
    """)

    # --- raw_messages ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_svr_id      INTEGER NOT NULL,
            group_id        INTEGER NOT NULL,
            sender_name     TEXT NOT NULL DEFAULT '',
            content_text    TEXT NOT NULL DEFAULT '',
            msg_type        INTEGER NOT NULL DEFAULT 1,
            create_time     INTEGER NOT NULL,
            is_processed    INTEGER NOT NULL DEFAULT 0,
            processed_in    INTEGER,
            collected_at    INTEGER NOT NULL,
            created_at      INTEGER NOT NULL,
            FOREIGN KEY (group_id) REFERENCES chat_groups(id)
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_messages_svr_id
        ON raw_messages(msg_svr_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_messages_group_time
        ON raw_messages(group_id, create_time)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_messages_unprocessed
        ON raw_messages(is_processed, group_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_raw_messages_processed_in
        ON raw_messages(processed_in)
    """)

    # --- daily_reports ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date     TEXT NOT NULL UNIQUE,
            content_md      TEXT NOT NULL,
            stats_json      TEXT NOT NULL DEFAULT '{}',
            groups_covered  TEXT NOT NULL DEFAULT '[]',
            message_count   INTEGER NOT NULL DEFAULT 0,
            generated_at    INTEGER NOT NULL,
            push_status     TEXT NOT NULL DEFAULT 'pending',
            pushed_at       INTEGER,
            push_error      TEXT DEFAULT '',
            created_at      INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_reports_date
        ON daily_reports(report_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_reports_push
        ON daily_reports(push_status)
    """)

    # --- report_items ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS report_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id       INTEGER NOT NULL,
            category        TEXT NOT NULL,
            content         TEXT NOT NULL,
            source_group    TEXT NOT NULL,
            source_sender   TEXT DEFAULT '',
            importance      TEXT NOT NULL DEFAULT 'low',
            deadline        TEXT,
            action_required INTEGER NOT NULL DEFAULT 0,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            created_at      INTEGER NOT NULL,
            FOREIGN KEY (report_id) REFERENCES daily_reports(id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_items_report
        ON report_items(report_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_items_category
        ON report_items(report_id, category)
    """)

    # --- run_log ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            phase           TEXT NOT NULL,
            status          TEXT NOT NULL,
            message         TEXT DEFAULT '',
            duration_ms     INTEGER DEFAULT 0,
            error_traceback TEXT DEFAULT '',
            created_at      INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_run_log_run_id
        ON run_log(run_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_run_log_created
        ON run_log(created_at)
    """)

    # --- config_store ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config_store (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            config_hash     TEXT NOT NULL,
            config_snapshot TEXT NOT NULL,
            created_at      INTEGER NOT NULL
        )
    """)

    # 记录版本
    conn.execute(
        "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
        ("schema_version", "1"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
        ("miru_version", "1.0.0"),
    )

    conn.commit()
    logger.info("数据库迁移 V1 完成 — 6 张核心表已创建")


# ============================================================
# V2 迁移 (DDL 定义，暂未注册)
# ============================================================

V2_DDL = {
    "todos": """
        CREATE TABLE IF NOT EXISTS todos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            content         TEXT NOT NULL,
            source_msg_id   INTEGER,
            source_group    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            priority        TEXT NOT NULL DEFAULT 'medium',
            deadline        TEXT,
            reminder_at     TEXT,
            completed_at    INTEGER,
            notes           TEXT DEFAULT '',
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL,
            FOREIGN KEY (source_msg_id) REFERENCES raw_messages(id)
        )
    """,
    "todos_indexes": [
        "CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status)",
        "CREATE INDEX IF NOT EXISTS idx_todos_deadline ON todos(deadline)",
        "CREATE INDEX IF NOT EXISTS idx_todos_source ON todos(source_group)",
    ],
    "important_notices": """
        CREATE TABLE IF NOT EXISTS important_notices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            content         TEXT NOT NULL,
            source_group    TEXT NOT NULL,
            source_sender   TEXT DEFAULT '',
            notice_date     TEXT NOT NULL,
            tags            TEXT DEFAULT '[]',
            keywords        TEXT DEFAULT '',
            created_at      INTEGER NOT NULL
        )
    """,
}


def _get_migrate_v2(db: Database) -> None:
    """V2 迁移: 添加 todos 和 important_notices 表。"""
    conn = db.conn

    conn.execute(V2_DDL["todos"])
    for idx_sql in V2_DDL["todos_indexes"]:
        conn.execute(idx_sql)

    conn.execute(V2_DDL["important_notices"])

    conn.execute(
        "INSERT OR REPLACE INTO db_metadata (key, value) VALUES (?, ?)",
        ("schema_version", "2"),
    )

    conn.commit()
    logger.info("数据库迁移 V2 完成 — todos + important_notices 已创建")


# ============================================================
# 迁移运行器
# ============================================================

def get_current_version(db: Database) -> int:
    """获取当前数据库 schema 版本。

    Returns:
        schema_version (int): 如果 db_metadata 表不存在则返回 0。
    """
    conn = db.conn
    try:
        row = conn.execute(
            "SELECT value FROM db_metadata WHERE key = 'schema_version'"
        ).fetchone()
        return int(row["value"]) if row else 0
    except Exception:
        return 0


def run_migrations(db: Database, target_version: int | None = None) -> int:
    """
    运行所有待执行的迁移，将数据库升级到目标版本。

    Args:
        db: 数据库实例。
        target_version: 目标版本号。None = 最新版本。

    Returns:
        迁移后的 schema 版本号。

    Raises:
        RuntimeError: 迁移失败。
    """
    if target_version is None:
        target_version = max(_MIGRATIONS.keys()) if _MIGRATIONS else 1

    current = get_current_version(db)
    logger.info(f"当前数据库版本: {current}, 目标版本: {target_version}")

    if current >= target_version:
        logger.info("数据库已是最新版本，无需迁移")
        return current

    # 迁移前备份
    _backup_database(db)

    # 按版本号顺序执行迁移
    for version in sorted(_MIGRATIONS.keys()):
        if version <= current:
            continue
        if version > target_version:
            break

        logger.info(f"执行数据库迁移 V{version}...")
        try:
            _MIGRATIONS[version](db)
        except Exception as e:
            logger.error(f"数据库迁移 V{version} 失败: {e}")
            raise RuntimeError(f"数据库迁移 V{version} 失败: {e}") from e

    new_version = get_current_version(db)
    logger.info(f"数据库迁移完成 — 当前版本: {new_version}")
    return new_version


def _backup_database(db: Database) -> None:
    """创建数据库备份。"""
    db_path = Path(db.db_path)
    if not db_path.exists():
        return

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"miru_backup_{timestamp}.db"

    # 确保所有数据写入磁盘
    db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    shutil.copy2(db_path, backup_path)
    logger.info(f"数据库已备份: {backup_path}")


def init_database(db_path: str = "data/miru.db") -> Database:
    """
    初始化数据库: 创建连接 + 运行迁移。

    这是应用启动时应调用的入口函数。

    Args:
        db_path: 数据库文件路径。

    Returns:
        已初始化并完成迁移的 Database 实例。
    """
    from miru.storage.database import Database as DB

    db = DB(db_path)

    # 强制建立连接
    _ = db.conn

    # 运行迁移
    run_migrations(db)

    return db
