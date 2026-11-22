"""Protocol conformance test suite.

Tests that FakeGuardrailEngine, FakeCacheEngine, and FakeRouter satisfy
the same behavioral contracts as real implementations will.

Parameterized over [(Fake*, scenario)] pairs so both fake and (Phase 2+) real
engines pass identical scenarios.

TESTING_AND_BENCHMARK_GUIDE.md §4, Blueprint §11.
"""

from __future__ import annotations

import pytest

from shared.contracts.cache import CacheKeys, CacheStoreRequest
from shared.contracts.context import RequestContext, TenantContext
from shared.contracts.enums import (
    CacheOutcome,
    Decision,
    ProviderName,
)
from shared.contracts.guardrails import GuardrailResult, ResponseScanResult
from shared.contracts.openai_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
)
from shared.contracts.router import RouterRequest
from tests.fakes import (
    FakeCacheEngine,
    FakeGuardrailEngine,
    FakeRouter,
    FakeScenario,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TENANT = TenantContext(
    tenant_id="test-tenant-01",
    key_id="key-01",
    key_prefix="fgx-test0001",
    guardrail_policy="default",
)


def make_ctx(request_id: str = "req_CONFORMANCE001") -> RequestContext:
    return RequestContext(
        request_id=request_id,
        tenant=TENANT,
        received_at_unix_ms=1_700_000_000_000,
    )


def make_request(model: str = "fluxgate-default") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content="Hello, world!")],
    )


def make_fake_response() -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-fake-conformance",
        created=1_700_000_000,
        model="fluxgate-default",
        choices=[],
        usage=ChatCompletionUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
    )


def make_guardrail_result(
    ctx: RequestContext, decision: Decision = Decision.ALLOW
) -> GuardrailResult:
    from shared.contracts.enums import GuardrailStage, Severity

    return GuardrailResult(
        request_id=ctx.request_id,
        stage=GuardrailStage.INBOUND,
        decision=decision,
        risk_score=0.0,
        risk_level=Severity.INFO,
        sanitized_request=make_request() if decision != Decision.BLOCK else None,
        policy_name="fake",
        policy_version="fake0000deadbeef",
    )


def make_response_scan_result() -> ResponseScanResult:
    return ResponseScanResult(decision=Decision.ALLOW)


# ---------------------------------------------------------------------------
# GuardrailEngine conformance
# ---------------------------------------------------------------------------


class TestFakeGuardrailEngineConformance:
    """Every test here will be run against real engines in Phase 2."""

    async def test_clean_allow_returns_allow(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.CLEAN_ALLOW)
        ctx = make_ctx()
        result = await engine.inspect_inbound(ctx, make_request())
        assert result.decision == Decision.ALLOW
        assert result.risk_score == 0.0
        assert result.request_id == ctx.request_id
        assert result.sanitized_request is not None

    async def test_block_scenario_returns_block_with_no_sanitized(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.INJECTION_BLOCK)
        ctx = make_ctx()
        result = await engine.inspect_inbound(ctx, make_request())
        assert result.decision == Decision.BLOCK
        assert result.sanitized_request is None
        assert result.risk_score >= 0.85  # INJECTION_BLOCK scenario sets risk_score=0.90

    async def test_warn_scenario_returns_warn_with_sanitized(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.INJECTION_WARN)
        ctx = make_ctx()
        result = await engine.inspect_inbound(ctx, make_request())
        assert result.decision == Decision.WARN
        assert result.sanitized_request is not None
        assert result.risk_score > 0

    async def test_pii_redact_returns_allow_with_redaction_count(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.PII_REDACT)
        ctx = make_ctx()
        result = await engine.inspect_inbound(ctx, make_request())
        assert result.decision == Decision.ALLOW
        assert result.redaction_count > 0

    async def test_internal_error_raises(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.INTERNAL_ERROR)
        ctx = make_ctx()
        with pytest.raises(RuntimeError):
            await engine.inspect_inbound(ctx, make_request())

    async def test_scan_response_returns_allow(self) -> None:
        engine = FakeGuardrailEngine()
        ctx = make_ctx()
        inbound = make_guardrail_result(ctx)
        result = await engine.scan_response(ctx, make_fake_response(), inbound)
        assert result.decision == Decision.ALLOW

    def test_policy_version_is_str(self) -> None:
        engine = FakeGuardrailEngine()
        assert isinstance(engine.policy_version, str)
        assert len(engine.policy_version) > 0

    def test_new_stream_redactor_passthrough(self) -> None:
        engine = FakeGuardrailEngine()
        ctx = make_ctx()
        inbound = make_guardrail_result(ctx)
        redactor = engine.new_stream_redactor(ctx, inbound)
        assert redactor.feed("hello") == "hello"
        flush = redactor.flush()
        assert flush.text == ""
        assert flush.findings == []

    async def test_cache_clean_property_true_on_clean_allow(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.CLEAN_ALLOW)
        ctx = make_ctx()
        result = await engine.inspect_inbound(ctx, make_request())
        assert result.cache_clean is True

    async def test_cache_clean_property_false_on_pii(self) -> None:
        engine = FakeGuardrailEngine(FakeScenario.PII_REDACT)
        ctx = make_ctx()
        result = await engine.inspect_inbound(ctx, make_request())
        # PII was redacted (redaction_count > 0) → cache_clean must be False (ADR-05)
        assert result.cache_clean is False


# ---------------------------------------------------------------------------
# CacheEngine conformance
# ---------------------------------------------------------------------------


class TestFakeCacheEngineConformance:
    async def test_l1_hit_returns_hit_l1(self) -> None:
        engine = FakeCacheEngine(FakeScenario.CACHE_L1_HIT)
        ctx = make_ctx()
        result = await engine.lookup_exact(ctx, make_request(), "policy-v-fake")
        assert result.outcome == CacheOutcome.HIT_L1
        assert result.hit is True
        assert result.response is not None

    async def test_miss_returns_miss(self) -> None:
        engine = FakeCacheEngine(FakeScenario.CACHE_MISS)
        ctx = make_ctx()
        result = await engine.lookup_exact(ctx, make_request(), "policy-v-fake")
        assert result.outcome == CacheOutcome.MISS
        assert result.hit is False

    async def test_l2_hit_has_similarity(self) -> None:
        engine = FakeCacheEngine(FakeScenario.CACHE_L2_HIT)
        ctx = make_ctx()
        inbound = make_guardrail_result(ctx)
        keys = CacheKeys(exact_key="a" * 64)
        result = await engine.lookup_semantic(ctx, make_request(), inbound, keys)
        assert result.outcome == CacheOutcome.HIT_L2
        assert result.similarity is not None
        assert result.similarity > 0.90

    async def test_bypass_has_reason(self) -> None:
        engine = FakeCacheEngine(FakeScenario.CACHE_BYPASS)
        ctx = make_ctx()
        inbound = make_guardrail_result(ctx)
        keys = CacheKeys(exact_key="b" * 64)
        result = await engine.lookup_semantic(ctx, make_request(), inbound, keys)
        assert result.outcome == CacheOutcome.BYPASS
        assert result.bypass_reason is not None

    async def test_maybe_store_returns_store_decision(self) -> None:
        engine = FakeCacheEngine()
        ctx = make_ctx()
        req = CacheStoreRequest(
            tenant_id=ctx.tenant.tenant_id,
            keys=CacheKeys(exact_key="c" * 64),
            sanitized_request=make_request(),
            response=make_fake_response(),
            guardrail_inbound=make_guardrail_result(ctx),
            response_scan=make_response_scan_result(),
            provider=ProviderName.GROQ,
            model_served="llama-3.1-8b-instant",
        )
        decision = await engine.maybe_store(req)
        assert isinstance(decision.stored, bool)

    async def test_invalidate_returns_int(self) -> None:
        engine = FakeCacheEngine()
        count = await engine.invalidate("test-tenant", all_entries=True)
        assert isinstance(count, int)

    async def test_stats_returns_dict_with_tenant_id(self) -> None:
        engine = FakeCacheEngine()
        stats = await engine.stats("test-tenant")
        assert stats["tenant_id"] == "test-tenant"


# ---------------------------------------------------------------------------
# Router conformance
# ---------------------------------------------------------------------------


class TestFakeRouterConformance:
    def _make_router_request(self) -> RouterRequest:
        return RouterRequest(
            request_id="req_ROUTER001",
            tenant=TENANT,
            request=make_request(),  # fluxgate field is None → passes validator
        )

    async def test_complete_returns_router_result(self) -> None:
        router = FakeRouter()
        result = await router.complete(self._make_router_request())
        assert result.response is not None
        assert result.provider in ProviderName.__members__.values()
        assert len(result.attempts) >= 1

    async def test_stream_returns_router_stream(self) -> None:
        router = FakeRouter()
        stream = await router.stream(self._make_router_request())
        assert stream.provider in ProviderName.__members__.values()
        chunks = [chunk async for chunk in stream.chunks]
        assert len(chunks) > 0

    def test_health_returns_list_of_provider_health(self) -> None:
        router = FakeRouter()
        health = router.health()
        assert isinstance(health, list)
        assert len(health) >= 1
        for h in health:
            assert h.provider in ProviderName.__members__.values()

    async def test_complete_raises_when_configured(self) -> None:
        router = FakeRouter(raise_on_complete=RuntimeError("simulated provider failure"))
        with pytest.raises(RuntimeError, match="simulated provider failure"):
            await router.complete(self._make_router_request())
