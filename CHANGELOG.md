# Changelog

All notable changes to FluxGate are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Contract changes are listed under a **Contracts** sub-heading in the relevant version.
Every contract change must reference the PR labelled `contract-change` and the
`CONTRACT_VERSION` bump.

---

## [Unreleased]

### Added
- Phase 1b Scaffold Commit — Batch A:
  - Full package directory tree with `__init__.py` stubs: `guardrails/`, `cache/`,
    `gateway/`, `router/`, `dashboard/`, `integration/`, `shared/db/`, `scripts/`,
    `tests/unit/{guardrails,cache,gateway,router,db}`, `tests/contract/`,
    `tests/integration/`, `tests/fakes/`.
  - SQLite migrations `0000`–`0004` in `shared/db/migrations/` (schema_migrations,
    core config, cache, telemetry, provider + alias seed).
  - Config files: `config/fluxgate.example.yaml`, `config/providers.example.yaml`,
    `config/policies/default.yaml`, `config/policies/strict.yaml`.

- Phase 1b Scaffold Commit — Batch B:
  - `Makefile` with all standard targets (`lint`, `typecheck`, `arch`, `test`,
    `test-m1`, `test-m2`, `test-contract`, `test-security`, `test-cov`, `perf`,
    `verify-m1`, `bench`, `db-migrate`, `db-backup`, `db-vacuum`, `clean`).
  - `.pre-commit-config.yaml` (ruff, mypy, gitleaks, standard hooks).
  - `.github/workflows/ci.yml` with jobs: `gitleaks`, `lint`, `typecheck`, `arch`,
    `unit`, `contract`, `security`, `perf`.
  - `.github/PULL_REQUEST_TEMPLATE.md`.
  - `docs/STATUS_LOG.md` — session and gate tracking.
  - `tests/security/__init__.py` stub.
  - `scripts/download_models.py` — idempotent MiniLM download + SHA-256 verification.
  - `scripts/verify_env.py` — environment readiness checker.
  - `scripts/create_dev_key.py` — mints a `fgx-` virtual key printed once.
  - `scripts/verify_m1.py` — Gate 2 acceptance runner (V1–V12 stubs).
  - `shared/testing/` — `FakeGuardrailEngine`, `FakeCacheEngine`, `FakeRouter`,
    `FakeClock`, `fake_clock.py`.
  - `tests/fakes/` — re-exports of `shared/testing/` fakes.
  - `tests/contract/test_schema_snapshot.py` — baseline JSON schema snapshot for
    `CONTRACT_VERSION = "1.0.0"`.
  - `tests/contract/test_protocol_conformance.py` — protocol conformance suite
    parameterized over fake implementations.
  - `tests/unit/db/test_migrations.py` — applies migrations 0000–0004 in an
    in-memory SQLite DB; asserts `PRAGMA integrity_check`, `PRAGMA foreign_key_check`,
    all tables and indexes present, seed rows correct.


### Contracts
- 1.1.0: add `shared/contracts/protocols.py` (GuardrailEngine, CacheEngine, Router, StreamRedactor, RedactionVault, TelemetrySink, Embedder) as specified in Blueprint §10.8. Additive only; no existing model changed.
---

## [0.1.0.dev0] — 2026-11-22 (Phase 1a — Planning and Docs)

### Added
- Repository skeleton: `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`
  (Apache-2.0), `.gitignore`, `.gitleaks.toml`, `pyproject.toml`, `uv.lock`.
- Full planning documentation in `docs/`: `ARCHITECTURE_BLUEPRINT.md`,
  `BACKEND_SCHEMA.md`, `TRD.md`, `DECISIONS.md`, `TOOLS_AND_REQUIREMENTS.md`,
  `GIT_AND_COLLAB_WORKFLOW.md`, `TESTING_AND_BENCHMARK_GUIDE.md`,
  `ENGINEERING_ROADMAP.md`, `PRD.md`, `UI_UX_SPEC.md`.
- `shared/contracts/` — Pydantic v2 contract modules:
  `enums.py`, `base.py`, `openai_models.py`, `context.py`, `guardrails.py`,
  `cache.py`, `router.py`, `gateway.py`, `telemetry.py`.

[Unreleased]: https://github.com/Narutouzumaki-manu/Fluxgate-/compare/v0.1.0.dev0...HEAD
[0.1.0.dev0]: https://github.com/Narutouzumaki-manu/Fluxgate-/releases/tag/v0.1.0.dev0
