"""Router contracts (Blueprint section 10.6)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from pydantic import model_validator

from .base import FGModel
from .context import TenantContext
from .enums import CircuitState, ProviderName, RouteFailureKind
from .openai_models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)


class RouterRequest(FGModel):
    request_id: str
    tenant: TenantContext
    request: ChatCompletionRequest  # sanitized; `fluxgate` MUST already be stripped (validated)
    deadline_seconds: float = 60.0
    preferred_provider: ProviderName | None = None

    @model_validator(mode="after")
    def _fluxgate_options_must_be_stripped(self) -> Self:
        if self.request.fluxgate is not None:
            raise ValueError("`fluxgate` options must be stripped before building a RouterRequest")
        return self


class RouteAttempt(FGModel):
    provider: ProviderName
    model_id: str
    started_at: datetime
    latency_ms: float
    http_status: int | None = None
    failure: RouteFailureKind | None = None
    retry_safe: bool = False
    circuit_state_at_start: CircuitState
    retry_after_seconds: float | None = None


class ProviderHealth(FGModel):
    provider: ProviderName
    circuit_state: CircuitState
    consecutive_failures: int
    cooldown_until: datetime | None = None
    last_success_at: datetime | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None


class RouterResult(FGModel):
    response: ChatCompletionResponse
    provider: ProviderName
    model_served: str
    usage: ChatCompletionUsage | None = None
    attempts: list[RouteAttempt]
    ttft_ms: float | None = None


@dataclass
class RouterStream:
    """Handle for a streaming call (errata E2: a plain dataclass, not a Pydantic model).

    `chunks` is an async iterator and cannot be validated/serialized; `attempts` is
    appended to as the stream runs. Pre-first-byte failures raise from Router.stream().
    """

    provider: ProviderName
    model_served: str
    attempts: list[RouteAttempt]
    chunks: AsyncIterator[ChatCompletionChunk]
