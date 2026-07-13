from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_controls import (
    RoomControlError,
    RoomObservationControlStore,
    assert_room_outcome_allowed,
    commit_room_outcome_attempt,
    create_room_control_schema,
    record_room_claim_attempt,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog


def _claimed_room(tmp_path, *, now: datetime | None = None, lease_ttl_s: float = 120):
    path = tmp_path / "chat.db"
    conversation = RoomTestStore(path).create_conversation("controlled room")
    participant = ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="reviewer",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(path)
    posted = kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="alice",
        content="review this",
        client_request_id="human-1",
    )
    claimed = kernel.claim_next_observation(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="host-1",
        lease_ttl_s=lease_ttl_s,
        now=now,
    )
    assert claimed is not None
    return path, conversation.id, participant, kernel, posted, claimed


def _bind_skill_decision(path, attempt_id: str, *, now: datetime) -> None:
    RoomAttemptSkillDecisionStore(path).bind_for_attempt(
        attempt_id=attempt_id,
        catalog=SkillCatalog.load_bundled(),
        now=now,
    )


def test_schema_migrates_existing_observation_and_claim_helper_is_idempotent(tmp_path):
    path, _, _, _, _, claim = _claimed_room(tmp_path)
    controls = RoomObservationControlStore(path)
    observation_id = claim["observation"]["observation_id"]

    first = controls.record_claim(observation_id, base_attempt_limit=3)
    second = controls.record_claim(observation_id, base_attempt_limit=3)

    assert first == second
    assert first["attempt_number"] == first["delivery_generation"] == 1
    assert first["effective_attempt_limit"] == 3
    assert "lease_token" not in first
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        create_room_control_schema(conn)
        row = conn.execute(
            "select control_state, control_seq, manual_retry_budget, current_attempt_id "
            "from room_observations where observation_id = ?",
            (observation_id,),
        ).fetchone()
        assert dict(row) == {
            "control_state": "active",
            "control_seq": 0,
            "manual_retry_budget": 0,
            "current_attempt_id": first["attempt_id"],
        }


def test_cancel_fences_late_outcome_and_replays_idempotently(tmp_path):
    path, conversation_id, participant, kernel, _, claim = _claimed_room(tmp_path)
    controls = RoomObservationControlStore(path)
    observation_id = claim["observation"]["observation_id"]
    attempt = controls.record_claim(observation_id, base_attempt_limit=3)
    _bind_skill_decision(path, attempt["attempt_id"], now=datetime.now(UTC))
    controls.bind_delivery(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        lease_token=claim["observation"]["lease_token"],
        delivery_task_id="task-1",
        provider_session_id="session-1",
        provider_session_generation="generation-1",
    )

    command = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel-1",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
    )
    replay = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel-1",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
    )

    assert replay["control"]["control_id"] == command["control"]["control_id"]
    assert command["projection"]["control_state"] == "cancel_requested"
    assert command["projection_event"]["event_type"] == "projection.changed"
    assert command["projection_event"]["source_ref"] == observation_id
    assert "attempt_id" not in repr(command["projection"])
    assert "lease_owner" not in repr(command["projection"])
    assert controls.list_pending_cancels()[0]["reconcile_binding"]["delivery_task_id"] == "task-1"
    assert claim["observation"]["lease_token"] not in repr(controls.list_pending_cancels())
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        kernel.complete_observation(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            caller_identity=f"god:session:{participant.participant_id}",
            observation_id=observation_id,
            lease_token=claim["observation"]["lease_token"],
            client_request_id="late-outcome",
            outcome_type="noop",
        )
    with pytest.raises(RoomControlError, match="room_control_idempotency_conflict"):
        controls.request_cancel(
            observation_id=observation_id,
            client_action_id="cancel-1",
            operator_identity="operator:local",
            expected_state="cancel_requested",
            expected_attempt_count=1,
            expected_control_seq=1,
        )


def test_cancel_pending_cancelled_retry_reopens_only_the_same_observation(tmp_path):
    path, conversation_id, participant, kernel, _, claim = _claimed_room(tmp_path)
    controls = RoomObservationControlStore(path)
    observation_id = claim["observation"]["observation_id"]
    attempt = controls.record_claim(observation_id, base_attempt_limit=3)
    requested = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
    )
    pending = controls.mark_cancel_pending(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        expected_control_seq=requested["projection"]["control_seq"],
    )
    with pytest.raises(RoomControlError, match="room_observation_not_retryable"):
        controls.request_retry(
            observation_id=observation_id,
            client_action_id="too-early",
            operator_identity="operator:local",
            expected_state="cancel_pending",
            expected_attempt_count=1,
            expected_control_seq=pending["control_seq"],
        )
    cancelled = controls.mark_cancelled(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        expected_control_seq=pending["control_seq"],
    )
    retried = controls.request_retry(
        observation_id=observation_id,
        client_action_id="retry",
        operator_identity="operator:local",
        expected_state="cancelled",
        expected_attempt_count=1,
        expected_control_seq=cancelled["control_seq"],
    )

    assert retried["projection"]["control_state"] == "active"
    assert retried["projection"]["manual_retry_budget"] == 1
    assert controls.effective_limit(observation_id, 3) == 4
    assert kernel.get_observation(observation_id)["status"] == "pending"
    next_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="host-2",
    )
    assert next_claim is not None
    second_attempt = controls.record_claim(observation_id, base_attempt_limit=3)
    assert second_attempt["attempt_number"] == 2
    assert second_attempt["effective_attempt_limit"] == 4
    with pytest.raises(RoomControlError, match="room_attempt_generation_lost"):
        controls.mark_cancelled(
            observation_id=observation_id,
            attempt_id=attempt["attempt_id"],
            expected_control_seq=retried["projection"]["control_seq"],
        )


def test_retry_remains_claimable_after_participant_cursor_advances(tmp_path):
    path, conversation_id, participant, kernel, _, first_claim = _claimed_room(tmp_path)
    controls = RoomObservationControlStore(path)
    observation_id = first_claim["observation"]["observation_id"]
    first_attempt = controls.record_claim(observation_id, base_attempt_limit=3)
    requested = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel-old-frontier",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
    )
    pending = controls.mark_cancel_pending(
        observation_id=observation_id,
        attempt_id=first_attempt["attempt_id"],
        expected_control_seq=requested["projection"]["control_seq"],
    )
    cancelled = controls.mark_cancelled(
        observation_id=observation_id,
        attempt_id=first_attempt["attempt_id"],
        expected_control_seq=pending["control_seq"],
    )

    later = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="later observation",
        client_request_id="human-later",
    )
    later_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="host-later",
    )
    assert later_claim is not None
    assert later_claim["activity"]["activity_id"] == later["activity"]["activity_id"]
    kernel.complete_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        caller_identity=f"god:session:{participant.participant_id}",
        observation_id=later_claim["observation"]["observation_id"],
        lease_token=later_claim["observation"]["lease_token"],
        client_request_id="later-noop",
        outcome_type="noop",
    )
    assert (
        kernel.get_participant_cursor(conversation_id, participant.participant_id)[
            "last_acknowledged_seq"
        ]
        == 2
    )

    controls.request_retry(
        observation_id=observation_id,
        client_action_id="retry-old-frontier",
        operator_identity="operator:local",
        expected_state="cancelled",
        expected_attempt_count=1,
        expected_control_seq=cancelled["control_seq"],
    )

    assert kernel.list_claimable_conversation_ids(max_attempts_per_observation=3) == [
        conversation_id
    ]
    retry_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="host-retry",
    )
    assert retry_claim is not None
    assert retry_claim["observation"]["observation_id"] == observation_id
    assert retry_claim["observation"]["attempt_count"] == 2


def test_exhaustion_is_durable_and_manual_retry_adds_one_attempt(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    path, _, _, _, _, claim = _claimed_room(tmp_path, now=start, lease_ttl_s=1)
    controls = RoomObservationControlStore(path)
    observation_id = claim["observation"]["observation_id"]
    controls.record_claim(observation_id, base_attempt_limit=1, now=start)

    exhausted = controls.mark_exhausted(
        observation_id=observation_id,
        base_attempt_limit=1,
        now=start + timedelta(seconds=2),
    )
    assert exhausted["control_state"] == "exhausted"
    assert exhausted["actions"]["retry"]["available"] is True
    retried = controls.request_retry(
        observation_id=observation_id,
        client_action_id="retry-exhausted",
        operator_identity="operator:local",
        expected_state="exhausted",
        expected_attempt_count=1,
        expected_control_seq=exhausted["control_seq"],
    )
    assert retried["projection"]["manual_retry_budget"] == 1
    assert controls.effective_limit(observation_id, 1) == 2


def test_manual_retry_waits_for_provider_cleanup_evidence(tmp_path):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    path, _, _, _, _, claim = _claimed_room(tmp_path, now=start, lease_ttl_s=1)
    controls = RoomObservationControlStore(path)
    observation_id = claim["observation"]["observation_id"]
    attempt = controls.record_claim(observation_id, base_attempt_limit=1, now=start)
    _bind_skill_decision(path, attempt["attempt_id"], now=start)
    controls.bind_delivery(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        lease_token=claim["observation"]["lease_token"],
        delivery_task_id="provider-cleanup-test",
        provider_session_generation=attempt["attempt_id"],
        now=start,
    )
    controls.mark_provider_ensure_started(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        delivery_generation=attempt["attempt_id"],
        now=start,
    )
    controls.mark_provider_cleanup(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        delivery_generation=attempt["attempt_id"],
        succeeded=False,
        reason_code="abort_failed",
        now=start + timedelta(seconds=1),
    )
    exhausted = controls.mark_exhausted(
        observation_id=observation_id,
        base_attempt_limit=1,
        now=start + timedelta(seconds=2),
    )

    assert exhausted["actions"]["retry"]["available"] is False
    with pytest.raises(RoomControlError, match="room_observation_retry_not_settled"):
        controls.request_retry(
            observation_id=observation_id,
            client_action_id="unsafe-retry",
            operator_identity="operator:local",
            expected_state="exhausted",
            expected_attempt_count=1,
            expected_control_seq=exhausted["control_seq"],
            now=start + timedelta(seconds=3),
        )
    controls.mark_provider_cleanup(
        observation_id=observation_id,
        attempt_id=attempt["attempt_id"],
        delivery_generation=attempt["attempt_id"],
        succeeded=True,
        reason_code="abort_confirmed",
        now=start + timedelta(seconds=4),
    )
    safe = controls.projection(observation_id)
    assert safe["actions"]["retry"]["available"] is True
    assert set(safe["current_attempt"]) == {
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


def test_conn_level_claim_and_outcome_helpers_share_the_authority_transaction(tmp_path):
    path, _, _, _, _, claim = _claimed_room(tmp_path)
    RoomObservationControlStore(path)
    observation_id = claim["observation"]["observation_id"]
    lease_token = claim["observation"]["lease_token"]

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        conn.execute("begin immediate")
        attempt = record_room_claim_attempt(
            conn, observation_id=observation_id, base_attempt_limit=3
        )
        assert (
            assert_room_outcome_allowed(
                conn,
                observation_id=observation_id,
                lease_token=lease_token,
                attempt_id=attempt["attempt_id"],
            )["attempt_id"]
            == attempt["attempt_id"]
        )
        completed = commit_room_outcome_attempt(
            conn,
            observation_id=observation_id,
            lease_token=lease_token,
            attempt_id=attempt["attempt_id"],
        )
        assert completed["state"] == "completed"
        conn.rollback()

    controls = RoomObservationControlStore(path)
    current = controls.projection(observation_id)["current_attempt"]
    assert current is not None
    assert current["state"] == "claimed"
