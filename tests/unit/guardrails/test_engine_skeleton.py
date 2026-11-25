from pathlib import Path

import pytest

from guardrails import build_guardrail_engine
from guardrails.policy import load_policy
from shared.config import Settings
from shared.contracts.context import RequestContext, TenantContext
from shared.contracts.enums import Decision
from shared.contracts.openai_models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    FluxGateOptions,
)
from shared.contracts.protocols import GuardrailEngine
from shared.errors import ConfigError

POLICIES_DIR = Path(__file__).resolve().parents[3] / "config" / "policies"


def make_settings(directory: Path = POLICIES_DIR) -> Settings:
    return Settings(_env_file=None, policies_dir=directory)


def make_ctx(policy: str = "default") -> RequestContext:
    tenant = TenantContext(
        tenant_id="t1", key_id="k1", key_prefix="fgx-test0001", guardrail_policy=policy
    )
    return RequestContext(
        request_id="req_TEST001", tenant=tenant, received_at_unix_ms=1_700_000_000_000
    )


def make_request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="fluxgate-default",
        messages=[ChatMessage(role="user", content="Hello")],
        fluxgate=FluxGateOptions(cache_scope="demo"),
    )


def test_engine_satisfies_the_protocol() -> None:
    assert isinstance(build_guardrail_engine(make_settings()), GuardrailEngine)


def test_policy_version_is_the_default_policys_version() -> None:
    engine = build_guardrail_engine(make_settings())
    assert engine.policy_version == load_policy("default", POLICIES_DIR).version


async def test_inbound_allows_and_stamps_policy() -> None:
    engine = build_guardrail_engine(make_settings())
    result = await engine.inspect_inbound(make_ctx(), make_request())
    assert result.decision == Decision.ALLOW
    assert result.request_id == "req_TEST001"
    assert result.policy_name == "default"
    assert result.policy_version == engine.policy_version
    assert result.sanitized_request is not None


async def test_fluxgate_field_is_stripped_and_original_untouched() -> None:
    engine = build_guardrail_engine(make_settings())
    request = make_request()
    result = await engine.inspect_inbound(make_ctx(), request)
    assert result.sanitized_request is not None
    assert result.sanitized_request.fluxgate is None
    assert request.fluxgate is not None


async def test_tenant_policy_is_used() -> None:
    engine = build_guardrail_engine(make_settings())
    result = await engine.inspect_inbound(make_ctx("strict"), make_request())
    assert result.policy_name == "strict"
    assert result.policy_version != engine.policy_version


async def test_unknown_tenant_policy_is_an_error() -> None:
    engine = build_guardrail_engine(make_settings())
    with pytest.raises(ConfigError, match="Unknown guardrail policy"):
        await engine.inspect_inbound(make_ctx("nope"), make_request())


async def test_stream_redactor_is_passthrough_for_now() -> None:
    engine = build_guardrail_engine(make_settings())
    inbound = await engine.inspect_inbound(make_ctx(), make_request())
    redactor = engine.new_stream_redactor(make_ctx(), inbound)
    assert redactor.feed("hello") == "hello"
    flush = redactor.flush()
    assert flush.text == ""
    assert flush.findings == []


async def test_scan_response_allows_for_now() -> None:
    engine = build_guardrail_engine(make_settings())
    inbound = await engine.inspect_inbound(make_ctx(), make_request())
    response = ChatCompletionResponse(id="x", created=1, model="m", choices=[])
    result = await engine.scan_response(make_ctx(), response, inbound)
    assert result.decision == Decision.ALLOW


def test_build_fails_when_default_policy_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        build_guardrail_engine(make_settings(tmp_path))


def test_build_fails_fast_on_a_broken_policy_file(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text("name: default\n", encoding="utf-8")
    (tmp_path / "bad.yaml").write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        build_guardrail_engine(make_settings(tmp_path))
