from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xmuse_core.chat.god_room_runtime import GodRoomEventKind, GodRoomEventV1, sort_god_room_events
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintDecisionLogEntry,
    MissionBlueprintStatus,
    MissionBlueprintV1,
)


class GodRoomBlueprintFreezeStatus(StrEnum):
    FROZEN = "frozen"
    MANUAL_GAP = "manual_gap"


class GodRoomBlueprintFreezeArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["xmuse.god_room_blueprint_freeze.v1"] = (
        "xmuse.god_room_blueprint_freeze.v1"
    )
    status: GodRoomBlueprintFreezeStatus
    blueprint: MissionBlueprintV1 | None = None
    decision_event_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    rejected_alternatives: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None

    @field_validator(
        "assumptions",
        "conflicts",
        "rejected_alternatives",
        "blockers",
        "source_refs",
    )
    @classmethod
    def _clean_text_list(cls, value: list[str]) -> list[str]:
        return _dedupe([item.strip() for item in value if item.strip()])


def compile_blueprint_freeze_from_god_room_events(
    *,
    blueprint_id: str,
    revision: int,
    events: list[GodRoomEventV1],
) -> GodRoomBlueprintFreezeArtifactV1:
    ordered_events = sort_god_room_events(events)
    source_refs = _source_refs(ordered_events)
    unresolved = _unresolved_challenges(ordered_events)
    conflicts = [_challenge_conflict(event) for event in unresolved]
    if unresolved:
        return GodRoomBlueprintFreezeArtifactV1(
            status=GodRoomBlueprintFreezeStatus.MANUAL_GAP,
            blueprint=None,
            decision_event_id=_latest_freeze_event_id(ordered_events),
            assumptions=_payload_texts(ordered_events, "assumptions"),
            conflicts=conflicts,
            rejected_alternatives=_payload_texts(
                ordered_events,
                "rejected_alternatives",
            ),
            blockers=[f"unresolved challenge {event.event_id}" for event in unresolved],
            source_refs=source_refs,
            blocked_reason="unresolved GOD room challenges block blueprint freeze",
        )

    freeze_event = _latest_freeze_event(ordered_events)
    if freeze_event is None:
        return GodRoomBlueprintFreezeArtifactV1(
            status=GodRoomBlueprintFreezeStatus.MANUAL_GAP,
            blueprint=None,
            assumptions=_payload_texts(ordered_events, "assumptions"),
            conflicts=[],
            rejected_alternatives=_payload_texts(
                ordered_events,
                "rejected_alternatives",
            ),
            blockers=["missing freeze_requested event"],
            source_refs=source_refs,
            blocked_reason="GOD room transcript has no freeze_requested event",
        )

    payload = freeze_event.payload
    blueprint = MissionBlueprintV1(
        blueprint_id=blueprint_id,
        conversation_id=freeze_event.conversation_id,
        revision=revision,
        goal=_payload_text(payload, "goal", fallback=freeze_event.content),
        scope=_payload_text_list(payload, "scope"),
        constraints=_payload_text_list(payload, "constraints"),
        non_goals=_payload_text_list(payload, "non_goals"),
        acceptance_contracts=_payload_text_list(payload, "acceptance_contracts"),
        repo_areas=_payload_text_list(payload, "repo_areas"),
        open_questions=_payload_text_list(payload, "open_questions"),
        decision_log=[
            MissionBlueprintDecisionLogEntry(
                decision=f"Freeze requested by {freeze_event.god_id}.",
                source_refs=[f"god-room-event:{freeze_event.event_id}", *freeze_event.source_refs],
            )
        ],
        source_refs=source_refs,
        status=MissionBlueprintStatus.FROZEN,
        approved_by=[freeze_event.god_id],
    )
    return GodRoomBlueprintFreezeArtifactV1(
        status=GodRoomBlueprintFreezeStatus.FROZEN,
        blueprint=blueprint,
        decision_event_id=freeze_event.event_id,
        assumptions=_payload_texts(ordered_events, "assumptions"),
        conflicts=[],
        rejected_alternatives=_payload_texts(ordered_events, "rejected_alternatives"),
        blockers=[],
        source_refs=source_refs,
        blocked_reason=None,
    )


def _latest_freeze_event(events: list[GodRoomEventV1]) -> GodRoomEventV1 | None:
    for event in reversed(events):
        if event.event_type is GodRoomEventKind.FREEZE_REQUESTED:
            return event
    return None


def _latest_freeze_event_id(events: list[GodRoomEventV1]) -> str | None:
    event = _latest_freeze_event(events)
    return event.event_id if event is not None else None


def _unresolved_challenges(events: list[GodRoomEventV1]) -> list[GodRoomEventV1]:
    return [
        event
        for event in events
        if event.event_type is GodRoomEventKind.CHALLENGE
        and event.payload.get("resolved") is not True
    ]


def _challenge_conflict(event: GodRoomEventV1) -> str:
    conflict = event.payload.get("conflict") or event.payload.get("question")
    if isinstance(conflict, str) and conflict.strip():
        return conflict.strip()
    return event.content


def _source_refs(events: list[GodRoomEventV1]) -> list[str]:
    refs: list[str] = []
    for event in events:
        refs.append(f"god-room-event:{event.event_id}")
        refs.extend(event.source_refs)
    return _dedupe(refs)


def _payload_texts(events: list[GodRoomEventV1], key: str) -> list[str]:
    values: list[str] = []
    for event in events:
        values.extend(_payload_text_list(event.payload, key))
    return _dedupe(values)


def _payload_text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _payload_text(payload: dict[str, Any], key: str, *, fallback: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback.strip()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "GodRoomBlueprintFreezeArtifactV1",
    "GodRoomBlueprintFreezeStatus",
    "compile_blueprint_freeze_from_god_room_events",
]
