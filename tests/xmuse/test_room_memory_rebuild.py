from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from tests.xmuse.test_room_participant_outcomes import root_and_claims, submit
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_delivery_store import RoomMemoryDeliveryStore
from xmuse_core.chat.room_memory_governance_store import RoomMemoryGovernanceStore
from xmuse_core.chat.room_memory_rebuild_store import (
    RoomMemoryRebuildActionStore,
    RoomMemoryRebuildError,
    reset_room_memory_index_conn,
    safe_memory_rebuild_action,
)


def _reserve(
    store: RoomMemoryRebuildActionStore,
    client_action_id: str,
    *,
    fingerprint: str | None = None,
) -> tuple[dict[str, object], bool]:
    return store.reserve(
        client_action_id=client_action_id,
        request_fingerprint=fingerprint or f"fingerprint-{client_action_id}",
        incident_guard="memoryos_incident_guard",
        before_state="degraded",
        before_code="memoryos_crash_loop",
    )


def test_rebuild_ledger_is_idempotent_conflict_safe_and_single_inflight(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    RoomDatabase(db).initialize()
    store = RoomMemoryRebuildActionStore(db)

    first, created = _reserve(store, "first")
    replay, replay_created = _reserve(store, "first")
    assert created is True
    assert replay_created is False
    assert replay == first
    assert first["status"] == "requested"
    assert first["phase"] == "requested"

    with pytest.raises(RoomMemoryRebuildError) as conflict:
        _reserve(store, "first", fingerprint="different-fingerprint")
    assert conflict.value.code == "room_memory_rebuild_idempotency_conflict"

    second, second_created = _reserve(store, "second")
    assert second_created is True
    assert second["status"] == "rejected"
    assert second["reason_code"] == "room_memory_rebuild_in_progress"
    assert store.next_requested() == first

    applied = store.finish(
        client_action_id="first",
        status="applied",
        after_state="ready",
        after_code="ready",
        reason_code=None,
    )
    assert applied["status"] == "applied"
    assert applied["phase"] == "complete"
    assert (
        store.finish(
            client_action_id="first",
            status="failed",
            after_state="degraded",
            after_code="memoryos_health_unavailable",
            reason_code="memoryos_rebuild_failed",
        )
        == applied
    )

    third, third_created = _reserve(store, "third")
    assert third_created is True
    assert third["status"] == "requested"

    safe = safe_memory_rebuild_action(third)
    assert set(safe) == {
        "schema_version",
        "action_id",
        "client_action_id",
        "status",
        "phase",
        "reason_code",
        "before",
        "after",
        "result",
        "requested_at",
        "applied_at",
        "proof_boundary",
    }
    assert "_incident_guard" not in safe
    assert "_revision" not in safe


def test_concurrent_rebuild_reservations_leave_exactly_one_requested(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    RoomDatabase(db).initialize()
    barrier = Barrier(2)

    def reserve(index: int) -> str:
        barrier.wait(timeout=5)
        action, _created = _reserve(RoomMemoryRebuildActionStore(db), f"parallel-{index}")
        return str(action["status"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(reserve, range(2)))

    assert sorted(statuses) == ["rejected", "requested"]
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "select count(*) from room_memory_rebuild_actions where status = 'requested'"
            ).fetchone()[0]
            == 1
        )


def _seed_rebuildable_memory(
    tmp_path: Path,
) -> tuple[Path, str, str, str]:
    db, registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    participant, session = records[0]
    source_activity_id = str(root["activity"]["activity_id"])
    submit(
        db,
        registry,
        conversation_id,
        participant,
        session,
        claims[participant.participant_id],
        "memory-rebuild-candidates",
        outcome_type="noop",
        outcome_payload={},
        memory_candidates=[
            {
                "kind": "room_fact",
                "content": "approved durable fact",
                "source_activity_ids": [source_activity_id],
            },
            {
                "kind": "user_preference",
                "content": "pending preference",
                "source_activity_ids": [source_activity_id],
            },
        ],
    )
    candidates = RoomMemoryGovernanceStore(db).list_candidates(conversation_id)
    approved = next(item for item in candidates if item["approval_state"] == "approved")
    pending = next(item for item in candidates if item["approval_state"] == "pending")
    RoomMemoryDeliveryStore(db).ensure_binding(conversation_id=conversation_id)
    stamp = "2026-07-12T00:00:00.000000Z"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """update room_memory_bindings
               set session_id = 'private-session', session_state = 'bound',
                   attachment_id = 'private-attachment-' || scope_type,
                   attachment_state = 'attached'"""
        )
        approved_outbox = conn.execute(
            "select outbox_id from room_memory_outbox where candidate_id = ?",
            (approved["candidate_id"],),
        ).fetchone()
        assert approved_outbox is not None
        conn.execute(
            """insert into room_memory_deliveries
               (delivery_id, outbox_id, attempt_number, worker_id,
                lease_token_sha256, state, request_digest, claimed_at, updated_at)
               values ('delivery-before-rebuild', ?, 1, 'private-worker', ?,
                       'claimed', ?, ?, ?)""",
            (
                approved_outbox[0],
                "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
                stamp,
                stamp,
            ),
        )
        conn.execute(
            """update room_memory_outbox
               set state = 'claimed', attempt_count = 1,
                   lease_owner = 'private-worker', lease_token = 'private-lease',
                   acquired_at = ?, expires_at = ?,
                   current_delivery_id = 'delivery-before-rebuild'
               where outbox_id = ?""",
            (stamp, "2026-07-12T01:00:00.000000Z", approved_outbox[0]),
        )
        # Model a partially lost derived outbox row. Rebuild recreates it only
        # from the durable visible Room activity.
        conn.execute("delete from room_memory_outbox where activity_id is not null")
    return db, conversation_id, str(approved["candidate_id"]), str(pending["candidate_id"])


def _authority_snapshot(db: Path) -> tuple[list[tuple[object, ...]], ...]:
    with sqlite3.connect(db) as conn:
        return (
            conn.execute(
                """select binding_id, session_id, session_state, attachment_id,
                          attachment_state, revision
                   from room_memory_bindings order by binding_id"""
            ).fetchall(),
            conn.execute(
                """select outbox_id, candidate_id, state, lease_owner, lease_token,
                          current_delivery_id, reason_code
                   from room_memory_outbox order by outbox_id"""
            ).fetchall(),
            conn.execute(
                """select candidate_id, approval_state, publish_state, reason_code, revision
                   from room_memory_candidates order by candidate_id"""
            ).fetchall(),
            conn.execute(
                """select delivery_id, state, reason_code
                   from room_memory_deliveries order by delivery_id"""
            ).fetchall(),
        )


def test_memory_index_reset_requires_caller_transaction_rolls_back_and_replays_only_proof(
    tmp_path: Path,
) -> None:
    db, _conversation_id, approved_id, pending_id = _seed_rebuildable_memory(tmp_path)
    before = _authority_snapshot(db)

    with RoomDatabase(db).connect() as conn:
        with pytest.raises(RoomMemoryRebuildError) as missing_transaction:
            reset_room_memory_index_conn(
                conn,
                reason_code="room_memory_operator_rebuild_required",
            )
        assert missing_transaction.value.code == "room_memory_rebuild_transaction_required"

        conn.execute("begin immediate")
        rolled_back_counts = reset_room_memory_index_conn(
            conn,
            reason_code="room_memory_operator_rebuild_required",
            stamp="2026-07-12T02:00:00.000000Z",
        )
        assert rolled_back_counts == {
            "bindings_reset": 3,
            "deliveries_reopened": 2,
            "claimed_attempts_fenced": 1,
            "candidates_requeued": 1,
        }
        conn.rollback()

    assert _authority_snapshot(db) == before

    with RoomDatabase(db).connect() as conn:
        conn.execute("begin immediate")
        counts = reset_room_memory_index_conn(
            conn,
            reason_code="room_memory_operator_rebuild_required",
            stamp="2026-07-12T03:00:00.000000Z",
        )
        conn.commit()
    assert counts == rolled_back_counts

    with sqlite3.connect(db) as conn:
        bindings = conn.execute(
            """select session_id, session_state, attachment_id, attachment_state
               from room_memory_bindings order by binding_id"""
        ).fetchall()
        outbox = conn.execute(
            """select candidate_id, state, lease_owner, lease_token,
                      current_delivery_id, delivered_at
               from room_memory_outbox order by outbox_id"""
        ).fetchall()
        candidates = dict(
            conn.execute(
                "select candidate_id, publish_state from room_memory_candidates"
            ).fetchall()
        )
        message_outbox = conn.execute(
            "select state, lease_owner, lease_token, current_delivery_id, delivered_at "
            "from room_memory_message_outbox"
        ).fetchall()
        delivery = conn.execute("select state, reason_code from room_memory_deliveries").fetchone()

    assert bindings == [(None, "unbound", None, "pending")] * 3
    assert len(outbox) == 2
    assert all(row[1:] == ("pending", None, None, None, None) for row in outbox)
    assert [row[0] for row in outbox].count(approved_id) == 1
    assert pending_id not in {row[0] for row in outbox}
    assert candidates == {approved_id: "queued", pending_id: "not_queued"}
    assert message_outbox
    assert all(row == ("pending", None, None, None, None) for row in message_outbox)
    assert delivery == ("failed", "room_memory_operator_rebuild_required")

    replay = RoomMemoryRebuildActionStore(db).replay_status()
    assert replay == {
        "bindings_pending": 3,
        "pending": 2,
        "claimed": 0,
        "failed": 0,
        "conflict": 0,
    }


def test_action_authority_reset_advances_phase_atomically(tmp_path: Path) -> None:
    db, _conversation_id, _approved_id, _pending_id = _seed_rebuildable_memory(tmp_path)
    store = RoomMemoryRebuildActionStore(db)
    _reserve(store, "reset-action")
    store.advance(
        client_action_id="reset-action",
        expected_phase="requested",
        phase="stopping",
    )
    store.advance(
        client_action_id="reset-action",
        expected_phase="stopping",
        phase="stopped",
    )
    store.advance(
        client_action_id="reset-action",
        expected_phase="stopped",
        phase="cache_cleared",
        result={"cache_cleared": True},
    )

    reset = store.reset_authority(client_action_id="reset-action")
    assert reset["phase"] == "authority_reset"
    assert reset["result"] == {
        "cache_cleared": True,
        "bindings_reset": 3,
        "deliveries_reopened": 2,
        "claimed_attempts_fenced": 1,
        "candidates_requeued": 1,
    }
    assert store.reset_authority(client_action_id="reset-action") == reset
