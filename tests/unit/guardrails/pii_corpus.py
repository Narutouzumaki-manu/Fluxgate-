"""Synthetic PII corpora for the detector tests (M1-2).

Everything is generated from fixed seeds. Nothing here is real: positives are made-up
numbers with valid checksums, negatives are harmless look-alikes. verify_m1 (M1-12)
reuses this module.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable

from guardrails.pii.validators import luhn_check_digit
from shared.contracts.enums import FindingType
from tests.unit.guardrails.pii_helpers import make_aadhaar, spaced

DIGITS = "0123456789"
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = _LOWER.upper()
_HOLDER_TYPES = "ABCFGHJLPT"


def _digits(rng: random.Random, n: int, first: str = DIGITS) -> str:
    return rng.choice(first) + "".join(rng.choice(DIGITS) for _ in range(n - 1))


def _hex(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


# ---------------------------------------------------------------------------
# Golden positives: made-up PII in several formats
# ---------------------------------------------------------------------------
def _grouped(rng: random.Random, number: str) -> str:
    style = rng.choice(["plain", "space", "hyphen"])
    if style == "space":
        return spaced(number)
    if style == "hyphen":
        return spaced(number, sep="-")
    return number


def _email(rng: random.Random) -> str:
    local = "".join(rng.choice(_LOWER + DIGITS) for _ in range(rng.randint(3, 12)))
    if rng.random() < 0.3:
        local += rng.choice([".", "+", "_"]) + "".join(rng.choice(_LOWER) for _ in range(4))
    domain = rng.choice(["example.com", "mail.example.org", "corp.example.co.in", "test.io"])
    return f"{local}@{domain}"


def _phone(rng: random.Random) -> str:
    if rng.random() < 0.25:  # international
        return "+" + rng.choice("1234567") + _digits(rng, 10)
    number = _digits(rng, 10, "6789")
    number = number[:5] + rng.choice(["", " ", "-"]) + number[5:]
    return rng.choice(["", "+91 ", "+91-", "0", "0091 "]) + number


def _aadhaar(rng: random.Random) -> str:
    return _grouped(rng, make_aadhaar(rng.getrandbits(32)))


def _pan(rng: random.Random) -> str:
    pan = (
        "".join(rng.choice(_UPPER) for _ in range(3))
        + rng.choice(_HOLDER_TYPES)
        + rng.choice(_UPPER)
        + "".join(rng.choice(DIGITS) for _ in range(4))
        + rng.choice(_UPPER)
    )
    return pan.lower() if rng.random() < 0.2 else pan


def _card(rng: random.Random) -> str:
    network = rng.choice(["visa", "mastercard", "amex", "discover", "rupay"])
    if network == "visa":
        body = "4" + _digits(rng, 14)
    elif network == "mastercard":
        body = "5" + rng.choice("12345") + _digits(rng, 13)
    elif network == "amex":
        body = rng.choice(["34", "37"]) + _digits(rng, 12)
    elif network == "discover":
        body = "6011" + _digits(rng, 11)
    else:  # rupay
        body = "81" + _digits(rng, 13)
    return _grouped(rng, body + luhn_check_digit(body))


GOLDEN_MAKERS: dict[FindingType, Callable[[random.Random], str]] = {
    FindingType.PII_EMAIL: _email,
    FindingType.PII_PHONE: _phone,
    FindingType.PII_AADHAAR: _aadhaar,
    FindingType.PII_PAN: _pan,
    FindingType.PII_CARD: _card,
}

# No word here is on the phone stoplist.
_TEMPLATES = [
    "contact {x} for details",
    "{x}",
    "value: {x}.",
    "send it to ({x}) soon",
    "note, {x}, thanks",
]


def golden_samples(kind: FindingType, n: int = 300, seed: int = 7) -> list[tuple[str, str]]:
    """(text, planted value) pairs. The detector should find `value` inside `text`."""
    rng = random.Random(f"{seed}-{kind.value}")
    make = GOLDEN_MAKERS[kind]
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        value = make(rng)
        samples.append((rng.choice(_TEMPLATES).format(x=value), value))
    return samples


# ---------------------------------------------------------------------------
# Benign corpus: harmless text that looks a bit like PII
# ---------------------------------------------------------------------------
SENTENCES = [
    "What is the capital of France?",
    "Explain how photosynthesis works in simple terms.",
    "Summarize the quarterly report in three bullet points.",
    "How do I reset my password on the portal?",
    "My PAN card and Aadhaar card are required for KYC verification.",
    "Never share your credit card number or CVV with anyone.",
    "A Verhoeff checksum detects every single digit error.",
    "The Luhn algorithm validates payment card numbers.",
    "Translate good morning into Hindi and Kannada.",
    "What are the main differences between TCP and UDP?",
    "Draft an email to my manager about the release schedule.",
    "Please review the attached design document by Friday.",
    "The meeting is scheduled for the third week of March.",
    "Our support team answers questions every weekday.",
    "List five healthy breakfast ideas for busy mornings.",
    "How does a circuit breaker protect a distributed system?",
    "Explain semantic caching and why thresholds matter.",
    "The server returned status 503 after three retries.",
    "Set the cache threshold to 0.92 and the TTL to 86400 seconds.",
    "The model has 384 dimensions and runs on the CPU.",
    "Rate limit: 60 requests per minute, burst of 10.",
    "This project is licensed under Apache-2.0.",
    "Contact the helpdesk through the in-app chat widget.",
    "Prompt injection is ranked first in the OWASP LLM Top 10.",
    "She scored 98 out of 100 in the final examination.",
    "The flight leaves at 6:45 and lands at 9:10.",
    "Population grew from 1.2 million to 1.9 million.",
    "Use the formula area = pi * r * r for a circle.",
    "Paste the error message and the last twenty log lines.",
]

CODE = [
    "def add(a: int, b: int) -> int:\n    return a + b",
    "SELECT id, name FROM users WHERE age > 30 ORDER BY name;",
    "@property\ndef value(self) -> int:\n    return self._value",
    "result = A @ B  # matrix multiply",
    "git clone https://github.com/example/repo.git",
    "pip install fastapi==0.115.0",
    '{"status": "ok", "count": 12345, "items": []}',
    "for i in range(100):\n    print(i)",
    "const total = 1234567;",
    "total = 12345678  # bytes",
    "curl -N http://localhost:8000/v1/models",
    "export FLUXGATE_L2_THRESHOLD=0.92",
    "docker compose up --build",
    "ssh user@prod-server",
    "Ping @alice about the release notes.",
    "if x >= 0.85: block()",
    "mask = 0xFFFF0000",
    "# TODO: handle the empty case",
    '<div class="card" id="main"></div>',
    'print(f"{name}: {value:.2f}")',
]


def benign_corpus_by_category() -> dict[str, list[str]]:
    rng = random.Random(20261127)
    c: dict[str, list[str]] = {}
    c["uuid"] = [f"request id {uuid.UUID(int=rng.getrandbits(128), version=4)}" for _ in range(60)]
    c["git_sha"] = [f"commit {_hex(rng, rng.choice([7, 12, 40]))}" for _ in range(40)]
    c["sha256"] = [f"sha256:{_hex(rng, 64)}" for _ in range(30)]
    c["version"] = [
        f"release v{rng.randint(0, 20)}.{rng.randint(0, 99)}.{rng.randint(0, 999)}"
        for _ in range(25)
    ] + [
        f"build {rng.randint(1, 9)}.{rng.randint(0, 9)}.{rng.randint(0, 99)}.{rng.randint(0, 9999)}"
        for _ in range(15)
    ]
    c["iso_timestamp"] = [
        f"created at 2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
        for _ in range(40)
    ]
    c["unix_time"] = [f"ts {rng.randint(1_600_000_000, 1_790_000_000)}" for _ in range(20)] + [
        f"epoch_ms {rng.randint(1_600_000_000_000, 1_790_000_000_000)}" for _ in range(20)
    ]
    words = [
        "order",
        "invoice no",
        "Invoice",
        "txn ref",
        "ticket",
        "tracking id",
        "ref",
        "account no",
        "AWB",
    ]
    c["order_ids"] = [
        f"{rng.choice(words)} {_digits(rng, 10, '6789')} was processed" for _ in range(60)
    ]
    c["tracking_12_digit"] = [f"tracking number {_digits(rng, 12)}" for _ in range(20)]
    c["long_numeric_ids"] = [
        f"object {_digits(rng, rng.randint(13, 19), '123456789')} stored" for _ in range(30)
    ]
    c["ipv4"] = [
        f"connect to {'.'.join(str(rng.randint(1, 254)) for _ in range(4))} "
        f"port {rng.randint(1024, 65535)}"
        for _ in range(30)
    ]
    c["mac"] = [f"mac {':'.join(_hex(rng, 2) for _ in range(6))}" for _ in range(20)]
    c["color"] = [f"color #{_hex(rng, 6)}" for _ in range(20)]
    c["paths"] = [f"/var/log/app/{_hex(rng, 8)}.log" for _ in range(10)] + [
        f"C:\\Users\\dev\\{_hex(rng, 8)}.txt" for _ in range(10)
    ]
    c["alnum_ids"] = [
        f"ticket {''.join(rng.choice(_UPPER + DIGITS) for _ in range(10))}" for _ in range(40)
    ]
    c["amounts"] = [
        f"total INR {rng.randint(1, 99)},{rng.randint(10, 99)},{rng.randint(100, 999)}.00"
        for _ in range(20)
    ]
    c["sentences"] = list(SENTENCES)
    c["code"] = list(CODE)
    return c
