from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse_core.chat.room_codex_bridge import (
    RoomCodexBridgeError,
    RoomCodexBridgeStore,
    opaque_guard,
)
from xmuse_core.chat.room_database import RoomDatabase


def _seed(path: Path, participant_ids: tuple[str, ...] = ("participant-1",)) -> None:
    RoomDatabase(path).initialize()
    with RoomDatabase(path).connect() as conn:
        conn.execute("begin immediate")
        conn.execute("insert into conversations values ('room-1', 'Room', 'now')")
        for participant_id in participant_ids:
            conn.execute(
                """insert into participants
                   (participant_id, conversation_id, role, display_name, cli_kind, model,
                    status, created_at) values (?, 'room-1', 'reviewer', 'Reviewer',
                    'codex', 'gpt-test', 'active', 'now')""",
                (participant_id,),
            )
        conn.commit()


def _ready(
    store: RoomCodexBridgeStore, participant_id: str = "participant-1"
) -> tuple[str, str, str]:
    session = opaque_guard(participant_id, "session")
    goal = opaque_guard(participant_id, "goal")
    settings = opaque_guard(participant_id, "settings")
    store.begin_reconcile(
        conversation_id="room-1",
        participant_id=participant_id,
        session_guard=session,
    )
    store.apply_native_snapshot(
        conversation_id="room-1",
        participant_id=participant_id,
        expected_session_guard=session,
        state="accepting",
        goal_guard=goal,
        settings_guard=settings,
        active_turn_guard=None,
    )
    return session, goal, settings


def _request(
    store: RoomCodexBridgeStore,
    *,
    client_action_id: str,
    session: str,
    goal: str,
    settings: str,
    participant_id: str = "participant-1",
    safe_request: dict[str, object] | None = None,
) -> tuple[dict[str, object], bool]:
    return store.request_action(
        conversation_id="room-1",
        participant_id=participant_id,
        capability_id="goal_get",
        safe_request=safe_request or {},
        client_action_id=client_action_id,
        expected_session_guard=session,
        expected_goal_guard=goal,
        expected_settings_guard=settings,
    )


def test_delivery_is_closed_until_native_snapshot_is_reconciled(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session = opaque_guard("session")

    assert store.participant_accepts_delivery("participant-1") is False
    hold = store.begin_reconcile(
        conversation_id="room-1",
        participant_id="participant-1",
        session_guard=session,
    )
    assert hold["state"] == "reconciling"
    assert store.participant_accepts_delivery("participant-1") is False
    with pytest.raises(RoomCodexBridgeError) as error:
        store.request_action(
            conversation_id="room-1",
            participant_id="participant-1",
            capability_id="goal_get",
            safe_request={},
            client_action_id="client-1",
            expected_session_guard=session,
        )
    assert error.value.code == "codex_native_session_conflict"


def test_action_request_is_atomic_guarded_and_exactly_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)

    first, created = _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    replay, replay_created = _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    assert created is True and replay_created is False
    assert replay == first
    assert first["control_seq"] == 1 and "safe_request" not in first
    with RoomDatabase(path).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_codex_bridge_actions").fetchone()[0] == 1
        assert (
            conn.execute(
                """select count(*) from chat_frontend_events
               where source_authority = 'chat.db:room_codex_bridge'"""
            ).fetchone()[0]
            == 3
        )

    with pytest.raises(RoomCodexBridgeError) as conflict:
        _request(
            store,
            client_action_id="client-1",
            session=session,
            goal=goal,
            settings=settings,
            safe_request={"changed": True},
        )
    assert conflict.value.code == "codex_native_action_idempotency_conflict"


def test_stale_opaque_guard_rejects_before_action_or_event(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    with RoomDatabase(path).connect(readonly=True) as conn:
        before = conn.execute("select count(*) from chat_frontend_events").fetchone()[0]

    with pytest.raises(RoomCodexBridgeError) as error:
        _request(
            store,
            client_action_id="client-stale",
            session=session,
            goal=opaque_guard("stale"),
            settings=settings,
        )
    assert error.value.code == "codex_native_goal_guard_conflict"
    with RoomDatabase(path).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_codex_bridge_actions").fetchone()[0] == 0
        assert conn.execute("select count(*) from chat_frontend_events").fetchone()[0] == before


def test_runner_claim_serializes_actions_per_participant(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    _request(
        store,
        client_action_id="client-2",
        session=session,
        goal=goal,
        settings=settings,
    )

    first = store.claim_next_action(runner_generation="runner-1")
    assert first is not None and first["control_seq"] == 1
    assert first["safe_request"] == {}
    assert store.claim_next_action(runner_generation="runner-1") is None
    completed = store.complete_action(
        action_id=str(first["action_id"]),
        runner_generation="runner-1",
        status="applied",
        reason_code=None,
        ack_summary={"native_method": "thread/goal/get", "acknowledged": True},
    )
    assert completed["status"] == "applied"
    second = store.claim_next_action(runner_generation="runner-1")
    assert second is not None and second["control_seq"] == 2


def test_old_runner_cannot_complete_new_generation_claim(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    action = store.claim_next_action(runner_generation="runner-new")
    assert action is not None

    with pytest.raises(RoomCodexBridgeError) as error:
        store.complete_action(
            action_id=str(action["action_id"]),
            runner_generation="runner-old",
            status="applied",
            reason_code=None,
        )
    assert error.value.code == "codex_native_action_claim_lost"
    with RoomDatabase(path).connect(readonly=True) as conn:
        assert (
            conn.execute("select status from room_codex_bridge_actions").fetchone()[0] == "applying"
        )


def test_ack_summary_rejects_provider_text_and_private_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    action = store.claim_next_action(runner_generation="runner")
    assert action is not None

    with pytest.raises(RoomCodexBridgeError) as error:
        store.complete_action(
            action_id=str(action["action_id"]),
            runner_generation="runner",
            status="applied",
            reason_code=None,
            ack_summary={"provider_output": "secret", "thread_id": "private"},
        )
    assert error.value.code == "codex_native_ack_summary_invalid"
    with sqlite3.connect(path) as conn:
        serialized = "\n".join(str(value) for row in conn.iterdump() for value in (row,))
    assert "secret" not in serialized and "thread_id" not in serialized
