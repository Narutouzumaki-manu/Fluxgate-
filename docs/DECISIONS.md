# FluxGate — Decision Log

Format: one entry per decision. Newest last. A decision changes only via a new entry that supersedes it.

| ID | Date | Decision | Status |
|---|---|---|---|
| D-001 | 2026-11-22 | **ADR-01 … ADR-15 (Architecture Blueprint §2) approved as written.** | Locked |
| D-002 | 2026-11-22 | **Dashboard = FastAPI + Jinja2 + HTMX + Alpine + Chart.js, vendored, no Node build step.** React/Vite is a P1 option only. | Locked |
| D-003 | 2026-11-22 | **Default on guardrail internal error = `block`** (`on_internal_error: block`). `permissive` policy may override per tenant. | Locked |
| D-004 | 2026-11-22 | **Sanitized prompt preview (≤ 80 chars): ON in `dev`, OFF in `strict`/`prod`.** Hashes + lengths always stored. | Locked |
| D-005 | 2026-11-22 | **License = Apache-2.0** (patent grant, matches Apache-2.0 MiniLM dependency; one-line change if the team prefers MIT). | Locked unless vetoed in Gate 1 |
| D-006 | 2026-11-22 | **Zero-cost project constraint** (student project). Only free software, free API tiers, local compute, free CI. No paid API, no cloud hosting, no billing details added to any provider account. See PRD §4. | Locked |
| D-007 | 2026-11-22 | **Placeholder syntax** is defined in TRD §A5 (`[[FG:<TYPE>:<N>:<nonce>]]`, ASCII, per-request random nonce). It supersedes the `⟦FG:…⟧` notation used as an illustration in the Roadmap and Testing Guide. Tests must read the format from the engine's constants, never hard-code it. | Locked |
| D-008 | 2026-11-22 | **Real-provider benchmark volume is capped by free-tier limits.** Bulk/overhead measurements use `mock_upstream`; real-provider runs are small (≤ ~150 calls per provider per day), repeated across days. See Testing Guide amendment in PRD §4. | Locked |
