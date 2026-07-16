"""Least-authority execution review store used by Room delivery."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_candidates import (
    bind_review_material_receipt_conn,
    review_material_for_batch_conn,
)
from xmuse_core.chat.room_execution_common import require_digest, timestamp


class RoomExecutionReviewStore:
    """Read review material and bind only its exact delivery receipt."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def get_review_material_for_batch(
        self,
        *,
        candidate_id: str,
        proposal_activity_id: str,
        observation_batch_id: str,
        participant_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return self._review_material_for_batch_conn(
                conn,
                candidate_id=candidate_id,
                proposal_activity_id=proposal_activity_id,
                observation_batch_id=observation_batch_id,
                participant_id=participant_id,
                attempt_id=attempt_id,
            )

    @staticmethod
    def _review_material_for_batch_conn(
        conn: sqlite3.Connection,
        *,
        candidate_id: str,
        proposal_activity_id: str,
        observation_batch_id: str,
        participant_id: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        return review_material_for_batch_conn(
            conn,
            candidate_id=candidate_id,
            proposal_activity_id=proposal_activity_id,
            observation_batch_id=observation_batch_id,
            participant_id=participant_id,
            attempt_id=attempt_id,
        )

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
    ) -> dict[str, Any]:
        review_material_digest = require_digest(
            review_material_digest, "room_execution_review_material_digest_invalid"
        )
        context_payload_sha256 = require_digest(
            context_payload_sha256, "room_execution_review_context_digest_invalid"
        )
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                result = bind_review_material_receipt_conn(
                    conn,
                    candidate_id=candidate_id,
                    proposal_activity_id=proposal_activity_id,
                    observation_batch_id=observation_batch_id,
                    participant_id=participant_id,
                    attempt_id=attempt_id,
                    review_material_digest=review_material_digest,
                    context_payload_sha256=context_payload_sha256,
                    stamp=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
