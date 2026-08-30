"""SQLite 引擎与会话工厂（WAL 模式）。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .migrations import apply_migrations
from .models import Base

engine = None
SessionLocal: sessionmaker[Session] | None = None


def init_db(db_path: str | Path) -> sessionmaker[Session]:
    """初始化数据库（幂等），返回会话工厂。"""
    global engine, SessionLocal
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    # create_all only creates missing tables. Versioned, transactional
    # migrations safely upgrade pre-versioned databases without deleting data.
    with engine.begin() as conn:
        apply_migrations(conn)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return SessionLocal
