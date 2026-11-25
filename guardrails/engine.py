"""Guardrail engine (M1-0 skeleton).

WARNING: this skeleton has NO detectors. It allows everything. It exists to fix the
public shape (build_guardrail_engine + the GuardrailEngine protocol) so the real
detectors (M1-1 to M1-8) can be added without changing how callers use it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from guardrails.policy import load_policy
from shared.config import Settings
from shared.contracts.context import RequestContext
from shared.contracts.enums import Decision, GuardrailStage, Severity
from shared.contracts.guardrails import (
    Finding,
    GuardrailPolicy,
    GuardrailResult,
    ResponseScanResult,
)
from shared.contracts.openai_models import ChatCompletionRequest, ChatCompletionResponse
from shared.contracts.protocols import GuardrailEngine
from shared.errors import ConfigError


@dataclass
class _Flush:
    text: str = ""
    findings: list[Finding] = field(default_factory=list)


class _PassthroughStreamRedactor:
    """Placeholder: returns every chunk unchanged. Replaced by the real one in M1-5."""

    @property
    def findings(self) -> list[Finding]:
        return []

    def feed(self, delta_text: str) -> str:
        return delta_text

    def flush(self) -> _Flush:
        return _Flush()


class SkeletonGuardrailEngine:
    def __init__(self, policies: dict[str, GuardrailPolicy], default_name: str) -> None:
        self._policies = policies
        self._default_name = default_name

    @property
    def policy_version(self) -> str:
        return self._policies[self._default_name].version

    def _policy_for(self, ctx: RequestContext) -> GuardrailPolicy:
        name = ctx.tenant.guardrail_policy
        policy = self._policies.get(name)
        if policy is None:
            raise ConfigError(f"Unknown guardrail policy: {name!r}")
        return policy

    async def inspect_inbound(
        self, ctx: RequestContext, request: ChatCompletionRequest
    ) -> GuardrailResult:
        start = time.perf_counter()
        policy = self._policy_for(ctx)
        # The provider must never see the 'fluxgate' extension field. Copy, don't mutate.
        sanitized = request.model_copy(update={"fluxgate": None}, deep=True)
        return GuardrailResult(
            request_id=ctx.request_id,
            stage=GuardrailStage.INBOUND,
            decision=Decision.ALLOW,
            risk_score=0.0,
            risk_level=Severity.INFO,
            sanitized_request=sanitized,
            policy_name=policy.name,
            policy_version=policy.version,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def new_stream_redactor(
        self, ctx: RequestContext, inbound: GuardrailResult
    ) -> _PassthroughStreamRedactor:
        return _PassthroughStreamRedactor()

    async def scan_response(
        self,
        ctx: RequestContext,
        response: ChatCompletionResponse,
        inbound: GuardrailResult,
    ) -> ResponseScanResult:
        return ResponseScanResult(decision=Decision.ALLOW)


def build_guardrail_engine(settings: Settings) -> GuardrailEngine:
    """Load and check every policy file, then return the engine. Fails fast on any problem."""
    policies: dict[str, GuardrailPolicy] = {}
    for path in sorted(settings.policies_dir.glob("*.yaml")):
        policies[path.stem] = load_policy(path.stem, settings.policies_dir)
    if settings.policy not in policies:
        raise ConfigError(
            f"Default policy {settings.policy!r} not found in {settings.policies_dir}"
        )
    return SkeletonGuardrailEngine(policies, settings.policy)
