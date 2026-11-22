-- Migration 0000 — bootstrap the migrations tracking table.
-- Owner: Member 2 (shared infrastructure).
-- Applied inside a transaction by shared/db/migrator.py on first startup.
-- Immutable once merged to main (fix forward with a new numbered file).
--
-- After this table exists, the migrator records every subsequent migration as:
--   INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (N, 'NNNN_name', sha256hex, now_ms);
-- A checksum mismatch on an already-applied migration aborts startup with a clear error.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version      INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    checksum     TEXT    NOT NULL,            -- sha256 of the .sql file contents
    applied_at   INTEGER NOT NULL             -- Unix milliseconds UTC
);
