.PHONY: lint lint-fix typecheck arch test test-m1 test-m2 test-contract \
        test-security test-cov perf verify-m1 bench \
        db-migrate db-backup db-vacuum clean

# ---------------------------------------------------------------------------
# Tooling shortcuts — commands run inside the uv-managed venv.
# Activate: source .venv/bin/activate  (Windows: .venv\Scripts\activate)
# ---------------------------------------------------------------------------
PYTHON  ?= python
UV      ?= uv run
PYTEST  ?= $(UV) pytest

# ---------------------------------------------------------------------------
# Lint + format
# ---------------------------------------------------------------------------
lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

lint-fix:
	$(UV) ruff check --fix .
	$(UV) ruff format .

# ---------------------------------------------------------------------------
# Type check (strict on shared/, guardrails/, cache/)
# ---------------------------------------------------------------------------
typecheck:
	$(UV) mypy shared tests

# ---------------------------------------------------------------------------
# Import-boundary enforcement (Blueprint §5)
# ---------------------------------------------------------------------------
arch:
	$(UV) lint-imports

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
# Default: fast tests only (excludes slow, perf, live)
test:
	$(PYTEST) -q -m "not slow and not perf and not live"

# Member 1 suite
test-m1:
	$(PYTEST) -q tests/unit/guardrails tests/unit/cache tests/unit/db \
	           tests/security tests/contract

# Member 2 suite
test-m2:
	$(PYTEST) -q tests/unit/gateway tests/unit/router \
	           tests/integration tests/e2e tests/contract

# Contract + snapshot tests only
test-contract:
	$(PYTEST) -q tests/contract

# Security tests only
test-security:
	$(PYTEST) -q -m security tests/security

# With coverage report (HTML + terminal)
test-cov:
	$(PYTEST) --cov --cov-report=term-missing --cov-report=html \
	           -m "not slow and not perf and not live"

# Micro-benchmarks (informational; not in CI by default)
perf:
	$(PYTEST) -q --benchmark-only -m perf tests/perf

# ---------------------------------------------------------------------------
# Member 1 Gate 2 acceptance runner
# ---------------------------------------------------------------------------
verify-m1:
	$(PYTHON) scripts/verify_m1.py

# ---------------------------------------------------------------------------
# Integration benchmarks (Phase 4)
# ---------------------------------------------------------------------------
bench:
	$(PYTHON) -m integration.benchmarks.run_benchmarks --suite all

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
db-migrate:
	FLUXGATE_AUTO_MIGRATE=true $(PYTHON) -c \
	  "import asyncio; from shared.db.migrator import run_migrations; asyncio.run(run_migrations())"

# Online-safe backup (WAL-safe; SQLite .backup command)
db-backup:
	@mkdir -p data
	@DATE=$$(python -c "import datetime; print(datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))"); \
	sqlite3 data/fluxgate.db ".backup data/backup-$$DATE.db"; \
	echo "Backup written: data/backup-$$DATE.db"

# Manual VACUUM (run when file > 2x expected size; see BACKEND_SCHEMA.md §7)
db-vacuum:
	sqlite3 data/fluxgate.db "VACUUM;"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache  -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache  -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov .coverage
