"""Checksum and structure checks used by the PII detectors (M1-2).

Pure functions: each answers yes/no for ONE candidate string. A passing checksum makes a
match more likely to be real; it does not prove it. The detectors add boundary and
context checks on top.
"""

from __future__ import annotations

# --- Verhoeff (Aadhaar) -----------------------------------------------------
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

# PAN: the 4th letter is the holder type (P = person, C = company, ...).
_PAN_HOLDER_TYPES = frozenset("ABCFGHJLPT")


def _ascii_digits(s: str) -> bool:
    """True for a non-empty string of plain 0-9 only (not other scripts' digits)."""
    return s.isascii() and s.isdigit()


def verhoeff_check_digit(body: str) -> str:
    """The Verhoeff check digit to append to `body` (digits only)."""
    if not _ascii_digits(body):
        raise ValueError("body must be ASCII digits")
    c = 0
    for i, ch in enumerate(reversed(body)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def is_valid_verhoeff(number: str) -> bool:
    """True if `number` (digits, check digit last) passes the Verhoeff checksum."""
    if not _ascii_digits(number):
        return False
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def is_valid_aadhaar(digits: str) -> bool:
    """12 digits, first digit 2-9, valid Verhoeff check digit."""
    return (
        len(digits) == 12
        and _ascii_digits(digits)
        and digits[0] in "23456789"
        and is_valid_verhoeff(digits)
    )


# --- Luhn (payment cards) ---------------------------------------------------
def luhn_check_digit(body: str) -> str:
    """The Luhn check digit to append to `body` (digits only)."""
    if not _ascii_digits(body):
        raise ValueError("body must be ASCII digits")
    total = 0
    for i, ch in enumerate(reversed(body)):
        n = int(ch)
        if i % 2 == 0:  # these become every second digit once the check digit is appended
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - total % 10) % 10)


def is_valid_luhn(number: str) -> bool:
    """True if `number` (digits, check digit last) passes the Luhn checksum."""
    if not _ascii_digits(number):
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def is_valid_card(digits: str) -> bool:
    """13 to 19 digits with a valid Luhn check digit."""
    return 13 <= len(digits) <= 19 and is_valid_luhn(digits)


def card_network(digits: str) -> str | None:
    """Name the card network from the number's starting digits, or None if unknown.

    Checks the prefix only, not the length or the checksum.
    """
    if len(digits) < 4 or not _ascii_digits(digits):
        return None
    p2, p3, p4 = int(digits[:2]), int(digits[:3]), int(digits[:4])
    if digits[0] == "4":
        return "visa"
    if 51 <= p2 <= 55 or 2221 <= p4 <= 2720:
        return "mastercard"
    if p2 in (34, 37):
        return "amex"
    if p4 == 6011 or p2 == 65 or 644 <= p3 <= 649:
        return "discover"
    if 300 <= p3 <= 305 or p2 in (36, 38, 39):
        return "diners"
    if 3528 <= p4 <= 3589:
        return "jcb"
    if p2 == 62:
        return "unionpay"
    if p2 in (60, 81, 82) or p3 == 508:
        return "rupay"
    if p2 in (50, 56, 57, 58, 63, 67):
        return "maestro"
    return None


# --- PAN (Indian tax ID) ----------------------------------------------------
def is_valid_pan(pan: str) -> bool:
    """AAAAA9999A: five letters, four digits, one letter; 4th letter is a holder type."""
    p = pan.upper()
    return (
        len(p) == 10
        and p.isascii()
        and p[:5].isalpha()
        and _ascii_digits(p[5:9])
        and p[9].isalpha()
        and p[3] in _PAN_HOLDER_TYPES
    )
