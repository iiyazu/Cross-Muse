from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.god_room_event_store import (
    GodRoomEventConflictError,
    GodRoomEventStore,
    GodRoomMembershipError,
)
from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)


def test_god_room_event_store_replays_after_restart_with_idempotent_append(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "god-room-events.sqlite3"
    store = GodRoomEventStore(db_path)
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
        GodRoomParticipant(participant_id="part-review", god_id="god-review"),
        GodRoomParticipant(participant_id="part-execute", god_id="god-execute"),
    ]
    store.ensure_room(
        room_id="room-1",
        conversation_id="conv-1",
        participants=participants,
    )

    first = store.append_event(_event("evt-speak"))
    duplicate = store.append_event(_event("evt-speak"))
    store.append_event(
        _event(
            "evt-challenge",
            event_type=GodRoomEventKind.CHALLENGE,
            participant_id="part-review",
            god_id="god-review",
            target_participant_ids=["part-architect"],
            causal_parent_id="evt-speak",
        )
    )
    store.append_event(
        _event(
            "evt-handoff",
            event_type=GodRoomEventKind.HANDOFF,
            participant_id="part-architect",
            god_id="god-architect",
            target_participant_ids=["part-execute"],
            causal_parent_id="evt-challenge",
        )
    )
    store.append_event(
        _event(
            "evt-freeze",
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            participant_id="part-execute",
            god_id="god-execute",
            causal_parent_id="evt-handoff",
            payload={"freeze_target_ref": "blueprint:bp-room-1:1"},
        )
    )

    reloaded = GodRoomEventStore(db_path)
    snapshot = reloaded.load_room("room-1")
    replay = reloaded.replay_room("room-1")

    assert first.status == "created"
    assert duplicate.status == "duplicate"
    assert duplicate.event.event_id == "evt-speak"
    assert [event.event_id for event in snapshot.events] == [
        "evt-speak",
        "evt-challenge",
        "evt-handoff",
        "evt-freeze",
    ]
    assert [participant.participant_id for participant in snapshot.participants] == [
        "part-architect",
        "part-review",
        "part-execute",
    ]
    assert [
        (decision.event_id, decision.next_participant_id, decision.reason)
        for decision in replay.decisions
    ] == [
        ("evt-speak", "part-review", "round_robin"),
        ("evt-challenge", "part-architect", "challenge_target"),
        ("evt-handoff", "part-execute", "handoff_target"),
        ("evt-freeze", None, "freeze_requested"),
    ]


def test_god_room_event_store_rejects_unknown_participants_and_targets(
    tmp_path: Path,
) -> None:
    store = GodRoomEventStore(tmp_path / "god-room-events.sqlite3")
    store.ensure_room(
        room_id="room-1",
        conversation_id="conv-1",
        participants=[
            GodRoomParticipant(participant_id="part-architect", god_id="god-architect")
        ],
    )

    with pytest.raises(GodRoomMembershipError, match="participant part-review"):
        store.append_event(
            _event(
                "evt-review",
                participant_id="part-review",
                god_id="god-review",
            )
        )

    with pytest.raises(GodRoomMembershipError, match="target participant part-review"):
        store.append_event(
            _event(
                "evt-question",
                event_type=GodRoomEventKind.QUESTION,
                target_participant_ids=["part-review"],
            )
        )

    assert store.load_room("room-1").events == []


def test_god_room_event_store_rejects_conflicting_reuse_of_event_identity(
    tmp_path: Path,
) -> None:
    store = GodRoomEventStore(tmp_path / "god-room-events.sqlite3")
    store.ensure_room(
        room_id="room-1",
        conversation_id="conv-1",
        participants=[
            GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
            GodRoomParticipant(participant_id="part-review", god_id="god-review"),
        ],
    )
    store.append_event(_event("evt-speak", content="First claim."))

    with pytest.raises(GodRoomEventConflictError, match="event_id evt-speak"):
        store.append_event(_event("evt-speak", content="Conflicting claim."))


def test_god_room_event_store_keeps_rooms_isolated(tmp_path: Path) -> None:
    store = GodRoomEventStore(tmp_path / "god-room-events.sqlite3")
    for room_id, conversation_id in (("room-1", "conv-1"), ("room-2", "conv-2")):
        store.ensure_room(
            room_id=room_id,
            conversation_id=conversation_id,
            participants=[
                GodRoomParticipant(
                    participant_id=f"part-{room_id}",
                    god_id=f"god-{room_id}",
                )
            ],
        )
        store.append_event(
            _event(
                f"evt-{room_id}",
                room_id=room_id,
                conversation_id=conversation_id,
                participant_id=f"part-{room_id}",
                god_id=f"god-{room_id}",
            )
        )

    assert [event.event_id for event in store.load_room("room-1").events] == [
        "evt-room-1"
    ]
    assert [event.event_id for event in store.load_room("room-2").events] == [
        "evt-room-2"
    ]


def test_god_room_event_store_writes_replay_snapshot_artifact(tmp_path: Path) -> None:
    store = GodRoomEventStore(tmp_path / "god-room-events.sqlite3")
    store.ensure_room(
        room_id="room-1",
        conversation_id="conv-1",
        participants=[
            GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
            GodRoomParticipant(participant_id="part-review", god_id="god-review"),
        ],
    )
    store.append_event(_event("evt-speak"))
    output = tmp_path / "god-room-snapshot.json"

    artifact = store.write_room_snapshot("room-1", output)

    assert artifact["schema_version"] == "xmuse.god_room_snapshot.v1"
    assert artifact["source_authority"] == "god_room_event_store"
    assert artifact["room_id"] == "room-1"
    assert artifact["conversation_id"] == "conv-1"
    assert [participant["participant_id"] for participant in artifact["participants"]] == [
        "part-architect",
        "part-review",
    ]
    assert [event["event_id"] for event in artifact["events"]] == ["evt-speak"]
    assert artifact["replay"]["status"] == "ok"
    assert artifact["replay"]["proof_level"] == "contract_proof"
    assert artifact["replay"]["decisions"][0]["next_participant_id"] == "part-review"
    assert artifact["replay"]["event_proofs"][0]["event_id"] == "evt-speak"
    assert artifact["replay"]["event_proofs"][0]["proof_level"] == "contract_proof"
    assert artifact["replay"]["event_proofs"][0]["source_authority"] == (
        "god_room_event_contract"
    )
    assert json.loads(output.read_text(encoding="utf-8")) == artifact


def _event(
    event_id: str,
    *,
    room_id: str = "room-1",
    conversation_id: str = "conv-1",
    event_type: GodRoomEventKind = GodRoomEventKind.SPEAK,
    participant_id: str = "part-architect",
    god_id: str = "god-architect",
    target_participant_ids: list[str] | None = None,
    causal_parent_id: str | None = None,
    content: str = "I propose the next production slice.",
    payload: dict[str, object] | None = None,
) -> GodRoomEventV1:
    return GodRoomEventV1(
        event_id=event_id,
        room_id=room_id,
        conversation_id=conversation_id,
        participant_id=participant_id,
        god_id=god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=event_type,
        timestamp_utc="2026-06-13T10:00:00Z",
        content=content,
        target_participant_ids=target_participant_ids or [],
        causal_parent_id=causal_parent_id,
        source_refs=[f"message:{event_id}"],
        cli_id="codex",
        provider_profile="codex",
        payload=payload or {"body": content},
    )
