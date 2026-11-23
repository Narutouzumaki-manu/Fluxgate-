import logging
from collections.abc import Iterator

import pytest
import structlog

from shared.logging import (
    _HANDLER_MARK,
    REDACTED,
    RedactingFilter,
    configure_logging,
    redact_text,
)

# Synthetic canaries only: fake values shaped like real keys. Never use real keys.
CANARIES = {
    "aws": "AKIA" + "IOSFODNN7EXAMPLE",
    "github": "ghp_" + "A" * 36,
    "groq": "gsk_" + "B" * 24,
    "openrouter": "sk-or-v1-" + "C" * 24,
    "nvidia": "nvapi-" + "D" * 24,
    "fgx": "fgx-" + "E" * 30,
    "jwt": ".".join(
        ["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJlMTIzNDU2"]
    ),
}


@pytest.mark.parametrize("canary", list(CANARIES.values()))
def test_redact_text_removes_canary(canary: str) -> None:
    out = redact_text(f"the value was {canary} in the call")
    assert canary not in out
    assert REDACTED in out


def test_assignment_keeps_name_hides_value() -> None:
    assert redact_text("api_key=abcd1234efgh5678") == f"api_key={REDACTED}"  # gitleaks:allow


def test_normal_text_untouched() -> None:
    text = "user asked about the weather in Bengaluru, request req_123"
    assert redact_text(text) == text


@pytest.fixture(autouse=True)
def _clean_logging_state() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)


def test_structlog_events_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    configure_logging("INFO")
    log = structlog.get_logger("test")
    log.info(
        "upstream call",
        api_key=CANARIES["groq"],
        nested={"header": f"Bearer {'x' * 20}"},
        note=CANARIES["aws"],
    )
    assert CANARIES["groq"] not in caplog.text
    assert CANARIES["aws"] not in caplog.text
    assert "x" * 20 not in caplog.text
    assert REDACTED in caplog.text


def test_exception_text_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    configure_logging("INFO")
    log = structlog.get_logger("test")
    try:
        raise ValueError(f"upstream rejected {CANARIES['nvidia']}")
    except ValueError:
        log.error("failed", exc_info=True)
    assert CANARIES["nvidia"] not in caplog.text
    assert REDACTED in caplog.text


def test_stdlib_filter_redacts_args() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "key %s", (CANARIES["fgx"],), None)
    assert RedactingFilter().filter(record) is True
    assert CANARIES["fgx"] not in record.msg
    assert record.args is None
