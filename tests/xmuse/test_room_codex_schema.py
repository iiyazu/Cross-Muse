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
