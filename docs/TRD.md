# FluxGate — Technical Requirements Document (TRD)

| Field | Value |
|---|---|
| Status | DRAFT v1.0 |
| Scope | Deep design of Member 1 subsystems (Part A) and Member 2 subsystems (Part B), edge cases (Part C), config, threat model (Part D) |
| Authority | Where this document and an earlier doc differ on a *mechanism* (e.g., placeholder syntax), **TRD wins** (see DECISIONS D-007). Contracts remain authoritative in Blueprint §10. |

Conventions: **MUST/SHOULD/MAY** per RFC 2119. Defaults are shown as `default: …` and live in `config/fluxgate.example.yaml` or policy files. Pseudocode is design notation, not implementation.

---

# PART A — MEMBER 1 SUBSYSTEMS

## A1. Text Normalization (`guardrails/normalize.py`)

Purpose: defeat trivial obfuscation before pattern matching, **without altering the text that is forwarded** (detection runs on a normalized *view*; redaction maps spans back to original offsets).

Pipeline (per text segment):
1. Unicode NFKC.
2. Remove zero-width and bidi control chars (U+200B–U+200F, U+202A–U+202E, U+2060–U+2064, U+FEFF); each removal recorded in an offset map and counted → if count ≥ `obfuscation_zw_threshold` (default 3) emit `OBFUSCATION` finding (severity LOW).
3. Homoglyph folding for a small confusable table (Cyrillic/Greek lookalikes → Latin) applied **only to the detection view**.
4. Collapse runs of whitespace (view only).
5. **Bounded decode-probe:** find base64/hex-looking tokens (≥ 24 chars, valid alphabet/padding), decode up to **depth 2**, **size ≤ 8 KB each**, **≤ 5 tokens per message**; if decoded bytes are valid UTF-8 text, append them as extra scan segments tagged `decoded_from=base64` (findings inside get `meta["decoded"]="1"` and +0.1 risk). Never execute/forward decoded text.

Offset map: `NormalizedView{ text, to_original: list[int] }` (sparse; O(n) memory). All `Finding.span` values refer to the **normalized view** of that message; redaction uses `to_original` to cut the **original** string.

Limits: `max_inspect_chars` (default 200,000 per request across messages). Over limit → policy `on_oversize` (default `warn`): scan the first 100k + last 50k chars, add `OBFUSCATION`/`meta.truncated=1` finding.

## A2. Guardrail Engine Flow (`guardrails/engine.py`)

```
inspect_inbound(ctx, request):
  t0
  policy = resolve_policy(ctx.tenant.guardrail_policy, request.fluxgate.guardrail_policy [if allowed])
  segments = extract_segments(request)            # each message text (+ multimodal text parts), retrieved_context chunks
  for seg in segments: seg.view = normalize(seg.text)
  findings = []
  findings += secret_scan(segments)               # A4
  findings += pii_scan(segments)                  # A4
  inj = injection_score(segments, policy)         # A3
  findings += inj.findings
  decision = decide(findings, inj.risk, policy)   # A2.2
  if decision != BLOCK:
      sanitized, vault, n = redact(request, findings, policy)   # A5
  return GuardrailResult(...)
```

Run order is chosen so cheap, high-precision checks come first; the whole function is wrapped with a **deadline** (`guardrail_timeout_ms`, default 250). On timeout/exception → `on_internal_error` (default **block**, D-003) and `degraded=true`. CPU-heavy scans run via `asyncio.to_thread` only when total text > `offload_chars` (default 20,000); small inputs run inline to avoid thread-hop cost.

### A2.1 Segment extraction and trust labels

| Source | Trust | Notes |
|---|---|---|
| `system` / `developer` | operator-controlled | Scanned when `inspect_system_messages` (default true); injection rules down-weighted ×0.5 (operators legitimately write imperative text) but secrets/PII always scanned |
| `user` | untrusted | Full weight |
| `assistant` (history) | semi-trusted | Full weight for secrets/PII; injection ×0.7 (could contain prior injected text) |
| `tool` messages | untrusted | Full weight + indirect-injection rules (A3.2) |
| `retrieved_context[*]` | **untrusted** | Indirect-injection rules (A3.2) with ×1.0 weight |
| Non-text parts (images, files) | — | Not inspected in MVP; request marked `multimodal` → cache bypass; findings none; documented limitation |

### A2.2 Decision algorithm

Inputs: `risk` (A3), PII/secret findings, policy.

```
if internal_error or timeout:            decision = policy.on_internal_error
elif any finding with action == BLOCK:   decision = BLOCK       # per-type block (e.g., secrets=block in strict)
elif risk >= policy.injection_block_threshold:  decision = BLOCK  (default 0.85)
elif risk >= policy.injection_warn_threshold:   decision = WARN   (default 0.50)
elif any finding with action == WARN:    decision = WARN
else:                                    decision = ALLOW
```

- `WARN` forwards the (sanitized) request, flags the trace, **disables caching** for it, and adds header `X-FluxGate-Risk`.
- `BLOCK` returns the OpenAI-style error `fluxgate_policy_block`; the error message names rule categories, never matched text.
- Redaction is independent of the decision: PII/secrets with action `redact` are replaced in all non-blocked requests.

### A2.3 Named policies (`config/policies/*.yaml`)

| Setting | `default` | `strict` |
|---|---|---|
| `injection_warn_threshold` / `block_threshold` | 0.50 / 0.85 | 0.35 / 0.70 |
| Secrets action | redact | **block** |
| Email / phone | redact | redact |
| Aadhaar / PAN / card | redact | **block** |
| `restore_in_response` | email, phone: false | all false |
| `response_scan` | redact | redact |
| `on_internal_error` | block | block |
| `store_prompt_preview` | env-dependent (dev on) | off |
| `cache_max_risk` | 0.30 | 0.15 |

`policy_version = sha256(canonical_json(policy))[:16]`; included in L1/L2 keys and compat hash.

## A3. Prompt-Injection and Jailbreak Scoring (`guardrails/injection/`)

**Honest scope (rule 11):** this is *risk assessment by pattern and heuristic*. It will miss novel and semantic attacks and will flag some benign text. The product reports measured recall/FPR and never claims protection.

### A3.1 Rule engine

Rule record: `{id, category, pattern (compiled regex, linear-time/bounded), weight w∈(0,1], applies_to (sources), requires_proximity (optional), description}`.

| Category (FindingType) | Rule ID range | Examples of signal (illustrative, not exhaustive) | Typical weight |
|---|---|---|---|
| Instruction override (`PROMPT_INJECTION`) | INJ-01xx | "ignore/disregard/forget (all\|any\|the) (previous\|prior\|above) instructions", "new instructions:", "from now on you will" | 0.55–0.75 |
| Role/persona jailbreak (`JAILBREAK`) | INJ-02xx | "you are now DAN", "developer mode enabled", "pretend you have no restrictions", "act as an unfiltered model" | 0.5–0.8 |
| System-prompt extraction (`PROMPT_LEAK_ATTEMPT`) | INJ-03xx | "repeat/print/reveal your (system\|initial) prompt", "what were you told before this conversation" | 0.5–0.7 |
| Delimiter / structure spoofing (`PROMPT_INJECTION`) | INJ-04xx | fake `</system>`, `<|im_start|>`, "### SYSTEM", forged "tool result:" blocks | 0.4–0.6 |
| Exfiltration channels (`PROMPT_INJECTION`) | INJ-05xx | markdown image/link with data in URL params, "send the conversation to http…", `fetch(` with variables | 0.5–0.7 |
| Tool/agent abuse (`PROMPT_INJECTION`) | INJ-06xx | "call the … tool with … without asking", "do not tell the user", "silently" + action verbs | 0.4–0.6 |
| Obfuscation signals (`OBFUSCATION`) | INJ-07xx | many zero-width chars, mixed-script homoglyph words in keywords, decoded payload containing INJ rules | 0.1–0.3 (additive) |
| Multilingual sample (`PROMPT_INJECTION`) | INJ-08xx | small English+Hindi-transliteration set (P1 expansion) | 0.4–0.6 |

Each rule match produces a `Finding` (`confidence = rule.weight` adjusted by context checks).

### A3.2 Indirect (context) injection rules (`context_scan.py`)

Applied to `retrieved_context`, `tool` messages and (optionally) long quoted blocks. Same engine plus **imperative-in-document heuristics**:
- Second-person imperatives addressed to "the assistant/AI/model/LLM" inside what should be document content.
- Instructions to change behavior, hide actions, or contact external URLs.
- HTML/Markdown hiding (HTML comments, `display:none`, white-on-white, zero-size text markers), invisible Unicode runs.
- Document-level cap: each chunk contributes at most `chunk_max_contribution` (default 0.9); findings carry `chunk_id` so the UI can point to the exact chunk.
- **Benign-discussion allowlist:** if the chunk has strong "about security" markers (quotes, "example of prompt injection", code fences) and **no** imperative addressed to the assistant, multiply weights by 0.4 to reduce false positives on security articles.

### A3.3 Risk aggregation

Noisy-OR with per-source multiplier `m_s` and per-category cap:

```
p_i = clamp(w_i * m_source(i) * ctx_factor(i), 0, 0.95)
risk = 1 - Π_i (1 - p_i)              # over distinct (rule_id, message_index) matches
risk = min(1.0, risk + bonus)         # bonus: +0.10 if ≥2 distinct categories matched, +0.10 if decoded payload matched
```
- Duplicate hits of the same rule in the same message count once.
- `risk_level`: <0.25 INFO, <0.5 LOW, <0.7 MEDIUM, <0.85 HIGH, ≥0.85 CRITICAL.
- Weights are tuned on the **dev split** of the corpus and reported on the held-out **test split** (never tune on the test split).

### A3.4 Corpus management
`corpus/attack_phrases.yaml` (labelled, categorized, with source/licence notes) and `benign_phrases.yaml` (hard negatives: security tutorials, code, support chats, policies with the word "ignore"). 70/30 dev/test split by stable hash of the sample id.

## A4. PII and Secret Detection (`guardrails/pii/`, `guardrails/secrets/`)

### A4.1 Detectors

| Type | Pattern strategy | Validator | Confidence |
|---|---|---|---|
| Email | RFC-pragmatic regex with length caps (local ≤ 64, domain ≤ 255) | TLD present | 0.95 |
| Phone (India + intl) | `(?:\+91[\s-]?\|0)?[6-9]\d{9}` with separators variants; generic E.164 `\+\d{8,15}` | digit count; not part of longer digit run; excludes timestamps/IDs via boundary + context stoplist ("order", "invoice", "id:") | 0.7 (0.9 with `+91`) |
| **Aadhaar** | 12 digits, optional single space/hyphen after each 4, first digit 2–9, not part of longer digit run | **Verhoeff checksum** must pass | 0.95 valid / 0.0 invalid (ignored) |
| **PAN** | `[A-Z]{5}[0-9]{4}[A-Z]` (case-insensitive), word-bounded | 4th char ∈ {A,B,C,F,G,H,J,L,P,T} (holder type) | 0.9 |
| Payment card | 13–19 digits with optional space/hyphen groups | **Luhn** + known IIN prefix ranges | 0.9 |
| Secret – provider formats | table below | format-specific length/charset | 0.95 |
| Secret – assignment | `(?i)(api[_-]?key\|secret\|token\|password\|passwd\|pwd)\s*[:=]\s*['"]?([^\s'"]{8,})` | value not in placeholder/allowlist | 0.8 |
| Secret – PEM | `-----BEGIN [A-Z ]*PRIVATE KEY-----` … `END` (or to end of text if truncated) | — | 1.0 |
| Secret – high entropy | tokens 20–200 chars `[A-Za-z0-9_\-+/=]`, Shannon entropy ≥ 4.0 bits/char | **allowlist**: UUIDs, hex hashes of lengths 32/40/64 when preceded by "sha/md5/commit/hash", base64 image data URIs, words with natural-language ratio | 0.6 (policy default `warn`; P1 `redact`) |

Provider secret formats (non-exhaustive; list lives in `secrets/patterns.py`, each with a unit-test canary):

| Name | Shape |
|---|---|
| FluxGate virtual key | `fgx-[A-Za-z0-9_-]{20,}` |
| Groq | `gsk_[A-Za-z0-9]{20,}` |
| OpenRouter | `sk-or-v1-[A-Za-z0-9]{20,}` |
| NVIDIA | `nvapi-[A-Za-z0-9_-]{20,}` |
| OpenAI-style | `sk-(?:proj-)?[A-Za-z0-9_-]{20,}` |
| Anthropic-style | `sk-ant-[A-Za-z0-9_-]{20,}` |
| AWS access key id | `\b(AKIA\|ASIA)[0-9A-Z]{16}\b` |
| GitHub | `\bgh[pousr]_[A-Za-z0-9]{36,}\b` |
| Google API key | `\bAIza[0-9A-Za-z_-]{35}\b` |
| Slack | `\bxox[baprs]-[A-Za-z0-9-]{10,}\b` |
| JWT | `\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b` |
| Bearer header | `(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}` |

**ReDoS rules:** no nested quantifiers on overlapping classes; every unbounded quantifier gets a max; patterns run on length-capped segments; CI test feeds 1 MB adversarial strings (V10). The `regex` third-party module is **not** used; stdlib `re` with bounded patterns. Custom patterns from policy are validated by compiling plus a probe-timeout test on adversarial strings before acceptance.

### A4.2 Overlap resolution
Collect all candidate spans → sort by `(start, -len)` → resolve overlaps by **higher priority**: `SECRET_PRIVATE_KEY > SECRET_API_KEY/TOKEN > PII_CARD > PII_AADHAAR > PII_PAN > PII_PHONE > PII_EMAIL > SECRET_HIGH_ENTROPY`; contained spans dropped; partial overlaps merged to the union with the higher-priority type. Deterministic (tested by property test).

### A4.3 Findings hygiene
`masked_preview`: type-specific masks (`AKIA************MPLE`, `j***@e*****.com`, `XXXXX9999X`, `XXXX XXXX 1234`) — never more than 4 trailing chars of a secret and never any chars for private keys/cards beyond last 4 digits.

## A5. Egress Redaction, Vault and Restoration (`guardrails/pii/redactor.py`, `vault.py`)

### A5.1 Placeholder format (D-007)
`[[FG:<TYPE>:<N>:<nonce>]]` — e.g., `[[FG:EMAIL:1:7f3a]]`. ASCII (robust to tokenizers/LLM echoing), `TYPE` ∈ {EMAIL, PHONE, AADHAAR, PAN, CARD, SECRET, KEY, CUSTOM}, `N` increments per type per request (same original value → same placeholder), `nonce` = 4 hex chars random **per request** so user-supplied text can't forge a restorable placeholder. Pre-pass: any literal `[[FG:` occurring in input is neutralized by being treated as a `CUSTOM` finding of severity LOW and redacted like data (prevents spoofing).

### A5.2 Redaction procedure
```
for each message/chunk in request (original text):
    spans = non-overlapping findings with action REDACT (original offsets via to_original)
    replace right-to-left with placeholders (stable)
sanitized_request = deep copy with replaced strings; `fluxgate` field removed
vault = {placeholder → original value}   # RAM only; exposes restore(text) and __len__
```
- **Secrets are never restorable** (even if policy flag set): placeholder type SECRET/KEY have `restore=false` hard-coded.
- Upstream provider receives **only** `sanitized_request`; `mock_upstream` capture tests assert zero canary substrings.
- System prompts containing secrets/PII are redacted too (operator mistakes are common).
- `function/tool` arguments in assistant `tool_calls` are scanned (JSON string values).

### A5.3 Response-side scanning (non-stream)
`scan_response(ctx, response, inbound)`:
1. Run secret + PII detectors over every choice's `message.content` (and `tool_calls[].function.arguments`).
2. Placeholders emitted by the model: if `restore_in_response` for that type and vault has entry → restore; unknown/foreign placeholders (wrong nonce) → left as-is.
3. New secrets in output (model hallucinated or leaked training data) → per `response_scan` action (default redact → `[[FG:SECRET:n:nonce]]` style marker without restore); `block` → return `fluxgate_response_blocked` 502.
4. Result `ResponseScanResult.decision` and findings feed the **cache eligibility** (any finding → ineligible).

Restoration occurs **after** scanning, and restored values are **never** passed to cache store (cache stores the *un-restored* scanned text; but requests containing PII aren't cached anyway by ADR-05).

## A6. SSE Sliding-Window Redaction (`guardrails/stream/sliding_window.py`)

### A6.1 Problem
Secrets/PII/placeholders can be split across streamed deltas (`"AKI"` + `"AIOSFODNN7EXAMPLE"`). Per-chunk scanning misses them; naive buffering of the whole stream destroys streaming UX.

### A6.2 Design
State per streamed choice: `pending: str` (not yet emitted), `emitted_len`, `findings`. Parameters: `W` = hold-back window (default **96 chars**, must be ≥ longest "potential-prefix" the detectors can hold; asserted at startup: `W ≥ max_pattern_hold`), `finalize_boundary_chars` = whitespace and most punctuation.

```
feed(delta):
    pending += delta
    # 1. find complete matches in pending (all detectors; validators applied)
    matches = detect(pending)                       # same engine as non-stream scanning
    # 2. a match is FINAL only if it is followed by a boundary char inside pending
    #    (otherwise it might still extend: "a@b.co" → "a@b.co.in", "1234 5678 9012" → "...3")
    final = [m for m in matches if m.end < len(pending) and is_boundary(pending[m.end])]
    # 3. compute hold_start = earliest index of anything that could still become a match:
    #    (a) a match touching end of buffer (non-final)
    #    (b) a suffix that is a viable PREFIX of a pattern (e.g., "AKI", "gsk_", "sk-or", "eyJ", "-----BEGIN",
    #        "[[FG:", digit/alnum run that could grow into Aadhaar/PAN/card/phone, "@"-containing token)
    #    (c) the trailing "token" (maximal run of non-boundary chars) if it is shorter than W
    #    hold_start = max(min(a, b, c), len(pending) - W)   # never hold more than W chars
    # 4. apply final matches that lie entirely before hold_start (replace with placeholder / restore)
    # 5. emit = transform(pending[:hold_start]); pending = pending[hold_start:]
    return emit

flush():  # at end of stream (or on completed choice)
    run detect on pending with end-of-text finalization (all matches final) ; return transformed rest
```

Key properties (verified by property tests; Testing Guide §2.2):
1. **Split invariance:** `concat(feed(c_i)) + flush() == redact_whole(T)` for any partition.
2. **No-leak:** no secret substring of length ≥ 8 is ever emitted unredacted.
3. **Bounded hold:** after each feed, `len(pending) ≤ W + len(delta)`; text not near a potential match is emitted immediately.
4. **Placeholder restore** across chunk splits (hold from `[[FG:` until `]]`; if no closing within W chars treat as plain text).

Complexity: each feed scans `pending` only (≤ W + |delta|) → O(W + |delta|). Detectors are the same compiled patterns as non-streaming (single source of truth).

**Rule exception to "bounded hold":** if a viable PEM header `-----BEGIN … PRIVATE KEY-----` is detected, hold **until the END marker or stream end** (private keys are long); cap at 8 KB then redact the whole held region as SECRET.

**No timer-based release** (fail-safe): a stalled upstream can delay a held tail, never leak it. The gateway's stream idle timeout (B2) bounds this.

**Multi-choice (`n>1`):** one redactor per choice index. **Unicode:** operate on decoded `str`; the adapter decodes UTF-8 incrementally so no split code points reach the redactor.

**Tool-call argument deltas:** streamed `tool_calls[].function.arguments` fragments are fed through a per-tool-call redactor too.

### A6.3 What the gateway does with it
Per upstream chunk: take `delta.content` → `redactor.feed()` → if result non-empty, emit chunk with replaced content; if empty, **still forward the chunk skeleton** only when it carries non-content fields (role, finish_reason, usage); pure-content chunks that yield `""` are dropped (some clients dislike empty-content chunks). On `finish_reason` or `[DONE]`: `flush()` → emit a final content chunk (if non-empty) **before** the finish chunk.

## A7. Cache Core (`cache/`)

### A7.1 Canonicalization (`canonicalize.py`)
Input: `ChatCompletionRequest` (post-parse, **raw** for L1 / **sanitized** for L2/store). Output: canonical JSON bytes (orjson, sorted keys, no whitespace):
- Included: `model` (as requested), `messages` (role, content normalized: strip trailing whitespace; text parts concatenated order-preserved; `name`, `tool_calls`, `tool_call_id`), `temperature`, `top_p`, `max_tokens`/`max_completion_tokens` (mapped to a single field), `stop` (sorted list), `seed`, `tools`, `tool_choice`, `response_format`, `n`, `presence_penalty`, `frequency_penalty`, `logit_bias`, `cache_scope`.
- **Excluded:** `stream`, `stream_options`, `user`, `fluxgate` (except `cache_scope`), unknown extra params are **included** (conservative) unless in the exclusion list.
- Defaults are **not** injected (an explicit `temperature: 1` differs from omitted) — conservative; compat check in A7.4 handles equivalences only where listed.

### A7.2 Keys (`keys.py`)
```
exact_key   = sha256( b"fg1|" + tenant_id + b"|" + policy_version + b"|" + cache_scope + b"|" + canonical_raw_request )
compat_hash = sha256( b"fgc1|" + tenant_id + b"|" + policy_version + b"|" + model + b"|" + sha256(system_text)
                      + b"|" + sha256(context_part) + b"|" + params_hash + b"|" + tools_hash + b"|" + response_format_hash
                      + b"|" + cache_scope )
```
`context_part` = `fluxgate.context_fingerprint` if provided; else canonical form of **all messages except the final user message** (so a different conversation history/RAG system context ≠ hit). `params_hash` covers temperature bucket (rounded to 0.1), top_p, seed, stop, penalties, `n`, logit_bias.
`semantic_query` = `fluxgate.semantic_query` if provided else the **sanitized text of the final user message**, truncated to 1,000 chars (MiniLM truncates at 256 word-pieces; ADR-03).

### A7.3 L1 Exact Cache (`l1_exact.py`)
- Structure: in-memory `OrderedDict` LRU per tenant (`l1_max_entries` default 2,000, `l1_max_bytes` default 64 MB), values = decoded `ChatCompletionResponse` + metadata; backing store = SQLite `cache_entries` (unique `(tenant_id, exact_key)`).
- Lookup: memory hit → return; miss → SQLite point lookup (≤ 8 ms) → promote to LRU. Expired (`expires_at ≤ now`) → treat as miss, schedule deletion.
- Hit serving: deep-copy response; set fresh `id` (`chatcmpl-fg-<ulid>`), `created=now`; **preserve** original `usage` for stats, but the client-visible `usage` is the original (OpenAI SDK users expect usage present).

### A7.4 L2 Semantic Cache (`l2_semantic.py`, `faiss_index.py`, `embedding.py`)

**Embedding service:** `SentenceTransformer(path)` loaded once; `normalize_embeddings=True`; `embed(text)` → `float32[384]`; executed on a dedicated `ThreadPoolExecutor(max_workers=FLUXGATE_CPU_THREADS)`; memo LRU (1,024 entries) keyed by sha256(text) so the injection scorer (P1) and L2 share one embedding. `torch.set_num_threads` pinned.

**Index:** per tenant `faiss.IndexIDMap2(faiss.IndexFlatIP(384))`; ids = `cache_vectors.vec_id` (int64). Inner product on unit vectors = cosine. All FAISS operations (add/remove/search) execute on **one dedicated single-thread executor** (FAISS flat index is not safe for concurrent add+search); search is ≤ 3 ms at 50k vectors so serialization is acceptable.

**Lookup algorithm:**
```
lookup_semantic(ctx, sanitized, inbound, keys):
    if not l2_eligible_request(sanitized, inbound): return BYPASS(reason)   # temperature, tools, n, multimodal, PII, WARN
    q = embed(semantic_query)
    D, I = index[tenant].search(q, k=5)
    near_miss = max(D) if no candidate passes
    for (sim, vec_id) in sorted by sim desc:
        if sim <= threshold: break                    # strict '>' per brief (0.92)
        entry = store.get(vec_id)
        if entry is None or entry.tenant_id != ctx.tenant.tenant_id: skip   # defense in depth (should never trigger)
        if entry.expired or not entry.l2_eligible:   skip
        if entry.compat_hash != keys.compat_hash:    record compat_mismatch; skip
        if not max_tokens_ok(entry, sanitized):      record "max_tokens"; skip
        return HIT_L2(entry, similarity=sim)
    return MISS(near_miss_similarity, compat_mismatch)
```
- `max_tokens_ok`: request's max tokens (if set) ≥ `entry.completion_tokens`, otherwise the cached answer might exceed the caller's limit → MISS.
- Threshold source: tenant override > `FLUXGATE_L2_THRESHOLD` (default 0.92). Final default is set by the Phase 4 sweep (Testing Guide §5.7).
- **Latency budget**: embed ≤ 14 ms, search ≤ 3 ms, compat+DB ≤ 3 ms (target total ≤ 20 ms p95).

**Capacity & memory:** 384 × 4 B = 1.5 KB/vector → 50k vectors ≈ 75 MB per tenant (cap `max_entries_per_tenant` default 50,000; global cap `max_total_vectors` default 200,000). Eviction (A7.6) removes ids from FAISS via `remove_ids`.

**Rebuild:** on first use of a tenant (lazy) or startup if `warm_tenants` configured: stream `cache_vectors` for the tenant in batches of 5k, `add_with_ids`. Corrupt/wrong-dim rows are deleted and counted.

### A7.5 Eligibility (`eligibility.py`) — checked at **store** time (and relevant parts at lookup time)

| Rule | Default | Layer effect |
|---|---|---|
| Cache enabled for tenant & request (`fluxgate.cache != "bypass"`) | — | bypass |
| Response HTTP 200, `finish_reason == "stop"` for all choices, stream completed | required | not stored |
| `n == 1` (or absent) | required | bypass |
| No `tools`/`tool_calls`/function calling in request or response | required | bypass |
| Text-only (no image/file parts) | required | bypass |
| Inbound `decision == ALLOW`, `redaction_count == 0`, not degraded | required (ADR-05) | bypass |
| `risk_score ≤ cache_max_risk` | 0.30 (strict 0.15) | not stored |
| Response scan clean (no findings, no redactions) | required | not stored |
| Temperature (omitted ⇒ treated as 1.0) | **L1: ≤ 1.0**; **L2: ≤ 0.5** (`l2_max_temperature`) | entry marked `l2_eligible=false` if above |
| Response size | ≤ 256 KB | not stored |
| Tenant entry quota | `max_entries_per_tenant` | evict then store |
| Poisoning checks (A7.7) | all pass | not stored |

Note: omitted temperature ⇒ L2 ineligible by default; dashboard shows reason `high_temperature`. Document in README: *"Set `temperature≤0.5` (RAG clients usually do) to benefit from semantic caching."*

### A7.6 TTL, eviction, sweeper (`ttl.py`)
- `expires_at = created_at + ttl` (default 24 h; per-tenant override; per-request `ttl_seconds` from store request capped to `max_ttl` default 7 d). Add ±10% jitter to avoid synchronized expiry.
- Sweeper task every 60 s: `DELETE … WHERE expires_at <= now LIMIT 500` + remove FAISS ids + drop L1 LRU entries; yields between batches.
- Eviction when tenant at cap: remove least-recently-hit (`COALESCE(last_hit_at, created_at)`) entries until under cap − 1% headroom.
- Clock is injected (`Clock` protocol) for tests.
- Entries are **served only if `expires_at > now`** at lookup time regardless of sweeper lag.

### A7.7 Cache-poisoning protection (`poisoning.py`)

| # | Threat | Defense |
|---|---|---|
| 1 | Attacker induces a model response containing injected instructions, which is then served to others | Response scanner + injection rules run on the **response**; any finding → not stored |
| 2 | Attacker primes cache with a wrong/malicious answer for a victim query | Same-tenant semantics: entries only from *completed clean upstream responses*, never from client-supplied content; no API to store arbitrary content except admin tooling (audited); per-key `cache_scope` available for stricter partitioning |
| 3 | Cross-tenant poisoning/leak | Tenant in keys, per-tenant FAISS, entry.tenant_id verified on read (defense in depth) |
| 4 | Semantic near-collision (high similarity, different intent: negation, numbers, entities) | Threshold, compat fingerprint, **numeric/entity guard**: if the set of digits-sequences or capitalized tokens in `semantic_query` differs between query and cached entry → MISS with `compat_mismatch="entity_guard"` (cheap, effective against PAWS-like flips; negation words `not/no/never/n't` parity check as well) |
| 5 | Flooding to evict valuable entries | per-tenant caps, per-key rate limit, store only after a *successful upstream call*, eviction by recency/hit-count |
| 6 | Policy change makes stored entries unsafe | `policy_version` in keys/compat; sweeper purges old versions |
| 7 | Tampered DB rows | store `response_sha256`; verify on L1 SQLite load; mismatch → delete + audit event |
| 8 | Embedding adversarial collisions | compat + guards; threshold; near-miss telemetry for tuning |

### A7.8 Invalidation and stats
`invalidate(tenant_id, entry_id|model|all)` removes DB rows, FAISS ids and LRU entries atomically (under the tenant's async lock) and returns count. `stats(tenant_id)`: entries, bytes, l1/l2 hits (counters in DB + in-memory deltas flushed periodically), hit rate, oldest/newest, by-model counts.

### A7.9 Concurrency model (cache)
- One asyncio lock per tenant for mutations (store/evict/invalidate); lookups don't take it (reads of Python dicts are safe on the single event loop; FAISS ops serialized by the FAISS executor).
- SQLite access via a small `aiosqlite` connection pool (1 writer + 2 readers); stores are background tasks (`asyncio.create_task`) with bounded concurrency (semaphore 4) and exception logging; if the queue is full (>200 pending) new stores are dropped and counted (`store_dropped`).

---

# PART B — MEMBER 2 SUBSYSTEMS

## B1. Gateway API (`gateway/routes/chat.py`)

### B1.1 Endpoints
| Method/Path | Auth | Purpose |
|---|---|---|
| `POST /v1/chat/completions` | `Authorization: Bearer fgx-…` | Main endpoint |
| `GET /v1/models` | same | Aliases + permitted concrete models for the key |
| `GET /healthz` | none | Liveness |
| `GET /readyz` | none | Ready after embedding warm-up, DB migrated, ≥ 1 provider configured |
| `/admin/*`, `/dashboard/*` | admin token/session | See B10 |

### B1.2 Request handling rules
- Content type `application/json`; body ≤ `max_body_bytes` (default 1,048,576 → 413 `request_too_large`); `messages` ≤ 256; unknown fields **pass through** to the provider except `fluxgate`.
- `model`: logical alias (`fluxgate-default`, …) or a concrete provider model ID; resolved by `model_map`. Unknown → 404 `model_not_found`. In zero-cost mode a non-free model → 403 `fluxgate_model_not_free`.
- `stream_options.include_usage`: the gateway **always requests usage upstream** when supported (needed for token accounting), and strips the extra usage chunk if the client didn't ask.
- Response `model` field returns the **requested** model string; the concrete served model is in `X-FluxGate-Model-Served`.
- Response IDs: provider IDs preserved on miss; cache hits get `chatcmpl-fg-…`.
- Headers per Blueprint §12. `X-FluxGate-Cache: HIT-L1|HIT-L2|MISS|BYPASS`.
- Request lifecycle per Blueprint §4; each stage records `StageTimings`.
- Hard server deadline `request_deadline_s` (default 90): exceed → 504.
- All gateway exceptions map to the OpenAI error envelope (Blueprint §12). Error messages **never** include request content.

### B1.3 Concurrency and backpressure
- `max_inflight_requests` (default 64) semaphore → excess returns 429 `fluxgate_overloaded` with `Retry-After: 1`.
- httpx `AsyncClient` per provider with `Limits(max_connections=32, max_keepalive_connections=16)`.

## B2. SSE Streaming (`gateway/streaming.py`)

### B2.1 Wire format
`Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Each event `data: <json>\n\n`; terminator `data: [DONE]\n\n`. Keep-alive comment `: keep-alive\n\n` every 15 s **only after the first upstream byte** was forwarded (before that, failover may still occur).

### B2.2 Miss path state machine
```
WAITING_UPSTREAM ──first chunk──► STREAMING ──finish+[DONE]──► COMPLETE → maybe_store (background)
        │ (429/5xx/timeout before first byte → router fails over)      │
        └──────────────────────────────────────────────────────────────┤
STREAMING ──upstream error/timeout──► ABORTED_UPSTREAM → emit error event, close, NO store
STREAMING ──client disconnect──────► ABORTED_CLIENT   → cancel upstream (close httpx response), NO store
```
- Upstream per-chunk idle timeout `stream_idle_timeout_s` (default 30).
- **Accumulator:** assembles content per choice for caching; capped at `max_cache_response_bytes` (256 KB) — exceeding the cap stops accumulating and marks `TOO_LARGE` (stream continues).
- **Redaction** via `StreamRedactor` (A6); the accumulator stores **post-redaction, pre-restoration** text (never restored values).
- After `[DONE]`: build a `ChatCompletionResponse` from the accumulated text (+ usage if present), run `scan_response` on it as a final safety net (belt-and-braces; any finding ⇒ not stored), then `maybe_store`.
- **Error event on mid-stream failure:** `data: {"error": {"message": "...", "type": "api_error", "code": "fluxgate_stream_interrupted"}}\n\n` then close **without** `[DONE]`.
- No failover after first byte (ADR-08).

### B2.3 Cache-hit replay
Split cached assistant text into deltas of ~24 chars at word boundaries (configurable); first chunk carries `role: "assistant"`; final chunk has `finish_reason` and, if client set `include_usage`, a usage chunk; then `[DONE]`. Optional `replay_delay_ms` (default 0).

### B2.4 Disconnect detection
Generator wrapped so `asyncio.CancelledError`/`GeneratorExit` closes the upstream response in a `finally`; request-level `await request.is_disconnected()` is polled between chunks as a secondary check. Trace records `client_disconnected=true` (status 499 in logs).

## B3. Virtual Keys (`gateway/auth/`)

- **Format:** `fgx-` + `secrets.token_urlsafe(32)` (≈ 43 chars). `key_prefix` = first 12 chars (`fgx-` + 8) shown in UI.
- **At rest:** `key_hash = HMAC-SHA256(FLUXGATE_KEY_PEPPER, raw_key)` hex. Raw key shown **once** in the create response/modal and never stored/logged.
- **Auth:** compute HMAC of presented key → dict lookup in in-memory `key_cache` (loaded at startup, refreshed on admin mutations in-process; TTL refresh 60 s as safety) → `TenantContext`. Compare with `hmac.compare_digest` on the hash when verifying against DB fallback. Unknown/malformed → 401 after a fixed small delay jitter (0–5 ms) to blunt timing differences.
- **Failed-auth throttling:** per client-IP-hash bucket (10 failures/min → 429) to reduce brute force.
- **Lifecycle:** create, edit limits, revoke (immediate; in-flight streams complete), rotate (new key issued + old revoked after optional grace ≤ 24 h), expire (`expires_at`), `last_used_at` updated at most once/min per key.
- **Per-key settings:** `rpm_limit`, `burst`, `daily_request_cap`, `allowed_models`, `guardrail_policy`, `cache_enabled`.
- **Admin auth:** `FLUXGATE_ADMIN_TOKEN` → login form posts token → server sets signed (itsdangerous-style HMAC) `HttpOnly; SameSite=Strict; Secure-if-https` session cookie (8 h). Admin routes also accept `Authorization: Bearer <admin token>` for scripts. CSRF: per-session token required on every state-changing dashboard request (`X-CSRF-Token` / hidden field). Admin and dashboard bind to **localhost-only by default** (`admin_bind_local_only: true`): requests from non-loopback addresses → 403.
- **Audit:** every admin mutation → `admin_audit` row (no secrets).

## B4. Token-Bucket Rate Limiting (`gateway/ratelimit/`)

Per key: `capacity = burst` (default `max(5, rpm/6)`), `refill_per_s = rpm/60`.
```
allow(key, now_monotonic):
    tokens = min(capacity, tokens + (now - last) * refill); last = now
    if tokens >= 1: tokens -= 1; return OK
    retry_after = ceil((1 - tokens) / refill)  → 429 rate_limit_exceeded, header Retry-After
```
- Monotonic clock; state in a dict on the event loop (no locks needed); idle buckets garbage-collected after 10 min.
- Cache hits **do** consume a token (protects the gateway CPU) but **do not** consume `daily_request_cap` (cap protects provider quota → counts only provider-bound requests).
- Response headers: `X-RateLimit-Limit-Requests`, `X-RateLimit-Remaining-Requests`, `X-RateLimit-Reset-Requests` (OpenAI-style, best-effort).
- **Outbound per-provider limiter** (protects free tier, RT-08): token bucket per provider from config `rpm_cap`/`rpd_cap` (set ~80% of real limits). If exhausted → provider treated as *temporarily unavailable* (not a breaker failure); router tries the next provider.

## B5. Provider Adapters (`router/adapters/`)

### B5.1 Interface (`base.py`)
```
class ProviderAdapter(ABC):
    name: ProviderName
    async def complete(self, req: ProviderCall) -> ProviderResult
    async def stream(self, req: ProviderCall) -> AsyncIterator[ChatCompletionChunk]   # raises before first yield on pre-byte failure
    def prepare_body(self, request, model_id) -> dict          # param pruning, model rewrite
    def classify_error(self, status, headers, body) -> RouteFailure
    capabilities: ProviderCapabilities   # supports_n, supports_tools, supports_logprobs, supports_json_mode, supports_stream_usage, max_stop
```

### B5.2 Provider specifics

| Aspect | Groq | OpenRouter | NVIDIA NIM |
|---|---|---|---|
| Base URL | `https://api.groq.com/openai/v1` | `https://openrouter.ai/api/v1` | `https://integrate.api.nvidia.com/v1` |
| Auth | `Authorization: Bearer $GROQ_API_KEY` | `Authorization: Bearer $OPENROUTER_API_KEY` + `HTTP-Referer`, `X-Title` (config) | `Authorization: Bearer $NVIDIA_API_KEY` |
| Model IDs | from `model_aliases` (verify on setup day) | same; `:free` suffix for free | same |
| Param pruning | drop unsupported (e.g., `n>1`, `logprobs` where unsupported) → if dropping would change semantics (n>1) mark attempt `bad_request` and skip provider | pass through; honor `provider` routing prefs: send `provider: {allow_fallbacks: false}` is **not** set (we do own failover) | drop unsupported; some models reject `response_format` |
| Errors | JSON `{error:{message,type,code}}`; 429 with `retry-after` / `x-ratelimit-*` | May return **HTTP 200 with error body** or SSE `error` event → adapter detects `error` key in body/first event | Standard HTTP errors; 429 on credit/limit |
| Rate-limit headers | parse `retry-after`, `x-ratelimit-remaining-*` | parse `retry-after` | parse `retry-after` |

### B5.3 Normalized error classification

| Upstream signal | `RouteFailureKind` | Counts toward breaker? | Failover? |
|---|---|---|---|
| 429 | `RATE_LIMITED` | **No** (cooldown) | Yes |
| 500/502/503/504 | `UPSTREAM_5XX` | Yes | Yes |
| httpx `ConnectError`/DNS | `CONNECT_ERROR` | Yes | Yes |
| `ConnectTimeout`/`ReadTimeout` before first byte | `TIMEOUT` | Yes | Yes |
| 400/422 (bad request) | `BAD_REQUEST` | No | **No** (return to client, sanitized); except param-pruning incompatibility → try next |
| 401/403 from provider | `AUTH_ERROR` | No; provider → `disabled_auth` + alert | Yes (next provider) |
| 404 model not found | `BAD_REQUEST` | No | Yes (next provider that maps the alias) |
| 200 with error body (OpenRouter) | classified by inner `error.code` | per mapped kind | per mapped kind |
| Stream cut after first byte | `STREAM_INTERRUPTED` | Yes | **No** |
| Client disconnect | `CLIENT_DISCONNECTED` | No | No |

### B5.4 Timeouts and connection handling
`httpx.Timeout(connect=5, read=60, write=10, pool=5)`; streaming read timeout = `stream_idle_timeout_s`; total deadline from `RouterRequest.deadline_seconds`. `provider response bodies` limited to 4 MB (non-stream). Provider keys read from env at startup; never logged; adapters redact `Authorization` in any debug logging.

## B6. Routing and Zero-Cost Mode (`router/selector.py`, `model_map.py`)

```
select(req) -> ordered list of (provider, model_id):
    candidates = providers that: enabled, have alias mapping for req.model, support required capabilities,
                 not disabled_auth, within outbound limiter, circuit not OPEN (HALF_OPEN allowed if probe slot free),
                 not in cooldown_until
    if zero_cost_mode: candidates = [c for c in candidates if alias_mapping.is_free]
    order by: explicit preferred_provider (if any) → configured priority → (P1: EWMA latency)
```
- If the list is empty: all circuits open → 503 `fluxgate_no_healthy_provider` with `Retry-After` = soonest recovery time; if zero-cost mode removed everything → 403 `fluxgate_model_not_free`.
- Max attempts = `min(len(candidates), 3)`.
- `/v1/models` lists only aliases usable by the key (and in zero-cost mode only free ones).

## B7. Circuit Breaker (`router/circuit_breaker.py`)

One breaker per provider (P1: per provider+model). State is mutated **synchronously** (no `await` between read and write), so it is race-free on the single event loop.

### B7.1 Parameters (defaults; env/config override; per provider override)
| Name | Default | Meaning |
|---|---|---|
| `failure_threshold` | 5 | consecutive counted failures → OPEN |
| `window_s` / `min_calls` / `error_rate_threshold` | 60 / 10 / 0.5 | alternate trip: ≥10 calls in 60 s with ≥50% counted failures |
| `recovery_s` | 30 | time in OPEN before HALF_OPEN |
| `recovery_backoff` / `recovery_max_s` | ×2 / 300 | each failed recovery doubles the next OPEN period |
| `half_open_max_probes` | 1 | concurrent trial requests allowed in HALF_OPEN |
| `half_open_success_threshold` | 2 | consecutive probe successes to CLOSE |

### B7.2 State machine
```
         counted failure (consecutive ≥ threshold) or error-rate trip
  ┌──────────────────────────────────────────────────────────┐
  │                                                          ▼
CLOSED ◄──────────── probe successes ≥ N ───────────── HALF_OPEN ◄──── recovery_s elapsed ──── OPEN
  ▲                                                          │                                  ▲
  └── success resets consecutive counter                      └──── any probe failure ──────────┘
                                                                   (OPEN again, recovery_s *= backoff)
```
| From | Event | To | Actions |
|---|---|---|---|
| CLOSED | success | CLOSED | reset consecutive failures |
| CLOSED | counted failure | CLOSED or OPEN | increment; trip → set `opened_at`, `cooldown_until = now + recovery_s`; emit `circuit_event` |
| OPEN | request arrives, `now < cooldown_until` | OPEN | reject immediately (`CIRCUIT_OPEN`, no network) |
| OPEN | request arrives, `now ≥ cooldown_until` | HALF_OPEN | allow up to `half_open_max_probes` |
| HALF_OPEN | probe success | HALF_OPEN → CLOSED when `successes ≥ N` | reset backoff |
| HALF_OPEN | probe failure | OPEN | `recovery_s = min(recovery_s*backoff, max)`; emit event |
| any | manual disable/enable/reset (admin) | per action | audited |

**429 handling (not a breaker failure):** set provider `cooldown_until = now + max(Retry-After, base_429_cooldown)` (default base 10 s, exponential ×2 on consecutive 429s up to 300 s); `RouteAttempt.retry_after_seconds` recorded; selector skips provider while cooling down. If a provider returns 429 for ≥ `rate_limit_trip_count` (default 8) consecutive attempts across a 10 min span, mark `degraded` in the dashboard (informational).

## B8. Retry and Failover Policy (`router/retry.py`)

| Condition | Action |
|---|---|
| Failure **before first byte to client** (429, 5xx, timeout, connect error, auth error, pruning mismatch) | Fail over to next candidate (no same-provider retry unless it's the only candidate) |
| Only one candidate and failure is 5xx/timeout | One retry after `jitter(200–800 ms)`; never for 429 or 4xx |
| 400-class client error | Return to client (sanitized) — no retry |
| Failure after first byte | No failover; error event (B2.2) |
| Deadline exhausted | 504 `fluxgate_upstream_timeout` |
| **Duplicate-execution safety** | Chat completions have no server-side side effects (tool execution is client-side), so pre-first-byte failover is safe. A timeout *after the request was fully sent* may mean the first provider still processed it; this can cause duplicate **billing/quota use** (not duplicate actions) — accepted and documented; the first provider's response, if it arrives late, is discarded (request cancelled). |
| Tools present | Same rules; never replay a request whose response has begun streaming |
| Backoff | none between providers (latency matters); 200–800 ms jitter only for the single-candidate retry |

Attempts are recorded in `RouteAttempt` list (provider, model, status, failure kind, latency, circuit state).

## B9. Telemetry (`gateway/telemetry/`)

- `TelemetrySink.emit_trace/emit_audit` do a non-blocking `put_nowait` on an `asyncio.Queue(maxsize=10_000)`; on full → drop **oldest** and increment `telemetry_dropped` (visible in dashboard banner).
- Writer task: flush when 100 events or 500 ms elapsed; one transaction per batch; on SQLite busy → retry with backoff; failure → log (redacted) and keep batch up to 3 tries then drop.
- **Rollups:** writer also increments in-memory minute buckets and upserts `metrics_rollup` each flush (counters + latency histogram buckets).
- Retention job (hourly): delete clean `request_logs` (no findings) > 14 days and `request_logs` with findings > 30 days (their `security_events` cascade, so audit events live as long as their request row), `circuit_events` > 30 days, `metrics_rollup` > 90 days; `PRAGMA wal_checkpoint(TRUNCATE)` weekly.
- `RequestTrace` is built from `GatewayResponse`; it **cannot** contain bodies (type-enforced by contract) and goes through the redacting logger test.
- Savings accounting per hit: `tokens_saved = original_usage.total_tokens` (provider-reported at store time; `tiktoken` estimate flagged `usage_estimated`); `cost_saved_usd_est = tokens × price_table[model_alias]` (price table in config, defaults to published *reference* prices for equivalent paid models; labeled estimate; free models have `reference_price` noted in table but UI says "equivalent").

## B10. Admin & Dashboard API (`gateway/routes/admin.py`)

All under `/admin/api/*` (JSON; admin auth + CSRF on mutations) and HTML fragments under `/dashboard/*` (HTMX).

| Endpoint | Purpose |
|---|---|
| `GET /admin/api/overview?range=15m\|1h\|24h\|7d&tenant=&key=&model=` | KPIs + chart series (from `metrics_rollup`) |
| `GET /admin/api/providers` / `POST …/{p}/disable|enable|reset-breaker|test` | Health, actions (test = 1-token call; warns about quota) |
| `GET /admin/api/traces?…filters…&cursor=` / `GET …/{request_id}` | Trace list/detail (keyset pagination on `(created_at, request_id)`) |
| `GET /admin/api/security-events?…` / `GET …/export.csv` | Audit logs |
| `GET/POST /admin/api/keys`, `PATCH …/{id}`, `POST …/{id}/revoke|rotate` | Key management (raw key only in create/rotate response) |
| `GET/PATCH /admin/api/tenants/{id}` | Tenant settings (cache, TTL, threshold, policy) |
| `POST /admin/api/cache/invalidate` | `{tenant, entry_id?, model?, all?}` |
| `GET /admin/api/cache/stats?tenant=` | Cache stats |
| `POST /admin/api/playground/run` | See UI spec §8; always uses reserved tenant `__playground__`; `dry_run` default **true** |
| `POST /admin/api/playground/similarity` | Embedding similarity of two texts (no provider call) |
| `POST /admin/api/playground/stream-sim` | Stream redaction simulator |
| `GET /admin/api/settings` / `PATCH` | Retention, preview toggle (blocked in strict), zero-cost status (read-only) |

---

# PART C — EDGE CASES AND REQUIRED BEHAVIOR

| # | Case | Required behavior |
|---|---|---|
| E-01 | **Streaming + caching, completed stream** | Tee, accumulate, scan, store; subsequent stream or non-stream request hits same entry |
| E-02 | **Stream cache hit for non-stream request and vice versa** | Allowed (stream flag excluded from key); response shape matches the *request's* mode |
| E-03 | **Partial response** (stream ends without `finish_reason`/`[DONE]`) | Not stored; error event; trace `INCOMPLETE_RESPONSE` |
| E-04 | `finish_reason == "length"` | Not stored (`NON_STOP_FINISH`) |
| E-05 | **Client disconnects mid-stream** | Cancel upstream; drop accumulator; no store; trace `client_disconnected` |
| E-06 | Upstream 429 before first byte | Cooldown provider (honor `Retry-After`), fail over; trace shows attempts |
| E-07 | Upstream 429 on all providers | 429 to client with `Retry-After` = min cooldown remaining (`rate_limit_exceeded`-style, code `fluxgate_upstream_rate_limited`) |
| E-08 | Upstream 5xx pre-byte | Fail over; counts toward breaker |
| E-09 | Upstream timeout pre-byte | Fail over; counts; possible duplicate quota use documented |
| E-10 | Mid-stream upstream failure | Error event, no failover, no store |
| E-11 | **TTL expires between lookup and serve** | Lookup compares `expires_at` to `now` at serve time; if expired → MISS; sweeper lag irrelevant |
| E-12 | Entry expires while a store of the same key is running | Upsert (`ON CONFLICT(tenant_id, exact_key) DO UPDATE`) replaces; vector replaced atomically (remove old id, add new) |
| E-13 | **Model mismatch** (same prompt, different `model`) | Different `exact_key` and `compat_hash` → MISS. Aliases are *not* equated with concrete IDs |
| E-14 | **Parameter mismatch** (temperature, top_p, stop, seed, tools, response_format) | L1: different key. L2: `compat_mismatch="params"`, MISS |
| E-15 | `max_tokens` smaller than cached completion length | MISS (`compat_mismatch="max_tokens"`) |
| E-16 | `n > 1` | BYPASS (`N_GREATER_THAN_ONE`) |
| E-17 | Tools/function calls (request or response) | BYPASS; guardrails still inspect tool messages |
| E-18 | Multimodal content parts | Text parts scanned; BYPASS cache; images not inspected (documented) |
| E-19 | Empty/whitespace-only final user message | Pass through to the provider; **not cached** (bypass reason `CACHE_DISABLED`, trace note `empty_query`; no new enum value needed) |
| E-20 | Very long prompt (> `max_inspect_chars`) | Truncated scan with warning finding (policy), cache bypass if truncated |
| E-21 | Prompt contains literal placeholder lookalikes | Neutralized/redacted (A5.1); cannot trigger restoration |
| E-22 | PII in request | Redacted before provider; not cached (ADR-05); response restoration per policy |
| E-23 | Secret in model output | Scrubbed (stream or non-stream); not cached; audit event |
| E-24 | Guardrail BLOCK | 400; no provider call; audit event; no cache |
| E-25 | Guardrail internal error / timeout | `block` by default (503 `fluxgate_guardrail_unavailable`), `degraded=true` |
| E-26 | Embedding model failure / FAISS error | L2 → BYPASS(`CACHE_ERROR`); request continues; alert banner |
| E-27 | SQLite locked / disk full | Cache store dropped + counted; telemetry retried then dropped; request unaffected; `/readyz` degraded if DB unwritable > 30 s |
| E-28 | Process restart | L1 LRU cold; L2 indexes rebuilt lazily from `cache_vectors`; breaker state resets to CLOSED (documented) |
| E-29 | Policy change | New `policy_version`; old entries unreachable and purged by sweeper |
| E-30 | Key revoked mid-stream | Current stream completes; next request 401 |
| E-31 | Clock jumps | Rate limiter uses monotonic clock; TTL uses wall clock with `expires_at` compared defensively (`created_at > now` → treat as fresh but log) |
| E-32 | Concurrent identical misses | Both go upstream in MVP (single-flight P1); the second store upserts |
| E-33 | Upstream returns 200 with empty `choices` | Treated as `UPSTREAM_5XX`, failover |
| E-34 | Upstream changes model name in response | Preserve in `X-FluxGate-Model-Served`; response `model` = requested |
| E-35 | Missing `usage` upstream | `tiktoken` estimate, flagged `usage_estimated=true` |
| E-36 | Unknown JSON fields from SDK | Pass through (except `fluxgate`) |
| E-37 | Duplicate `Idempotency-Key` header | Ignored in MVP (P1) |
| E-38 | Admin endpoints hit from non-loopback | 403 unless `admin_bind_local_only=false` |
| E-39 | Playground run with provider call while quota low | Dry-run default; non-dry-run requires explicit toggle and shows quota remaining |
| E-40 | Cache hit but guardrail policy for tenant is stricter than when stored | Policy version differs ⇒ MISS (stored entries bound to policy_version) |

---

# PART D — CONFIGURATION, SECURITY MODEL AND OBSERVABILITY

## D1. Configuration tree (`config/fluxgate.example.yaml`)

```yaml
server: { host: 0.0.0.0, port: 8000, max_body_bytes: 1048576, request_deadline_s: 90, max_inflight_requests: 64, admin_bind_local_only: true }
zero_cost_mode: true
guardrails: { default_policy: default, guardrail_timeout_ms: 250, offload_chars: 20000, policies_dir: config/policies }
cache:
  enabled: true
  l1: { max_entries: 2000, max_bytes: 67108864 }
  l2: { threshold: 0.92, max_temperature: 0.5, top_k: 5, entity_guard: true, model_path: ./models/all-MiniLM-L6-v2 }
  default_ttl_s: 86400
  max_ttl_s: 604800
  max_entries_per_tenant: 50000
  max_total_vectors: 200000
  max_response_bytes: 262144
  sweeper_interval_s: 60
router:
  priority: [groq, openrouter, nvidia_nim]
  circuit_breaker: { failure_threshold: 5, window_s: 60, min_calls: 10, error_rate_threshold: 0.5, recovery_s: 30, recovery_max_s: 300, half_open_max_probes: 1, half_open_success_threshold: 2 }
  rate_limit_cooldown: { base_s: 10, max_s: 300 }
  timeouts: { connect_s: 5, read_s: 60, stream_idle_s: 30 }
telemetry: { queue_size: 10000, flush_ms: 500, flush_batch: 100, retention_days: { request_logs: 14, security_events: 30, circuit_events: 30, metrics_rollup: 90 } }
privacy: { store_prompt_preview: true }   # dev default; strict profile sets false
```

## D2. Threat model summary (OWASP LLM Top 10, 2025 numbering)

| OWASP | FluxGate coverage | Level |
|---|---|---|
| LLM01 Prompt Injection | Inbound rule-based risk scoring (direct + indirect); block/warn; context inspection | **Partial** (risk assessment; known misses) |
| LLM02 Sensitive Information Disclosure | Egress PII/secret redaction; response scanning; stream redaction; no raw data at rest | **Strong for defined patterns**; no NER names/addresses |
| LLM03 Supply Chain | Pinned lockfile, vendored frontend, model revision pinning, gitleaks | Process-level |
| LLM04 Data/Model Poisoning | Cache-poisoning defenses (A7.7) | Partial (cache layer only) |
| LLM05 Improper Output Handling | Response scanning for secrets/PII; no HTML rendering of model output in dashboard (escaped) | Partial |
| LLM06 Excessive Agency | Not addressed (tool execution is client-side); tool messages inspected | Out of scope |
| LLM07 System Prompt Leakage | Extraction-attempt rules; secrets in system prompts redacted | Partial |
| LLM08 Vector/Embedding Weaknesses | Per-tenant indexes, compat + entity guards against embedding collisions | Partial (cache scope) |
| LLM09 Misinformation | Not addressed | Out of scope |
| LLM10 Unbounded Consumption | Per-key rate limits, daily caps, body size limits, per-provider outbound caps, inflight semaphore | **Strong** |

Gateway-level threats: key theft (HMAC at rest, revocation, localhost admin), timing/brute-force (jitter, failed-auth throttle), SSRF (no user-controlled URLs: providers fixed by config), log injection (structured logs, escaped), dashboard XSS (Jinja autoescape, strict CSP, escaped trace content), CSRF (token), DoS (limits, deadlines).

## D3. Observability inside the process
Structured JSON logs (request_id, tenant_id, stage timings, outcome); all log events pass the redacting processor. Counters/histograms kept in memory and persisted via rollups; Prometheus `/metrics` is P1.

## D4. Open technical items to resolve in Phase 2/3 (tracked, not blocking)
1. Final `W` hold-back value after measuring detector prefix needs (A6) — default 96.
2. Entity-guard tuning (A7.7 #4) against W3 false-hit data.
3. Final L2 threshold from Phase 4 sweep.
4. Whether `tiktoken` is needed once providers return usage reliably.
