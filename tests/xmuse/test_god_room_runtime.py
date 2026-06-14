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
    assert replay.event_proofs[0].proof_level == "contract_proof"


def test_replay_god_room_turns_projects_event_proof_lineage_without_upgrading_room_proof() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
        GodRoomParticipant(participant_id="part-review", god_id="god-review"),
    ]
    events = [
        _event(
            "evt-1-public-gap",
            payload={
                "body": "Manual transcript when selected binding is unresolved.",
                "public_append_authority": {
                    "schema_version": "xmuse.god_room_public_append_authority.v1",
                    "source_authority": (
                        "chat_api_public_event_append+room_selected_god_binding_manual_gap"
                    ),
                    "status": "manual_gap",
                    "proof_level": "manual_gap",
                    "room_id": "room-1",
                    "participant_id": "part-architect",
                    "god_id": "god-architect",
                    "binding_revision": None,
                    "account_ref": None,
                    "cli_command": None,
                    "model": None,
                    "variant": None,
                    "blocked_reason": "room selected GOD binding unresolved",
                    "source_refs": [],
                    "manual_gaps": ["room_selected_god_binding_unresolved"],
                    "forbidden_claims": [
                        "provider_invocation_live_proof",
                        "capture_equals_invocation_proof",
                        "natural_groupchat_closure",
                    ],
                },
            },
        ),
        _event(
            "evt-2-public-bound",
            payload={
                "body": "Contract transcript from selected room GOD binding.",
                "public_append_authority": {
                    "schema_version": "xmuse.god_room_public_append_authority.v1",
                    "source_authority": (
                        "chat_api_public_event_append+room_selected_god_binding"
                    ),
                    "status": "resolved",
                    "proof_level": "contract_proof",
                    "room_id": "room-1",
                    "participant_id": "part-architect",
                    "god_id": "god-architect",
                    "binding_revision": "binding:god-room:conv-1:part-architect:1",
                    "account_ref": "codex.god",
                    "cli_command": "codex",
                    "model": "gpt-5.4",
                    "variant": None,
                    "blocked_reason": None,
                    "source_refs": ["provider-account:codex.god"],
                    "manual_gaps": [],
                    "forbidden_claims": [
                        "provider_invocation_live_proof",
                        "capture_equals_invocation_proof",
                        "natural_groupchat_closure",
                    ],
                },
            },
        ),
        _event(
            "evt-3-provider-speak",
            participant_id="part-review",
            god_id="god-review",
            causal_parent_id="evt-2-public-bound",
            source_refs=[
                "god-room-speaker-attempt:evt-2-public-bound",
                "provider-run:codex:provider-response-1",
                "provider_response_artifact:reports/provider-responses/provider-response-1.json",
            ],
            payload={
                "body": "Provider-backed review speech.",
                "provider_response_id": "provider-response-1",
                "provider_response_artifact_ref": (
                    "reports/provider-responses/provider-response-1.json"
                ),
                "provider_session_id": "provider-thread-review",
                "provider_session_kind": "provider_thread",
                "provider_profile_ref": "codex.god",
                "binding_revision": "binding:god-room:conv-1:part-review:1",
                "account_ref": "codex.god",
                "cli_command": "codex",
                "model": "gpt-5.4",
                "variant": None,
                "proof_level": "real_provider_proof",
                "speaker_attempt_event_id": "evt-2-public-bound",
            },
        ),
    ]

    replay = replay_god_room_turns(participants=participants, events=events)

    assert replay.status == "ok"
    assert replay.proof_level == "contract_proof"
    assert [
        (proof.event_id, proof.proof_level, proof.source_authority)
        for proof in replay.event_proofs
    ] == [
        (
            "evt-1-public-gap",
            "manual_gap",
            "chat_api_public_event_append+room_selected_god_binding_manual_gap",
        ),
        (
            "evt-2-public-bound",
            "contract_proof",
            "chat_api_public_event_append+room_selected_god_binding",
        ),
        (
            "evt-3-provider-speak",
            "opt_in_live_proof",
            "god_room_speaker_response_capture+provider_response_artifact",
        ),
    ]
    provider_proof = replay.event_proofs[2]
    assert provider_proof.projection_only is True
    assert provider_proof.provider_response_artifact_ref == (
        "reports/provider-responses/provider-response-1.json"
    )
    assert provider_proof.artifact_proof_level == "real_provider_proof"
    assert provider_proof.binding_revision == "binding:god-room:conv-1:part-review:1"
    assert "capture_equals_invocation_proof" in provider_proof.forbidden_claims


def test_replay_god_room_turns_treats_empty_public_append_authority_as_manual_gap() -> None:
    participants = [
        GodRoomParticipant(participant_id="part-architect", god_id="god-architect"),
    ]
    replay = replay_god_room_turns(
        participants=participants,
        events=[
            _event(
                "evt-empty-authority",
                payload={
                    "body": "Malformed authority projection must fail closed.",
                    "public_append_authority": {},
                },
            )
        ],
    )

    assert replay.status == "ok"
    assert replay.proof_level == "contract_proof"
    assert replay.event_proofs[0].proof_level == "manual_gap"
    assert replay.event_proofs[0].source_authority == (
        "chat_api_public_event_append+room_selected_god_binding_manual_gap"
    )


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
