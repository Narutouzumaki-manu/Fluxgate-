import pytest
from pydantic import ValidationError

from shared.config import Settings


def test_defaults_match_docs() -> None:
    s = Settings(_env_file=None)
    assert s.l2_threshold == 0.92
    assert s.cache_default_ttl_s == 86_400
    assert s.cache_max_entries_per_tenant == 50_000
    assert s.policy == "default"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLUXGATE_L2_THRESHOLD", "0.9")
    assert Settings(_env_file=None).l2_threshold == 0.9


def test_invalid_threshold_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLUXGATE_L2_THRESHOLD", "1.5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_prompt_preview_follows_profile_unless_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLUXGATE_ENV", "prod")
    assert Settings(_env_file=None).prompt_preview_default is False
    monkeypatch.setenv("FLUXGATE_STORE_PROMPT_PREVIEW", "true")
    assert Settings(_env_file=None).prompt_preview_default is True


def test_secrets_not_in_repr() -> None:
    assert "change-me-dev-only" not in repr(Settings(_env_file=None))
