"""Small, transactional SQLite schema-version mechanism for the cloud profile.

The project intentionally stays on SQLite.  Migrations run inside the same
transaction opened by :func:`init_db`; a failing migration therefore rolls
back both its DDL/data changes and the version marker.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text

LATEST_SCHEMA_VERSION = 2
Migration = Callable[[Connection], None]


def _legacy_baseline(conn: Connection) -> None:
    """Bring pre-versioned databases up to the current model columns."""
    attachment_columns = {
        row[1] for row in conn.execute(text("PRAGMA table_info(attachments)"))
    }
    if attachment_columns and "preview_paths" not in attachment_columns:
        conn.execute(
            text("ALTER TABLE attachments ADD COLUMN preview_paths TEXT NOT NULL DEFAULT '[]'")
        )

    message_columns = {
        row[1] for row in conn.execute(text("PRAGMA table_info(messages)"))
    }
    if message_columns and "turn_id" not in message_columns:
        conn.execute(text("ALTER TABLE messages ADD COLUMN turn_id TEXT"))


def _attachment_storage_key(conn: Connection) -> None:
    """Add the cloud-neutral storage key without moving existing files."""
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(attachments)"))}
    if columns and "storage_key" not in columns:
        conn.execute(text("ALTER TABLE attachments ADD COLUMN storage_key TEXT NOT NULL DEFAULT ''"))


MIGRATIONS: dict[int, Migration] = {
    1: _legacy_baseline,
    2: _attachment_storage_key,
}


def schema_version(conn: Connection) -> int:
    return int(conn.execute(text("PRAGMA user_version")).scalar_one())


def apply_migrations(
    conn: Connection,
    *,
    target: int = LATEST_SCHEMA_VERSION,
    migrations: dict[int, Migration] | None = None,
) -> int:
    """Apply missing migrations and return the resulting version.

    The caller owns the transaction.  No migration is allowed to run when
    the database is newer than this binary or when a requested migration is
    missing; either condition fails closed without changing user data.
    """
    if target < 0:
        raise ValueError("target schema version must be non-negative")
    current = schema_version(conn)
    if current > target:
        raise RuntimeError(
            f"database schema version {current} is newer than supported {target}"
        )
    registry = migrations or MIGRATIONS
    if current == target:
        return target

    # pysqlite may implicitly commit DDL when no explicit savepoint exists.
    # A savepoint makes a failed batch rollback both schema changes and the
    # version marker while remaining composable with the caller's transaction.
    savepoint = "miru_migration_batch"
    conn.exec_driver_sql(f"SAVEPOINT {savepoint}")
    try:
        for version in range(current + 1, target + 1):
            migration = registry.get(version)
            if migration is None:
                raise RuntimeError(f"missing migration for schema version {version}")
            migration(conn)
        # SQLite's PRAGMA user_version is not reliably transactional across all
        # supported SQLite builds.  Write it once, after every migration has
        # succeeded, so a failed migration leaves the previous marker intact.
        conn.execute(text(f"PRAGMA user_version = {target}"))
        conn.exec_driver_sql(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        conn.exec_driver_sql(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.exec_driver_sql(f"RELEASE SAVEPOINT {savepoint}")
        raise
    return target
