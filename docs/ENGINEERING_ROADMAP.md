# FluxGate — Engineering Roadmap, Ownership & Phase Gates

| Field | Value |
|---|---|
| Status | DRAFT v1.0 |
| Model | **Strict sequential**: Phase 1 → Phase 2 (Member 1 only) → Phase 3 (Member 2 only) → Phase 4 (joint) |
| Estimates | Effort in *focused working days* per person. **Estimates, not commitments** — re-baseline at each gate. |

---

## 1. Roles and File Boundaries

### Member 1 (Dev A) — AI Security, Semantic Cache & RAG Integration Lead

| Owns (may edit freely) | Must not edit without agreement |
|---|---|
| `guardrails/**` | `gateway/**`, `router/**`, `dashboard/**` |
| `cache/**` | `shared/contracts/**` (contract-change PR only) |
| `integration/**` | `Dockerfile`, `docker-compose.yml` |
| `config/policies/**` | |
| `tests/unit/guardrails/**`, `tests/unit/cache/**`, `tests/security/**` | |
| `scripts/verify_m1.py` | |

**Responsibilities:** inbound injection/context-injection scoring; PII/secret detection, redaction, request-scoped vault; response scanning; SSE sliding-window redactor; L1 exact cache; L2 FAISS semantic cache; tenant isolation; eligibility + poisoning defense; TTL sweeper; standalone CLIs and verification runner; Hybrid RAG benchmark harness and reports.

**Public surface (the only things Member 2 may import):**
`guardrails.build_guardrail_engine(settings) -> GuardrailEngine` and `cache.build_cache_engine(settings, db) -> CacheEngine`.

### Member 2 (Dev B) — Core Proxy, Resilience Router & Control Plane Lead

| Owns | Must not edit without agreement |
|---|---|
| `gateway/**` | `guardrails/**`, `cache/**`, `integration/**` |
| `router/**` | `shared/contracts/**` (contract-change PR only) |
| `dashboard/**` | `config/policies/**` |
| `Dockerfile`, `docker-compose.yml`, `config/providers.example.yaml` | |
| `tests/unit/gateway/**`, `tests/unit/router/**`, `tests/e2e/**` | |

**Responsibilities:** FastAPI app, OpenAI-compatible endpoint, SSE streaming and tee-and-store, virtual `fgx-` keys (HMAC-hashed), token-bucket rate limiting, provider adapters, model alias map, circuit breaker, retry/failover policy, telemetry queue + writer, aggregates, dashboard (4 MVP views), Docker packaging.

**Public surface (the only things Member 1 relies on):** the HTTP API, plus `TelemetrySink` writes for traces/audit (via the gateway).

### Shared (both approve)
`shared/**`, `docs/**`, root files, `.github/**`, `tests/contract`, `tests/perf`, `tests/integration`, `scripts/` (except `verify_m1.py`).

### Bug in the other member's module?
File a GitHub issue with a failing test; owner fixes. Emergency exception: non-owner may open a PR touching the module **only with the owner's written approval on the PR**.

---

## 2. Phase Overview

```
 PHASE 1            PHASE 2                       PHASE 3                          PHASE 4
 Docs + Contracts → Member 1 builds 100% of    →  Member 2 builds gateway/      →  Joint: Hybrid RAG integration
 + Scaffold         guardrails/ + cache/          router/ dashboard/ on real        + benchmarks + report
 (both)             (M2 does NOT code)            M1 code (M1 does NOT code)        (both)
 ~3–4 days each     ~18–22 days (M1)              ~20–24 days (M2)                  ~8–10 days each
       │                  │                              │                              │
    GATE 1             GATE 2                         GATE 3                         GATE 4
```

---

## 3. Phase 1 — Unified Docs & Shared Contracts (Both)

**Goal:** both developers can explain the whole system and the interfaces; the repo skeleton and CI exist.

| # | Task | Owner | Done when |
|---|---|---|---|
| 1.1 | Review and approve Batch 1–3 docs; resolve Blueprint §13 open questions | Both | Questions answered in `docs/DECISIONS.md` |
| 1.2 | Create GitHub repo, branch protection, CODEOWNERS, PR template | Both | See `GIT_AND_COLLAB_WORKFLOW.md` §2 |
| 1.3 | **Scaffold commit (only after all 3 batches approved):** folder tree with empty package `__init__.py`s, `shared/contracts/*` copied from Blueprint §10, starter files | Both (pair on Discord) | CI green |
| 1.4 | Fakes: `FakeGuardrailEngine`, `FakeCacheEngine`, `FakeRouter`, `FakeClock`; protocol conformance tests | M1 writes, M2 reviews | `tests/contract` green |
| 1.5 | Contract schema snapshot test | Both | Snapshot committed |
| 1.6 | Tooling: pre-commit, ruff, mypy, import-linter, gitleaks, CI | Both | CI runs all checks |
| 1.7 | Environments verified (`verify_env.py` green) incl. MiniLM offline | Both | Screenshot/log in PR |
| 1.8 | Provider accounts created; model IDs recorded in config comments | M2 (M1 optional) | Test 1-token call each |
| 1.9 | Tag `contracts-v1.0.0` | Both | Tag exists |

### GATE 1 — "Contracts frozen"
- [ ] All docs approved by both (PR approvals).
- [ ] `contracts-v1.0.0` tagged; snapshot test green.
- [ ] CI green on `main` (lint, types, import-linter, contract tests, gitleaks).
- [ ] Both machines pass `verify_env.py`.
- [ ] Both can walk through Blueprint §4 pipeline from memory on Discord (15-min mutual walkthrough).

---

## 4. Phase 2 — Member 1 Builds `guardrails/` + `cache/` (100%)

**Member 2 does not write application code in this phase.** Member 2's allowed work (non-code or prep): PR review of every M1 PR (read-only learning), provider account setup, collecting **golden provider fixtures** (recorded real JSON/SSE responses saved as files under `shared/testing/fixtures/providers/` via a PR), drafting dashboard wireframes in the UI spec, rehearsing the Phase 3 plan. This keeps Member 2 productive without violating the no-parallel-coding rule.

### Work packages (suggested order; each = 1+ PRs ≤ ~400 lines of diff)

| WP | Deliverable | Key tests | Est. days |
|---|---|---|---|
| **M1-0** | Package skeletons, `build_*` factory functions returning working-but-minimal engines, policy loader + `policy_version` hashing | policy load/validation, version stability | 1.5 |
| **M1-1** | `normalize.py` (NFKC, zero-width/bidi strip, homoglyph fold, bounded base64/hex decode-probe) | unit + hypothesis (idempotence) | 1.5 |
| **M1-2** | PII detectors + validators (email, phone incl. India formats, **Aadhaar w/ Verhoeff**, **PAN structure**, Luhn card) | golden positive/negative sets; false-positive corpus (UUIDs, order IDs, git SHAs, timestamps) | 2.5 |
| **M1-3** | Secret detectors (provider key formats incl. `fgx-`, `gsk_`, `sk-or-`, `nvapi-`, `AKIA`, `ghp_`, JWT, PEM blocks) + entropy heuristic with allowlist | canary tests; entropy FP corpus | 2 |
| **M1-4** | Redactor + request-scoped vault (placeholder `⟦FG:EMAIL:1⟧` style, collision-safe, overlap merge, restore) | round-trip property tests | 2 |
| **M1-5** | **StreamRedactor** (sliding window) | **chunk-split invariance property test** (§ Testing Guide), fuzz splits | 2.5 |
| **M1-6** | Injection rule engine + scorer (categories: instruction override, role/DAN jailbreak, prompt-leak, delimiter/encoding tricks, tool-abuse, exfil URLs/markdown images) | attack corpus recall; benign corpus FPR; per-rule unit tests | 3 |
| **M1-7** | Context/indirect-injection scan for `retrieved_context` and untrusted tool/RAG text | planted-injection documents | 1.5 |
| **M1-8** | `GuardrailEngine` assembly: decision logic (thresholds, per-type actions), degraded/strict modes, `ResponseScanner` | decision-matrix tests | 1.5 |
| **M1-9** | Canonicalization + keys (`exact_key`, `compat_hash`) + L1 (LRU + SQLite) | key stability, param-sensitivity tests | 2 |
| **M1-10** | `EmbeddingService` (thread pool, memo LRU) + per-tenant FAISS + L2 lookup with compat check + near-miss reporting | tenant isolation (hypothesis), threshold behavior, latency micro-bench | 3 |
| **M1-11** | Eligibility + poisoning defenses + TTL sweeper + eviction + invalidate | eligibility matrix, TTL via FakeClock, poisoning cases | 2 |
| **M1-12** | CLIs (`guardrails.cli`, `cache.cli`) + `scripts/verify_m1.py` standalone runner | runner produces `verify_m1_report.md/json` | 1.5 |
| **M1-13** | Hardening: log-leak canary test, ReDoS audit, fuzzing, perf budget run, docs (`guardrails/README`, `cache/README`), **handoff notes** | `tests/security/*`, `tests/perf/*` | 2 |

**Total ≈ 28 package-days upper bound; plan buffer for 18–22 focused days by merging small WPs.** If schedule slips, scope-cut order (never cut security tests): (1) entropy heuristic → P1, (2) custom-pattern support → P1, (3) CLI polish.

### Discord protocol in Phase 2
At the start of each WP, Member 1 shares screen ≥ 30 min; Member 2 reviews the PR live and approves in GitHub (see Git workflow doc §5). Each WP ends with a 5-min demo using the CLI.

### Deliverables at end of Phase 2
1. Merged `guardrails/` and `cache/` on `main`, tagged `v0.1.0-m1-complete`.
2. `python scripts/verify_m1.py` runs standalone (no gateway/router/dashboard code needed) and prints PASS/FAIL per acceptance criterion.
3. Measured (not claimed) micro-benchmark report for M1 stages, committed under `integration/benchmarks/reports/m1_micro/`.
4. Handoff package: `guardrails/README.md`, `cache/README.md`, usage snippets for the two `build_*` functions, known limitations list, threshold-tuning notes.

### GATE 2 — "M1 complete → M2 may start" (all must be true)
**Functional**
- [ ] Every Phase-2 WP merged; no open P0 bugs labelled `m1`.
- [ ] `verify_m1.py` all PASS on **both** developers' machines.
- [ ] Contract conformance suite passes with the real engines (same suite as the fakes).
**Quality**
- [ ] Coverage: `guardrails/` ≥ 90%, `cache/` ≥ 90% line; 100% of tenant-isolation and eligibility code paths.
- [ ] `mypy --strict` clean on `shared/`, `guardrails/`, `cache/`.
- [ ] Property tests green: tenant isolation, redaction round-trip, **stream chunk-split invariance**.
**Security**
- [ ] Canary-secret log-leak test green (nothing in logs/DB/traces).
- [ ] ReDoS audit: all regexes linear-time or length-bounded; 1 MB adversarial inputs finish < 250 ms.
- [ ] Attack corpus and benign corpus results recorded (numbers reported honestly, whatever they are).
**Performance (measured on M1's laptop, hardware recorded)**
- [ ] Stage micro-benchmarks recorded vs Blueprint §6 budgets. Misses are documented with a plan, not hidden. (Gate does not require every budget met; it requires *measurement and disclosure*. A budget miss > 2× on L2 lookup blocks the gate.)
**Handoff**
- [ ] Handoff checklist (Git workflow doc §7) signed by both in the merge PR.
- [ ] Member 2 has reviewed all M1 PRs and can run `verify_m1.py` and both CLIs.

---

## 5. Phase 3 — Member 2 Builds `gateway/` + `router/` + `dashboard/`

**Member 1 does not write application code in this phase.** Member 1's allowed work: reviewing M2 PRs, answering questions about M1 modules, fixing **bugs in `guardrails/`/`cache/`** reported with failing tests (owner fixes; tiny PRs), and non-code preparation for Phase 4 (query-set design on paper, dataset licence checks).

### Work packages

| WP | Deliverable | Key tests | Est. days |
|---|---|---|---|
| **M2-0** | App factory, settings, lifespan (builds M1 engines, warm-up), health/ready endpoints, DB migrations runner (`0001_init`) | startup/shutdown tests | 2 |
| **M2-1** | Virtual keys: generation (`fgx-` + CSPRNG), HMAC hashing, CRUD, revoke, in-mem key cache, auth dependency | key never logged/stored raw; timing-safe compare | 2 |
| **M2-2** | Token-bucket limiter per key (+ `Retry-After`), burst/refill config | FakeClock tests; concurrency | 1.5 |
| **M2-3** | Provider adapter base + Groq/OpenRouter/NIM adapters (non-stream first), error normalization, model alias map | respx with golden fixtures; OpenRouter 200-with-error case | 4 |
| **M2-4** | Circuit breaker + selector + retry policy (429 handling, `Retry-After`, jitter, ADR-08 rules) | state-machine tests with FakeClock; chaos scenarios | 3 |
| **M2-5** | `pipeline.py` non-stream path wired to **real** M1 engines (no mocks) + OpenAI error envelope + headers | integration tests incl. block/redact/L1/L2/miss | 3 |
| **M2-6** | Streaming: adapter SSE parsing, StreamRedactor wiring, tee-and-store, stream cache replay, disconnect handling | SSE tests; cancel tests; no-cache-on-partial | 4 |
| **M2-7** | Telemetry: queue, batch writer, audit events, aggregates (hit rate, savings, latency percentiles) | no-raw-secret test; backpressure test | 2.5 |
| **M2-8** | Dashboard 4 MVP views + playground (per UI/UX spec) | smoke tests; empty/error states | 5 |
| **M2-9** | OpenAI SDK e2e compatibility tests (sync, async, streaming), Docker image + compose | e2e green in CI with mock upstream | 2 |
| **M2-10** | Hardening, docs, load smoke, handoff notes for Phase 4 | locust smoke; `tests/integration/*` | 2 |

### Deliverables at end of Phase 3
1. Merged `gateway/`, `router/`, `dashboard/` on `main`, tag `v0.2.0-m2-complete`.
2. `docker compose up` yields a working gateway at `http://localhost:8000` with a seeded dev key.
3. The official `openai` Python SDK passes the e2e suite via `base_url` change only.
4. README quickstart verified by Member 1 from a clean clone (cold-start test).

### GATE 3 — "Gateway complete → joint benchmarking may start"
- [ ] All Phase-3 WPs merged; no open P0 bugs labelled `m2`.
- [ ] e2e: OpenAI SDK (sync + async + stream) green against the mock upstream **and** at least one real provider.
- [ ] Failover test: with provider A forced to 429/5xx/timeout, requests succeed via B; breaker transitions CLOSED→OPEN→HALF_OPEN→CLOSED observed in tests and dashboard.
- [ ] Streaming + cache: complete stream stored; aborted stream **not** stored; cached stream replays valid SSE ending in `[DONE]`.
- [ ] Security: raw key never in DB/logs; cross-tenant cache test via HTTP (two keys, two tenants) green; canary log-leak test green through the full stack.
- [ ] Dashboard: 4 views render with data, empty, loading and error states; no external network requests (CSP verified).
- [ ] Cold-start from clean clone by Member 1 succeeds in ≤ 30 min following README only.
- [ ] Coverage `gateway/` and `router/` ≥ 85%; `mypy` clean.

---

## 6. Phase 4 — Joint Hybrid RAG Integration & Benchmarking

| # | Task | Owner | Done when |
|---|---|---|---|
| 4.1 | RAG client adapter: point existing Hybrid RAG's OpenAI client `base_url` at FluxGate (no FluxGate imports in the RAG repo; optional `extra_body={"fluxgate":…}`) | M1 | RAG answers match baseline structure |
| 4.2 | Workload design: repeat-heavy, paraphrase-heavy, unique, RAG-with-context sets | M1 + M2 | Files committed with seeds |
| 4.3 | Mock-upstream overhead benchmark (isolates FluxGate cost) | M1 runs, M2 supports | JSON results committed |
| 4.4 | Real-provider before/after benchmark (baseline direct vs via FluxGate) | Both | JSON results + hardware + commit SHA |
| 4.5 | Security benchmark: injection corpus detection/FPR; PII redaction recall/precision; indirect injection with poisoned chunks | M1 | Report |
| 4.6 | Failover chaos benchmark (kill/slow provider mid-run) | M2 | Report |
| 4.7 | Threshold tuning: L2 threshold sweep → hit rate vs false-hit rate curve; decide default | M1 | Decision recorded |
| 4.8 | `REPORT.md`, README numbers, resume bullet drafts **using only measured values** | Both | Every number links to a result file |

### GATE 4 — "Release candidate"
- [ ] Every target in PRD is marked **Measured ✅ / Missed ❌ (with reason) / Not measured**.
- [ ] No claim in README/resume text without a result file + commit SHA.
- [ ] Reproducibility: `make bench` reproduces headline numbers within stated variance on a second machine.
- [ ] `SECURITY.md` limitations section updated with real measured gaps.
- [ ] Tag `v1.0.0`; demo video/GIF recorded (red-team playground + failover + cache hit).

---

## 7. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Phase 3 is the critical path and all on Member 2**; Member 1 idle | Schedule slip, uneven load | See Amendment A below; M1 does PR review + bug fixing + benchmark design. |
| Contract flaws discovered late in Phase 3 | Rework | `FakeEngine` conformance in Phase 1; additive-only changes; `contract-change` PR process. |
| M1 modules pass unit tests but fail inside streaming | Late surprise | Phase 2 includes `stream-sim` CLI feeding chunked SSE; chunk-split property test. |
| Free-tier provider limits / model churn disrupt benchmarks | Noisy numbers | Mock upstream for overhead; real-provider runs short, repeated, with variance reported. |
| L2 false hits (semantically close, different answer) | Correctness/trust | Compat fingerprint, high threshold, PAWS-style adversarial tests, near-miss telemetry. |
| Scope creep (Presidio, Redis, React, ANN indexes) | Never finishes | P1 list in PRD; any P0 addition needs both approvals. |
| Detection overclaiming | Credibility | "Risk score" wording everywhere; measured recall/FPR with corpus described. |
| Secrets leak via Discord stream or git | Account compromise | Screen-share rules, gitleaks, key rotation drill. |

### Recommended Amendments (**need your explicit approval; roadmap defaults to the strict original**)

- **Amendment A — benchmark harness prep during Phase 3.** Member 1 owns `integration/benchmarks/`, which does not overlap with any Member 2 file. Letting Member 1 build the harness against `mock_upstream.py` during Phase 3 shortens Phase 4 by ~4–5 days without any file-level parallel conflict. This deviates from "no parallel coding" in letter, not in spirit.
- **Amendment B — Phase 3 mid-point review.** At the end of M2-5 (non-stream pipeline on real M1 engines), a 60-minute joint review: any M1 behavior that hurts the gateway is fixed by M1 immediately, before streaming work starts.
- **Amendment C — Phase 2 "stub-free" insurance.** Add `tests/integration/test_pipeline_smoke.py` in Phase 1 using fakes; in Phase 3 it switches to real engines with no code change. Already implied; listed for visibility.

---

## 8. Definition of Done (Every PR, Every Phase)

1. Tests added/updated; CI green (lint, mypy, import-linter, unit, contract, gitleaks).
2. No contract change (or a labelled `contract-change` PR).
3. No raw secrets/PII in code, fixtures, logs, snapshots (fixtures use obviously-fake canaries).
4. Docstrings on public functions; module README updated if behavior changed.
5. Reviewed live on Discord (or async approval with notes) by the other member.
6. Performance-sensitive change includes a micro-benchmark delta in the PR description.

## 9. Communication Cadence

- Phase 2/3: 2–3 live sessions per week (≥ 1 hr), plus async PR comments.
- Weekly 15-min status: done / next / blockers / risks, appended to `docs/STATUS_LOG.md`.
- Decisions recorded in `docs/DECISIONS.md` (ADR-style, one paragraph each).
