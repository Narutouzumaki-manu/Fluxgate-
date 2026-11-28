import re
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.secrets.contextual import (
    MAX_PEM_CHARS,
    detect_assignment,
    detect_bearer,
    detect_private_key,
)
from shared.contracts.enums import FindingType

API, TOKEN, PEM = (
    FindingType.SECRET_API_KEY,
    FindingType.SECRET_TOKEN,
    FindingType.SECRET_PRIVATE_KEY,
)

# Made-up values, built from pieces so the file holds no complete secret-looking string.
VALUE = "".join(["Zq4Mw7Hx", "P2kL9sVd", "R6tY1cNb"])  # 24 characters
TOKEN32 = "".join(["Zq4Mw7Hx", "P2kL9sVd", "R6tY1cNb", "A8fG3jQe"])

# Built from pieces so the secret scanners never see a whole private-key header.
DASHES = "-" * 5
KEY_WORDS = " ".join(["PRIVATE", "KEY"])
BEGIN_HEADER = f"{DASHES}BEGIN {KEY_WORDS}{DASHES}"
END_HEADER = f"{DASHES}END {KEY_WORDS}{DASHES}"


def seen(text: str, found: list) -> list[str]:  # type: ignore[type-arg]
    return [text[d.start : d.end] for d in found]


# --- Bearer --------------------------------------------------------------------------------
@pytest.mark.parametrize("word", ["Bearer", "bearer", "BEARER"])
def test_bearer_token_is_found_without_the_word_bearer(word: str) -> None:
    text = f"Authorization: {word} {TOKEN32}"
    found = detect_bearer(text)
    assert seen(text, found) == [TOKEN32]
    assert found[0].type == TOKEN
    assert found[0].rule_id == "SEC-BEARER-001"
    assert found[0].confidence == 0.9


def test_bearer_jwt_shaped_token_is_found() -> None:
    jwt = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJlMTIz"])
    text = f"Authorization: Bearer {jwt}"
    assert seen(text, detect_bearer(text)) == [jwt]


def test_trailing_full_stop_is_not_part_of_the_token() -> None:
    text = f"send Bearer {TOKEN32}. Then wait."
    assert seen(text, detect_bearer(text)) == [TOKEN32]


@pytest.mark.parametrize(
    "text",
    [
        "Bearer " + "A1b2C3d4" * 1,  # too short
        "Bearer " + "A1b2C3d4E5f6G7h",  # 15 characters
        "Use Bearer authentication-based-approach for the API",  # words, not a token
        "bearer token_based_access_control is common",
        "Bearer <your-token-goes-here>",
        "Bearer ${ACCESS_TOKEN_VALUE_HERE}",
        "Bearer [REDACTED]",
        "xBearer " + "Zq4Mw7HxP2kL9sVd",  # glued to a letter
        "A bearer of bad news arrived",
    ],
)
def test_bearer_non_tokens_are_ignored(text: str) -> None:
    assert detect_bearer(text) == []


def test_exactly_sixteen_characters_is_found_but_not_if_the_full_stop_makes_it_fifteen() -> None:
    sixteen = "Zq4Mw7HxP2kL9sVd"
    assert seen(f"Bearer {sixteen}", detect_bearer(f"Bearer {sixteen}")) == [sixteen]
    assert detect_bearer(f"Bearer {sixteen[:15]}.") == []


# --- Assignments ----------------------------------------------------------------------------
FORMS = [
    ("api_key", "{n}={v}"),
    ("api-key", "{n}: {v}"),
    ("API_KEY", '{n} = "{v}"'),
    ("GROQ_API_KEY", "{n}={v}"),
    ("apiKey", '"{n}": "{v}"'),
    ("password", "{n}: {v}"),
    ("client_secret", "{n}='{v}'"),
    ("authToken", "{n}: {v}"),
    ("pwd", "{n}={v}"),
    ("passwd", "{n}={v}"),
    ("SECRET", "{n}={v}"),
    ("access_token", "{n}={v}"),
]


@pytest.mark.parametrize(("name", "form"), FORMS)
def test_assignment_value_is_found_and_the_name_is_left_alone(name: str, form: str) -> None:
    text = "config: " + form.format(n=name, v=VALUE) + " # end"
    found = detect_assignment(text)
    assert seen(text, found) == [VALUE]
    assert found[0].type == (API if re.search("api", name, re.IGNORECASE) else TOKEN)
    assert found[0].rule_id == "SEC-ASSIGN-001"
    assert found[0].confidence == 0.8


def test_json_line_with_a_trailing_comma() -> None:
    text = '{"token": "' + VALUE + '", "id": 7}'
    assert seen(text, detect_assignment(text)) == [VALUE]


def test_trailing_punctuation_is_not_part_of_the_value() -> None:
    text = f"the password={VALUE}."
    assert seen(text, detect_assignment(text)) == [VALUE]


def test_env_file_style_text() -> None:
    other = VALUE[::-1]
    text = f"GROQ_API_KEY={VALUE}\nNVIDIA_API_KEY={other}\nDEBUG=true\n"
    assert seen(text, detect_assignment(text)) == [VALUE, other]


@pytest.mark.parametrize(
    "text",
    [
        "password=short",
        "password=abcdefg.",  # 7 characters once the full stop is removed
        "max_tokens: 4096",
        "tokenizer: bert-base-uncased-model",
        "token_budget = 1000000000",
        "reset your password by email today",
        "password reset instructions follow",
        "api_key:\n" + VALUE,  # value on the next line
        "my secrets: " + VALUE,  # name is 'secrets', not 'secret'
    ],
)
def test_non_assignments_are_ignored(text: str) -> None:
    assert detect_assignment(text) == []


@pytest.mark.parametrize(
    "placeholder",
    [
        "YOUR_API_KEY",
        "your-api-key-here",
        "changeme",
        "REPLACE_ME",
        "********",
        "xxxxxxxx",
        "<your-key-here>",
        "${GROQ_API_KEY}",
        "$GROQ_API_KEY",
        "%(password)s",
        "[[FG:SECRET:1:ab12]]",
        "[REDACTED]",
        "required",
        "optional",
        "undefined",
        "None",
        "os.getenv(",
        "self.api_key",
        "settings.token",
        "request.headers.get(",
        "os.environ[",
    ],
)
def test_placeholders_and_code_are_ignored(placeholder: str) -> None:
    for name in ("api_key", "password", "token"):
        assert detect_assignment(f"{name}={placeholder}") == []
        assert detect_assignment(f'{name}: "{placeholder}"') == []


def test_exactly_eight_characters_is_found() -> None:
    value = "Zq4Mw7Hx"
    assert seen(f"pwd={value}", detect_assignment(f"pwd={value}")) == [value]


# --- Private keys ----------------------------------------------------------------------------
BODY = "\n".join(["Zq4Mw7HxP2kL9sVdR6tY1cNbA8fG3jQe" * 2] * 4)


def pem(kind: str, body: str = BODY, *, end: bool = True) -> str:
    block = f"{DASHES}BEGIN {kind}{DASHES}\n{body}\n"
    return block + (f"{DASHES}END {kind}{DASHES}" if end else "")


@pytest.mark.parametrize(
    "kind",
    [
        "RSA PRIVATE KEY",
        "PRIVATE KEY",
        "EC PRIVATE KEY",
        "OPENSSH PRIVATE KEY",
        "ENCRYPTED PRIVATE KEY",
        "PGP PRIVATE KEY BLOCK",
    ],
)
def test_private_key_block_is_found_whole(kind: str) -> None:
    block = pem(kind)
    text = f"here is my key:\n{block}\nthanks"
    found = detect_private_key(text)
    assert seen(text, found) == [block]
    assert found[0].type == PEM
    assert found[0].rule_id == "SEC-PEM-001"
    assert found[0].confidence == 1.0


def test_two_blocks_give_two_detections() -> None:
    one, two = pem("RSA PRIVATE KEY"), pem("EC PRIVATE KEY")
    text = f"{one}\nand\n{two}"
    assert seen(text, detect_private_key(text)) == [one, two]


def test_block_without_an_end_line_runs_to_the_end_of_the_text() -> None:
    block = pem("RSA PRIVATE KEY", end=False)
    text = f"before {block}"
    assert seen(text, detect_private_key(text)) == [block]


def test_block_without_an_end_line_is_capped() -> None:
    huge = pem("PRIVATE KEY", body="A" * (MAX_PEM_CHARS * 3), end=False)
    (found,) = detect_private_key(huge)
    assert found.end - found.start <= len(BEGIN_HEADER) + MAX_PEM_CHARS


def test_public_keys_are_not_flagged() -> None:
    assert detect_private_key(pem("PUBLIC KEY")) == []
    assert detect_private_key(pem("CERTIFICATE")) == []


def test_text_that_only_mentions_the_words_is_not_flagged() -> None:
    assert detect_private_key("a private key is a secret number") == []


# --- Safety --------------------------------------------------------------------------------------
@given(st.text(max_size=300))
def test_detections_are_always_well_formed(text: str) -> None:
    for d in detect_bearer(text) + detect_assignment(text) + detect_private_key(text):
        assert 0 <= d.start < d.end <= len(text)
        assert 0 < d.confidence <= 1


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "bearer " * 140_000,
        "Bearer " + "A" * 1_000_000,
        "password" * 125_000,
        "token=" * 160_000,
        "secret:" * 140_000,
        "api_key" + " " * 1_000_000,
        "=" * 1_000_000,
        "pwd='" * 200_000,
        BEGIN_HEADER * 37_000,
        "-----BEGIN " * 90_000,
        END_HEADER * 40_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_bearer(text)
        detect_assignment(text)
        detect_private_key(text)
        assert time.perf_counter() - start < 3.0
