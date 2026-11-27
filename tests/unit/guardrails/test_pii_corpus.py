import pytest

from guardrails.pii.detectors import detect_pii
from shared.contracts.enums import FindingType
from tests.unit.guardrails.pii_corpus import benign_corpus_by_category, golden_samples

KINDS = [
    FindingType.PII_EMAIL,
    FindingType.PII_PHONE,
    FindingType.PII_AADHAAR,
    FindingType.PII_PAN,
    FindingType.PII_CARD,
]


@pytest.mark.parametrize("kind", KINDS)
def test_golden_recall(kind: FindingType) -> None:
    """Target (PRD S-01): at least 99% of planted values are found, as the right type."""
    samples = golden_samples(kind)
    missed: list[str] = []
    for text, value in samples:
        pos = text.index(value)
        found = detect_pii(text)
        if not any(d.type == kind and d.start <= pos and d.end >= pos + len(value) for d in found):
            missed.append(text)
    recall = 1 - len(missed) / len(samples)
    print(f"\nrecall {kind.value:<14}{recall:7.1%}  ({len(samples)} samples)")
    assert recall >= 0.99, f"{kind.value}: recall {recall:.1%}, missed e.g. {missed[:5]}"


def test_false_positive_rates() -> None:
    """Target (PRD S-02): at most 1% of benign snippets flagged, per detector."""
    by_category = benign_corpus_by_category()
    corpus = [snippet for items in by_category.values() for snippet in items]
    assert len(corpus) >= 500

    print(f"\nbenign corpus: {len(corpus)} snippets in {len(by_category)} categories")
    failures: list[str] = []
    for kind in KINDS:
        flagged = [s for s in corpus if any(d.type == kind for d in detect_pii(s))]
        rate = len(flagged) / len(corpus)
        print(f"false positives {kind.value:<14}{len(flagged):4d}  {rate:7.2%}")
        if rate > 0.01:
            failures.append(f"{kind.value}: {rate:.2%}, e.g. {flagged[:5]}")
    assert not failures, "; ".join(failures)


def test_known_limitations_are_pinned_by_tests() -> None:
    """Behaviours we accept and will document. If one changes, this test says so."""
    # A bare 10-digit number starting 6-9, with no context word, is flagged as a phone.
    assert any(d.type == FindingType.PII_PHONE for d in detect_pii("my number 9876543210"))
    # SSH-style addresses look like emails.
    assert any(d.type == FindingType.PII_EMAIL for d in detect_pii("git@github.com"))
