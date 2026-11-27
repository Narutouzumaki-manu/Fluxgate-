"""The record every detector returns (shared by pii/ and secrets/)."""

from __future__ import annotations

from dataclasses import dataclass

from shared.contracts.enums import FindingType


@dataclass(frozen=True)
class Detection:
    """One detected item. Never stores the matched value itself, only where it is."""

    type: FindingType
    rule_id: str
    start: int
    end: int
    confidence: float
