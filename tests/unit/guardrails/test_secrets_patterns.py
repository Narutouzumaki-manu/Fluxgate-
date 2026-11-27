import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from guardrails.secrets.patterns import SECRET_RULES, detect_secret_keys
from shared.contracts.enums import FindingType

API, TOKEN = FindingType.SECRET_API_KEY, FindingType.SECRET_TOKEN

# name -> (fake key, finding type, rule id). Built from pieces so the file holds no full key.
CANARIES: dict[str, tuple[str, FindingType, str]] = {
    "fgx": ("fgx-" + "E" * 30, API, "SEC-FGX-001"),
    "groq": ("gsk_" + "B" * 24, API, "SEC-GROQ-001"),
    "openrouter": ("sk-or-v1-" + "C" * 24, API, "SEC-OPENROUTER-001"),
    "nvidia": ("nvapi-" + "D" * 24, API, "SEC-NVIDIA-001"),
    "anthropic": ("sk-ant-" + "api03-" + "F1" * 20, API, "SEC-ANTHROPIC-001"),
    "openai": ("sk-" + "abcd1234" * 6, API, "SEC-OPENAI-001"),
    "openai_proj": ("sk-proj-" + "Ab1" * 10, API, "SEC-OPENAI-001"),
    "aws": ("AKIA" + "IOSFODNN7EXAMPLE", API, "SEC-AWS-001"),
    "aws_temp": ("ASIA" + "IOSFODNN7EXAMPLE", API, "SEC-AWS-001"),
    "google": ("AIza" + "G" * 35, API, "SEC-GOOGLE-001"),
    "github": ("ghp_" + "A" * 36, TOKEN, "SEC-GITHUB-001"),
    "slack": ("xoxb-" + "1" * 12 + "-" + "h" * 12, TOKEN, "SEC-SLACK-001"),
    "jwt": (
        ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJlMTIzNDU2"]),
        TOKEN,
        "SEC-JWT-001",
    ),
}
ALL = list(CANARIES.items())


@pytest.mark.parametrize(("name", "canary"), ALL)
def test_each_key_format_is_found_exactly(name: str, canary: tuple[str, FindingType, str]) -> None:
    value, kind, rule_id = canary
    for text in (value, f'token="{value}" ok', f"export KEY={value}.", f"({value})"):
        found = detect_secret_keys(text)
        assert [text[d.start : d.end] for d in found] == [value], name
        assert found[0].type == kind
        assert found[0].rule_id == rule_id
        assert found[0].confidence == 0.95


@pytest.mark.parametrize(("name", "canary"), ALL)
def test_key_glued_to_a_letter_is_ignored(name: str, canary: tuple[str, FindingType, str]) -> None:
    assert detect_secret_keys("x" + canary[0]) == []


def test_every_rule_has_a_canary_test() -> None:
    assert {rule.rule_id for rule in SECRET_RULES} == {rid for _, _, rid in CANARIES.values()}


@pytest.mark.parametrize(
    "short",
    [
        "gsk_" + "B" * 19,
        "fgx-" + "E" * 19,
        "nvapi-" + "D" * 19,
        "sk-or-v1-" + "C" * 19,
        "AKIA" + "X" * 15,
        "AKIA" + "X" * 17,  # too long for an AWS key id
        "AIza" + "G" * 34,
        "AIza" + "G" * 36,  # runs on past a Google key's length
        "ghp_" + "A" * 35,
        "xoxb-" + "1" * 9,
        "eyJ" + "a" * 7 + "." + "eyJ" + "a" * 8 + "." + "a" * 8,
        "sk-" + "a1" * 5,
    ],
)
def test_too_short_or_wrong_length_is_ignored(short: str) -> None:
    assert detect_secret_keys(short) == []


@pytest.mark.parametrize(
    "benign",
    [
        "sk-learn-something-very-long-name",
        "sk-" + "abcdefghij" * 3,  # no digit at all
        "task-management-system-for-teams",
        "risk-assessment-framework-document",
        "ask-me-about-everything-today",
        "What is the capital of France?",
        "version 1.2.3 released",
        "git clone https://github.com/example/repo.git",
    ],
)
def test_ordinary_text_is_not_flagged(benign: str) -> None:
    assert detect_secret_keys(benign) == []


def test_specific_rule_wins_over_the_generic_openai_rule() -> None:
    for name in ("openrouter", "anthropic"):
        value, _, rule_id = CANARIES[name]
        found = detect_secret_keys(value)
        assert [d.rule_id for d in found] == [rule_id]


def test_several_secrets_in_one_message_come_back_in_text_order() -> None:
    groq, aws, jwt = CANARIES["groq"][0], CANARIES["aws"][0], CANARIES["jwt"][0]
    text = f"a {groq} b {aws} c {jwt} d"
    found = detect_secret_keys(text)
    assert [text[d.start : d.end] for d in found] == [groq, aws, jwt]


def test_env_file_style_text() -> None:
    groq, nvidia = CANARIES["groq"][0], CANARIES["nvidia"][0]
    text = f"GROQ_API_KEY={groq}\nNVIDIA_API_KEY={nvidia}\n"
    assert [text[d.start : d.end] for d in detect_secret_keys(text)] == [groq, nvidia]


@given(st.text(max_size=300))
def test_detections_are_always_well_formed(text: str) -> None:
    for d in detect_secret_keys(text):
        assert 0 <= d.start < d.end <= len(text)
        assert 0 < d.confidence <= 1


def test_adversarial_inputs_finish_quickly() -> None:
    nasty = [
        "A" * 1_000_000,
        "sk-" * 333_333,
        "gsk_" * 250_000,
        "fgx-" * 250_000,
        "nvapi-" * 160_000,
        "AKIA" * 250_000,
        "AIza" * 250_000,
        "ghp_" * 250_000,
        "xoxb-" * 200_000,
        "eyJ-" * 250_000,
        "eyJaaaaaaaa." * 80_000,
        "eyJaaaaaaaa.eyJaaaaaaaa." * 40_000,
    ]
    for text in nasty:
        start = time.perf_counter()
        detect_secret_keys(text)
        assert time.perf_counter() - start < 2.0
