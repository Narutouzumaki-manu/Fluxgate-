import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.pii.validators import (
    is_valid_aadhaar,
    is_valid_card,
    is_valid_luhn,
    is_valid_pan,
    is_valid_verhoeff,
    luhn_check_digit,
    verhoeff_check_digit,
)

DIGITS = "0123456789"
_digit_strings = st.text(alphabet=DIGITS, min_size=1, max_size=30)


def make_aadhaar(seed: int) -> str:
    """A made-up Aadhaar-shaped number with a valid check digit (never a real identity)."""
    rng = random.Random(seed)
    body = rng.choice("23456789") + "".join(rng.choice(DIGITS) for _ in range(10))
    return body + verhoeff_check_digit(body)


# --- Verhoeff ---------------------------------------------------------------
def test_verhoeff_known_example() -> None:
    assert verhoeff_check_digit("236") == "3"
    assert is_valid_verhoeff("2363")
    assert not is_valid_verhoeff("2364")


@given(_digit_strings)
def test_verhoeff_generated_numbers_validate(body: str) -> None:
    assert is_valid_verhoeff(body + verhoeff_check_digit(body))


@given(_digit_strings, st.data())
def test_verhoeff_detects_any_single_digit_error(body: str, data: st.DataObject) -> None:
    full = body + verhoeff_check_digit(body)
    i = data.draw(st.integers(0, len(full) - 1))
    wrong = data.draw(st.sampled_from([d for d in DIGITS if d != full[i]]))
    assert not is_valid_verhoeff(full[:i] + wrong + full[i + 1 :])


@given(_digit_strings.filter(lambda s: len(s) >= 2), st.data())
def test_verhoeff_detects_swapped_neighbours(body: str, data: st.DataObject) -> None:
    full = body + verhoeff_check_digit(body)
    i = data.draw(st.integers(0, len(full) - 2))
    if full[i] == full[i + 1]:
        return  # swapping equal digits changes nothing
    swapped = full[:i] + full[i + 1] + full[i] + full[i + 2 :]
    assert not is_valid_verhoeff(swapped)


def test_verhoeff_rejects_non_ascii_digits_and_text() -> None:
    assert not is_valid_verhoeff("")
    assert not is_valid_verhoeff("23\u0663")  # ARABIC-INDIC DIGIT THREE
    assert not is_valid_verhoeff("2363x")


# --- Aadhaar ----------------------------------------------------------------
def test_generated_aadhaar_numbers_are_valid() -> None:
    for seed in range(50):
        assert is_valid_aadhaar(make_aadhaar(seed))


def test_aadhaar_with_a_wrong_check_digit_is_rejected() -> None:
    good = make_aadhaar(1)
    wrong = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert not is_valid_aadhaar(wrong)


def test_aadhaar_cannot_start_with_zero_or_one() -> None:
    for first in "01":
        body = first + "23456789012"
        assert not is_valid_aadhaar(body + verhoeff_check_digit(body))


def test_aadhaar_must_be_twelve_digits() -> None:
    good = make_aadhaar(2)
    assert not is_valid_aadhaar(good[:-1])
    assert not is_valid_aadhaar(good + "0")
    assert not is_valid_aadhaar("")


# --- Luhn / cards ------------------------------------------------------------
def test_luhn_public_test_card_numbers() -> None:
    for number in ["4111111111111111", "4242424242424242", "5555555555554444"]:
        assert is_valid_luhn(number)
        assert is_valid_card(number)


def test_luhn_wrong_check_digit_is_rejected() -> None:
    assert not is_valid_luhn("4111111111111112")


@given(_digit_strings)
def test_luhn_generated_numbers_validate(body: str) -> None:
    assert is_valid_luhn(body + luhn_check_digit(body))


@given(_digit_strings, st.data())
def test_luhn_detects_any_single_digit_error(body: str, data: st.DataObject) -> None:
    full = body + luhn_check_digit(body)
    i = data.draw(st.integers(0, len(full) - 1))
    wrong = data.draw(st.sampled_from([d for d in DIGITS if d != full[i]]))
    assert not is_valid_luhn(full[:i] + wrong + full[i + 1 :])


def test_card_length_must_be_13_to_19() -> None:
    twelve = "4" + "0" * 10
    twelve += luhn_check_digit(twelve)  # 12 digits, Luhn-valid
    assert is_valid_luhn(twelve)
    assert not is_valid_card(twelve)
    twenty = "4" + "0" * 18
    twenty += luhn_check_digit(twenty)  # 20 digits, Luhn-valid
    assert not is_valid_card(twenty)


def test_luhn_rejects_non_digits() -> None:
    assert not is_valid_luhn("")
    assert not is_valid_luhn("4111 1111 1111 1111")  # separators are the detector's job


# --- PAN ----------------------------------------------------------------------
def test_pan_valid_examples() -> None:
    assert is_valid_pan("ABCPE1234F")  # 4th letter P = person
    assert is_valid_pan("abcpe1234f")  # lower case is accepted
    assert is_valid_pan("AAACB1234C")  # 4th letter C = company


def test_pan_wrong_holder_type_is_rejected() -> None:
    assert not is_valid_pan("ABCXE1234F")  # X is not a holder type


def test_pan_wrong_shape_is_rejected() -> None:
    for bad in ["ABCPE1234", "ABCPE12345F", "ABCP11234F", "ABCPEA234F", "ABCPE1234", "1BCPE1234F"]:
        assert not is_valid_pan(bad)
    assert not is_valid_pan("")
    assert not is_valid_pan("ABCPE1234\u00c9")  # non-ASCII letter at the end


def test_check_digit_generators_reject_non_digit_bodies() -> None:
    for bad in ["", "12a", "1 2", "\u0663"]:  # last one: ARABIC-INDIC DIGIT THREE
        with pytest.raises(ValueError, match="ASCII digits"):
            verhoeff_check_digit(bad)
        with pytest.raises(ValueError, match="ASCII digits"):
            luhn_check_digit(bad)
