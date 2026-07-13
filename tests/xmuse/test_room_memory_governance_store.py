from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_common import RoomMemoryStoreError
from xmuse_core.chat.room_memory_contracts import normalize_memory_candidates
from xmuse_core.chat.room_memory_governance_store import record_memory_candidates_conn


def test_record_memory_candidates_requires_caller_owned_transaction(tmp_path: Path) -> None:
    database = RoomDatabase(tmp_path / "chat.db")
    database.initialize()
    candidates = normalize_memory_candidates(
        [
            {
                "kind": "room_fact",
                "content": "Candidate writes must join the Room outcome transaction.",
                "source_activity_ids": ["activity-1"],
            }
        ]
    )

    with database.connect() as conn:
        assert not conn.in_transaction
        with pytest.raises(RoomMemoryStoreError) as raised:
            record_memory_candidates_conn(
                conn,
                conversation_id="conversation-1",
                author_participant_id="participant-1",
                source_observation_id="observation-1",
                source_batch_id="batch-1",
                source_attempt_id="attempt-1",
                batch_activity_ids={"activity-1"},
                candidates=candidates,
                stamp="2026-07-12T00:00:00.000000Z",
            )

    assert raised.value.code == "room_memory_candidate_transaction_required"
