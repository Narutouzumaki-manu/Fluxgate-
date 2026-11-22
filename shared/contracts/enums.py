"""Enumerations shared by every module (Blueprint section 10.1)."""

from enum import StrEnum


class Decision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContentSource(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    RETRIEVED_CONTEXT = "retrieved_context"
    RESPONSE = "response"


class FindingType(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    INDIRECT_INJECTION = "indirect_injection"
    PROMPT_LEAK_ATTEMPT = "prompt_leak_attempt"
    OBFUSCATION = "obfuscation"
    PII_EMAIL = "pii_email"
    PII_PHONE = "pii_phone"
    PII_AADHAAR = "pii_aadhaar"
    PII_PAN = "pii_pan"
    PII_CARD = "pii_card"
    SECRET_API_KEY = "secret_api_key"
    SECRET_TOKEN = "secret_token"
    SECRET_PRIVATE_KEY = "secret_private_key"
    SECRET_HIGH_ENTROPY = "secret_high_entropy"
    CUSTOM = "custom"


class RedactionAction(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    REDACT = "redact"
    BLOCK = "block"


class GuardrailStage(StrEnum):
    INBOUND = "inbound"
    RESPONSE = "response"
    STREAM = "stream"


class CacheOutcome(StrEnum):
    HIT_L1 = "hit_l1"
    HIT_L2 = "hit_l2"
    MISS = "miss"
    BYPASS = "bypass"


class CacheBypassReason(StrEnum):
    CLIENT_OPT_OUT = "client_opt_out"
    CACHE_DISABLED = "cache_disabled"
    HIGH_TEMPERATURE = "high_temperature"
    TOOLS_PRESENT = "tools_present"
    MULTIMODAL = "multimodal"
    N_GREATER_THAN_ONE = "n_greater_than_one"
    PII_OR_SECRET_PRESENT = "pii_or_secret_present"
    GUARDRAIL_NOT_CLEAN = "guardrail_not_clean"
    RISK_ABOVE_THRESHOLD = "risk_above_threshold"
    RESPONSE_NOT_CLEAN = "response_not_clean"
    INCOMPLETE_RESPONSE = "incomplete_response"
    NON_STOP_FINISH = "non_stop_finish"
    TOO_LARGE = "too_large"
    CACHE_ERROR = "cache_error"
    TENANT_QUOTA_EXCEEDED = "tenant_quota_exceeded"


class ProviderName(StrEnum):
    GROQ = "groq"
    OPENROUTER = "openrouter"
    NVIDIA_NIM = "nvidia_nim"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RouteFailureKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    UPSTREAM_5XX = "upstream_5xx"
    TIMEOUT = "timeout"
    CONNECT_ERROR = "connect_error"
    CIRCUIT_OPEN = "circuit_open"
    BAD_REQUEST = "bad_request"
    AUTH_ERROR = "auth_error"
    STREAM_INTERRUPTED = "stream_interrupted"
    CLIENT_DISCONNECTED = "client_disconnected"
