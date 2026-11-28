"""Secret detectors for keys with a recognisable prefix (M1-3 step 1).

Each rule finds one kind of key. Detectors only FIND; M1-4 hides. Spans refer to the
string that was scanned. All repeats are bounded, and every rule refuses to start in the
middle of a longer run of key characters (ReDoS rule).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from guardrails.detection import Detection
from shared.contracts.enums import FindingType

_START = r"(?<![A-Za-z0-9_])"  # never start in the middle of a word
_START_B64 = r"(?<![A-Za-z0-9_-])"  # same, also refusing to start right after '-'


@dataclass(frozen=True)
class SecretRule:
    rule_id: str
    type: FindingType
    pattern: re.Pattern[str]
    require_digit: bool = False  # real keys are random, so a digit-free match is a plain word


SECRET_RULES: tuple[SecretRule, ...] = (
    SecretRule(
        "SEC-FGX-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"fgx-[A-Za-z0-9_-]{20,4096}"),
    ),
    SecretRule(
        "SEC-GROQ-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"gsk_[A-Za-z0-9]{20,4096}"),
    ),
    SecretRule(
        "SEC-OPENROUTER-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"sk-or-v1-[A-Za-z0-9]{20,4096}"),
    ),
    SecretRule(
        "SEC-NVIDIA-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"nvapi-[A-Za-z0-9_-]{20,4096}"),
    ),
    SecretRule(
        "SEC-ANTHROPIC-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"sk-ant-[A-Za-z0-9_-]{20,4096}"),
    ),
    SecretRule(
        "SEC-OPENAI-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"sk-(?!or-|ant-)[A-Za-z0-9_-]{20,4096}"),
        require_digit=True,
    ),
    SecretRule(
        "SEC-AWS-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),
    ),
    SecretRule(
        "SEC-GOOGLE-001",
        FindingType.SECRET_API_KEY,
        re.compile(_START + r"AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"),
    ),
    SecretRule(
        "SEC-GITHUB-001",
        FindingType.SECRET_TOKEN,
        re.compile(_START + r"gh[pousr]_[A-Za-z0-9]{36,255}"),
    ),
    SecretRule(
        "SEC-SLACK-001",
        FindingType.SECRET_TOKEN,
        re.compile(_START + r"xox[baprs]-[A-Za-z0-9-]{10,4096}"),
    ),
    SecretRule(
        "SEC-JWT-001",
        FindingType.SECRET_TOKEN,
        re.compile(
            _START_B64
            + r"eyJ[A-Za-z0-9_-]{8,4096}\.eyJ[A-Za-z0-9_-]{8,4096}\.[A-Za-z0-9_-]{8,4096}"
        ),
    ),
)

_HAS_DIGIT = re.compile(r"[0-9]")


def detect_secret_keys(text: str) -> list[Detection]:
    """Find keys and tokens that have a recognisable provider format."""
    found: list[Detection] = []
    for rule in SECRET_RULES:
        for m in rule.pattern.finditer(text):
            if rule.require_digit and _HAS_DIGIT.search(m.group()) is None:
                continue
            found.append(Detection(rule.type, rule.rule_id, m.start(), m.end(), 0.95))
    return sorted(found, key=lambda d: (d.start, d.end))
