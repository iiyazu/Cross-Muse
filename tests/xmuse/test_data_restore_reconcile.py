from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_host import RoomHostPolicy, RoomParticipantHost
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _room(path: Path, *, participant_count: int = 1) -> tuple[Path, str, list[Participant]]:
    db_path = path / "chat.db"
    conversation = CompatDataTestStore(db_path).create_conversation("Restored room")
    participants = [
        ParticipantStore(db_path).add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(participant_count)
    ]
    RoomKernelStore(db_path).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="Please inspect the restored runtime.",
        client_request_id="human-before-backup",
    )
    return db_path, conversation.id, participants


def _claim(
    db_path: Path,
    conversation_id: str,
    participant: Participant,
    *,
    base_attempt_limit: int = 3,
) -> dict:
    claim = RoomKernelStore(db_path).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="room-host:old-generation",
        lease_ttl_s=300,
        base_attempt_limit=base_attempt_limit,
        now=NOW,
    )
    assert claim is not None
    return claim


def _bind_provider(
    db_path: Path,
    controls: RoomObservationControlStore,
    claim: dict,
) -> None:
    observation = claim["observation"]
    attempt_id = claim["attempt"]["attempt_id"]
    RoomAttemptSkillDecisionStore(db_path).bind_for_attempt(
        attempt_id=attempt_id,
        catalog=SkillCatalog.load_bundled(),
        now=NOW,
    )
    controls.bind_delivery(
        observation_id=observation["observation_id"],
        attempt_id=attempt_id,
        lease_token=observation["lease_token"],
        delivery_task_id=f"delivery:{attempt_id}",
        provider_session_generation=attempt_id,
        now=NOW,
    )
    controls.mark_provider_ensure_started(
        observation_id=observation["observation_id"],
        attempt_id=attempt_id,
        delivery_generation=attempt_id,
        now=NOW,
    )
    controls.bind_provider_session(
        observation_id=observation["observation_id"],
        attempt_id=attempt_id,
        delivery_generation=attempt_id,
        god_session_id="god-old-generation",
        provider_session_id="thread-old-generation",
        now=NOW,
    )


def _attempt_row(db_path: Path, attempt_id: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "select * from room_observation_attempts where attempt_id = ?",
            (attempt_id,),
        ).fetchone()
    assert row is not None
    return row


def test_offline_fence_reopens_claim_and_rejects_late_lease(tmp_path: Path) -> None:
    db_path, conversation_id, participants = _room(tmp_path)
    claim = _claim(db_path, conversation_id, participants[0], base_attempt_limit=2)
    old_token = claim["observation"]["lease_token"]
    observation_id = claim["observation"]["observation_id"]
    attempt_id = claim["attempt"]["attempt_id"]

    # initialize=False must not seed or migrate the validated staging database.
    with sqlite3.connect(db_path) as conn:
        conn.execute("drop table room_runtime_restore_fences")
    controls = RoomObservationControlStore(db_path, initialize=False)
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "select 1 from sqlite_master where name = 'room_runtime_restore_fences'"
            ).fetchone()
            is None
        )

    result = controls.fence_restored_runtime_generation(
        operation_id="restore-1",
        now=NOW + timedelta(seconds=1),
    )

    assert result["reopened_pending_count"] == 1
    observation = RoomKernelStore(db_path).get_observation(observation_id)
    assert observation["status"] == "pending"
    assert observation["control_state"] == "active"
    assert observation["lease_owner"] is None
    assert observation["lease_token"] is None
    assert observation["expires_at"] is None
    attempt = _attempt_row(db_path, attempt_id)
    assert (attempt["state"], attempt["reason_code"]) == (
        "expired",
        "restore_runtime_generation_fenced",
    )

    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        RoomKernelStore(db_path).complete_observation(
            conversation_id=conversation_id,
            participant_id=participants[0].participant_id,
            caller_identity=f"god:old:{participants[0].participant_id}",
            observation_id=observation_id,
            lease_token=old_token,
            client_request_id="late-outcome",
            outcome_type="noop",
            now=NOW + timedelta(seconds=2),
        )

    reclaimed = RoomKernelStore(db_path).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participants[0].participant_id,
        lease_owner="room-host:new-generation",
        base_attempt_limit=2,
        now=NOW + timedelta(seconds=2),
    )
    assert reclaimed is not None
    assert reclaimed["attempt"]["attempt_number"] == 2


def test_pending_cancel_keeps_control_generation_until_host_settles_it(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participants = _room(tmp_path)
    claim = _claim(db_path, conversation_id, participants[0])
    controls = RoomObservationControlStore(db_path)
    _bind_provider(db_path, controls, claim)
    observation_id = claim["observation"]["observation_id"]
    attempt_id = claim["attempt"]["attempt_id"]
    requested = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel-before-restore",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
        now=NOW + timedelta(seconds=1),
    )["projection"]
    with sqlite3.connect(db_path) as conn:
        control_count = conn.execute("select count(*) from room_observation_controls").fetchone()[0]

    result = controls.fence_restored_runtime_generation(
        operation_id="restore-cancel",
        now=NOW + timedelta(seconds=2),
    )

    assert result["pending_cancel_count"] == 1
    pending = controls.reconcile_state(observation_id)
    assert pending["control_state"] == "cancel_requested"
    assert pending["control_seq"] == requested["control_seq"]
    assert pending["manual_retry_budget"] == 0
    assert pending["reconcile_binding"]["state"] == "cancel_requested"
    assert pending["reconcile_binding"]["provider_phase"] == "cleanup_succeeded"
    assert pending["reconcile_binding"]["provider_cleanup_reason"] == (
        "restore_transport_generation_fenced"
    )
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("select count(*) from room_observation_controls").fetchone()[0]
            == control_count
        )

    class _UnusedTransport:
        async def deliver(self, delivery, *, timeout_s):
            raise AssertionError("settled restore cleanup must not start transport")

    host = RoomParticipantHost(
        db_path,
        _UnusedTransport(),
        policy=RoomHostPolicy(
            delivery_timeout_s=1,
            cleanup_grace_s=1,
            lease_ttl_s=3,
        ),
        clock=lambda: NOW + timedelta(seconds=3),
        control_store=controls,
    )
    asyncio.run(host.reconcile_controls())
    assert controls.projection(observation_id)["control_state"] == "cancelled"
    assert _attempt_row(db_path, attempt_id)["state"] == "cancelled"


def test_restore_operation_is_idempotent_and_emits_one_event_per_room(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participants = _room(tmp_path, participant_count=2)
    claims = [_claim(db_path, conversation_id, participant) for participant in participants]
    controls = RoomObservationControlStore(db_path)
    before_events = len(CompatDataTestStore(db_path).list_frontend_events(conversation_id))
    before_attempts = _table_count(db_path, "room_observation_attempts")

    first = controls.fence_restored_runtime_generation(
        operation_id="restore-idempotent",
        now=NOW + timedelta(seconds=1),
    )
    second = controls.fence_restored_runtime_generation(
        operation_id=" restore-idempotent ",
        now=NOW + timedelta(seconds=10),
    )

    assert second == first
    assert first["affected_observation_count"] == 2
    assert first["affected_conversation_count"] == 1
    restored_events = CompatDataTestStore(db_path).list_frontend_events(conversation_id)
    assert len(restored_events) == before_events + 1
    assert _table_count(db_path, "room_runtime_restore_fences") == 1
    assert _table_count(db_path, "room_observation_attempts") == before_attempts
    assert all(
        RoomKernelStore(db_path).get_observation(claim["observation"]["observation_id"])[
            "manual_retry_budget"
        ]
        == 0
        for claim in claims
    )


def test_restore_fence_materializes_attempt_budget_terminal_state(tmp_path: Path) -> None:
    db_path, conversation_id, participants = _room(tmp_path)
    claim = _claim(db_path, conversation_id, participants[0], base_attempt_limit=1)
    observation_id = claim["observation"]["observation_id"]

    result = RoomObservationControlStore(db_path).fence_restored_runtime_generation(
        operation_id="restore-exhausted",
        now=NOW + timedelta(seconds=1),
    )

    observation = RoomKernelStore(db_path).get_observation(observation_id)
    assert result["exhausted_count"] == 1
    assert observation["control_state"] == "exhausted"
    assert observation["control_seq"] == 1
    assert observation["attempt_count"] == 1
    assert observation["manual_retry_budget"] == 0
    assert observation["lease_token"] is None
    assert (
        RoomKernelStore(db_path).claim_next_observation(
            conversation_id=conversation_id,
            participant_id=participants[0].participant_id,
            lease_owner="room-host:new-generation",
            base_attempt_limit=1,
            now=NOW + timedelta(seconds=2),
        )
        is None
    )


def _table_count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"select count(*) from {table}").fetchone()[0])
