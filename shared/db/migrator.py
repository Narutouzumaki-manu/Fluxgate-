"""Forward-only numbered SQL migrations (docs/BACKEND_SCHEMA.md §10)."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from shared.errors import MigrationError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    seen: set[int] = set()
    for path in sorted(directory.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if match is None:
            raise MigrationError(f"Bad migration file name: {path.name}")
        version = int(match.group(1))
        if version in seen:
            raise MigrationError(f"Duplicate migration version {version:04d}")
        seen.add(version)
        # Normalize CRLF -> LF so checksums match across Windows/Linux checkouts.
        data = path.read_bytes().replace(b"\r\n", b"\n")
        found.append(
            Migration(
                version=version,
                name=path.stem,
                sql=data.decode("utf-8"),
                checksum=hashlib.sha256(data).hexdigest(),
            )
        )
    return found


async def _applied(db: aiosqlite.Connection) -> dict[int, str]:
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ) as cur:
        if await cur.fetchone() is None:
            return {}
    async with db.execute("SELECT version, checksum FROM schema_migrations") as cur:
        return {int(row[0]): str(row[1]) async for row in cur}


async def migrate(
    db: aiosqlite.Connection,
    directory: Path = MIGRATIONS_DIR,
    *,
    now_ms: int | None = None,
) -> list[int]:
    """Apply pending migrations; return the versions applied. Each file is all-or-nothing."""
    applied = await _applied(db)
    done: list[int] = []
    for mig in discover(directory):
        if mig.version in applied:
            if applied[mig.version] != mig.checksum:
                raise MigrationError(
                    f"Migration {mig.name} was modified after being applied (checksum mismatch)"
                )
            continue
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        try:
            await db.executescript(f"BEGIN EXCLUSIVE;\n{mig.sql}\n;\n")
            await db.execute(
                "INSERT INTO schema_migrations "
                "(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                (mig.version, mig.name, mig.checksum, ts),
            )
            await db.commit()
        except sqlite3.Error as exc:
            with suppress(sqlite3.Error):
                await db.execute("ROLLBACK")
            raise MigrationError(f"Migration {mig.name} failed: {exc}") from exc
        done.append(mig.version)
    return done
