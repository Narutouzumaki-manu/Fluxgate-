# FluxGate — Status Log

Running record of Discord sessions, gate decisions, and blockers.
Updated at the end of every live review session (GIT_AND_COLLAB_WORKFLOW.md §7, step 5).

Format per entry:
```
## YYYY-MM-DD — <Session title>
**Who:** M1 / M2 / both
**Phase / Gate:** e.g., Phase 1b
**Work packages completed:** comma-separated
**Blockers / open items:** or "none"
**Next session goal:**
**Status:** 🟢 On track / 🟡 At risk / 🔴 Blocked
```

---

## 2026-11-22 — Phase 1b Scaffold Commit

**Who:** both
**Phase / Gate:** Phase 1b (scaffold), pre-Gate 1

**Work packages completed:**
- Batch A: package tree `__init__.py` stubs, SQLite migrations 0000–0004 (all
  verified with in-process SQLite smoke test), `config/fluxgate.example.yaml`,
  `config/providers.example.yaml`, `config/policies/default.yaml`,
  `config/policies/strict.yaml`.
- Batch B: `Makefile`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`,
  `.github/PULL_REQUEST_TEMPLATE.md`, `CHANGELOG.md`, `docs/STATUS_LOG.md`,
  `tests/security/__init__.py`, all four scripts (`download_models.py`,
  `verify_env.py`, `create_dev_key.py`, `verify_m1.py`), `shared/testing/`
  fakes (`FakeGuardrailEngine`, `FakeCacheEngine`, `FakeRouter`, `FakeClock`),
  `tests/fakes/`, `tests/contract/test_schema_snapshot.py`,
  `tests/contract/test_protocol_conformance.py`,
  `tests/unit/db/test_migrations.py`.

**Verification run:**
- `uv run lint-imports` — PASS (all packages are empty stubs with no cross-imports)
- `uv run ruff check .` — PASS
- `uv run mypy shared tests` — PASS
- `uv run pytest` — PASS (contract snapshot saved, migration test green)

**Decisions made this session:**
- D-001 through D-008 locked (see `docs/DECISIONS.md`).
- Placeholder syntax `[[FG:<TYPE>:<N>:<nonce>]]` confirmed (D-007).
- `store_prompt_preview: true` in dev, `false` in strict (D-004).
- `on_internal_error: block` as default (D-003).
- Zero-cost project constraint locked (D-006).

**Blockers / open items:**
- Model IDs in `0004_seed_config.sql` and `config/providers.example.yaml` carry
  `VERIFY:` prefix — replace on each developer's setup day with verified, current
  free-tier model IDs.
- `scripts/download_models.py` requires network; run before setting `HF_HUB_OFFLINE=1`.
- Gate 1 tag `contracts-v1.0.0` to be created after both developers tick off §7.1–§7.4
  of `docs/TOOLS_AND_REQUIREMENTS.md`.

**Next session goal:**
- Member 1 begins Phase 2: `guardrails/normalize.py` → PII detectors → injection rules.
- Member 2 reviews contracts and sets up provider keys.

**Status:** 🟢 On track

---

<!-- Add new entries above this line, newest first. -->
- 2026-11-25 — M1-0 complete: protocols (contracts v1.1.0), policy loader, skeleton guardrail/cache engines, baseline conformance suite. 172 tests green. Next: M1-1 normalizer.
- 2026-11-27 — M1-1 complete: text normalizer (invisible-character stripping, NFKC, homoglyph fold, whitespace collapse, offset map) and bounded base64/hex decode-probe. 32 new tests incl. hypothesis properties. Next: M1-2 PII detectors.
- 2026-11-27 — M1-2 complete: PII validators (Verhoeff, Luhn, PAN, card networks), detectors for email/phone/Aadhaar/PAN/card with overlap resolution (detect_pii). Measured on synthetic data: recall 100% (5 x 300 samples); false positives 0-0.36% per detector on 559 benign snippets. Next: M1-3 secret detectors.
