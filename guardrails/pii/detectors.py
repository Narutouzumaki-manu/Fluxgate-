"""PII detectors (M1-2). Each detector scans text and reports where it found something.

Detectors only FIND; M1-4 hides. Spans refer to the string that was scanned, normally the
normalized view's text. All regexes use bounded repeats (ReDoS rule).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.contracts.enums import FindingType


@dataclass(frozen=True)
class Detection:
    """One detected item. Never stores the matched value itself, only where it is."""

    type: FindingType
    rule_id: str
    start: int
    end: int
    confidence: float


# --- Email ---------------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@"
    r"[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,8}(?![A-Za-z0-9])"
)
_MAX_DOMAIN_CHARS = 255


def detect_email(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _EMAIL_RE.finditer(text):
        matched = m.group().rstrip("-")
        domain = matched.split("@", 1)[1]
        tld = domain.rsplit(".", 1)[-1]
        if len(domain) > _MAX_DOMAIN_CHARS or not (tld.isalpha() and len(tld) >= 2):
            continue
        found.append(
            Detection(
                FindingType.PII_EMAIL,
                "PII-EMAIL-001",
                m.start(),
                m.start() + len(matched),
                0.95,
            )
        )
    return found


# --- Phone ---------------------------------------------------------------------
# Indian mobile: optional +91 / 0091 / 0, then 6-9 followed by 9 digits (5+5, optional separator).
_IN_PHONE_RE = re.compile(r"(?<![\w+-])((?:\+91|0091)[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\w|[.-]\d)")
# International (E.164-style): + then 8 to 15 digits, optional separators between digits.
_E164_RE = re.compile(r"(?<![\w+-])\+[1-9](?:[\s.-]?\d){7,14}(?!\w|[.-]\d)")
# Words that mean "this digit string is an ID, not a phone number".
_PHONE_STOPLIST = re.compile(
    r"\b(?:order|invoice|inv|id|ref|reference|txn|transaction|tracking|awb|ticket|"
    r"serial|sku|timestamp|ts|epoch|account|acct)\b",
    re.IGNORECASE,
)
_STOPLIST_WINDOW = 24


def detect_phone(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _IN_PHONE_RE.finditer(text):
        prefix = m.group(1) or ""
        strong = prefix.startswith(("+91", "0091"))
        stoplist_context = text[max(0, m.start() - _STOPLIST_WINDOW) : m.start()]
        if not strong and _PHONE_STOPLIST.search(stoplist_context):
            continue
        found.append(
            Detection(
                FindingType.PII_PHONE,
                "PII-PHONE-IN-001",
                m.start(),
                m.end(),
                0.9 if strong else 0.7,
            )
        )
    in_spans = [(d.start, d.end) for d in found]
    for m in _E164_RE.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in in_spans):
            continue  # already reported as an Indian number
        found.append(
            Detection(FindingType.PII_PHONE, "PII-PHONE-E164-001", m.start(), m.end(), 0.7)
        )
    return sorted(found, key=lambda d: d.start)
