"""One scan for everything sensitive: PII and secrets (M1-3 step 4)."""

from __future__ import annotations

from guardrails.detection import Detection, resolve_overlaps
from guardrails.pii.detectors import (
    detect_aadhaar,
    detect_card,
    detect_email,
    detect_pan,
    detect_phone,
)
from guardrails.secrets.contextual import detect_assignment, detect_bearer, detect_private_key
from guardrails.secrets.entropy import detect_high_entropy
from guardrails.secrets.patterns import detect_secret_keys


def detect_sensitive(text: str) -> list[Detection]:
    """Run every PII and secret detector and return non-overlapping detections, in text order.

    All detectors run first and their results are resolved together, once, so the answer
    never depends on the order the detectors ran in.
    """
    return resolve_overlaps(
        [
            *detect_email(text),
            *detect_phone(text),
            *detect_aadhaar(text),
            *detect_pan(text),
            *detect_card(text),
            *detect_secret_keys(text),
            *detect_bearer(text),
            *detect_assignment(text),
            *detect_private_key(text),
            *detect_high_entropy(text),
        ]
    )
