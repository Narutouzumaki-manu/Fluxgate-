"""shared.testing — test doubles, fixtures, and helpers.

Jointly owned.  Used by both Member 1 and Member 2 test suites.
Importable from tests via:  from tests.fakes import FakeGuardrailEngine, ...
Or directly:               from shared.testing.fakes import FakeGuardrailEngine

Sub-modules:
  fakes.py        — FakeGuardrailEngine, FakeCacheEngine, FakeRouter, FakeClock
  fake_clock.py   — Clock protocol + FakeClock implementation
  fixtures/       — golden request/response JSON fixtures
"""

from __future__ import annotations

__all__: list[str] = []
