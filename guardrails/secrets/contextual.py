"""Contextual secret detectors (M1-3 step 2).

Secrets that have no recognisable prefix but give themselves away by the words around
them: Bearer headers, name=value assignments, and PEM private-key blocks. These are
heuristics: they can miss a secret and can flag a harmless value. The false-positive rate
is measured in M1-3 step 4. All repeats are bounded (ReDoS rule).
"""

from __future__ import annotations

import re

from guardrails.detection import Detection
from shared.contracts.enums import FindingType

# --- Bearer ------------------------------------------------------------------------
_BEARER_RE = re.compile(
    r"(?<![A-Za-z0-9_])bearer[ \t]{1,8}(?P<token>[A-Za-z0-9._~+/=-]{16,4096})",
    re.IGNORECASE,
)
# Lowercase words joined by - or _ : ordinary text, not a random token.
_WORDLIKE = re.compile(r"[a-z]+(?:[-_][a-z]+)*")


def detect_bearer(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _BEARER_RE.finditer(text):
        token = m.group("token").rstrip(".")  # a full stop ends the sentence, not the token
        if len(token) < 16 or _WORDLIKE.fullmatch(token):
            continue
        start = m.start("token")
        found.append(
            Detection(FindingType.SECRET_TOKEN, "SEC-BEARER-001", start, start + len(token), 0.9)
        )
    return found


# --- name=value assignments --------------------------------------------------------
_ASSIGN_RE = re.compile(
    r"(?P<name>api[_-]?key|secret|token|password|passwd|pwd)"
    r"['\"]?[ \t]{0,8}[:=][ \t]{0,8}['\"]?"
    r"(?P<value>[^\s'\"]{8,4096})",
    re.IGNORECASE,
)
_MIN_VALUE_CHARS = 8
_NON_SECRET_WORDS = frozenset(
    {
        "required", "optional", "none", "null", "undefined", "hidden", "masked", "redacted",
        "empty", "string", "unknown", "invalid", "expired", "missing", "enabled", "disabled",
        "true", "false", "changeme", "change-me", "change_me", "replace_me", "replaceme",
        "password", "secret", "token", "example",
    }
)  # fmt: skip
_REFERENCE_STARTS = ("[[fg:", "[redacted", "<", "$", "%", "{{", "your_", "your-")
_MASK_CHARS = frozenset("*xX#.-_")
_CODE_START = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*[(\[]")
_ATTRIBUTE = re.compile(r"[A-Za-z_]+(?:\.[A-Za-z_]+)+")


def _looks_like_placeholder(value: str) -> bool:
    """True for values that are references, templates, masks or code, not real secrets."""
    low = value.lower()
    return (
        low.startswith(_REFERENCE_STARTS)
        or low in _NON_SECRET_WORDS
        or set(value) <= _MASK_CHARS
        or _CODE_START.match(value) is not None
        or _ATTRIBUTE.fullmatch(value) is not None
    )


def detect_assignment(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _ASSIGN_RE.finditer(text):
        value = m.group("value").rstrip(".,;:)]}>")  # trailing punctuation is not the secret
        if len(value) < _MIN_VALUE_CHARS or _looks_like_placeholder(value):
            continue
        kind = (
            FindingType.SECRET_API_KEY
            if m.group("name").lower().startswith("api")
            else FindingType.SECRET_TOKEN
        )
        start = m.start("value")
        found.append(Detection(kind, "SEC-ASSIGN-001", start, start + len(value), 0.8))
    return found


# --- PEM private keys --------------------------------------------------------------
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY(?: BLOCK)?-----")
_PEM_END = re.compile(r"-----END [A-Z ]{0,30}PRIVATE KEY(?: BLOCK)?-----")
MAX_PEM_CHARS = 16384  # a key with no END line is redacted at most this far


def detect_private_key(text: str) -> list[Detection]:
    found: list[Detection] = []
    pos = 0
    while (begin := _PEM_BEGIN.search(text, pos)) is not None:
        window_end = min(len(text), begin.end() + MAX_PEM_CHARS)
        end = _PEM_END.search(text, begin.end(), window_end)
        stop = end.end() if end is not None else window_end
        found.append(
            Detection(FindingType.SECRET_PRIVATE_KEY, "SEC-PEM-001", begin.start(), stop, 1.0)
        )
        pos = stop
    return found
