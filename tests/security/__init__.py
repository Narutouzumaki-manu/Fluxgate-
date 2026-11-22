"""Security tests — canary log-leak, tenant isolation, ReDoS adversarial suite.

Owner: Member 1 (CODEOWNERS: /tests/security/).
All tests in this directory are marked @pytest.mark.security.

Phase 1 status: directory stub only.  Real tests are added in Phase 2 alongside
the guardrails and cache implementations they exercise.

Required tests (see TESTING_AND_BENCHMARK_GUIDE.md §2.1 and CI pipeline §6):

  test_no_secret_in_logs.py     — feeds canary secrets through the full engine,
                                   asserts no canary appears in caplog/exceptions/DB/WAL.
  test_tenant_isolation.py      — Hypothesis stateful test: random interleavings of
                                   store/lookup/invalidate across N tenants; a lookup
                                   for tenant A must NEVER return an entry stored by B.
  test_redos.py                 — feeds 1 MB adversarial strings to every compiled
                                   regex; asserts completion < 250 ms per pattern.
"""

from __future__ import annotations

__all__: list[str] = []
