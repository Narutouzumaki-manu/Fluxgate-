## What & why
<!-- 2–4 sentences. Link the roadmap work package (e.g., M1-5) -->

## Module / owner
- [ ] guardrails  - [ ] cache  - [ ] integration  - [ ] gateway  - [ ] router  - [ ] dashboard  - [ ] shared

Owner of touched module: @…
Touches another member's module?  - [ ] No  - [ ] Yes → owner approved in comments

## Contract impact
- [ ] None
- [ ] Additive change (label `contract-change`, `CONTRACT_VERSION` bumped, schema snapshot updated)
- [ ] Breaking change (needs both approvals + migration note)

## Tests
- [ ] Unit tests added/updated
- [ ] Property/fuzz tests added (if parsing, redaction, or cache logic changed)
- [ ] Integration/e2e tests added (if full pipeline changed)

Commands run: `pytest -q …`
Coverage of touched files: __%

## Security checklist
-- [ ] No raw secrets/PII in code, fixtures, logs, or snapshots (canaries only: `sk-canary-test-0000`, `user@example.com`, synthetic Aadhaar/PAN)
- [ ] Tenant isolation preserved (tenant_id present in every cache path / DB query)
- [ ] No unsafe or ineligible response can be cached by this change
- [ ] New regexes reviewed for ReDoS (linear-time or length-bounded; tested against 1 MB adversarial strings)
- [ ] All new log statements go through the redacting logger (`shared/logging.py`)

## Performance
- [ ] N/A
- [ ] Micro-benchmark delta attached (before → after, hardware noted)

## Docs
- [ ] Module README / docstrings updated
- [ ] `docs/DECISIONS.md` entry added (if a design or implementation choice was made)
- [ ] `CHANGELOG.md` updated (unreleased section)

## Screenshots / CLI output (if UI or CLI change)
<!-- Paste terminal output or screenshot here -->
