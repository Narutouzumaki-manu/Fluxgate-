"""Telemetry contracts (Blueprint section 10.7). Maps 1:1 onto request_logs / security_events."""

from pydantic import Field

from .base import FGModel
from .enums import (
    CacheBypassReason,
    CacheOutcome,
    ContentSource,
    Decision,
    FindingType,
    GuardrailStage,
    ProviderName,
    Severity,
)
from .gateway import StageTimings


class RequestTrace(FGModel):
    """Persisted subset of a request. No bodies, no raw sensitive values (enforced by a test)."""

    request_id: str
    tenant_id: str
    key_id: str
    created_at_unix_ms: int
    model_requested: str
    model_served: str | None
    provider: ProviderName | None
    served_from: str
    streamed: bool
    status_code: int
    cache_outcome: CacheOutcome
    similarity: float | None
    near_miss_similarity: float | None
    bypass_reason: CacheBypassReason | None
    decision: Decision | None
    risk_score: float | None
    finding_summary: dict[str, int]
    redaction_count: int
    prompt_tokens: int | None
    completion_tokens: int | None
    tokens_saved: int
    cost_saved_usd_est: float
    timings: StageTimings
    attempts_summary: list[dict[str, str | int | float | None]]
    prompt_sha256: str  # hash of the RAW canonical prompt (irreversible)
    prompt_chars: int
    sanitized_preview: str | None = None  # <= 80 chars of SANITIZED text; null if disabled
    # Added in scaffold (errata E4) so every request_logs column has a contract field:
    error_code: str | None = None
    client_disconnected: bool = False
    cache_entry_id: str | None = None
    compat_mismatch: str | None = None
    store_stored: bool | None = None
    policy_name: str | None = None
    policy_version: str | None = None
    degraded: bool = False
    usage_estimated: bool = False
    failed_over: bool = False
    attempt_count: int = 0
    client_ip_hash: str | None = None


class SecurityAuditEvent(FGModel):
    event_id: str
    request_id: str
    tenant_id: str
    key_id: str
    created_at_unix_ms: int
    stage: GuardrailStage
    decision: Decision
    finding_type: FindingType
    rule_id: str
    severity: Severity
    masked_preview: str | None
    policy_name: str
    policy_version: str
    # Added in scaffold (errata E5) to match security_events columns:
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: ContentSource = ContentSource.USER
    message_index: int | None = None
    chunk_id: str | None = None
    span: tuple[int, int] | None = None
