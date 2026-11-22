# FluxGate — Backend Database Schema & Storage Design

| Field | Value |
|---|---|
| Status | DRAFT v1.0 — **schema freezes with contracts at Gate 1**; afterwards additive migrations only |
| Engine | SQLite ≥ 3.40, **WAL mode** (MVP). DDL is written to be **PostgreSQL-portable** (see §9) |
| Access | `aiosqlite`; migrations by `shared/db/migrator.py` |
| Related | Blueprint §7 (data classification), TRD A7/B9, UI spec §13 |

---

## 1. Storage Placement: SQLite vs FAISS vs Memory

| Data | Where | Why | Lost on restart? |
|---|---|---|---|
| Tenants, virtual keys (HMAC only), providers, model aliases, settings | **SQLite** | Durable config | No |
| Cache entries (response JSON, metadata, TTL) | **SQLite** `cache_entries` | Durable L1 backing, source of truth | No |
| Embedding vectors (float32 BLOB) | **SQLite** `cache_vectors` | Rebuild FAISS without recomputing | No |
| FAISS per-tenant indexes (`IndexIDMap2(IndexFlatIP)`) | **RAM** | Sub-3 ms search | Yes → rebuilt lazily from `cache_vectors` |
| L1 LRU (decoded responses) | **RAM** | Sub-2 ms hit | Yes (cold start refills from SQLite) |
| Request traces, security events, circuit events | **SQLite** | Dashboard, audit | No (retention-limited) |
| Metrics rollups (per-minute counters + latency histogram) | **SQLite** (written in batches) | Fast dashboard queries without scanning logs | No |
| Token buckets (rate limiter), provider outbound limiter | **RAM** | Hot path, monotonic clock | Yes (resets full — documented) |
| Circuit-breaker state, 429 cooldowns | **RAM** (+ `circuit_events` log) | Hot path | Yes → CLOSED |
| Key cache (hash → tenant context) | **RAM** | Auth in < 1 ms | Yes (reloaded) |
| Redaction vault (placeholder ↔ original) | **RAM, request-scoped only** | Must never persist | Always discarded at request end |
| Telemetry queue | **RAM** | Non-blocking enqueue | Yes (drained on graceful shutdown) |
| Provider API keys | **Environment only** | Never in DB | — |

## 2. Conventions

- **IDs:** `TEXT` ULIDs (sortable, portable); exceptions: `vec_id` (int64 surrogate for FAISS) and small enums as `TEXT` with `CHECK`.
- **Timestamps:** `INTEGER` Unix **milliseconds** (UTC). Names end in `_at`/`_ms`. Avoids SQLite/PG datetime divergence.
- **Booleans:** `INTEGER NOT NULL DEFAULT 0 CHECK (x IN (0,1))`.
- **JSON:** stored as `TEXT` in columns named `*_json`; validated in the application (no `json_valid` in DDL for portability). Never store bodies/PII in JSON columns.
- **Hashes:** lowercase hex `TEXT` (SHA-256 = 64 chars, HMAC-SHA256 = 64 chars).
- **Foreign keys** are enforced (`PRAGMA foreign_keys=ON` per connection).
- **Tenancy:** every row that could hold tenant-attributable data carries `tenant_id`.

## 3. Connection PRAGMAs (applied on every connection)

```sql
PRAGMA journal_mode = WAL;          -- persistent once set
PRAGMA synchronous = NORMAL;        -- safe with WAL; fsync at checkpoints
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA journal_size_limit = 67108864;   -- 64 MB cap on WAL file growth
PRAGMA temp_store = MEMORY;
PRAGMA cache_size = -20000;         -- ~20 MB page cache
```
Run `PRAGMA optimize;` on graceful shutdown. DB file permissions `0600`; directory `0700`.

## 4. DDL — Migration Files

Migrations live in `shared/db/migrations/`, forward-only, applied in order inside a transaction, checksummed. **Ownership:** `0000`/`0001`/`0003`/`0004` Member 2; `0002` Member 1. All are authored in Phase 1 scaffolding (so Member 1 can run cache tables standalone) and frozen at Gate 1.

### 4.1 `0000_schema_migrations.sql`

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version      INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    checksum     TEXT    NOT NULL,            -- sha256 of the .sql file
    applied_at   INTEGER NOT NULL
);
```

### 4.2 `0001_core.sql` — tenants, keys, providers, aliases, settings, admin audit

```sql
CREATE TABLE tenants (
    id                    TEXT PRIMARY KEY,                         -- ULID or reserved: 'default', '__playground__', '__playground_b__'
    name                  TEXT    NOT NULL UNIQUE,
    status                TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
    guardrail_policy      TEXT    NOT NULL DEFAULT 'default',
    cache_enabled         INTEGER NOT NULL DEFAULT 1 CHECK (cache_enabled IN (0,1)),
    cache_default_ttl_s   INTEGER NOT NULL DEFAULT 86400 CHECK (cache_default_ttl_s > 0),
    cache_max_entries     INTEGER NOT NULL DEFAULT 50000 CHECK (cache_max_entries > 0),
    l2_threshold          REAL    CHECK (l2_threshold IS NULL OR (l2_threshold > 0 AND l2_threshold <= 1)),  -- NULL = global default
    settings_json         TEXT    NOT NULL DEFAULT '{}',
    created_at            INTEGER NOT NULL,
    updated_at            INTEGER NOT NULL
);

CREATE TABLE virtual_keys (
    id                    TEXT PRIMARY KEY,                         -- ULID
    tenant_id             TEXT    NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    name                  TEXT    NOT NULL,
    key_prefix            TEXT    NOT NULL UNIQUE,                  -- 'fgx-' + first 8 chars; display only
    key_hash              TEXT    NOT NULL UNIQUE,                  -- hex HMAC-SHA256(pepper, raw_key). RAW KEY NEVER STORED
    status                TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked','expired')),
    rpm_limit             INTEGER NOT NULL DEFAULT 60  CHECK (rpm_limit > 0),
    burst                 INTEGER NOT NULL DEFAULT 10  CHECK (burst > 0),
    daily_request_cap     INTEGER CHECK (daily_request_cap IS NULL OR daily_request_cap > 0),   -- counts provider-bound requests only
    allowed_models_json   TEXT,                                     -- NULL = all permitted aliases
    guardrail_policy      TEXT,                                     -- NULL = inherit tenant
    cache_enabled         INTEGER CHECK (cache_enabled IS NULL OR cache_enabled IN (0,1)),      -- NULL = inherit tenant
    created_at            INTEGER NOT NULL,
    created_by            TEXT    NOT NULL DEFAULT 'admin',
    expires_at            INTEGER,
    last_used_at          INTEGER,
    revoked_at            INTEGER,
    revoked_reason        TEXT,
    rotated_from_key_id   TEXT REFERENCES virtual_keys(id) ON DELETE SET NULL,
    revoke_grace_until    INTEGER                                   -- for rotation grace period
);
CREATE INDEX idx_vkeys_tenant_status ON virtual_keys (tenant_id, status);

CREATE TABLE providers (
    id                    TEXT PRIMARY KEY CHECK (id IN ('groq','openrouter','nvidia_nim')),
    display_name          TEXT    NOT NULL,
    base_url              TEXT    NOT NULL,
    auth_env_var          TEXT    NOT NULL,                         -- NAME of env var, never the key
    enabled               INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    disabled_reason       TEXT,                                     -- 'manual' | 'auth_error' | NULL
    priority              INTEGER NOT NULL DEFAULT 100,             -- lower = preferred
    free_tier_only        INTEGER NOT NULL DEFAULT 1 CHECK (free_tier_only IN (0,1)),
    rpm_cap               INTEGER,                                  -- outbound limiter (set below real limit)
    rpd_cap               INTEGER,
    connect_timeout_s     REAL    NOT NULL DEFAULT 5,
    read_timeout_s        REAL    NOT NULL DEFAULT 60,
    cb_failure_threshold  INTEGER NOT NULL DEFAULT 5,
    cb_recovery_s         INTEGER NOT NULL DEFAULT 30,
    cb_half_open_probes   INTEGER NOT NULL DEFAULT 1,
    extra_headers_json    TEXT    NOT NULL DEFAULT '{}',            -- e.g., OpenRouter attribution; no secrets
    updated_at            INTEGER NOT NULL
);

CREATE TABLE model_aliases (
    id                    TEXT PRIMARY KEY,                         -- ULID
    alias                 TEXT    NOT NULL,                         -- e.g., 'fluxgate-default'
    provider_id           TEXT    NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    model_id              TEXT    NOT NULL,                         -- provider's concrete model id
    is_free               INTEGER NOT NULL DEFAULT 0 CHECK (is_free IN (0,1)),   -- zero-cost mode filter
    enabled               INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    reference_price_in    REAL,                                     -- USD per 1M input tokens (equivalent paid price, estimate)
    reference_price_out   REAL,
    UNIQUE (alias, provider_id)
);
CREATE INDEX idx_alias_alias ON model_aliases (alias);

CREATE TABLE app_settings (
    key                   TEXT PRIMARY KEY,                         -- e.g., 'retention.request_logs_days', 'privacy.store_prompt_preview'
    value                 TEXT    NOT NULL,
    updated_at            INTEGER NOT NULL
);

CREATE TABLE admin_audit (
    id                    TEXT PRIMARY KEY,                         -- ULID
    created_at            INTEGER NOT NULL,
    actor                 TEXT    NOT NULL DEFAULT 'admin',
    action                TEXT    NOT NULL,                         -- 'key.create','key.revoke','cache.purge','provider.disable',...
    target_type           TEXT,
    target_id             TEXT,
    details_json          TEXT    NOT NULL DEFAULT '{}'             -- never secrets / raw keys
);
CREATE INDEX idx_admin_audit_time ON admin_audit (created_at DESC);

INSERT INTO tenants (id, name, created_at, updated_at) VALUES
  ('default', 'default', 0, 0),
  ('__playground__', '__playground__', 0, 0),
  ('__playground_b__', '__playground_b__', 0, 0);
```

### 4.3 `0002_cache.sql` — **Member 1**

```sql
CREATE TABLE cache_entries (
    id                    TEXT PRIMARY KEY,                         -- ULID
    tenant_id             TEXT    NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    cache_scope           TEXT    NOT NULL DEFAULT '',              -- optional client-defined partition
    exact_key             TEXT    NOT NULL,                         -- sha256 hex (L1)
    compat_hash           TEXT    NOT NULL,                         -- sha256 hex (L2 compat fingerprint)
    policy_version        TEXT    NOT NULL,
    model_requested       TEXT    NOT NULL,
    model_served          TEXT    NOT NULL,
    provider_id           TEXT    REFERENCES providers(id) ON DELETE SET NULL,
    semantic_query        TEXT,                                     -- SANITIZED text that was embedded (<= 1000 chars); NULL if L1-only
    request_sanitized_json TEXT,                                    -- sanitized canonical request (optional; dev default on); never raw
    response_json         TEXT    NOT NULL,                         -- scanned, clean ChatCompletionResponse
    response_sha256       TEXT    NOT NULL,                         -- integrity check on load
    response_bytes        INTEGER NOT NULL CHECK (response_bytes >= 0),
    prompt_tokens         INTEGER NOT NULL DEFAULT 0,
    completion_tokens     INTEGER NOT NULL DEFAULT 0,
    usage_estimated       INTEGER NOT NULL DEFAULT 0 CHECK (usage_estimated IN (0,1)),
    finish_reason         TEXT    NOT NULL DEFAULT 'stop',
    l2_eligible           INTEGER NOT NULL DEFAULT 0 CHECK (l2_eligible IN (0,1)),
    risk_score            REAL    NOT NULL DEFAULT 0 CHECK (risk_score >= 0 AND risk_score <= 1),
    streamed              INTEGER NOT NULL DEFAULT 0 CHECK (streamed IN (0,1)),
    created_at            INTEGER NOT NULL,
    expires_at            INTEGER NOT NULL,                         -- TTL
    last_hit_at           INTEGER,
    hit_count_l1          INTEGER NOT NULL DEFAULT 0,
    hit_count_l2          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (tenant_id, exact_key)
);
CREATE INDEX idx_cache_tenant_expires ON cache_entries (tenant_id, expires_at);
CREATE INDEX idx_cache_tenant_lastused ON cache_entries (tenant_id, last_hit_at);
CREATE INDEX idx_cache_tenant_compat ON cache_entries (tenant_id, compat_hash);
CREATE INDEX idx_cache_expires ON cache_entries (expires_at);       -- global sweeper
CREATE INDEX idx_cache_policy ON cache_entries (policy_version);    -- purge stale policy versions

CREATE TABLE cache_vectors (
    vec_id                INTEGER PRIMARY KEY AUTOINCREMENT,        -- int64 id used inside FAISS IndexIDMap2
    entry_id              TEXT    NOT NULL UNIQUE REFERENCES cache_entries(id) ON DELETE CASCADE,
    tenant_id             TEXT    NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,   -- duplicated for tenant-scoped rebuild scans
    dim                   INTEGER NOT NULL CHECK (dim > 0),         -- 384 for MiniLM-L6-v2
    model_name            TEXT    NOT NULL,                         -- embedding model + revision (index invalidates on change)
    embedding             BLOB    NOT NULL                          -- float32[dim], L2-normalized, little-endian
);
CREATE INDEX idx_vectors_tenant ON cache_vectors (tenant_id);
```
*Integrity rule (tested):* `cache_vectors.tenant_id` must equal its entry's `tenant_id`; the cache engine asserts this on insert and on rebuild (mismatch → delete row + audit event). When the embedding model/revision changes, vectors with a different `model_name` are discarded and L2 is rebuilt lazily.

### 4.4 `0003_telemetry.sql` — traces, security events, circuit events, rollups

```sql
CREATE TABLE request_logs (
    request_id            TEXT PRIMARY KEY,                         -- 'req_' + ULID
    tenant_id             TEXT    NOT NULL,                         -- no FK: logs outlive deleted tenants/keys
    key_id                TEXT    NOT NULL,
    created_at            INTEGER NOT NULL,
    model_requested       TEXT    NOT NULL,
    model_served          TEXT,
    provider_id           TEXT,
    served_from           TEXT    NOT NULL CHECK (served_from IN ('l1','l2','provider','error')),
    streamed              INTEGER NOT NULL DEFAULT 0 CHECK (streamed IN (0,1)),
    status_code           INTEGER NOT NULL,
    error_code            TEXT,                                     -- 'fluxgate_policy_block', ...
    client_disconnected   INTEGER NOT NULL DEFAULT 0 CHECK (client_disconnected IN (0,1)),
    -- cache
    cache_outcome         TEXT    NOT NULL CHECK (cache_outcome IN ('hit_l1','hit_l2','miss','bypass')),
    cache_entry_id        TEXT,                                     -- soft reference (entry may expire)
    similarity            REAL,
    near_miss_similarity  REAL,
    bypass_reason         TEXT,
    compat_mismatch       TEXT,
    store_stored          INTEGER CHECK (store_stored IS NULL OR store_stored IN (0,1)),
    -- security (aggregates only; details in security_events)
    guardrail_decision    TEXT    CHECK (guardrail_decision IS NULL OR guardrail_decision IN ('allow','warn','block')),
    risk_score            REAL,
    policy_name           TEXT,
    policy_version        TEXT,
    degraded              INTEGER NOT NULL DEFAULT 0 CHECK (degraded IN (0,1)),
    finding_summary_json  TEXT    NOT NULL DEFAULT '{}',            -- {"pii_email":1,"secret_api_key":1}
    redaction_count       INTEGER NOT NULL DEFAULT 0,
    -- tokens & savings
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    usage_estimated       INTEGER NOT NULL DEFAULT 0 CHECK (usage_estimated IN (0,1)),
    tokens_saved          INTEGER NOT NULL DEFAULT 0,
    cost_saved_usd_est    REAL    NOT NULL DEFAULT 0,
    -- timings (ms)
    t_total_ms            REAL    NOT NULL,
    t_auth_ms             REAL,
    t_ratelimit_ms        REAL,
    t_parse_ms            REAL,
    t_l1_ms               REAL,
    t_guardrails_in_ms    REAL,
    t_l2_ms               REAL,
    t_router_overhead_ms  REAL,
    t_upstream_ms         REAL,
    t_ttft_ms             REAL,
    t_guardrails_out_ms   REAL,
    -- routing
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    attempts_json         TEXT    NOT NULL DEFAULT '[]',            -- [{provider,model,status,failure,latency_ms,circuit}]
    failed_over           INTEGER NOT NULL DEFAULT 0 CHECK (failed_over IN (0,1)),
    -- content-safe identifiers
    prompt_sha256         TEXT    NOT NULL,                         -- hash of RAW canonical prompt (irreversible); correlates repeats
    prompt_chars          INTEGER NOT NULL DEFAULT 0,
    sanitized_preview     TEXT,                                     -- <= 80 chars of SANITIZED text; NULL when disabled
    client_ip_hash        TEXT                                      -- salted hash, never raw IP
);
CREATE INDEX idx_reqlog_time        ON request_logs (created_at DESC);
CREATE INDEX idx_reqlog_tenant_time ON request_logs (tenant_id, created_at DESC);
CREATE INDEX idx_reqlog_key_time    ON request_logs (key_id, created_at DESC);
CREATE INDEX idx_reqlog_cache_time  ON request_logs (cache_outcome, created_at DESC);
CREATE INDEX idx_reqlog_provider    ON request_logs (provider_id, created_at DESC);
CREATE INDEX idx_reqlog_status      ON request_logs (status_code, created_at DESC);
CREATE INDEX idx_reqlog_decision    ON request_logs (guardrail_decision, created_at DESC) WHERE guardrail_decision IN ('warn','block');
CREATE INDEX idx_reqlog_prompthash  ON request_logs (prompt_sha256);

CREATE TABLE security_events (
    id                    TEXT PRIMARY KEY,                         -- ULID
    request_id            TEXT    NOT NULL REFERENCES request_logs(request_id) ON DELETE CASCADE,
    tenant_id             TEXT    NOT NULL,
    key_id                TEXT    NOT NULL,
    created_at            INTEGER NOT NULL,
    stage                 TEXT    NOT NULL CHECK (stage IN ('inbound','response','stream')),
    decision              TEXT    NOT NULL CHECK (decision IN ('allow','warn','block')),
    finding_type          TEXT    NOT NULL,                         -- FindingType enum value
    rule_id               TEXT    NOT NULL,
    severity              TEXT    NOT NULL CHECK (severity IN ('info','low','medium','high','critical')),
    confidence            REAL    NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    source                TEXT    NOT NULL,                         -- ContentSource
    message_index         INTEGER,
    chunk_id              TEXT,
    span_start            INTEGER,
    span_end              INTEGER,
    masked_preview        TEXT,                                     -- masked, <= 64 chars; never raw
    policy_name           TEXT    NOT NULL,
    policy_version        TEXT    NOT NULL
);
CREATE INDEX idx_secev_time      ON security_events (created_at DESC);
CREATE INDEX idx_secev_request   ON security_events (request_id);
CREATE INDEX idx_secev_type_time ON security_events (finding_type, created_at DESC);
CREATE INDEX idx_secev_rule_time ON security_events (rule_id, created_at DESC);
CREATE INDEX idx_secev_sev_time  ON security_events (severity, created_at DESC);

CREATE TABLE circuit_events (
    id                    TEXT PRIMARY KEY,
    provider_id           TEXT    NOT NULL,
    created_at            INTEGER NOT NULL,
    from_state            TEXT    NOT NULL CHECK (from_state IN ('closed','open','half_open')),
    to_state              TEXT    NOT NULL CHECK (to_state IN ('closed','open','half_open')),
    reason                TEXT    NOT NULL,                         -- 'threshold','error_rate','probe_success','probe_failure','manual_reset','manual_disable'
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    cooldown_until        INTEGER,
    request_id            TEXT
);
CREATE INDEX idx_circ_provider_time ON circuit_events (provider_id, created_at DESC);

CREATE TABLE metrics_rollup (
    bucket_start          INTEGER NOT NULL,                         -- minute start, Unix ms
    tenant_id             TEXT    NOT NULL,
    provider_id           TEXT    NOT NULL DEFAULT '',              -- '' = not provider-specific (cache/guardrail rows)
    requests              INTEGER NOT NULL DEFAULT 0,
    hits_l1               INTEGER NOT NULL DEFAULT 0,
    hits_l2               INTEGER NOT NULL DEFAULT 0,
    misses                INTEGER NOT NULL DEFAULT 0,
    bypasses              INTEGER NOT NULL DEFAULT 0,
    errors                INTEGER NOT NULL DEFAULT 0,
    blocks                INTEGER NOT NULL DEFAULT 0,
    warns                 INTEGER NOT NULL DEFAULT 0,
    redactions            INTEGER NOT NULL DEFAULT 0,
    failovers             INTEGER NOT NULL DEFAULT 0,
    prompt_tokens         INTEGER NOT NULL DEFAULT 0,
    completion_tokens     INTEGER NOT NULL DEFAULT 0,
    tokens_saved          INTEGER NOT NULL DEFAULT 0,
    cost_saved_usd_est    REAL    NOT NULL DEFAULT 0,
    provider_calls        INTEGER NOT NULL DEFAULT 0,
    lat_total_hist_json   TEXT    NOT NULL DEFAULT '[]',            -- counts per fixed bucket [5,10,20,50,100,200,500,1000,2000,5000,+inf] ms
    lat_overhead_hist_json TEXT   NOT NULL DEFAULT '[]',
    lat_upstream_hist_json TEXT   NOT NULL DEFAULT '[]',
    lat_l2_hist_json      TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (bucket_start, tenant_id, provider_id)
);
CREATE INDEX idx_rollup_tenant_time ON metrics_rollup (tenant_id, bucket_start DESC);
```

### 4.5 `0004_seed_config.sql` (Member 2) — optional seed for providers/aliases
Inserts the three `providers` rows (`auth_env_var` names only) and example `model_aliases` rows with `is_free` flags **after the team verifies current model IDs** on setup day (Tools doc §5). Contains no secrets.

## 5. Entity Relationships

```
tenants 1───* virtual_keys
tenants 1───* cache_entries 1───1 cache_vectors
providers 1───* model_aliases
providers 1───* cache_entries (SET NULL)
request_logs 1───* security_events          (CASCADE)
request_logs ···· cache_entries              (soft reference by entry id; no FK)
circuit_events ···· providers                (by id; no FK to survive provider row edits)
metrics_rollup ···· tenants/providers        (by id; no FK, retention-managed)
```
Logs deliberately avoid FKs to tenants/keys so purging a tenant/key never destroys audit history; `ON DELETE CASCADE` is used only where child rows are meaningless without the parent (`cache_vectors`, `security_events`, `model_aliases`).

## 6. Security Requirements for the Schema

| Rule | Enforcement |
|---|---|
| Raw virtual API keys never stored | Only `key_hash` + `key_prefix`; test scans the DB file for any `fgx-` string longer than prefix length |
| Provider keys never in DB | `providers.auth_env_var` holds the variable **name**; test scans for provider-key patterns |
| No raw prompts/responses outside `cache_entries` | `request_logs` has hash, length, optional ≤ 80-char **sanitized** preview only |
| No raw PII/secrets | `security_events.masked_preview` is masked; canary test inserts canaries through the full pipeline and greps the DB + WAL |
| Cached responses are clean | Only written via `maybe_store` after eligibility + scan; `response_sha256` verified on load |
| Tenant isolation | `tenant_id` NOT NULL on cache tables; unique key includes tenant; vector rows carry tenant; engine verifies equality on read |
| Hashing | HMAC-SHA256 with `FLUXGATE_KEY_PEPPER`; changing the pepper invalidates all keys (documented; rotation = re-issue keys) |
| File protection | DB file `0600`; `data/` git-ignored; WAL/SHM included in ignore rules |
| TTL | `cache_entries.expires_at NOT NULL`; lookup checks `expires_at > now` regardless of sweeper |

## 7. Retention and Maintenance

| Data | Default retention | Mechanism |
|---|---|---|
| `request_logs` (clean rows: no findings) | 14 days | hourly batched `DELETE … WHERE created_at < ? AND finding_summary_json = '{}' LIMIT 5000` |
| `request_logs` with findings + their `security_events` | 30 days | same job with the 30-day cutoff; `security_events` rows go via `ON DELETE CASCADE`, so audit events live exactly as long as their request row |
| `circuit_events` | 30 days | hourly purge |
| `metrics_rollup` | 90 days | daily purge |
| `cache_entries` | TTL (default 24 h, max 7 d) | sweeper every 60 s |
| `admin_audit` | 365 days | monthly purge |
| WAL | checkpoint `TRUNCATE` weekly + on shutdown | maintenance task |
| `VACUUM` | manual (`make db-vacuum`) when file > 2× expected | not automatic |

Size estimate (engineering estimate, verify): ~1 KB per `request_logs` row → 100k requests ≈ 100 MB; cache entry ≈ response size + 1.5 KB vector; 50k entries × ~3 KB ≈ 150 MB. Keep the whole DB comfortably under 1 GB on a student laptop; the retention values above are tunable in Settings.

## 8. Representative Queries (Dashboard)

```sql
-- Overall hit rate in range (Overview KPI)
SELECT SUM(hits_l1) AS l1, SUM(hits_l2) AS l2, SUM(requests) AS n,
       1.0 * (SUM(hits_l1)+SUM(hits_l2)) / NULLIF(SUM(requests),0) AS hit_rate
FROM metrics_rollup
WHERE bucket_start >= :from AND bucket_start < :to AND (:tenant IS NULL OR tenant_id = :tenant);

-- Tokens saved + estimated equivalent cost
SELECT SUM(tokens_saved), SUM(cost_saved_usd_est) FROM metrics_rollup WHERE bucket_start >= :from AND (:tenant IS NULL OR tenant_id = :tenant);

-- Trace list with keyset pagination (newest first)
SELECT * FROM request_logs
WHERE tenant_id = :tenant AND (created_at, request_id) < (:cursor_ts, :cursor_id)   -- row-value comparison; PG-compatible
ORDER BY created_at DESC, request_id DESC LIMIT 50;

-- Blocked/warned requests
SELECT request_id, created_at, risk_score FROM request_logs
WHERE guardrail_decision IN ('warn','block') AND created_at >= :from ORDER BY created_at DESC LIMIT 100;

-- Top triggered rules
SELECT rule_id, finding_type, COUNT(*) c FROM security_events WHERE created_at >= :from GROUP BY rule_id, finding_type ORDER BY c DESC LIMIT 10;

-- Cache sweeper candidates
SELECT id, tenant_id, vec_id FROM cache_entries e JOIN cache_vectors v ON v.entry_id = e.id WHERE e.expires_at <= :now LIMIT 500;

-- Rebuild FAISS for a tenant
SELECT vec_id, embedding FROM cache_vectors WHERE tenant_id = :tenant AND model_name = :model;

-- Provider daily usage (free-tier meter)
SELECT SUM(provider_calls) FROM metrics_rollup WHERE provider_id = :p AND bucket_start >= :start_of_day_utc;
```
Percentiles (p50/p95) from `lat_*_hist_json` are computed in Python by cumulative-count interpolation (approximate, labelled "approx." in UI).

## 9. PostgreSQL Compatibility Notes (Design-Time; no PG runtime in MVP)

| SQLite construct | PostgreSQL equivalent | Notes |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` (`vec_id`) | `BIGINT GENERATED ALWAYS AS IDENTITY` | only table using it |
| `INTEGER` 0/1 booleans + `CHECK` | `BOOLEAN` | migrate with `x::boolean`; app layer already treats as bool |
| `TEXT` `*_json` | `JSONB` | add GIN indexes only if needed |
| `BLOB` | `BYTEA` | |
| `INTEGER` ms timestamps | `BIGINT` | keep ms ints; avoids timezone issues |
| `REAL` | `DOUBLE PRECISION` | |
| Partial index (`WHERE …`) | same syntax | supported |
| Row-value comparison `(a,b) < (x,y)` | same | supported |
| `INSERT … ON CONFLICT … DO UPDATE` | same | use this instead of `INSERT OR REPLACE` everywhere |
| PRAGMAs | server config | n/a |
| `CHECK (id IN (...))` | same | |
Rules to keep portability: no `rowid` usage, no `WITHOUT ROWID`, no SQLite-specific functions in application SQL (`json_extract`, `strftime` banned in queries — use Python), no triggers, no virtual tables/FTS. A `postgres/` migrations folder (P1) will mirror each file with the type mappings above. FAISS stays in-process regardless of DB engine (pgvector is a possible P1 swap).

## 10. Migration Strategy

1. **Files:** `shared/db/migrations/NNNN_name.sql`, strictly increasing, immutable once merged to `main` (fix forward with a new file).
2. **Runner:** at startup (`FLUXGATE_AUTO_MIGRATE=true`, default in dev) acquires an `EXCLUSIVE` transaction, applies pending files in order, records `(version, name, checksum, applied_at)`. A checksum mismatch on an already-applied file aborts startup with a clear error.
3. **Ownership & stages:** all DDL above is authored in Phase 1 scaffolding and frozen at Gate 1, so Member 1 can run `0000–0003` standalone (CLI uses `ensure_tenant()` helper) and Member 2 inherits identical tables. Post-Gate-1 schema changes are **additive** (new nullable column, new table, new index) via a new migration in a PR labelled `contract-change` (schema is part of the contract surface).
4. **Destructive changes** (drop/rename column) use expand → migrate → contract across two releases; SQLite table rebuild pattern (`CREATE new; INSERT SELECT; DROP old; RENAME`) inside the migration transaction with `PRAGMA foreign_keys=OFF/ON`.
5. **Backups:** `sqlite3 data/fluxgate.db ".backup data/backup-YYYYMMDD.db"` (online-safe in WAL); optional `make db-backup`. Cache data is reproducible, so backups matter mainly for keys/config.
6. **Tests:** `tests/unit/db/` applies all migrations to an empty DB, asserts `PRAGMA integrity_check`, foreign-key check, expected indexes (`PRAGMA index_list`), and the security scans in §6.
7. **Embedding model change:** bump `cache_vectors.model_name`; on mismatch the cache engine ignores old vectors and schedules re-embedding or purge (config `on_embedding_model_change: purge|reembed`, default `purge`).

## 11. Schema ↔ Contract Mapping

| Contract (Blueprint §10) | Table(s) |
|---|---|
| `TenantContext` | `tenants` + `virtual_keys` |
| `CacheStoreRequest`/`CacheResult` | `cache_entries`, `cache_vectors` |
| `RequestTrace` | `request_logs` |
| `SecurityAuditEvent` | `security_events` |
| `ProviderHealth` (persisted part) | `providers`, `circuit_events` |
| `StageTimings` | `request_logs.t_*_ms` |
| `GuardrailPolicy` | YAML files (not DB); `policy_version` stored per entry/event |
