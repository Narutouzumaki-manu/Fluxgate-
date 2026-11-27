import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.pii.detectors import Detection, detect_email, detect_phone
from shared.contracts.enums import FindingType


def slices(text: str, detections: list[Detection]) -> list[str]:
    return [text[d.start : d.end] for d in detections]


# --- Email --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("write to user@example.com please", "user@example.com"),
        ("first.last+tag@sub.example.co.in", "first.last+tag@sub.example.co.in"),
        ("USER@EXAMPLE.COM", "USER@EXAMPLE.COM"),
        ("<a@b.io>", "a@b.io"),
        ("(a@b.io)", "a@b.io"),
        ("mail a@b.com.", "a@b.com"),
        ("mail a@b.com-", "a@b.com"),
        ("not..dots@example.com", "not..dots@example.com"),
    ],
)
def test_emails_are_found(text: str, expected: str) -> None:
    detections = detect_email(text)
    assert slices(text, detections) == [expected]
    assert detections[0].type == FindingType.PII_EMAIL
    assert detections[0].rule_id == "PII-EMAIL-001"
    assert detections[0].confidence == 0.95


def test_multiple_emails_are_all_found() -> None:
    text = "a@b.io and c@d.org"
    assert slices(text, detect_email(text)) == ["a@b.io", "c@d.org"]


@pytest.mark.parametrize(
    "text",
    [
        "user@localhost",
        "a@b.c",
        "@handle",
        "user@",
        "foo@1.2.3",
        "a@b.12",
        "no at sign here",
        "a@@b.com",
    ],
)
def test_non_emails_are_ignored(text: str) -> None:
    assert detect_email(text) == []


def test_overlong_domain_is_ignored() -> None:
    domain = ".".join(["x" * 63] * 5)  # 319 characters
    assert detect_email(f"a@{domain}") == []


# --- Phone ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call 9876543210 now", "9876543210"),
        ("call 98765 43210 now", "98765 43210"),
        ("call 98765-43210 now", "98765-43210"),
        ("call 098765 43210", "098765 43210"),
        ("call +91 98765 43210", "+91 98765 43210"),
        ("call +91-9876543210", "+91-9876543210"),
        ("call 0091 9876543210", "0091 9876543210"),
        ("call 9876543210.", "9876543210"),
        ("call +1 415 555 2671", "+1 415 555 2671"),
        ("call +442071838750", "+442071838750"),
        ("call +44 20 7183 8750", "+44 20 7183 8750"),
    ],
)
def test_phone_numbers_are_found(text: str, expected: str) -> None:
    detections = detect_phone(text)
    assert slices(text, detections) == [expected]
    assert detections[0].type == FindingType.PII_PHONE


def test_prefix_gives_higher_confidence() -> None:
    assert detect_phone("+91 9876543210")[0].confidence == 0.9
    assert detect_phone("9876543210")[0].confidence == 0.7
    assert detect_phone("+1 415 555 2671")[0].confidence == 0.7


def test_indian_number_is_reported_once_not_twice() -> None:
    detections = detect_phone("+91 98765 43210")
    assert len(detections) == 1
    assert detections[0].rule_id == "PII-PHONE-IN-001"


def test_two_numbers_in_one_message() -> None:
    text = "call 9876543210 or +1 415 555 2671"
    assert slices(text, detect_phone(text)) == ["9876543210", "+1 415 555 2671"]


@pytest.mark.parametrize(
    "text",
    [
        "987654321012",  # 12 digits: not a phone number
        "1700000000",  # unix timestamp (starts with 1)
        "4111111111111111",  # card number
        "version 1.2.3.4",
        "2024-11-27T10:15:30",
        "5555555555",  # starts with 5
        "9876543210.5",
        "2023-9876543210",
    ],
)
def test_digit_strings_that_are_not_phones_are_ignored(text: str) -> None:
    assert detect_phone(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "order 9876543210 shipped",
        "Order ID: 9876543210",
        "invoice no 9123456789",
        "txn ref 9876543210",
        "account number 9876543210",
        "ts=9876543210",
    ],
)
def test_ids_next_to_stoplist_words_are_ignored(text: str) -> None:
    assert detect_phone(text) == []


def test_international_prefix_overrides_the_stoplist() -> None:
    text = "order: +91 9876543210"
    assert slices(text, detect_phone(text)) == ["+91 9876543210"]


def test_stoplist_word_far_away_does_not_suppress() -> None:
    text = "order " + "x" * 30 + " 9876543210"
    assert slices(text, detect_phone(text)) == ["9876543210"]


# --- Safety properties ---------------------------------------------------------------
@given(st.text(max_size=300))
def test_detections_are_always_well_formed(text: str) -> None:
    for d in detect_email(text) + detect_phone(text):
        assert 0 <= d.start < d.end <= len(text)
        assert 0 < d.confidence <= 1


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "a" * 1_000_000,
        "a@" * 500_000,
        "a." * 500_000,
        "a@a." * 250_000,
        "9" * 1_000_000,
        "9 " * 500_000,
        "+9 " * 300_000,
        ("x" * 70 + "@") * 10_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_email(text)
        detect_phone(text)
        assert time.perf_counter() - start < 2.0
