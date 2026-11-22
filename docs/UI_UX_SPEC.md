# FluxGate — UI/UX Specification (Developer Dashboard)

| Field | Value |
|---|---|
| Status | DRAFT v1.0 |
| Owner | Member 2 (`dashboard/`) — consumes Member 1's security/cache telemetry and Member 2's proxy/provider telemetry |
| Stack (D-002) | FastAPI + Jinja2 + HTMX 2.x + Alpine 3.x + Chart.js 4.x, all vendored; plain CSS; **no Node build, no CDN, no external requests** |
| Related | PRD DB-01…DB-08, TRD B10 (API), BACKEND_SCHEMA (data) |

---

## 1. Design Goals

1. **Explainability first:** every request answers "what happened, and why?" (hit/miss, blocked, redacted, failed over).
2. **Developer-dense, not decorative:** scannable KPIs, tables, timelines. Dark-first with a light theme.
3. **Safe by construction:** the UI never displays raw prompts, secrets or PII; it shows masked previews, placeholders, hashes and counts. Raw virtual keys appear exactly once.
4. **Honest numbers:** estimates are labelled "estimate"; targets and measured values are never mixed; no fake data in production views.
5. **Free-tier aware (D-006):** quota meters and a persistent "Zero-cost mode" indicator; destructive/expensive actions confirm first.

## 2. Information Architecture

```
/dashboard/login                      Admin token → session
/dashboard                            1  Overview & Live Telemetry            (MVP view 1)
/dashboard/providers                  2  Provider Health & Routing            (MVP view 2)
/dashboard/traces                     3  Request Traces & Security Audit      (MVP view 3)   tabs: Traces | Security Audit
/dashboard/keys                       4  Virtual Keys & Settings              (MVP view 4)   tabs: Keys | Tenants | Settings
/dashboard/playground                 5  Red-Team & Cache Playground          (P0 tool surface)
P1 expansion: /dashboard/cache (Cache Explorer), /dashboard/policy (Policy Editor), /dashboard/alerts, /dashboard/bench
```
The brief's "four consolidated views" are screens 1–4; the playground is the fifth P0 surface required by the product brief.

### Global shell
```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ ◆ FluxGate   [Tenant ▾ all]  [Range ▾ 1h]  [⟳ Live ●]        ⓘ Zero-cost mode: ON    ☾/☀   Admin ▾ │
├───────────┬───────────────────────────────────────────────────────────────────────────────┤
│ Overview  │                                                                               │
│ Providers │                           (page content)                                      │
│ Traces    │                                                                               │
│ Keys      │                                                                               │
│ Playground│  Banner area (system warnings: telemetry dropped, DB not writable, model down)│
└───────────┴───────────────────────────────────────────────────────────────────────────────┘
```
- **Header controls (global filters):** tenant selector (default "All"), time range (15m / 1h / 24h / 7d / custom), Live toggle (polling on/off), theme toggle.
- **Zero-cost badge:** green pill "Zero-cost mode: ON — free models only"; if OFF → amber pill "Zero-cost mode OFF — paid models may be used" with tooltip.
- **Banner area** shows prioritized system conditions: `/readyz` degraded, telemetry events dropped, embedding model unavailable (cache bypassed), all providers OPEN.

## 3. Design System

### 3.1 Tokens (CSS custom properties; dark default)

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | #0e1116 | #f6f7f9 | page |
| `--surface` | #161b22 | #ffffff | cards |
| `--surface-2` | #1d242d | #eef1f5 | table stripes, inputs |
| `--border` | #2b3440 | #d6dbe3 | |
| `--text` | #e6edf3 | #1b2430 | |
| `--text-muted` | #9aa7b4 | #5b6776 | |
| `--accent` | #4c9aff | #1f6feb | primary actions, links |
| `--ok` | #3fb950 | #1a7f37 | CLOSED, ALLOW, HIT |
| `--warn` | #d29922 | #9a6700 | HALF_OPEN, WARN |
| `--bad` | #f85149 | #cf222e | OPEN, BLOCK |
| `--info` | #a371f7 | #8250df | L2/semantic, redaction |
| `--l1` / `--l2` / `--miss` | #3fb950 / #a371f7 / #6e7681 | same family | cache outcome series |

All text/background pairs must meet **WCAG AA (4.5:1)**; verify with an automated check in CI (a small script over token pairs).

### 3.2 Typography, spacing, components
- System font stack (no web fonts): `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; monospace `ui-monospace, "SF Mono", Consolas, monospace` for IDs/hashes/regex rule IDs.
- Scale: 12 / 14 (base) / 16 / 20 / 28 px. Spacing unit 4 px (4, 8, 12, 16, 24, 32).
- Components: KPI card, chart card, data table (sortable, sticky header, keyset-paginated), status badge, severity chip, filter bar, tabs, drawer (right sheet), modal, toast, copy-button, key-value list, stage-timeline (waterfall), meter/gauge, empty-state, skeleton, inline code, banner.
- **Status is never color-only:** badges include an icon + text (`● CLOSED`, `▲ HALF_OPEN`, `■ OPEN`, `✓ ALLOW`, `! WARN`, `✕ BLOCK`).

### 3.3 Data refresh behavior (HTMX)
| Screen | Poll interval | Notes |
|---|---|---|
| Overview KPIs/charts | 5 s | `hx-trigger="every 5s [document.visibilityState==='visible' && live]"` |
| Providers | 3 s | countdown timers computed client-side from `cooldown_until` |
| Traces list | 5 s only when "Live" and on first page | pausing when a drawer is open |
| Keys/Settings | none (on-demand) | |
| Playground | none | request/response |
When the tab is hidden polling pauses; when the API fails 3 consecutive times the UI shows the **stale** state (§9) and backs off exponentially (5 → 10 → 20 → 40 s).

## 4. Screen 1 — Overview & Live Telemetry

**Purpose:** at-a-glance health, savings and risk for the selected tenant/time range.

```
┌ KPI row (6 cards) ─────────────────────────────────────────────────────────────────────────────┐
│ Requests     │ Cache hit rate │ Tokens saved │ Provider calls │ Proxy p95     │ Security events │
│ 1,284        │ 63.4%          │ 412,300      │ avoided 814    │ overhead 21ms │ 17 (3 blocked)  │
│ +12% vs prev │ L1 41% · L2 22%│ ≈ $0.62 est. │ (free quota)   │ L2 lookup 14ms│ 41 redactions   │
├──────────────────────────────────────────┬──────────────────────────────────────────────────────┤
│ Cache outcomes over time (stacked bars)  │ Latency (lines): total p50/p95, upstream p95,         │
│ L1 | L2 | MISS | BYPASS per bucket        │ FluxGate overhead p95                                  │
├──────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ Cumulative tokens saved (area line)      │ Outcome mix (donut) + Bypass reasons (horizontal bar) │
├──────────────────────────────────────────┴──────────────────────────────────────────────────────┤
│ Provider strip:  ● groq CLOSED 98.7% · 210ms   ▲ openrouter HALF_OPEN   ■ nvidia_nim OPEN (retry 0:42) │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Recent requests (last 20): time · key · model · outcome · decision · provider · latency · [open] │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### KPI definitions (tooltips show formula and window)
| KPI | Definition | Sub-text |
|---|---|---|
| Requests | count of `request_logs` in range | delta vs previous equal range |
| Cache hit rate | `(L1+L2 hits) / requests` | L1 % · L2 % |
| Tokens saved | Σ `tokens_saved` | "≈ $X est." = Σ `cost_saved_usd_est`, labelled **"equivalent paid-API cost (estimate)"** |
| Provider calls avoided | = hits | "free-tier quota saved" |
| Proxy overhead p95 | p95 of `total_ms − upstream_ms` for misses | secondary: L2 lookup p95 |
| Security events | count of `security_events` (distinct requests with findings) | blocked count; redaction count |

Percentiles are computed from the latency histogram in `metrics_rollup` (approximate, bucket-interpolated; tooltip says "approx."). Exact percentiles are available in the trace table for the last N=5,000 requests.

### Charts
1. **Cache outcomes over time** — stacked bar; legend toggles; hover shows counts + rate.
2. **Latency** — lines: total p50, total p95, upstream p95, FluxGate overhead p95; log-scale toggle.
3. **Cumulative tokens saved** — area.
4. **Outcome mix donut** + **bypass reasons bar** (top 6: `high_temperature`, `pii_or_secret_present`, `tools_present`…), clicking a segment applies it as a filter on the Traces tab.
Each chart has a **"View as table"** toggle (accessibility + copying).

### Filters
Global tenant/range; local: key, model alias, served-from. Filters persist in the URL query string.

### Empty/loading/error
See §9. First-run empty state includes a copy-paste snippet:
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="fgx-…")
```

## 5. Screen 2 — Provider Health & Routing

**Purpose:** show circuit-breaker states, quota use and routing outcomes; allow safe operator actions.

```
┌ Provider cards (one per provider) ─────────────────────────────────────────────────────────────┐
│ groq                              ● CLOSED         │ openrouter           ▲ HALF_OPEN (probe 1/1) │
│ Success 98.7% (n=412) · p50 180ms p95 410ms        │ Cooldown: — · Probes: 1/2 successes          │
│ Consecutive failures: 0                            │ Last failure: 5xx at 12:04:11                │
│ Free-tier today: ███████░░░ 212/300 req (cap)      │ Free-tier today: ██░░░░░░░░ 41/200           │
│ [Disable] [Reset breaker] [Test call ⚠ uses quota] │ ...                                          │
├────────────────────────────────────────────────────┴──────────────────────────────────────────────┤
│ Circuit timeline (last 24h): colored bands per provider: CLOSED/HALF_OPEN/OPEN with event markers   │
├───────────────────────────────────────────────┬───────────────────────────────────────────────────┤
│ Provider latency (p50/p95 lines)              │ Routing share (donut): served by provider / cache  │
├───────────────────────────────────────────────┴───────────────────────────────────────────────────┤
│ Model aliases table: alias · provider · model id · free ✓ · enabled · status                       │
├───────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Recent failovers: time · request · from → to · reason (429/5xx/timeout) · added latency            │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```
- **Breaker badge colors:** CLOSED `--ok`, HALF_OPEN `--warn`, OPEN `--bad`; `disabled` (manual) grey; `disabled_auth` red with "Provider key rejected — check env var".
- **429 cooldown** shown as a distinct pill "Rate-limited · retry in 0:23" (not the breaker badge).
- **Actions (admin, CSRF):** Disable/Enable (confirm), Reset breaker (confirm: "Forces CLOSED; next failures re-open it"), **Test call** (modal warns: "Sends 1 tiny request; counts against your free quota").
- **Quota meter:** `requests today / configured rpd_cap`; amber ≥ 70%, red ≥ 90%.
- Alias table is read-only in MVP (edited via config); shows `is_free` and zero-cost enforcement notes.

## 6. Screen 3 — Request Trace Inspector & Security Audit Logs

Tabs: **Traces** | **Security Audit**.

### 6.1 Traces tab

**Filter bar:** time range (global), cache outcome (HIT_L1/HIT_L2/MISS/BYPASS), guardrail decision (ALLOW/WARN/BLOCK), provider, status code, key, model, `min similarity`, `has redactions`, `failed over`, free-text (request_id or prompt-hash prefix). **No raw prompt search** (not stored).

**Table columns:** Time · Request ID (mono, copy) · Key prefix · Model → served · Cache (badge + similarity) · Guardrail (badge + risk) · Provider/attempts · Tokens (in/out, saved) · Latency (total, overhead) · Status.
Keyset pagination ("Load more"), 50 rows/page, sortable by time/latency/risk/similarity.

**Detail drawer (click row):**
```
┌ Trace req_01J… ───────────────────────────────────────────────────────────── [Copy JSON] [✕] ┐
│ Timeline (waterfall)                                                                          │
│ auth ▏ ratelimit ▏ parse ▏ L1 ▏ guardrails-in ▇▇▇ ▏ L2 ▇▇ ▏ router ▏ upstream ▇▇▇▇▇▇▇▇ ▏ scan  │
│ total 412 ms · FluxGate overhead 24 ms · upstream 385 ms · TTFT 190 ms                        │
├ Cache ─────────────────────────────┬ Guardrails ───────────────────────────────────────────────┤
│ Outcome: MISS (BYPASS reason: —)   │ Decision: ✓ ALLOW   Risk 0.12 [▮▯▯▯▯] policy default@a1b2 │
│ L1: miss                           │ Findings (3):                                               │
│ L2: best 0.89 vs threshold 0.92    │  rule · type · severity · source · masked preview           │
│     [gauge with threshold marker]  │  PII-EMAIL · email · low · user#2 · j***@e*****.com         │
│ compat mismatch: params            │  SEC-GROQ · secret · high · user#2 · gsk_****…WXYZ          │
│ entry: — · TTL: —                  │ Redactions: EMAIL×1, SECRET×1 (placeholders shown below)   │
├ Routing ───────────────────────────┴───────────────────────────────────────────────────────────┤
│ Attempt 1: groq  429 RATE_LIMITED  180 ms  circuit CLOSED  retry-after 12s                      │
│ Attempt 2: openrouter 200 OK 385 ms circuit CLOSED  ← served                                    │
├ Tokens & savings ───────────────────────────────────────────────────────────────────────────────┤
│ prompt 512 · completion 128 · saved 0 (miss)                                                    │
├ Sanitized preview (first 80 chars; only if enabled) ───────────────────────────────────────────┤
│ "Summarize the invoice for [[FG:EMAIL:1:7f3a]] using key [[FG:SECRET:1:7f3a]] …"                │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```
- Placeholders are rendered as highlighted chips; hovering shows type only.
- For **hits**, the cache panel shows entry id, age, TTL remaining, similarity, hit count; for **blocked**, the guardrail panel is expanded and routing shows "No provider call".
- "Copy JSON" exports the sanitized `RequestTrace` (no bodies).

### 6.2 Security Audit tab
- **Summary strip:** blocked, warned, redactions by type (bar), top 5 rules (bar), severity distribution.
- **Table:** Time · Request ID (link to trace) · Stage (inbound/response/stream) · Decision · Type · Rule ID · Severity chip · Confidence · Source (user/system/context chunk id) · Masked preview.
- **Filters:** type, rule ID, severity, decision, stage, key.
- **Export CSV** (masked data only). A persistent notice: *"FluxGate stores masked previews only. Detection is a risk assessment, not a guarantee."*
- Clicking a rule ID opens a small popover with the rule description (from rule registry metadata, not matched text).

## 7. Screen 4 — Virtual Keys & Settings

Tabs: **Keys** | **Tenants** | **Settings**.

### 7.1 Keys tab
**Table:** Name · Prefix (`fgx-ab12cd34…`) · Tenant · Status (active/revoked/expired) · Limits (rpm/burst/day cap) · Models · Policy · Last used · Created · Expires · 7-day usage sparkline · [⋯ menu: Edit limits, Rotate, Revoke].

**Create key (modal):** Name*, Tenant* (select or "create new"), Rate limit rpm (default 60), Burst (default 10), Daily request cap (default 200; hint: "protects free-tier quota"), Allowed models (multi-select, default all free), Guardrail policy (default/strict), Cache enabled (inherit/on/off), Expires (optional). Submit → **One-time reveal modal**:
```
┌ Key created ───────────────────────────────────────────────┐
│ Copy this key now. You will not be able to see it again.   │
│ fgx-AbCd…(full key)                          [Copy]        │
│ ☐ I have stored this key securely        [Done] (disabled until checked) │
└─────────────────────────────────────────────────────────────┘
```
The key is delivered in the POST response body only, never in a URL, never in server logs; closing the modal clears it from the DOM.

**Revoke:** confirm modal ("Immediately blocks new requests. In-flight streams finish."). **Rotate:** creates a new key (one-time reveal) and offers grace period (0/1h/24h) for the old key.

### 7.2 Tenants tab
Table of tenants (name, key count, cache entries, hit rate) + edit panel: cache enabled, default TTL, max entries, L2 threshold override (shows near-miss histogram hint), guardrail policy. Reserved tenant `__playground__` shown read-only.

### 7.3 Settings tab (sections)
| Section | Controls |
|---|---|
| **Guardrail policy** | Active policy name, version hash, thresholds (read-only table of the loaded YAML in MVP); P1: editor |
| **Cache** | Global enable, L2 threshold (default 0.92), max temperature, default TTL, max entries; **Purge cache** (tenant/all, confirm with typed word `PURGE`) |
| **Privacy & retention** | Store sanitized preview toggle (disabled with explanation when policy is strict), retention days per table |
| **Zero-cost mode** | Read-only status, list of free-flagged aliases; changing requires config/env (not UI) to avoid accidental spend |
| **Admin** | Admin session length, sign out all; reminder to keep `FLUXGATE_ADMIN_TOKEN` secret |
| **Diagnostics** | Contract version, build SHA, model path, embedding warm-up time, DB size, WAL size, telemetry dropped counter |

## 8. Screen 5 — Interactive Red-Team & Cache Playground

**Purpose:** let a developer *see* prompt-injection detection, PII redaction, semantic caching and stream redaction live, safely and for free.

### 8.1 Safety rules
- Banner: *"Use synthetic data only. Do not paste real secrets or personal data."*
- Runs use the reserved tenant `__playground__` (isolated cache, short TTL = 1 h, separate quotas) and the admin session (no virtual key needed).
- **Dry-run is ON by default** → full guardrail + cache pipeline runs, provider call is **skipped** (shows "Would have sent this sanitized request to <provider/model>"). Turning dry-run off shows a free-quota meter and requires a checkbox "I understand this uses 1 request of free quota".
- Presets contain only synthetic canaries (e.g., `AKIAIOSFODNN7EXAMPLE`, `user@example.com`, generator-made valid-checksum fake Aadhaar/PAN).

### 8.2 Layout
```
┌ Mode tabs: [Prompt Injection] [PII & Secrets] [Semantic Cache] [Stream Redaction] [Free-form] ┐
├ Input panel ─────────────────────────────────┬ Results panel ──────────────────────────────────┤
│ Presets ▾  (category list + "Load")          │ Pipeline stepper:                                │
│ System prompt  [textarea]                    │  [L1 miss 0.4ms]→[Guardrails ✓ 8ms]→[L2 miss 14ms]│
│ User message   [textarea]                    │  →[Router (skipped: dry-run)]→[Scan]→[Store?]     │
│ Retrieved chunks (+ add chunk)  [chunk 1 ✎]  │ ─────────────────────────────────────────────────│
│ Options: policy ▾  model alias ▾  temp [0.2] │ Guardrail verdict: ✕ BLOCK  risk 0.91 [▮▮▮▮▯]     │
│          stream ☐  cache mode ▾  dry-run ☑   │ Findings table + highlighted input overlay        │
│ [ Run ]   [ Reset ]   quota: 212/300         │ "What the provider would receive" (diff view)     │
│                                              │ Cache panel (similarity bar, threshold, near-miss)│
│                                              │ Response (if not dry-run) · headers X-FluxGate-*   │
└──────────────────────────────────────────────┴──────────────────────────────────────────────────┘
History (session): last 20 runs as chips → click to reload inputs + results
```

### 8.3 Mode specifics

**A. Prompt Injection mode**
- Presets by category: instruction override, role jailbreak, system-prompt extraction, delimiter spoofing, exfil via markdown link, **indirect injection in a retrieved chunk** (benign document with an embedded instruction), and **benign hard negatives** (an article *about* prompt injection) to show false-positive behavior.
- Results: risk gauge with warn/block threshold markers; per-rule contributions sorted by weight (rule ID, category, weight, source/chunk); decision under the *selected policy* with a "Compare with strict" side toggle.
- Input overlay highlights matched spans (using normalized→original offsets), tooltip = rule ID.
- Footnote: *"Risk assessment, not a guarantee."*

**B. PII & Secrets mode**
- Presets: email, India phone, valid Aadhaar, valid PAN, test card, provider key canaries, JWT, PEM header, mixed text, false-positive set (UUID, git SHA, order number).
- Results: findings with masked previews; **side-by-side original vs. sanitized** (original shown only in the browser from what the user typed; server response contains only sanitized text + spans); redaction counts; "restore in response" simulation toggle (shows how a placeholder echoed by a model would be restored — for non-secret types only).

**C. Semantic Cache mode**
- Two-step workflow: **Step 1** "Seed": run prompt A (non-dry-run required to create an entry; or **"Seed with fake response"** button that stores a synthetic response in the playground tenant — free, no provider). **Step 2** "Probe": run prompt B.
- **Similarity Probe** sub-tool: two text boxes → cosine similarity, threshold marker, verdict "would hit / would miss", entity-guard result (digits/capitalized-token/negation parity), compat check explanation (differences in model/system/params highlighted). No provider call, no storage.
- Presets: paraphrase pair (expected hit), negation flip (expected miss via entity guard/threshold), changed number (expected miss), different system prompt (compat miss), different tenant (isolation demo: toggles a second sandbox tenant `__playground_b__`; the same prompt must MISS).
- Results: outcome badge (HIT_L1/HIT_L2/MISS/BYPASS), similarity bar with threshold line and near-miss value, entry id, TTL, bypass reason in plain language ("temperature 0.9 > 0.5 limit for semantic cache").

**D. Stream Redaction mode**
- Input: text containing a canary secret + chunking control (fixed size 1–20, random seeded, or "split exactly inside the secret").
- Output visualization: a timeline of chunks as **received** (top row) vs **emitted** (bottom row) with the **hold-back window** shaded; a leak check badge "✓ no secret emitted" computed server-side by searching emitted text for the canary; final equality check "✓ matches one-shot redaction" (split-invariance).

**E. Free-form** — compose any request; shows entire trace and headers exactly as a real client would receive them.

### 8.4 Playground API usage
`POST /admin/api/playground/run | similarity | stream-sim` (TRD B10). Responses contain sanitized text, spans, decisions, timings; never the raw input.

## 9. States (apply to every view)

| State | Presentation |
|---|---|
| **Loading** | Skeleton placeholders matching final layout (cards/rows); charts show a flat shimmer; no spinners over existing data on refresh (swap in place) |
| **Empty (no data yet)** | Illustration-free message + guidance + snippet (Overview), "No traces match filters" + `Clear filters` button (Traces), "Create your first key" CTA (Keys), "No security events in this range ✓" (Audit) |
| **Error (request failed)** | Inline card: what failed, HTTP status, request id, `Retry` button; page remains usable |
| **Stale** | Subtle amber "Last updated 42 s ago — connection issue" in the header; data remains visible |
| **Partial** | If rollups exist but detail rows were purged by retention, show "Details older than 14 days are not retained" |
| **Unauthorized/Session expired** | Redirect to login with message; unsaved modal content is not preserved |
| **Degraded system** | Global banner (embedding model failed → cache bypassed; DB not writable; telemetry dropping) with link to Diagnostics |
| **No providers configured** | Providers page shows setup checklist (env var names, link to docs) |
| **Playground cold model** | "Warming up embedding model…" with disabled Run until `/readyz` OK |

## 10. Responsive Behavior

| Breakpoint | Layout |
|---|---|
| ≥ 1280 px | Sidebar nav, KPI row of 6, two-column charts, drawers 560 px wide |
| 768–1279 px | Collapsible sidebar (icons), KPI 3×2 grid, charts stack in one column pairs, drawers 70% width |
| < 768 px | Top bar with hamburger; KPI cards single column (swipeable carousel optional); tables render as **card lists** (key fields, "Details" button); drawer becomes full-screen sheet; playground input/results stack vertically with sticky Run button; charts reduce to sparklines + "View as table" |
Touch targets ≥ 44 px. No horizontal page scroll; wide tables scroll inside their own container with a sticky first column.

## 11. Accessibility and Security UX

- Keyboard: all actions reachable; visible focus ring; `Esc` closes drawers/modals; focus is trapped in modals and returned on close.
- Semantics: landmarks (`nav`, `main`), `aria-live="polite"` for toasts and stale-state banner, `aria-sort` on sortable headers, charts have text summaries and table toggles.
- Color contrast AA; no information by color alone; respects `prefers-reduced-motion` and `prefers-color-scheme` (default) with manual override stored in `localStorage` (theme only).
- Security: Jinja autoescape everywhere; **model-origin text and any trace text is escaped and rendered as text**, never HTML; CSP `default-src 'self'; script-src 'self' 'nonce-…'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'`; CSRF token on all mutations; cookies `HttpOnly; SameSite=Strict`; clipboard writes only on explicit user action; no raw key in URLs or HTML after the reveal modal closes.
- Privacy: sanitized preview column hidden when `store_prompt_preview=false`; UI shows "preview disabled by policy".

## 12. Microcopy (examples)

| Context | Text |
|---|---|
| Cost savings label | "Equivalent paid-API cost avoided (estimate)" |
| L2 near miss | "Closest cached answer scored 0.89 (needs > 0.92)" |
| Compat mismatch | "Similar question, but the system prompt differs, so the cached answer was not reused" |
| Block | "Blocked by policy `default` (risk 0.91). Matched categories: instruction override, system-prompt extraction." (never quotes the text) |
| Revoke | "Revoke key `fgx-ab12cd34…`? New requests will be rejected immediately." |
| Free quota | "212 of 300 daily requests used (configured cap, below the provider's limit)" |

## 13. Component → Data Mapping (for implementers)

| UI element | Source |
|---|---|
| KPI cards, charts | `metrics_rollup` via `/admin/api/overview` |
| Recent requests/traces | `request_logs` (+ attempts_json) via `/admin/api/traces` |
| Security audit | `security_events` |
| Provider cards/timeline | in-memory `ProviderHealth` + `circuit_events`; quota from `providers` caps + rollups |
| Keys/tenants | `virtual_keys`, `tenants` |
| Cache stats | `CacheEngine.stats` |
| Playground | live pipeline against `__playground__` tenant |

## 14. P1 Expansion Specs (not in MVP)

| Screen | Summary |
|---|---|
| **Cache Explorer** | Browse cache entries per tenant (sanitized query, model, age, TTL, hits, similarity histogram), invalidate by entry/model, threshold what-if simulator replaying recent near-misses |
| **Policy Editor** | Form-based editing of thresholds and per-type actions with diff preview, validation, version hash, rollback; "test against corpus" button |
| **Alerts** | Rules (breaker OPEN > N min, block rate spike, quota > 90%, telemetry dropping) with in-app notifications; optional webhook (local only) |
| **Benchmark Viewer** | Loads `REPORT.md`/result JSON from `integration/benchmarks/reports`, charts before/after, Targets-vs-Measured table |
| **Exports** | CSV/JSON export for traces/audit; PDF report P1+ |
| **React migration** | Optional port using the same `/admin/api` JSON |

## 15. UI Acceptance Checklist (Gate 3)

- [ ] All 5 screens render with seeded data, empty DB, and API-error states.
- [ ] No request leaves `localhost` (browser network tab check + CSP).
- [ ] Raw key visible only in reveal modal; absent from DOM/HTML/log afterwards.
- [ ] Trace drawer shows waterfall, cache, guardrail, routing, token panels for hit, miss, bypass, block and failover examples.
- [ ] Playground dry-run works without any provider key configured.
- [ ] Keyboard-only walkthrough and 320 px viewport pass; AA contrast script green.
