"""Typed settings. Env vars use the FLUXGATE_ prefix."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLUXGATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    db_path: Path = Path("./data/fluxgate.db")
    key_pepper: SecretStr = SecretStr("change-me-dev-only")
    admin_token: SecretStr = SecretStr("change-me")

    # --- guardrails (Member 1) ---
    policy: str = "default"
    policies_dir: Path = Path("config/policies")
    guardrail_timeout_ms: int = Field(default=250, gt=0)
    offload_chars: int = Field(default=20_000, gt=0)
    store_prompt_preview: bool | None = None

    # --- cache (Member 1) ---
    cache_enabled: bool = True
    l1_max_entries: int = Field(default=2_000, gt=0)
    l1_max_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    l2_threshold: float = Field(default=0.92, gt=0, le=1)
    l2_max_temperature: float = Field(default=0.5, ge=0, le=2)
    l2_top_k: int = Field(default=5, ge=1, le=50)
    entity_guard: bool = True
    cache_default_ttl_s: int = Field(default=86_400, gt=0)
    cache_max_ttl_s: int = Field(default=604_800, gt=0)
    cache_max_entries_per_tenant: int = Field(default=50_000, gt=0)
    max_total_vectors: int = Field(default=200_000, gt=0)
    max_response_bytes: int = Field(default=262_144, gt=0)
    sweeper_interval_s: int = Field(default=60, gt=0)
    embed_model_path: Path = Path("./models/all-MiniLM-L6-v2")
    cpu_threads: int = Field(default=2, ge=1, le=64)

    @property
    def prompt_preview_default(self) -> bool:
        """D-004: preview ON in dev, OFF otherwise, unless explicitly set."""
        if self.store_prompt_preview is not None:
            return self.store_prompt_preview
        return self.env == "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
