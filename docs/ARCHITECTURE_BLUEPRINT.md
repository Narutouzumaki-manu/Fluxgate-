# FluxGate — Architecture Blueprint

| Field | Value |
|---|---|
| Status | **DRAFT v1.0 — pending approval by both developers** |
| Contract version | `1.0.0` (see §11) |
| Owners | Member 1 (Dev A) — `guardrails/`, `cache/`, `integration/`; Member 2 (Dev B) — `gateway/`, `router/`, `dashboard/`; `shared/` is jointly owned |
| Audience | Both developers. This is the source of truth for structure, interfaces and latency budgets |

> **Rule 0:** Targets in this document are **engineering targets, not achieved results**. Nothing here may be quoted as a measured number until it appears in a committed benchmark report (`integration/benchmarks/reports/`).

---

## 1. What FluxGate Is

A self-hosted, OpenAI-compatible reverse proxy that sits between any AI application and external LLM providers.

```
Any OpenAI-SDK client ──► FluxGate :8000/v1/chat/completions ──► Groq | OpenRouter | NVIDIA NIM
   (only base_url changes)    auth · limits · guardrails · cache · routing · telemetry
```

Four infrastructure concerns are handled once, at the gateway, instead of in every application:

1. **Cost/latency** — dual-layer cache (exact + semantic).
2. **Resilience** — multi-provider routing with circuit breakers.
3. **Security** — prompt/context-injection risk scoring, PII/secret redaction before data leaves the machine.
4. **Visibility** — traces, audit logs, KPIs, a red-team playground.

### Design principles

1. **Fail safe, not fail open, for security; fail open for cache.** Guardrail internal error → configurable (`block` default in strict mode). Cache error → bypass cache and continue.
2. **Tenant isolation is structural**, not a filter: tenant ID is part of every cache key and every FAISS index is per-tenant.
3. **No raw secrets/PII at rest or in logs.** Only hashes, masked previews, counts, and spans.
4. **Detection is risk assessment, never a guarantee** (OWASP LLM01 reality). All UI and docs use "risk score", never "safe".
5. **Contracts first.** Members integrate through `shared/contracts` only; no cross-imports of internals.
6. **MVP-lean.** One process, SQLite, in-memory FAISS, no message broker, no Redis.

---

## 2. Architecture Decision Records (Spec Improvements Made in This Blueprint)

These go beyond the original brief. Each is a deliberate fix for a real failure mode. **Please approve or veto each in review.**

| ID | Decision | Why |
|---|---|---|
| ADR-01 | **L1 lookup runs *before* inbound guardrails**, keyed on `(tenant_id, policy_version, canonical_request_hash)`. | Only requests that already passed guardrails and were cache-eligible are ever stored, so an exact hit is already vetted. Saves ~15–25 ms on exact hits. Changing policy bumps `policy_version` and implicitly invalidates L1. |
| ADR-02 | **L2 runs *after* guardrails**, embedding the **sanitized** query text. | Never embed raw PII; never let an injection attempt semantically "match" a cached clean entry. |
| ADR-03 | **L2 embeds a short "semantic query", not the whole prompt.** Default: last user message. RAG clients may pass `fluxgate.semantic_query`. | `all-MiniLM-L6-v2` truncates at **256 word-pieces**; a RAG prompt with 5 chunks would embed mostly the chunks, and similarity would measure context, not the question. |
| ADR-04 | **L2 hit requires exact equality of a compatibility fingerprint**: model, system-prompt hash, non-query context hash, generation-params hash, tools hash, response_format hash, `policy_version`. Similarity alone is never sufficient. | Prevents serving an answer generated from different retrieved context, different persona, or different parameters. |
| ADR-05 | **Requests where PII/secrets were detected and redacted are not cache-eligible (P0).** | Placeholder-restoration across different requests would map wrong values. Simple and safe. P1 may revisit. |
| ADR-06 | **One FAISS index per tenant** (`IndexIDMap(IndexFlatIP)` on L2-normalized vectors). | Cross-tenant leakage becomes impossible by construction, no post-filtering bugs. Flat search at ≤50k vectors/tenant is fast enough; ANN is unnecessary complexity for MVP. |
| ADR-07 | **Streaming uses tee-and-store:** forward chunks live while accumulating; store only if stream completed (`[DONE]` seen, `finish_reason == "stop"`, client still connected). Cache hits on `stream=true` are replayed as synthetic SSE. `stream` is **excluded** from the cache key so both modes share entries. | Streaming must not defeat caching; partial responses must never be cached. |
| ADR-08 | **Failover after the first byte reaches the client is forbidden.** Pre-first-byte failures (429/5xx/timeout/connect) may fail over. Mid-stream failure emits an error SSE event and closes. | Prevents spliced answers from two models. |
| ADR-09 | **Single-process deployment for MVP** (`uvicorn --workers 1`). In-memory token buckets, circuit-breaker state, FAISS indexes and L1 LRU assume one process. | Honest scope. Multi-worker needs Redis/shared state → P1/non-goal. |
| ADR-10 | **CPU-bound work (embedding, regex scans on large inputs) runs in a bounded thread pool** via `asyncio.to_thread`/dedicated executor; the event loop does only I/O and orchestration. | Keeps SSE latency steady while a request is being embedded. |
| ADR-11 | **Virtual keys are stored as `HMAC-SHA256(server_pepper, key)`**, not bare SHA-256. | Keys are high-entropy so a fast hash is fine, but a pepper means a leaked DB alone cannot be used to verify guesses. Satisfies "SHA-256 hashing, never raw". |
| ADR-12 | **Gateway extension field `fluxgate` in the request body** (`FluxGateOptions`), stripped before forwarding upstream. Plain OpenAI SDKs can send it through `extra_body`. Never required. | Lets RAG clients pass `retrieved_context` (for indirect-injection scanning) and `semantic_query`/`context_fingerprint` (for safe L2) without breaking SDK compatibility. |
| ADR-13 | **Logical model aliases** (`fluxgate-default`, plus pass-through of real model IDs) mapped per provider in config. | Provider model IDs differ and churn; failover across providers needs a mapping layer. |
| ADR-14 | **Telemetry is event-based:** M1 modules never touch the dashboard DB tables; they return timing/finding data in result objects and the gateway persists them. | Keeps Stage 1 fully standalone and testable without M2 code. |
| ADR-15 | **Injection detection P0 = rule engine + weighted heuristic scoring** (no heavy model). Optional embedding-kNN scorer and a small classifier are P1 behind feature flags, adopted only if they meet the latency budget in benchmarks. | A DeBERTa-class classifier can cost 50–150 ms on CPU; unproven against the budget. Rules are fast, explainable, testable. |

---

## 3. High-Level System Architecture

```
                                   ┌─────────────────────────────────────────────────────────┐
                                   │                    DEVELOPER / OPERATOR                  │
                                   │        Dashboard UI (:8000/dashboard)  ·  CLI tools       │
                                   └───────────────▲─────────────────────────────────────────┘
                                                   │ reads telemetry / manages keys
┌────────────────────┐  HTTP+SSE   ┌───────────────┴─────────────────────────────────────────┐        ┌──────────────┐
│  Client apps       │────────────►│                      FLUXGATE (single process)           │───────►│ Groq         │
│  · Hybrid RAG      │ fgx-… key   │                                                          │ HTTPS  ├──────────────┤
│  · Chatbots/Agents │◄────────────│  gateway/  ──►  guardrails/  ──►  cache/  ──►  router/   │───────►│ OpenRouter   │
│  · OpenAI SDK      │ JSON / SSE  │   (M2)           (M1)             (M1)        (M2)       │        ├──────────────┤
└────────────────────┘             │                                                          │───────►│ NVIDIA NIM   │
                                   │  shared/contracts  ·  shared/db  ·  telemetry queue      │        └──────────────┘
                                   └───────┬───────────────┬───────────────────┬──────────────┘
                                           │               │                   │
                                    ┌──────▼─────┐  ┌──────▼───────┐   ┌───────▼────────────┐
                                    │ SQLite WAL │  │ FAISS (RAM)  │   │ In-memory state     │
                                    │ keys,logs, │  │ per-tenant   │   │ token buckets,      │
                                    │ cache rows │  │ L2 vectors   │   │ breaker state, L1   │
                                    └────────────┘  └──────────────┘   │ LRU, redaction vault│
                                                                       └─────────────────────┘
```

## 4. Component-Level Architecture (Request Pipeline)

```
 CLIENT REQUEST  POST /v1/chat/completions   Authorization: Bearer fgx-…
        │
        ▼
┌─ gateway/ (M2) ─────────────────────────────────────────────────────────────────────────────┐
│ [1] Auth: HMAC(key) → TenantContext (in-mem cache of key records)         ──► 401 / 403       │
│ [2] Token-bucket rate limit per key                                         ──► 429 + Retry-After│
│ [3] Parse → ChatCompletionRequest, extract FluxGateOptions, validate        ──► 400             │
└───────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                                ▼
┌─ cache/ (M1) ───────────────────────────────────────────────────────────────────────────────┐
│ [4] L1 exact lookup (tenant, policy_version, SHA-256(canonical request))                      │
│        HIT ───────────────────────────────────────────────────────────────┐                  │
└───────────────────────────────────────────────┬───────────────────────────┼─────────────────┘
                                          MISS  ▼                           │
┌─ guardrails/ (M1) ──────────────────────────────────────────────────────┐ │
│ [5] Normalize text (NFKC, zero-width strip, decode-probe)                │ │
│     Inbound scan: injection scoring (user, system, RAG context)          │ │
│     PII + secret detect → redact to placeholders → sanitized_request     │ │
│     Decision: ALLOW | WARN | BLOCK                                       │ │
│        BLOCK ──► 400 fluxgate_policy_block (audit logged)                │ │
└───────────────────────────────────────────────┬─────────────────────────┘ │
                                                ▼                           │
┌─ cache/ (M1) ───────────────────────────────────────────────────────────┐ │
│ [6] L2 semantic lookup (per-tenant FAISS, cos > 0.92 AND compat match)   │ │
│        HIT ───────────────────────────────────────────────────────────┐ │ │
└───────────────────────────────────────────────┬───────────────────────┼─┘ │
                                          MISS  ▼                       │   │
┌─ router/ (M2) ──────────────────────────────────────────────────────┐ │   │
│ [7] Select provider (health, circuit state, priority, model map)     │ │   │
│     Adapter call (httpx async) · retry/failover rules (ADR-08)       │ │   │
└───────────────────────────────────────────────┬─────────────────────┘ │   │
                                                ▼                       │   │
┌─ guardrails/ (M1) ──────────────────────────────────────────────────┐ │   │
│ [8] Response scan: non-stream → ResponseScanner;                     │ │   │
│     stream → StreamRedactor (sliding-window) per chunk; restore      │ │   │
│     placeholders if policy allows (vault is request-scoped)          │ │   │
└───────────────────────────────────────────────┬─────────────────────┘ │   │
                                                ▼                       │   │
┌─ cache/ (M1) ───────────────────────────────────────────────────────┐ │   │
│ [9] Eligibility + poisoning checks → store L1+L2 (background task)   │ │   │
└───────────────────────────────────────────────┬─────────────────────┘ │   │
                                                ▼◄──────────────────────┴───┘
┌─ gateway/ (M2) ─────────────────────────────────────────────────────────────────────────────┐
│ [10] Build GatewayResponse · headers (X-FluxGate-*) · enqueue telemetry · return JSON / SSE    │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Orchestration owner:** `gateway/pipeline.py` (M2) calls the other modules only through the Protocols in §10. M1 modules never call the router or gateway.

---

## 5. Repository Folder Tree

Ownership legend: **[S]** shared (both approve) · **[M1]** Member 1 · **[M2]** Member 2.

```
fluxgate/
├── README.md                          [S]
├── SECURITY.md                        [S]
├── LICENSE                            [S]  (MIT or Apache-2.0 — decide before first public push)
├── pyproject.toml                     [S]
├── uv.lock                            [S]  (committed lockfile)
├── .env.example                       [S]  (no real secrets)
├── .gitignore                         [S]
├── .pre-commit-config.yaml            [S]  (ruff, gitleaks, mypy)
├── Dockerfile                         [M2]
├── docker-compose.yml                 [M2]
├── Makefile                           [S]
│
├── .github/
│   ├── CODEOWNERS                     [S]
│   ├── PULL_REQUEST_TEMPLATE.md       [S]
│   └── workflows/ci.yml               [S]
│
├── config/
│   ├── fluxgate.example.yaml          [S]  (server, cache, limits)
│   ├── providers.example.yaml         [M2] (provider URLs, model map, priorities)
│   └── policies/
│       ├── default.yaml               [M1] (guardrail policy)
│       └── strict.yaml                [M1]
│
├── docs/                              [S]  (all planning docs; this file lives here)
│
├── shared/                            [S]  ── CONTRACT-OWNED. Changes need both approvals.
│   ├── contracts/
│   │   ├── __init__.py                     (CONTRACT_VERSION, re-exports)
│   │   ├── enums.py
│   │   ├── openai_models.py                (ChatMessage, ChatCompletionRequest/Response/Chunk)
│   │   ├── context.py                      (TenantContext, RequestContext)
│   │   ├── guardrails.py                   (GuardrailPolicy, Finding, GuardrailResult, ResponseScanResult)
│   │   ├── cache.py                        (CacheKeys, CacheResult, CacheStoreRequest, StoreDecision)
│   │   ├── router.py                       (RouterRequest, RouteAttempt, RouterResult, ProviderHealth)
│   │   ├── gateway.py                      (GatewayResponse, StageTimings, ErrorInfo)
│   │   ├── telemetry.py                    (RequestTrace, SecurityAuditEvent)
│   │   └── protocols.py                    (GuardrailEngine, CacheEngine, Router, StreamRedactor, …)
│   ├── config.py                           (pydantic-settings; one Settings tree)
│   ├── errors.py                           (FluxGateError hierarchy → OpenAI error mapping)
│   ├── logging.py                          (structlog + mandatory redacting processor)
│   ├── ids.py                              (request_id, key generation helpers)
│   ├── db/
│   │   ├── connection.py                   (aiosqlite, WAL pragmas)
│   │   ├── migrator.py                     (numbered .sql runner)
│   │   └── migrations/                     (0001_init.sql …; each member owns own tables' files)
│   └── testing/
│       ├── fakes.py                        (FakeGuardrailEngine, FakeCacheEngine, FakeRouter)
│       ├── fixtures/                       (golden request/response JSON)
│       └── fake_clock.py
│
├── guardrails/                        [M1] ── AI security
│   ├── __init__.py                         (build_guardrail_engine(settings) -> GuardrailEngine)
│   ├── engine.py                           (orchestrates scan → decide → sanitize)
│   ├── policy.py                           (load/validate/version YAML policies)
│   ├── normalize.py                        (NFKC, zero-width/bidi strip, homoglyph fold, decode-probe)
│   ├── injection/
│   │   ├── rules.py                        (rule registry: id, regex, weight, category)
│   │   ├── scorer.py                       (weighted aggregation → risk 0..1)
│   │   ├── context_scan.py                 (indirect injection in retrieved chunks)
│   │   └── corpus/                         (attack_phrases.yaml, benign_phrases.yaml)
│   ├── pii/
│   │   ├── detectors.py                    (email, phone, Aadhaar, PAN, card, custom)
│   │   ├── validators.py                   (Verhoeff, Luhn, PAN structure)
│   │   ├── redactor.py                     (span merge, placeholder substitution)
│   │   └── vault.py                        (request-scoped placeholder↔value map; RAM only)
│   ├── secrets/
│   │   ├── patterns.py                     (provider key formats incl. fgx-, gsk_, nvapi-, sk-or-)
│   │   └── entropy.py                      (high-entropy token heuristic, allowlist)
│   ├── stream/
│   │   └── sliding_window.py               (StreamRedactor implementation)
│   ├── response_scanner.py                 (non-stream response scan)
│   └── cli.py                              (python -m guardrails.cli check|redact|stream-sim)
│
├── cache/                             [M1] ── semantic cache
│   ├── __init__.py                         (build_cache_engine(settings, db) -> CacheEngine)
│   ├── engine.py                           (lookup_exact / lookup_semantic / maybe_store / invalidate)
│   ├── canonicalize.py                     (stable request normalization for hashing)
│   ├── keys.py                             (SHA-256 exact key, compat fingerprint)
│   ├── l1_exact.py                         (in-mem LRU + SQLite backing)
│   ├── l2_semantic.py                      (threshold, compat check, near-miss reporting)
│   ├── embedding.py                        (EmbeddingService: MiniLM, thread pool, memo LRU)
│   ├── faiss_index.py                      (per-tenant IndexIDMap(IndexFlatIP), rebuild/evict)
│   ├── eligibility.py                      (cache-or-not rules)
│   ├── poisoning.py                        (write-time + read-time poisoning defenses)
│   ├── store.py                            (cache_entries SQLite access)
│   ├── ttl.py                              (expiry sweeper)
│   └── cli.py                              (python -m cache.cli lookup|store|stats|sweep|threshold-sweep)
│
├── integration/                       [M1]
│   └── benchmarks/
│       ├── README.md
│       ├── rag_client_adapter.py           (drives Hybrid RAG via OpenAI SDK base_url only)
│       ├── workloads/                      (repeat.jsonl, paraphrase.jsonl, unique.jsonl, rag.jsonl)
│       ├── security_corpus/                (injection, pii_synthetic, benign)
│       ├── mock_upstream.py                (deterministic OpenAI-compatible fake provider)
│       ├── run_benchmarks.py
│       └── reports/                        (results/*.json, REPORT.md — committed with commit SHA)
│
├── gateway/                           [M2] ── proxy & control surface
│   ├── app.py                              (FastAPI factory, lifespan, middleware)
│   ├── pipeline.py                         (the §4 orchestration)
│   ├── routes/
│   │   ├── chat.py                         (POST /v1/chat/completions)
│   │   ├── models.py                       (GET /v1/models)
│   │   ├── health.py                       (/healthz, /readyz)
│   │   └── admin.py                        (key CRUD, playground endpoints, telemetry APIs)
│   ├── auth/ (keys.py, hashing.py, deps.py)
│   ├── ratelimit/ (token_bucket.py, limiter.py)
│   ├── streaming.py                        (SSE encode, tee-and-store, disconnect handling)
│   ├── errors.py                           (exception handlers → OpenAI error envelope)
│   └── telemetry/ (queue.py, writer.py, aggregates.py)
│
├── router/                            [M2] ── resilience
│   ├── base.py                             (ProviderAdapter ABC)
│   ├── adapters/ (groq.py, openrouter.py, nvidia_nim.py)
│   ├── model_map.py                        (logical alias → provider model ID)
│   ├── circuit_breaker.py                  (CLOSED/OPEN/HALF_OPEN)
│   ├── selector.py                         (priority + health + cooldown)
│   ├── retry.py                            (retry-safety policy, backoff, jitter)
│   └── service.py                          (implements Router protocol)
│
├── dashboard/                         [M2] ── observability UI
│   ├── templates/ (base.html, overview.html, providers.html, traces.html, keys.html, playground.html)
│   ├── static/ (css/, js/, vendor/  ← vendored htmx, alpine, chart.js; no CDN at runtime)
│   └── views.py
│
├── scripts/                           [S]
│   ├── download_models.py                  (pins model revision, verifies checksum)
│   ├── verify_env.py                       (checks Python, deps, models, accounts reachable)
│   ├── create_dev_key.py                   (mints fgx- key, prints once)
│   └── verify_m1.py                        [M1] (standalone Stage-1 acceptance runner)
│
└── tests/
    ├── unit/{guardrails,cache}/        [M1]
    ├── unit/{gateway,router}/          [M2]
    ├── contract/                       [S]  (schema snapshot + fake-vs-real conformance)
    ├── security/                       [M1] (tenant isolation, poisoning, log-leak tests)
    ├── perf/                           [S]
    ├── integration/                    [S]  (pipeline with real M1 modules + mock upstream)
    └── e2e/                            [M2] (OpenAI SDK → uvicorn → mock/real providers)
```

**Import rules (enforced by a CI import-linter check):**
- `guardrails/` and `cache/` may import only `shared/` and third-party libs.
- `router/` may import only `shared/`.
- `gateway/` may import `shared/` and the public builder functions `guardrails.build_guardrail_engine`, `cache.build_cache_engine`, `router.build_router`. Nothing else.
- `dashboard/` may import `shared/` and `gateway.routes.admin` APIs only.
- Nothing imports from `integration/`. The Hybrid RAG project is **never** imported anywhere in FluxGate.

---

## 6. End-to-End Lifecycle and Latency Budgets

All values are **engineering targets (p95)**, on a 4-core laptop-class CPU, prompts ≤ 512 tokens, warm process, MiniLM loaded, ≤ 50k vectors per tenant. They are **unvalidated until benchmarked**. Upstream provider time is excluded.

### 6.1 Non-streaming request

| # | Stage | Owner | Budget (p95) | Notes |
|---|---|---|---|---|
| 1 | Auth + key lookup | M2 | ≤ 1 ms | in-memory key-record cache, HMAC compare |
| 2 | Rate limit | M2 | ≤ 0.3 ms | in-memory token bucket |
| 3 | Parse/validate/canonicalize | M2/M1 | ≤ 3 ms | canonicalization is M1's `cache.canonicalize` |
| 4 | **L1 lookup** | M1 | ≤ 2 ms | LRU hit; ≤ 8 ms if SQLite fallback |
| 5 | Inbound guardrails (rules + PII/secret + redact) | M1 | ≤ 15 ms (≤ 40 ms for 8k-token RAG prompts) | regex compiled once; linear-time patterns only |
| 6 | **L2 lookup** (embed + FAISS + compat) | M1 | **≤ 20 ms** (embed ≤ 14, search ≤ 3, compat ≤ 1) | the brief's L2 target |
| 7 | Router selection + dispatch overhead | M2 | ≤ 3 ms | excludes network |
| 8 | Response scan (non-stream) | M1 | ≤ 5 ms per 1k tokens | |
| 9 | Eligibility + store | M1 | off critical path | background task |
| 10 | Telemetry enqueue + response build | M2 | ≤ 2 ms | writer is async batch |

**Aggregate targets**
- **L1 hit:** gateway server time ≤ 10 ms.
- **L2 hit:** ≤ 55 ms (stages 1–6 + response build).
- **Miss overhead added by FluxGate (excluding upstream):** ≤ 45 ms for typical prompts.
- Overhead on streaming TTFT: ≤ 45 ms (stages 1–7) plus ≤ 0.5 ms per chunk redaction.

### 6.2 Streaming request

```
client ◄── SSE chunk ◄── StreamRedactor.feed(delta) ◄── adapter yields upstream delta
                               │ holds back ≤ W chars (window) when tail could be a partial secret/placeholder
                               ▼
                       accumulator (RAM, bounded) ──► on clean completion → CacheEngine.maybe_store (background)
```

- First byte to client after: stages 1–7 + first upstream chunk.
- Window `W` default = 96 chars (≥ longest secret/placeholder pattern prefix); this adds at most one chunk of added delay for text near a potential match, zero otherwise.
- Client disconnect → cancel upstream request, discard accumulator, **no cache write**, emit `client_disconnected` trace.
- Stream cache hit → synthetic chunks (`~20-char` deltas, no artificial sleep by default; optional `replay_delay_ms` for UX).

### 6.3 Failure paths

| Condition | Behavior |
|---|---|
| Guardrail BLOCK | HTTP 400, code `fluxgate_policy_block`, no upstream call, audit event written |
| Guardrail internal error | `strict` policy → 503 `fluxgate_guardrail_unavailable`; `permissive` → continue with `degraded=true` flag in trace |
| Cache error (embedding/FAISS/SQLite) | Treated as MISS + `BYPASS(cache_error)`; request continues |
| Provider 429 / 5xx / timeout before first byte | Router fails over to next provider (ADR-08) |
| All providers unavailable | HTTP 503 `fluxgate_no_healthy_provider` with `Retry-After` |
| Rate limit exceeded | HTTP 429 `rate_limit_exceeded` + `Retry-After` |
| Invalid/unknown key | HTTP 401 `invalid_api_key` (OpenAI-compatible) |

---

## 7. Data Classification and Storage Rules

| Data | May be persisted? | May be logged? | Where |
|---|---|---|---|
| Raw virtual API key | **Never** (shown once at creation) | **Never** | — |
| `HMAC-SHA256(pepper, key)` + 8-char prefix | Yes | prefix only | SQLite `virtual_keys` |
| Raw provider API keys | Env/secret store only | **Never** | `.env` / process env |
| Raw user prompt | **No** (P0) | **No** | — |
| Sanitized (redacted) prompt text | Yes, in `cache_entries` only for eligible entries; request logs store **hash + length + first 80 chars of sanitized text** (configurable off) | Same | SQLite |
| Detected PII/secret values | **Never** | **Never** | only RAM vault for request lifetime |
| Findings (category, rule_id, span, masked preview e.g. `AKIA****MPLE`) | Yes | Yes | SQLite audit tables |
| Cached response text | Yes (clean, scanned) | No | SQLite + not in logs |
| Embeddings | Yes (BLOB) for index rebuild | No | SQLite + FAISS RAM |

A mandatory **redacting log processor** (`shared/logging.py`) runs every log record through the secret patterns before emission. A CI test (`tests/security/test_no_secret_in_logs.py`) feeds canary secrets through the whole pipeline and fails if any canary appears in logs, DB, or traces.

---

## 8. Runtime Topology and Constraints

- One Python process, one event loop, `uvicorn --workers 1`.
- Thread pool for CPU work (`FLUXGATE_CPU_THREADS`, default 2). Set `OMP_NUM_THREADS`/`torch.set_num_threads` to avoid oversubscription.
- SQLite in WAL mode, `synchronous=NORMAL`, `busy_timeout=5000`; single writer task for telemetry (batching) and a separate short-lived writer for cache stores.
- Startup: load policy → load MiniLM → rebuild per-tenant FAISS indexes from `cache_entries` embeddings (lazy per tenant on first use, to keep startup fast).
- Graceful shutdown: drain telemetry queue (≤ 5 s), close httpx clients.
- Readiness (`/readyz`) is true only after embedding model warm-up (one dummy embedding).

---

## 9. Ownership Matrix

| Area | Owner | Reviewer |
|---|---|---|
| `guardrails/**`, `cache/**`, `integration/**`, `config/policies/**`, `tests/{unit/guardrails,unit/cache,security}`, `scripts/verify_m1.py` | **Member 1** | Member 2 |
| `gateway/**`, `router/**`, `dashboard/**`, `Dockerfile`, `docker-compose.yml`, `config/providers.example.yaml`, `tests/{unit/gateway,unit/router,e2e}` | **Member 2** | Member 1 |
| `shared/**`, `docs/**`, root files, `.github/**`, `tests/{contract,perf,integration}` | **Both** | Both approve |

---

## 10. Shared Pydantic Interface Contracts (v1.0.0)

These are the **specification** of `shared/contracts/*`. They are copied verbatim into the repo during Phase 1 scaffolding (after all batches are approved). Pydantic v2, Python ≥ 3.11.

> **Rules:** (1) After Phase 2 starts, changes are **additive-only** (new optional fields with defaults). (2) Any change = PR labelled `contract-change`, both approvals, `CONTRACT_VERSION` bump, CHANGELOG entry. (3) `extra="allow"` only on OpenAI-shaped models so unknown provider/SDK fields pass through; all FluxGate-internal models use `extra="forbid"`.

### 10.1 Enums — `shared/contracts/enums.py`

```python
from enum import StrEnum


class Decision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContentSource(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    RETRIEVED_CONTEXT = "retrieved_context"
    RESPONSE = "response"


class FindingType(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    INDIRECT_INJECTION = "indirect_injection"
    PROMPT_LEAK_ATTEMPT = "prompt_leak_attempt"
    OBFUSCATION = "obfuscation"
    PII_EMAIL = "pii_email"
    PII_PHONE = "pii_phone"
    PII_AADHAAR = "pii_aadhaar"
    PII_PAN = "pii_pan"
    PII_CARD = "pii_card"
    SECRET_API_KEY = "secret_api_key"
    SECRET_TOKEN = "secret_token"
    SECRET_PRIVATE_KEY = "secret_private_key"
    SECRET_HIGH_ENTROPY = "secret_high_entropy"
    CUSTOM = "custom"


class RedactionAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    REDACT = "redact"
    BLOCK = "block"


class GuardrailStage(StrEnum):
    INBOUND = "inbound"
    RESPONSE = "response"
    STREAM = "stream"


class CacheOutcome(StrEnum):
    HIT_L1 = "hit_l1"
    HIT_L2 = "hit_l2"
    MISS = "miss"
    BYPASS = "bypass"


class CacheBypassReason(StrEnum):
    CLIENT_OPT_OUT = "client_opt_out"
    CACHE_DISABLED = "cache_disabled"
    HIGH_TEMPERATURE = "high_temperature"
    TOOLS_PRESENT = "tools_present"
    MULTIMODAL = "multimodal"
    N_GREATER_THAN_ONE = "n_greater_than_one"
    PII_OR_SECRET_PRESENT = "pii_or_secret_present"
    GUARDRAIL_NOT_CLEAN = "guardrail_not_clean"
    RISK_ABOVE_THRESHOLD = "risk_above_threshold"
    RESPONSE_NOT_CLEAN = "response_not_clean"
    INCOMPLETE_RESPONSE = "incomplete_response"
    NON_STOP_FINISH = "non_stop_finish"
    TOO_LARGE = "too_large"
    CACHE_ERROR = "cache_error"
    TENANT_QUOTA_EXCEEDED = "tenant_quota_exceeded"


class ProviderName(StrEnum):
    GROQ = "groq"
    OPENROUTER = "openrouter"
    NVIDIA_NIM = "nvidia_nim"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RouteFailureKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    UPSTREAM_5XX = "upstream_5xx"
    TIMEOUT = "timeout"
    CONNECT_ERROR = "connect_error"
    CIRCUIT_OPEN = "circuit_open"
    BAD_REQUEST = "bad_request"
    AUTH_ERROR = "auth_error"
    STREAM_INTERRUPTED = "stream_interrupted"
    CLIENT_DISCONNECTED = "client_disconnected"
```

### 10.2 OpenAI-shaped models — `shared/contracts/openai_models.py`

```python
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str = Field(max_length=128)
    text: str = Field(max_length=32_000)
    source: str | None = Field(default=None, max_length=512)  # e.g. filename#page


class FluxGateOptions(BaseModel):
    """Optional extension (body field `fluxgate`). Stripped before upstream. Never required."""

    model_config = ConfigDict(extra="forbid")
    cache: Literal["auto", "bypass", "exact_only"] = "auto"
    semantic_query: str | None = Field(default=None, max_length=2_000)
    context_fingerprint: str | None = Field(
        default=None, max_length=128
    )  # hash of retrieved chunk IDs/versions
    cache_scope: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    retrieved_context: list[RetrievedChunk] | None = None
    guardrail_policy: str | None = Field(default=None, max_length=64)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # pass through unknown OpenAI params
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    n: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stop: str | list[str] | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    stream_options: dict[str, Any] | None = None
    user: str | None = None
    fluxgate: FluxGateOptions | None = None


class ChatCompletionUsage(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionChoice(BaseModel):
    model_config = ConfigDict(extra="allow")
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None = None
    system_fingerprint: str | None = None


class ChatCompletionChunkDelta(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str | None = None
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionChunkChoice(BaseModel):
    model_config = ConfigDict(extra="allow")
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]
    usage: ChatCompletionUsage | None = None
```

### 10.3 Context — `shared/contracts/context.py`

```python
from pydantic import BaseModel, ConfigDict, Field


class TenantContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tenant_id: str  # isolation boundary for cache, quotas, audit
    key_id: str  # virtual_keys.id
    key_prefix: str  # e.g. "fgx-ab12"  (never the full key)
    guardrail_policy: str = "default"
    cache_enabled: bool = True
    allowed_models: list[str] | None = None  # None = all
    rpm_limit: int = 60


class RequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    request_id: str  # "req_" + ULID
    tenant: TenantContext
    received_at_unix_ms: int
    client_ip_hash: str | None = None  # salted hash, never raw IP
    trace_enabled: bool = True
```

### 10.4 Guardrails — `shared/contracts/guardrails.py`

```python
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from .enums import *
from .openai_models import ChatCompletionRequest


class Finding(BaseModel):
    """Never contains raw sensitive values."""

    model_config = ConfigDict(extra="forbid")
    type: FindingType
    severity: Severity
    rule_id: str  # e.g. "INJ-0007", "PII-AADHAAR-VERHOEFF"
    confidence: float = Field(ge=0, le=1)
    source: ContentSource
    message_index: int | None = None
    chunk_id: str | None = None  # when from retrieved_context
    span: tuple[int, int] | None = None  # offsets in the normalized text of that message
    masked_preview: str | None = Field(default=None, max_length=64)  # e.g. "AKIA****MPLE"
    action: RedactionAction = RedactionAction.ALLOW
    meta: dict[str, str] = Field(default_factory=dict)  # non-sensitive only


class TypePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: RedactionAction = RedactionAction.REDACT
    restore_in_response: bool = False  # replace placeholder back in outputs (request-scoped)


class GuardrailPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str  # content hash of the normalized policy; part of L1/L2 keys
    injection_warn_threshold: float = 0.50
    injection_block_threshold: float = 0.85
    inspect_system_messages: bool = True
    inspect_retrieved_context: bool = True
    max_inspect_chars: int = 200_000  # beyond → truncate+warn finding, or block (policy-defined)
    on_oversize: Decision = Decision.WARN
    on_internal_error: Decision = Decision.BLOCK  # strict default
    pii: dict[FindingType, TypePolicy] = Field(default_factory=dict)
    secrets: TypePolicy = TypePolicy(action=RedactionAction.REDACT)
    response_scan: RedactionAction = RedactionAction.REDACT
    custom_patterns: dict[str, str] = Field(
        default_factory=dict
    )  # name → regex (validated linear-time-safe)


class GuardrailResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    request_id: str
    stage: GuardrailStage = GuardrailStage.INBOUND
    decision: Decision
    risk_score: float = Field(ge=0, le=1)  # injection/jailbreak risk, NOT a safety guarantee
    risk_level: Severity
    findings: list[Finding] = Field(default_factory=list)
    sanitized_request: ChatCompletionRequest | None = None  # None when BLOCK
    redaction_count: int = 0
    redacted_types: dict[str, int] = Field(default_factory=dict)
    policy_name: str
    policy_version: str
    degraded: bool = False  # internal error / timeout path taken
    reason: str | None = None  # human-safe summary for error body / UI
    latency_ms: float = 0.0
    vault: Any = Field(default=None, exclude=True)  # RedactionVault; RAM-only, never serialized

    @property
    def cache_clean(self) -> bool:
        return self.decision == Decision.ALLOW and self.redaction_count == 0 and not self.degraded


class ResponseScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Decision
    findings: list[Finding] = Field(default_factory=list)
    redaction_count: int = 0
    sanitized_text: str | None = None
    latency_ms: float = 0.0
```

### 10.5 Cache — `shared/contracts/cache.py`

```python
from pydantic import BaseModel, ConfigDict, Field
from .enums import *
from .openai_models import ChatCompletionRequest, ChatCompletionResponse, ChatCompletionUsage
from .guardrails import GuardrailResult, ResponseScanResult


class CacheKeys(BaseModel):
    """Computed at L1 lookup and passed through to maybe_store to avoid recomputation."""

    model_config = ConfigDict(extra="forbid")
    exact_key: str  # SHA-256 hex over (tenant, policy_version, canonical request)
    compat_hash: str | None = None  # set after guardrails (sanitized request)
    cache_scope: str | None = None


class CacheResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: CacheOutcome
    response: ChatCompletionResponse | None = None
    entry_id: str | None = None
    similarity: float | None = None  # L2 hit similarity
    near_miss_similarity: float | None = (
        None  # best candidate below threshold (dashboard/threshold tuning)
    )
    compat_mismatch: str | None = None  # which fingerprint component differed
    bypass_reason: CacheBypassReason | None = None
    age_seconds: int | None = None
    ttl_remaining_seconds: int | None = None
    keys: CacheKeys | None = None
    embed_ms: float = 0.0
    search_ms: float = 0.0
    latency_ms: float = 0.0

    @property
    def hit(self) -> bool:
        return self.outcome in (CacheOutcome.HIT_L1, CacheOutcome.HIT_L2)


class CacheStoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    keys: CacheKeys
    sanitized_request: ChatCompletionRequest
    response: ChatCompletionResponse
    guardrail_inbound: GuardrailResult
    response_scan: ResponseScanResult
    provider: ProviderName
    model_served: str
    usage: ChatCompletionUsage | None = None
    completed: bool = True  # False for aborted/partial streams
    streamed: bool = False
    ttl_seconds: int | None = None  # None → tenant/default TTL


class StoreDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stored: bool
    entry_id: str | None = None
    ineligible_reasons: list[CacheBypassReason] = Field(default_factory=list)
    latency_ms: float = 0.0
```

### 10.6 Router — `shared/contracts/router.py`

```python
from datetime import datetime
from typing import AsyncIterator
from pydantic import BaseModel, ConfigDict, Field
from .enums import *
from .openai_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    ChatCompletionUsage,
)
from .context import TenantContext


class RouterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    tenant: TenantContext
    request: ChatCompletionRequest  # sanitized; `fluxgate` field already stripped
    deadline_seconds: float = 60.0
    preferred_provider: ProviderName | None = None


class RouteAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName
    model_id: str
    started_at: datetime
    latency_ms: float
    http_status: int | None = None
    failure: RouteFailureKind | None = None
    retry_safe: bool = False
    circuit_state_at_start: CircuitState
    retry_after_seconds: float | None = None


class ProviderHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName
    circuit_state: CircuitState
    consecutive_failures: int
    cooldown_until: datetime | None = None
    last_success_at: datetime | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None


class RouterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: ChatCompletionResponse
    provider: ProviderName
    model_served: str
    usage: ChatCompletionUsage | None = None
    attempts: list[RouteAttempt]
    ttft_ms: float | None = None


class RouterStream(BaseModel):
    """Handle for a streaming call. `chunks` is an async iterator; attempts is filled as it runs."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    provider: ProviderName
    model_served: str
    attempts: list[RouteAttempt]
    chunks: AsyncIterator[ChatCompletionChunk] = Field(exclude=True)
```

### 10.7 Gateway and Telemetry — `shared/contracts/gateway.py`, `telemetry.py`

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .enums import *
from .openai_models import ChatCompletionResponse, ChatCompletionUsage
from .cache import CacheResult, StoreDecision
from .guardrails import GuardrailResult, ResponseScanResult
from .router import RouteAttempt


class StageTimings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_ms: float = 0
    ratelimit_ms: float = 0
    parse_ms: float = 0
    l1_ms: float = 0
    guardrails_in_ms: float = 0
    l2_ms: float = 0
    router_overhead_ms: float = 0
    upstream_ms: float = 0
    ttft_ms: float | None = None
    guardrails_out_ms: float = 0
    total_ms: float = 0


class ErrorInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    http_status: int
    type: str  # OpenAI-style: invalid_request_error, rate_limit_error, api_error …
    code: str  # fluxgate_policy_block, fluxgate_no_healthy_provider, …
    message: str  # never contains sensitive content


class GatewayResponse(BaseModel):
    """Final per-request envelope assembled by gateway/pipeline.py."""

    model_config = ConfigDict(extra="forbid")
    request_id: str
    tenant_id: str
    key_id: str
    served_from: Literal["l1", "l2", "provider", "error"]
    model_requested: str
    model_served: str | None = None
    provider: ProviderName | None = None
    streamed: bool = False
    status_code: int = 200
    body: ChatCompletionResponse | None = (
        None  # None for streamed (assembled copy not retained) / errors
    )
    headers: dict[str, str] = Field(default_factory=dict)  # X-FluxGate-*
    cache: CacheResult
    store: StoreDecision | None = None
    guardrail_in: GuardrailResult | None = None
    guardrail_out: ResponseScanResult | None = None
    attempts: list[RouteAttempt] = Field(default_factory=list)
    usage: ChatCompletionUsage | None = None
    tokens_saved: int = 0
    cost_saved_usd_est: float = 0.0
    timings: StageTimings = Field(default_factory=StageTimings)
    error: ErrorInfo | None = None


class RequestTrace(BaseModel):
    """Persisted subset (no bodies, no raw sensitive values). Built from GatewayResponse."""

    model_config = ConfigDict(extra="forbid")
    request_id: str
    tenant_id: str
    key_id: str
    created_at_unix_ms: int
    model_requested: str
    model_served: str | None
    provider: ProviderName | None
    served_from: str
    streamed: bool
    status_code: int
    cache_outcome: CacheOutcome
    similarity: float | None
    near_miss_similarity: float | None
    bypass_reason: CacheBypassReason | None
    decision: Decision | None
    risk_score: float | None
    finding_summary: dict[str, int]
    redaction_count: int
    prompt_tokens: int | None
    completion_tokens: int | None
    tokens_saved: int
    cost_saved_usd_est: float
    timings: StageTimings
    attempts_summary: list[dict[str, str | int | float | None]]
    prompt_sha256: str
    prompt_chars: int
    sanitized_preview: str | None = None  # ≤ 80 chars of SANITIZED text; null if disabled


class SecurityAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    request_id: str
    tenant_id: str
    key_id: str
    created_at_unix_ms: int
    stage: GuardrailStage
    decision: Decision
    finding_type: FindingType
    rule_id: str
    severity: Severity
    masked_preview: str | None
    policy_name: str
    policy_version: str
```

### 10.8 Protocols (integration seams) — `shared/contracts/protocols.py`

```python
from typing import Protocol, Any, AsyncIterator, runtime_checkable
from .context import RequestContext, TenantContext
from .openai_models import *
from .guardrails import GuardrailResult, ResponseScanResult, Finding
from .cache import CacheResult, CacheStoreRequest, StoreDecision, CacheKeys
from .router import RouterRequest, RouterResult, RouterStream, ProviderHealth
from .telemetry import RequestTrace, SecurityAuditEvent


class RedactionVault(Protocol):
    def restore(self, text: str) -> str: ...  # placeholder → original; request-scoped
    def __len__(self) -> int: ...


class StreamFlush(Protocol):
    text: str
    findings: list[Finding]


class StreamRedactor(Protocol):
    """One instance per streamed response (per choice index). Not thread-safe by design."""

    def feed(self, delta_text: str) -> str: ...  # returns text SAFE to emit now (may be "")
    def flush(self) -> StreamFlush: ...  # call once at end of stream
    @property
    def findings(self) -> list[Finding]: ...


@runtime_checkable
class GuardrailEngine(Protocol):
    @property
    def policy_version(self) -> str: ...
    async def inspect_inbound(
        self, ctx: RequestContext, request: ChatCompletionRequest
    ) -> GuardrailResult: ...
    def new_stream_redactor(
        self, ctx: RequestContext, inbound: GuardrailResult
    ) -> StreamRedactor: ...
    async def scan_response(
        self, ctx: RequestContext, response: ChatCompletionResponse, inbound: GuardrailResult
    ) -> ResponseScanResult: ...


@runtime_checkable
class CacheEngine(Protocol):
    async def lookup_exact(
        self, ctx: RequestContext, request: ChatCompletionRequest, policy_version: str
    ) -> CacheResult: ...  # step [4]
    async def lookup_semantic(
        self,
        ctx: RequestContext,
        sanitized: ChatCompletionRequest,
        inbound: GuardrailResult,
        keys: CacheKeys,
    ) -> CacheResult: ...  # step [6]
    async def maybe_store(self, req: CacheStoreRequest) -> StoreDecision: ...  # step [9]
    async def invalidate(
        self,
        tenant_id: str,
        *,
        entry_id: str | None = None,
        model: str | None = None,
        all_entries: bool = False,
    ) -> int: ...
    async def stats(self, tenant_id: str) -> dict[str, Any]: ...


@runtime_checkable
class Router(Protocol):
    async def complete(self, req: RouterRequest) -> RouterResult: ...
    async def stream(self, req: RouterRequest) -> RouterStream: ...
    def health(self) -> list[ProviderHealth]: ...


class TelemetrySink(Protocol):
    def emit_trace(self, trace: RequestTrace) -> None: ...  # non-blocking enqueue
    def emit_audit(self, event: SecurityAuditEvent) -> None: ...


class Embedder(Protocol):
    dim: int

    async def embed(self, text: str) -> "numpy.ndarray": ...  # L2-normalized float32[384]
```

---

## 11. Contract Change Control

1. **Freeze point:** contracts are frozen at end of Phase 1 (`v1.0.0`, git tag `contracts-v1.0.0`).
2. **Additive only** afterwards. Removing/renaming a field or changing a type = **breaking** → needs both developers, a version bump (`2.0.0`), and a migration note.
3. **Snapshot test:** `tests/contract/test_schema_snapshot.py` dumps `model_json_schema()` of every contract to `tests/contract/snapshots/`; CI fails on diff unless the snapshot was updated in a `contract-change` PR.
4. **Fake-conformance test:** `FakeGuardrailEngine`/`FakeCacheEngine`/`FakeRouter` (in `shared/testing/`) must pass the same protocol conformance suite as the real implementations, so Stage-3 integration surprises are caught early.
5. **Never** add business logic to contract modules (validators for format/ranges only).

## 12. Error Mapping (OpenAI-Compatible Envelope)

```json
{ "error": { "message": "…", "type": "invalid_request_error", "param": null, "code": "fluxgate_policy_block" } }
```

| Internal condition | HTTP | `type` | `code` |
|---|---|---|---|
| Missing/invalid `fgx-` key | 401 | `invalid_request_error` | `invalid_api_key` |
| Key revoked/disabled | 403 | `invalid_request_error` | `fluxgate_key_disabled` |
| Model not allowed for key | 403 | `invalid_request_error` | `model_not_allowed` |
| Malformed body | 400 | `invalid_request_error` | `invalid_request` |
| Guardrail BLOCK | 400 | `invalid_request_error` | `fluxgate_policy_block` |
| Guardrail unavailable (strict) | 503 | `api_error` | `fluxgate_guardrail_unavailable` |
| Rate limit | 429 | `rate_limit_error` | `rate_limit_exceeded` |
| No healthy provider | 503 | `api_error` | `fluxgate_no_healthy_provider` |
| Upstream 4xx (client-side error) | pass-through status | pass-through | pass-through (message sanitized) |
| Gateway timeout | 504 | `api_error` | `fluxgate_upstream_timeout` |

Response headers on every reply: `X-FluxGate-Request-Id`, `X-FluxGate-Cache` (`HIT-L1|HIT-L2|MISS|BYPASS`), `X-FluxGate-Provider` (when applicable), `X-FluxGate-Similarity` (L2 hit), `X-FluxGate-Risk` (0–1, 2 decimals). Debug headers can be disabled per tenant.

---

## 13. Open Questions for Review (Answer Before Phase 1 Closes)

1. Approve/veto ADR-01 … ADR-15.
2. License: MIT vs Apache-2.0.
3. Dashboard stack: HTMX + Jinja2 + Chart.js (no Node, recommended) vs React/Vite (more resume polish, ~1–2 extra weeks).
4. Default `on_internal_error`: `block` (recommended) vs `allow`.
5. Persist sanitized prompt preview (80 chars) in request logs by default, or hash-only? (Recommended: preview on in dev, off in `strict`.)
