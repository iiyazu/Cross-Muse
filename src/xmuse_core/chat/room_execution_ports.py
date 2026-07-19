"""Narrow Room-facing ports for the exact-patch execution ledger.

The Room host and provider transport only exchange review evidence with the
execution subsystem.  They must not depend on its privileged operator or
controller surface; composition supplies only the review capability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class ExecutionReviewMaterialReader(Protocol):
    """Read bounded proposal material for one claimed observation batch."""

    def get_review_material_for_batch(
        self,
        *,
        candidate_id: str,
        proposal_activity_id: str,
        observation_batch_id: str,
        participant_id: str,
        attempt_id: str,
    ) -> dict[str, Any]: ...


class ExecutionReviewReceiptWriter(Protocol):
    """Bind submitted review context to the exact delivery attempt."""

    def bind_review_material_receipt(
        self,
        *,
        candidate_id: str,
        proposal_activity_id: str,
        observation_batch_id: str,
        participant_id: str,
        attempt_id: str,
        review_material_digest: str,
        context_payload_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]: ...


class ExecutionReviewPort(
    ExecutionReviewMaterialReader,
    ExecutionReviewReceiptWriter,
    Protocol,
):
    """Combined composition port supplied to the Room host and transport."""
