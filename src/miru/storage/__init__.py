"""Miru Assistant — 数据持久化层。

提供:
    Database:    SQLite 连接管理
    Models:      数据模型 (dataclass)
    Repository:  数据访问层 (不暴露 SQL)
    Migrations:  Schema 版本迁移
"""

from miru.storage.database import Database, get_db
from miru.storage.migrations import init_database, run_migrations
from miru.storage.models import (
    ChatGroup,
    ConfigStore,
    DailyReport,
    ImportantNotice,
    RawMessage,
    ReportItem,
    RunLog,
    Todo,
)
from miru.storage.repository import (
    ConfigStoreRepository,
    GroupRepository,
    MessageRepository,
    ReportRepository,
    RunLogRepository,
)

__all__ = [
    # Database
    "Database",
    "get_db",
    # Models
    "ChatGroup",
    "ConfigStore",
    "DailyReport",
    "ImportantNotice",
    "RawMessage",
    "ReportItem",
    "RunLog",
    "Todo",
    # Repository
    "GroupRepository",
    "MessageRepository",
    "ReportRepository",
    "RunLogRepository",
    "ConfigStoreRepository",
    # Migrations
    "init_database",
    "run_migrations",
]
