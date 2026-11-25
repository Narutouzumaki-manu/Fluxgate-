"""Guardrails package — AI security (prompt injection, PII, secrets, redaction).

Owner: Member 1.
Public entry point: ``build_guardrail_engine(settings) -> GuardrailEngine``.
Only imports ``shared/`` and third-party libraries.
"""

from guardrails.engine import build_guardrail_engine

__all__ = ["build_guardrail_engine"]
