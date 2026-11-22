"""Guardrail contracts (Blueprint section 10.4)."""

from typing import Any

from pydantic import Field

from .base import FGModel
from .enums import (
    ContentSource,
    Decision,
    FindingType,
    GuardrailStage,
    RedactionAction,
    Severity,
)
from .openai_models import ChatCompletionRequest


class Finding(FGModel):
    """A single detection. NEVER contains raw sensitive values."""

    type: FindingType
    severity: Severity
    rule_id: str  # e.g. "INJ-0107", "PII-AADHAAR-VERHOEFF"
    confidence: float = Field(ge=0, le=1)
    source: ContentSource
    message_index: int | None = None
    chunk_id: str | None = None  # when from retrieved_context
    span: tuple[int, int] | None = None  # offsets in the normalized text of that message
    masked_preview: str | None = Field(default=None, max_length=64)  # e.g. "AKIA****MPLE"
    action: RedactionAction = RedactionAction.ALLOW
    meta: dict[str, str] = Field(default_factory=dict)  # non-sensitive only


class TypePolicy(FGModel):
    action: RedactionAction = RedactionAction.REDACT
    restore_in_response: bool = False  # restore placeholder in outputs (request-scoped vault)


class GuardrailPolicy(FGModel):
    name: str
    version: str  # content hash of the normalized policy; part of L1/L2 keys
    injection_warn_threshold: float = Field(default=0.50, ge=0, le=1)
    injection_block_threshold: float = Field(default=0.85, ge=0, le=1)
    inspect_system_messages: bool = True
    inspect_retrieved_context: bool = True
    max_inspect_chars: int = 200_000
    on_oversize: Decision = Decision.WARN
    on_internal_error: Decision = Decision.BLOCK  # D-003
    pii: dict[FindingType, TypePolicy] = Field(default_factory=dict)
    secrets: TypePolicy = Field(default_factory=lambda: TypePolicy(action=RedactionAction.REDACT))
    response_scan: RedactionAction = RedactionAction.REDACT
    custom_patterns: dict[str, str] = Field(default_factory=dict)  # name -> regex (validated)
    # Added in scaffold (errata E3; TRD A2.3): policy-level cache and privacy knobs.
    cache_max_risk: float = Field(default=0.30, ge=0, le=1)  # risk above this is never cached
    store_prompt_preview: bool | None = None  # None = follow the runtime profile (D-004)


class GuardrailResult(FGModel):
    request_id: str
    stage: GuardrailStage = GuardrailStage.INBOUND
    decision: Decision
    risk_score: float = Field(ge=0, le=1)  # injection/jailbreak RISK, not a safety guarantee
    risk_level: Severity
    findings: list[Finding] = Field(default_factory=list)
    sanitized_request: ChatCompletionRequest | None = None  # None when BLOCK
    redaction_count: int = 0
    redacted_types: dict[str, int] = Field(default_factory=dict)
    policy_name: str
    policy_version: str
    degraded: bool = False  # internal error / timeout path taken
    reason: str | None = None  # human-safe summary for error body / UI
    latency_ms: float = 0.0
    # RedactionVault (RAM-only, request-scoped). Never serialized, never persisted.
    vault: Any = Field(default=None, exclude=True)

    @property
    def cache_clean(self) -> bool:
        """True only if this request may ever be cached (ADR-05)."""
        return self.decision == Decision.ALLOW and self.redaction_count == 0 and not self.degraded


class ResponseScanResult(FGModel):
    decision: Decision
    findings: list[Finding] = Field(default_factory=list)
    redaction_count: int = 0
    sanitized_text: str | None = None
    latency_ms: float = 0.0
