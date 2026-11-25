"""Baseline conformance: the Fake* engines AND the real engines must all pass these.

Scenario tests (injection -> BLOCK, PII -> redaction) stay fake-only until the real
detectors exist (M1-6 to M1-8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from cache import build_cache_engine
from guardrails import build_guardrail_engine
from shared.config import Settings
from shared.contracts.cache import CacheKeys, CacheStoreRequest
from shared.contracts.enums import CacheOutcome, Decision, ProviderName
from shared.contracts.protocols import CacheEngine, GuardrailEngine
from shared.db.connection import open_db
from tests.contract.test_protocol_conformance import (
    make_ctx,
    make_fake_response,
    make_guardrail_result,
    make_request,
    make_response_scan_result,
)
from tests.fakes import FakeCacheEngine, FakeGuardrailEngine

POLICIES_DIR = Path(__file__).resolve().parents[2] / "config" / "policies"


@pytest.fixture(params=["fake", "real"])
def guardrail_engine(request: pytest.FixtureRequest) -> GuardrailEngine:
    if request.param == "fake":
        return FakeGuardrailEngine()
    return build_guardrail_engine(Settings(_env_file=None, policies_dir=POLICIES_DIR))


@pytest.fixture(params=["fake", "real"])
async def cache_engine(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[CacheEngine]:
    if request.param == "fake":
        yield FakeCacheEngine()
        return
    conn = await open_db(tmp_path / "conformance.db")
    try:
        yield build_cache_engine(Settings(_env_file=None), conn)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# GuardrailEngine baseline
# ---------------------------------------------------------------------------


def test_guardrail_engine_satisfies_protocol(guardrail_engine: GuardrailEngine) -> None:
    assert isinstance(guardrail_engine, GuardrailEngine)


def test_guardrail_policy_version_is_a_nonempty_string(guardrail_engine: GuardrailEngine) -> None:
    assert isinstance(guardrail_engine.policy_version, str)
    assert guardrail_engine.policy_version != ""


async def test_guardrail_clean_request_is_allowed(guardrail_engine: GuardrailEngine) -> None:
    ctx = make_ctx()
    result = await guardrail_engine.inspect_inbound(ctx, make_request())
    assert result.decision == Decision.ALLOW
    assert result.risk_score == 0.0
    assert result.request_id == ctx.request_id
    assert result.sanitized_request is not None
    assert result.policy_version != ""


async def test_guardrail_scan_response_returns_a_decision(
    guardrail_engine: GuardrailEngine,
) -> None:
    ctx = make_ctx()
    inbound = make_guardrail_result(ctx)
    result = await guardrail_engine.scan_response(ctx, make_fake_response(), inbound)
    assert result.decision == Decision.ALLOW


async def test_guardrail_stream_redactor_keeps_clean_text_intact(
    guardrail_engine: GuardrailEngine,
) -> None:
    ctx = make_ctx()
    inbound = make_guardrail_result(ctx)
    redactor = guardrail_engine.new_stream_redactor(ctx, inbound)
    emitted = redactor.feed("hello ") + redactor.feed("world")
    flush = redactor.flush()
    assert emitted + flush.text == "hello world"
    assert flush.findings == []


# ---------------------------------------------------------------------------
# CacheEngine baseline
# ---------------------------------------------------------------------------


def test_cache_engine_satisfies_protocol(cache_engine: CacheEngine) -> None:
    assert isinstance(cache_engine, CacheEngine)


async def test_fresh_cache_never_hits_on_exact_lookup(cache_engine: CacheEngine) -> None:
    result = await cache_engine.lookup_exact(make_ctx(), make_request(), "policy-v-test")
    assert result.outcome in (CacheOutcome.MISS, CacheOutcome.BYPASS)
    assert result.hit is False
    assert result.response is None


async def test_fresh_cache_never_hits_on_semantic_lookup(cache_engine: CacheEngine) -> None:
    ctx = make_ctx()
    keys = CacheKeys(exact_key="a" * 64)
    result = await cache_engine.lookup_semantic(
        ctx, make_request(), make_guardrail_result(ctx), keys
    )
    assert result.hit is False
    assert result.response is None


async def test_store_decision_is_consistent(cache_engine: CacheEngine) -> None:
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
    decision = await cache_engine.maybe_store(req)
    assert isinstance(decision.stored, bool)
    if not decision.stored:
        assert decision.entry_id is None


async def test_invalidate_returns_a_non_negative_count(cache_engine: CacheEngine) -> None:
    count = await cache_engine.invalidate("test-tenant", all_entries=True)
    assert isinstance(count, int)
    assert count >= 0


async def test_stats_are_tied_to_the_tenant(cache_engine: CacheEngine) -> None:
    stats = await cache_engine.stats("test-tenant")
    assert stats["tenant_id"] == "test-tenant"
