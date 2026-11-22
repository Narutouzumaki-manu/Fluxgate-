# Security Policy

FluxGate is a security-focused project, so we treat reports seriously. It is also a **student-run, pre-release, zero-cost project**: we respond on a best-effort basis and make no service-level promises.

## Supported Versions

| Version | Supported |
|---|---|
| `main` (pre-release, `0.1.0.dev0`) | Yes, fixes land on `main` |
| Tagged releases | The latest tag only |

## Reporting a Vulnerability

**Please do not open a public issue for security problems.**

1. Use GitHub's **Private vulnerability reporting** ("Security" tab → "Report a vulnerability") on this repository.
2. If that is unavailable, contact the maintainers privately at `manoj.s200612@gmail.com` (placeholder: replace with a real address before the first public push).

Include: affected component, version/commit SHA, reproduction steps or a failing test, impact, and any suggested fix. **Use synthetic data only** (canary secrets such as `AKIAIOSFODNN7EXAMPLE`, fake emails); never send real credentials or personal data.

**Targets (best effort):** acknowledge within 7 days, triage within 14 days, fix or documented mitigation for confirmed high-severity issues within 30–60 days. We credit reporters who want credit. Please allow us to fix an issue before public disclosure.

**Good-faith research:** testing against your own local FluxGate instance is welcome. Do not test against anyone else's deployment, and do not use FluxGate to attack third-party LLM providers or violate their terms.

## Highest-Priority Vulnerability Classes

We especially want to hear about:

- **Cross-tenant cache leakage** (any path where tenant A can receive tenant B's cached data, via L1, L2, FAISS, or the DB).
- **Redaction bypasses**: PII/secrets reaching a provider, a log, the database, a trace, or the dashboard; secrets leaking across SSE chunk boundaries.
- **Virtual key weaknesses**: raw key recovery, hash/pepper misuse, auth bypass, rate-limit bypass.
- **Cache poisoning** that serves unsafe or attacker-controlled content.
- **Admin/dashboard** issues: authentication or CSRF bypass, XSS (including via model output or trace text), exposure beyond loopback.
- **ReDoS / resource exhaustion** in guardrails, parsers or the streaming path.
- **Supply-chain** concerns in pinned dependencies or vendored frontend assets.

### Out of scope

- "The injection detector missed attack X" or "flagged benign text Y". Detection is heuristic **risk assessment**; misses and false positives are expected. Please contribute a labelled sample via a normal issue/PR instead (see `CONTRIBUTING.md`).
- Vulnerabilities in third-party providers (Groq, OpenRouter, NVIDIA NIM) or in upstream libraries (report those upstream).
- Findings that require physical access to the machine or a compromised host/OS.
- Denial of service by an operator who sets deliberately unsafe configuration.

## Security Model (Summary)

| Topic | Design (see `docs/TRD.md` §D2) |
|---|---|
| **Trust boundary** | Clients → FluxGate → providers. Providers are treated as untrusted recipients of data; they only receive **sanitized** requests. |
| **Virtual keys** | `fgx-…` keys are stored as `HMAC-SHA256(pepper, key)` plus an 8-character display prefix. The raw key is shown once at creation and never stored or logged. |
| **Provider credentials** | Environment variables only; never in the database, logs, traces or dashboard. |
| **Data at rest** | No raw prompts or responses outside the cache. Logs hold hashes, lengths, masked finding previews, and (dev profile only) an ≤ 80-char *sanitized* preview. |
| **Egress redaction** | PII/secrets replaced by request-scoped placeholders `[[FG:<TYPE>:<N>:<nonce>]]` before any provider call; the original values live in RAM for the request only; secrets are never restored. |
| **Tenant isolation** | Tenant ID in every cache key; one FAISS index per tenant; tenant re-verified on read. |
| **Cache safety** | Only complete, clean, low-risk, PII-free responses are cached; partial streams and ineligible requests are never stored. |
| **Admin surface** | Single admin token → signed `HttpOnly; SameSite=Strict` session, CSRF tokens, loopback-only by default, strict CSP, no external requests. |
| **Abuse limits** | Per-key token buckets, daily caps, body-size limits, in-flight limits, per-provider outbound caps. |

OWASP LLM Top 10 (2025) coverage is summarized in `docs/TRD.md` §D2 with explicit "partial / out of scope" labels.

## Known Limitations (Read Before Trusting FluxGate)

We state these plainly rather than imply protection we cannot demonstrate:

1. **Prompt-injection detection is a risk score, not a guarantee.** The MVP is rule-based and will miss novel, semantic, multilingual and heavily obfuscated attacks, and it will flag some benign text. Measured recall/false-positive rates are reported with the test corpus description once benchmarks exist.
2. **PII coverage is pattern-based.** Emails, phone numbers (incl. India formats), Aadhaar (checksum-validated), PAN, payment cards and common secret formats are covered. **Names, postal addresses, free-form identifiers and context-dependent PII are not detected** (no NER in the MVP).
3. **High-entropy secret detection is heuristic** and warns by default.
4. **Multimodal content** (images/files) is not inspected, and such requests bypass the cache.
5. **Streaming redaction can delay** a short tail of text near a potential match (bounded hold-back window) and has no timer-based release by design (fail-safe over speed).
6. **Single-process MVP.** Rate-limit buckets, circuit-breaker state and the L1 cache live in memory and reset on restart. FAISS indexes are rebuilt from SQLite. Not designed for multi-worker or HA deployments.
7. **Redacted requests are not cached** (so a repeated request containing PII always reaches the provider).
8. **Timeout after send** can cause a provider to process a request that FluxGate then fails over: duplicate quota use is possible (not duplicate actions; tool execution is client-side).
9. **Not a compliance product.** FluxGate is not certified for GDPR, India's DPDP Act, HIPAA, PCI-DSS or similar regimes. Do not rely on it as your only control for regulated data.
10. **Dashboard is single-admin.** No per-user accounts, SSO, or fine-grained RBAC.
11. **Token/cost figures are estimates** (provider-reported usage preferred; `tiktoken` fallback is approximate).
12. Rotating `FLUXGATE_KEY_PEPPER` invalidates every virtual key.

## Operator Hardening Checklist

- [ ] Generate a unique `FLUXGATE_KEY_PEPPER` and `FLUXGATE_ADMIN_TOKEN` (see `.env.example` for commands); never reuse placeholders.
- [ ] Keep `FLUXGATE_ADMIN_BIND_LOCAL_ONLY=true`. If you must expose FluxGate beyond localhost, put it behind a TLS reverse proxy and restrict `/admin` and `/dashboard` to trusted networks.
- [ ] Keep `FLUXGATE_ZERO_COST_MODE=true`; use free-tier keys only; never attach billing to provider accounts used for development.
- [ ] Use the `strict` policy and `FLUXGATE_STORE_PROMPT_PREVIEW=false` for anything beyond local experiments.
- [ ] Restrict file permissions: `data/` directory `0700`, database `0600`; keep `.env` out of backups you share.
- [ ] Issue one key per client, set low `rpm_limit`/`daily_request_cap`, revoke unused keys, rotate on suspicion.
- [ ] Reduce retention (Settings → Privacy & retention) if you do not need long audit history.
- [ ] Keep dependencies updated (`uv lock --upgrade` in a `sec/` PR) and review Dependabot/secret-scanning alerts.
- [ ] Never paste real secrets or personal data into the Playground; use the synthetic presets.

## For Contributors: Secret Hygiene

- **No real secrets in the repository**, ever: not in code, tests, fixtures, docs, screenshots, or recordings. Use obviously fake **canaries** (e.g., the public AWS documentation example key `AKIAIOSFODNN7EXAMPLE`, `user@example.com`, generator-made checksum-valid fake Aadhaar/PAN, public test card ranges).
- Pre-commit runs `gitleaks` and private-key detection; CI repeats the scan. Do not bypass hooks.
- **If a real credential is exposed** (committed, pasted in a PR, or shown on a Discord stream): **revoke/rotate it immediately at the provider**, then notify the maintainers; history cleanup follows `docs/GIT_AND_COLLAB_WORKFLOW.md` §10.
- Do not log, print, or snapshot request bodies, headers containing `Authorization`, or vault contents. All logging goes through the redacting logger.
- Never relax tenant isolation, eligibility, or redaction code without a failing test first and a security-labelled PR reviewed by both maintainers.

## Safe Harbor and Disclosure

We will not pursue action against researchers who act in good faith, follow this policy, avoid privacy violations and service disruption, and give us reasonable time to remediate. Once fixed, we publish a short advisory in the repository's Security Advisories and `CHANGELOG.md` (under **Security**).

This repository contains **no real secrets**. Any key-like string you see is a documented fake canary or a placeholder.
