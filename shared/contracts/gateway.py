"""Gateway envelope contracts (Blueprint section 10.7)."""

from typing import Literal

from pydantic import Field

from .base import FGModel
from .cache import CacheResult, StoreDecision
from .enums import ProviderName
from .guardrails import GuardrailResult, ResponseScanResult
from .openai_models import ChatCompletionResponse, ChatCompletionUsage
from .router import RouteAttempt


class StageTimings(FGModel):
    auth_ms: float = 0
    ratelimit_ms: float = 0
    parse_ms: float = 0
    l1_ms: float = 0
    guardrails_in_ms: float = 0
    l2_ms: float = 0
    router_overhead_ms: float = 0
    upstream_ms: float = 0
    ttft_ms: float | None = None
    guardrails_out_ms: float = 0
    total_ms: float = 0


class ErrorInfo(FGModel):
    http_status: int
    type: str  # OpenAI-style: invalid_request_error, rate_limit_error, api_error ...
    code: str  # fluxgate_policy_block, fluxgate_no_healthy_provider, ...
    message: str  # never contains sensitive content


class GatewayResponse(FGModel):
    """Final per-request envelope assembled by gateway/pipeline.py."""

    request_id: str
    tenant_id: str
    key_id: str
    served_from: Literal["l1", "l2", "provider", "error"]
    model_requested: str
    model_served: str | None = None
    provider: ProviderName | None = None
    streamed: bool = False
    status_code: int = 200
    body: ChatCompletionResponse | None = None  # None for streamed (copy not retained) / errors
    headers: dict[str, str] = Field(default_factory=dict)  # X-FluxGate-*
    cache: CacheResult
    store: StoreDecision | None = None
    guardrail_in: GuardrailResult | None = None
    guardrail_out: ResponseScanResult | None = None
    attempts: list[RouteAttempt] = Field(default_factory=list)
    usage: ChatCompletionUsage | None = None
    usage_estimated: bool = False  # tiktoken fallback used (errata E6)
    client_disconnected: bool = False  # (errata E6)
    tokens_saved: int = 0
    cost_saved_usd_est: float = 0.0
    timings: StageTimings = Field(default_factory=StageTimings)
    error: ErrorInfo | None = None
