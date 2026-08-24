from pathlib import Path

from miru_server.db.backup import backup_database


def test_backup_database_keeps_daily_snapshot(tmp_path: Path):
    import sqlite3

    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE test (value TEXT)")
        db.execute("INSERT INTO test VALUES ('safe')")
        db.commit()

    target = backup_database(source, tmp_path / "backups", retention_days=30)
    assert target.exists()
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM test").fetchone()[0] == "safe"
