-- Migration 0001 — core config tables: tenants, virtual keys, providers,
--                  model aliases, app settings, admin audit log.
-- Owner: Member 2.
-- Applied inside a transaction; foreign keys are ON per-connection pragma.
-- Immutable once merged to main.

-- ---------------------------------------------------------------------------
-- Tenants
-- ---------------------------------------------------------------------------
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
    created_at            INTEGER NOT NULL,                         -- Unix milliseconds UTC
    updated_at            INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Virtual API keys
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- Providers (Groq, OpenRouter, NVIDIA NIM)
-- ---------------------------------------------------------------------------
CREATE TABLE providers (
    id                    TEXT PRIMARY KEY CHECK (id IN ('groq','openrouter','nvidia_nim')),
    display_name          TEXT    NOT NULL,
    base_url              TEXT    NOT NULL,
    auth_env_var          TEXT    NOT NULL,                         -- NAME of env var, never the key value
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

-- ---------------------------------------------------------------------------
-- Logical model aliases (alias → provider concrete model ID)
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- Application settings (key-value store for tunable runtime config)
-- ---------------------------------------------------------------------------
CREATE TABLE app_settings (
    key                   TEXT PRIMARY KEY,                         -- e.g., 'retention.request_logs_days', 'privacy.store_prompt_preview'
    value                 TEXT    NOT NULL,
    updated_at            INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Admin audit log (every admin mutation; no secrets)
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- Seed: reserved tenants (created_at/updated_at = 0 = "bootstrap epoch")
-- ---------------------------------------------------------------------------
INSERT INTO tenants (id, name, created_at, updated_at) VALUES
  ('default',           'default',           0, 0),
  ('__playground__',    '__playground__',    0, 0),
  ('__playground_b__',  '__playground_b__',  0, 0);
