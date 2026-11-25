from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from cache import build_cache_engine
from shared.config import Settings
from shared.contracts.cache import CacheKeys, CacheStoreRequest
from shared.contracts.context import RequestContext, TenantContext
from shared.contracts.enums import (
    CacheBypassReason,
    CacheOutcome,
    Decision,
    ProviderName,
    Severity,
)
from shared.contracts.guardrails import GuardrailResult, ResponseScanResult
from shared.contracts.openai_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
)
from shared.contracts.protocols import CacheEngine
from shared.db.connection import open_db


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await open_db(tmp_path / "cache-test.db")
    try:
        yield conn
    finally:
        await conn.close()


def make_ctx() -> RequestContext:
    tenant = TenantContext(tenant_id="t1", key_id="k1", key_prefix="fgx-test0001")
    return RequestContext(
        request_id="req_TEST001", tenant=tenant, received_at_unix_ms=1_700_000_000_000
    )


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="fluxgate-default", messages=[ChatMessage(role="user", content="Hello")]
    )


def make_inbound() -> GuardrailResult:
    return GuardrailResult(
        request_id="req_TEST001",
        decision=Decision.ALLOW,
        risk_score=0.0,
        risk_level=Severity.INFO,
        policy_name="default",
        policy_version="0" * 16,
    )


def make_engine(db: aiosqlite.Connection) -> CacheEngine:
    return build_cache_engine(Settings(_env_file=None), db)


def test_engine_satisfies_the_protocol(db: aiosqlite.Connection) -> None:
    assert isinstance(make_engine(db), CacheEngine)


async def test_exact_lookup_bypasses(db: aiosqlite.Connection) -> None:
    result = await make_engine(db).lookup_exact(make_ctx(), make_request(), "0" * 16)
    assert result.outcome == CacheOutcome.BYPASS
    assert result.bypass_reason == CacheBypassReason.CACHE_DISABLED
    assert result.hit is False
    assert result.response is None


async def test_semantic_lookup_bypasses(db: aiosqlite.Connection) -> None:
    keys = CacheKeys(exact_key="a" * 64)
    result = await make_engine(db).lookup_semantic(make_ctx(), make_request(), make_inbound(), keys)
    assert result.outcome == CacheOutcome.BYPASS
    assert result.hit is False


async def test_store_is_refused_and_nothing_is_written(db: aiosqlite.Connection) -> None:
    req = CacheStoreRequest(
        tenant_id="t1",
        keys=CacheKeys(exact_key="c" * 64),
        sanitized_request=make_request(),
        response=ChatCompletionResponse(id="x", created=1, model="m", choices=[]),
        guardrail_inbound=make_inbound(),
        response_scan=ResponseScanResult(decision=Decision.ALLOW),
        provider=ProviderName.GROQ,
        model_served="llama-3.1-8b-instant",
    )
    decision = await make_engine(db).maybe_store(req)
    assert decision.stored is False
    assert decision.entry_id is None
    assert decision.ineligible_reasons == [CacheBypassReason.CACHE_DISABLED]


async def test_invalidate_removes_nothing(db: aiosqlite.Connection) -> None:
    assert await make_engine(db).invalidate("t1", all_entries=True) == 0


async def test_stats_are_zero_and_tied_to_the_tenant(db: aiosqlite.Connection) -> None:
    stats = await make_engine(db).stats("t1")
    assert stats["tenant_id"] == "t1"
    assert stats["entries"] == 0
    assert stats["l1_hits"] == 0
    assert stats["l2_hits"] == 0
