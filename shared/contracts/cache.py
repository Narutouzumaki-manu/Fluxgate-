"""Cache contracts (Blueprint section 10.5)."""

from pydantic import Field

from .base import FGModel
from .enums import CacheBypassReason, CacheOutcome, ProviderName
from .guardrails import GuardrailResult, ResponseScanResult
from .openai_models import ChatCompletionRequest, ChatCompletionResponse, ChatCompletionUsage


class CacheKeys(FGModel):
    """Computed at L1 lookup and passed through to maybe_store to avoid recomputation."""

    exact_key: str  # SHA-256 hex over (tenant, policy_version, scope, canonical raw request)
    compat_hash: str | None = None  # set after guardrails (sanitized request)
    cache_scope: str | None = None


class CacheResult(FGModel):
    outcome: CacheOutcome
    response: ChatCompletionResponse | None = None
    entry_id: str | None = None
    similarity: float | None = None  # L2 hit similarity
    near_miss_similarity: float | None = None  # best candidate below threshold (tuning/dashboard)
    compat_mismatch: str | None = None  # which fingerprint component differed
    bypass_reason: CacheBypassReason | None = None
    age_seconds: int | None = None
    ttl_remaining_seconds: int | None = None
    keys: CacheKeys | None = None
    embed_ms: float = 0.0
    search_ms: float = 0.0
    latency_ms: float = 0.0

    @property
    def hit(self) -> bool:
        return self.outcome in (CacheOutcome.HIT_L1, CacheOutcome.HIT_L2)


class CacheStoreRequest(FGModel):
    tenant_id: str
    keys: CacheKeys
    sanitized_request: ChatCompletionRequest  # keeps `fluxgate` options (sanitized) for the cache
    response: ChatCompletionResponse
    guardrail_inbound: GuardrailResult
    response_scan: ResponseScanResult
    provider: ProviderName
    model_served: str
    usage: ChatCompletionUsage | None = None
    usage_estimated: bool = False
    completed: bool = True  # False for aborted/partial streams
    streamed: bool = False
    ttl_seconds: int | None = None  # None -> tenant/default TTL


class StoreDecision(FGModel):
    stored: bool
    entry_id: str | None = None
    ineligible_reasons: list[CacheBypassReason] = Field(default_factory=list)
    latency_ms: float = 0.0
