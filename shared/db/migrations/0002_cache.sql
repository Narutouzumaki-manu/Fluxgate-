-- Migration 0002 — cache tables: cache_entries and cache_vectors.
-- Owner: Member 1.
-- Applied inside a transaction; foreign keys are ON per-connection pragma.
-- Immutable once merged to main.
--
-- Integrity rule (tested in tests/unit/db/):
--   cache_vectors.tenant_id MUST equal the parent cache_entries.tenant_id.
--   The cache engine asserts this on insert and on rebuild; a mismatch →
--   delete row + admin_audit event.
--
-- When the embedding model/revision changes, vectors with a different
-- model_name are discarded and the per-tenant FAISS index is rebuilt lazily.

-- ---------------------------------------------------------------------------
-- Cache entries (L1 backing store + metadata for L2 eligibility)
-- ---------------------------------------------------------------------------
CREATE TABLE cache_entries (
    id                    TEXT PRIMARY KEY,                         -- ULID
    tenant_id             TEXT    NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cache_scope           TEXT    NOT NULL DEFAULT '',              -- optional client-defined partition (fluxgate.cache_scope)
    exact_key             TEXT    NOT NULL,                         -- sha256 hex (L1)
    compat_hash           TEXT    NOT NULL,                         -- sha256 hex (L2 compat fingerprint)
    policy_version        TEXT    NOT NULL,
    model_requested       TEXT    NOT NULL,
    model_served          TEXT    NOT NULL,
    provider_id           TEXT    REFERENCES providers(id) ON DELETE SET NULL,
    semantic_query        TEXT,                                     -- SANITIZED text that was embedded (<= 1000 chars); NULL if L1-only
    request_sanitized_json TEXT,                                    -- sanitized canonical request (optional; dev default on); never raw
    response_json         TEXT    NOT NULL,                         -- scanned, clean ChatCompletionResponse JSON
    response_sha256       TEXT    NOT NULL,                         -- integrity check on load; mismatch → delete + audit
    response_bytes        INTEGER NOT NULL CHECK (response_bytes >= 0),
    prompt_tokens         INTEGER NOT NULL DEFAULT 0,
    completion_tokens     INTEGER NOT NULL DEFAULT 0,
    usage_estimated       INTEGER NOT NULL DEFAULT 0 CHECK (usage_estimated IN (0,1)),
    finish_reason         TEXT    NOT NULL DEFAULT 'stop',
    l2_eligible           INTEGER NOT NULL DEFAULT 0 CHECK (l2_eligible IN (0,1)),
    risk_score            REAL    NOT NULL DEFAULT 0 CHECK (risk_score >= 0 AND risk_score <= 1),
    streamed              INTEGER NOT NULL DEFAULT 0 CHECK (streamed IN (0,1)),
    created_at            INTEGER NOT NULL,                         -- Unix milliseconds UTC
    expires_at            INTEGER NOT NULL,                         -- TTL; lookup checks expires_at > now regardless of sweeper
    last_hit_at           INTEGER,
    hit_count_l1          INTEGER NOT NULL DEFAULT 0,
    hit_count_l2          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, exact_key)
);
CREATE INDEX idx_cache_tenant_expires  ON cache_entries (tenant_id, expires_at);
CREATE INDEX idx_cache_tenant_lastused ON cache_entries (tenant_id, last_hit_at);
CREATE INDEX idx_cache_tenant_compat   ON cache_entries (tenant_id, compat_hash);
CREATE INDEX idx_cache_expires         ON cache_entries (expires_at);       -- global sweeper
CREATE INDEX idx_cache_policy          ON cache_entries (policy_version);   -- purge stale policy versions

-- ---------------------------------------------------------------------------
-- Cache vectors (float32 embeddings; rebuild FAISS without recomputing)
-- ---------------------------------------------------------------------------
CREATE TABLE cache_vectors (
    vec_id                INTEGER PRIMARY KEY AUTOINCREMENT,        -- int64 id used inside FAISS IndexIDMap2
    entry_id              TEXT    NOT NULL UNIQUE REFERENCES cache_entries(id) ON DELETE CASCADE,
    tenant_id             TEXT    NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,   -- duplicated for tenant-scoped rebuild scans
    dim                   INTEGER NOT NULL CHECK (dim > 0),         -- 384 for all-MiniLM-L6-v2
    model_name            TEXT    NOT NULL,                         -- embedding model + revision (index invalidates on change)
    embedding             BLOB    NOT NULL                          -- float32[dim], L2-normalized, little-endian byte order
);
CREATE INDEX idx_vectors_tenant ON cache_vectors (tenant_id);
