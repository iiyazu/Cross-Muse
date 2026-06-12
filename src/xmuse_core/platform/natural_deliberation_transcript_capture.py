from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xmuse_core.agents.god_session_registry import (
    GodSessionRecord,
    GodSessionRegistry,
)
from xmuse_core.chat.models import ChatMessage
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.protocol_v2 import GodSpeechAct, GodSpeechActMessageV1
from xmuse_core.chat.store import ChatStore


def export_natural_deliberation_transcript_artifact(
    *,
    chat_db_path: str | Path,
    registry_path: str | Path,
    conversation_id: str,
    output_path: str | Path,
    source_refs: Sequence[str] = (),
    target_refs: Sequence[str] = (),
) -> dict[str, Any]:
    chat = ChatStore(chat_db_path)
    participants = {
        participant.participant_id: participant
        for participant in ParticipantStore(chat_db_path).list_by_conversation(conversation_id)
    }
    sessions = _sessions_by_participant(registry_path, conversation_id)
    transcript_messages: list[dict[str, Any]] = []
    blockers: list[dict[str, object]] = []

    for stored in chat.list_messages(conversation_id):
        speech = _speech_act_from_message(stored)
        if speech is None:
            continue
        participant = participants.get(stored.author)
        session = sessions.get(stored.author)
        source_ref = f"chat:message:{speech.message_id}"
        message_refs = _dedupe(
            [
                source_ref,
                *speech.references,
                *speech.memory_refs,
            ]
        )
        provider_session_id = session.provider_session_id if session is not None else None
        if not provider_session_id:
            blockers.append(
                _blocker(
                    "provider_session_metadata_missing",
                    source_refs=[source_ref, f"god:{speech.sender_god}"],
                )
            )
        transcript_messages.append(
            {
                "message_id": speech.message_id,
                "conversation_id": conversation_id,
                "god_id": speech.sender_god,
                "provider_id": _provider_id(participant, session),
                "provider_profile": _provider_profile(participant),
                "session_id": provider_session_id or "",
                "speech_act": speech.speech_act.value,
                "decision_scope": _decision_scope(speech),
                "source_refs": message_refs,
                "target_refs": _target_refs(speech, target_refs),
                "blocking": _is_blocking(speech),
            }
        )
        if _is_blocking(speech):
            blockers.append(
                _blocker(
                    _blocking_reason(speech),
                    source_refs=[source_ref, f"god:{speech.sender_god}"],
                )
            )

    god_ids = _dedupe(
        [
            str(message["god_id"])
            for message in transcript_messages
            if str(message.get("god_id") or "").strip()
        ]
    )
    if not transcript_messages:
        blockers.append(
            _blocker(
                "natural_god_speech_act_messages_missing",
                source_refs=[f"conversation:{conversation_id}"],
            )
        )
    elif len(god_ids) < 2:
        blockers.append(
            _blocker(
                "natural_deliberation_requires_two_gods",
                source_refs=[f"conversation:{conversation_id}", *[f"god:{god}" for god in god_ids]],
            )
        )

    proof_level = "real_provider_proof"
    if _has_manual_gap(blockers):
        proof_level = "manual_gap"
    artifact: dict[str, Any] = {
        "schema_version": "xmuse.operator_transcript.v1",
        "conversation_id": conversation_id,
        "proof_level": proof_level,
        "fact_state": "blocked" if blockers else "observed",
        "natural_deliberation": bool(transcript_messages),
        "source_refs": _artifact_source_refs(conversation_id, source_refs, transcript_messages),
        "target_refs": _dedupe([str(ref) for ref in target_refs if str(ref).strip()]),
        "messages": transcript_messages,
        "blockers": blockers,
        "captured_at": _utc_now(),
    }
    _write_json(Path(output_path), artifact)
    return artifact


def _sessions_by_participant(
    registry_path: str | Path,
    conversation_id: str,
) -> dict[str, GodSessionRecord]:
    sessions: dict[str, GodSessionRecord] = {}
    for session in GodSessionRegistry(registry_path).list():
        if session.conversation_id != conversation_id:
            continue
        if not session.participant_id:
            continue
        sessions[session.participant_id] = session
    return sessions


def _speech_act_from_message(message: ChatMessage) -> GodSpeechActMessageV1 | None:
    if message.role != "assistant":
        return None
    envelope = message.envelope_json or {}
    if message.envelope_type != "god_speech_act" and envelope.get("type") != "god_speech_act":
        return None
    payload = envelope.get("message") or envelope.get("god_speech_act")
    if not isinstance(payload, dict):
        return None
    try:
        return GodSpeechActMessageV1.model_validate(payload)
    except ValidationError:
        return None


def _provider_id(participant: Participant | None, session: GodSessionRecord | None) -> str:
    if participant is not None:
        return participant.provider_id.value
    if session is not None and session.runtime:
        return "codex" if session.runtime == "codex" else session.runtime
    return ""


def _provider_profile(participant: Participant | None) -> str:
    if participant is None:
        return ""
    return participant.profile_id.value


def _decision_scope(message: GodSpeechActMessageV1) -> str:
    value = message.payload.get("decision_scope")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if message.lane_scope:
        return message.lane_scope
    return "conversation"


def _target_refs(
    message: GodSpeechActMessageV1,
    default_refs: Sequence[str],
) -> list[str]:
    payload_refs = _string_list(message.payload.get("target_refs"))
    return _dedupe(
        [
            *[str(ref) for ref in default_refs if str(ref).strip()],
            *payload_refs,
        ]
    )


def _is_blocking(message: GodSpeechActMessageV1) -> bool:
    value = message.payload.get("blocking")
    if isinstance(value, bool):
        return value
    return message.speech_act in {GodSpeechAct.CHALLENGE, GodSpeechAct.OBJECT}


def _blocking_reason(message: GodSpeechActMessageV1) -> str:
    value = message.payload.get("blocking_reason") or message.payload.get("reason")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "transcript_blocking_message"


def _has_manual_gap(blockers: Sequence[Mapping[str, object]]) -> bool:
    manual_gap_reasons = {
        "natural_god_speech_act_messages_missing",
        "natural_deliberation_requires_two_gods",
        "provider_session_metadata_missing",
    }
    return any(str(blocker.get("reason")) in manual_gap_reasons for blocker in blockers)


def _artifact_source_refs(
    conversation_id: str,
    source_refs: Sequence[str],
    messages: Sequence[Mapping[str, Any]],
) -> list[str]:
    refs = [
        f"memory://conversation/{conversation_id}/transcript",
        *[str(ref) for ref in source_refs if str(ref).strip()],
    ]
    for message in messages:
        refs.extend(_string_list(message.get("source_refs")))
    return _dedupe(refs)


def _blocker(reason: str, *, source_refs: Sequence[str]) -> dict[str, object]:
    return {
        "reason": reason,
        "source_refs": _dedupe([str(ref) for ref in source_refs if str(ref).strip()]),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["export_natural_deliberation_transcript_artifact"]
