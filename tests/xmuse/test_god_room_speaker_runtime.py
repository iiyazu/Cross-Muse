from __future__ import annotations

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.chat.god_room_speaker_runtime import build_god_room_speaker_attempt
from xmuse_core.platform.god_runtime_continuity import (
    build_selected_god_runtime_continuity_view,
)
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionRecord


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
