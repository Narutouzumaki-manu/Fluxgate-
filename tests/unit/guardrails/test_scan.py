import random
import string
import time
from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from guardrails.scan import detect_sensitive
from shared.contracts.enums import FindingType as T

ALPHABET = string.ascii_letters + string.digits


def tok(seed: int, n: int = 40, extra: str = "") -> str:
    rng = random.Random(seed)
    return "".join(rng.choice(ALPHABET + extra) for _ in range(n))


def describe(text: str) -> list[tuple[T, str, str]]:
    return [(d.type, d.rule_id, text[d.start : d.end]) for d in detect_sensitive(text)]


def test_a_jwt_is_one_detection_not_four() -> None:
    jwt = ".".join(["eyJ" + tok(1), "eyJ" + tok(2), tok(3, 43)])
    text = f"jwt {jwt} end"
    assert describe(text) == [(T.SECRET_TOKEN, "SEC-JWT-001", jwt)]


def test_a_provider_key_is_not_double_reported_as_entropy() -> None:
    key = "gsk_" + tok(4)
    assert describe(f"key {key}") == [(T.SECRET_API_KEY, "SEC-GROQ-001", key)]


def test_a_bearer_token_keeps_its_specific_rule() -> None:
    token = tok(5)
    assert describe(f"Authorization: Bearer {token}") == [(T.SECRET_TOKEN, "SEC-BEARER-001", token)]


def test_an_assignment_value_is_flagged_but_not_its_name() -> None:
    value = tok(6)
    assert describe(f"API_KEY={value}") == [(T.SECRET_API_KEY, "SEC-ASSIGN-001", value)]


def test_a_private_key_block_swallows_the_random_lines_inside() -> None:
    kind = "RSA PRIVATE KEY"
    lines = "\n".join(tok(10 + i, 64, extra="+/") for i in range(4))
    block = f"-----BEGIN {kind}-----\n{lines}\n-----END {kind}-----"
    assert describe(f"here:\n{block}\nthanks") == [(T.SECRET_PRIVATE_KEY, "SEC-PEM-001", block)]


def test_a_mixed_message_comes_back_in_text_order() -> None:
    groq, aws, bearer = "gsk_" + tok(7), "AKIA" + "IOSFODNN7EXAMPLE", tok(8)
    text = (
        f"mail a@b.io phone +91 98765 43210 key {groq} aws {aws} "
        f"card 4111 1111 1111 1111 auth Bearer {bearer}"
    )
    assert [kind for kind, _, _ in describe(text)] == [
        T.PII_EMAIL,
        T.PII_PHONE,
        T.SECRET_API_KEY,
        T.SECRET_API_KEY,
        T.PII_CARD,
        T.SECRET_TOKEN,
    ]


def test_clean_text_and_ordinary_identifiers_are_not_flagged() -> None:
    for text in [
        "What is the capital of France?",
        "createAuthenticationTokenManagerFactory",
        "tests/unit/guardrails/test_scan_module_helpers",
    ]:
        assert detect_sensitive(text) == []


@given(st.text(alphabet=ALPHABET + "-_+/=:@. \n", max_size=400))
def test_results_are_sorted_and_never_overlap(text: str) -> None:
    found = detect_sensitive(text)
    for d in found:
        assert 0 <= d.start < d.end <= len(text)
    for a, b in pairwise(found):
        assert a.end <= b.start


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "A" * 1_000_000,
        tok(9, 1_000_000),
        "gsk_" * 250_000,
        "bearer " * 140_000,
        "token=" * 160_000,
        "-----BEGIN " * 90_000,
        "eyJ-" * 250_000,
        "4 " * 500_000,
        "a@" * 500_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_sensitive(text)
        assert time.perf_counter() - start < 6.0
