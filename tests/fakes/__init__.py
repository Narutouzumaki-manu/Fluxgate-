"""tests/fakes — re-exports of shared/testing fakes for convenient test imports.

Usage::

    from tests.fakes import FakeGuardrailEngine, FakeCacheEngine, FakeRouter
    from tests.fakes import FakeClock, FakeScenario
"""

from __future__ import annotations

from shared.testing.fake_clock import Clock, FakeClock
from shared.testing.fakes import (
    FakeCacheEngine,
    FakeGuardrailEngine,
    FakeRouter,
    FakeScenario,
)

__all__ = [
    "Clock",
    "FakeCacheEngine",
    "FakeClock",
    "FakeGuardrailEngine",
    "FakeRouter",
    "FakeScenario",
]
