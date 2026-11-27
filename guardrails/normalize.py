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
_HOMOGLYPHS: dict[int, str] = {
    # Cyrillic lowercase
    0x0430: "a",
    0x0435: "e",
    0x043E: "o",
    0x0440: "p",
    0x0441: "c",
    0x0443: "y",
    0x0445: "x",
    0x0456: "i",
    0x0458: "j",
    0x0455: "s",
    0x0501: "d",
    # Cyrillic uppercase
    0x0410: "A",
    0x0412: "B",
    0x0415: "E",
    0x041A: "K",
    0x041C: "M",
    0x041D: "H",
    0x041E: "O",
    0x0420: "P",
    0x0421: "C",
    0x0422: "T",
    0x0425: "X",
    0x0423: "Y",
    0x0406: "I",
    0x0408: "J",
    0x0405: "S",
    # Greek uppercase
    0x0391: "A",
    0x0392: "B",
    0x0395: "E",
    0x0396: "Z",
    0x0397: "H",
    0x0399: "I",
    0x039A: "K",
    0x039C: "M",
    0x039D: "N",
    0x039F: "O",
    0x03A1: "P",
    0x03A4: "T",
    0x03A5: "Y",
    0x03A7: "X",
    # Greek lowercase
    0x03BF: "o",
    0x03BD: "v",
    0x03B9: "i",
    0x03C1: "p",
    0x03B1: "a",
    0x03C5: "u",
}


def _count_homoglyphs(s: str) -> int:
    return sum(1 for ch in s if ord(ch) in _HOMOGLYPHS)


@dataclass(frozen=True)
class NormalizedView:
    """Cleaned text plus a map back to the original text."""

    text: str
    starts: tuple[int, ...]  # starts[i]: where cleaned char i's source begins in the original
    ends: tuple[int, ...]  # ends[i]: where that source ends (exclusive)
    invisible_removed: int  # how many invisible characters were dropped
    homoglyphs_folded: int  # how many look-alike letters were folded

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        """Turn a span of the cleaned text into the matching span of the original."""
        if not 0 <= start < end <= len(self.text):
            raise ValueError(f"Bad span ({start}, {end}) for text of length {len(self.text)}")
        return self.starts[start], self.ends[end - 1]


def _collapse_whitespace(
    chars: list[str], starts: list[int], ends: list[int]
) -> tuple[list[str], list[int], list[int]]:
    """Turn every run of whitespace into one space, keeping the offset map correct."""
    out: list[str] = []
    out_starts: list[int] = []
    out_ends: list[int] = []
    in_run = False
    for ch, s, e in zip(chars, starts, ends, strict=True):
        if ch.isspace():
            if in_run:
                out_ends[-1] = e  # the run grows: its source now ends later
            else:
                out.append(" ")
                out_starts.append(s)
                out_ends.append(e)
                in_run = True
        else:
            out.append(ch)
            out_starts.append(s)
            out_ends.append(e)
            in_run = False
    return out, out_starts, out_ends


def normalize(text: str) -> NormalizedView:
    """Clean text for detection: drop invisible characters, fold look-alikes, apply NFKC,
    and collapse whitespace. Keeps an offset map back to the original."""
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    removed = 0
    folded = 0
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
        group = text[i:j]
        folded += _count_homoglyphs(group)
        # Fold look-alikes BEFORE NFKC so an accent can still compose with the Latin letter...
        cleaned = unicodedata.normalize("NFKC", group.translate(_HOMOGLYPHS))
        # ...and AFTER, for characters that only turn into look-alikes through NFKC.
        folded += _count_homoglyphs(cleaned)
        cleaned = cleaned.translate(_HOMOGLYPHS)
        for ch in cleaned:
            out.append(ch)
            starts.append(i)
            ends.append(j)
        i = j
    out, starts, ends = _collapse_whitespace(out, starts, ends)
    return NormalizedView("".join(out), tuple(starts), tuple(ends), removed, folded)
