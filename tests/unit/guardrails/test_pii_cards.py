import time
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.pii.detectors import (
    Detection,
    detect_card,
    detect_pii,
    resolve_overlaps,
)
from guardrails.pii.validators import card_network, luhn_check_digit
from shared.contracts.enums import FindingType
from tests.unit.guardrails.pii_helpers import make_aadhaar, spaced

# Public test numbers published by card networks and payment providers. Not real cards.
PUBLIC_TEST_CARDS = [
    "4111111111111111",
    "4012888888881881",
    "5555555555554444",
    "2221000000000009",
    "378282246310005",
    "371449635398431",
    "6011111111111117",
    "3530111333300000",
    "30569309025904",
]


def slices(text: str, detections: list[Detection]) -> list[str]:
    return [text[d.start : d.end] for d in detections]


# --- card_network ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("digits", "network"),
    [
        ("4111111111111111", "visa"),
        ("5105105105105100", "mastercard"),
        ("2221000000000009", "mastercard"),
        ("378282246310005", "amex"),
        ("6011111111111117", "discover"),
        ("6500000000000000", "discover"),
        ("6440000000000000", "discover"),
        ("3530111333300000", "jcb"),
        ("30569309025904", "diners"),
        ("3600000000000000", "diners"),
        ("6200000000000000", "unionpay"),
        ("6070000000000000", "rupay"),
        ("8100000000000000", "rupay"),
        ("5080000000000000", "rupay"),
        ("5018000000000000", "maestro"),
        ("6304000000000000", "maestro"),
        ("6759000000000000", "maestro"),
        ("1000000000000000", None),
        ("9000000000000000", None),
        ("0000000000000000", None),
        ("41", None),
        ("\u0664\u0661\u0661\u0661", None),  # ARABIC-INDIC digits
    ],
)
def test_card_network_from_prefix(digits: str, network: str | None) -> None:
    assert card_network(digits) == network


# --- detect_card -------------------------------------------------------------------------
@pytest.mark.parametrize("card", PUBLIC_TEST_CARDS)
def test_public_test_cards_are_found_plain_and_grouped(card: str) -> None:
    for form in (card, spaced(card), spaced(card, sep="-")):
        text = f"pay with {form} today"
        detections = detect_card(text)
        assert slices(text, detections) == [form]
        assert detections[0].type == FindingType.PII_CARD
        assert detections[0].rule_id == "PII-CARD-LUHN"
        assert detections[0].confidence == 0.9


def test_amex_style_grouping_is_found() -> None:
    text = "card 3782 822463 10005 ok"
    assert slices(text, detect_card(text)) == ["3782 822463 10005"]


def test_wrong_check_digit_is_ignored() -> None:
    assert detect_card("4111111111111112") == []


def test_unknown_prefix_is_ignored() -> None:
    for first in "19":
        body = first + "0" * 14
        assert detect_card(body + luhn_check_digit(body)) == []


def test_wrong_length_is_ignored() -> None:
    twelve = "4" + "0" * 10
    twelve += luhn_check_digit(twelve)
    twenty = "4" + "0" * 18
    twenty += luhn_check_digit(twenty)
    assert detect_card(twelve) == []
    assert detect_card(twenty) == []


def test_glued_to_letters_is_ignored() -> None:
    assert detect_card("x4111111111111111") == []
    assert detect_card("4111111111111111x") == []


def test_middle_of_a_longer_grouped_number_is_ignored() -> None:
    assert detect_card("1234 4111 1111 1111 1111") == []


# --- resolve_overlaps ----------------------------------------------------------------------
def d(kind: FindingType, start: int, end: int, rule: str = "r") -> Detection:
    return Detection(kind, rule, start, end, 0.9)


EMAIL, PHONE, PAN = FindingType.PII_EMAIL, FindingType.PII_PHONE, FindingType.PII_PAN
AADHAAR, CARD = FindingType.PII_AADHAAR, FindingType.PII_CARD


def test_empty_input() -> None:
    assert resolve_overlaps([]) == []


def test_contained_span_is_dropped_whatever_its_priority() -> None:
    outer, inner = d(EMAIL, 0, 20, "e"), d(PHONE, 5, 15, "p")
    assert resolve_overlaps([inner, outer]) == [outer]


def test_identical_range_keeps_the_higher_priority_type() -> None:
    low, high = d(EMAIL, 3, 9, "e"), d(CARD, 3, 9, "c")
    assert resolve_overlaps([low, high]) == [high]


def test_partial_overlap_merges_with_the_higher_priority_type() -> None:
    result = resolve_overlaps([d(EMAIL, 0, 10, "e"), d(PHONE, 5, 15, "p")])
    assert result == [d(PHONE, 0, 15, "p")]


def test_chain_of_overlaps_merges_into_one() -> None:
    result = resolve_overlaps([d(EMAIL, 0, 10, "e"), d(PHONE, 8, 20, "p"), d(PAN, 18, 30, "n")])
    assert result == [d(PAN, 0, 30, "n")]


def test_touching_spans_stay_separate() -> None:
    items = [d(PHONE, 5, 9, "p"), d(EMAIL, 0, 5, "e")]
    assert resolve_overlaps(items) == [d(EMAIL, 0, 5, "e"), d(PHONE, 5, 9, "p")]


def _make_detection(kind: FindingType, start: int, length: int) -> Detection:
    return Detection(kind, f"r-{kind.value}", start, start + length, 0.9)


_detections = st.builds(
    _make_detection,
    st.sampled_from([EMAIL, PHONE, AADHAAR, PAN, CARD]),
    st.integers(0, 40),
    st.integers(1, 15),
)


@given(st.lists(_detections, max_size=12))
def test_resolution_properties(items: list[Detection]) -> None:
    out = resolve_overlaps(items)
    for a, b in pairwise(out):
        assert a.end <= b.start  # sorted and non-overlapping
    covered_in = {i for x in items for i in range(x.start, x.end)}
    covered_out = {i for x in out for i in range(x.start, x.end)}
    assert covered_in == covered_out  # nothing flagged is left uncovered
    assert resolve_overlaps(out) == out  # resolving twice changes nothing
    assert resolve_overlaps(list(reversed(items))) == out  # input order does not matter


# --- detect_pii ------------------------------------------------------------------------------
def test_all_five_types_in_one_message() -> None:
    aadhaar = spaced(make_aadhaar(9))
    text = (
        f"mail a@b.io call +91 98765 43210 aadhaar {aadhaar} "
        "pan ABCPE1234F card 4111 1111 1111 1111"
    )
    found = [(x.type, text[x.start : x.end]) for x in detect_pii(text)]
    assert found == [
        (EMAIL, "a@b.io"),
        (PHONE, "+91 98765 43210"),
        (AADHAAR, aadhaar),
        (PAN, "ABCPE1234F"),
        (CARD, "4111 1111 1111 1111"),
    ]


def test_phone_looking_digits_inside_an_email_are_part_of_the_email() -> None:
    text = "9876543210@example.com"
    found = detect_pii(text)
    assert [(x.type, text[x.start : x.end]) for x in found] == [(EMAIL, text)]


def test_clean_text_has_no_detections() -> None:
    assert detect_pii("What is the capital of France?") == []


@given(st.text(max_size=300))
def test_detect_pii_output_is_well_formed(text: str) -> None:
    out = detect_pii(text)
    for a, b in pairwise(out):
        assert a.end <= b.start
    for x in out:
        assert 0 <= x.start < x.end <= len(text)


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "4" * 1_000_000,
        "4 " * 500_000,
        "4-" * 500_000,
        "4111 " * 200_000,
        "9876543210@" * 90_000,
        "1" * 20 + " " + "4" * 1_000_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_pii(text)
        assert time.perf_counter() - start < 3.0
