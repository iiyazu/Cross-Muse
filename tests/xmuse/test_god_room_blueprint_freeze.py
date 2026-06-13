from __future__ import annotations

from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
)
from xmuse_core.structuring.god_room_blueprint_freeze import (
    GodRoomBlueprintFreezeStatus,
    compile_blueprint_freeze_from_god_room_events,
)
from xmuse_core.structuring.mission_blueprint_v1 import MissionBlueprintStatus


def test_compile_blueprint_freeze_from_room_events_preserves_decision_context() -> None:
    artifact = compile_blueprint_freeze_from_god_room_events(
        blueprint_id="bp-god-room",
        revision=1,
        events=[
            _event(
                "evt-proposal",
                event_type=GodRoomEventKind.SPEAK,
                payload={
                    "goal": "Build GOD room runtime.",
                    "scope": ["GOD room event contract", "Speaker replay"],
                    "acceptance_contracts": ["Room replay recovers speaker decisions."],
                    "assumptions": ["Provider responses may be unavailable in CI."],
                    "rejected_alternatives": [
                        "Scrape TUI rendered text as transcript authority."
                    ],
                },
            ),
            _event(
                "evt-freeze",
                event_type=GodRoomEventKind.FREEZE_REQUESTED,
                participant_id="part-review",
                god_id="god-review",
                causal_parent_id="evt-proposal",
                payload={
                    "freeze_target_ref": "blueprint:bp-god-room:1",
                    "goal": "Build GOD room runtime.",
                    "scope": ["GOD room event contract", "Speaker replay"],
                    "constraints": ["Use durable GOD room events."],
                    "non_goals": ["Do not claim pr_merged."],
                    "acceptance_contracts": ["Room replay recovers speaker decisions."],
                    "repo_areas": ["src/xmuse_core/chat"],
                    "assumptions": ["Provider responses may be unavailable in CI."],
                    "rejected_alternatives": [
                        "Scrape TUI rendered text as transcript authority."
                    ],
                },
            ),
        ],
    )

    assert artifact.status is GodRoomBlueprintFreezeStatus.FROZEN
    assert artifact.blueprint is not None
    assert artifact.blueprint.status is MissionBlueprintStatus.FROZEN
    assert artifact.blueprint.goal == "Build GOD room runtime."
    assert artifact.blueprint.source_refs == [
        "god-room-event:evt-proposal",
        "message:evt-proposal",
        "god-room-event:evt-freeze",
        "message:evt-freeze",
    ]
    assert artifact.assumptions == ["Provider responses may be unavailable in CI."]
    assert artifact.rejected_alternatives == [
        "Scrape TUI rendered text as transcript authority."
    ]
    assert artifact.blockers == []
    assert artifact.blocked_reason is None


def test_compile_blueprint_freeze_blocks_unresolved_challenge_as_manual_gap() -> None:
    artifact = compile_blueprint_freeze_from_god_room_events(
        blueprint_id="bp-god-room",
        revision=1,
        events=[
            _event(
                "evt-proposal",
                event_type=GodRoomEventKind.SPEAK,
                payload={
                    "goal": "Build GOD room runtime.",
                    "scope": ["GOD room event contract"],
                    "acceptance_contracts": ["Events reject missing source refs."],
                },
            ),
            _event(
                "evt-challenge",
                event_type=GodRoomEventKind.CHALLENGE,
                participant_id="part-review",
                god_id="god-review",
                target_participant_ids=["part-architect"],
                causal_parent_id="evt-proposal",
                payload={
                    "conflict": "No proof that TUI is non-authoritative.",
                    "resolved": False,
                },
            ),
            _event(
                "evt-freeze",
                event_type=GodRoomEventKind.FREEZE_REQUESTED,
                causal_parent_id="evt-proposal",
                payload={
                    "freeze_target_ref": "blueprint:bp-god-room:1",
                    "goal": "Build GOD room runtime.",
                    "scope": ["GOD room event contract"],
                    "acceptance_contracts": ["Events reject missing source refs."],
                },
            ),
        ],
    )

    assert artifact.status is GodRoomBlueprintFreezeStatus.MANUAL_GAP
    assert artifact.blueprint is None
    assert artifact.conflicts == ["No proof that TUI is non-authoritative."]
    assert artifact.blockers == ["unresolved challenge evt-challenge"]
    assert artifact.blocked_reason == "unresolved GOD room challenges block blueprint freeze"


def _event(
    event_id: str,
    *,
    event_type: GodRoomEventKind,
    participant_id: str = "part-architect",
    god_id: str = "god-architect",
    target_participant_ids: list[str] | None = None,
    causal_parent_id: str | None = None,
    payload: dict[str, object],
) -> GodRoomEventV1:
    return GodRoomEventV1(
        event_id=event_id,
        room_id="room-1",
        conversation_id="conv-1",
        participant_id=participant_id,
        god_id=god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=event_type,
        timestamp_utc=f"2026-06-13T10:00:0{len(event_id)}Z",
        content=str(payload.get("goal") or payload.get("conflict") or "Freeze request."),
        target_participant_ids=target_participant_ids or [],
        causal_parent_id=causal_parent_id,
        source_refs=[f"message:{event_id}"],
        cli_id="codex.god",
        provider_profile="codex",
        payload=payload,
    )
