from pathlib import Path

import pytest

from guardrails.policy import (
    build_policy,
    load_policy,
    policy_path,
    read_policy_file,
)
from shared.errors import ConfigError

POLICIES_DIR = Path(__file__).resolve().parents[3] / "config" / "policies"


def test_reads_default_policy() -> None:
    data = read_policy_file(POLICIES_DIR / "default.yaml")
    assert data["name"] == "default"
    assert data["injection_block_threshold"] == 0.85


def test_reads_strict_policy() -> None:
    data = read_policy_file(POLICIES_DIR / "strict.yaml")
    assert data["name"] == "strict"


def test_policy_path_builds_expected_file() -> None:
    assert policy_path("default", POLICIES_DIR) == POLICIES_DIR / "default.yaml"


@pytest.mark.parametrize("bad", ["../secret", "..\\secret", "a/b", "A", "", "x" * 65, "a.b"])
def test_policy_path_rejects_unsafe_names(bad: str) -> None:
    with pytest.raises(ConfigError, match="Invalid policy name"):
        policy_path(bad, POLICIES_DIR)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read"):
        read_policy_file(tmp_path / "nope.yaml")


def test_invalid_yaml_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        read_policy_file(bad)


@pytest.mark.parametrize("content", ["", "- just\n- a list\n", "42"])
def test_non_mapping_is_a_config_error(tmp_path: Path, content: str) -> None:
    f = tmp_path / "odd.yaml"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain"):
        read_policy_file(f)


def test_load_default_policy_is_checked_and_versioned() -> None:
    policy = load_policy("default", POLICIES_DIR)
    assert policy.name == "default"
    assert policy.injection_block_threshold == 0.85
    assert len(policy.version) == 16
    assert all(c in "0123456789abcdef" for c in policy.version)


def test_strict_is_stricter_and_has_a_different_version() -> None:
    default = load_policy("default", POLICIES_DIR)
    strict = load_policy("strict", POLICIES_DIR)
    assert strict.injection_block_threshold < default.injection_block_threshold
    assert strict.version != default.version


def test_version_is_stable_across_loads() -> None:
    assert (
        load_policy("default", POLICIES_DIR).version == load_policy("default", POLICIES_DIR).version
    )


def test_version_ignores_key_order() -> None:
    raw = read_policy_file(POLICIES_DIR / "default.yaml")
    shuffled = dict(reversed(list(raw.items())))
    assert build_policy(shuffled).version == build_policy(raw).version


def test_version_changes_when_policy_changes() -> None:
    raw = read_policy_file(POLICIES_DIR / "default.yaml")
    changed = {**raw, "injection_block_threshold": 0.80}
    assert build_policy(changed).version != build_policy(raw).version


def test_out_of_range_value_is_rejected() -> None:
    raw = read_policy_file(POLICIES_DIR / "default.yaml")
    with pytest.raises(ConfigError, match="injection_block_threshold"):
        build_policy({**raw, "injection_block_threshold": 1.5})


def test_unknown_key_is_rejected() -> None:
    raw = read_policy_file(POLICIES_DIR / "default.yaml")
    with pytest.raises(ConfigError, match="injection_blok_threshold"):
        build_policy({**raw, "injection_blok_threshold": 0.9})


def test_version_in_file_is_rejected() -> None:
    raw = read_policy_file(POLICIES_DIR / "default.yaml")
    with pytest.raises(ConfigError, match="computed"):
        build_policy({**raw, "version": "deadbeefdeadbeef"})


def test_error_message_does_not_echo_the_bad_value() -> None:
    with pytest.raises(ConfigError) as info:
        build_policy({"name": "x", "injection_block_threshold": "SECRET-LOOKING-VALUE"})
    assert "SECRET-LOOKING-VALUE" not in str(info.value)


def test_file_name_must_match_declared_name(tmp_path: Path) -> None:
    (tmp_path / "relaxed.yaml").write_text("name: default\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="declares name"):
        load_policy("relaxed", tmp_path)
