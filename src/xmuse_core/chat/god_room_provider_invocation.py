from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.god_room_speaker_response import (
    GodRoomProviderSpeechResponseV1,
)
from xmuse_core.chat.god_room_speaker_runtime import GodRoomSpeakerAttemptV1

ProviderCommandRunner = Callable[
    [Sequence[str], str | None, Path, int],
    "ProviderCommandResult",
]


@dataclass(frozen=True)
class ProviderCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def invoke_god_room_provider_speech(
    *,
    attempt: GodRoomSpeakerAttemptV1,
    prompt: str,
    workspace: Path,
    timeout_seconds: int,
    prompt_refs: Sequence[str] = (),
    timestamp_factory: Callable[[], datetime] | None = None,
    runner: ProviderCommandRunner | None = None,
    allow_live_provider_proof: bool = False,
) -> GodRoomProviderSpeechResponseV1:
    """Invoke the selected provider/GOD and emit an L4 speech response artifact.

    This function produces only the provider response artifact. Converting that
    artifact into durable GOD room speech remains the separate L5 capture gate.
    """

    clock = timestamp_factory or (lambda: datetime.now(UTC))
    started = clock()
    started_at = _format_utc(started)
    invocation_id = _invocation_id(attempt=attempt, prompt=prompt, started_at=started_at)
    base = _base_payload(
        attempt=attempt,
        invocation_id=invocation_id,
        started_at_utc=started_at,
        prompt_refs=list(prompt_refs),
    )
    required_gap = _required_attempt_gap(attempt)
    if required_gap is not None:
        return _blocked_response(
            base,
            blocked_reason=required_gap,
            completed_at_utc=started_at,
            duration_ms=0,
            failure_kind="manual_gap",
        )

    command, stdin_text, command_gap = _build_command(
        cli_command=attempt.cli_command or "",
        model=attempt.model or "",
        variant=attempt.variant,
        workspace=workspace,
        prompt=prompt,
    )
    base["command"] = command
    if command_gap is not None:
        return _blocked_response(
            base,
            blocked_reason=command_gap,
            completed_at_utc=started_at,
            duration_ms=0,
            failure_kind="manual_gap",
        )

    run = runner or _run_subprocess
    monotonic_start = time.monotonic()
    try:
        completed = run(command, stdin_text, workspace, timeout_seconds)
    except FileNotFoundError:
        return _blocked_response(
            base,
            blocked_reason=f"provider CLI unavailable: {attempt.cli_command}",
            completed_at_utc=_format_utc(clock()),
            duration_ms=_duration_ms(monotonic_start),
            failure_kind="missing_cli_binary",
        )
    except subprocess.TimeoutExpired:
        return _failed_response(
            base,
            blocked_reason="invocation_timeout",
            completed_at_utc=_format_utc(clock()),
            duration_ms=_duration_ms(monotonic_start),
            exit_code=None,
            failure_kind="invocation_timeout",
        )
    except OSError as exc:
        return _failed_response(
            base,
            blocked_reason=f"provider transport error: {exc}",
            completed_at_utc=_format_utc(clock()),
            duration_ms=_duration_ms(monotonic_start),
            exit_code=None,
            failure_kind="transport_crash",
        )

    completed_at = _format_utc(clock())
    duration_ms = _duration_ms(monotonic_start)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    raw_digest = _digest_text(stdout + "\n" + stderr)
    raw_output_ref = f"provider_raw_output_sha256:{raw_digest}"
    base["raw_output_digest"] = raw_digest
    base["output_refs"] = _unique([raw_output_ref])
    base["source_refs"] = _unique([*base["source_refs"], raw_output_ref])
    if completed.returncode != 0:
        return _failed_response(
            base,
            blocked_reason="invocation_failed",
            completed_at_utc=completed_at,
            duration_ms=duration_ms,
            exit_code=completed.returncode,
            failure_kind="nonzero_exit",
        )

    parsed = _parse_structured_speech(stdout)
    if parsed is None:
        return _blocked_response(
            base,
            blocked_reason="raw_archive_only: provider output is not structured speech",
            completed_at_utc=completed_at,
            duration_ms=duration_ms,
            exit_code=completed.returncode,
            failure_kind="raw_archive_only",
        )

    content = parsed["content"]
    parsed_refs = _text_list(parsed.get("source_refs"))
    output_refs = _unique([*base["output_refs"], *_text_list(parsed.get("output_refs"))])
    proof_level: Literal["real_provider_proof", "contract_proof"] = (
        "real_provider_proof" if allow_live_provider_proof else "contract_proof"
    )
    provider_session_id = _optional_text(parsed.get("provider_session_id"))
    raw_provider_session_id = _provider_session_id_from_output(stdout + "\n" + stderr)
    response_id = _optional_text(parsed.get("response_id")) or _response_id(
        invocation_id=invocation_id,
        content=content,
    )
    return GodRoomProviderSpeechResponseV1(
        **{
            **base,
            "response_id": response_id,
            "status": "completed",
            "proof_level": proof_level,
            "provider_session_id": provider_session_id
            or raw_provider_session_id
            or attempt.provider_session_id
            or invocation_id,
            "provider_session_kind": _optional_text(parsed.get("provider_session_kind"))
            or attempt.provider_session_kind
            or "provider_invocation",
            "content": content,
            "source_refs": _unique(
                [
                    *base["source_refs"],
                    *parsed_refs,
                    f"provider_invocation:{invocation_id}",
                ]
            ),
            "output_refs": output_refs,
            "completed_at_utc": completed_at,
            "duration_ms": duration_ms,
            "exit_code": completed.returncode,
            "invocation_status": "completed",
        }
    )


def _run_subprocess(
    command: Sequence[str],
    stdin_text: str | None,
    workspace: Path,
    timeout_seconds: int,
) -> ProviderCommandResult:
    completed = subprocess.run(
        list(command),
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=workspace,
        timeout=timeout_seconds,
        check=False,
    )
    return ProviderCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _base_payload(
    *,
    attempt: GodRoomSpeakerAttemptV1,
    invocation_id: str,
    started_at_utc: str,
    prompt_refs: list[str],
) -> dict[str, Any]:
    target_participant_id = attempt.target_participant_id or "unresolved-participant"
    provider_profile_ref = attempt.provider_profile_ref or attempt.account_ref or "unresolved"
    provider_session_id = attempt.provider_session_id or invocation_id
    return {
        "response_id": _response_id(invocation_id=invocation_id, content="manual-gap"),
        "status": "blocked",
        "proof_level": "manual_gap",
        "target_participant_id": target_participant_id,
        "provider_profile_ref": provider_profile_ref,
        "provider_session_id": provider_session_id,
        "provider_session_kind": attempt.provider_session_kind,
        "content": None,
        "source_refs": _unique(
            [
                *attempt.source_refs,
                *prompt_refs,
                f"provider_invocation:{invocation_id}",
            ]
        ),
        "conversation_id": attempt.conversation_id,
        "room_id": attempt.room_id,
        "target_god_id": attempt.target_god_id,
        "binding_revision": attempt.binding_revision,
        "account_ref": attempt.account_ref,
        "cli_command": attempt.cli_command,
        "model": attempt.model,
        "variant": attempt.variant,
        "invocation_id": invocation_id,
        "invocation_status": "blocked",
        "command": [],
        "started_at_utc": started_at_utc,
        "completed_at_utc": None,
        "duration_ms": None,
        "exit_code": None,
        "prompt_refs": _unique(prompt_refs),
        "output_refs": [],
        "raw_output_digest": None,
        "blocked_reason": None,
        "failure_kind": None,
    }


def _required_attempt_gap(attempt: GodRoomSpeakerAttemptV1) -> str | None:
    if attempt.status != "ready_for_provider_attempt":
        return attempt.blocked_reason or "speaker attempt is not ready for provider invocation"
    required = {
        "target_participant_id": attempt.target_participant_id,
        "provider_profile_ref": attempt.provider_profile_ref,
        "account_ref": attempt.account_ref,
        "cli_command": attempt.cli_command,
        "model": attempt.model,
    }
    for field_name, value in required.items():
        if _optional_text(value) is None:
            return f"speaker attempt missing {field_name}"
    return None


def _build_command(
    *,
    cli_command: str,
    model: str,
    variant: str | None,
    workspace: Path,
    prompt: str,
) -> tuple[list[str], str | None, str | None]:
    command = _optional_text(cli_command)
    model_id = _optional_text(model)
    if command is None:
        return [], None, "speaker attempt missing cli_command"
    if model_id is None:
        return [], None, "speaker attempt missing model"
    if command == "opencode":
        run_command = [
            command,
            "run",
            "--model",
            model_id,
        ]
        if variant:
            run_command.extend(["--variant", variant])
        run_command.extend(["--format", "json", "--dir", str(workspace), prompt])
        return run_command, None, None
    if command == "codex":
        return [
            command,
            "exec",
            "-m",
            model_id,
            "-C",
            str(workspace),
        ], prompt, None
    return [], None, f"unsupported provider CLI for GOD room speech: {command}"


def _parse_structured_speech(stdout: str) -> dict[str, Any] | None:
    for payload in reversed(_json_objects(stdout)):
        content = _optional_text(payload.get("content"))
        if content is None:
            content = _optional_text(payload.get("text"))
        if content is None:
            message = payload.get("message")
            if isinstance(message, dict):
                content = _optional_text(message.get("content"))
        if content is None:
            continue
        return {**payload, "content": content}
    return None


def _json_objects(stdout: str) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    cleaned = stdout.strip()
    if not cleaned:
        return values
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        values.append(payload)
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            values.append(item)
    return values


def _provider_session_id_from_output(output: str) -> str | None:
    for line in output.splitlines():
        match = re.search(r"\bsession id:\s*([A-Za-z0-9._:-]+)", line, flags=re.I)
        if match:
            return match.group(1)
    return None


def _blocked_response(
    base: Mapping[str, Any],
    *,
    blocked_reason: str,
    completed_at_utc: str,
    duration_ms: int,
    exit_code: int | None = None,
    failure_kind: str,
) -> GodRoomProviderSpeechResponseV1:
    return GodRoomProviderSpeechResponseV1(
        **{
            **dict(base),
            "status": "blocked",
            "proof_level": "manual_gap",
            "invocation_status": failure_kind,
            "completed_at_utc": completed_at_utc,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "blocked_reason": blocked_reason,
            "failure_kind": failure_kind,
        }
    )


def _failed_response(
    base: Mapping[str, Any],
    *,
    blocked_reason: str,
    completed_at_utc: str,
    duration_ms: int,
    exit_code: int | None,
    failure_kind: str,
) -> GodRoomProviderSpeechResponseV1:
    return GodRoomProviderSpeechResponseV1(
        **{
            **dict(base),
            "status": "failed",
            "proof_level": "manual_gap",
            "invocation_status": failure_kind,
            "completed_at_utc": completed_at_utc,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "blocked_reason": blocked_reason,
            "failure_kind": failure_kind,
        }
    )


def _invocation_id(
    *,
    attempt: GodRoomSpeakerAttemptV1,
    prompt: str,
    started_at: str,
) -> str:
    seed = {
        "conversation_id": attempt.conversation_id,
        "room_id": attempt.room_id,
        "selected_event_id": attempt.selected_event_id,
        "target_participant_id": attempt.target_participant_id,
        "binding_revision": attempt.binding_revision,
        "prompt_digest": _digest_text(prompt),
        "started_at": started_at,
    }
    return f"provider-invocation-{_digest_json(seed)[:16]}"


def _response_id(*, invocation_id: str, content: str) -> str:
    seed = {"invocation_id": invocation_id, "content": content}
    return f"provider-response-{_digest_json(seed)[:16]}"


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _duration_ms(started_monotonic: float) -> int:
    return max(0, round((time.monotonic() - started_monotonic) * 1000))


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _text_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = _optional_text(item)
        if text is not None:
            result.append(text)
    return result


def _unique(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


__all__ = [
    "ProviderCommandResult",
    "invoke_god_room_provider_speech",
]
