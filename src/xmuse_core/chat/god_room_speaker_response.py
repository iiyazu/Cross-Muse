from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.chat.god_room_speaker_runtime import (
    GodRoomSpeakerAttemptV1,
    SelectedBindingResolver,
    build_god_room_speaker_attempt,
)

ProviderResponseStatus = Literal["completed", "blocked", "failed"]
ProofLevel = Literal["real_provider_proof", "contract_proof", "manual_gap"]
CaptureStatus = Literal["speak_event_appended", "event_appended", "manual_gap"]
AppendStatus = Literal["created", "duplicate"]
SourceAuthority = Literal[
    "god_room_event_store+selected_god_runtime_continuity+provider_response"
]
ProviderBackedEventKind = Literal[
    GodRoomEventKind.SPEAK,
    GodRoomEventKind.QUESTION,
    GodRoomEventKind.CHALLENGE,
    GodRoomEventKind.HANDOFF,
]


class GodRoomProviderSpeechResponseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xmuse.god_room_provider_speech_response.v1"] = (
        "xmuse.god_room_provider_speech_response.v1"
    )
    response_id: str
    status: ProviderResponseStatus
    proof_level: ProofLevel
    target_participant_id: str
    provider_profile_ref: str
    provider_session_id: str
    provider_session_kind: str | None = None
    content: str | None = None
    source_refs: list[str] = Field(min_length=1)
    conversation_id: str | None = None
    room_id: str | None = None
    target_god_id: str | None = None
    binding_revision: str | None = None
    account_ref: str | None = None
    cli_command: str | None = None
    model: str | None = None
    variant: str | None = None
    invocation_id: str | None = None
    invocation_status: str | None = None
    command: list[str] = Field(default_factory=list)
    started_at_utc: str | None = None
    completed_at_utc: str | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    prompt_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    raw_output_digest: str | None = None
    blocked_reason: str | None = None
    failure_kind: str | None = None

    @field_validator(
        "response_id",
        "target_participant_id",
        "provider_profile_ref",
        "provider_session_id",
    )
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("provider_session_kind", "content")
    @classmethod
    def _validate_optional_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "field")

    @field_validator(
        "conversation_id",
        "room_id",
        "target_god_id",
        "binding_revision",
        "account_ref",
        "cli_command",
        "model",
        "variant",
        "invocation_id",
        "invocation_status",
        "started_at_utc",
        "completed_at_utc",
        "raw_output_digest",
        "blocked_reason",
        "failure_kind",
    )
    @classmethod
    def _validate_optional_lineage_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name or "field")

    @field_validator("source_refs", "command", "prompt_refs", "output_refs")
    @classmethod
    def _validate_source_refs(cls, value: list[str]) -> list[str]:
        return _unique([_require_non_empty(item, "source_refs") for item in value])


class GodRoomSpeakerResponseCaptureV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xmuse.god_room_speaker_response.v1"] = (
        "xmuse.god_room_speaker_response.v1"
    )
    status: CaptureStatus
    proof_level: Literal["real_provider_proof", "manual_gap"]
    source_authority: SourceAuthority = (
        "god_room_event_store+selected_god_runtime_continuity+provider_response"
    )
    conversation_id: str
    room_id: str
    selected_event_id: str | None = None
    target_participant_id: str | None = None
    target_god_id: str | None = None
    binding_revision: str | None = None
    account_ref: str | None = None
    cli_command: str | None = None
    model: str | None = None
    variant: str | None = None
    provider_profile_ref: str | None = None
    provider_session_id: str | None = None
    provider_session_kind: str | None = None
    provider_response_artifact_ref: str | None = None
    append_status: AppendStatus | None = None
    blocked_reason: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    speaker_attempt: GodRoomSpeakerAttemptV1
    provider_response: GodRoomProviderSpeechResponseV1 | None = None
    event_type: GodRoomEventKind | None = None
    target_participant_ids: list[str] = Field(default_factory=list)
    appended_event: GodRoomEventV1 | None = None
    speak_event: GodRoomEventV1 | None = None


def capture_god_room_speaker_response(
    *,
    conversation_id: str,
    room_id: str,
    participants: Sequence[GodRoomParticipant],
    events: Sequence[GodRoomEventV1],
    runtime_continuity: Mapping[str, object],
    provider_response: GodRoomProviderSpeechResponseV1 | None,
    provider_response_artifact_ref: str | None,
    append_event: Callable[[GodRoomEventV1], AppendStatus],
    after_event_id: str | None = None,
    event_id: str | None = None,
    event_type: ProviderBackedEventKind = GodRoomEventKind.SPEAK,
    target_participant_ids: Sequence[str] = (),
    selected_binding_resolver: SelectedBindingResolver | None = None,
    timestamp_utc: str,
) -> GodRoomSpeakerResponseCaptureV1:
    attempt = build_god_room_speaker_attempt(
        conversation_id=conversation_id,
        room_id=room_id,
        participants=participants,
        events=events,
        runtime_continuity=runtime_continuity,
        after_event_id=after_event_id,
        selected_binding_resolver=selected_binding_resolver,
    )
    if attempt.status != "ready_for_provider_attempt":
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            attempt=attempt,
            provider_response=provider_response,
            event_type=event_type,
            target_participant_ids=target_participant_ids,
            blocked_reason=attempt.blocked_reason
            or "speaker attempt is not ready for provider response capture",
        )
    if provider_response is None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            attempt=attempt,
            provider_response=None,
            event_type=event_type,
            target_participant_ids=target_participant_ids,
            blocked_reason="provider response missing",
        )
    blocked_reason = _provider_response_gap(attempt, provider_response)
    if blocked_reason is not None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            attempt=attempt,
            provider_response=provider_response,
            event_type=event_type,
            target_participant_ids=target_participant_ids,
            blocked_reason=blocked_reason,
        )
    artifact_ref = _optional_text(provider_response_artifact_ref)
    if artifact_ref is None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            attempt=attempt,
            provider_response=provider_response,
            event_type=event_type,
            target_participant_ids=target_participant_ids,
            blocked_reason="provider response artifact missing",
        )
    target_ids = _unique(
        [
            _require_non_empty(target_id, "target_participant_ids")
            for target_id in target_participant_ids
        ]
    )
    event_shape_gap = _provider_backed_event_shape_gap(
        event_type=event_type,
        target_participant_ids=target_ids,
        selected_event_id=attempt.selected_event_id,
        participants=participants,
    )
    if event_shape_gap is not None:
        return _manual_gap(
            conversation_id=conversation_id,
            room_id=room_id,
            attempt=attempt,
            provider_response=provider_response,
            event_type=event_type,
            target_participant_ids=target_ids,
            blocked_reason=event_shape_gap,
        )

    event = _build_provider_backed_event(
        conversation_id=conversation_id,
        room_id=room_id,
        attempt=attempt,
        provider_response=provider_response,
        provider_response_artifact_ref=artifact_ref,
        event_id=event_id,
        event_type=event_type,
        target_participant_ids=target_ids,
        timestamp_utc=timestamp_utc,
    )
    append_status = append_event(event)
    return GodRoomSpeakerResponseCaptureV1(
        status=(
            "speak_event_appended"
            if event_type is GodRoomEventKind.SPEAK
            else "event_appended"
        ),
        proof_level="real_provider_proof",
        conversation_id=conversation_id,
        room_id=room_id,
        selected_event_id=attempt.selected_event_id,
        target_participant_id=attempt.target_participant_id,
        target_god_id=attempt.target_god_id,
        binding_revision=attempt.binding_revision,
        account_ref=attempt.account_ref,
        cli_command=attempt.cli_command,
        model=attempt.model,
        variant=attempt.variant,
        provider_profile_ref=attempt.provider_profile_ref,
        provider_session_id=attempt.provider_session_id,
        provider_session_kind=attempt.provider_session_kind,
        provider_response_artifact_ref=artifact_ref,
        append_status=append_status,
        event_type=event_type,
        target_participant_ids=target_ids,
        source_refs=_unique(
            [
                *attempt.source_refs,
                *provider_response.source_refs,
                f"provider_response_artifact:{artifact_ref}",
            ]
        ),
        speaker_attempt=attempt,
        provider_response=provider_response,
        appended_event=event,
        speak_event=event if event_type is GodRoomEventKind.SPEAK else None,
    )


def _provider_response_gap(
    attempt: GodRoomSpeakerAttemptV1,
    response: GodRoomProviderSpeechResponseV1,
) -> str | None:
    if response.target_participant_id != attempt.target_participant_id:
        return "provider response target participant mismatch"
    if response.provider_profile_ref != attempt.provider_profile_ref:
        return "provider response profile mismatch"
    if response.provider_session_id != attempt.provider_session_id:
        return "provider response session mismatch"
    if response.status != "completed":
        return f"provider response status is {response.status}"
    if response.proof_level != "real_provider_proof":
        return f"provider response proof level is {response.proof_level}"
    if not _optional_text(response.content):
        return "provider response content missing"
    return None


def _provider_backed_event_shape_gap(
    *,
    event_type: ProviderBackedEventKind,
    target_participant_ids: Sequence[str],
    selected_event_id: str | None,
    participants: Sequence[GodRoomParticipant],
) -> str | None:
    if event_type is GodRoomEventKind.SPEAK:
        return None
    if event_type not in {
        GodRoomEventKind.QUESTION,
        GodRoomEventKind.CHALLENGE,
        GodRoomEventKind.HANDOFF,
    }:
        return f"provider-backed event type {event_type.value} is not capturable"
    if not target_participant_ids:
        return f"{event_type.value} capture requires target_participant_ids"
    participant_ids = {participant.participant_id for participant in participants}
    missing_targets = [
        target_id for target_id in target_participant_ids if target_id not in participant_ids
    ]
    if missing_targets:
        return f"{event_type.value} capture target not in room: {missing_targets[0]}"
    if event_type is GodRoomEventKind.CHALLENGE and selected_event_id is None:
        return "challenge capture requires after_event_id causal parent"
    return None


def _build_provider_backed_event(
    *,
    conversation_id: str,
    room_id: str,
    attempt: GodRoomSpeakerAttemptV1,
    provider_response: GodRoomProviderSpeechResponseV1,
    provider_response_artifact_ref: str,
    event_id: str | None,
    event_type: ProviderBackedEventKind,
    target_participant_ids: Sequence[str],
    timestamp_utc: str,
) -> GodRoomEventV1:
    if attempt.target_participant_id is None or attempt.target_god_id is None:
        raise ValueError("speaker attempt target identity is incomplete")
    content = _optional_text(provider_response.content)
    if content is None:
        raise ValueError("provider response content missing")
    stable_event_id = _optional_text(event_id) or _default_event_id(
        attempt=attempt,
        provider_response=provider_response,
        event_type=event_type,
    )
    return GodRoomEventV1(
        event_id=stable_event_id,
        room_id=room_id,
        conversation_id=conversation_id,
        participant_id=attempt.target_participant_id,
        god_id=attempt.target_god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=event_type,
        timestamp_utc=timestamp_utc,
        content=content,
        target_participant_ids=list(target_participant_ids),
        causal_parent_id=attempt.selected_event_id,
        source_refs=_unique(
            [
                *attempt.source_refs,
                *provider_response.source_refs,
                f"provider_response_artifact:{provider_response_artifact_ref}",
            ]
        ),
        cli_id=attempt.target_cli_id,
        provider_profile=attempt.provider_profile_ref,
        payload={
            "body": content,
            "event_type": event_type.value,
            "target_participant_ids": list(target_participant_ids),
            "provider_response_id": provider_response.response_id,
            "provider_response_artifact_ref": provider_response_artifact_ref,
            "provider_session_id": provider_response.provider_session_id,
            "provider_session_kind": provider_response.provider_session_kind,
            "provider_profile_ref": provider_response.provider_profile_ref,
            "binding_revision": attempt.binding_revision,
            "account_ref": attempt.account_ref,
            "cli_command": attempt.cli_command,
            "model": attempt.model,
            "variant": attempt.variant,
            "proof_level": provider_response.proof_level,
            "speaker_attempt_event_id": attempt.selected_event_id,
        },
    )


def _manual_gap(
    *,
    conversation_id: str,
    room_id: str,
    attempt: GodRoomSpeakerAttemptV1,
    provider_response: GodRoomProviderSpeechResponseV1 | None,
    event_type: GodRoomEventKind | None = None,
    target_participant_ids: Sequence[str] = (),
    blocked_reason: str,
) -> GodRoomSpeakerResponseCaptureV1:
    response_refs = provider_response.source_refs if provider_response is not None else []
    return GodRoomSpeakerResponseCaptureV1(
        status="manual_gap",
        proof_level="manual_gap",
        conversation_id=conversation_id,
        room_id=room_id,
        selected_event_id=attempt.selected_event_id,
        target_participant_id=attempt.target_participant_id,
        target_god_id=attempt.target_god_id,
        binding_revision=attempt.binding_revision,
        account_ref=attempt.account_ref,
        cli_command=attempt.cli_command,
        model=attempt.model,
        variant=attempt.variant,
        provider_profile_ref=attempt.provider_profile_ref,
        provider_session_id=attempt.provider_session_id,
        provider_session_kind=attempt.provider_session_kind,
        provider_response_artifact_ref=None,
        blocked_reason=blocked_reason,
        event_type=event_type,
        target_participant_ids=list(target_participant_ids),
        source_refs=_unique([*attempt.source_refs, *response_refs]),
        speaker_attempt=attempt,
        provider_response=provider_response,
    )


def _default_event_id(
    *,
    attempt: GodRoomSpeakerAttemptV1,
    provider_response: GodRoomProviderSpeechResponseV1,
    event_type: ProviderBackedEventKind,
) -> str:
    seed = {
        "selected_event_id": attempt.selected_event_id,
        "target_participant_id": attempt.target_participant_id,
        "provider_response_id": provider_response.response_id,
        "event_type": event_type.value,
    }
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()[:16]
    return f"provider-event-{digest}"


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


__all__ = [
    "GodRoomProviderSpeechResponseV1",
    "GodRoomSpeakerResponseCaptureV1",
    "capture_god_room_speaker_response",
]
