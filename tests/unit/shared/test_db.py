import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from shared.db.connection import open_db
from shared.db.migrator import MIGRATIONS_DIR, discover, migrate
from shared.errors import MigrationError


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await open_db(tmp_path / "data" / "fg.db")
    try:
        yield conn
    finally:
        await conn.close()


async def _scalar(db: aiosqlite.Connection, sql: str) -> object:
    async with db.execute(sql) as cur:
        row = await cur.fetchone()
    assert row is not None
    return row[0]


async def test_pragmas_applied(db: aiosqlite.Connection) -> None:
    assert await _scalar(db, "PRAGMA journal_mode") == "wal"
    assert await _scalar(db, "PRAGMA foreign_keys") == 1
    assert await _scalar(db, "PRAGMA busy_timeout") == 5000


async def test_migrate_applies_all_and_is_idempotent(db: aiosqlite.Connection) -> None:
    expected = [m.version for m in discover()]
    assert expected[:2] == [0, 1]
    assert await migrate(db) == expected
    assert await migrate(db) == []
    assert await _scalar(db, "PRAGMA integrity_check") == "ok"
    for table in ("tenants", "virtual_keys", "cache_entries", "cache_vectors", "request_logs"):
        count = await _scalar(
            db,
            f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'",  # noqa: S608
        )
        assert count == 1, table


async def test_modified_migration_is_detected(db: aiosqlite.Connection, tmp_path: Path) -> None:
    mdir = tmp_path / "migs"
    shutil.copytree(MIGRATIONS_DIR, mdir)
    await migrate(db, mdir)
    target = mdir / "0001_core.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- tampered\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="checksum"):
        await migrate(db, mdir)


async def test_failed_migration_rolls_back(db: aiosqlite.Connection, tmp_path: Path) -> None:
    mdir = tmp_path / "migs"
    mdir.mkdir()
    shutil.copy(MIGRATIONS_DIR / "0000_schema_migrations.sql", mdir)
    (mdir / "0001_bad.sql").write_text(
        "CREATE TABLE a (x INTEGER);\nSELECT FROM broken;", encoding="utf-8"
    )
    with pytest.raises(MigrationError):
        await migrate(db, mdir)
    assert await _scalar(db, "SELECT COUNT(*) FROM schema_migrations") == 1  # only 0000
    assert (
        await _scalar(db, "SELECT COUNT(*) FROM sqlite_master WHERE name='a'") == 0
    )  # rolled back


def test_bad_filename_rejected(tmp_path: Path) -> None:
    (tmp_path / "oops.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError):
        discover(tmp_path)


def test_crlf_does_not_change_checksum(tmp_path: Path) -> None:
    (tmp_path / "0000_a.sql").write_bytes(b"SELECT 1;\nSELECT 2;\n")
    lf = discover(tmp_path)[0].checksum
    (tmp_path / "0000_a.sql").write_bytes(b"SELECT 1;\r\nSELECT 2;\r\n")
    assert discover(tmp_path)[0].checksum == lf
