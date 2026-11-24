"""Contract schema snapshot test.

Saves the baseline JSON schema for every contract model at CONTRACT_VERSION="1.0.0"
and asserts that subsequent runs produce identical schemas (CI fails on diff unless
the snapshot was updated in a `contract-change` PR).

Snapshots are written to tests/contract/snapshots/<ModelName>.json.
They are committed to the repository and treated as the source of truth.

TESTING_AND_BENCHMARK_GUIDE.md §4, Blueprint §11.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import all contract models
# ---------------------------------------------------------------------------
from shared.contracts import CONTRACT_VERSION
from shared.contracts.cache import CacheKeys, CacheResult, CacheStoreRequest, StoreDecision
from shared.contracts.context import RequestContext, TenantContext
from shared.contracts.enums import (
    CacheBypassReason,
    CacheOutcome,
    CircuitState,
    ContentSource,
    Decision,
    FindingType,
    GuardrailStage,
    ProviderName,
    RedactionAction,
    RouteFailureKind,
    Severity,
)
from shared.contracts.gateway import ErrorInfo, GatewayResponse, StageTimings
from shared.contracts.guardrails import (
    Finding,
    GuardrailPolicy,
    GuardrailResult,
    ResponseScanResult,
    TypePolicy,
)
from shared.contracts.openai_models import (
    ChatCompletionChunk,
    ChatCompletionChunkDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
    FluxGateOptions,
    RetrievedChunk,
)
from shared.contracts.router import ProviderHealth, RouteAttempt, RouterRequest, RouterResult
from shared.contracts.telemetry import RequestTrace, SecurityAuditEvent

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# All Pydantic models we snapshot — ordered for stable diff readability.
CONTRACT_MODELS: list[Any] = [
    # enums are StrEnum; we snapshot them as sorted value lists
    Decision,
    Severity,
    ContentSource,
    FindingType,
    RedactionAction,
    GuardrailStage,
    CacheOutcome,
    CacheBypassReason,
    ProviderName,
    CircuitState,
    RouteFailureKind,
    # Pydantic models
    ChatMessage,
    RetrievedChunk,
    FluxGateOptions,
    ChatCompletionRequest,
    ChatCompletionUsage,
    ChatCompletionResponse,
    ChatCompletionChunkDelta,
    ChatCompletionChunk,
    TenantContext,
    RequestContext,
    Finding,
    TypePolicy,
    GuardrailPolicy,
    GuardrailResult,
    ResponseScanResult,
    CacheKeys,
    CacheResult,
    CacheStoreRequest,
    StoreDecision,
    RouteAttempt,
    ProviderHealth,
    RouterRequest,
    RouterResult,
    StageTimings,
    ErrorInfo,
    GatewayResponse,
    RequestTrace,
    SecurityAuditEvent,
]


def _schema_for(model: Any) -> dict[str, Any]:
    """Return a comparable schema dict for a model (Pydantic) or StrEnum."""
    from enum import EnumMeta

    if isinstance(model, EnumMeta):
        return {"__type": "StrEnum", "values": sorted(m.value for m in model)}  # type: ignore[var-annotated]
    # Pydantic BaseModel
    return model.model_json_schema()  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def snapshot_dir() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOT_DIR


def test_contract_version() -> None:
    """CONTRACT_VERSION must be 1.1.0 at Gate 1."""
    assert CONTRACT_VERSION == "1.1.0", (
        f"CONTRACT_VERSION is {CONTRACT_VERSION!r}; expected '1.1.0'.\n"
        "If you intentionally bumped the version, update this assertion "
        "and open a contract-change PR."
    )


@pytest.mark.parametrize("model", CONTRACT_MODELS, ids=lambda m: m.__name__)
def test_schema_snapshot(model: Any, snapshot_dir: Path) -> None:
    """Schema must match the committed snapshot; create snapshot on first run."""
    snap_file = snapshot_dir / f"{model.__name__}.json"
    current = _schema_for(model)
    current_text = json.dumps(current, indent=2, sort_keys=True)

    if not snap_file.exists():
        # First run — write the baseline snapshot.
        snap_file.write_text(current_text, encoding="utf-8")
        pytest.skip(f"Baseline snapshot created for {model.__name__} — commit it to the repo.")

    expected_text = snap_file.read_text(encoding="utf-8")
    expected = json.loads(expected_text)

    assert current == expected, (
        f"Schema for {model.__name__} differs from snapshot.\n"
        f"If this is intentional:\n"
        f"  1. Update {snap_file} with the new schema.\n"
        f"  2. Open a PR labelled 'contract-change'.\n"
        f"  3. Bump CONTRACT_VERSION in shared/contracts/__init__.py.\n"
        f"Diff (first 500 chars):\n" + _diff_summary(expected_text, current_text)[:500]
    )


def _diff_summary(expected: str, current: str) -> str:
    import difflib

    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            current.splitlines(),
            fromfile="snapshot",
            tofile="current",
            lineterm="",
        )
    )
