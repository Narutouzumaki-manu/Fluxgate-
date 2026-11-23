"""Logging with a mandatory secret-redacting step (Blueprint section 7)."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

REDACTED = "[REDACTED]"

# Baseline patterns only. Every quantifier is bounded (ReDoS-safe).
# The full detector set lives in guardrails/secrets (M1-3).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----[\s\S]{0,8192}"), REDACTED),
    (re.compile(r"\bfgx-[A-Za-z0-9_-]{20,200}"), REDACTED),
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,200}"), REDACTED),
    (re.compile(r"\bsk-or-v1-[A-Za-z0-9]{20,200}"), REDACTED),
    (re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,200}"), REDACTED),
    (re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,200}"), REDACTED),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"), REDACTED),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,2000}\.eyJ[A-Za-z0-9_-]{8,2000}\.[A-Za-z0-9_-]{8,2000}"),
        REDACTED,
    ),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,500}", re.IGNORECASE), f"Bearer {REDACTED}"),
    (
        re.compile(
            r"(api[_-]?key|secret|token|password|passwd|pwd)(\s*[:=]\s*)['\"]?[^\s'\"]{8,200}",
            re.IGNORECASE,
        ),
        rf"\1\2{REDACTED}",
    ),
)


def redact_text(text: str) -> str:
    """Replace anything that looks like a secret with [REDACTED]."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_value(value: Any) -> Any:
    """Clean one value from a log event, however deeply it is nested."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact_value(v) for v in value]
    return redact_text(str(value))  # unknown objects: turn into text, then clean


def redacting_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog step: clean every field of every log event."""
    return {k: _redact_value(v) for k, v in event_dict.items()}


class RedactingFilter(logging.Filter):
    """For plain Python log records (uvicorn, httpx and other libraries)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


_HANDLER_MARK = "_fluxgate_handler"


def configure_logging(level: str = "INFO") -> None:
    """Set up logging for the whole app. Safe to call more than once."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,  # traceback -> text FIRST
            redacting_processor,  # then clean everything
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactingFilter())
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
