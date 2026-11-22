# Contributing to FluxGate

Thanks for your interest! FluxGate is a student-built, **zero-cost**, security-focused open-source project. This guide summarizes the rules; the full versions live in [`docs/GIT_AND_COLLAB_WORKFLOW.md`](docs/GIT_AND_COLLAB_WORKFLOW.md), [`docs/TESTING_AND_BENCHMARK_GUIDE.md`](docs/TESTING_AND_BENCHMARK_GUIDE.md) and [`docs/DECISIONS.md`](docs/DECISIONS.md).

## 1. Before You Start

- **Project phase:** development is **strictly sequential** (Phase 2: Member 1 builds `guardrails/` + `cache/`; Phase 3: Member 2 builds `gateway/` + `router/` + `dashboard/`). Until Gate 4, please **open an issue first** and wait for a maintainer to confirm before sending code, so work doesn't collide with the current phase.
- **Good first contributions anytime:** documentation fixes, labelled test samples (benign/attack/PII corpora), bug reports with a failing test, provider quirks recorded as sanitized fixtures.
- **Security problems:** do **not** file a public issue. Follow [`SECURITY.md`](SECURITY.md).
- Be respectful and constructive in issues, PRs and reviews.

## 2. Ownership (Who Reviews What)

| Area | Owner | Reviewer |
|---|---|---|
| `guardrails/`, `cache/`, `integration/`, `config/policies/`, M1 tests, `scripts/verify_m1.py` | Member 1 | Member 2 |
| `gateway/`, `router/`, `dashboard/`, `Dockerfile`, `docker-compose.yml`, M2 tests | Member 2 | Member 1 |
| `shared/` (contracts, config, db migrations), `docs/`, root files, `.github/` | Both | Both approve |

Do not modify another owner's module without their written approval on the PR. Found a bug in someone else's module? File an issue with a failing test.

## 3. Development Setup

```bash
git clone git@github.com:<your-org>/fluxgate.git && cd fluxgate
uv venv --python 3.12 && source .venv/bin/activate     # Windows: use WSL2
uv sync --extra dev
pre-commit install
cp .env.example .env                                   # edit locally; never commit .env
python scripts/download_models.py                      # one-time MiniLM download
python scripts/verify_env.py
```
Requirements and versions: [`docs/TOOLS_AND_REQUIREMENTS.md`](docs/TOOLS_AND_REQUIREMENTS.md).

## 4. Zero-Cost Rules (D-006: non-negotiable)

Every contribution must keep FluxGate free to build, run, test and demo:

- **No paid services or dependencies**: no paid APIs, hosted vector DBs, paid CI runners, paid SaaS, or anything needing a credit card.
- **Free-tier keys only** for providers; never add billing to an account used for FluxGate.
- Default tests **must not call real providers**: use `respx` or `integration/benchmarks/mock_upstream.py`. Tests that touch real APIs are marked `@pytest.mark.live` and run manually.
- New models/data must be local, small and license-compatible; document size and license in your PR.
- Do not change `zero_cost_mode` default (`true`).

## 5. Branches, Commits, PRs

- **Branches:** `<type>/<scope>-<short-description>`; types `feat`, `fix`, `sec`, `perf`, `test`, `docs`, `bench`, `contract`, `chore`, `release` (e.g., `feat/guardrails-aadhaar-verhoeff`).
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/), e.g., `fix(guardrails): handle placeholder split across SSE chunks`.
- **PRs:** small (target ≤ 400 changed lines), one purpose, squash-merge into `main`, **non-author approval required**, CI green. Fill in the PR template (module, contract impact, tests, security checklist, performance, docs).
- Rebase on `main` before requesting review.

## 6. Quality Bar (CI enforces)

```bash
make lint        # ruff check + format check
make typecheck   # mypy (strict on shared/, guardrails/, cache/)
make arch        # import-linter module boundaries
make test        # fast tests
```
- Add or update tests with every behavior change. Parsing, redaction and cache logic need **property-based tests** (`hypothesis`) where applicable.
- Coverage targets: `guardrails/`, `cache/` ≥ 90 %; `gateway/`, `router/` ≥ 85 %; security-critical files (tenant isolation, eligibility, redactor, key hashing) 100 % branch.
- Style: Ruff (line length 100), full type hints, `async` for I/O, CPU-bound work off the event loop (ADR-10). Docstrings on public functions.
- Performance-sensitive changes include a micro-benchmark delta (before → after, hardware noted). **Never claim a number you did not measure.**

## 7. Contracts and Schema (Change Control)

`shared/contracts/*` and `shared/db/migrations/*` are frozen at Gate 1 and **additive-only** afterwards.

1. Open an issue `contract: <what/why>` with an example payload.
2. Branch `contract/<desc>`, bump `CONTRACT_VERSION`, update the schema snapshot test, fakes and docs.
3. PR labelled `contract-change`; **both** maintainers approve.
- Existing migration files are immutable; fix forward with a new numbered file.

## 8. Security Rules for Every PR

- **No real secrets or personal data** in code, tests, fixtures, docs, screenshots or recordings. Use canaries (`AKIAIOSFODNN7EXAMPLE`, `user@example.com`, generator-made fake Aadhaar/PAN).
- **Placeholders** follow `[[FG:<TYPE>:<N>:<nonce>]]` (D-007). Tests must read the format from the engine's constants; never hard-code it.
- Tenant ID must be part of every cache path; never weaken tenant isolation, eligibility or redaction without a failing test first.
- Never cache unsafe, partial or ineligible responses; never log raw sensitive content; logs go through the redacting logger.
- New regexes must be **linear-time or length-bounded** (ReDoS suite must pass); no nested quantifiers on overlapping classes.
- Prompt-injection detection is described as **risk assessment**, never as protection. Keep that wording in docs, UI and code comments.
- Run `pre-commit run --all-files` (includes `gitleaks`) before pushing; do not bypass hooks.

## 9. Documentation

- The files in `docs/` are the source of truth. If your change alters behavior described there, update the doc **in the same PR**; design choices get a short entry in `docs/DECISIONS.md`.
- Benchmark numbers belong only in committed reports (`integration/benchmarks/reports/`) with hardware, commit SHA and method; README/resume text may quote only those.

## 10. Live Review Etiquette (Maintainers)

Reviews happen live on Discord. Before screen-sharing: close provider consoles and password managers, share a single window, never display `.env` or shell history, and use synthetic data only. See [`docs/GIT_AND_COLLAB_WORKFLOW.md`](docs/GIT_AND_COLLAB_WORKFLOW.md) §7.

## 11. Licensing of Contributions

FluxGate is licensed under **Apache-2.0**. By submitting a contribution you agree it is licensed under the same terms (inbound = outbound). Only submit code you wrote or have the right to contribute, and note third-party material with its license.
