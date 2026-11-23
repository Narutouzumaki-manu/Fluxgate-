"""SQLite connection factory (docs/BACKEND_SCHEMA.md §3). Every connection gets the same PRAGMAs."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

_PRAGMAS = (
    "PRAGMA journal_mode = WAL;"
    "PRAGMA synchronous = NORMAL;"
    "PRAGMA foreign_keys = ON;"
    "PRAGMA busy_timeout = 5000;"
    "PRAGMA wal_autocheckpoint = 1000;"
    "PRAGMA journal_size_limit = 67108864;"
    "PRAGMA temp_store = MEMORY;"
    "PRAGMA cache_size = -20000;"
)


async def open_db(path: str | Path) -> aiosqlite.Connection:
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(target)
    db.row_factory = aiosqlite.Row
    await db.executescript(_PRAGMAS)
    return db
