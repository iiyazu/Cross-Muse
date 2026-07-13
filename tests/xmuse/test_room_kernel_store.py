from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_setup import RoomConversationCreate, RoomSetupService


def _room(tmp_path):
    path = tmp_path / "chat.db"
    chat = RoomTestStore(path)
    conversation = chat.create_conversation("room")
    participants = ParticipantStore(path)
    active = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(3)
    ]
    stopped = participants.add(
        conversation_id=conversation.id,
        role="stopped",
        display_name="Stopped",
        cli_kind="codex",
        model="gpt-5",
        status="stopped",
    )
    return path, conversation.id, active, stopped


def _single_participant_room(path, title):
    conversation = RoomTestStore(path).create_conversation(title)
    participant = ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="review",
        display_name=f"{title} reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    return conversation.id, participant


def _counts(path, conversation_id):
    with sqlite3.connect(path) as conn:
        return {
            table: conn.execute(
                f"select count(*) from {table} where conversation_id = ?",
                (conversation_id,),
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


def test_active_activity_is_authoritative_and_targets_all_active(tmp_path):
    path, conversation_id, active, stopped = _room(tmp_path)
    store = RoomKernelStore(path)
    result = store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="hello room",
        client_request_id="req-1",
        mentions=[active[0].participant_id],
    )

    activity = result["activity"]
    assert activity["seq"] == 1
    assert activity["actor_kind"] == "human"
    assert activity["actor_identity"] == "human:alice"
    assert activity["activity_type"] == "message.posted"
    assert activity["visibility"] == "room"
    assert activity["audience"] == {
        "type": "room",
        "conversation_id": conversation_id,
    }
    assert activity["causation_id"].startswith("causation_")
    assert activity["correlation_id"].startswith("correlation_")
    assert result["message"]["envelope_json"] == {"type": "message"}
    observations = store.list_observations(conversation_id)
    assert len(observations) == 3
    assert sorted(result["observations"], key=lambda item: item["observation_id"]) == sorted(
        observations, key=lambda item: item["observation_id"]
    )
    assert all("outcome_payload" in item for item in observations)
    assert all("outcome_payload_json" not in item for item in observations)
    assert {item["participant_id"] for item in observations} == {
        item.participant_id for item in active
    }
    assert {item["participant_id"]: item["priority"] for item in observations} == {
        active[0].participant_id: 100,
        active[1].participant_id: 0,
        active[2].participant_id: 0,
    }
    assert all(item["status"] == "pending" for item in observations)
    assert stopped.participant_id not in {item["participant_id"] for item in observations}
    counts = _counts(path, conversation_id)
    assert counts["messages"] == counts["room_activities"] == 1
    assert counts["chat_frontend_events"] == 1


def test_mentions_are_metadata_not_eligibility(tmp_path):
    path, conversation_id, active, _ = _room(tmp_path)
    store = RoomKernelStore(path)
    store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="only mentions one",
        client_request_id="req-mentions",
        mentions=[active[0].participant_id],
    )
    assert len(store.list_observations(conversation_id)) == 3


def test_bootstrap_init_god_is_not_a_room_observer(tmp_path):
    path, conversation_id, active, _ = _room(tmp_path)
    init_god = ParticipantStore(path).ensure_init_god(
        conversation_id=conversation_id,
        model="gpt-5",
    )

    result = RoomKernelStore(path).post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="hello persistent room members",
        client_request_id="without-init-god",
    )

    participant_ids = {item["participant_id"] for item in result["observations"]}
    assert participant_ids == {item.participant_id for item in active}
    assert init_god.participant_id not in participant_ids


@pytest.mark.parametrize("cli_kind", ["a2a", "opencode"])
def test_historical_provider_cannot_receive_or_claim_room_work(tmp_path, cli_kind):
    path = tmp_path / "chat.db"
    conversation_id, participant = _single_participant_room(path, "historical")
    kernel = RoomKernelStore(path)
    first = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="created before provider retirement",
        client_request_id="before-retirement",
    )
    assert len(first["observations"]) == 1
    with sqlite3.connect(path) as conn:
        conn.execute(
            "update participants set cli_kind = ?, model = ? where participant_id = ?",
            (cli_kind, "historical-model", participant.participant_id),
        )

    second = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="created after provider retirement",
        client_request_id="after-retirement",
    )

    assert second["observations"] == []
    assert kernel.list_claimable_conversation_ids(max_attempts_per_observation=3) == []
    with pytest.raises(ValueError, match="room_participant_not_active"):
        kernel.claim_next_observation(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            lease_owner="host",
        )


def test_claimable_rooms_use_durable_frontier_attempts_and_participant_status(
    tmp_path,
):
    path = tmp_path / "chat.db"
    exhausted_id, exhausted_participant = _single_participant_room(path, "exhausted")
    stopped_id, stopped_participant = _single_participant_room(path, "stopped")
    kernel = RoomKernelStore(path)
    for conversation_id in (exhausted_id, stopped_id):
        kernel.post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content="first",
            client_request_id="first",
        )

    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert (
        kernel.claim_next_observation(
            conversation_id=exhausted_id,
            participant_id=exhausted_participant.participant_id,
            lease_owner="host-1",
            lease_ttl_s=1,
            now=now,
        )
        is not None
    )
    kernel.post_human_activity(
        conversation_id=exhausted_id,
        human_id="human",
        content="later activity must not bypass the exhausted frontier",
        client_request_id="later",
    )
    ParticipantStore(path).update_status(
        stopped_participant.participant_id,
        "stopped",
    )

    assert (
        kernel.list_claimable_conversation_ids(
            max_attempts_per_observation=2,
            now=now + timedelta(milliseconds=500),
        )
        == []
    )
    after_expiry = now + timedelta(seconds=2)
    assert (
        kernel.list_claimable_conversation_ids(
            max_attempts_per_observation=1,
            now=after_expiry,
        )
        == []
    )
    assert kernel.list_claimable_conversation_ids(
        max_attempts_per_observation=2,
        now=after_expiry,
    ) == [exhausted_id]

    ParticipantStore(path).update_status(
        stopped_participant.participant_id,
        "active",
    )
    assert set(
        kernel.list_claimable_conversation_ids(
            max_attempts_per_observation=2,
            now=after_expiry,
        )
    ) == {exhausted_id, stopped_id}

    with pytest.raises(ValueError, match="room_max_attempts_invalid"):
        kernel.list_claimable_conversation_ids(
            max_attempts_per_observation=True,
            now=after_expiry,
        )
    with pytest.raises(ValueError, match="room_observation_now_timezone_required"):
        kernel.list_claimable_conversation_ids(
            max_attempts_per_observation=2,
            now=datetime(2026, 1, 1),
        )


def test_request_replay_and_conflict_are_deduplicated(tmp_path):
    path, conversation_id, _, _ = _room(tmp_path)
    store = RoomKernelStore(path)
    kwargs = dict(
        conversation_id=conversation_id,
        human_id="alice",
        content="same",
        client_request_id="same-key",
    )
    first = store.post_human_activity(**kwargs)
    second = store.post_human_activity(**kwargs)
    assert second == first
    before = _counts(path, conversation_id)
    with pytest.raises(ValueError, match="room_request_idempotency_conflict"):
        store.post_human_activity(**{**kwargs, "content": "changed"})
    with pytest.raises(ValueError, match="room_request_idempotency_conflict"):
        store.post_human_activity(**{**kwargs, "delivery_mode": "shadow"})
    assert _counts(path, conversation_id) == before


def test_observation_failure_rolls_back_everything(tmp_path, monkeypatch):
    path, conversation_id, _, _ = _room(tmp_path)
    store = RoomKernelStore(path)

    original = store._insert_observation_conn
    calls = 0

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected observation failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "_insert_observation_conn", fail_on_second)
    with pytest.raises(RuntimeError, match="injected"):
        store.post_human_activity(
            conversation_id=conversation_id,
            human_id="alice",
            content="rollback",
            client_request_id="rollback-key",
        )
    counts = _counts(path, conversation_id)
    assert calls == 2
    assert counts["messages"] == counts["room_activities"] == 0
    assert counts["room_observations"] == counts["chat_request_log"] == 0


def test_concurrent_posts_have_contiguous_sequences(tmp_path):
    path, conversation_id, _, _ = _room(tmp_path)

    def post(index):
        return RoomKernelStore(path).post_human_activity(
            conversation_id=conversation_id,
            human_id="alice",
            content=f"message-{index}",
            client_request_id=f"concurrent-{index}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(post, range(8)))
    assert sorted(item["activity"]["seq"] for item in results) == list(range(1, 9))
    counts = _counts(path, conversation_id)
    assert counts["room_activities"] == counts["messages"] == 8
    assert counts["chat_request_log"] == 8
    assert counts["room_observations"] == 24


def test_four_rooms_accept_twenty_concurrent_human_posts_without_lock_errors(
    tmp_path,
):
    path = tmp_path / "chat.db"
    RoomDatabase(path).initialize()
    setup = RoomSetupService(tmp_path)
    conversation_ids = [
        setup.create_conversation(
            RoomConversationCreate(
                title=f"Concurrent room {index}",
                client_request_id=f"concurrent-room-{index}",
            )
        )["id"]
        for index in range(4)
    ]

    def post(index):
        conversation_id = conversation_ids[index % len(conversation_ids)]
        return RoomKernelStore(path).post_human_activity(
            conversation_id=conversation_id,
            human_id="audit",
            content=f"request-{index}",
            client_request_id=f"concurrent-human-{index}",
        )

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(post, range(20)))

    assert len(results) == 20
    with sqlite3.connect(path) as conn:
        for conversation_id in conversation_ids:
            assert [
                row[0]
                for row in conn.execute(
                    "select seq from room_activities where conversation_id = ? order by seq",
                    (conversation_id,),
                )
            ] == [1, 2, 3, 4, 5]
            assert [
                row[0]
                for row in conn.execute(
                    "select seq from chat_frontend_events where conversation_id = ? order by seq",
                    (conversation_id,),
                )
            ] == [1, 2, 3, 4, 5]
            assert (
                conn.execute(
                    "select count(*) from messages where conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                == 5
            )
            assert (
                conn.execute(
                    "select count(*) from room_observations where conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                == 20
            )


def test_shadow_is_diagnostic_only_and_projection_excludes_it(tmp_path):
    path, conversation_id, _, _ = _room(tmp_path)
    store = RoomKernelStore(path)
    result = store.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="diagnostic",
        client_request_id="shadow-key",
        delivery_mode="shadow",
    )
    assert result["message"] is None
    observations = store.list_observations(conversation_id)
    assert len(observations) == 3
    assert all(item["status"] == "shadowed" for item in observations)
    counts = _counts(path, conversation_id)
    assert counts["room_activities"] == 1
    assert counts["room_observations"] == 3
    assert counts["chat_request_log"] == 1
    assert counts["messages"] == 0
    assert counts["chat_frontend_events"] == counts["proposals"] == 0
    assert store.list_projection_events(conversation_id) == []
    assert (
        store.post_human_activity(
            conversation_id=conversation_id,
            human_id="alice",
            content="diagnostic",
            client_request_id="shadow-key",
            delivery_mode="shadow",
        )
        == result
    )


def test_reopen_preserves_order_and_projection(tmp_path):
    path, conversation_id, _, _ = _room(tmp_path)
    first = RoomKernelStore(path)
    first.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="visible",
        client_request_id="visible-key",
    )
    first.post_human_activity(
        conversation_id=conversation_id,
        human_id="alice",
        content="hidden",
        client_request_id="hidden-key",
        delivery_mode="shadow",
    )
    activities = first.list_activities(conversation_id)
    projection = first.list_projection_events(conversation_id)
    second = RoomKernelStore(path)
    assert second.list_activities(conversation_id) == activities
    assert second.list_projection_events(conversation_id) == projection
    assert [item["seq"] for item in activities] == [1, 2]
    assert [item["sequence"] for item in projection] == [1]
    assert projection[0]["event_type"] == activities[0]["activity_type"]
    assert second.list_projection_events(conversation_id, after_seq=-1, limit=0) == projection


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("human_id", "", "room_human_id_required"),
        ("content", "", "room_content_required"),
        ("client_request_id", "", "room_client_request_id_required"),
        ("delivery_mode", "invalid", "room_delivery_mode_invalid"),
    ],
)
def test_stable_validation_codes(tmp_path, field, value, code):
    path, conversation_id, _, _ = _room(tmp_path)
    kwargs = {
        "conversation_id": conversation_id,
        "human_id": "alice",
        "content": "content",
        "client_request_id": "request",
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=code):
        RoomKernelStore(path).post_human_activity(**kwargs)
