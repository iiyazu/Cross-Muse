from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.chat.god_room_provider_invocation import (
    ProviderCommandResult,
    invoke_god_room_provider_speech,
)
from xmuse_core.chat.god_room_runtime import (
    GodRoomActorKind,
    GodRoomEventKind,
    GodRoomEventV1,
    GodRoomParticipant,
)
from xmuse_core.chat.god_room_speaker_response import (
    capture_god_room_speaker_response,
)
from xmuse_core.chat.god_room_speaker_runtime import (
    GodRoomSpeakerAttemptV1,
    build_god_room_speaker_attempt,
)
from xmuse_core.providers.god_identity_binding import build_operator_selected_god_binding


def test_provider_invocation_emits_contract_artifact_from_selected_binding(
    tmp_path: Path,
) -> None:
    attempt = _ready_attempt(
        cli_command="opencode",
        model="opencode-go/deepseek-v4-flash",
        variant="max",
    )
    calls: list[tuple[tuple[str, ...], str | None, Path, int]] = []

    def runner(command, stdin_text, workspace, timeout_seconds):
        calls.append((tuple(command), stdin_text, workspace, timeout_seconds))
        return ProviderCommandResult(
            returncode=0,
            stdout='{"content": "I challenge the missing invocation path.", '
            '"source_refs": ["provider-run:opencode:1"], '
            '"provider_session_id": "provider-thread-review"}\n',
        )

    response = invoke_god_room_provider_speech(
        attempt=attempt,
        prompt="Respond with structured GOD speech.",
        workspace=tmp_path,
        timeout_seconds=90,
        prompt_refs=["prompt:god-room:evt-propose"],
        timestamp_factory=_clock(),
        runner=runner,
    )

    assert response.schema_version == "xmuse.god_room_provider_speech_response.v1"
    assert response.status == "completed"
    assert response.proof_level == "contract_proof"
    assert response.content == "I challenge the missing invocation path."
    assert response.target_participant_id == "part-review"
    assert response.target_god_id == "review-god"
    assert response.binding_revision == "binding:god-room:conv-1:part-review:1"
    assert response.account_ref == "opencode.god"
    assert response.cli_command == "opencode"
    assert response.model == "opencode-go/deepseek-v4-flash"
    assert response.variant == "max"
    assert response.provider_session_id == "provider-thread-review"
    assert "provider-run:opencode:1" in response.source_refs
    assert calls == [
        (
            (
                "opencode",
                "run",
                "--model",
                "opencode-go/deepseek-v4-flash",
                "--variant",
                "max",
                "--format",
                "json",
                "--dir",
                str(tmp_path),
                "Respond with structured GOD speech.",
            ),
            None,
            tmp_path,
            90,
        )
    ]


def test_provider_invocation_does_not_let_contract_artifact_auto_capture_speech(
    tmp_path: Path,
) -> None:
    attempt = _ready_attempt(
        cli_command="opencode",
        model="opencode-go/deepseek-v4-flash",
        variant="max",
    )
    response = invoke_god_room_provider_speech(
        attempt=attempt,
        prompt="Respond with structured GOD speech.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        runner=lambda *_: ProviderCommandResult(
            returncode=0,
            stdout='{"content": "Contract proof is not live proof."}',
        ),
    )
    appended: list[GodRoomEventV1] = []

    capture = capture_god_room_speaker_response(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=_participants(),
        events=_events(),
        runtime_continuity=_runtime_view(provider_session_id="provider-thread-review"),
        provider_response=response,
        provider_response_artifact_ref="reports/provider-responses/response.json",
        after_event_id="evt-propose",
        timestamp_utc="2026-06-14T00:00:03Z",
        append_event=lambda event: appended.append(event) or "created",
        selected_binding_resolver=_binding_resolver(
            cli_command="opencode",
            model="opencode-go/deepseek-v4-flash",
            variant="max",
        ),
    )

    assert capture.status == "manual_gap"
    assert capture.blocked_reason == "provider response proof level is contract_proof"
    assert appended == []


def test_provider_invocation_fails_closed_without_selected_binding(
    tmp_path: Path,
) -> None:
    attempt = build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=_participants(),
        events=_events(),
        runtime_continuity=_runtime_view(provider_session_id="provider-thread-review"),
        after_event_id="evt-propose",
        selected_binding_resolver=lambda participant: {
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "room_id": "god-room:conv-1",
            "participant_id": participant.participant_id,
            "god_id": participant.god_id,
            "blocked_reason": "provider account unavailable: opencode.god",
            "source_refs": [f"god-room-participant:{participant.participant_id}"],
        },
    )
    calls: list[object] = []

    response = invoke_god_room_provider_speech(
        attempt=attempt,
        prompt="Should not run.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        runner=lambda *args: calls.append(args) or ProviderCommandResult(returncode=0),
    )

    assert response.status == "blocked"
    assert response.proof_level == "manual_gap"
    assert response.failure_kind == "manual_gap"
    assert response.blocked_reason == "provider account unavailable: opencode.god"
    assert response.command == []
    assert calls == []


def test_provider_invocation_records_raw_archive_only_for_unstructured_output(
    tmp_path: Path,
) -> None:
    response = invoke_god_room_provider_speech(
        attempt=_ready_attempt(
            cli_command="opencode",
            model="opencode-go/deepseek-v4-flash",
            variant="max",
        ),
        prompt="Respond with JSON.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        runner=lambda *_: ProviderCommandResult(
            returncode=0,
            stdout="plain terminal output, not structured speech",
        ),
    )

    assert response.status == "blocked"
    assert response.proof_level == "manual_gap"
    assert response.failure_kind == "raw_archive_only"
    assert response.blocked_reason == (
        "raw_archive_only: provider output is not structured speech"
    )
    assert response.content is None
    assert response.raw_output_digest is not None
    assert response.output_refs == [
        f"provider_raw_output_sha256:{response.raw_output_digest}"
    ]


def test_provider_invocation_records_timeout_without_live_claim(
    tmp_path: Path,
) -> None:
    def runner(*_):
        raise subprocess.TimeoutExpired(cmd=("opencode", "run"), timeout=90)

    response = invoke_god_room_provider_speech(
        attempt=_ready_attempt(
            cli_command="opencode",
            model="opencode-go/deepseek-v4-flash",
            variant="max",
        ),
        prompt="Respond with JSON.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        runner=runner,
    )

    assert response.status == "failed"
    assert response.proof_level == "manual_gap"
    assert response.failure_kind == "invocation_timeout"
    assert response.blocked_reason == "invocation_timeout"


def test_provider_invocation_records_missing_cli_without_live_claim(
    tmp_path: Path,
) -> None:
    def runner(*_):
        raise FileNotFoundError("opencode not installed")

    response = invoke_god_room_provider_speech(
        attempt=_ready_attempt(
            cli_command="opencode",
            model="opencode-go/deepseek-v4-flash",
            variant="max",
        ),
        prompt="Respond with JSON.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        runner=runner,
    )

    assert response.status == "blocked"
    assert response.proof_level == "manual_gap"
    assert response.failure_kind == "missing_cli_binary"
    assert response.blocked_reason == "provider CLI unavailable: opencode"


def test_provider_invocation_records_nonzero_exit_without_live_claim(
    tmp_path: Path,
) -> None:
    response = invoke_god_room_provider_speech(
        attempt=_ready_attempt(
            cli_command="opencode",
            model="opencode-go/deepseek-v4-flash",
            variant="max",
        ),
        prompt="Respond with JSON.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        runner=lambda *_: ProviderCommandResult(
            returncode=2,
            stdout="",
            stderr="provider failed",
        ),
    )

    assert response.status == "failed"
    assert response.proof_level == "manual_gap"
    assert response.failure_kind == "nonzero_exit"
    assert response.blocked_reason == "invocation_failed"
    assert response.exit_code == 2


def test_provider_invocation_extracts_codex_session_id_from_live_output(
    tmp_path: Path,
) -> None:
    response = invoke_god_room_provider_speech(
        attempt=_ready_attempt(
            cli_command="codex",
            model="gpt-5.4",
            variant=None,
        ),
        prompt="Respond with JSON.",
        workspace=tmp_path,
        timeout_seconds=90,
        timestamp_factory=_clock(),
        allow_live_provider_proof=True,
        runner=lambda *_: ProviderCommandResult(
            returncode=0,
            stdout='{"content": "Live Codex output is structured."}\n',
            stderr=(
                "OpenAI Codex v0.139.0\n"
                "session id: 019ec421-536e-7722-b2bc-9ed1e3863586\n"
            ),
        ),
    )

    assert response.status == "completed"
    assert response.proof_level == "real_provider_proof"
    assert (
        response.provider_session_id
        == "019ec421-536e-7722-b2bc-9ed1e3863586"
    )
    assert response.content == "Live Codex output is structured."


def _ready_attempt(
    *,
    cli_command: str,
    model: str,
    variant: str | None,
) -> GodRoomSpeakerAttemptV1:
    return build_god_room_speaker_attempt(
        conversation_id="conv-1",
        room_id="god-room:conv-1",
        participants=_participants(),
        events=_events(),
        runtime_continuity=_runtime_view(provider_session_id="provider-thread-review"),
        after_event_id="evt-propose",
        selected_binding_resolver=_binding_resolver(
            cli_command=cli_command,
            model=model,
            variant=variant,
        ),
    )


def _binding_resolver(
    *,
    cli_command: str,
    model: str,
    variant: str | None,
):
    account_ref = f"{cli_command}.god"
    account, profile, binding = build_operator_selected_god_binding(
        room_id="god-room:conv-1",
        participant_id="part-review",
        god_id="review-god",
        account_ref=account_ref,
        cli_command=cli_command,
        model=model,
        variant=variant,
        selected_by="operator",
        selected_at="2026-06-14T00:00:00Z",
        role="review",
        capabilities=("peer_god", "review"),
    )

    def resolve(_participant: GodRoomParticipant) -> dict[str, object]:
        return {
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
        }

    return resolve


def _participants() -> list[GodRoomParticipant]:
    return [
        GodRoomParticipant(participant_id="part-architect", god_id="architect-god"),
        GodRoomParticipant(
            participant_id="part-review",
            god_id="review-god",
            cli_id="opencode",
        ),
    ]


def _events() -> list[GodRoomEventV1]:
    return [
        GodRoomEventV1(
            event_id="evt-propose",
            room_id="god-room:conv-1",
            conversation_id="conv-1",
            participant_id="part-architect",
            god_id="architect-god",
            actor_kind=GodRoomActorKind.GOD,
            event_type=GodRoomEventKind.SPEAK,
            timestamp_utc="2026-06-14T00:00:00Z",
            content="I propose asking the review GOD for a provider response.",
            source_refs=["message:evt-propose"],
            cli_id="codex",
            provider_profile="codex.god",
            payload={"body": "I propose asking the review GOD."},
        )
    ]


def _runtime_view(*, provider_session_id: str | None) -> dict[str, object]:
    if provider_session_id is None:
        return {
            "conversation_id": "conv-1",
            "status": "manual_gap",
            "items": [],
            "blockers": [{"reason": "provider session metadata unavailable"}],
        }
    return {
        "conversation_id": "conv-1",
        "status": "ready",
        "items": [
            {
                "participant_id": "part-review",
                "peer_god_ready": True,
                "provider_profile_ref": "opencode.god",
                "provider_session_id": provider_session_id,
                "provider_session_kind": "provider_thread",
                "provider_binding_status": "active",
                "effective_session_status": "active",
                "source_refs": [
                    "god_cli_selection:conv-1",
                    "god_session:god-session-review",
                    f"provider_session:{provider_session_id}",
                ],
            }
        ],
        "blockers": [],
    }


def _clock():
    values = iter(
        [
            datetime(2026, 6, 14, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 6, 14, 0, 0, 2, tzinfo=UTC),
        ]
    )
    return lambda: next(values)
