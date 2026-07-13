from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_attempt_ledger import (
    ClaimAttemptRecord,
    attempt_by_id_conn,
    attempt_by_number_conn,
    attempt_view,
    insert_claim_attempt_conn,
    pending_cancel_observation_ids_conn,
    pending_provider_cleanup_observation_ids_conn,
    pending_runner_recovery_observation_ids_conn,
    public_attempt_view,
)
from xmuse_core.chat.room_kernel import RoomKernelStore


def _claimed_observation(path: Path) -> tuple[str, dict[str, object]]:
    conversation = RoomTestStore(path).create_conversation("attempt ledger")
    participant = ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="reviewer",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="alice",
        content="review this",
        client_request_id="human-1",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="host-1",
    )
    assert claim is not None
    return str(claim["observation"]["observation_id"]), claim["observation"]


def _record(observation: sqlite3.Row, *, attempt_id: str = "attempt-1") -> ClaimAttemptRecord:
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    token = str(observation["lease_token"])
    return ClaimAttemptRecord(
        attempt_id=attempt_id,
        batch_id=None,
        conversation_id=str(observation["conversation_id"]),
        observation_id=str(observation["observation_id"]),
        participant_id=str(observation["participant_id"]),
        attempt_number=int(observation["attempt_count"]),
        effective_attempt_limit=3,
        delivery_generation=int(observation["attempt_count"]),
        lease_owner=str(observation["lease_owner"]),
        lease_token_digest=hashlib.sha256(token.encode()).hexdigest(),
        runner_generation="runner-gen",
        runner_boot_id="runner-boot",
        claimed_at=str(observation["acquired_at"]),
        expires_at=str(observation["expires_at"]),
        created_at=stamp,
        updated_at=stamp,
    )


def _remove_kernel_attempt(conn: sqlite3.Connection, observation_id: str) -> sqlite3.Row:
    """Leave the claimed observation intact so the leaf insert can be exercised."""

    observation = conn.execute(
        "select * from room_observations where observation_id = ?", (observation_id,)
    ).fetchone()
    conn.execute(
        "update room_observations set current_attempt_id = null where observation_id = ?",
        (observation_id,),
    )
    conn.execute(
        "delete from room_observation_attempts where observation_id = ?",
        (observation_id,),
    )
    return observation


def test_insert_and_queries_remain_in_caller_transaction(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    observation_id, _claim = _claimed_observation(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        conn.execute("begin immediate")
        observation = _remove_kernel_attempt(conn, observation_id)
        inserted = insert_claim_attempt_conn(conn, _record(observation))
        assert attempt_by_id_conn(conn, "attempt-1") == inserted
        assert (
            attempt_by_number_conn(conn, observation_id=observation_id, attempt_number=1)
            == inserted
        )
        conn.rollback()

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert attempt_by_id_conn(conn, "attempt-1") is None


def test_attempt_views_fence_authority_and_browser_fields(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    observation_id, _claim = _claimed_observation(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        observation = _remove_kernel_attempt(conn, observation_id)
        row = insert_claim_attempt_conn(conn, _record(observation))

        ordinary = attempt_view(row)
        reconcile = attempt_view(row, include_reconcile_binding=True)
        public = public_attempt_view(row)
        assert ordinary is not None and reconcile is not None and public is not None
        for hidden in (
            "lease_owner",
            "lease_token_digest",
            "runner_generation",
            "runner_boot_id",
        ):
            assert hidden not in ordinary
            assert hidden not in reconcile
            assert hidden not in public
        assert "provider_session_generation" not in ordinary
        assert "provider_session_generation" in reconcile
        assert set(public) == {
            "attempt_number",
            "effective_attempt_limit",
            "state",
            "reason_code",
            "claimed_at",
            "expires_at",
            "transport_started_at",
            "finished_at",
            "updated_at",
        }


def test_pending_queries_preserve_cleanup_and_recovery_semantics(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    observation_id, _claim = _claimed_observation(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        observation = _remove_kernel_attempt(conn, observation_id)
        insert_claim_attempt_conn(conn, _record(observation))
        conn.execute(
            "update room_observations set current_attempt_id = ?, control_state = ? "
            "where observation_id = ?",
            ("attempt-1", "cancel_pending", observation_id),
        )
        assert pending_cancel_observation_ids_conn(conn) == [observation_id]
        assert pending_provider_cleanup_observation_ids_conn(conn) == []

        conn.execute(
            "update room_observations set control_state = 'active' where observation_id = ?",
            (observation_id,),
        )
        conn.execute(
            "update room_observation_attempts set provider_phase = 'cleanup_pending', "
            "recovery_state = 'cleanup_pending', recovery_reason_code = 'boot_lost' "
            "where attempt_id = 'attempt-1'"
        )
        assert pending_provider_cleanup_observation_ids_conn(conn) == [observation_id]
        assert pending_runner_recovery_observation_ids_conn(conn, reason_code="boot_lost") == [
            observation_id
        ]
        assert pending_runner_recovery_observation_ids_conn(conn, reason_code="different") == []
