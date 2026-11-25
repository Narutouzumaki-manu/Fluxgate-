"""Guardrail policy loading (M1-0).

Step 1: find a policy file by name and read it safely into a dictionary.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import orjson
import yaml
from pydantic import ValidationError

from shared.contracts.guardrails import GuardrailPolicy
from shared.errors import ConfigError

# Policy names come from config and, later, from request bodies.
# Only allow plain names so nobody can point us at a file outside the policy folder.
_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def policy_path(name: str, policies_dir: Path) -> Path:
    """Turn a policy name like 'default' into config/policies/default.yaml."""
    if _NAME_RE.fullmatch(name) is None:
        raise ConfigError(f"Invalid policy name: {name!r}")
    return policies_dir / f"{name}.yaml"


def read_policy_file(path: Path) -> dict[str, Any]:
    """Read one policy YAML file into a dictionary. Raises ConfigError on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read policy file {path.name}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Policy file {path.name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Policy file {path.name} must contain key: value rules")
    return data


def compute_policy_version(policy: GuardrailPolicy) -> str:
    """Fingerprint of the policy's content (first 16 hex chars of SHA-256).

    Hashes the CHECKED policy with sorted keys, so comments, blank lines and key order
    in the YAML file never change it. The version field itself is excluded.
    """
    body = policy.model_dump(mode="json", exclude={"version"})
    canonical = orjson.dumps(body, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(canonical).hexdigest()[:16]


def build_policy(raw: dict[str, Any]) -> GuardrailPolicy:
    """Check a raw dictionary against GuardrailPolicy and stamp it with its version."""
    if "version" in raw:
        raise ConfigError("A policy file must not set 'version'; it is computed")
    try:
        draft = GuardrailPolicy.model_validate({**raw, "version": "pending"})
    except ValidationError as exc:
        # Report WHERE and WHAT is wrong, never the offending input value.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"Invalid policy: {problems}") from exc
    return draft.model_copy(update={"version": compute_policy_version(draft)})


def load_policy(name: str, policies_dir: Path) -> GuardrailPolicy:
    """Find, read, check and version one policy by name. The engine will call this."""
    path = policy_path(name, policies_dir)
    policy = build_policy(read_policy_file(path))
    if policy.name != name:
        raise ConfigError(f"Policy file {path.name} declares name{policy.name!r},expected {name!r}")
    return policy
