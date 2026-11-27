"""High-entropy token heuristic (M1-3 step 3).

Flags random-looking tokens that have no recognisable prefix and no telling name. This is a
guess: confidence is 0.6 and the policy decides whether it only warns. All repeats are
bounded (ReDoS rule), and the allowlist runs before the entropy maths.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from itertools import pairwise

from guardrails.detection import Detection
from shared.contracts.enums import FindingType

MIN_LEN = 20
MAX_LEN = 200
MIN_ENTROPY = 4.0  # bits per character
_HASH_LENGTHS = frozenset({32, 40, 64})  # md5, sha1, sha256 as hex
_CONTEXT_WINDOW = 16  # how far back we look for words like "sha256:" or "base64,"

# A run of token characters. '=' only as trailing padding, so NAME=value splits at '='.
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_+/-])[A-Za-z0-9_+/-]{20,200}={0,2}(?![A-Za-z0-9_+/=-])")
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_RE = re.compile(r"[0-9a-fA-F]+")
_HASH_CONTEXT = re.compile(
    r"(?:sha\d{0,3}|md5|commit|hash|checksum|digest|etag)[\s:=\"'-]{0,4}$", re.IGNORECASE
)
_DATA_URI_CONTEXT = re.compile(r"base64,$", re.IGNORECASE)
_SPLIT = re.compile(r"[-_/+]+")


def shannon_entropy(s: str) -> float:
    """Bits of randomness per character (0.0 for an empty string)."""
    if not s:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def _wordy(core: str) -> bool:
    """True if the token reads like names, paths or slugs rather than random characters."""
    for piece in _SPLIT.split(core):
        if not piece:
            continue
        if piece.isdigit():
            if len(piece) > 4:
                return False
        elif piece.isalpha():
            humps = sum(1 for a, b in pairwise(piece) if a.islower() and b.isupper())
            if humps > len(piece) // 7:
                return False
        else:  # letters and digits mixed inside one piece
            return False
    return True


def _allowlisted(core: str, before: str) -> bool:
    if _UUID_RE.fullmatch(core):
        return True
    if len(core) in _HASH_LENGTHS and _HEX_RE.fullmatch(core) and _HASH_CONTEXT.search(before):
        return True
    if _DATA_URI_CONTEXT.search(before):
        return True
    return _wordy(core)


def detect_high_entropy(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _TOKEN_RE.finditer(text):
        core = m.group().rstrip("=")
        before = text[max(0, m.start() - _CONTEXT_WINDOW) : m.start()]
        if _allowlisted(core, before) or shannon_entropy(core) < MIN_ENTROPY:
            continue
        found.append(
            Detection(FindingType.SECRET_HIGH_ENTROPY, "SEC-ENTROPY-001", m.start(), m.end(), 0.6)
        )
    return found
