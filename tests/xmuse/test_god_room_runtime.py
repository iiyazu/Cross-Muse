from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
    replay_god_room_turns,
)


def test_god_room_event_serialization_identity_and_idempotency_are_stable() -> None:
    event = _event(
        "evt-challenge",
        event_type=GodRoomEventKind.CHALLENGE,
        participant_id="part-review",
        god_id="god-review",
        target_participant_ids=["part-architect"],
        causal_parent_id="evt-propose",
        content="Which source proves the freeze can proceed?",
        payload={"decision_scope": "blueprint.freeze"},
    )
    duplicate = event.model_copy(update={"event_id": "evt-duplicate"})

    assert event.stable_json() == (
        '{"actor_kind":"god","causal_parent_id":"evt-propose",'
        '"cli_id":"codex.god","content":"Which source proves the freeze can proceed?",'
        '"conversation_id":"conv-1","event_id":"evt-challenge",'
        '"event_type":"challenge","god_id":"god-review",'
        '"participant_id":"part-review",'
        '"payload":{"decision_scope":"blueprint.freeze"},'
        '"provider_profile":"codex","room_id":"room-1",'
        '"source_refs":["message:evt-propose"],'
        '"target_participant_ids":["part-architect"],'
        '"timestamp_utc":"2026-06-13T10:00:00Z",'
        '"version":"xmuse.god_room_event.v1"}'
    )
    assert event.idempotency_key() == duplicate.idempotency_key()


def test_god_room_event_rejects_missing_identity_source_refs_and_invalid_routing() -> None:
    with pytest.raises(ValidationError, match="source_refs"):
        _event("evt-no-source", source_refs=[])

    with pytest.raises(ValidationError, match="participant_id"):
        _event("evt-no-participant", participant_id="")

    with pytest.raises(ValidationError, match="content"):
        _event("evt-no-content", content="")

    with pytest.raises(ValidationError, match="challenge events require"):
        _event(
            "evt-bad-challenge",
            event_type=GodRoomEventKind.CHALLENGE,
            target_participant_ids=[],
            causal_parent_id=None,
        )

    with pytest.raises(ValidationError, match="freeze_requested events require"):
        _event(
            "evt-bad-freeze",
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            payload={"decision_scope": "blueprint.freeze"},
        )


def test_replay_god_room_turns_routes_challenge_handoff_and_freeze_deterministically() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
        GodRoomParticipant(participant_id="part-review", god_id="god-review"),
        GodRoomParticipant(participant_id="part-execute", god_id="god-execute"),
    ]
    events = [
        _event("evt-speak", participant_id="part-architect", god_id="god-architect"),
        _event(
            "evt-challenge",
            event_type=GodRoomEventKind.CHALLENGE,
            participant_id="part-review",
            god_id="god-review",
            target_participant_ids=["part-architect"],
            causal_parent_id="evt-speak",
        ),
        _event(
            "evt-handoff",
            event_type=GodRoomEventKind.HANDOFF,
            participant_id="part-architect",
            god_id="god-architect",
            target_participant_ids=["part-execute"],
            causal_parent_id="evt-challenge",
        ),
        _event(
            "evt-freeze",
            event_type=GodRoomEventKind.FREEZE_REQUESTED,
            participant_id="part-execute",
            god_id="god-execute",
            causal_parent_id="evt-handoff",
            payload={"freeze_target_ref": "blueprint:conv-1:1"},
        ),
    ]

    replay = replay_god_room_turns(participants=participants, events=events)

    assert replay.status == "ok"
    assert replay.proof_level == "contract_proof"
    assert replay.blocked_reason is None
    assert [
        (decision.event_id, decision.next_participant_id, decision.reason)
        for decision in replay.decisions
    ] == [
        ("evt-speak", "part-review", "round_robin"),
        ("evt-challenge", "part-architect", "challenge_target"),
        ("evt-handoff", "part-execute", "handoff_target"),
        ("evt-freeze", None, "freeze_requested"),
    ]


def test_replay_god_room_turns_reports_manual_gap_instead_of_inventing_missing_target() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
        GodRoomParticipant(participant_id="part-review", god_id="god-review"),
    ]
    events = [
        _event(
            "evt-question",
            event_type=GodRoomEventKind.QUESTION,
            participant_id="part-review",
            god_id="god-review",
            target_participant_ids=["part-missing"],
        )
    ]

    replay = replay_god_room_turns(participants=participants, events=events)

    assert replay.status == "manual_gap"
    assert replay.proof_level == "manual_gap"
    assert replay.blocked_reason == (
        "target participant part-missing for event evt-question is not in the room roster"
    )
    assert replay.decisions == []


def _event(
    event_id: str,
    *,
    event_type: GodRoomEventKind = GodRoomEventKind.SPEAK,
    participant_id: str = "part-architect",
    god_id: str = "god-architect",
    target_participant_ids: list[str] | None = None,
    causal_parent_id: str | None = None,
    content: str = "I propose freezing the current blueprint.",
    source_refs: list[str] | None = None,
    payload: dict[str, object] | None = None,
) -> GodRoomEventV1:
    return GodRoomEventV1(
        event_id=event_id,
        room_id="room-1",
        conversation_id="conv-1",
        participant_id=participant_id,
        god_id=god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=event_type,
        timestamp_utc="2026-06-13T10:00:00Z",
        content=content,
        target_participant_ids=target_participant_ids or [],
        causal_parent_id=causal_parent_id,
        source_refs=["message:evt-propose"] if source_refs is None else source_refs,
        cli_id="codex.god",
        provider_profile="codex",
        payload=payload or {"body": content},
    )
