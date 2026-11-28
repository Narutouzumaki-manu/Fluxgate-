import random
from collections import Counter
from collections.abc import Callable

import pytest

from guardrails.detection import Detection
from guardrails.scan import detect_sensitive
from guardrails.secrets.contextual import detect_assignment, detect_bearer, detect_private_key
from guardrails.secrets.entropy import detect_high_entropy
from guardrails.secrets.patterns import detect_secret_keys
from shared.contracts.enums import FindingType
from tests.unit.guardrails import pii_corpus, secrets_corpus
from tests.unit.guardrails.secrets_corpus import HEX, PROVIDER_MAKERS, provider_samples, rand

SECRET_TYPES = {
    FindingType.SECRET_API_KEY,
    FindingType.SECRET_TOKEN,
    FindingType.SECRET_PRIVATE_KEY,
    FindingType.SECRET_HIGH_ENTROPY,
}
Samples = list[tuple[str, str]]


def hit(found: list[Detection], start: int, end: int, *, rule: str | None = None) -> bool:
    """Is there a detection with exactly this span (and this rule, if given)?"""
    return any(
        d.start == start and d.end == end and (rule is None or d.rule_id == rule) for d in found
    )


def covered(found: list[Detection], start: int, end: int) -> bool:
    """Is the whole span inside some detection?"""
    return any(d.start <= start and d.end >= end for d in found)


def recall_of(samples: Samples, check: Callable[[str, int, int], bool]) -> tuple[float, list[str]]:
    missed = [t for t, v in samples if not check(t, t.index(v), len(v))]
    return 1 - len(missed) / len(samples), missed


# --- recall ----------------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", sorted(PROVIDER_MAKERS))
def test_provider_key_recall(fmt: str) -> None:
    """Target (PRD S-01, V3): at least 99%, found by the RIGHT rule and fully covered."""
    rule = PROVIDER_MAKERS[fmt][0]

    def check(text: str, pos: int, n: int) -> bool:
        return hit(detect_secret_keys(text), pos, pos + n, rule=rule) and covered(
            detect_sensitive(text), pos, pos + n
        )

    recall, missed = recall_of(provider_samples(fmt), check)
    print(f"\nrecall {fmt:<12}{recall:7.1%}  (200 samples)")
    assert recall >= 0.99, missed[:3]


def test_bearer_recall() -> None:
    def check(text: str, pos: int, n: int) -> bool:
        return hit(detect_bearer(text), pos, pos + n, rule="SEC-BEARER-001")

    recall, missed = recall_of(secrets_corpus.bearer_samples(), check)
    print(f"\nrecall {'bearer':<12}{recall:7.1%}  (300 samples)")
    assert recall >= 0.99, missed[:3]


@pytest.mark.parametrize(
    ("name", "samples"),
    [
        ("assign_random", secrets_corpus.assignment_samples()),
        ("assign_human", secrets_corpus.human_password_samples()),
    ],
)
def test_assignment_recall(name: str, samples: Samples) -> None:
    def check(text: str, pos: int, n: int) -> bool:
        return hit(detect_assignment(text), pos, pos + n, rule="SEC-ASSIGN-001")

    recall, missed = recall_of(samples, check)
    print(f"\nrecall {name:<12}{recall:7.1%}  ({len(samples)} samples)")
    assert recall >= 0.99, missed[:3]


def test_private_key_recall() -> None:
    def check(text: str, pos: int, n: int) -> bool:
        return hit(detect_private_key(text), pos, pos + n, rule="SEC-PEM-001")

    recall, missed = recall_of(secrets_corpus.pem_samples(), check)
    print(f"\nrecall {'private_key':<12}{recall:7.1%}  (100 samples)")
    assert recall >= 0.99, [m[:60] for m in missed[:3]]


def test_entropy_recall_and_the_short_token_probe() -> None:
    def check(text: str, pos: int, n: int) -> bool:
        return hit(detect_high_entropy(text), pos, pos + n)

    recall, missed = recall_of(secrets_corpus.entropy_samples(32, 64), check)
    print(f"\nrecall {'entropy 32-64':<14}{recall:7.1%}  (300 samples)")
    assert recall >= 0.99, missed[:3]
    short, _ = recall_of(secrets_corpus.entropy_samples(20, 24), check)
    print(f"recall {'entropy 20-24':<14}{short:7.1%}  (300 samples, informational, no target)")


def test_every_golden_secret_is_hidden_by_the_combined_scan() -> None:
    """The redactor hides whatever detect_sensitive reports, so measure that end to end."""
    samples: Samples = []
    for fmt in PROVIDER_MAKERS:
        samples += provider_samples(fmt, n=50)
    samples += secrets_corpus.bearer_samples(100)
    samples += secrets_corpus.assignment_samples(100)
    samples += secrets_corpus.human_password_samples(100)
    samples += secrets_corpus.pem_samples(50)
    samples += secrets_corpus.entropy_samples(32, 64, n=100)

    def check(text: str, pos: int, n: int) -> bool:
        return covered(detect_sensitive(text), pos, pos + n)

    recall, missed = recall_of(samples, check)
    print(f"\ncombined scan covers {recall:.1%} of {len(samples)} planted secrets")
    assert recall >= 0.99, [m[:60] for m in missed[:3]]


# --- false positives ---------------------------------------------------------------------------
FAMILIES: dict[str, Callable[[str], list[Detection]]] = {
    "provider_keys": detect_secret_keys,
    "bearer": detect_bearer,
    "assignment": detect_assignment,
    "private_key": detect_private_key,
    "entropy": detect_high_entropy,
}


def test_false_positive_rates() -> None:
    """Target (PRD S-02): at most 1% of benign snippets flagged, per detector."""
    secret_cats = secrets_corpus.secrets_benign_by_category()
    assert sum(len(v) for v in secret_cats.values()) >= 300
    cats = {f"pii:{k}": v for k, v in pii_corpus.benign_corpus_by_category().items()}
    cats |= {f"sec:{k}": v for k, v in secret_cats.items()}
    corpus = [(cat, s) for cat, items in cats.items() for s in items]

    print(f"\nbenign corpus: {len(corpus)} snippets in {len(cats)} categories")
    failures: list[str] = []
    for name, detect in FAMILIES.items():
        flagged = [(cat, s) for cat, s in corpus if detect(s)]
        rate = len(flagged) / len(corpus)
        print(f"false positives {name:<14}{len(flagged):4d}  {rate:7.2%}")
        for cat, count in Counter(cat for cat, _ in flagged).most_common():
            print(f"    {cat}: {count}")
        if rate > 0.01:
            examples = [s[:70] for _, s in flagged[:6]]
            failures.append(f"{name}: {rate:.2%}, e.g. {examples}")
    overall = [
        (c, s) for c, s in corpus if any(d.type in SECRET_TYPES for d in detect_sensitive(s))
    ]
    print(f"any secret rule, combined scan: {len(overall)}  {len(overall) / len(corpus):7.2%}")
    assert not failures, "; ".join(failures)


def test_known_limitations_are_pinned_by_tests() -> None:
    """Behaviours we accept and will document. If one changes, this test says so."""
    # A random lower-case-only string looks like a word, so the entropy rule skips it.
    assert detect_high_entropy("value " + "qwzxjkvbnmplrtghfdsa") == []
    # Random hex: only 16 symbols, so entropy is at most 4.0 bits and almost always below it.
    rng = random.Random(99)
    samples = [rand(rng, HEX, rng.choice([32, 40, 64])) for _ in range(200)]
    flagged = [s for s in samples if detect_high_entropy(f"value {s}")]
    print(f"\nrandom hex tokens flagged by the entropy rule: {len(flagged)} of 200")
    assert len(flagged) <= 2
