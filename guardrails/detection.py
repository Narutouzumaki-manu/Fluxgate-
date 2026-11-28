"""The record every detector returns, and how overlapping detections are resolved."""

from __future__ import annotations

from dataclasses import dataclass, replace

from shared.contracts.enums import FindingType


@dataclass(frozen=True)
class Detection:
    """One detected item. Never stores the matched value itself, only where it is."""

    type: FindingType
    rule_id: str
    start: int
    end: int
    confidence: float


# Higher number wins when two detections have the same range or partly overlap (TRD A4.2).
_PRIORITY: dict[FindingType, int] = {
    FindingType.SECRET_PRIVATE_KEY: 9,
    FindingType.SECRET_API_KEY: 8,
    FindingType.SECRET_TOKEN: 8,
    FindingType.PII_CARD: 5,
    FindingType.PII_AADHAAR: 4,
    FindingType.PII_PAN: 3,
    FindingType.PII_PHONE: 2,
    FindingType.PII_EMAIL: 1,
    FindingType.SECRET_HIGH_ENTROPY: 0,  # a guess, so it always loses to a specific rule
}


def _rank(d: Detection) -> int:
    return _PRIORITY.get(d.type, 0)


def resolve_overlaps(detections: list[Detection]) -> list[Detection]:
    """Make the detections non-overlapping, sorted, and independent of input order.

    - A span inside a bigger span is dropped (the bigger one already covers it).
    - Identical ranges: the higher-priority type wins.
    - Partial overlaps are merged into one span covering both, with the higher-priority type.
    No text that was flagged ever becomes uncovered.
    """
    ordered = sorted(
        detections,
        key=lambda d: (d.start, -(d.end - d.start), -_rank(d), -d.confidence, d.rule_id),
    )
    merged: list[Detection] = []
    for d in ordered:
        if not merged or d.start >= merged[-1].end:
            merged.append(d)
            continue
        prev = merged[-1]
        if d.end <= prev.end:  # contained in (or identical to) the earlier, bigger span
            continue
        winner = d if _rank(d) > _rank(prev) else prev
        merged[-1] = replace(winner, start=prev.start, end=d.end)
    return merged
