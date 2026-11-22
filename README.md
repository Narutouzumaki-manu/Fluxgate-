# FluxGate

**A self-hosted, OpenAI-compatible AI security gateway and semantic cache.**
Point your existing OpenAI SDK at FluxGate by changing one line (`base_url`) and get a local semantic cache, automatic provider failover, and PII / secret / prompt-injection controls applied *before* your data leaves your machine. **Zero-cost by design**: free software, free API tiers, local compute.

> **Project status: planning complete, implementation not started.**
> The architecture, contracts, schema and dashboard are specified in [`docs/`](docs/). The code described below is the **design target**. **No benchmark results exist yet**; every number in the docs is an *engineering target* until a committed report in `integration/benchmarks/reports/` says otherwise.

---

## Why FluxGate exists

We built an [Enterprise Hybrid-Search RAG system](#benchmark-client-hybrid-rag) and hit four production-style problems that every small AI app meets:

| Problem | FluxGate's answer |
|---|---|
| Free-tier LLM APIs (Groq, OpenRouter, NVIDIA NIM) rate-limit you | Per-provider outbound limits, automatic failover, circuit breakers |
| Repeated and near-identical questions waste tokens, quota and time | Two-layer cache: exact (SHA-256) + semantic (MiniLM + FAISS) |
| Raw document chunks and user text reach third-party APIs | PII/secret redaction before egress; injection risk scoring incl. retrieved RAG context |
| One provider outage breaks the app | Multi-provider router, `CLOSED / OPEN / HALF_OPEN` circuit breaker |

## Features (design targets)

- **Drop-in proxy**: `POST /v1/chat/completions` (JSON and SSE streaming) and `GET /v1/models`; works with the official OpenAI SDKs.
- **Virtual keys** `fgx-…`: HMAC-hashed at rest, raw key shown once, per-key token-bucket rate limits and daily caps.
- **Dual-layer cache**: L1 exact match; L2 semantic match (cosine similarity **> 0.92** initially, tuned by benchmark), per-tenant FAISS indexes, compatibility checks (model, system prompt, context, parameters), TTL, poisoning defenses, strict tenant isolation.
- **Resilient routing**: Groq, OpenRouter, NVIDIA NIM adapters; handles 429 / 5xx / timeouts; retries only when safe (never after the first byte reaches the client).
- **AI security guardrails**: prompt-injection / jailbreak risk scoring (user text, system text, retrieved chunks); configurable `allow / warn / block`; PII and secret redaction (emails, phones, **Aadhaar** with Verhoeff check, **PAN**, cards, provider API keys); **sliding-window redaction for SSE streams** so secrets split across chunks never leak.
- **Developer dashboard** (FastAPI + Jinja2 + HTMX, no Node, no CDN): Overview, Provider Health, Trace & Security Audit, Keys & Settings, and a **Red-Team & Cache Playground**.

### How a request flows

```
client ─► auth + rate limit ─► L1 exact cache ─► guardrails (inject score, PII/secret redact)
                                    │hit                     │block → 400
                                    ▼                        ▼
                               return response      L2 semantic cache ─► router (Groq | OpenRouter | NIM)
                                                         │hit                     │
                                                         ▼                        ▼
                                                  return response   response scan / stream redaction ─► cache store ─► client
```
Details: [`docs/ARCHITECTURE_BLUEPRINT.md`](docs/ARCHITECTURE_BLUEPRINT.md).

---

## Quickstart (target experience; becomes real after Phase 3)

```bash
git clone (https://github.com/Narutouzumaki-manu/Fluxgate-.git) && cd fluxgate
uv venv --python 3.12 && source .venv/bin/activate
uv sync --extra dev
cp .env.example .env                       # then edit; never commit .env
python scripts/download_models.py          # one-time ~90 MB MiniLM download, then set HF_HUB_OFFLINE=1
python scripts/verify_env.py               # green/red checklist
uvicorn gateway.app:create_app --factory --port 8000 --workers 1   # single process by design (ADR-09)
python scripts/create_dev_key.py           # prints an fgx- key ONCE
```

### Use it from the OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="fgx-...")   # only these two values change

resp = client.chat.completions.create(
    model="fluxgate-default",
    messages=[{"role": "user", "content": "Summarize our refund policy."}],
    temperature=0.2,          # semantic (L2) cache serves temperature <= 0.5; omitted temperature counts as 1.0
)
print(resp.choices[0].message.content)
```

Optional extension for RAG clients (sent via `extra_body`, stripped before the provider call):

```python
resp = client.chat.completions.create(
    model="fluxgate-default",
    messages=[...],
    temperature=0.2,
    extra_body={"fluxgate": {
        "semantic_query": "What is the refund window?",          # what L2 embeds (MiniLM truncates at 256 word-pieces)
        "context_fingerprint": "sha256-of-retrieved-chunk-ids",  # semantic hits require identical context
        "retrieved_context": [{"chunk_id": "c1", "text": "…", "source": "policy.pdf#3"}],  # scanned for indirect injection
    }},
)
```

Streaming works the same way (`stream=True`). Response headers explain what happened: `X-FluxGate-Cache` (`HIT-L1 | HIT-L2 | MISS | BYPASS`), `X-FluxGate-Provider`, `X-FluxGate-Similarity`, `X-FluxGate-Risk`, `X-FluxGate-Request-Id`.

### What the provider receives

Detected PII and secrets are replaced with request-scoped placeholders of the form `[[FG:<TYPE>:<N>:<nonce>]]`, for example:

```
Before:  "Email jane@example.com about invoice 42"
Sent:    "Email [[FG:EMAIL:1:7f3a]] about invoice 42"
```
The original values live only in RAM for the duration of the request. Secrets are never restored. Requests that needed redaction are not cached.

---

## Zero-cost by design

FluxGate must be buildable, testable, benchmarked and demoed for **$0**:

- Free tiers only (Groq, OpenRouter `:free` models, NVIDIA NIM). **Do not add payment methods** to any provider account.
- `FLUXGATE_ZERO_COST_MODE=true` (default): the router refuses models not flagged free.
- Per-provider outbound caps and per-key daily caps protect your free quota; the playground defaults to **dry-run** (no provider call).
- Embeddings and detection run locally on CPU. SQLite + in-RAM FAISS. No cloud services, no paid CI.
- "Cost saved" in the dashboard is an **estimate of equivalent paid-API cost**, not money actually saved.

## Security stance (read [`SECURITY.md`](SECURITY.md))

- Prompt-injection detection is **risk assessment, not a guarantee**. Measured recall and false-positive rates will be published with the corpus description.
- No raw prompts, responses, PII, secrets or virtual keys in logs or the database (only hashes, masked previews, sanitized previews in dev).
- Tenant isolation is structural: tenant ID is part of every cache key and each tenant has its own FAISS index.
- Dashboard binds to localhost by default and makes no external requests.

## Benchmark client: Hybrid RAG

FluxGate is independent infrastructure. Our Hybrid-Search RAG project (BM25 + dense retrieval, PyTorch fusion/reranking, strict source citation) is only a **benchmark client**: it changes its `base_url` and nothing else. FluxGate never imports it. Methodology: [`docs/TESTING_AND_BENCHMARK_GUIDE.md`](docs/TESTING_AND_BENCHMARK_GUIDE.md).

---

## Repository layout

```
shared/        contracts (Pydantic), config, db migrations, test fakes        (both)
guardrails/    injection scoring, PII/secret redaction, SSE redactor           (Member 1)
cache/         L1 exact + L2 FAISS semantic cache, eligibility, poisoning      (Member 1)
integration/   RAG client adapter, mock upstream, benchmarks and reports       (Member 1)
gateway/       FastAPI proxy, SSE, virtual keys, rate limiting, telemetry      (Member 2)
router/        provider adapters, circuit breaker, failover                    (Member 2)
dashboard/     observability UI                                                (Member 2)
docs/          planning docs: the source of truth
```

## Documentation

| Doc | Purpose |
|---|---|
| [`ARCHITECTURE_BLUEPRINT.md`](docs/ARCHITECTURE_BLUEPRINT.md) | Diagrams, repo tree, lifecycle, latency budgets, shared contracts, ADRs |
| [`TOOLS_AND_REQUIREMENTS.md`](docs/TOOLS_AND_REQUIREMENTS.md) | Software, libraries, free-tier accounts, setup checklist |
| [`ENGINEERING_ROADMAP.md`](docs/ENGINEERING_ROADMAP.md) | Ownership, phases and gates |
| [`GIT_AND_COLLAB_WORKFLOW.md`](docs/GIT_AND_COLLAB_WORKFLOW.md) | Branching, PRs, Discord review, handoff checklist |
| [`TESTING_AND_BENCHMARK_GUIDE.md`](docs/TESTING_AND_BENCHMARK_GUIDE.md) | Test strategy and benchmark methodology |
| [`PRD.md`](docs/PRD.md) · [`TRD.md`](docs/TRD.md) | Product requirements · technical design |
| [`UI_UX_SPEC.md`](docs/UI_UX_SPEC.md) · [`BACKEND_SCHEMA.md`](docs/BACKEND_SCHEMA.md) | Dashboard spec · database schema |
| [`DECISIONS.md`](docs/DECISIONS.md) | Locked decisions (license, placeholder syntax, zero-cost rules, …) |

## Roadmap

1. **Phase 1**: docs, shared contracts, scaffold, CI.
2. **Phase 2**: Member 1 completes `guardrails/` + `cache/` and a standalone verification runner.
3. **Phase 3**: Member 2 builds `gateway/` + `router/` + `dashboard/` on top of the finished modules.
4. **Phase 4**: joint Hybrid RAG integration and honest, reproducible benchmarks.

Development is strictly sequential (see the roadmap), so external code contributions are best opened as issues first. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Claims policy

Performance and security numbers appear in this README **only** after they exist in a committed benchmark report (with hardware, commit SHA and method). Until then, treat all targets as goals.

## License

[Apache-2.0](LICENSE). Third-party components keep their own licenses (e.g., `all-MiniLM-L6-v2` is Apache-2.0).
