"""Per-request context objects (Blueprint section 10.3)."""

from pydantic import ConfigDict

from .base import FGModel


class TenantContext(FGModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str  # isolation boundary for cache, quotas, audit
    key_id: str  # virtual_keys.id
    key_prefix: str  # e.g. "fgx-ab12cd34" (never the full key)
    guardrail_policy: str = "default"
    cache_enabled: bool = True
    allowed_models: list[str] | None = None  # None = all
    rpm_limit: int = 60


class RequestContext(FGModel):
    request_id: str  # "req_" + ULID
    tenant: TenantContext
    received_at_unix_ms: int
    client_ip_hash: str | None = None  # salted hash, never a raw IP
    trace_enabled: bool = True
