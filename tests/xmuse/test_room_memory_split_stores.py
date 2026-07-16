from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from tests.xmuse.test_room_memory import DIGEST, _setup_memory_session
from tests.xmuse.test_room_participant_outcomes import root_and_claims
from xmuse_core.chat.room_memory_advisory_store import RoomMemoryAdvisoryStore
from xmuse_core.chat.room_memory_binding_store import RoomMemoryBindingStore
from xmuse_core.chat.room_memory_recall_receipt_store import RoomMemoryRecallReceiptStore
from xmuse_core.chat.room_memory_recall_source_store import RoomMemoryRecallSourceStore
from xmuse_core.chat.room_memory_source_conn import activity_source_conn


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def test_source_request_store_keeps_connection_helpers_caller_owned(tmp_path: Path) -> None:
    db, _registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    delivery = RoomMemoryBindingStore(db)
    _setup_memory_session(delivery, conversation_id)
    source_store = RoomMemoryRecallSourceStore(db)
    activity_id = str(root["activity"]["activity_id"])
    participant_id = records[0][0].participant_id
    attempt_id = str(claims[participant_id]["attempt"]["attempt_id"])

    request = source_store.build_recall_request(
        conversation_id=conversation_id,
        attempt_id=attempt_id,
        correlation_id=str(root["activity"]["correlation_id"]),
        causal_activity_ids=[activity_id],
    )
    proof = source_store.resolve_recall_source(
        conversation_id=conversation_id,
        document_id=f"xmuse-room-activity-{activity_id}",
        source_activity_ids=[activity_id],
        content_sha256=_sha("ell"),
        item_text="ell",
    )

    assert request["schema_version"] == "room_memory_recall_request/v1"
    assert proof["source_activities"][0]["activity_id"] == activity_id
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("begin")
        assert (
            activity_source_conn(
                conn,
                conversation_id=conversation_id,
                activity_id=activity_id,
            )["content"]
            == "hello"
        )
        assert conn.in_transaction
        conn.rollback()


def test_receipt_store_preserves_two_phase_context_binding(tmp_path: Path) -> None:
    db, _registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    participant_id = records[0][0].participant_id
    attempt_id = str(claims[participant_id]["attempt"]["attempt_id"])
    activity_id = str(root["activity"]["activity_id"])
    store = RoomMemoryRecallReceiptStore(db)

    receipt = store.record_attempt_memory_receipt(
        attempt_id=attempt_id,
        status="ok",
        schema_version="metadata.v3_context/v1",
        latency_ms=5,
        items=[
            {
                "item_id": "item-valid",
                "document_id": f"xmuse-room-activity-{activity_id}",
                "source_activity_ids": [activity_id],
                "content_sha256": _sha("ell"),
                "text": "ell",
            }
        ],
        evidence_sha256=DIGEST,
    )
    bound = store.bind_attempt_memory_context(
        attempt_id=attempt_id,
        evidence_sha256=DIGEST,
        context_payload_sha256="sha256:" + "2" * 64,
    )

    assert receipt["context_payload_sha256"] is None
    assert bound["context_submitted_at"] is not None
    assert store.list_attempt_receipts(conversation_id) == [bound]


def test_advisory_store_reproves_sources_and_records_governance_receipt(
    tmp_path: Path,
) -> None:
    db, _registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    participant_id = records[0][0].participant_id
    attempt_id = str(claims[participant_id]["attempt"]["attempt_id"])
    activity_id = str(root["activity"]["activity_id"])
    store = RoomMemoryAdvisoryStore(db)
    advisory = {
        "advisory_id": "advisory-split-store",
        "fingerprint": "a" * 64,
        "proposal_type": "archive_write",
        "content": "The current Room source remains authoritative.",
        "source_refs": [
            {
                "source_type": "document",
                "source_id": f"xmuse-room-activity-{activity_id}",
            }
        ],
    }

    result = store.record_external_advisories(
        conversation_id=conversation_id,
        attempt_id=attempt_id,
        advisories=[advisory],
    )
    replay = store.record_external_advisories(
        conversation_id=conversation_id,
        attempt_id=attempt_id,
        advisories=[advisory],
    )
    receipts = store.list_external_advisory_receipts(conversation_id)

    assert result and result[0]["kind"] == "room_fact"
    assert replay == []
    assert receipts[0]["status"] == "accepted"
    assert receipts[0]["source_activity_ids"] == [activity_id]
