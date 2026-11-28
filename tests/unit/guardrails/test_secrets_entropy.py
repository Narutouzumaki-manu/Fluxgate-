import hashlib
import random
import string
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.secrets.entropy import (
    MAX_LEN,
    _wordy,
    detect_high_entropy,
    shannon_entropy,
)
from shared.contracts.enums import FindingType
from shared.ids import new_request_id, new_ulid

ALPHABET = string.ascii_letters + string.digits


def random_token(seed: int, n: int = 40, extra: str = "") -> str:
    rng = random.Random(seed)
    return "".join(rng.choice(ALPHABET + extra) for _ in range(n))


def seen(text: str) -> list[str]:
    return [text[d.start : d.end] for d in detect_high_entropy(text)]


# --- entropy maths --------------------------------------------------------------------------
def test_entropy_known_values() -> None:
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaa") == 0.0
    assert abs(shannon_entropy("abab") - 1.0) < 1e-9
    assert abs(shannon_entropy("abcd") - 2.0) < 1e-9
    assert abs(shannon_entropy("0123456789abcdef") - 4.0) < 1e-9


# --- random tokens are found --------------------------------------------------------------------
@pytest.mark.parametrize("n", range(32, 65))
def test_random_tokens_are_found(n: int) -> None:
    token = random_token(n, n)
    found = detect_high_entropy(f"secret blob {token} end")
    assert [f"secret blob {token} end"[d.start : d.end] for d in found] == [token]
    assert found[0].type == FindingType.SECRET_HIGH_ENTROPY
    assert found[0].rule_id == "SEC-ENTROPY-001"
    assert found[0].confidence == 0.6


def test_token_with_dashes_underscores_plus_and_slash_is_found() -> None:
    for seed in range(20):
        token = random_token(seed, 44, extra="-_+/")
        assert seen(f"x {token} y") == [token]


def test_letters_only_random_token_is_found() -> None:
    token = "kQzPmWxRvTnLhYdFsGbJcAeUiO"  # random case, no digits
    assert seen(f"id {token}") == [token]


def test_the_name_in_name_equals_value_is_not_part_of_the_detection() -> None:
    token = random_token(1)
    assert seen(f"API_KEY={token}") == [token]
    assert seen(f"secret_value:{token}.") == [token]


def test_base64_padding_is_part_of_the_span() -> None:
    token = random_token(2, 42)
    assert seen(f"data {token}== more") == [token + "=="]


def test_two_tokens_are_both_found() -> None:
    a, b = random_token(3), random_token(4)
    assert seen(f"{a} and {b}") == [a, b]


# --- length limits ------------------------------------------------------------------------------
def test_length_boundaries() -> None:
    assert seen(random_token(5, 200)) == [random_token(5, 200)]
    assert seen(random_token(5, MAX_LEN + 1)) == []  # a longer run is never examined
    assert seen("aB3xZ9qL2mN8vK5tR7y") == []  # 19 characters


def test_a_20_character_token_with_all_different_characters_is_found() -> None:
    token = string.ascii_uppercase[:10] + string.digits  # entropy log2(20) = 4.32
    assert seen(token) == [token]


def test_a_20_character_token_just_under_the_threshold_is_not_found() -> None:
    sixteen = string.digits + string.ascii_uppercase[:6]
    token = sixteen + sixteen[:4]  # 16 different characters, 4 repeated: about 3.92
    assert shannon_entropy(token) < 4.0
    assert seen(token) == []


@pytest.mark.parametrize("token", ["a" * 40, "ab12" * 10, "0123456789" * 3])
def test_low_entropy_tokens_are_ignored(token: str) -> None:
    assert seen(token) == []


# --- the allowlist ------------------------------------------------------------------------------
def test_uuids_are_ignored() -> None:
    assert seen("request id 123e4567-e89b-12d3-a456-426614174000") == []
    assert seen("id 123E4567-E89B-12D3-A456-426614174000") == []


@pytest.mark.parametrize("label", ["sha256: ", "sha1=", "md5 ", "commit ", "hash: ", 'checksum="'])
def test_hashes_with_a_label_are_ignored(label: str) -> None:
    for size, digest in ((32, hashlib.md5), (40, hashlib.sha1), (64, hashlib.sha256)):
        value = digest(b"x").hexdigest()
        assert len(value) == size
        assert seen(f"{label}{value}") == []


def test_bare_hex_hashes_are_not_flagged_because_hex_entropy_is_low() -> None:
    for i in range(20):
        assert seen(hashlib.sha256(str(i).encode()).hexdigest()) == []


def test_image_data_is_ignored_but_the_same_blob_without_the_prefix_is_found() -> None:
    blob = random_token(6, 60)
    assert seen(f"data:image/png;base64,{blob}") == []
    assert seen(f"blob {blob}") == [blob]


@pytest.mark.parametrize(
    "name",
    [
        "my-long-descriptive-variable-name-here",
        "createAuthenticationTokenManagerFactory",
        "tests/unit/guardrails/test_secrets_entropy_module",
        "abcdefghijklmnopqrstuvwxyz",
        "internationalization_and_localization",
        "SOME_VERY_LONG_CONSTANT_NAME_HERE",
        "_internal_helper_function_name_",
        "annual-report-2026-final-version-draft",
    ],
)
def test_names_paths_and_slugs_are_ignored(name: str) -> None:
    assert seen(name) == []


def test_wordy_decisions_directly() -> None:
    assert _wordy("annual-report-2026-final")
    assert _wordy("createAuthenticationManager")
    assert _wordy("_internal_name_")
    assert not _wordy("report-1700000000")  # a long number
    assert not _wordy("v2x-handler")  # letters and digits mixed in one piece
    assert not _wordy("kQzPmWxRvTnLhYdFsGbJcAeUiO")  # case flips every few letters


# --- safety ---------------------------------------------------------------------------------------
@given(st.text(max_size=300))
def test_detections_are_always_well_formed(text: str) -> None:
    for d in detect_high_entropy(text):
        assert 0 <= d.start < d.end <= len(text)


@given(st.text(alphabet=ALPHABET + "-_+/= ", max_size=400))
def test_detections_on_token_like_text_are_well_formed(text: str) -> None:
    for d in detect_high_entropy(text):
        assert 0 <= d.start < d.end <= len(text)
        assert 20 <= d.end - d.start <= MAX_LEN + 2


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "A" * 1_000_000,
        random_token(7, 1_000_000),
        "-" * 1_000_000,
        "a-" * 500_000,
        "/" * 1_000_000,
        "aB3xZ9qL2mN8vK5tR7yW " * 50_000,
        ("x" * 199 + " ") * 5_000,
        ("x" * 201 + " ") * 5_000,
        "=" * 1_000_000,
        random_token(8, 190) + "=" * 500_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_high_entropy(text)
        assert time.perf_counter() - start < 3.0


def test_ulids_and_request_ids_are_ignored() -> None:
    for _ in range(50):
        assert seen(f"id {new_ulid()}") == []
        assert seen(f"log {new_request_id()} done") == []


@pytest.mark.parametrize("algo", ["sha256", "sha384", "sha512"])
def test_integrity_hashes_are_ignored(algo: str) -> None:
    digest = random_token(9, 86, extra="+/")
    assert seen(f"integrity {algo}-{digest}==") == []
    assert seen(f"integrity {digest}==") != []  # the same blob without the prefix is a finding
