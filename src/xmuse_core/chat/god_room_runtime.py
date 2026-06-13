from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class GodRoomEventKind(StrEnum):
    SPEAK = "speak"
    QUESTION = "question"
    CHALLENGE = "challenge"
    HANDOFF = "handoff"
    FREEZE_REQUESTED = "freeze_requested"


class GodRoomActorKind(StrEnum):
    GOD = "god"
    OPERATOR = "operator"
    SUPERVISOR = "supervisor"
    SYSTEM = "system"
    DERIVED_PROJECTION = "derived_projection"


class GodRoomParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    participant_id: str
    god_id: str
    cli_id: str | None = None
    role: str | None = None

    @field_validator("participant_id", "god_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("cli_id", "role")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "field")


class GodRoomEventV1(BaseModel):
    """Durable event contract for replayable natural GOD room coordination."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["xmuse.god_room_event.v1"] = "xmuse.god_room_event.v1"
    event_id: str
    room_id: str
    conversation_id: str
    participant_id: str
    god_id: str
    actor_kind: GodRoomActorKind
    event_type: GodRoomEventKind
    timestamp_utc: str
    content: str
    target_participant_ids: list[str] = Field(default_factory=list)
    causal_parent_id: str | None = None
    source_refs: list[str] = Field(min_length=1)
    cli_id: str | None = None
    provider_profile: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "event_id",
        "room_id",
        "conversation_id",
        "participant_id",
        "god_id",
        "timestamp_utc",
        "content",
    )
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("causal_parent_id", "cli_id", "provider_profile")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("target_participant_ids", "source_refs")
    @classmethod
    def _validate_text_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        return _dedupe([_require_non_empty(item, info.field_name or "field") for item in value])

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("payload must be non-empty")
        return value

    @model_validator(mode="after")
    def _validate_event_shape(self) -> GodRoomEventV1:
        if self.event_type is GodRoomEventKind.CHALLENGE and (
            not self.causal_parent_id or not self.target_participant_ids
        ):
            raise ValueError("challenge events require causal_parent_id and target_participant_ids")
        if self.event_type in {GodRoomEventKind.QUESTION, GodRoomEventKind.HANDOFF} and (
            not self.target_participant_ids
        ):
            raise ValueError(f"{self.event_type.value} events require target_participant_ids")
        if (
            self.event_type is GodRoomEventKind.FREEZE_REQUESTED
            and not self.payload.get("freeze_target_ref")
        ):
            raise ValueError("freeze_requested events require payload.freeze_target_ref")
        return self

    def stable_json(self) -> str:
        data = self.model_dump(mode="json")
        ordered = {
            "actor_kind": data["actor_kind"],
            "causal_parent_id": data["causal_parent_id"],
            "cli_id": data["cli_id"],
            "content": data["content"],
            "conversation_id": data["conversation_id"],
            "event_id": data["event_id"],
            "event_type": data["event_type"],
            "god_id": data["god_id"],
            "participant_id": data["participant_id"],
            "payload": data["payload"],
            "provider_profile": data["provider_profile"],
            "room_id": data["room_id"],
            "source_refs": data["source_refs"],
            "target_participant_ids": data["target_participant_ids"],
            "timestamp_utc": data["timestamp_utc"],
            "version": data["version"],
        }
        return _stable_json(ordered)

    def idempotency_key(self) -> str:
        payload = self.model_dump(mode="json", exclude={"event_id"})
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return f"god-room-event:{digest}"


class GodRoomTurnDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    next_participant_id: str | None
    reason: str
    source_refs: list[str] = Field(default_factory=list)


class GodRoomReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "manual_gap"]
    proof_level: Literal["contract_proof", "manual_gap"]
    participant_count: int
    event_count: int
    decisions: list[GodRoomTurnDecision] = Field(default_factory=list)
    blocked_reason: str | None = None


def replay_god_room_turns(
    *,
    participants: list[GodRoomParticipant],
    events: list[GodRoomEventV1],
) -> GodRoomReplayResult:
    roster = {participant.participant_id: participant for participant in participants}
    participant_order = [participant.participant_id for participant in participants]
    decisions: list[GodRoomTurnDecision] = []
    if not participant_order:
        return _manual_gap_result(
            participants=participants,
            events=events,
            blocked_reason="god room replay requires at least one participant",
        )

    for event in sort_god_room_events(events):
        if event.participant_id not in roster:
            return _manual_gap_result(
                participants=participants,
                events=events,
                blocked_reason=(
                    f"event participant {event.participant_id} for event "
                    f"{event.event_id} is not in the room roster"
                ),
            )
        missing_target = _first_missing_target(event, roster)
        if missing_target is not None:
            return _manual_gap_result(
                participants=participants,
                events=events,
                blocked_reason=(
                    f"target participant {missing_target} for event "
                    f"{event.event_id} is not in the room roster"
                ),
            )
        decisions.append(_decision_for_event(event, participant_order))

    return GodRoomReplayResult(
        status="ok",
        proof_level="contract_proof",
        participant_count=len(participants),
        event_count=len(events),
        decisions=decisions,
        blocked_reason=None,
    )


def sort_god_room_events(events: list[GodRoomEventV1]) -> list[GodRoomEventV1]:
    by_id = {event.event_id: event for event in events}
    ordered: list[GodRoomEventV1] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(event_id: str) -> None:
        if event_id in visited:
            return
        if event_id in visiting:
            raise ValueError("causal_parent_id cycle detected")
        visiting.add(event_id)
        event = by_id[event_id]
        if event.causal_parent_id in by_id:
            visit(event.causal_parent_id)
        visiting.remove(event_id)
        visited.add(event_id)
        ordered.append(event)

    for event in sorted(events, key=lambda item: (item.timestamp_utc, item.event_id)):
        visit(event.event_id)
    return ordered


def _decision_for_event(
    event: GodRoomEventV1,
    participant_order: list[str],
) -> GodRoomTurnDecision:
    if event.event_type is GodRoomEventKind.FREEZE_REQUESTED:
        return GodRoomTurnDecision(
            event_id=event.event_id,
            next_participant_id=None,
            reason="freeze_requested",
            source_refs=[f"god-room-event:{event.event_id}", *event.source_refs],
        )
    if event.event_type is GodRoomEventKind.CHALLENGE:
        return _target_decision(event, reason="challenge_target")
    if event.event_type is GodRoomEventKind.QUESTION:
        return _target_decision(event, reason="question_target")
    if event.event_type is GodRoomEventKind.HANDOFF:
        return _target_decision(event, reason="handoff_target")
    return GodRoomTurnDecision(
        event_id=event.event_id,
        next_participant_id=_next_round_robin(event.participant_id, participant_order),
        reason="round_robin",
        source_refs=[f"god-room-event:{event.event_id}", *event.source_refs],
    )


def _target_decision(event: GodRoomEventV1, *, reason: str) -> GodRoomTurnDecision:
    return GodRoomTurnDecision(
        event_id=event.event_id,
        next_participant_id=event.target_participant_ids[0],
        reason=reason,
        source_refs=[f"god-room-event:{event.event_id}", *event.source_refs],
    )


def _next_round_robin(
    participant_id: str,
    participant_order: list[str],
) -> str | None:
    if len(participant_order) < 2:
        return None
    index = participant_order.index(participant_id)
    return participant_order[(index + 1) % len(participant_order)]


def _first_missing_target(
    event: GodRoomEventV1,
    roster: dict[str, GodRoomParticipant],
) -> str | None:
    for target in event.target_participant_ids:
        if target not in roster:
            return target
    return None


def _manual_gap_result(
    *,
    participants: list[GodRoomParticipant],
    events: list[GodRoomEventV1],
    blocked_reason: str,
) -> GodRoomReplayResult:
    return GodRoomReplayResult(
        status="manual_gap",
        proof_level="manual_gap",
        participant_count=len(participants),
        event_count=len(events),
        decisions=[],
        blocked_reason=blocked_reason,
    )


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


__all__ = [
    "GodRoomActorKind",
    "GodRoomEventKind",
    "GodRoomEventV1",
    "GodRoomParticipant",
    "GodRoomReplayResult",
    "GodRoomTurnDecision",
    "replay_god_room_turns",
    "sort_god_room_events",
]
