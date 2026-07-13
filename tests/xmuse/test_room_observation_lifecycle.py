from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_kernel import RoomKernelStore


def _room(tmp_path, count=3):
    path = tmp_path / "chat.db"
    chat = RoomTestStore(path)
    conversation = chat.create_conversation("room")
    participants = ParticipantStore(path)
    agents = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{i}",
            display_name=f"Agent {i}",
            cli_kind="codex",
            model="gpt-5",
        )
        for i in range(count)
    ]
    return path, conversation.id, agents


def _post(store, conversation_id, key="human"):
    return store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content=key,
        client_request_id=key,
    )


def _claim(store, conversation_id, participant, owner="worker", now=None):
    return store.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner=owner,
        now=now,
    )


def _complete(
    store, conversation_id, participant, claim, request, outcome="noop", payload=None, now=None
):
    return store.complete_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        caller_identity=f"god:session:{participant.participant_id}",
        observation_id=claim["observation"]["observation_id"],
        lease_token=claim["observation"]["lease_token"],
        client_request_id=request,
        outcome_type=outcome,
        outcome_payload=payload,
        now=now,
    )


def _counts(path, conversation_id):
    with sqlite3.connect(path) as conn:
        return {
            table: conn.execute(
                f"select count(*) from {table} where conversation_id = ?", (conversation_id,)
            ).fetchone()[0]
            for table in (
                "messages",
                "room_activities",
                "room_observations",
                "chat_request_log",
                "chat_frontend_events",
                "proposals",
            )
        }


def test_all_active_participants_complete_silently(tmp_path):
    path, conversation_id, agents = _room(tmp_path)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    for index, participant in enumerate(agents):
        claim = _claim(store, conversation_id, participant)
        _complete(
            store,
            conversation_id,
            participant,
            claim,
            f"done-{index}",
            "defer" if index == 2 else "noop",
            {"wake_condition": "later"} if index == 2 else None,
        )
    assert all(item["status"] == "completed" for item in store.list_observations(conversation_id))
    assert all(
        item["last_acknowledged_seq"] == 1
        for item in store.list_participant_cursors(conversation_id)
    )
    counts = _counts(path, conversation_id)
    assert counts["messages"] == 1
    assert counts["chat_frontend_events"] == 7
    assert counts["proposals"] == 0


def test_claim_is_owner_idempotent_and_exclusive(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 1)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    first = _claim(store, conversation_id, agents[0], "one")
    assert _claim(store, conversation_id, agents[0], "one") == first
    assert _claim(store, conversation_id, agents[0], "two") is None
    assert first["observation"]["attempt_count"] == 1


def test_stopped_participant_cannot_claim_active_observation(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 1)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    ParticipantStore(path).update_status(agents[0].participant_id, "stopped")
    with pytest.raises(ValueError, match="room_participant_not_active"):
        _claim(store, conversation_id, agents[0])
    observation = store.list_observations(conversation_id)[0]
    assert observation["status"] == "pending"
    assert observation["attempt_count"] == 0
    assert (
        store.get_participant_cursor(conversation_id, agents[0].participant_id)[
            "last_acknowledged_seq"
        ]
        == 0
    )


def test_expiry_reclaims_one_row_and_old_token_is_lost(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 1)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first = _claim(store, conversation_id, agents[0], now=start)
    expiry = start + timedelta(seconds=120)
    second = _claim(
        store,
        conversation_id,
        agents[0],
        "new",
        now=expiry + timedelta(milliseconds=500),
    )
    assert second["observation"]["observation_id"] == first["observation"]["observation_id"]
    assert second["observation"]["lease_token"] != first["observation"]["lease_token"]
    assert second["observation"]["attempt_count"] == 2
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        store.complete_observation(
            conversation_id=conversation_id,
            participant_id=agents[0].participant_id,
            caller_identity=f"god:s:{agents[0].participant_id}",
            observation_id=first["observation"]["observation_id"],
            lease_token=first["observation"]["lease_token"],
            client_request_id="old",
            outcome_type="noop",
            now=expiry + timedelta(seconds=1),
        )
    _complete(
        store,
        conversation_id,
        agents[0],
        second,
        "new",
        now=expiry + timedelta(seconds=1),
    )
    assert len(store.list_observations(conversation_id)) == 1


def test_completion_failure_rolls_back_and_retries(tmp_path, monkeypatch):
    path, conversation_id, agents = _room(tmp_path, 1)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    claim = _claim(store, conversation_id, agents[0])
    original = store._insert_lifecycle_request_log_conn
    monkeypatch.setattr(
        store,
        "_insert_lifecycle_request_log_conn",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError, match="crash"):
        _complete(store, conversation_id, agents[0], claim, "retry")
    observation = store.get_observation(claim["observation"]["observation_id"])
    assert observation["status"] == "claimed"
    assert observation["lease_token"] == claim["observation"]["lease_token"]
    assert (
        store.get_participant_cursor(conversation_id, agents[0].participant_id)[
            "last_acknowledged_seq"
        ]
        == 0
    )
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                """select 1 from chat_request_log
               where conversation_id = ? and tool_name = 'room_complete_observation'
                 and caller_identity = ? and client_request_id = 'retry'""",
                (conversation_id, f"god:session:{agents[0].participant_id}"),
            ).fetchone()
            is None
        )
    monkeypatch.setattr(store, "_insert_lifecycle_request_log_conn", original)
    _complete(store, conversation_id, agents[0], claim, "retry")


def test_completion_replay_conflict_and_completed_guard(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 1)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    claim = _claim(store, conversation_id, agents[0])
    first = _complete(
        store, conversation_id, agents[0], claim, "same", "defer", {"wake_condition": "x"}
    )
    ParticipantStore(path).update_status(agents[0].participant_id, "stopped")
    assert (
        _complete(
            store, conversation_id, agents[0], claim, "same", "defer", {"wake_condition": "x"}
        )
        == first
    )
    before_conflict = _counts(path, conversation_id)
    assert before_conflict["room_observations"] == 1
    assert before_conflict["room_activities"] == 1
    assert before_conflict["messages"] == 1
    assert before_conflict["chat_request_log"] == 2
    with pytest.raises(ValueError, match="room_observation_idempotency_conflict"):
        _complete(store, conversation_id, agents[0], claim, "same", "noop")
    assert _counts(path, conversation_id) == before_conflict
    with pytest.raises(ValueError, match="room_observation_already_completed"):
        store.complete_observation(
            conversation_id=conversation_id,
            participant_id=agents[0].participant_id,
            caller_identity=f"god:s:{agents[0].participant_id}",
            observation_id=claim["observation"]["observation_id"],
            lease_token="new",
            client_request_id="other",
            outcome_type="noop",
        )


def test_restart_reopens_live_claim_and_reclaims_after_expiry(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 1)
    store = RoomKernelStore(path)
    _post(store, conversation_id)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    claim = _claim(store, conversation_id, agents[0], now=start)
    reopened = RoomKernelStore(path)
    same = _claim(
        reopened,
        conversation_id,
        agents[0],
        now=start + timedelta(seconds=1),
    )
    assert same == claim
    expiry = start + timedelta(seconds=120)
    reclaimed = _claim(
        reopened,
        conversation_id=conversation_id,
        participant=agents[0],
        owner="new-owner",
        now=expiry + timedelta(milliseconds=500),
    )
    assert reclaimed["observation"]["observation_id"] == claim["observation"]["observation_id"]
    assert reclaimed["observation"]["lease_token"] != claim["observation"]["lease_token"]
    assert reclaimed["observation"]["attempt_count"] == 2
    _complete(
        reopened,
        conversation_id,
        agents[0],
        reclaimed,
        "restart-complete",
        now=expiry + timedelta(seconds=1),
    )
    assert (
        reopened.get_participant_cursor(conversation_id, agents[0].participant_id)[
            "last_acknowledged_seq"
        ]
        == 1
    )
    assert len(reopened.list_observations(conversation_id)) == 1


def test_shadow_only_has_no_cursor_claim_or_side_effects(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 3)
    store = RoomKernelStore(path)
    shadow = store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="shadow",
        client_request_id="shadow",
        delivery_mode="shadow",
    )
    assert store.get_participant_cursor(conversation_id, agents[0].participant_id) is None
    assert (
        store.claim_next_observation(
            conversation_id=conversation_id,
            participant_id=agents[0].participant_id,
            lease_owner="worker",
        )
        is None
    )
    assert all(item["status"] == "shadowed" for item in shadow["observations"])
    counts = _counts(path, conversation_id)
    assert counts["room_activities"] == 1
    assert counts["room_observations"] == 3
    assert counts["chat_request_log"] == 1
    assert counts["messages"] == 0
    assert counts["chat_frontend_events"] == counts["proposals"] == 0


def test_actor_binding_and_ordering(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 2)
    store = RoomKernelStore(path)
    _post(store, conversation_id, "one")
    first = _claim(store, conversation_id, agents[0])
    other_conversation = RoomTestStore(path).create_conversation("other room")
    other_agent = ParticipantStore(path).add(
        conversation_id=other_conversation.id,
        role="other-role",
        display_name="Other Agent",
        cli_kind="codex",
        model="gpt-5",
    )
    observation_id = first["observation"]["observation_id"]
    lease_token = first["observation"]["lease_token"]
    attempts = [
        (agents[0].participant_id, "scheduler:bad"),
        (agents[0].participant_id, "system:bad"),
        (agents[0].participant_id, f"god:session:{agents[1].participant_id}"),
        (other_agent.participant_id, f"god:session:{other_agent.participant_id}"),
        ("missing-participant", "god:session:missing-participant"),
    ]
    for attempted_participant, caller in attempts:
        with pytest.raises(ValueError, match="room_observation_actor_forbidden"):
            store.complete_observation(
                conversation_id=conversation_id,
                participant_id=attempted_participant,
                caller_identity=caller,
                observation_id=observation_id,
                lease_token=lease_token,
                client_request_id=f"bad-{attempted_participant}",
                outcome_type="noop",
            )
    assert store.get_observation(observation_id)["status"] == "claimed"
    assert (
        store.get_participant_cursor(conversation_id, agents[0].participant_id)[
            "last_acknowledged_seq"
        ]
        == 0
    )
    _complete(store, conversation_id, agents[0], first, "correct")
    assert store.get_observation(observation_id)["status"] == "completed"


def test_claim_ordering_advances_cursor_by_sequence(tmp_path):
    path, conversation_id, agents = _room(tmp_path, 2)
    store = RoomKernelStore(path)
    _post(store, conversation_id, "one")
    _post(store, conversation_id, "two")
    first = _claim(store, conversation_id, agents[0])
    assert _claim(store, conversation_id, agents[0], "other") is None
    _complete(store, conversation_id, agents[0], first, "first")
    second = _claim(store, conversation_id, agents[0])
    assert second["activity"]["seq"] == 2
    assert _claim(store, conversation_id, agents[1])["activity"]["seq"] == 1
