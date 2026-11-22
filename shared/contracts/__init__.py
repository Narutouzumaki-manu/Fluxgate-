"""Shared, jointly-owned code: contracts, config, errors, ids, clock, db, test fakes.

Changes to shared/contracts and shared/db/migrations follow the contract change procedure
(docs/GIT_AND_COLLAB_WORKFLOW.md section 9). Everything else here needs both approvals.
"""

"""FluxGate inter-module contracts (v1.0.0)."""

CONTRACT_VERSION: str = "1.0.0"

__all__ = ["CONTRACT_VERSION"]
