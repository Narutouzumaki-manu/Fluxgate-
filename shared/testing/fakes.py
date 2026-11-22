"""Test fakes — FakeGuardrailEngine, FakeCacheEngine, FakeRouter.

These fakes implement the Protocol interfaces defined in shared/contracts/ and are
used in:
  - tests/contract/test_protocol_conformance.py (fake-vs-protocol conformance)
  - tests/integration/ (full pipeline with fake M1 engines)
  - scripts/verify_m1.py V1 (contract conformance with real engines)

Design rules (Blueprint §11, TESTING_AND_BENCHMARK_GUIDE.md §4):
  1. Fakes implement EXACTLY the Protocol interface — no extra public methods.
  2. Fakes must pass the SAME conformance test suite as real implementations.
  3. Fakes are configurable (inject scenario outcomes) but keep zero real logic.
  4. No network, no filesystem, no asyncio.sleep — only in-memory state.

Canonical scenarios available via FakeScenario enum:
  CLEAN_ALLOW      — clean request, ALLOW decision, no findings
  PII_REDACT       — PII detected, ALLOW+redact
  INJECTION_WARN   — injection risk 0.6, WARN decision
  INJECTION_BLOCK  — injection risk 0.90, BLOCK decision
  INTERNAL_ERROR   — guardrail raises (tests degraded path)
  CACHE_L1_HIT     — L1 exact cache hit
  CACHE_L2_HIT     — L2 semantic cache hit (similarity 0.95)
  CACHE_MISS       — cache miss
  CACHE_BYPASS     — bypass (high temperature)
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from shared.contracts.cache import CacheKeys, CacheResult, CacheStoreRequest, StoreDecision
from shared.contracts.context import RequestContext
from shared.contracts.enums import (
    CacheBypassReason,
    CacheOutcome,
    CircuitState,
    ContentSource,
    Decision,
    FindingType,
    GuardrailStage,
    ProviderName,
    RedactionAction,
    Severity,
)
from shared.contracts.guardrails import (
    Finding,
    GuardrailPolicy,
    GuardrailResult,
    ResponseScanResult,
    TypePolicy,
)
from shared.contracts.openai_models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)
from shared.contracts.router import (
    ProviderHealth,
    RouteAttempt,
    RouterRequest,
    RouterResult,
    RouterStream,
)


class FakeScenario(StrEnum):
    CLEAN_ALLOW = "clean_allow"
    PII_REDACT = "pii_redact"
    INJECTION_WARN = "injection_warn"
    INJECTION_BLOCK = "injection_block"
    INTERNAL_ERROR = "internal_error"
    CACHE_L1_HIT = "cache_l1_hit"
    CACHE_L2_HIT = "cache_l2_hit"
    CACHE_MISS = "cache_miss"
    CACHE_BYPASS = "cache_bypass"


# ---------------------------------------------------------------------------
# Canonical fake policy (must match shared/contracts/guardrails.GuardrailPolicy)
# ---------------------------------------------------------------------------
_FAKE_POLICY = GuardrailPolicy(
    name="fake",
    version="fake0000deadbeef",
    injection_warn_threshold=0.50,
    injection_block_threshold=0.85,
    secrets=TypePolicy(action=RedactionAction.REDACT),
)

# ---------------------------------------------------------------------------
# Canonical fake response (used by cache fakes)
# ---------------------------------------------------------------------------
_FAKE_RESPONSE = ChatCompletionResponse(
    id="chatcmpl-fake-0001",
    created=1_700_000_000,
    model="fluxgate-default",
    choices=[],
    usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
)


# ---------------------------------------------------------------------------
# FakeGuardrailEngine
# ---------------------------------------------------------------------------
class FakeGuardrailEngine:
    """Fake implementation of the GuardrailEngine protocol.

    Usage::

        engine = FakeGuardrailEngine(scenario=FakeScenario.CLEAN_ALLOW)
        result = await engine.inspect_inbound(ctx, request)
        assert result.decision == Decision.ALLOW
    """

    def __init__(self, scenario: FakeScenario = FakeScenario.CLEAN_ALLOW) -> None:
        self._scenario = scenario
        self.inspect_inbound_calls: list[tuple[RequestContext, ChatCompletionRequest]] = []
        self.scan_response_calls: int = 0

    @property
    def policy_version(self) -> str:
        return _FAKE_POLICY.version

    async def inspect_inbound(
        self, ctx: RequestContext, request: ChatCompletionRequest
    ) -> GuardrailResult:
        self.inspect_inbound_calls.append((ctx, request))

        if self._scenario == FakeScenario.INTERNAL_ERROR:
            raise RuntimeError("FakeGuardrailEngine: simulated internal error")

        base = {
            "request_id": ctx.request_id,
            "stage": GuardrailStage.INBOUND,
            "policy_name": _FAKE_POLICY.name,
            "policy_version": _FAKE_POLICY.version,
        }

        if self._scenario == FakeScenario.INJECTION_BLOCK:
            return GuardrailResult(
                **base,
                decision=Decision.BLOCK,
                risk_score=0.90,
                risk_level=Severity.CRITICAL,
                sanitized_request=None,
                findings=[
                    Finding(
                        type=FindingType.PROMPT_INJECTION,
                        severity=Severity.HIGH,
                        rule_id="INJ-0101",
                        confidence=0.90,
                        source=ContentSource.USER,
                        action=RedactionAction.BLOCK,
                    )
                ],
                reason="Prompt injection detected (fake)",
            )

        if self._scenario == FakeScenario.INJECTION_WARN:
            return GuardrailResult(
                **base,
                decision=Decision.WARN,
                risk_score=0.60,
                risk_level=Severity.MEDIUM,
                sanitized_request=request,
                findings=[
                    Finding(
                        type=FindingType.JAILBREAK,
                        severity=Severity.MEDIUM,
                        rule_id="INJ-0201",
                        confidence=0.60,
                        source=ContentSource.USER,
                        action=RedactionAction.WARN,
                    )
                ],
            )

        if self._scenario == FakeScenario.PII_REDACT:
            return GuardrailResult(
                **base,
                decision=Decision.ALLOW,
                risk_score=0.0,
                risk_level=Severity.INFO,
                sanitized_request=request,
                redaction_count=1,
                redacted_types={"pii_email": 1},
                findings=[
                    Finding(
                        type=FindingType.PII_EMAIL,
                        severity=Severity.LOW,
                        rule_id="PII-EMAIL-001",
                        confidence=0.95,
                        source=ContentSource.USER,
                        action=RedactionAction.REDACT,
                        masked_preview="u***@e*****.com",
                    )
                ],
            )

        # Default: CLEAN_ALLOW
        return GuardrailResult(
            **base,
            decision=Decision.ALLOW,
            risk_score=0.0,
            risk_level=Severity.INFO,
            sanitized_request=request,
        )

    def new_stream_redactor(
        self, ctx: RequestContext, inbound: GuardrailResult
    ) -> _FakeStreamRedactor:
        return _FakeStreamRedactor()

    async def scan_response(
        self,
        ctx: RequestContext,
        response: ChatCompletionResponse,
        inbound: GuardrailResult,
    ) -> ResponseScanResult:
        self.scan_response_calls += 1
        return ResponseScanResult(decision=Decision.ALLOW)


class _FakeStreamRedactor:
    """Passthrough stream redactor — returns input unchanged."""

    @property
    def findings(self) -> list[Finding]:
        return []

    def feed(self, delta_text: str) -> str:
        return delta_text

    def flush(self) -> _FakeStreamFlush:
        return _FakeStreamFlush()


@dataclass
class _FakeStreamFlush:
    text: str = ""
    findings: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# FakeCacheEngine
# ---------------------------------------------------------------------------
class FakeCacheEngine:
    """Fake implementation of the CacheEngine protocol."""

    def __init__(self, scenario: FakeScenario = FakeScenario.CACHE_MISS) -> None:
        self._scenario = scenario
        self.lookup_exact_calls: int = 0
        self.lookup_semantic_calls: int = 0
        self.maybe_store_calls: int = 0
        self.invalidate_calls: int = 0

    def _make_keys(self, request: ChatCompletionRequest, policy_version: str) -> CacheKeys:
        raw = f"{policy_version}|{request.model}|{request.messages}"
        return CacheKeys(exact_key=hashlib.sha256(raw.encode()).hexdigest())

    async def lookup_exact(
        self, ctx: RequestContext, request: ChatCompletionRequest, policy_version: str
    ) -> CacheResult:
        self.lookup_exact_calls += 1
        keys = self._make_keys(request, policy_version)
        if self._scenario == FakeScenario.CACHE_L1_HIT:
            return CacheResult(
                outcome=CacheOutcome.HIT_L1,
                response=_FAKE_RESPONSE,
                entry_id="fake-entry-l1",
                keys=keys,
                age_seconds=60,
                ttl_remaining_seconds=86340,
                latency_ms=1.5,
            )
        return CacheResult(outcome=CacheOutcome.MISS, keys=keys, latency_ms=2.0)

    async def lookup_semantic(
        self,
        ctx: RequestContext,
        sanitized: ChatCompletionRequest,
        inbound: GuardrailResult,
        keys: CacheKeys,
    ) -> CacheResult:
        self.lookup_semantic_calls += 1
        if self._scenario == FakeScenario.CACHE_L2_HIT:
            return CacheResult(
                outcome=CacheOutcome.HIT_L2,
                response=_FAKE_RESPONSE,
                entry_id="fake-entry-l2",
                similarity=0.95,
                keys=keys,
                embed_ms=14.0,
                search_ms=2.5,
                latency_ms=18.0,
            )
        if self._scenario == FakeScenario.CACHE_BYPASS:
            return CacheResult(
                outcome=CacheOutcome.BYPASS,
                bypass_reason=CacheBypassReason.HIGH_TEMPERATURE,
                keys=keys,
                latency_ms=0.1,
            )
        return CacheResult(
            outcome=CacheOutcome.MISS,
            near_miss_similarity=0.88,
            keys=keys,
            embed_ms=14.0,
            search_ms=2.5,
            latency_ms=18.0,
        )

    async def maybe_store(self, req: CacheStoreRequest) -> StoreDecision:
        self.maybe_store_calls += 1
        return StoreDecision(stored=True, entry_id="fake-stored-entry", latency_ms=5.0)

    async def invalidate(
        self,
        tenant_id: str,
        *,
        entry_id: str | None = None,
        model: str | None = None,
        all_entries: bool = False,
    ) -> int:
        self.invalidate_calls += 1
        return 0

    async def stats(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "entries": 0,
            "l1_hits": 0,
            "l2_hits": 0,
            "misses": 0,
        }


# ---------------------------------------------------------------------------
# FakeRouter
# ---------------------------------------------------------------------------
class FakeRouter:
    """Fake implementation of the Router protocol."""

    def __init__(
        self,
        provider: ProviderName = ProviderName.GROQ,
        model_served: str = "llama-3.1-8b-instant",
        raise_on_complete: Exception | None = None,
    ) -> None:
        self._provider = provider
        self._model_served = model_served
        self._raise = raise_on_complete
        self.complete_calls: int = 0
        self.stream_calls: int = 0

    def _make_attempt(self) -> RouteAttempt:
        return RouteAttempt(
            provider=self._provider,
            model_id=self._model_served,
            started_at=datetime.now(UTC),
            latency_ms=50.0,
            http_status=200,
            circuit_state_at_start=CircuitState.CLOSED,
        )

    async def complete(self, req: RouterRequest) -> RouterResult:
        self.complete_calls += 1
        if self._raise:
            raise self._raise
        return RouterResult(
            response=_FAKE_RESPONSE,
            provider=self._provider,
            model_served=self._model_served,
            usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            attempts=[self._make_attempt()],
            ttft_ms=None,
        )

    async def stream(self, req: RouterRequest) -> RouterStream:
        self.stream_calls += 1
        if self._raise:
            raise self._raise

        async def _chunks() -> AsyncIterator[ChatCompletionChunk]:
            for word in ["Hello", " world", "!"]:
                yield ChatCompletionChunk(
                    id="chatcmpl-fake-stream",
                    created=int(time.time()),
                    model=self._model_served,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(content=word),
                        )
                    ],
                )
                await asyncio.sleep(0)

        return RouterStream(
            provider=self._provider,
            model_served=self._model_served,
            attempts=[self._make_attempt()],
            chunks=_chunks(),
        )

    def health(self) -> list[ProviderHealth]:
        return [
            ProviderHealth(
                provider=self._provider,
                circuit_state=CircuitState.CLOSED,
                consecutive_failures=0,
            )
        ]
