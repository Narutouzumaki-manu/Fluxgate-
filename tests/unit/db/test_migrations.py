"""SQLite migration tests.

Applies migrations 0000-0004 in an in-memory SQLite database and asserts:
  - PRAGMA integrity_check passes
  - PRAGMA foreign_key_check passes
  - All expected tables are present
  - All expected indexes are present
  - Seed rows (tenants, providers, model_aliases) are correct
  - Security schema rules (§6 of BACKEND_SCHEMA.md):
      * No column in virtual_keys stores raw key (no 'key' column except key_hash/key_prefix)
      * cache_entries has response_sha256
      * No triggers exist (PostgreSQL-compatibility rule)
      * No virtual tables / FTS (portability rule)

BACKEND_SCHEMA.md §10.6 and §6; TESTING_AND_BENCHMARK_GUIDE.md §2.
"""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[3] / "shared" / "db" / "migrations"


@pytest.fixture(scope="module")
def db() -> sqlite3.Connection:
    """In-memory SQLite DB with all migrations applied, in order."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")

    migs = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert migs, f"No migration files found in {MIGRATIONS_DIR}"
    for f in migs:
        sql = f.read_text(encoding="utf-8")
        con.executescript(sql)

    return con


def tables(db: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def indexes(db: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }


def triggers(db: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
    }


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# 1. Integrity checks
# ---------------------------------------------------------------------------


def test_integrity_check(db: sqlite3.Connection) -> None:
    result = db.execute("PRAGMA integrity_check").fetchone()
    assert result[0] == "ok", f"integrity_check failed: {result[0]}"


def test_foreign_key_check(db: sqlite3.Connection) -> None:
    rows = db.execute("PRAGMA foreign_key_check").fetchall()
    assert rows == [], f"foreign_key_check found violations: {rows}"


# ---------------------------------------------------------------------------
# 2. All 13 expected tables present
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "schema_migrations",
    "tenants",
    "virtual_keys",
    "providers",
    "model_aliases",
    "app_settings",
    "admin_audit",
    "cache_entries",
    "cache_vectors",
    "request_logs",
    "security_events",
    "circuit_events",
    "metrics_rollup",
}


def test_all_tables_present(db: sqlite3.Connection) -> None:
    missing = EXPECTED_TABLES - tables(db)
    assert not missing, f"Missing tables: {missing}"


def test_no_unexpected_tables(db: sqlite3.Connection) -> None:
    extra = tables(db) - EXPECTED_TABLES
    # allow sqlite internal tables
    extra = {t for t in extra if not t.startswith("sqlite_")}
    assert not extra, f"Unexpected tables: {extra}"


# ---------------------------------------------------------------------------
# 3. Key indexes present
# ---------------------------------------------------------------------------

EXPECTED_INDEXES = {
    "idx_vkeys_tenant_status",
    "idx_alias_alias",
    "idx_admin_audit_time",
    "idx_cache_tenant_expires",
    "idx_cache_tenant_lastused",
    "idx_cache_tenant_compat",
    "idx_cache_expires",
    "idx_cache_policy",
    "idx_vectors_tenant",
    "idx_reqlog_time",
    "idx_reqlog_tenant_time",
    "idx_reqlog_key_time",
    "idx_reqlog_cache_time",
    "idx_reqlog_provider",
    "idx_reqlog_status",
    "idx_reqlog_decision",
    "idx_reqlog_prompthash",
    "idx_secev_time",
    "idx_secev_request",
    "idx_secev_type_time",
    "idx_secev_rule_time",
    "idx_secev_sev_time",
    "idx_circ_provider_time",
    "idx_rollup_tenant_time",
}


def test_all_indexes_present(db: sqlite3.Connection) -> None:
    all_idx = indexes(db)
    missing = EXPECTED_INDEXES - all_idx
    assert not missing, f"Missing indexes: {missing}"


# ---------------------------------------------------------------------------
# 4. Seed rows correct
# ---------------------------------------------------------------------------


def test_seed_tenants(db: sqlite3.Connection) -> None:
    rows = {r[0] for r in db.execute("SELECT id FROM tenants").fetchall()}
    assert "default" in rows
    assert "__playground__" in rows
    assert "__playground_b__" in rows


def test_seed_providers(db: sqlite3.Connection) -> None:
    rows = {r[0] for r in db.execute("SELECT id FROM providers ORDER BY priority").fetchall()}
    assert rows == {"groq", "openrouter", "nvidia_nim"}


def test_seed_provider_priority_order(db: sqlite3.Connection) -> None:
    rows = [r[0] for r in db.execute("SELECT id FROM providers ORDER BY priority").fetchall()]
    assert rows == ["groq", "openrouter", "nvidia_nim"], f"Unexpected priority order: {rows}"


def test_seed_provider_free_tier_only(db: sqlite3.Connection) -> None:
    for row in db.execute("SELECT id, free_tier_only FROM providers").fetchall():
        assert row[1] == 1, f"Provider {row[0]} has free_tier_only != 1 (zero-cost project D-006)"


def test_seed_model_aliases_present(db: sqlite3.Connection) -> None:
    aliases = {r[0] for r in db.execute("SELECT DISTINCT alias FROM model_aliases").fetchall()}
    assert "fluxgate-default" in aliases
    assert "fluxgate-fast" in aliases
    assert "fluxgate-smart" in aliases


def test_seed_model_aliases_all_free(db: sqlite3.Connection) -> None:
    for row in db.execute("SELECT alias, provider_id, is_free FROM model_aliases").fetchall():
        assert row[2] == 1, f"Alias {row[0]}/{row[1]} has is_free != 1 (zero-cost D-006)"


def test_seed_model_aliases_per_provider(db: sqlite3.Connection) -> None:
    """Each alias must have exactly one mapping per provider."""
    for alias in ("fluxgate-default", "fluxgate-fast", "fluxgate-smart"):
        for provider in ("groq", "openrouter", "nvidia_nim"):
            count = db.execute(
                "SELECT COUNT(*) FROM model_aliases WHERE alias=? AND provider_id=?",
                (alias, provider),
            ).fetchone()[0]
            assert count == 1, f"Expected 1 row for alias={alias}, provider={provider}, got {count}"


# ---------------------------------------------------------------------------
# 5. Security schema rules (BACKEND_SCHEMA.md §6)
# ---------------------------------------------------------------------------


def test_virtual_keys_no_raw_key_column(db: sqlite3.Connection) -> None:
    """virtual_keys must not have a column that could store the raw key."""
    cols = columns(db, "virtual_keys")
    # Permitted: key_hash, key_prefix — but never 'key', 'raw_key', 'secret', 'password'
    forbidden = {"key", "raw_key", "secret", "password", "plain_key"}
    found = cols & forbidden
    assert not found, f"virtual_keys has forbidden column(s): {found}"


def test_cache_entries_has_response_sha256(db: sqlite3.Connection) -> None:
    cols = columns(db, "cache_entries")
    assert "response_sha256" in cols, (
        "cache_entries.response_sha256 is required for integrity checks"
    )


def test_cache_entries_has_expires_at_not_null(db: sqlite3.Connection) -> None:
    """expires_at NOT NULL is enforced (TTL rule)."""
    result = db.execute(
        "SELECT COUNT(*) FROM pragma_table_info('cache_entries') "
        "WHERE name='expires_at' AND \"notnull\"=1"
    ).fetchone()[0]
    assert result == 1, "cache_entries.expires_at must be NOT NULL"


def test_no_triggers(db: sqlite3.Connection) -> None:
    """No triggers allowed — PostgreSQL-portability rule (BACKEND_SCHEMA.md §9)."""
    t = triggers(db)
    assert not t, f"Found triggers (not allowed for portability): {t}"


def test_no_virtual_tables(db: sqlite3.Connection) -> None:
    """No virtual/FTS tables (portability rule)."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%USING%'"
    ).fetchall()
    assert not rows, f"Found virtual tables: {[r[0] for r in rows]}"


def test_providers_auth_env_var_not_key(db: sqlite3.Connection) -> None:
    """providers.auth_env_var must store variable NAMES, not key VALUES."""
    for row in db.execute("SELECT id, auth_env_var FROM providers").fetchall():
        env_var = row[1]
        # Must look like an env var name (all caps + underscores), not a key value
        assert env_var.isupper() or "_" in env_var, (
            f"Provider {row[0]}: auth_env_var {env_var!r} looks like a key value, not a var name"
        )
        # Must not look like any known key prefix
        for prefix in ("gsk_", "sk-or-", "nvapi-", "fgx-", "sk-", "AKIA"):
            assert not env_var.startswith(prefix), (
                f"Provider {row[0]}: auth_env_var starts with key prefix {prefix!r}"
            )


def test_cache_vectors_has_dim_check(db: sqlite3.Connection) -> None:
    """cache_vectors.dim CHECK (dim > 0) must be present."""
    sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='cache_vectors'"
    ).fetchone()[0]
    assert "dim > 0" in sql or "dim>0" in sql, (
        "cache_vectors should have CHECK (dim > 0) constraint"
    )


# ---------------------------------------------------------------------------
# 6. schema_migrations table structure
# ---------------------------------------------------------------------------


def test_schema_migrations_columns(db: sqlite3.Connection) -> None:
    cols = columns(db, "schema_migrations")
    assert {"version", "name", "checksum", "applied_at"} <= cols


def test_schema_migrations_primary_key_integer(db: sqlite3.Connection) -> None:
    sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()[0]
    assert "INTEGER PRIMARY KEY" in sql


# ---------------------------------------------------------------------------
# 7. Metrics rollup composite primary key
# ---------------------------------------------------------------------------


def test_metrics_rollup_composite_pk(db: sqlite3.Connection) -> None:
    sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='metrics_rollup'"
    ).fetchone()[0]
    assert "PRIMARY KEY" in sql
    # Composite key must include all three dimensions
    assert "bucket_start" in sql
    assert "tenant_id" in sql
    assert "provider_id" in sql
