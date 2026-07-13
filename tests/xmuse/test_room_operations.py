from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_operations import (
    RoomRuntimeOperatorActionStore,
    build_room_operations_projection,
    runtime_incident_guard,
    runtime_recoverability,
)


def _runtime(
    *,
    state: str = "ready",
    code: str = "ready",
    ready: bool = True,
    host_state: str = "healthy",
    host_code: str = "room_host_healthy",
) -> dict:
    live = state != "stopped"
    return {
        "state": state,
        "code": code,
        "ready": ready,
        "generation": "private-generation",
        "boot_id": "private-boot",
        "services": {
            "room_runner": {
                "live": live,
                "ready": ready,
                "pids": [101] if live else [],
                "assessment_code": code,
            },
            "room_mcp": {
                "live": live,
                "ready": ready,
                "pids": [102] if live else [],
            },
        },
        "host": {
            "state": host_state,
            "code": host_code,
            "active_delivery_count": 3,
            "retained_cleanup_count": 2,
        },
    }


def _bulk_observations(db: Path, count: int) -> None:
    store = RoomTestStore(db)
    conversation = store.create_conversation("Operations Room")
    participant = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="reviewer",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    activities = []
    observations = []
    attempts = []
    for index in range(count):
        stamp = f"2026-07-11T00:00:{index % 60:02d}Z"
        activity_id = f"activity_{index}"
        observation_id = f"observation_{index}"
        attempt_id = f"attempt_{index}"
        activities.append(
            (
                activity_id,
                conversation.id,
                index + 1,
                f"cause_{index}",
                f"correlation_{index}",
                stamp,
            )
        )
        observations.append(
            (
                observation_id,
                conversation.id,
                activity_id,
                participant.participant_id,
                "exhausted",
                attempt_id,
                stamp,
                stamp,
            )
        )
        attempts.append(
            (
                attempt_id,
                conversation.id,
                observation_id,
                participant.participant_id,
                index + 1,
                stamp,
                stamp,
                stamp,
                stamp,
            )
        )
    with sqlite3.connect(db) as conn:
        conn.executemany(
            """insert into room_activities (
                activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, causation_id, correlation_id, visibility,
                audience_json, payload_json, delivery_mode, created_at
            ) values (?, ?, ?, 'message.posted', 'human', 'human:test', ?, ?,
                      'room', '{}', '{}', 'active', ?)""",
            activities,
        )
        conn.executemany(
            """insert into room_observations (
                observation_id, conversation_id, activity_id, participant_id,
                delivery_mode, status, attempt_count, control_state,
                current_attempt_id, created_at, updated_at
            ) values (?, ?, ?, ?, 'active', 'pending', 1, ?, ?, ?, ?)""",
            observations,
        )
        conn.executemany(
            """insert into room_observation_attempts (
                attempt_id, conversation_id, observation_id, participant_id,
                attempt_number, effective_attempt_limit, delivery_generation,
                state, reason_code, lease_owner, lease_token_digest,
                provider_phase, recovery_state, claimed_at, expires_at,
                created_at, updated_at
            ) values (?, ?, ?, ?, ?, 1, 1, 'expired', 'attempts_exhausted',
                      'host', 'digest', 'not_started', 'none', ?, ?, ?, ?)""",
            attempts,
        )


def test_projection_is_safe_bounded_and_counts_all_rows(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    _bulk_observations(db, 10_000)
    runtime = _runtime()

    projection = build_room_operations_projection(db, runtime)

    assert projection["schema_version"] == "room_operations_projection/v2"
    assert projection["overall"] == "attention"
    assert projection["counts"] == {
        "active_delivery": 3,
        "retained_cleanup": 2,
        "recovery_pending": 0,
        "cancel_pending": 0,
        "provider_cleanup_pending": 0,
        "exhausted": 10_000,
    }
    assert projection["incident_total"] == 10_000
    assert len(projection["incidents"]) == 20
    encoded = str(projection)
    for forbidden in (
        "private-generation",
        "private-boot",
        "lease_owner",
        "provider_session",
    ):
        assert forbidden not in encoded
    assert projection["proof_boundary"].endswith("not_authority")


def test_retired_provider_observations_do_not_create_actionable_incidents(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    _bulk_observations(db, 3)
    with sqlite3.connect(db) as conn:
        conn.execute("update participants set cli_kind = 'opencode', model = 'historical'")

    projection = build_room_operations_projection(db, _runtime())

    assert projection["counts"]["exhausted"] == 0
    assert not [item for item in projection["incidents"] if item["kind"] == "observation"]


def test_observation_incident_priority_and_bound_is_not_cleanup(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    _bulk_observations(db, 5)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """update room_observations set control_state = 'active'
                 where observation_id = 'observation_0'"""
        )
        conn.execute(
            """update room_observation_attempts
                  set reason_code = 'room_skill_catalog_drift', provider_phase = 'cleanup_pending',
                      recovery_state = 'cleanup_pending'
                where attempt_id = 'attempt_0'"""
        )
        conn.execute(
            """update room_observations set control_state = 'cancel_pending'
                 where observation_id = 'observation_1'"""
        )
        conn.execute(
            """update room_observations set control_state = 'active'
                 where observation_id in ('observation_2','observation_3')"""
        )
        conn.execute(
            """update room_observation_attempts set provider_phase = 'cleanup_pending'
                 where attempt_id = 'attempt_2'"""
        )
        conn.execute(
            """update room_observation_attempts set provider_phase = 'bound'
                 where attempt_id = 'attempt_3'"""
        )

    projection = build_room_operations_projection(db, _runtime())

    observation_incidents = [
        item for item in projection["incidents"] if item["kind"] == "observation"
    ]
    assert observation_incidents[0]["code"] == "room_skill_catalog_drift"
    assert [item["observation_id"] for item in observation_incidents] == [
        "observation_0",
        "observation_1",
        "observation_2",
        "observation_4",
    ]
    assert projection["counts"]["provider_cleanup_pending"] == 2


def test_operations_canonicalizes_mirrored_batch_cancel_and_exhausted(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    _bulk_observations(db, 2)
    with sqlite3.connect(db) as conn:
        conversation_id, participant_id = conn.execute(
            "select conversation_id, participant_id from room_observations limit 1"
        ).fetchone()
        conn.execute(
            """insert into room_observation_batches
               (batch_id, conversation_id, participant_id, correlation_id, phase,
                primary_observation_id, cutoff_seq, member_count, digest, created_at)
               values ('batch_ops', ?, ?, 'correlation_0', 'peer',
                       'observation_0', 2, 2, 'digest', '2026-07-11T00:00:00Z')""",
            (conversation_id, participant_id),
        )
        conn.executemany(
            """insert into room_observation_batch_members
               (batch_id, observation_id, ordinal, activity_id, activity_seq)
               values ('batch_ops', ?, ?, ?, ?)""",
            [
                ("observation_0", 0, "activity_0", 1),
                ("observation_1", 1, "activity_1", 2),
            ],
        )
        # The durable trigger mirrors authority facts to the secondary member.
        conn.execute(
            """update room_observations
               set control_state = 'cancel_pending', current_attempt_id = 'attempt_0'
               where observation_id = 'observation_0'"""
        )

    cancelling = build_room_operations_projection(db, _runtime())
    assert cancelling["counts"]["cancel_pending"] == 1
    assert cancelling["incident_total"] == 1
    assert [
        item["observation_id"] for item in cancelling["incidents"] if item["kind"] == "observation"
    ] == ["observation_0"]

    with sqlite3.connect(db) as conn:
        conn.execute(
            """update room_observations set control_state = 'exhausted'
               where observation_id = 'observation_0'"""
        )
    exhausted = build_room_operations_projection(db, _runtime())
    assert exhausted["counts"]["cancel_pending"] == 0
    assert exhausted["counts"]["exhausted"] == 1
    assert exhausted["incident_total"] == 1
    observation_incidents = [
        item for item in exhausted["incidents"] if item["kind"] == "observation"
    ]
    assert len(observation_incidents) == 1
    assert observation_incidents[0]["observation_id"] == "observation_0"
    assert observation_incidents[0]["code"] == "room_observation_exhausted"


def test_runtime_guard_is_opaque_and_recoverability_is_conservative() -> None:
    stopped = _runtime(state="stopped", code="room_runtime_stopped", ready=False)
    guard = runtime_incident_guard(stopped)
    assert guard.startswith("incident_")
    assert "private" not in guard
    assert runtime_recoverability(stopped)["mode"] == "start"
    assert runtime_recoverability(stopped)["available"] is True

    stale = _runtime(state="degraded", code="room_runner_heartbeat_stale", ready=False)
    assert runtime_recoverability(stale)["available"] is True
    unreadable = _runtime(state="degraded", code="room_runner_status_unreadable", ready=False)
    assert runtime_recoverability(unreadable)["available"] is True
    identity_unknown = _runtime(
        state="degraded", code="room_runner_process_identity_mismatch", ready=False
    )
    assert runtime_recoverability(identity_unknown)["available"] is False
    assert runtime_recoverability(_runtime())["available"] is False


def test_memory_attention_is_not_misreported_as_host_cleanup(tmp_path: Path) -> None:
    projection = build_room_operations_projection(
        tmp_path / "chat.db",
        _runtime(host_state="attention", host_code="room_memory_degraded"),
    )

    incident = next(item for item in projection["incidents"] if item["kind"] == "host")
    assert incident["code"] == "room_memory_degraded"
    assert incident["title"] == "Optional memory index is degraded"
    assert "Room causal delivery remains available" in incident["detail"]
    assert incident["next_action"] == "wait"


def test_component_codes_do_not_blame_healthy_mcp_for_runner_failure(
    tmp_path: Path,
) -> None:
    runtime = _runtime(state="degraded", code="room_runner_heartbeat_stale", ready=False)
    runtime["services"]["room_mcp"]["ready"] = True

    projection = build_room_operations_projection(tmp_path / "missing.db", runtime)

    assert projection["runtime"]["runner"] == {
        "state": "blocked",
        "code": "room_runner_heartbeat_stale",
    }
    assert projection["runtime"]["mcp"] == {"state": "healthy", "code": "ready"}


def test_active_delivery_alone_is_healthy(tmp_path: Path) -> None:
    runtime = _runtime()
    runtime["host"]["active_delivery_count"] = 4
    runtime["host"]["retained_cleanup_count"] = 0

    projection = build_room_operations_projection(tmp_path / "missing.db", runtime)

    assert projection["overall"] == "healthy"
    assert projection["counts"]["active_delivery"] == 4
    assert projection["incidents"] == []


def test_action_ledger_is_idempotent_and_fences_parallel_client_ids(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    RoomTestStore(db)
    ledger = RoomRuntimeOperatorActionStore(db)
    first, created = ledger.reserve(
        client_action_id="action-one",
        request_fingerprint="fingerprint-one",
        incident_guard="incident-one",
        before_state="stopped",
        before_code="room_runtime_stopped",
    )
    assert created is True
    assert first["status"] == "requested"
    assert first["action_id"].startswith("rta_")

    replay, replay_created = ledger.reserve(
        client_action_id="action-one",
        request_fingerprint="fingerprint-one",
        incident_guard="incident-one",
        before_state="stopped",
        before_code="room_runtime_stopped",
    )
    assert replay_created is False
    assert replay["action_id"] == first["action_id"]

    second, _ = ledger.reserve(
        client_action_id="action-two",
        request_fingerprint="fingerprint-two",
        incident_guard="incident-one",
        before_state="stopped",
        before_code="room_runtime_stopped",
    )
    assert second["status"] == "rejected"
    assert second["reason_code"] == "room_runtime_recovery_in_progress"

    applied = ledger.finish(
        client_action_id="action-one",
        status="applied",
        after_state="ready",
        after_code="ready",
        reason_code=None,
    )
    assert applied["status"] == "applied"
