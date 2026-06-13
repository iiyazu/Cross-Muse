from __future__ import annotations

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.chat.god_room_speaker_response import (
    GodRoomProviderSpeechResponseV1,
    capture_god_room_speaker_response,
)
from xmuse_core.chat.god_room_speaker_runtime import build_god_room_speaker_attempt
from xmuse_core.platform.god_runtime_continuity import (
    build_selected_god_runtime_continuity_view,
)
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionRecord
from xmuse_core.providers.god_identity_binding import build_operator_selected_god_binding


def test_speaker_attempt_joins_replay_decision_to_provider_bound_selected_god() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(participant_id="part-review", god_id="review-god"),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]
    continuity = _runtime_view(
        participant_id="part-review",
        provider_session_id="provider-thread-review",
    )

    attempt = build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=continuity,
        after_event_id="evt-propose",
    )

    assert attempt.status == "ready_for_provider_attempt"
    assert attempt.proof_level == "contract_proof"
    assert attempt.source_authority == (
        "god_room_event_store+selected_god_runtime_continuity"
    )
    assert attempt.selected_event_id == "evt-propose"
    assert attempt.decision_reason == "round_robin"
    assert attempt.target_participant_id == "part-review"
    assert attempt.target_god_id == "review-god"
    assert attempt.provider_profile_ref == "codex.god"
    assert attempt.provider_session_id == "provider-thread-review"
    assert attempt.blocked_reason is None
    assert attempt.source_refs == [
        "god-room-event:evt-propose",
        "message:evt-propose",
        "god-room-participant:part-review",
        "god_cli_selection:conv-1",
        "god_cli_registration:codex.god",
        "god_session:god-session-review",
        "provider_session:provider-thread-review",
    ]


def test_speaker_attempt_reports_manual_gap_without_matching_provider_ready_god() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(participant_id="part-review", god_id="review-god"),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]
    continuity = _runtime_view(
        participant_id="part-review",
        provider_session_id=None,
    )

    attempt = build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=continuity,
        after_event_id="evt-propose",
    )

    assert attempt.status == "manual_gap"
    assert attempt.proof_level == "manual_gap"
    assert attempt.target_participant_id == "part-review"
    assert attempt.provider_session_id is None
    assert attempt.blocked_reason == "provider session metadata unavailable"
    assert "provider_session:" not in " ".join(attempt.source_refs)


def test_speaker_attempt_requires_selected_room_binding_when_resolver_is_present() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(participant_id="part-review", god_id="review-god"),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]

    attempt = build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=_runtime_view(
            participant_id="part-review",
            provider_session_id="provider-thread-review",
        ),
        after_event_id="evt-propose",
        selected_binding_resolver=lambda participant: {
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "room_id": "god-room:conv-1",
            "participant_id": participant.participant_id,
            "god_id": participant.god_id,
            "blocked_reason": "room selected GOD binding unavailable",
            "source_refs": [f"god-room-participant:{participant.participant_id}"],
        },
    )

    assert attempt.status == "manual_gap"
    assert attempt.proof_level == "manual_gap"
    assert attempt.source_authority == (
        "god_room_event_store+room_selected_god_binding+selected_god_runtime_continuity"
    )
    assert attempt.provider_session_id is None
    assert attempt.blocked_reason == "room selected GOD binding unavailable"


def test_speaker_attempt_includes_selected_room_binding_lineage() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(participant_id="part-review", god_id="review-god"),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]
    account, profile, binding = build_operator_selected_god_binding(
        room_id="god-room:conv-1",
        participant_id="part-review",
        god_id="review-god",
        account_ref="codex.god",
        cli_command="codex",
        model="gpt-5.4",
        selected_by="operator",
        selected_at="2026-06-14T00:00:00Z",
        capabilities=("peer_god", "review"),
        role="review",
    )

    attempt = build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=_runtime_view(
            participant_id="part-review",
            provider_session_id="provider-thread-review",
        ),
        after_event_id="evt-propose",
        selected_binding_resolver=lambda _participant: {
            "status": "resolved",
            "proof_level": "contract_proof",
            "room_id": binding.room_id,
            "participant_id": binding.participant_id,
            "god_id": binding.god_id,
            "binding_revision": binding.binding_revision,
            "account_ref": binding.account_ref,
            "cli_command": binding.cli_command,
            "model": binding.model,
            "variant": binding.variant,
            "source_refs": [
                binding.binding_ref,
                f"provider_account:{account.account_ref}",
                f"god_profile:{profile.god_id}",
            ],
        },
    )

    assert attempt.status == "ready_for_provider_attempt"
    assert attempt.source_authority == (
        "god_room_event_store+room_selected_god_binding+selected_god_runtime_continuity"
    )
    assert attempt.binding_revision == binding.binding_revision
    assert attempt.account_ref == "codex.god"
    assert attempt.cli_command == "codex"
    assert attempt.model == "gpt-5.4"
    assert binding.binding_ref in attempt.source_refs
    assert "provider_account:codex.god" in attempt.source_refs
    assert "god_profile:review-god" in attempt.source_refs


def test_speaker_attempt_rejects_binding_that_does_not_match_replay_target() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(participant_id="part-review", god_id="review-god"),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]
    account, profile, binding = build_operator_selected_god_binding(
        room_id="god-room:conv-1",
        participant_id="part-review",
        god_id="other-god",
        account_ref="codex.god",
        cli_command="codex",
        model="gpt-5.4",
        selected_by="operator",
        selected_at="2026-06-14T00:00:00Z",
        capabilities=("peer_god", "review"),
        role="review",
    )

    attempt = build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=_runtime_view(
            participant_id="part-review",
            provider_session_id="provider-thread-review",
        ),
        after_event_id="evt-propose",
        selected_binding_resolver=lambda _participant: {
            "status": "resolved",
            "proof_level": "contract_proof",
            "room_id": binding.room_id,
            "participant_id": binding.participant_id,
            "god_id": binding.god_id,
            "binding_revision": binding.binding_revision,
            "account_ref": binding.account_ref,
            "cli_command": binding.cli_command,
            "model": binding.model,
            "source_refs": [
                binding.binding_ref,
                f"provider_account:{account.account_ref}",
                f"god_profile:{profile.god_id}",
            ],
        },
    )

    assert attempt.status == "manual_gap"
    assert attempt.source_authority == (
        "god_room_event_store+room_selected_god_binding+selected_god_runtime_continuity"
    )
    assert attempt.blocked_reason == (
        "room selected GOD binding does not match replay target"
    )
    assert attempt.target_god_id == "review-god"
    assert attempt.account_ref == "codex.god"
    assert binding.binding_ref in attempt.source_refs


def test_speaker_response_appends_real_provider_speak_event() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(
            participant_id="part-review",
            god_id="review-god",
            cli_id="codex",
        ),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]
    appended: list[GodRoomEventV1] = []

    capture = capture_god_room_speaker_response(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=_runtime_view(
            participant_id="part-review",
            provider_session_id="provider-thread-review",
        ),
        provider_response=GodRoomProviderSpeechResponseV1(
            response_id="provider-response-1",
            status="completed",
            proof_level="real_provider_proof",
            target_participant_id="part-review",
            provider_profile_ref="codex.god",
            provider_session_id="provider-thread-review",
            provider_session_kind="provider_thread",
            content="I challenge this path until the provider response is durable.",
            source_refs=["provider-run:codex:provider-response-1"],
        ),
        provider_response_artifact_ref="reports/provider-responses/provider-response-1.json",
        after_event_id="evt-propose",
        event_id="evt-review-provider-speak",
        timestamp_utc="2026-06-13T10:02:00Z",
        append_event=lambda event: appended.append(event) or "created",
    )

    assert capture.status == "speak_event_appended"
    assert capture.proof_level == "real_provider_proof"
    assert capture.append_status == "created"
    assert capture.blocked_reason is None
    assert capture.speak_event is not None
    assert capture.speak_event.event_id == "evt-review-provider-speak"
    assert capture.speak_event.event_type is GodRoomEventKind.SPEAK
    assert capture.speak_event.actor_kind is GodRoomActorKind.GOD
    assert capture.speak_event.participant_id == "part-review"
    assert capture.speak_event.god_id == "review-god"
    assert capture.speak_event.provider_profile == "codex.god"
    assert capture.speak_event.causal_parent_id == "evt-propose"
    assert capture.speak_event.content == (
        "I challenge this path until the provider response is durable."
    )
    assert capture.speak_event.source_refs == [
        "god-room-event:evt-propose",
        "message:evt-propose",
        "god-room-participant:part-review",
        "god_cli_selection:conv-1",
        "god_cli_registration:codex.god",
        "god_session:god-session-review",
        "provider_session:provider-thread-review",
        "provider-run:codex:provider-response-1",
        "provider_response_artifact:reports/provider-responses/provider-response-1.json",
    ]
    assert appended == [capture.speak_event]


def test_speaker_response_keeps_manual_gap_without_structured_provider_speech() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(participant_id="part-review", god_id="review-god"),
    ]
    events = [
        _event(
            "evt-propose",
            participant_id="part-architect",
            god_id="architect-god",
        )
    ]
    appended: list[GodRoomEventV1] = []

    capture = capture_god_room_speaker_response(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=participants,
        events=events,
        runtime_continuity=_runtime_view(
            participant_id="part-review",
            provider_session_id="provider-thread-review",
        ),
        provider_response=GodRoomProviderSpeechResponseV1(
            response_id="provider-response-1",
            status="completed",
            proof_level="real_provider_proof",
            target_participant_id="part-review",
            provider_profile_ref="codex.god",
            provider_session_id="provider-thread-review",
            provider_session_kind="provider_thread",
            content=None,
            source_refs=["provider-run:codex:provider-response-1"],
        ),
        provider_response_artifact_ref="reports/provider-responses/provider-response-1.json",
        after_event_id="evt-propose",
        event_id="evt-review-provider-speak",
        timestamp_utc="2026-06-13T10:02:00Z",
        append_event=lambda event: appended.append(event) or "created",
    )

    assert capture.status == "manual_gap"
    assert capture.proof_level == "manual_gap"
    assert capture.blocked_reason == "provider response content missing"
    assert capture.speak_event is None
    assert appended == []


def _runtime_view(
    *,
    participant_id: str,
    provider_session_id: str | None,
) -> dict[str, object]:
    return build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[
            GodCliSelectionRecord(
                conversation_id="conv-1",
                cli_id="codex.god",
                selected_by="operator",
                audit_id="audit-select-1",
                idempotency_key="select:codex.god",
                selected_at_utc="2026-06-13T00:00:00Z",
            )
        ],
        sessions=[
            GodSessionRecord(
                god_session_id="god-session-review",
                role="review",
                agent_name="codex.god",
                runtime="codex",
                session_address="@review",
                session_inbox_id="inbox-review",
                conversation_id="conv-1",
                participant_id=participant_id,
                status="starting" if provider_session_id is not None else "active",
                model="gpt-5.4",
                provider_session_id=provider_session_id,
                provider_session_kind=(
                    "provider_thread" if provider_session_id is not None else None
                ),
                provider_binding_status="active"
                if provider_session_id is not None
                else None,
            )
        ],
        god_cli_registry=build_default_god_cli_registry(),
    )


def _event(
    event_id: str,
    *,
    participant_id: str,
    god_id: str,
) -> GodRoomEventV1:
    return GodRoomEventV1(
        event_id=event_id,
        room_id="god-room:conv-1",
        conversation_id="conv-1",
        participant_id=participant_id,
        god_id=god_id,
        actor_kind=GodRoomActorKind.GOD,
        event_type=GodRoomEventKind.SPEAK,
        timestamp_utc="2026-06-13T10:00:00Z",
        content="I propose the next GOD reviews this production path.",
        source_refs=["message:evt-propose"],
        cli_id="codex",
        provider_profile="codex.god",
        payload={"body": "I propose the next GOD reviews this production path."},
    )
