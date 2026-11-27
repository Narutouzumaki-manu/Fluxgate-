"""Test helpers for PII tests. Everything here makes up numbers; none is a real identity."""

import random

from guardrails.pii.validators import verhoeff_check_digit

DIGITS = "0123456789"


def make_aadhaar(seed: int) -> str:
    """A made-up Aadhaar-shaped number with a valid check digit."""
    rng = random.Random(seed)
    body = rng.choice("23456789") + "".join(rng.choice(DIGITS) for _ in range(10))
    return body + verhoeff_check_digit(body)


def spaced(number: str, size: int = 4, sep: str = " ") -> str:
    """'234567890123' -> '2345 6789 0123' (or with another separator)."""
    return sep.join(number[i : i + size] for i in range(0, len(number), size))
