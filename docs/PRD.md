# FluxGate — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Status | DRAFT v1.0 — locked decisions in `DECISIONS.md` (D-001…D-008) |
| Owners | Member 1 (security, cache, benchmarks) · Member 2 (gateway, router, dashboard) |
| Related | `ARCHITECTURE_BLUEPRINT.md` (structure/contracts), `TRD.md` (how), `UI_UX_SPEC.md`, `BACKEND_SCHEMA.md` |

> **Reading rule:** every numeric target in this PRD is an **engineering target** (a goal we design toward). It becomes a **proven result** only when a committed benchmark report says so (Gate 4). The tables in §7 carry a *Status* column that starts as `Not measured` for every row.

---

## 1. Vision

**FluxGate is the drop-in security-and-efficiency layer for LLM apps that run on free or rate-limited APIs.** Change one line (`base_url`), and the app gains: repeat/paraphrase answers served from a local cache, automatic failover between providers, and PII/secret/prompt-injection controls applied *before* data leaves the machine — with a dashboard that shows exactly what happened and why.

## 2. Problem Statement

Building our Hybrid-Search RAG system exposed four production-style problems that every small AI app hits:

| # | Problem | Consequence |
|---|---|---|
| P-1 | Free-tier providers (Groq, OpenRouter, NVIDIA NIM) enforce tight rate limits | App stalls, 429 errors, demos break |
| P-2 | Repeated and near-identical questions are re-sent to the LLM | Wasted quota, tokens, latency |
| P-3 | Raw document chunks and user text go to third-party APIs | PII/secret leakage; indirect prompt injection via retrieved documents (OWASP LLM01/LLM02) |
| P-4 | A single provider outage or 5xx interrupts the application | No resilience |

Each application re-implementing caching, retries, redaction and key handling is wasteful and error-prone. FluxGate solves them once, at the infrastructure layer.

## 3. Personas and Stories

| Persona | Needs |
|---|---|
| **App developer** (our Hybrid RAG; any chatbot/agent builder) | One-line integration; no behavior change except speed/resilience; clear errors |
| **Operator** (the student running it locally) | Free to run; visibility into hit rate, failures, quota; easy key management |
| **Security reviewer** | Evidence of what was redacted/blocked, without the dashboard itself leaking secrets |

Key stories (P0):
- *As an app developer, I set `base_url=http://localhost:8000/v1` and my existing OpenAI SDK code works, streaming included.*
- *As an operator, when Groq returns 429, my request still succeeds via another provider and I can see that in the dashboard.*
- *As an app developer, my second identical question returns in milliseconds and consumes zero provider quota.*
- *As a security reviewer, I can see that an email and API key in a prompt were replaced by placeholders before the provider call, and that nothing sensitive is stored.*
- *As an operator, I can create/revoke `fgx-` keys with per-key rate limits, and a leaked DB doesn't reveal usable keys.*

## 4. Constraints — **Zero-Cost Project (D-006)**

FluxGate must be buildable, runnable, tested, benchmarked and demoed at **₹0 / $0**.

| Area | Rule |
|---|---|
| Software | Only open-source/free tools (Python, FastAPI, FAISS, SQLite, HTMX, Chart.js, pytest…). No paid SaaS. |
| LLM APIs | **Free tiers only**: Groq free, OpenRouter `:free` models, NVIDIA NIM free credits/limits. **Do not add payment methods** to any provider account. |
| Guard against accidental spend | `zero_cost_mode: true` (default) → router only dispatches to models flagged `is_free: true` in `model_aliases`; any alias without the flag is refused with a clear error. Provider API keys are the only credential and no billing is attached. |
| Free-quota protection | Per-provider outbound limiter (config RPM/RPD caps below the real limits) so FluxGate itself can't burn a daily quota; per-key `daily_request_cap`; playground defaults to **dry-run** (no provider call). |
| Embeddings / detection | Local only (MiniLM on CPU; regex/checksum rules). No hosted embedding or moderation API. |
| Hosting | Local machine / Docker on laptop. No cloud VM. Demo = screen recording + reproducible `docker compose up`. |
| CI | GitHub Actions on a **public** repo (free minutes). No paid runners. Live-provider tests are manual-only. |
| Benchmarks | Bulk and overhead measurements use `mock_upstream` (free, deterministic). Real-provider runs are **small, repeated across days** within free limits (D-008). LLM-as-judge for false-hit labelling is optional and, if used, runs on free tier within quota; human labelling by the two members is the default. |
| Storage | SQLite file + RAM FAISS; no managed DB/vector DB. |
| "Cost saved" metric | Shown as an **estimate of equivalent paid-API cost avoided** plus **free-tier quota saved** (provider calls/tokens not spent). The UI labels it "estimate" and never implies real money was spent or saved. |

## 5. Goals and Non-Goals

### Goals
1. **G1 Compatibility:** standard OpenAI SDK works via `base_url` change only (JSON + SSE).
2. **G2 Efficiency:** measurable reduction in provider calls, tokens and latency on repeat/paraphrase workloads, without serving wrong answers.
3. **G3 Resilience:** automatic provider failover with a circuit breaker; no duplicate/spliced responses.
4. **G4 Security:** inbound injection/context-injection risk scoring; PII/secret redaction before egress; safe streaming redaction; zero raw sensitive data in logs/DB.
5. **G5 Isolation:** no cross-tenant cache leakage, ever.
6. **G6 Observability:** trace-level explainability (why hit/miss, why blocked, why failed over).
7. **G7 Independence:** FluxGate has no dependency on the Hybrid RAG codebase; RAG is a benchmark client.
8. **G8 Honesty:** every performance/security claim is backed by committed benchmark data.

### Non-Goals (explicit)
- Guaranteeing prompt-injection prevention (we provide **risk assessment** only).
- Content moderation / toxicity / hallucination detection.
- Endpoints other than `/v1/chat/completions` and `/v1/models` (no embeddings, images, audio, Assistants, Responses API) in MVP.
- Multi-process / HA / horizontal scaling; Redis; Kubernetes (single process by ADR-09).
- Billing, invoicing, payments, or real-money cost accounting.
- Fine-grained user management/SSO (single admin token for the dashboard).
- Name/address PII detection via NER (P1 research item).
- Anthropic/OpenAI/Gemini native adapters (MVP = Groq, OpenRouter, NVIDIA NIM).
- Mobile apps; public SaaS hosting.

## 6. Requirements

Priority: **P0** = required for v1.0; **P1** = planned enhancement after v1.0 (only if time permits). Owner: M1 / M2 / S (shared).

### 6.1 Member 1 — Guardrails (`guardrails/`)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| GR-01 | Normalize text (NFKC, zero-width/bidi strip, homoglyph fold, bounded decode-probe) before scanning | P0 | M1 |
| GR-02 | Rule-based prompt-injection/jailbreak scoring over user, system, tool and assistant messages; output `risk_score` ∈ [0,1] with rule IDs | P0 | M1 |
| GR-03 | Configurable decisions: `allow / warn / block` by thresholds per policy; named policies (`default`, `strict`) | P0 | M1 |
| GR-04 | **Context/indirect-injection inspection** of `fluxgate.retrieved_context` chunks and of untrusted text (tool results, document-like blocks) | P0 | M1 |
| GR-05 | PII detection: email, phone (incl. India formats), **Aadhaar (Verhoeff-validated)**, **PAN (structure-validated)**, payment card (Luhn) | P0 | M1 |
| GR-06 | Secret detection: API keys/tokens for AWS, GitHub, Groq, OpenRouter, NVIDIA, OpenAI-style, JWT, PEM private keys, `fgx-` keys, `key=value` secrets | P0 | M1 |
| GR-07 | Egress redaction: replace detections with request-scoped placeholders **before** any provider call; vault in RAM only | P0 | M1 |
| GR-08 | Optional placeholder restoration in responses per type policy | P0 | M1 |
| GR-09 | Response scanner (non-stream): redact/warn/block secrets & PII emitted by the model | P0 | M1 |
| GR-10 | **SSE sliding-window `StreamRedactor`**: secrets/placeholders split across chunks never leak; bounded hold-back | P0 | M1 |
| GR-11 | Configurable per-type actions (`allow/warn/redact/block`) and custom regex patterns (linear-time validated) | P0 (types) / P1 (custom patterns UI) | M1 |
| GR-12 | Fail-safe behavior on internal error/timeouts (`block` default) | P0 | M1 |
| GR-13 | Findings contain masked previews only; no raw values anywhere | P0 | M1 |
| GR-14 | Embedding-kNN attack-phrase scorer and/or small classifier as second opinion | P1 | M1 |
| GR-15 | Hot-reload policy files with new `policy_version` | P1 | M1 |
| GR-16 | Non-English injection coverage beyond a small Hindi-transliteration sample | P1 | M1 |

### 6.2 Member 1 — Cache (`cache/`)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| CA-01 | L1 exact cache: SHA-256 over canonical request + tenant + policy version; in-memory LRU backed by SQLite | P0 | M1 |
| CA-02 | L2 semantic cache: local MiniLM embeddings, FAISS inner-product on normalized vectors, initial threshold `> 0.92` | P0 | M1 |
| CA-03 | L2 hit requires compat-fingerprint equality (model, system prompt, context hash, params, tools, response_format, policy version) and max_tokens sanity | P0 | M1 |
| CA-04 | **Tenant isolation**: tenant in every key; per-tenant FAISS indexes; optional `cache_scope` | P0 | M1 |
| CA-05 | Eligibility: cache only clean, complete, low-risk, no-PII, non-tool responses within temperature limits | P0 | M1 |
| CA-06 | Poisoning defenses (write-time and read-time) | P0 | M1 |
| CA-07 | TTL per entry, background sweeper, per-tenant max entries with LRU-style eviction | P0 | M1 |
| CA-08 | Persistence and index rebuild on restart | P0 | M1 |
| CA-09 | Near-miss reporting (best similarity below threshold, which compat component differed) | P0 | M1 |
| CA-10 | Manual invalidation API (by entry/model/tenant/all) | P0 | M1 |
| CA-11 | Stats API per tenant (entries, hits, bytes, hit rate) | P0 | M1 |
| CA-12 | Single-flight (collapse concurrent identical misses into one upstream call) | P1 | M1/M2 |
| CA-13 | Approximate (HNSW/IVF) index for > 100k vectors | P1 | M1 |
| CA-14 | Cache warm-up/import from file | P1 | M1 |

### 6.3 Member 1 — Integration & Benchmarks (`integration/benchmarks/`)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| BM-01 | RAG client adapter using only `base_url` + optional `extra_body.fluxgate` | P0 | M1 |
| BM-02 | `mock_upstream.py`: deterministic OpenAI-compatible provider with latency/failure injection | P0 | M1 |
| BM-03 | Workloads W1–W8 (Testing Guide §5.2) committed with seeds | P0 | M1 |
| BM-04 | Before/after latency, hit-rate, token-savings, overhead benchmarks with reproducible reports | P0 | M1 |
| BM-05 | Security benchmark: detection recall/precision/FPR; PII/secret redaction recall; leakage = 0 check | P0 | M1 |
| BM-06 | L2 threshold sweep and false-hit analysis | P0 | M1 |
| BM-07 | Provider-free-tier-aware run plan (small real-provider runs, multi-day) | P0 | M1 |

### 6.4 Member 2 — Gateway (`gateway/`)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| GW-01 | `POST /v1/chat/completions`, OpenAI-compatible JSON, error envelope, response headers | P0 | M2 |
| GW-02 | SSE streaming (`stream=true`), `stream_options.include_usage`, `[DONE]`, disconnect handling | P0 | M2 |
| GW-03 | `GET /v1/models` listing aliases visible to the key | P0 | M2 |
| GW-04 | Virtual keys `fgx-…`: create/list/revoke/rotate; HMAC-hashed at rest; raw key shown once | P0 | M2 |
| GW-05 | Per-key token-bucket rate limiting (`Retry-After`), `daily_request_cap` | P0 | M2 |
| GW-06 | Pipeline orchestration per Blueprint §4 using M1/M2 protocols | P0 | M2 |
| GW-07 | Streaming tee-and-store, stream cache replay, no store on partial/disconnect | P0 | M2 |
| GW-08 | Tenant model: key → tenant; tenant-level settings | P0 | M2 |
| GW-09 | Telemetry queue + batched writer; audit events; never blocks request path | P0 | M2 |
| GW-10 | `/healthz`, `/readyz` | P0 | M2 |
| GW-11 | Request size/shape limits (body ≤ 1 MB default, ≤ 256 messages) | P0 | M2 |
| GW-12 | Token-per-minute limiting | P1 | M2 |
| GW-13 | `Idempotency-Key` support | P1 | M2 |
| GW-14 | Prometheus `/metrics` endpoint | P1 | M2 |

### 6.5 Member 2 — Router (`router/`)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| RT-01 | Provider adapters: Groq, OpenRouter, NVIDIA NIM (JSON + streaming), error normalization | P0 | M2 |
| RT-02 | Logical model aliases with per-provider mapping; `is_free` flag | P0 | M2 |
| RT-03 | **Zero-cost mode** enforcement (free models only) | P0 | M2 |
| RT-04 | Priority + health-aware provider selection and automatic fallback | P0 | M2 |
| RT-05 | Circuit breaker `CLOSED/OPEN/HALF_OPEN` with configurable thresholds/recovery windows | P0 | M2 |
| RT-06 | Handle 429 (cooldown honoring `Retry-After`), 5xx, timeouts, connect errors | P0 | M2 |
| RT-07 | Retry/failover only when safe (ADR-08) | P0 | M2 |
| RT-08 | Per-provider outbound limiter protecting free quotas | P0 | M2 |
| RT-09 | Manual provider disable/enable and breaker reset | P0 | M2 |
| RT-10 | Latency-aware selection (EWMA) | P1 | M2 |
| RT-11 | Hedged requests | Non-goal | — |

### 6.6 Member 2 — Dashboard (`dashboard/`)

| ID | Requirement | Pri | Owner |
|---|---|---|---|
| DB-01 | **Overview & Live Telemetry** view | P0 | M2 |
| DB-02 | **Provider Health & Routing** view | P0 | M2 |
| DB-03 | **Request Trace Inspector & Security Audit Logs** view | P0 | M2 |
| DB-04 | **Virtual Key Manager & Settings** view | P0 | M2 |
| DB-05 | **Red-Team & Cache Playground** (dry-run default) | P0 | M2 |
| DB-06 | No external network requests; vendored assets; strict CSP | P0 | M2 |
| DB-07 | Admin auth (token → signed session cookie), CSRF protection | P0 | M2 |
| DB-08 | P1 expansion screens: Cache Explorer, Policy Editor, Alerts, Benchmark Viewer, CSV/JSON export | P1 | M2 |

### 6.7 Cross-Cutting (Shared)

| ID | Requirement | Pri |
|---|---|---|
| XC-01 | Contracts per Blueprint §10, versioned, additive-only after Gate 1 | P0 |
| XC-02 | SQLite WAL schema per `BACKEND_SCHEMA.md`, forward-only migrations | P0 |
| XC-03 | Redacting logger; canary-secret leak test in CI | P0 |
| XC-04 | CI: lint, types, import-linter, unit, contract, security, gitleaks (free runners) | P0 |
| XC-05 | Docker image + compose (M2); runs without paid services | P0 |
| XC-06 | Apache-2.0 license; `SECURITY.md` with limitations | P0 |
| XC-07 | PostgreSQL-compatible schema design (no PG runtime in MVP) | P0 (design) / P1 (runtime) |

## 7. Acceptance Criteria and Targets

**Legend — Status:** `Not measured` (initial) → `Measured ✅` / `Measured ❌ (reason)`. **Type:** *Target* = engineering target, *Gate* = must pass for the stated Gate, *Zero-tolerance* = any violation fails.

Hardware reference for latency targets: 4-core laptop CPU, ≥ 8 GB RAM, prompts ≤ 512 tokens, ≤ 50k vectors/tenant, warm process (Blueprint §6).

### 7.1 Latency and Overhead

| ID | Metric | Target | Method | Gate | Status |
|---|---|---|---|---|---|
| T-01 | L1 lookup latency (LRU hit) | p95 ≤ 2 ms | `StageTimings.l1_ms` in micro-bench | 2 | Not measured |
| T-02 | **L2 lookup latency** (embed + FAISS + compat) | **p95 ≤ 20 ms** | `tests/perf` + `verify_m1` V12 | 2 | Not measured |
| T-03 | Inbound guardrails latency (rules + PII + redact) | p95 ≤ 15 ms (≤ 40 ms for 8k-token RAG prompts) | micro-bench | 2 | Not measured |
| T-04 | Stream redactor per-chunk cost | p95 ≤ 0.5 ms/chunk | micro-bench | 2 | Not measured |
| T-05 | Gateway server time on L1 hit | p95 ≤ 10 ms | mock-upstream run | 4 | Not measured |
| T-06 | Gateway server time on L2 hit | p95 ≤ 55 ms | mock-upstream run | 4 | Not measured |
| T-07 | Added latency on cache miss (excl. upstream) | p95 ≤ 45 ms | W4 vs direct-to-mock | 4 | Not measured |
| T-08 | Added TTFT on streaming miss | p95 ≤ 45 ms | W8 | 4 | Not measured |

### 7.2 Cache Effectiveness and Correctness

| ID | Metric | Target | Method | Gate | Status |
|---|---|---|---|---|---|
| C-01 | Overall hit rate on W1 (repeat-heavy) | ≥ 90% of the theoretical maximum for that trace | measured vs max computable from trace | 4 | Not measured |
| C-02 | L2 hit rate on W2 (labelled should-hit paraphrases) | report; engineering target ≥ 50% at default threshold | W2 labels | 4 | Not measured |
| C-03 | **L2 false-hit rate** on W3 adversarial near-duplicates | ≤ 1% of L2 hits (n ≥ 200 hits labelled) | human labels (2 raters) | 4 | Not measured |
| C-04 | **Cross-tenant leakage** | **0 occurrences** | stateful property test (≥ 300 examples) + HTTP test | 2, 3 | Not measured |
| C-05 | Ineligible/unsafe responses cached | **0 occurrences** | eligibility + poisoning suites | 2 | Not measured |
| C-06 | Partial/aborted streams cached | **0 occurrences** | streaming tests | 3 | Not measured |
| C-07 | Provider calls avoided | = number of hits (reported) | `request_logs` | 4 | Not measured |
| C-08 | Tokens saved | reported as `Σ original usage.total_tokens of served hits` (estimate flagged if `tiktoken`) | W1/W2/W5 | 4 | Not measured |
| C-09 | Equivalent paid-API cost avoided | reported as estimate with committed price table | W1/W2/W5 | 4 | Not measured |

### 7.3 Resilience

| ID | Metric | Target | Method | Gate | Status |
|---|---|---|---|---|---|
| R-01 | Failover success while one provider is faulted (429/5xx/timeout) and ≥ 1 other healthy | ≥ 99% of requests succeed | W7 chaos | 3, 4 | Not measured |
| R-02 | Added latency on failed-over requests | report median/p95 | W7 | 4 | Not measured |
| R-03 | Breaker transitions correct | CLOSED→OPEN→HALF_OPEN→CLOSED exercised in tests | state-machine tests | 3 | Not measured |
| R-04 | Duplicate/spliced responses after mid-stream failure | **0** | streaming chaos test | 3 | Not measured |
| R-05 | 429 never counted as breaker failure; cooldown honors `Retry-After` | exact per TRD | unit tests | 3 | Not measured |

### 7.4 Security

| ID | Metric | Target | Method | Gate | Status |
|---|---|---|---|---|---|
| S-01 | PII/secret recall on golden sets (email, phone, Aadhaar, PAN, card, key formats) | ≥ 99% | `verify_m1` V2/V3 | 2 | Not measured |
| S-02 | PII detector false-positive rate on benign corpus | ≤ 1% per detector (reported) | V2 | 2 | Not measured |
| S-03 | **Raw canary reaching provider payload / logs / DB / traces** | **0** | upstream-capture + canary tests | 2, 3 | Not measured |
| S-04 | Stream redaction leakage under any chunking | **0** | property tests | 2 | Not measured |
| S-05 | Injection corpus detection recall (warn-or-block) | engineering target ≥ 85% on our corpus | V5 | 2 | Not measured |
| S-06 | Injection FPR on benign corpus (block decision) | ≤ 3% | V5 | 2 | Not measured |
| S-07 | Indirect-injection detection on planted-document set | reported; target ≥ 80% | V6 | 2 | Not measured |
| S-08 | Raw virtual key at rest | **0** (HMAC only) | DB scan test | 3 | Not measured |
| S-09 | ReDoS: 1 MB adversarial input | < 250 ms | V10 | 2 | Not measured |

*Claims policy:* detection results are always reported as **"N% of a K-sample corpus, M% false positives"** with corpus description; never as protection guarantees.

### 7.5 Compatibility and Operations

| ID | Metric | Target | Gate | Status |
|---|---|---|---|---|
| O-01 | Official `openai` Python SDK (sync/async/stream) works via `base_url` only | e2e green | 3 | Not measured |
| O-02 | Cold start from clean clone following README | ≤ 30 min | 3 | Not measured |
| O-03 | Gateway RSS at idle (model loaded) | report (target ≤ 1.5 GB) | 4 | Not measured |
| O-04 | 50 concurrent clients × 60 s smoke: error rate, no memory growth | 0 gateway-caused 5xx; flat memory | 3 | Not measured |
| O-05 | Total recurring cost to run/test/demo | **$0** | 4 | Not measured |

## 8. Success Metrics (Project-Level)

- v1.0 tagged with every §7 row marked Measured ✅ or Measured ❌ with reason.
- README + resume bullets quote only numbers present in `REPORT.md`.
- A recorded demo shows: SDK integration, cache hit (L1 and L2 with similarity), PII redaction, injection block, failover with breaker transitions.
- Hybrid RAG runs through FluxGate unchanged except `base_url`.

## 9. Assumptions and Dependencies

- Free tiers of Groq / OpenRouter / NVIDIA NIM remain available; limits and model IDs may change (read from config).
- Team machines have ≥ 8 GB RAM; MiniLM downloads once (~90 MB) then runs offline.
- Hybrid RAG exposes a public entry point that accepts an OpenAI-compatible `base_url`.
- GitHub free features (public repo, Actions, secret scanning) available.

## 10. Risks (Product Level)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Free-tier quotas exhaust during benchmarking | High | Medium | Mock upstream for bulk; multi-day small runs; per-provider outbound caps |
| L2 false hits erode trust | Medium | High | Compat fingerprint, threshold tuning on adversarial set, near-miss telemetry |
| Rule-based injection detection misses novel attacks | High | Medium | Honest recall reporting; layered controls; P1 second-opinion scorer |
| Scope creep | Medium | High | P1 list frozen; additions need both approvals |
| Streaming complexity (redaction + cache + failover) | Medium | High | Property tests; ADR-07/08 constraints; Phase 2 `stream-sim` |

## 11. Release Criteria for v1.0

All Gate 4 conditions in the Roadmap, plus: every P0 requirement implemented and linked to a test; `SECURITY.md` limitations updated with measured gaps; zero-cost audit (no paid dependencies, no billing set up) checked off.

## 12. Glossary

**Tenant** — isolation boundary owning keys, cache entries, quotas. **Virtual key** — `fgx-…` credential issued by FluxGate. **Compat fingerprint** — hash of request properties that must match exactly for a semantic hit. **Near miss** — best semantic candidate below threshold. **Vault** — request-scoped RAM map of placeholder → original sensitive value. **Policy version** — content hash of the active guardrail policy.
