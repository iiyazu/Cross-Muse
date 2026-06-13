from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.chat.god_room_runtime import (
    GodRoomEventV1,
    GodRoomParticipant,
    GodRoomTurnDecision,
    replay_god_room_turns,
)

Status = Literal["ready_for_provider_attempt", "manual_gap"]
ProofLevel = Literal["contract_proof", "manual_gap"]
SourceAuthority = Literal[
    "god_room_event_store+selected_god_runtime_continuity",
    "god_room_event_store+room_selected_god_binding+selected_god_runtime_continuity",
]
SelectedBindingResolver = Callable[[GodRoomParticipant], Mapping[str, Any]]


class GodRoomSpeakerAttemptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xmuse.god_room_speaker_attempt.v1"] = (
        "xmuse.god_room_speaker_attempt.v1"
    )
    status: Status
    proof_level: ProofLevel
    source_authority: SourceAuthority = (
        "god_room_event_store+selected_god_runtime_continuity"
    )
    conversation_id: str
    room_id: str
    selected_event_id: str | None = None
    decision_reason: str | None = None
    target_participant_id: str | None = None
    target_god_id: str | None = None
    target_cli_id: str | None = None
    binding_revision: str | None = None
    account_ref: str | None = None
    cli_command: str | None = None
    model: str | None = None
    variant: str | None = None
    provider_profile_ref: str | None = None
    provider_session_id: str | None = None
    provider_session_kind: str | None = None
    provider_binding_status: str | None = None
    effective_session_status: str | None = None
    blocked_reason: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    provider_attempt: dict[str, Any] | None = None


def build_god_room_speaker_attempt(
    *,
    conversation_id: str,
    room_id: str,
    participants: Sequence[GodRoomParticipant],
    events: Sequence[GodRoomEventV1],
    runtime_continuity: Mapping[str, Any],
    after_event_id: str | None = None,
    selected_binding_resolver: SelectedBindingResolver | None = None,
) -> GodRoomSpeakerAttemptV1:
    """Build replayable evidence for the next GOD speaker provider attempt.

    This function intentionally does not invoke a provider and does not append a
    GOD room speak event. It only proves whether the durable room replay can be
    joined to a selected provider-bound GOD session.
    """

    participant_list = list(participants)
    event_list = list(events)
    replay = replay_god_room_turns(
        participants=participant_list,
        events=event_list,
    )
    if replay.status != "ok":
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            blocked_reason=replay.blocked_reason or "god room replay is not ready",
            source_refs=[],
        )

    decision = _select_decision(replay.decisions, after_event_id=after_event_id)
    if decision is None:
        reason = (
            f"speaker replay decision not found: {after_event_id}"
            if after_event_id
            else "god room has no replay decisions"
        )
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            blocked_reason=reason,
            source_refs=[],
        )
    if decision.next_participant_id is None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            source_authority=_source_authority(selected_binding_resolver),
            selected_event_id=decision.event_id,
            decision_reason=decision.reason,
            blocked_reason=f"replay decision has no next speaker: {decision.reason}",
            source_refs=list(decision.source_refs),
        )

    target = _participant_by_id(participant_list).get(decision.next_participant_id)
    if target is None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            source_authority=_source_authority(selected_binding_resolver),
            selected_event_id=decision.event_id,
            decision_reason=decision.reason,
            target_participant_id=decision.next_participant_id,
            blocked_reason=(
                f"target participant {decision.next_participant_id} is not in "
                "the GOD room roster"
            ),
            source_refs=list(decision.source_refs),
        )

    runtime_item = _runtime_item_for_participant(
        runtime_continuity,
        target.participant_id,
    )
    participant_ref = f"god-room-participant:{target.participant_id}"
    binding_resolution = _resolve_selected_binding(
        target,
        selected_binding_resolver=selected_binding_resolver,
    )
    binding_source_refs = _string_list(binding_resolution.get("source_refs"))
    if binding_resolution.get("status") == "manual_gap":
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            source_authority=_source_authority(selected_binding_resolver),
            selected_event_id=decision.event_id,
            decision_reason=decision.reason,
            target_participant_id=target.participant_id,
            target_god_id=target.god_id,
            target_cli_id=target.cli_id,
            binding_revision=_optional_text(binding_resolution.get("binding_revision")),
            account_ref=_optional_text(binding_resolution.get("account_ref")),
            cli_command=_optional_text(binding_resolution.get("cli_command")),
            model=_optional_text(binding_resolution.get("model")),
            variant=_optional_text(binding_resolution.get("variant")),
            blocked_reason=_optional_text(binding_resolution.get("blocked_reason"))
            or "room selected GOD binding unavailable",
            source_refs=_unique([*decision.source_refs, participant_ref, *binding_source_refs]),
        )
    if _binding_mismatch(target, binding_resolution):
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            source_authority=_source_authority(selected_binding_resolver),
            selected_event_id=decision.event_id,
            decision_reason=decision.reason,
            target_participant_id=target.participant_id,
            target_god_id=target.god_id,
            target_cli_id=target.cli_id,
            binding_revision=_optional_text(binding_resolution.get("binding_revision")),
            account_ref=_optional_text(binding_resolution.get("account_ref")),
            cli_command=_optional_text(binding_resolution.get("cli_command")),
            model=_optional_text(binding_resolution.get("model")),
            variant=_optional_text(binding_resolution.get("variant")),
            blocked_reason="room selected GOD binding does not match replay target",
            source_refs=_unique([*decision.source_refs, participant_ref, *binding_source_refs]),
        )

    if runtime_item is None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            source_authority=_source_authority(selected_binding_resolver),
            selected_event_id=decision.event_id,
            decision_reason=decision.reason,
            target_participant_id=target.participant_id,
            target_god_id=target.god_id,
            target_cli_id=target.cli_id,
            binding_revision=_optional_text(binding_resolution.get("binding_revision")),
            account_ref=_optional_text(binding_resolution.get("account_ref")),
            cli_command=_optional_text(binding_resolution.get("cli_command")),
            model=_optional_text(binding_resolution.get("model")),
            variant=_optional_text(binding_resolution.get("variant")),
            blocked_reason=_runtime_gap_reason(
                runtime_continuity,
                target_participant_id=target.participant_id,
            ),
            source_refs=_unique([*decision.source_refs, participant_ref, *binding_source_refs]),
        )

    item_sources = _string_list(runtime_item.get("source_refs"))
    source_refs = _unique(
        [*decision.source_refs, participant_ref, *binding_source_refs, *item_sources]
    )
    waiting_reason = _optional_text(runtime_item.get("waiting_reason"))
    if waiting_reason or runtime_item.get("peer_god_ready") is not True:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            source_authority=_source_authority(selected_binding_resolver),
            selected_event_id=decision.event_id,
            decision_reason=decision.reason,
            target_participant_id=target.participant_id,
            target_god_id=target.god_id,
            target_cli_id=target.cli_id,
            binding_revision=_optional_text(binding_resolution.get("binding_revision")),
            account_ref=_optional_text(binding_resolution.get("account_ref")),
            cli_command=_optional_text(binding_resolution.get("cli_command")),
            model=_optional_text(binding_resolution.get("model")),
            variant=_optional_text(binding_resolution.get("variant")),
            provider_profile_ref=_optional_text(runtime_item.get("provider_profile_ref")),
            provider_session_id=_optional_text(runtime_item.get("provider_session_id")),
            provider_session_kind=_optional_text(
                runtime_item.get("provider_session_kind")
            ),
            provider_binding_status=_optional_text(
                runtime_item.get("provider_binding_status")
            ),
            effective_session_status=_optional_text(
                runtime_item.get("effective_session_status")
            ),
            blocked_reason=waiting_reason or "selected GOD runtime is not ready",
            source_refs=source_refs,
        )

    return GodRoomSpeakerAttemptV1(
        status="ready_for_provider_attempt",
        proof_level="contract_proof",
        source_authority=_source_authority(selected_binding_resolver),
        conversation_id=conversation_id,
        room_id=room_id,
        selected_event_id=decision.event_id,
        decision_reason=decision.reason,
        target_participant_id=target.participant_id,
        target_god_id=target.god_id,
        target_cli_id=target.cli_id,
        binding_revision=_optional_text(binding_resolution.get("binding_revision")),
        account_ref=_optional_text(binding_resolution.get("account_ref")),
        cli_command=_optional_text(binding_resolution.get("cli_command")),
        model=_optional_text(binding_resolution.get("model")),
        variant=_optional_text(binding_resolution.get("variant")),
        provider_profile_ref=_optional_text(runtime_item.get("provider_profile_ref")),
        provider_session_id=_optional_text(runtime_item.get("provider_session_id")),
        provider_session_kind=_optional_text(runtime_item.get("provider_session_kind")),
        provider_binding_status=_optional_text(
            runtime_item.get("provider_binding_status")
        ),
        effective_session_status=_optional_text(
            runtime_item.get("effective_session_status")
        ),
        source_refs=source_refs,
        provider_attempt={
            "prompt_contract": "god_room_next_speaker",
            "delivery_mode": "provider_session_resume",
            "requires_fresh_provider_response": True,
            "proof_level_after_response": "real_provider_proof",
        },
    )


def _select_decision(
    decisions: Sequence[GodRoomTurnDecision],
    *,
    after_event_id: str | None,
) -> GodRoomTurnDecision | None:
    if after_event_id:
        return next(
            (decision for decision in decisions if decision.event_id == after_event_id),
            None,
        )
    return decisions[-1] if decisions else None


def _participant_by_id(
    participants: Sequence[GodRoomParticipant],
) -> dict[str, GodRoomParticipant]:
    return {participant.participant_id: participant for participant in participants}


def _runtime_item_for_participant(
    runtime_continuity: Mapping[str, Any],
    participant_id: str,
) -> Mapping[str, Any] | None:
    items = runtime_continuity.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("participant_id") == participant_id:
            return item
    return None


def _resolve_selected_binding(
    target: GodRoomParticipant,
    *,
    selected_binding_resolver: SelectedBindingResolver | None,
) -> Mapping[str, Any]:
    if selected_binding_resolver is None:
        return {"status": "not_required", "source_refs": []}
    return selected_binding_resolver(target)


def _binding_mismatch(
    target: GodRoomParticipant,
    binding_resolution: Mapping[str, Any],
) -> bool:
    if binding_resolution.get("status") != "resolved":
        return False
    participant_id = _optional_text(binding_resolution.get("participant_id"))
    god_id = _optional_text(binding_resolution.get("god_id"))
    if participant_id is not None and participant_id != target.participant_id:
        return True
    return god_id is not None and god_id != target.god_id


def _source_authority(
    selected_binding_resolver: SelectedBindingResolver | None,
) -> SourceAuthority:
    if selected_binding_resolver is None:
        return "god_room_event_store+selected_god_runtime_continuity"
    return "god_room_event_store+room_selected_god_binding+selected_god_runtime_continuity"


def _runtime_gap_reason(
    runtime_continuity: Mapping[str, Any],
    *,
    target_participant_id: str,
) -> str:
    blockers = runtime_continuity.get("blockers")
    if isinstance(blockers, list):
        for blocker in blockers:
            if not isinstance(blocker, dict):
                continue
            reason = _optional_text(blocker.get("reason"))
            if reason:
                return reason
    return (
        "no selected GOD runtime continuity item matches participant "
        f"{target_participant_id}"
    )


def _manual_gap(
    *,
    conversation_id: str,
    room_id: str,
    blocked_reason: str,
    source_authority: SourceAuthority = "god_room_event_store+selected_god_runtime_continuity",
    selected_event_id: str | None = None,
    decision_reason: str | None = None,
    target_participant_id: str | None = None,
    target_god_id: str | None = None,
    target_cli_id: str | None = None,
    binding_revision: str | None = None,
    account_ref: str | None = None,
    cli_command: str | None = None,
    model: str | None = None,
    variant: str | None = None,
    provider_profile_ref: str | None = None,
    provider_session_id: str | None = None,
    provider_session_kind: str | None = None,
    provider_binding_status: str | None = None,
    effective_session_status: str | None = None,
    source_refs: list[str] | None = None,
) -> GodRoomSpeakerAttemptV1:
    return GodRoomSpeakerAttemptV1(
        status="manual_gap",
        proof_level="manual_gap",
        source_authority=source_authority,
        conversation_id=conversation_id,
        room_id=room_id,
        selected_event_id=selected_event_id,
        decision_reason=decision_reason,
        target_participant_id=target_participant_id,
        target_god_id=target_god_id,
        target_cli_id=target_cli_id,
        binding_revision=binding_revision,
        account_ref=account_ref,
        cli_command=cli_command,
        model=model,
        variant=variant,
        provider_profile_ref=provider_profile_ref,
        provider_session_id=provider_session_id,
        provider_session_kind=provider_session_kind,
        provider_binding_status=provider_binding_status,
        effective_session_status=effective_session_status,
        blocked_reason=blocked_reason,
        source_refs=_unique(source_refs or []),
    )


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


__all__ = ["GodRoomSpeakerAttemptV1", "build_god_room_speaker_attempt"]
