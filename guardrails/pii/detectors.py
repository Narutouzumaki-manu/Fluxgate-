"""PII detectors (M1-2). Each detector scans text and reports where it found something.

Detectors only FIND; M1-4 hides. Spans refer to the string that was scanned, normally the
normalized view's text. All regexes use bounded repeats (ReDoS rule).
"""

from __future__ import annotations

import re

from guardrails.detection import Detection as Detection  # re-exported for existing imports
from guardrails.detection import resolve_overlaps as resolve_overlaps  # likewise
from guardrails.pii.validators import card_network, is_valid_aadhaar, is_valid_card, is_valid_pan
from shared.contracts.enums import FindingType

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


# --- Aadhaar ---------------------------------------------------------------------
# 12 digits, first digit 2-9, optionally grouped 4-4-4 with ONE consistent separator.
_AADHAAR_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?<![0-9][ -])"
    r"[2-9][0-9]{3}([ -]?)[0-9]{4}\1[0-9]{4}"
    r"(?![A-Za-z0-9_])(?![ -][0-9])"
)


def detect_aadhaar(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _AADHAAR_RE.finditer(text):
        digits = "".join(ch for ch in m.group() if ch.isdigit())
        if is_valid_aadhaar(digits):  # a bad Verhoeff check digit means "not an Aadhaar"
            found.append(
                Detection(FindingType.PII_AADHAAR, "PII-AADHAAR-VERHOEFF", m.start(), m.end(), 0.95)
            )
    return found


# --- PAN ---------------------------------------------------------------------------
_PAN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{5}[0-9]{4}[A-Za-z](?![A-Za-z0-9])")


def detect_pan(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _PAN_RE.finditer(text):
        if is_valid_pan(m.group()):  # the 4th letter must be a real holder type
            found.append(Detection(FindingType.PII_PAN, "PII-PAN-001", m.start(), m.end(), 0.9))
    return found


# --- Payment card ------------------------------------------------------------------
# 13-19 digits with an optional single space or hyphen between any two digits.
# Same boundary guards as Aadhaar so we never start or stop in the middle of a longer number.
_CARD_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?<![0-9][ -])"
    r"[0-9](?:[ -]?[0-9]){12,18}"
    r"(?![A-Za-z0-9_])(?![ -][0-9])"
)


def detect_card(text: str) -> list[Detection]:
    found: list[Detection] = []
    for m in _CARD_RE.finditer(text):
        digits = "".join(ch for ch in m.group() if ch.isdigit())
        if is_valid_card(digits) and card_network(digits) is not None:
            found.append(Detection(FindingType.PII_CARD, "PII-CARD-LUHN", m.start(), m.end(), 0.9))
    return found


def detect_pii(text: str) -> list[Detection]:
    """Run every PII detector and return clean, non-overlapping detections, in text order."""
    return resolve_overlaps(
        [
            *detect_email(text),
            *detect_phone(text),
            *detect_aadhaar(text),
            *detect_pan(text),
            *detect_card(text),
        ]
    )
