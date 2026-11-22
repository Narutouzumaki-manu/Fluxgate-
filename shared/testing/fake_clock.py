"""Clock protocol and FakeClock for deterministic time in tests.

Usage::

    from shared.testing.fake_clock import FakeClock

    clock = FakeClock(start_ms=1_700_000_000_000)
    clock.advance(seconds=5)
    assert clock.now_ms() == 1_700_000_005_000

FakeClock is compatible with any code that accepts a ``Clock`` protocol object.
Inject it via shared/config.py or pass it directly to cache/guardrail constructors.
"""

from __future__ import annotations

import time


class Clock:
    """Production clock — returns real wall-clock time in milliseconds."""

    def now_ms(self) -> int:
        """Unix epoch in milliseconds (UTC wall clock)."""
        return int(time.time() * 1000)

    def monotonic_ms(self) -> float:
        """Monotonic clock in milliseconds (for rate-limiter, timeouts)."""
        return time.monotonic() * 1000


class FakeClock:
    """Deterministic clock for unit/property tests.

    All time methods are synchronous; advance() is called explicitly.
    Never use real time in unit tests — always inject FakeClock (rule 2 in
    TESTING_AND_BENCHMARK_GUIDE.md §1).
    """

    def __init__(self, start_ms: int = 1_700_000_000_000) -> None:
        self._wall_ms = start_ms
        self._mono_ms: float = 0.0

    # --- wall clock (epoch ms) ---

    def now_ms(self) -> int:
        return self._wall_ms

    # --- monotonic clock (ms) ---

    def monotonic_ms(self) -> float:
        return self._mono_ms

    # --- control API (test use only) ---

    def advance(self, *, seconds: float = 0, ms: int = 0) -> None:
        """Advance both wall and monotonic clock by the given duration."""
        delta_ms = int(seconds * 1000) + ms
        self._wall_ms += delta_ms
        self._mono_ms += delta_ms

    def set(self, *, wall_ms: int) -> None:
        """Hard-set the wall clock (use sparingly; advance() is preferred)."""
        self._wall_ms = wall_ms
