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
    assert "execution_stage" not in first and "failure_stage" not in first
    with RoomDatabase(path).connect(readonly=True) as conn:
        assert (
            conn.execute(
                "select execution_stage from room_codex_bridge_actions where action_id = ?",
                (first["action_id"],),
            ).fetchone()[0]
            == "session_preparing"
        )
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


def test_participant_control_seq_wins_over_non_monotonic_wall_clock(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    first, _ = _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    second, _ = _request(
        store,
        client_action_id="client-2",
        session=session,
        goal=goal,
        settings=settings,
    )
    with RoomDatabase(path).connect() as conn:
        conn.execute("begin immediate")
        conn.execute(
            "update room_codex_bridge_actions set requested_at = 'later' where action_id = ?",
            (first["action_id"],),
        )
        conn.execute(
            "update room_codex_bridge_actions set requested_at = 'earlier' where action_id = ?",
            (second["action_id"],),
        )
        conn.commit()

    claimed = store.claim_next_action(runner_generation="runner-1")

    assert claimed is not None
    assert claimed["action_id"] == first["action_id"]
    assert claimed["control_seq"] == 1


@pytest.mark.parametrize(
    ("capability_id", "missing", "expected_code"),
    [
        ("goal_pause", "goal", "codex_native_goal_guard_required"),
        ("settings_update", "settings", "codex_native_settings_guard_required"),
        ("turn_steer", "turn", "codex_native_turn_guard_required"),
        ("turn_interrupt", "turn", "codex_native_turn_guard_required"),
    ],
)
def test_mutating_action_requires_its_authoritative_native_guard(
    tmp_path: Path,
    capability_id: str,
    missing: str,
    expected_code: str,
) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    turn = opaque_guard("participant-1", "turn")
    store.apply_native_snapshot(
        conversation_id="room-1",
        participant_id="participant-1",
        expected_session_guard=session,
        state="turn_active" if capability_id.startswith("turn_") else "accepting",
        goal_guard=goal,
        settings_guard=settings,
        active_turn_guard=turn if capability_id.startswith("turn_") else None,
    )
    kwargs: dict[str, object] = {
        "conversation_id": "room-1",
        "participant_id": "participant-1",
        "capability_id": capability_id,
        "safe_request": {"text": "focus"}
        if capability_id == "turn_steer"
        else ({"model": "gpt-test"} if capability_id == "settings_update" else {}),
        "client_action_id": f"missing-{missing}",
        "expected_session_guard": session,
        "expected_goal_guard": None if missing == "goal" else goal,
        "expected_settings_guard": None if missing == "settings" else settings,
        "expected_turn_guard": None if missing == "turn" else turn,
    }

    with pytest.raises(RoomCodexBridgeError) as error:
        store.request_action(**kwargs)  # type: ignore[arg-type]

    assert error.value.code == expected_code
    with RoomDatabase(path).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_codex_bridge_actions").fetchone()[0] == 0


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


@pytest.mark.parametrize(
    "stage",
    ["session_preparing", "snapshot_proving", "guards_proving"],
)
def test_restart_requeues_pre_dispatch_action(tmp_path: Path, stage: str) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    requested, _ = _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    claimed = store.claim_next_action(runner_generation="runner-dead")
    assert claimed is not None
    if stage in {"snapshot_proving", "guards_proving"}:
        store.advance_action_stage(
            action_id=str(claimed["action_id"]),
            runner_generation="runner-dead",
            stage="snapshot_proving",
        )
    if stage == "guards_proving":
        store.advance_action_stage(
            action_id=str(claimed["action_id"]),
            runner_generation="runner-dead",
            stage="guards_proving",
        )

    assert store.fence_interrupted_actions() == 1

    with RoomDatabase(path).connect(readonly=True) as conn:
        row = conn.execute(
            """select status, execution_stage, failure_stage, runner_generation,
                      applying_at, completed_at
               from room_codex_bridge_actions where action_id = ?""",
            (requested["action_id"],),
        ).fetchone()
    assert tuple(row) == ("requested", "queued", None, None, None, None)
    reclaimed = store.claim_next_action(runner_generation="runner-new")
    assert reclaimed is not None and reclaimed["action_id"] == requested["action_id"]


def test_restart_fences_unknown_dispatching_result_without_replay(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _seed(path)
    store = RoomCodexBridgeStore(path)
    session, goal, settings = _ready(store)
    first, _ = _request(
        store,
        client_action_id="client-1",
        session=session,
        goal=goal,
        settings=settings,
    )
    second, _ = _request(
        store,
        client_action_id="client-2",
        session=session,
        goal=goal,
        settings=settings,
    )
    claimed = store.claim_next_action(runner_generation="runner-dead")
    assert claimed is not None and claimed["action_id"] == first["action_id"]
    for stage in ("snapshot_proving", "guards_proving", "dispatching"):
        store.advance_action_stage(
            action_id=str(claimed["action_id"]),
            runner_generation="runner-dead",
            stage=stage,  # type: ignore[arg-type]
        )

    assert store.fence_interrupted_actions() == 1

    with RoomDatabase(path).connect(readonly=True) as conn:
        rows = conn.execute(
            """select action_id, status, reason_code, execution_stage, failure_stage
               from room_codex_bridge_actions """
            "order by control_seq"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        (
            first["action_id"],
            "failed",
            "codex_native_action_result_unknown",
            "completed",
            "dispatching",
        ),
        (second["action_id"], "requested", None, "queued", None),
    ]
    next_action = store.claim_next_action(runner_generation="runner-new")
    assert next_action is not None and next_action["action_id"] == second["action_id"]


def test_action_stage_progression_is_ordered_and_idempotent(tmp_path: Path) -> None:
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

    with pytest.raises(RoomCodexBridgeError) as skipped:
        store.advance_action_stage(
            action_id=str(action["action_id"]),
            runner_generation="runner",
            stage="guards_proving",
        )
    assert skipped.value.code == "codex_native_action_stage_conflict"
    for stage in ("snapshot_proving", "guards_proving", "dispatching"):
        store.advance_action_stage(
            action_id=str(action["action_id"]),
            runner_generation="runner",
            stage=stage,  # type: ignore[arg-type]
        )
        store.advance_action_stage(
            action_id=str(action["action_id"]),
            runner_generation="runner",
            stage=stage,  # type: ignore[arg-type]
        )

    completed = store.complete_action(
        action_id=str(action["action_id"]),
        runner_generation="runner",
        status="applied",
        reason_code=None,
        ack_summary={"native_method": "thread/goal/get", "acknowledged": True},
    )
    assert completed["status"] == "applied"
    assert "execution_stage" not in completed and "failure_stage" not in completed
    with RoomDatabase(path).connect(readonly=True) as conn:
        row = conn.execute(
            """select execution_stage, failure_stage
               from room_codex_bridge_actions where action_id = ?""",
            (action["action_id"],),
        ).fetchone()
    assert tuple(row) == ("completed", None)


def test_failed_action_records_only_its_safe_failure_stage(tmp_path: Path) -> None:
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
    store.advance_action_stage(
        action_id=str(action["action_id"]),
        runner_generation="runner",
        stage="snapshot_proving",
    )

    completed = store.complete_action(
        action_id=str(action["action_id"]),
        runner_generation="runner",
        status="failed",
        reason_code="codex_native_action_snapshot_failed",
    )

    assert completed["status"] == "failed"
    assert "failure_stage" not in completed
    with RoomDatabase(path).connect(readonly=True) as conn:
        row = conn.execute(
            """select execution_stage, failure_stage, reason_code
               from room_codex_bridge_actions where action_id = ?""",
            (action["action_id"],),
        ).fetchone()
    assert tuple(row) == (
        "completed",
        "snapshot_proving",
        "codex_native_action_snapshot_failed",
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
