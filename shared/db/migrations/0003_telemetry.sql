-- Migration 0003 — telemetry tables: request_logs, security_events,
--                  circuit_events, metrics_rollup.
-- Owner: Member 2.
-- Applied inside a transaction; foreign keys are ON per-connection pragma.
-- Immutable once merged to main.
--
-- Retention policy (enforced by hourly maintenance job in gateway/telemetry/):
--   request_logs (no findings): 14 days
--   request_logs with findings + their security_events: 30 days (cascade)
--   circuit_events: 30 days
--   metrics_rollup: 90 days
--
-- Note: request_logs has NO FK to tenants/virtual_keys deliberately —
--   logs must outlive deleted tenants and keys to preserve audit history.

-- ---------------------------------------------------------------------------
-- Request logs (one row per gateway request; no raw prompt bodies)
-- ---------------------------------------------------------------------------
CREATE TABLE request_logs (
    request_id            TEXT PRIMARY KEY,                         -- 'req_' + ULID
    tenant_id             TEXT    NOT NULL,                         -- no FK: logs outlive deleted tenants/keys
    key_id                TEXT    NOT NULL,
    created_at            INTEGER NOT NULL,                         -- Unix milliseconds UTC
    model_requested       TEXT    NOT NULL,
    model_served          TEXT,
    provider_id           TEXT,
    served_from           TEXT    NOT NULL CHECK (served_from IN ('l1','l2','provider','error')),
    streamed              INTEGER NOT NULL DEFAULT 0 CHECK (streamed IN (0,1)),
    status_code           INTEGER NOT NULL,
    error_code            TEXT,                                     -- 'fluxgate_policy_block', 'rate_limit_exceeded', …
    client_disconnected   INTEGER NOT NULL DEFAULT 0 CHECK (client_disconnected IN (0,1)),
    -- cache outcome
    cache_outcome         TEXT    NOT NULL CHECK (cache_outcome IN ('hit_l1','hit_l2','miss','bypass')),
    cache_entry_id        TEXT,                                     -- soft reference (entry may expire); no FK
    similarity            REAL,
    near_miss_similarity  REAL,
    bypass_reason         TEXT,
    compat_mismatch       TEXT,
    store_stored          INTEGER CHECK (store_stored IS NULL OR store_stored IN (0,1)),
    -- security aggregates (details in security_events)
    guardrail_decision    TEXT    CHECK (guardrail_decision IS NULL OR guardrail_decision IN ('allow','warn','block')),
    risk_score            REAL,
    policy_name           TEXT,
    policy_version        TEXT,
    degraded              INTEGER NOT NULL DEFAULT 0 CHECK (degraded IN (0,1)),
    finding_summary_json  TEXT    NOT NULL DEFAULT '{}',            -- {"pii_email":1,"secret_api_key":1}
    redaction_count       INTEGER NOT NULL DEFAULT 0,
    -- token and cost accounting
    prompt_tokens         INTEGER,
    completion_tokens     INTEGER,
    usage_estimated       INTEGER NOT NULL DEFAULT 0 CHECK (usage_estimated IN (0,1)),
    tokens_saved          INTEGER NOT NULL DEFAULT 0,
    cost_saved_usd_est    REAL    NOT NULL DEFAULT 0,
    -- stage timings (milliseconds)
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
    -- routing summary
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    attempts_json         TEXT    NOT NULL DEFAULT '[]',            -- [{provider,model,status,failure,latency_ms,circuit}]
    failed_over           INTEGER NOT NULL DEFAULT 0 CHECK (failed_over IN (0,1)),
    -- content-safe identifiers (no raw text)
    prompt_sha256         TEXT    NOT NULL,                         -- sha256 of raw canonical prompt (irreversible); correlates repeats
    prompt_chars          INTEGER NOT NULL DEFAULT 0,
    sanitized_preview     TEXT,                                     -- <= 80 chars of SANITIZED text; NULL when disabled (D-004)
    client_ip_hash        TEXT                                      -- salted sha256 hash, never raw IP
);
CREATE INDEX idx_reqlog_time        ON request_logs (created_at DESC);
CREATE INDEX idx_reqlog_tenant_time ON request_logs (tenant_id, created_at DESC);
CREATE INDEX idx_reqlog_key_time    ON request_logs (key_id, created_at DESC);
CREATE INDEX idx_reqlog_cache_time  ON request_logs (cache_outcome, created_at DESC);
CREATE INDEX idx_reqlog_provider    ON request_logs (provider_id, created_at DESC);
CREATE INDEX idx_reqlog_status      ON request_logs (status_code, created_at DESC);
CREATE INDEX idx_reqlog_decision    ON request_logs (guardrail_decision, created_at DESC) WHERE guardrail_decision IN ('warn','block');
CREATE INDEX idx_reqlog_prompthash  ON request_logs (prompt_sha256);

-- ---------------------------------------------------------------------------
-- Security audit events (one row per Finding that reached audit threshold)
-- ---------------------------------------------------------------------------
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
    source                TEXT    NOT NULL,                         -- ContentSource enum value
    message_index         INTEGER,
    chunk_id              TEXT,
    span_start            INTEGER,
    span_end              INTEGER,
    masked_preview        TEXT,                                     -- masked, <= 64 chars; never raw value
    policy_name           TEXT    NOT NULL,
    policy_version        TEXT    NOT NULL
);
CREATE INDEX idx_secev_time      ON security_events (created_at DESC);
CREATE INDEX idx_secev_request   ON security_events (request_id);
CREATE INDEX idx_secev_type_time ON security_events (finding_type, created_at DESC);
CREATE INDEX idx_secev_rule_time ON security_events (rule_id, created_at DESC);
CREATE INDEX idx_secev_sev_time  ON security_events (severity, created_at DESC);

-- ---------------------------------------------------------------------------
-- Circuit breaker event log
-- ---------------------------------------------------------------------------
CREATE TABLE circuit_events (
    id                    TEXT PRIMARY KEY,                         -- ULID
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

-- ---------------------------------------------------------------------------
-- Per-minute metrics rollup (fast dashboard KPI queries without log scans)
-- ---------------------------------------------------------------------------
CREATE TABLE metrics_rollup (
    bucket_start          INTEGER NOT NULL,                         -- minute start, Unix milliseconds UTC
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
    -- latency histogram counts per fixed bucket (ms): [5,10,20,50,100,200,500,1000,2000,5000,+inf]
    lat_total_hist_json   TEXT    NOT NULL DEFAULT '[]',
    lat_overhead_hist_json TEXT   NOT NULL DEFAULT '[]',
    lat_upstream_hist_json TEXT   NOT NULL DEFAULT '[]',
    lat_l2_hist_json      TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (bucket_start, tenant_id, provider_id)
);
CREATE INDEX idx_rollup_tenant_time ON metrics_rollup (tenant_id, bucket_start DESC);
