"""Cache engine (M1-0 skeleton).

WARNING: this skeleton never hits and never stores. It exists to fix the public shape
(build_cache_engine + the CacheEngine protocol) so the real L1/L2 logic (M1-9 to M1-11)
can be added without changing how callers use it.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from shared.config import Settings
from shared.contracts.cache import CacheKeys, CacheResult, CacheStoreRequest, StoreDecision
from shared.contracts.context import RequestContext
from shared.contracts.enums import CacheBypassReason, CacheOutcome
from shared.contracts.guardrails import GuardrailResult
from shared.contracts.openai_models import ChatCompletionRequest
from shared.contracts.protocols import CacheEngine


class SkeletonCacheEngine:
    def __init__(self, settings: Settings, db: aiosqlite.Connection) -> None:
        self._settings = settings
        self._db = db  # used by the real L1/L2 later; unused in the skeleton

    def _bypass(self) -> CacheResult:
        return CacheResult(
            outcome=CacheOutcome.BYPASS,
            bypass_reason=CacheBypassReason.CACHE_DISABLED,
        )

    async def lookup_exact(
        self, ctx: RequestContext, request: ChatCompletionRequest, policy_version: str
    ) -> CacheResult:
        return self._bypass()

    async def lookup_semantic(
        self,
        ctx: RequestContext,
        sanitized: ChatCompletionRequest,
        inbound: GuardrailResult,
        keys: CacheKeys,
    ) -> CacheResult:
        return self._bypass()

    async def maybe_store(self, req: CacheStoreRequest) -> StoreDecision:
        return StoreDecision(stored=False, ineligible_reasons=[CacheBypassReason.CACHE_DISABLED])

    async def invalidate(
        self,
        tenant_id: str,
        *,
        entry_id: str | None = None,
        model: str | None = None,
        all_entries: bool = False,
    ) -> int:
        return 0

    async def stats(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "entries": 0,
            "l1_hits": 0,
            "l2_hits": 0,
            "misses": 0,
        }


def build_cache_engine(settings: Settings, db: aiosqlite.Connection) -> CacheEngine:
    """Return the cache engine. The gateway calls this once at startup."""
    return SkeletonCacheEngine(settings, db)
