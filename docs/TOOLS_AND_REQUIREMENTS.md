# FluxGate — Tools, Libraries, Accounts & Environment Setup

| Field | Value |
|---|---|
| Status | DRAFT v1.0 |
| Applies to | Both developers (identical environments) |

> **Version honesty note.** Versions below are **minimum known-good floors** (`>=`) plus a recommended major/minor line. External libraries move fast. On **Day 1 of Phase 1b**, run `uv lock` (or `pip-compile`) and **commit the lockfile**; from then on the lockfile — not this document — is the exact-version source of truth. Before pinning anything not listed as "floor", check with `uv pip index versions <pkg>` / the package's release page.

---

## 1. Required System Software

| Tool | Version | Needed by | Why / Notes |
|---|---|---|---|
| **Python** | **3.12** recommended (3.11 minimum) | both | `StrEnum`, `tomllib`, better async perf. Do not use 3.13+ until `faiss-cpu`/`torch` wheels are confirmed on your OS. |
| **uv** (Astral) | latest | both | Fast venv + resolver + lockfile. Alternative: `venv + pip-tools`. Pick **one** and write it in README. |
| **Git** | ≥ 2.40 | both | PR workflow, `git switch`, `git restore`. |
| **GitHub account + CLI (`gh`)** | latest | both | PRs, branch protection, CODEOWNERS, Actions CI. |
| **Docker Desktop / Engine + Compose v2** | ≥ 24 / v2 | M2 (primary), M1 (smoke) | Reproducible run; M1 does **not** need Docker for Stage 1. |
| **SQLite** | ≥ 3.40 (bundled with Python) + `sqlite3` CLI | both | WAL mode; `sqlite3 fluxgate.db ".schema"` for inspection. Optional GUI: *DB Browser for SQLite*. |
| **Node.js** | **Not required for MVP** | — | Dashboard is server-rendered (Jinja2 + HTMX) with vendored JS. Install Node only if you opt into React (Open Question #3 in the Blueprint). |
| **Discord** | desktop app | both | Live screen-share. See `GIT_AND_COLLAB_WORKFLOW.md` for what must never be on screen. |
| **Editor** | VS Code (+ Python, Ruff, Pylance, SQLite Viewer) or PyCharm | both | Enable "format on save" with Ruff. |
| **curl / httpie**, **jq** | any | both | Manual endpoint and SSE testing (`curl -N`). |
| **gitleaks** | ≥ 8 | both | Pre-commit secret scanning. |
| **OS** | Linux / macOS / Windows 11 with **WSL2 (recommended on Windows)** | both | `faiss-cpu` and `torch` wheel availability is best on Linux/WSL2. Do all development inside WSL2 if on Windows. |
| **Hardware** | ≥ 8 GB RAM, ≥ 4 cores, 5 GB free disk | both | PyTorch + model ≈ 1–2 GB installed. Record CPU model/RAM in every benchmark report. |

---

## 2. Python Library Stack

### 2.1 Runtime dependencies (MVP — deliberately minimal)

| Package | Floor | Used by | Justification |
|---|---|---|---|
| `fastapi` | ≥ 0.115 | M2 | Async web framework, OpenAPI docs for free. |
| `uvicorn[standard]` | ≥ 0.30 | M2 | ASGI server (uvloop, httptools). Run with `--workers 1` (ADR-09). |
| `httpx` | ≥ 0.27 | M2 | Async upstream client with streaming and per-phase timeouts; also the test client. |
| `pydantic` | ≥ 2.8 | all | Contracts (v2 only; Rust core = fast validation). |
| `pydantic-settings` | ≥ 2.4 | all | Typed settings from env + YAML. |
| `pyyaml` | ≥ 6.0 | M1/M2 | Policy and provider config. |
| `aiosqlite` | ≥ 0.20 | all | Async SQLite access (WAL). |
| `orjson` | ≥ 3.10 | M1/M2 | Fast JSON for canonicalization, SSE encoding, cache blobs. |
| `structlog` | ≥ 24.1 | all | Structured logs + the mandatory redacting processor. |
| `numpy` | ≥ 1.26, < 3 | M1 | Vector math, FAISS I/O. |
| `faiss-cpu` | ≥ 1.8 | M1 | L2 similarity search (`IndexFlatIP` + `IndexIDMap`). |
| `sentence-transformers` | ≥ 3.0 | M1 | Loads `all-MiniLM-L6-v2`. |
| `torch` (**CPU build**) | ≥ 2.3 | M1 | Backend for embeddings; install from CPU index to avoid ~2 GB CUDA wheels. |
| `tiktoken` | ≥ 0.7 | M1/M2 | Token counting for savings estimates (`cl100k_base`/`o200k_base` approximation; note it is an *estimate* for non-OpenAI models). Needs one-time encoding download → vendor via `scripts/download_models.py` for offline use. |
| `ulid-py` or `python-ulid` | latest | M2 | Sortable request IDs. |
| `jinja2` | ≥ 3.1 | M2 | Dashboard templates. |
| `python-multipart` | ≥ 0.0.9 | M2 | Dashboard form posts (key creation). |
| `typer` | ≥ 0.12 | M1/M2 | CLIs (`guardrails.cli`, `cache.cli`, `scripts/*`). |
| `rich` | ≥ 13 | M1/M2 | Readable CLI/verification output. |

**Deliberately excluded in MVP** (to avoid over-engineering): Redis, Celery, Kafka, SQLAlchemy/Alembic, Presidio/spaCy, LangChain, Kubernetes, vector DBs. Rationale: single process, regex + checksum validators for PII, plain numbered SQL migrations. P1 may add Presidio (spaCy NER) for names/addresses — it adds ~500 MB and 20–60 ms, which would break the budget.

### 2.2 Dev / test dependencies

| Package | Floor | Purpose |
|---|---|---|
| `pytest` | ≥ 8 | Test runner |
| `pytest-asyncio` | ≥ 0.23 | Async tests (`asyncio_mode = "auto"`) |
| `pytest-cov` | ≥ 5 | Coverage gates |
| `pytest-benchmark` | ≥ 4 | Micro-benchmarks (stage latency) |
| `hypothesis` | ≥ 6.100 | Property tests (tenant isolation, redaction round-trips, chunk-split invariance) |
| `respx` | ≥ 0.21 | Mock `httpx` upstream providers |
| `freezegun` or own `FakeClock` | — | TTL / circuit-breaker timing (own clock preferred; `shared/testing/fake_clock.py`) |
| `faker` | ≥ 25 | Synthetic PII incl. `en_IN` locale |
| `openai` | ≥ 1.40 | **Compatibility tests only** — proves the real OpenAI SDK works against FluxGate |
| `ruff` | ≥ 0.5 | Lint + format (single tool) |
| `mypy` | ≥ 1.10 | Type check (`strict` on `shared/`, `cache/`, `guardrails/`) |
| `import-linter` | ≥ 2.0 | Enforce module boundary rules (Blueprint §5) |
| `pre-commit` | ≥ 3.7 | Hooks: ruff, mypy (fast), gitleaks, end-of-file |
| `locust` *(optional)* | ≥ 2.29 | Load tests for M2 |
| `scikit-learn` *(P1 optional extra)* | ≥ 1.4 | Only if the embedding-based injection head is adopted |

### 2.3 Packaging layout (`pyproject.toml` — written in Batch 3)

- Project name `fluxgate`, `requires-python = ">=3.11"`.
- Dependency groups: core (above), `[project.optional-dependencies]` `m1`, `m2`, `dev`, `bench`.
- CPU torch via `[tool.uv.sources]`/index config; documented fallback: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.
- Tool config for ruff, mypy, pytest, import-linter lives in the same file.

---

## 3. Frontend Stack (Dashboard — No Build Step)

| Asset | Version line | Why |
|---|---|---|
| **HTMX** | 2.0.x | Partial page updates, polling for live KPIs without a JS framework. |
| **Alpine.js** | 3.14.x | Tiny reactivity for tabs, drawers, copy buttons. |
| **Chart.js** | 4.4.x | Line/bar/doughnut charts, small bundle. |
| **Plain CSS** (custom properties, grid/flex) | — | Dark/light theme; no Tailwind build step. |

- **Vendor all JS/CSS into `dashboard/static/vendor/`** (no CDN at runtime → works offline, no third-party requests from a security tool's UI).
- Record the exact versions + SHA-256 of each vendored file in `dashboard/static/vendor/VENDOR.md`.
- Set a strict CSP on dashboard routes (`default-src 'self'`; no inline scripts except nonce'd).
- If React is chosen instead: Node 20 LTS, Vite 5, React 18, TypeScript 5; add `dashboard/frontend/` and a Docker multi-stage build.

---

## 4. Models and Data Downloads

| Asset | Source | Size | Used for | Notes |
|---|---|---|---|---|
| **`sentence-transformers/all-MiniLM-L6-v2`** | Hugging Face | ~90 MB | L2 embeddings (384-dim, max 256 word-pieces) | Apache-2.0. **Pin the commit hash** (revision) in `scripts/download_models.py`; store under `models/all-MiniLM-L6-v2/` (git-ignored). After download set `HF_HUB_OFFLINE=1` to prevent surprise network calls. |
| tiktoken encodings | OpenAI public blob | ~2 MB | Token estimates | Pre-fetch once, store under `models/tiktoken/`, set `TIKTOKEN_CACHE_DIR`. |
| **Injection detection — P0** | **No model.** Rule corpus in `guardrails/injection/corpus/*.yaml` authored by M1 | KBs | Rule engine + weighted scoring | Fast, explainable, zero extra download. |
| Injection detection — **P1 candidates** (benchmark before adopting; must fit budget) | (a) kNN against a small embedding index of known attack phrases using the *same* MiniLM (no extra model); (b) a small prompt-injection classifier from Hugging Face (e.g., ProtectAI's DeBERTa-v3 *small* variant if available — **verify name, license and CPU latency before use**); (c) Meta Prompt-Guard-86M is gated and larger — likely over budget | 0–200 MB | Optional second-opinion scorer behind a feature flag | If p95 > 25 ms on target hardware, reject. |
| Public datasets for evaluation (candidates — **verify license/availability**) | e.g., `deepset/prompt-injections`; a paraphrase set such as Quora Question Pairs; **PAWS** (adversarial near-duplicates with different meaning) | MBs | Security benchmarks; semantic-cache false-hit testing | Store raw downloads under `integration/benchmarks/datasets/raw/` (git-ignored); commit only small derived samples with attribution. |

**Download script contract (`scripts/download_models.py`)**: idempotent; prints SHA-256 of each artifact; refuses to run if `HF_HUB_OFFLINE=1` and files missing; exit code ≠ 0 on mismatch.

---

## 5. External API Accounts and Free-Tier Setup

> Free-tier limits, model catalogs and IDs **change often**. Treat every number here as "verify on the provider's page on setup day", and record the values you observe in `config/providers.example.yaml` comments. FluxGate must read limits from config, never hard-code them.

All three expose **OpenAI-compatible** chat-completions APIs, so adapters mostly differ in: base URL, auth header details, model IDs, supported parameters, rate-limit headers, error body shapes, and quirks.

| Provider | Sign-up | Base URL (OpenAI-compatible) | Key format | Setup steps |
|---|---|---|---|---|
| **Groq** | console.groq.com | `https://api.groq.com/openai/v1` | `gsk_…` | 1) Sign in. 2) *API Keys → Create*. 3) Copy once into `.env` as `GROQ_API_KEY`. 4) Note model IDs (e.g., a Llama 3.x 70B/8B variant) and RPM/TPM/daily limits shown in *Settings → Limits*. 5) Expect rate limits to be the first thing you hit — that's the point of the project. |
| **OpenRouter** | openrouter.ai | `https://openrouter.ai/api/v1` | `sk-or-v1-…` | 1) Sign in. 2) *Keys → Create*. 3) `OPENROUTER_API_KEY`. 4) Use `:free` model variants for dev; note their strict daily/min limits. 5) Send recommended attribution headers `HTTP-Referer` and `X-Title` (set from config). 6) Handle upstream-provider errors surfaced inside OpenRouter responses (200 with error body is possible — adapter must detect). |
| **NVIDIA NIM** (hosted API catalog) | build.nvidia.com | `https://integrate.api.nvidia.com/v1` | `nvapi-…` | 1) Sign in with NVIDIA developer account. 2) Pick a model page → *Get API Key*. 3) `NVIDIA_API_KEY`. 4) Note credit/rate allowance. 5) Some models have parameter restrictions — encode in adapter capability table. |

**Provider hygiene checklist**
- [ ] Each developer creates **their own** keys (never share keys over Discord/DMs).
- [ ] Keys live only in `.env` (git-ignored) or the OS keychain; `.env.example` has placeholders only.
- [ ] Use a **dedicated low-limit key** for benchmarks; rotate after Phase 4.
- [ ] Add each key to gitleaks allow-nothing baseline: any commit containing `gsk_`, `sk-or-v1-`, `nvapi-`, `fgx-` patterns must fail pre-commit.
- [ ] Never show the terminal/editor with `.env` open on Discord share.

**Logical model alias example (config, M2-owned):**

```yaml
aliases:
  fluxgate-default:
    groq:        <verify: Groq model id>
    openrouter:  <verify: OpenRouter model id, ":free" variant for dev>
    nvidia_nim:  <verify: NIM model id>
```
Pass-through of a concrete model ID is allowed only for the provider that owns that ID.

---

## 6. Environment Variables (`.env.example` will mirror this table)

| Variable | Example (placeholder) | Owner | Meaning |
|---|---|---|---|
| `FLUXGATE_ENV` | `dev` | S | `dev` / `test` / `prod` |
| `FLUXGATE_HOST` / `FLUXGATE_PORT` | `0.0.0.0` / `8000` | M2 | Bind |
| `FLUXGATE_DB_PATH` | `./data/fluxgate.db` | S | SQLite file |
| `FLUXGATE_KEY_PEPPER` | `change-me-32+random-bytes-hex` | M2 | HMAC pepper for virtual keys. **Generate with** `python -c "import secrets;print(secrets.token_hex(32))"` |
| `FLUXGATE_ADMIN_TOKEN` | `change-me` | M2 | Protects dashboard/admin routes |
| `FLUXGATE_POLICY` | `default` | M1 | Default guardrail policy name |
| `FLUXGATE_CACHE_ENABLED` | `true` | M1 | Global cache switch |
| `FLUXGATE_L2_THRESHOLD` | `0.92` | M1 | Cosine threshold (initial; tuned by benchmark) |
| `FLUXGATE_CACHE_DEFAULT_TTL_S` | `86400` | M1 | Default TTL |
| `FLUXGATE_CACHE_MAX_ENTRIES_PER_TENANT` | `50000` | M1 | Eviction cap |
| `FLUXGATE_EMBED_MODEL_PATH` | `./models/all-MiniLM-L6-v2` | M1 | Local model dir |
| `FLUXGATE_CPU_THREADS` | `2` | M1 | Embedding/scan thread pool |
| `HF_HUB_OFFLINE` | `1` | S | After models downloaded |
| `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `NVIDIA_API_KEY` | `REPLACE_ME` | M2 | Provider credentials |
| `FLUXGATE_PROVIDER_PRIORITY` | `groq,openrouter,nvidia_nim` | M2 | Default order |
| `FLUXGATE_CB_FAILURE_THRESHOLD` / `FLUXGATE_CB_RECOVERY_S` / `FLUXGATE_CB_HALF_OPEN_PROBES` | `5` / `30` / `2` | M2 | Circuit breaker defaults |
| `FLUXGATE_UPSTREAM_CONNECT_TIMEOUT_S` / `…_READ_TIMEOUT_S` | `5` / `60` | M2 | httpx timeouts |
| `FLUXGATE_LOG_LEVEL` | `INFO` | S | |
| `FLUXGATE_STORE_PROMPT_PREVIEW` | `false` (strict) / `true` (dev) | S | Persist ≤80-char sanitized preview |

---

## 7. Local Environment Setup Checklist

Both developers complete this **before Phase 1 closes** (✅ = tick in the PR that closes Phase 1).

### 7.1 Machine

- [ ] Python 3.12 installed; `python --version` OK.
- [ ] `uv --version` OK (or pip-tools chosen).
- [ ] `git --version` ≥ 2.40; `gh auth status` OK.
- [ ] Docker runs `docker run hello-world` (M2 required, M1 optional).
- [ ] `sqlite3 --version` OK.
- [ ] `gitleaks version` OK.
- [ ] ≥ 5 GB free disk, ≥ 8 GB RAM.

### 7.2 Repository

```bash
git clone git@github.com:<org-or-user>/fluxgate.git && cd fluxgate
uv venv --python 3.12 && source .venv/bin/activate       # Windows(WSL2): same
uv sync --extra dev                                       # after pyproject exists (Batch 3)
pre-commit install
cp .env.example .env                                      # then edit locally; NEVER commit
python scripts/download_models.py                          # fetches + verifies MiniLM
python scripts/verify_env.py                               # prints a green/red checklist
```

### 7.3 Required files present at Phase 1 close

- [ ] `.env.example` — placeholders only, every variable in §6 present.
- [ ] `.gitignore` — must include: `.env`, `.env.*` (except `.env.example`), `data/`, `*.db`, `*.db-wal`, `*.db-shm`, `models/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `htmlcov/`, `.coverage`, `integration/benchmarks/datasets/raw/`, `integration/benchmarks/reports/tmp/`, `*.pem`, `*.key`, `*.log`, `node_modules/` (if React), IDE folders, OS junk.
- [ ] `pyproject.toml` — dependencies per §2, tool configs.
- [ ] `uv.lock` committed.
- [ ] `.pre-commit-config.yaml` — ruff, ruff-format, mypy, gitleaks, check-added-large-files (limit 1 MB), detect-private-key.
- [ ] `SECURITY.md` — vulnerability reporting + threat-model summary + "detection is risk assessment".
- [ ] `.github/workflows/ci.yml` — lint, type-check, import-linter, unit tests, contract snapshot test, gitleaks.

### 7.4 `scripts/verify_env.py` must check

1. Python ≥ 3.11; required packages importable (`faiss`, `sentence_transformers`, `fastapi`, `httpx`, `aiosqlite`).
2. MiniLM loads **offline**, outputs shape `(384,)`, norm ≈ 1 after normalization; one embedding < 100 ms after warm-up (informational).
3. `.env` exists, all required variables non-placeholder (provider keys optional for M1).
4. SQLite WAL mode can be enabled in `data/`.
5. (Optional, M2) each configured provider key returns 200 on a 1-token test call; prints **only** status codes, never keys.
6. Prints Python/OS/CPU/RAM summary → paste into benchmark reports.

### 7.5 Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `pip` pulls 2+ GB of CUDA | default torch wheel | install CPU wheel index |
| First embedding takes seconds | lazy model load + thread warm-up | warm up in lifespan; `/readyz` gates on it |
| Embedding latency spikes under load | thread oversubscription | `torch.set_num_threads(N)` + `OMP_NUM_THREADS` |
| `faiss` import error on Windows | wheel/ABI mismatch | use WSL2 |
| Tests flaky on TTL | real time used | inject `FakeClock` |
| HF tries network at runtime | offline flag unset | `HF_HUB_OFFLINE=1` after download |
| SQLite "database is locked" | long write transactions | WAL + `busy_timeout`, batch telemetry writes, keep transactions short |

---

## 8. Docker (M2, Phase 3)

- Base `python:3.12-slim`; multi-stage; non-root user; models mounted as a volume (not baked in → smaller image, no license/pinning confusion).
- `docker-compose.yml`: one service `fluxgate`, volumes `./data`, `./models`, env file, port `8000`, healthcheck on `/readyz`, **`--workers 1`**.
- Optional compose profile `bench` that starts `mock_upstream` for overhead benchmarks.

## 9. Pre-Phase-2 Readiness Gate for Tools (Member 1)

Member 1 may begin Phase 2 only when: §7.1–§7.4 all ticked on Member 1's machine, MiniLM loads offline, `pytest` runs an empty suite green in CI, and `verify_env.py` is green. Member 2's machine is verified before Phase 3 starts (including provider keys).
