import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.pii.detectors import Detection, detect_aadhaar, detect_pan
from guardrails.pii.validators import verhoeff_check_digit
from shared.contracts.enums import FindingType
from tests.unit.guardrails.pii_helpers import make_aadhaar, spaced


def slices(text: str, detections: list[Detection]) -> list[str]:
    return [text[d.start : d.end] for d in detections]


# --- Aadhaar --------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(20))
def test_valid_aadhaar_is_found_plain_spaced_and_hyphenated(seed: int) -> None:
    number = make_aadhaar(seed)
    for form in (number, spaced(number), spaced(number, sep="-")):
        text = f"my aadhaar is {form} thanks"
        detections = detect_aadhaar(text)
        assert slices(text, detections) == [form]
        assert detections[0].type == FindingType.PII_AADHAAR
        assert detections[0].rule_id == "PII-AADHAAR-VERHOEFF"
        assert detections[0].confidence == 0.95


def test_punctuation_after_the_number_is_fine() -> None:
    number = make_aadhaar(3)
    text = f"({spaced(number)}), ok"
    assert slices(text, detect_aadhaar(text)) == [spaced(number)]


def test_wrong_check_digit_is_ignored() -> None:
    number = make_aadhaar(1)
    wrong = number[:-1] + str((int(number[-1]) + 1) % 10)
    assert detect_aadhaar(f"id {wrong}") == []
    assert detect_aadhaar(f"id {spaced(wrong)}") == []


def test_leading_zero_or_one_is_ignored() -> None:
    for first in "01":
        body = first + "23456789012"
        assert detect_aadhaar(body + verhoeff_check_digit(body)) == []


def test_wrong_length_is_ignored() -> None:
    number = make_aadhaar(2)
    assert detect_aadhaar(number[:-1]) == []
    assert detect_aadhaar("7" + number) == []
    assert detect_aadhaar(number + "7") == []


def test_mixed_separators_are_ignored() -> None:
    number = make_aadhaar(4)
    assert detect_aadhaar(f"{number[:4]} {number[4:8]}-{number[8:]}") == []


def test_glued_to_letters_or_other_digits_is_ignored() -> None:
    number = make_aadhaar(5)
    assert detect_aadhaar(f"x{number}") == []
    assert detect_aadhaar(f"{number}x") == []
    assert detect_aadhaar(f"ID-{number}") == []


def test_tail_of_a_spaced_card_number_is_not_an_aadhaar() -> None:
    number = make_aadhaar(6)
    assert detect_aadhaar(f"4111 {spaced(number)}") == []


def test_head_of_a_longer_spaced_number_is_not_an_aadhaar() -> None:
    number = make_aadhaar(7)
    assert detect_aadhaar(f"{spaced(number)} 9999") == []


# --- PAN ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PAN is ABCPE1234F.", "ABCPE1234F"),
        ("pan abcpe1234f ok", "abcpe1234f"),
        ("(AAACB1234C)", "AAACB1234C"),
        ("ABCPE1234F", "ABCPE1234F"),
        ("pan_ABCPE1234F", "ABCPE1234F"),
    ],
)
def test_valid_pan_is_found(text: str, expected: str) -> None:
    detections = detect_pan(text)
    assert slices(text, detections) == [expected]
    assert detections[0].type == FindingType.PII_PAN
    assert detections[0].rule_id == "PII-PAN-001"
    assert detections[0].confidence == 0.9


def test_two_pans_in_one_message() -> None:
    text = "ABCPE1234F and AAACB1234C"
    assert slices(text, detect_pan(text)) == ["ABCPE1234F", "AAACB1234C"]


@pytest.mark.parametrize(
    "text",
    [
        "ABCXE1234F",  # X is not a holder type
        "AB12CD34EF",  # random ten-character ID
        "ABCPE12345",  # last character must be a letter
        "ABCPE1234",  # too short
        "xABCPE1234F",  # glued to a letter
        "ABCPE1234FG",  # glued to a letter
        "1ABCPE1234F",  # glued to a digit
    ],
)
def test_non_pans_are_ignored(text: str) -> None:
    assert detect_pan(text) == []


# --- Safety properties -------------------------------------------------------------------------
@given(st.text(max_size=300))
def test_detections_are_always_well_formed(text: str) -> None:
    for d in detect_aadhaar(text) + detect_pan(text):
        assert 0 <= d.start < d.end <= len(text)
        assert 0 < d.confidence <= 1


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "2" * 1_000_000,
        "2345 " * 200_000,
        "2345-" * 200_000,
        "A" * 1_000_000,
        "ABCDE1234" * 100_000,
        "AAAAA1111A " * 90_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_aadhaar(text)
        detect_pan(text)
        assert time.perf_counter() - start < 2.0
