-- Migration 0004 — seed: provider rows and example model_aliases.
-- Owner: Member 2.
-- Applied inside a transaction after 0003.
-- Immutable once merged to main.
--
-- IMPORTANT: model_id values in model_aliases are PLACEHOLDER strings prefixed
-- with "VERIFY:" — the team must replace them with verified, current model IDs
-- on setup day (see docs/ARCHITECTURE_BLUEPRINT.md §5 and providers tool docs).
-- Only free-tier models are seeded (zero-cost project constraint, D-006).
-- Provider auth_env_var holds the VARIABLE NAME only, never the key value.
--
-- updated_at = 0 (bootstrap epoch) for seeded rows; the application updates
-- this column on any admin mutation.

-- ---------------------------------------------------------------------------
-- Seed providers
-- ---------------------------------------------------------------------------
INSERT INTO providers (
    id, display_name, base_url, auth_env_var,
    enabled, priority, free_tier_only,
    rpm_cap, rpd_cap,
    connect_timeout_s, read_timeout_s,
    cb_failure_threshold, cb_recovery_s, cb_half_open_probes,
    extra_headers_json, updated_at
) VALUES
(
    'groq',
    'Groq',
    'https://api.groq.com/openai/v1',
    'GROQ_API_KEY',
    1, 10, 1,
    25, NULL,          -- Groq free tier: ~30 rpm; cap set ~80% = 25
    5, 60,
    5, 30, 1,
    '{}', 0
),
(
    'openrouter',
    'OpenRouter',
    'https://openrouter.ai/api/v1',
    'OPENROUTER_API_KEY',
    1, 20, 1,
    18, NULL,          -- OpenRouter free tier varies; conservative cap
    5, 60,
    5, 30, 1,
    '{"HTTP-Referer": "https://github.com/your-org/fluxgate", "X-Title": "FluxGate"}', 0
),
(
    'nvidia_nim',
    'NVIDIA NIM',
    'https://integrate.api.nvidia.com/v1',
    'NVIDIA_API_KEY',
    1, 30, 1,
    NULL, NULL,        -- NVIDIA free tier limits vary by model; unset = unlimited outbound (circuit breaker handles 429s)
    5, 60,
    5, 30, 1,
    '{}', 0
);

-- ---------------------------------------------------------------------------
-- Seed model aliases
-- WARNING: Verify these model IDs before first use on setup day.
--          Replace every "VERIFY:..." string with the current, correct model ID
--          from each provider's documentation / free-tier model list.
--          Use `python scripts/verify_env.py` to confirm reachability.
-- ---------------------------------------------------------------------------
INSERT INTO model_aliases (
    id, alias, provider_id, model_id, is_free, enabled,
    reference_price_in, reference_price_out
) VALUES
-- fluxgate-default: fast, free, general-purpose alias (resolved in priority order)
('01JFLXG0001GROQDFLT001',  'fluxgate-default', 'groq',       'VERIFY:llama-3.1-8b-instant',              1, 1,  0.10, 0.10),
('01JFLXG0001ORDFLT00001',  'fluxgate-default', 'openrouter', 'VERIFY:meta-llama/llama-3.1-8b-instruct:free', 1, 1, 0.10, 0.10),
('01JFLXG0001NVDFLT000001', 'fluxgate-default', 'nvidia_nim', 'VERIFY:meta/llama-3.1-8b-instruct',        1, 1,  0.10, 0.10),

-- fluxgate-fast: smallest/fastest alias (latency-optimised; L2 threshold-sweep workload)
('01JFLXG0002GROQFAST001',  'fluxgate-fast',    'groq',       'VERIFY:llama-3.1-8b-instant',              1, 1,  0.10, 0.10),
('01JFLXG0002ORFAST00001',  'fluxgate-fast',    'openrouter', 'VERIFY:meta-llama/llama-3.1-8b-instruct:free', 1, 1, 0.10, 0.10),
('01JFLXG0002NVFAST000001', 'fluxgate-fast',    'nvidia_nim', 'VERIFY:meta/llama-3.1-8b-instruct',        1, 1,  0.10, 0.10),

-- fluxgate-smart: largest free-tier alias (quality tasks; playground default)
('01JFLXG0003GROQSMART001', 'fluxgate-smart',   'groq',       'VERIFY:llama-3.3-70b-versatile',           1, 1,  0.59, 0.79),
('01JFLXG0003ORSMART00001', 'fluxgate-smart',   'openrouter', 'VERIFY:meta-llama/llama-3.3-70b-instruct:free', 1, 1, 0.59, 0.79),
('01JFLXG0003NVSMART000001','fluxgate-smart',   'nvidia_nim', 'VERIFY:meta/llama-3.3-70b-instruct',       1, 1,  0.59, 0.79);
