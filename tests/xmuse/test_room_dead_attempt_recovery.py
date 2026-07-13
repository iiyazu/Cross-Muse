from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_controls import (
    RUNNER_RECOVERY_REASON,
    RoomControlError,
    RoomObservationControlStore,
    assert_room_outcome_allowed,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

NOW = datetime(2026, 7, 11, tzinfo=UTC)


def _room(tmp_path: Path) -> tuple[Path, str, Participant, RoomKernelStore]:
    db_path = tmp_path / "chat.db"
    conversation = RoomTestStore(db_path).create_conversation("Runner recovery")
    participant = ParticipantStore(db_path).add(
        conversation_id=conversation.id,
        role="reviewer",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(db_path)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="Recover this observation.",
        client_request_id="human-recovery-1",
    )
    return db_path, conversation.id, participant, kernel


def _claim(
    kernel: RoomKernelStore,
    conversation_id: str,
    participant: Participant,
    *,
    generation: str | None = "generation-a",
    boot_id: str | None = "boot-a",
    base_attempt_limit: int = 3,
    now: datetime = NOW,
) -> dict:
    claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner=f"owner:{generation}:{boot_id}",
        lease_ttl_s=300,
        base_attempt_limit=base_attempt_limit,
        runner_generation=generation,
        runner_boot_id=boot_id,
        now=now,
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
        god_session_id="god-a",
        provider_session_id="thread-a",
        now=NOW,
    )


def _attempt_row(db_path: Path, attempt_id: str) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "select * from room_observation_attempts where attempt_id = ?",
            (attempt_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _frontend_event_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("select count(*) from chat_frontend_events").fetchone()[0])


def _assert_old_lease_lost(
    db_path: Path,
    *,
    observation_id: str,
    attempt_id: str,
    lease_token: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(RoomControlError, match="room_observation_lease_lost"):
            assert_room_outcome_allowed(
                conn,
                observation_id=observation_id,
                attempt_id=attempt_id,
                lease_token=lease_token,
            )


def test_claim_records_bounded_runner_identity_and_keeps_it_internal(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    claim = _claim(kernel, conversation_id, participant)
    attempt_id = claim["attempt"]["attempt_id"]

    row = _attempt_row(db_path, attempt_id)
    assert row["runner_generation"] == "generation-a"
    assert row["runner_boot_id"] == "boot-a"
    assert row["recovery_state"] == "none"
    assert "runner_generation" not in claim["attempt"]
    assert "runner_boot_id" not in claim["attempt"]
    assert "lease_owner" not in claim["attempt"]

    other_path, other_conversation, other_participant, other_kernel = _room(tmp_path / "bad")
    with pytest.raises(RoomControlError, match="room_runner_attempt_identity_incomplete"):
        other_kernel.claim_next_observation(
            conversation_id=other_conversation,
            participant_id=other_participant.participant_id,
            lease_owner="owner-bad",
            runner_generation="generation-only",
            now=NOW,
        )
    observation = RoomKernelStore(other_path).list_observations(other_conversation)[0]
    assert observation["status"] == "pending"
    assert observation["attempt_count"] == 0


def test_fence_skips_same_boot_and_null_legacy_attempts(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path / "owned")
    _claim(kernel, conversation_id, participant)
    controls = RoomObservationControlStore(db_path)

    same = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-a",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )
    assert same["fenced_count"] == 0

    legacy_path, legacy_conversation, legacy_participant, legacy_kernel = _room(tmp_path / "legacy")
    legacy = _claim(
        legacy_kernel,
        legacy_conversation,
        legacy_participant,
        generation=None,
        boot_id=None,
    )
    legacy_controls = RoomObservationControlStore(legacy_path)
    result = legacy_controls.fence_prior_runner_attempts(
        current_runner_generation="generation-b",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )
    assert result["fenced_count"] == 0
    current = legacy_kernel.get_observation(legacy["observation"]["observation_id"])
    assert current["lease_token"] == legacy["observation"]["lease_token"]


def test_safe_prior_boot_is_reopened_immediately_and_replay_adds_no_event(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant)
    observation_id = first["observation"]["observation_id"]
    attempt_id = first["attempt"]["attempt_id"]
    old_token = first["observation"]["lease_token"]
    controls = RoomObservationControlStore(db_path)
    before_events = _frontend_event_count(db_path)

    fenced = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )

    assert fenced["schema_version"] == "room_runner_recovery_fence/v1"
    assert fenced["fenced_count"] == 1
    assert fenced["cleanup_pending_count"] == 0
    assert fenced["recovered_count"] == 1
    assert fenced["pending_count"] == 1
    assert fenced["exhausted_count"] == 0
    assert fenced["cancel_pending_count"] == 0
    assert set(fenced["event_cursors"]) == {observation_id}
    current = kernel.get_observation(observation_id)
    assert current["status"] == "pending"
    assert current["lease_token"] is None
    attempt = _attempt_row(db_path, attempt_id)
    assert attempt["state"] == "expired"
    assert attempt["reason_code"] == RUNNER_RECOVERY_REASON
    assert attempt["recovery_state"] == "recovered"
    assert attempt["recovery_reason_code"] == RUNNER_RECOVERY_REASON
    assert attempt["recovery_completed_at"] is not None
    _assert_old_lease_lost(
        db_path,
        observation_id=observation_id,
        attempt_id=attempt_id,
        lease_token=old_token,
    )

    events_after_fence = _frontend_event_count(db_path)
    assert events_after_fence == before_events + 1
    replay = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=2),
    )
    assert replay["fenced_count"] == 0
    assert _frontend_event_count(db_path) == events_after_fence

    second = _claim(
        kernel,
        conversation_id,
        participant,
        generation="generation-a",
        boot_id="boot-b",
        now=NOW + timedelta(seconds=2),
    )
    assert second["attempt"]["attempt_number"] == 2
    assert second["attempt"]["attempt_id"] != attempt_id


def test_unsafe_provider_cleanup_gates_finalize_and_then_reopens(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant)
    controls = RoomObservationControlStore(db_path)
    _bind_provider(db_path, controls, first)
    observation_id = first["observation"]["observation_id"]
    attempt_id = first["attempt"]["attempt_id"]
    old_token = first["observation"]["lease_token"]

    result = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )
    assert result["cleanup_pending_count"] == 1
    assert result["recovered_count"] == 0
    fenced_observation = kernel.get_observation(observation_id)
    assert fenced_observation["lease_token"] != old_token
    assert fenced_observation["expires_at"] == "2026-07-11T00:00:01.000000Z"
    _assert_old_lease_lost(
        db_path,
        observation_id=observation_id,
        attempt_id=attempt_id,
        lease_token=old_token,
    )

    pending = controls.list_pending_runner_recoveries()
    assert len(pending) == 1
    binding = pending[0]["reconcile_binding"]
    assert binding["attempt_id"] == attempt_id
    assert binding["provider_phase"] == "cleanup_pending"
    assert binding["recovery_state"] == "cleanup_pending"
    assert "runner_generation" not in binding
    assert "runner_boot_id" not in binding
    assert "lease_owner" not in binding
    events_after_first_fence = _frontend_event_count(db_path)
    restarted_again = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-c",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=2),
    )
    assert restarted_again["fenced_count"] == 0
    assert len(controls.list_pending_runner_recoveries()) == 1
    assert _frontend_event_count(db_path) == events_after_first_fence
    with pytest.raises(RoomControlError, match="room_runner_recovery_cleanup_unproven"):
        controls.finalize_runner_recovery(
            observation_id=observation_id,
            attempt_id=attempt_id,
            base_attempt_limit=3,
            now=NOW + timedelta(seconds=2),
        )

    controls.mark_provider_cleanup(
        observation_id=observation_id,
        attempt_id=attempt_id,
        delivery_generation=attempt_id,
        succeeded=True,
        reason_code="runner_recovery_abort_confirmed",
        now=NOW + timedelta(seconds=3),
    )
    before_finalize_events = _frontend_event_count(db_path)
    finalized = controls.finalize_runner_recovery(
        observation_id=observation_id,
        attempt_id=attempt_id,
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=4),
    )
    assert finalized["control_state"] == "active"
    assert kernel.get_observation(observation_id)["status"] == "pending"
    assert controls.list_pending_runner_recoveries() == []
    assert _attempt_row(db_path, attempt_id)["recovery_state"] == "recovered"

    replay = controls.finalize_runner_recovery(
        observation_id=observation_id,
        attempt_id=attempt_id,
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=5),
    )
    assert replay["control_state"] == "active"
    assert _frontend_event_count(db_path) == before_finalize_events + 1


def test_completed_outcome_wins_before_runner_fence(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant)
    observation_id = first["observation"]["observation_id"]
    attempt_id = first["attempt"]["attempt_id"]
    kernel.complete_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        caller_identity=f"god:session:{participant.participant_id}",
        observation_id=observation_id,
        lease_token=first["observation"]["lease_token"],
        client_request_id="completion-wins",
        outcome_type="noop",
        now=NOW + timedelta(milliseconds=500),
    )
    controls = RoomObservationControlStore(db_path)
    before_events = _frontend_event_count(db_path)

    result = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )

    assert result["fenced_count"] == 0
    assert kernel.get_observation(observation_id)["status"] == "completed"
    attempt = _attempt_row(db_path, attempt_id)
    assert attempt["state"] == "completed"
    assert attempt["recovery_state"] == "none"
    assert _frontend_event_count(db_path) == before_events


def test_completion_and_runner_fence_serialize_to_exactly_one_winner(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant)
    observation_id = first["observation"]["observation_id"]
    attempt_id = first["attempt"]["attempt_id"]
    old_token = first["observation"]["lease_token"]
    controls = RoomObservationControlStore(db_path)
    barrier = Barrier(2)

    def complete() -> str:
        barrier.wait()
        try:
            kernel.complete_observation(
                conversation_id=conversation_id,
                participant_id=participant.participant_id,
                caller_identity=f"god:session:{participant.participant_id}",
                observation_id=observation_id,
                lease_token=old_token,
                client_request_id="completion-fence-race",
                outcome_type="noop",
                now=NOW + timedelta(seconds=1),
            )
        except ValueError as exc:
            return str(exc)
        return "completed"

    def fence() -> dict:
        barrier.wait()
        return controls.fence_prior_runner_attempts(
            current_runner_generation="generation-a",
            current_runner_boot_id="boot-b",
            base_attempt_limit=3,
            now=NOW + timedelta(seconds=1),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion_result = executor.submit(complete)
        fence_result = executor.submit(fence)
        completed = completion_result.result(timeout=10)
        fenced = fence_result.result(timeout=10)

    observation = kernel.get_observation(observation_id)
    attempt = _attempt_row(db_path, attempt_id)
    if completed == "completed":
        assert fenced["fenced_count"] == 0
        assert observation["status"] == "completed"
        assert attempt["state"] == "completed"
        assert attempt["recovery_state"] == "none"
    else:
        assert completed == "room_observation_lease_lost"
        assert fenced["fenced_count"] == 1
        assert observation["status"] == "pending"
        assert attempt["state"] == "expired"
        assert attempt["recovery_state"] == "recovered"


def test_last_automatic_attempt_recovers_to_exhausted(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant, base_attempt_limit=1)
    controls = RoomObservationControlStore(db_path)

    result = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=1,
        now=NOW + timedelta(seconds=1),
    )

    assert result["exhausted_count"] == 1
    projection = controls.projection(first["observation"]["observation_id"])
    assert projection["control_state"] == "exhausted"
    assert projection["actions"]["retry"]["available"] is True
    assert kernel.get_observation(first["observation"]["observation_id"])["status"] == "pending"
    assert (
        kernel.claim_next_observation(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            lease_owner="owner-b",
            base_attempt_limit=1,
            runner_generation="generation-a",
            runner_boot_id="boot-b",
            now=NOW + timedelta(seconds=2),
        )
        is None
    )


def test_cancelled_recovery_closes_without_automatic_reopen(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant)
    controls = RoomObservationControlStore(db_path)
    _bind_provider(db_path, controls, first)
    observation_id = first["observation"]["observation_id"]
    attempt_id = first["attempt"]["attempt_id"]
    requested = controls.request_cancel(
        observation_id=observation_id,
        client_action_id="cancel-before-runner-death",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
        now=NOW + timedelta(seconds=1),
    )

    result = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=2),
    )
    assert result["cancel_pending_count"] == 1
    assert result["cleanup_pending_count"] == 1
    assert controls.list_pending_runner_recoveries() == []
    controls.mark_provider_cleanup(
        observation_id=observation_id,
        attempt_id=attempt_id,
        delivery_generation=attempt_id,
        succeeded=True,
        reason_code="runner_recovery_cancel_abort_confirmed",
        now=NOW + timedelta(seconds=3),
    )
    cancelled = controls.mark_cancelled(
        observation_id=observation_id,
        attempt_id=attempt_id,
        expected_control_seq=requested["projection"]["control_seq"],
        reason_code="runner_reconciled_provider_abort",
        now=NOW + timedelta(seconds=4),
    )

    assert cancelled["control_state"] == "cancelled"
    attempt = _attempt_row(db_path, attempt_id)
    assert attempt["state"] == "cancelled"
    assert attempt["recovery_state"] == "recovered"
    assert attempt["recovery_completed_at"] is not None
    assert (
        kernel.claim_next_observation(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            lease_owner="owner-b",
            runner_generation="generation-a",
            runner_boot_id="boot-b",
            now=NOW + timedelta(seconds=5),
        )
        is None
    )


def test_offline_restore_closes_pending_runner_recovery(tmp_path: Path) -> None:
    db_path, conversation_id, participant, kernel = _room(tmp_path)
    first = _claim(kernel, conversation_id, participant)
    controls = RoomObservationControlStore(db_path)
    _bind_provider(db_path, controls, first)
    observation_id = first["observation"]["observation_id"]
    attempt_id = first["attempt"]["attempt_id"]
    controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
        now=NOW + timedelta(seconds=1),
    )
    assert _attempt_row(db_path, attempt_id)["recovery_state"] == "cleanup_pending"

    restored = controls.fence_restored_runtime_generation(
        operation_id="restore-after-runner-loss",
        now=NOW + timedelta(seconds=2),
    )

    assert restored["affected_observation_count"] == 1
    attempt = _attempt_row(db_path, attempt_id)
    assert attempt["provider_phase"] == "cleanup_succeeded"
    assert attempt["recovery_state"] == "recovered"
    assert attempt["recovery_completed_at"] is not None
    assert kernel.get_observation(observation_id)["status"] == "pending"
