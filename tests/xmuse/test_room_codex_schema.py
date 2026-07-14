from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse_core.chat.room_database import RoomDatabase


def _seed_participant(path: Path) -> None:
    with RoomDatabase(path).connect() as conn:
        conn.execute("begin immediate")
        conn.execute("insert into conversations values ('room-1', 'Room', 'now')")
        conn.execute(
            """insert into participants
               (participant_id, conversation_id, role, display_name, cli_kind, model,
                status, created_at)
               values ('participant-1', 'room-1', 'reviewer', 'Reviewer', 'codex',
                       'gpt-test', 'active', 'now')"""
        )
        conn.commit()


def test_codex_bridge_schema_enforces_participant_local_action_identity(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    RoomDatabase(path).initialize()
    _seed_participant(path)
    with RoomDatabase(path).connect() as conn:
        conn.execute(
            """insert into room_codex_delivery_holds
               (participant_id, conversation_id, hold_revision, next_control_seq, state,
                session_guard, created_at, updated_at)
               values ('participant-1', 'room-1', 1, 1, 'reconciling', 'session_guard',
                       'now', 'now')"""
        )
        values = (
            "action-1",
            "room-1",
            "participant-1",
            1,
            "client-1",
            "operator:local",
            "fingerprint",
            "goal_get",
            "session_guard",
            "{}",
            "requested",
            "now",
            "now",
        )
        conn.execute(
            """insert into room_codex_bridge_actions
               (action_id, conversation_id, participant_id, control_seq, client_action_id,
                operator_identity, request_fingerprint, capability_id,
                expected_session_guard, request_json, status, requested_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """insert into room_codex_bridge_actions
                   (action_id, conversation_id, participant_id, control_seq,
                    client_action_id, operator_identity, request_fingerprint,
                    capability_id, expected_session_guard, request_json, status,
                    requested_at, updated_at)
                   values ('action-2', 'room-1', 'participant-1', 2, 'client-1',
                           'operator:local', 'different', 'goal_get', 'session_guard',
                           '{}', 'requested', 'now', 'now')"""
            )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("state", "invented"),
        ("hold_revision", -1),
        ("next_control_seq", -1),
    ],
)
def test_codex_delivery_hold_rejects_invalid_state_and_revision(
    tmp_path: Path, column: str, value: object
) -> None:
    path = tmp_path / "chat.db"
    RoomDatabase(path).initialize()
    _seed_participant(path)
    row = {
        "hold_revision": 0,
        "next_control_seq": 0,
        "state": "reconciling",
    }
    row[column] = value
    with RoomDatabase(path).connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """insert into room_codex_delivery_holds
               (participant_id, conversation_id, hold_revision, next_control_seq, state,
                created_at, updated_at) values (?, ?, ?, ?, ?, 'now', 'now')""",
            (
                "participant-1",
                "room-1",
                row["hold_revision"],
                row["next_control_seq"],
                row["state"],
            ),
        )


def test_codex_action_stage_constraints_reject_unknown_values(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    RoomDatabase(path).initialize()
    _seed_participant(path)
    with RoomDatabase(path).connect() as conn:
        conn.execute(
            """insert into room_codex_delivery_holds
               (participant_id, conversation_id, hold_revision, next_control_seq, state,
                session_guard, created_at, updated_at)
               values ('participant-1', 'room-1', 1, 1, 'reconciling', 'session_guard',
                       'now', 'now')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """insert into room_codex_bridge_actions
                   (action_id, conversation_id, participant_id, control_seq,
                    client_action_id, operator_identity, request_fingerprint,
                    capability_id, expected_session_guard, request_json, status,
                    execution_stage, requested_at, updated_at)
                   values ('action-1', 'room-1', 'participant-1', 1, 'client-1',
                           'operator:local', 'fingerprint', 'goal_get', 'session_guard',
                           '{}', 'requested', 'invented', 'now', 'now')"""
            )


def test_codex_action_stage_migration_is_conservative(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    RoomDatabase(path).initialize()
    _seed_participant(path)
    with RoomDatabase(path).connect() as conn:
        conn.execute("drop table room_codex_bridge_actions")
        conn.execute(
            """create table room_codex_bridge_actions (
                action_id text primary key,
                conversation_id text not null references conversations(id),
                participant_id text not null references participants(participant_id),
                control_seq integer not null check (control_seq > 0),
                client_action_id text not null,
                operator_identity text not null,
                request_fingerprint text not null,
                capability_id text not null,
                expected_session_guard text not null,
                expected_goal_guard text,
                expected_settings_guard text,
                expected_turn_guard text,
                request_json text not null,
                status text not null,
                reason_code text,
                ack_summary_json text,
                runner_generation text,
                requested_at text not null,
                applying_at text,
                completed_at text,
                updated_at text not null,
                unique(participant_id, control_seq),
                unique(participant_id, operator_identity, client_action_id)
            )"""
        )
        for control_seq, status in enumerate(
            ("requested", "applying", "applied", "rejected", "failed"), start=1
        ):
            conn.execute(
                """insert into room_codex_bridge_actions
                   (action_id, conversation_id, participant_id, control_seq,
                    client_action_id, operator_identity, request_fingerprint,
                    capability_id, expected_session_guard, request_json, status,
                    requested_at, updated_at)
                   values (?, 'room-1', 'participant-1', ?, ?, 'operator:local', ?,
                           'goal_get', 'session_guard', '{}', ?, 'now', 'now')""",
                (
                    f"action-{control_seq}",
                    control_seq,
                    f"client-{control_seq}",
                    f"fingerprint-{control_seq}",
                    status,
                ),
            )
    RoomDatabase(path).initialize()
    with RoomDatabase(path).connect(readonly=True) as conn:
        rows = conn.execute(
            """select status, execution_stage, failure_stage
               from room_codex_bridge_actions order by control_seq"""
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("requested", "queued", None),
        ("applying", "dispatching", None),
        ("applied", "completed", None),
        ("rejected", "completed", None),
        ("failed", "completed", None),
    ]
