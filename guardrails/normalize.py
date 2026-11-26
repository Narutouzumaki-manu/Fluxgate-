"""Text normalization (M1-1).

Detection runs on a cleaned VIEW of the text. The original text is never changed and is
what gets forwarded. The view keeps an offset map so a span found in the view can be
cut out of the original.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Zero-width and bidi control characters (TRD A1 step 2, plus the bidi isolates).
_INVISIBLE: frozenset[int] = frozenset(
    [
        *range(0x200B, 0x2010),  # zero-width space/joiners, LRM, RLM
        *range(0x202A, 0x202F),  # bidi embeddings and overrides
        *range(0x2060, 0x2065),  # word joiner and invisible operators
        *range(0x2066, 0x206A),  # bidi isolates
        0xFEFF,  # zero-width no-break space / BOM
    ]
)


@dataclass(frozen=True)
class NormalizedView:
    """Cleaned text plus a map back to the original text."""

    text: str
    starts: tuple[int, ...]  # starts[i]: where cleaned char i's source begins in the original
    ends: tuple[int, ...]  # ends[i]: where that source ends (exclusive)
    invisible_removed: int  # how many invisible characters were dropped

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """Turn a span of the cleaned text into the matching span of the original."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError(f"Bad span ({start}, {end}) for text of length {len(self.text)}")
        return self.starts[start], self.ends[end - 1]


def normalize(text: str) -> NormalizedView:
    """Drop invisible characters and apply Unicode NFKC, keeping the offset map."""
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    removed = 0
    i = 0
    n = len(text)
    while i < n:
        if ord(text[i]) in _INVISIBLE:
            removed += 1
            i += 1
            continue
        # A base character plus any combining marks that follow it fold together.
        j = i + 1
        while j < n and unicodedata.combining(text[j]) and ord(text[j]) not in _INVISIBLE:
            j += 1
        for ch in unicodedata.normalize("NFKC", text[i:j]):
            out.append(ch)
            starts.append(i)
            ends.append(j)
        i = j
    return NormalizedView("".join(out), tuple(starts), tuple(ends), removed)
