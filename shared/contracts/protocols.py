"""Integration seams between modules (Blueprint section 10.8).

These are checklists, not logic. M2's gateway is written against them, so it cannot
tell whether it is talking to a fake or the real engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .cache import CacheKeys, CacheResult, CacheStoreRequest, StoreDecision
from .context import RequestContext
from .guardrails import Finding, GuardrailResult, ResponseScanResult
from .openai_models import ChatCompletionRequest, ChatCompletionResponse
from .router import ProviderHealth, RouterRequest, RouterResult, RouterStream
from .telemetry import RequestTrace, SecurityAuditEvent

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class RedactionVault(Protocol):
    """Request-scoped map of placeholder -> original value. Lives in RAM only."""

    def restore(self, text: str) -> str: ...

    def __len__(self) -> int: ...


class StreamFlush(Protocol):
    text: str
    findings: list[Finding]


class StreamRedactor(Protocol):
    """One per streamed response. Not thread-safe by design."""

    def feed(self, delta_text: str) -> str: ...

    def flush(self) -> StreamFlush: ...

    @property
    def findings(self) -> list[Finding]: ...


@runtime_checkable
class GuardrailEngine(Protocol):
    @property
    def policy_version(self) -> str: ...

    async def inspect_inbound(
        self, ctx: RequestContext, request: ChatCompletionRequest
    ) -> GuardrailResult: ...

    def new_stream_redactor(
        self, ctx: RequestContext, inbound: GuardrailResult
    ) -> StreamRedactor: ...

    async def scan_response(
        self, ctx: RequestContext, response: ChatCompletionResponse, inbound: GuardrailResult
    ) -> ResponseScanResult: ...


@runtime_checkable
class CacheEngine(Protocol):
    async def lookup_exact(
        self, ctx: RequestContext, request: ChatCompletionRequest, policy_version: str
    ) -> CacheResult: ...

    async def lookup_semantic(
        self,
        ctx: RequestContext,
        sanitized: ChatCompletionRequest,
        inbound: GuardrailResult,
        keys: CacheKeys,
    ) -> CacheResult: ...

    async def maybe_store(self, req: CacheStoreRequest) -> StoreDecision: ...

    async def invalidate(
        self,
        tenant_id: str,
        *,
        entry_id: str | None = None,
        model: str | None = None,
        all_entries: bool = False,
    ) -> int: ...

    async def stats(self, tenant_id: str) -> dict[str, Any]: ...


@runtime_checkable
class Router(Protocol):
    async def complete(self, req: RouterRequest) -> RouterResult: ...

    async def stream(self, req: RouterRequest) -> RouterStream: ...

    def health(self) -> list[ProviderHealth]: ...


class TelemetrySink(Protocol):
    def emit_trace(self, trace: RequestTrace) -> None: ...

    def emit_audit(self, event: SecurityAuditEvent) -> None: ...


class Embedder(Protocol):
    dim: int

    async def embed(self, text: str) -> NDArray[np.float32]: ...
