"""Room-native participant identity verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_errors import RoomApplicationError


@dataclass(frozen=True)
class RoomParticipantIdentity:
    participant: Participant
    caller_identity: str


def verify_room_participant_identity(
    participants: ParticipantStore,
    *,
    registry_path: Path,
    conversation_id: str,
    participant_id: str,
    god_session_id: str,
    required_role: str | None = None,
    forbidden_code: str | None = None,
    forbidden_message: str | None = None,
    forbidden_details: dict[str, Any] | None = None,
) -> RoomParticipantIdentity:
    """Bind a God session to one participant in exactly one Room."""

    try:
        session = GodSessionRegistry(registry_path).get(god_session_id)
    except KeyError as exc:
        raise RoomApplicationError("unknown_god_session", god_session_id) from exc
    if session.conversation_id != conversation_id or session.participant_id != participant_id:
        raise RoomApplicationError("session_participant_mismatch", god_session_id)

    try:
        participant = participants.get(participant_id)
    except KeyError as exc:
        raise RoomApplicationError("unknown_participant", participant_id) from exc
    if participant.conversation_id != conversation_id:
        raise RoomApplicationError("unknown_participant", participant_id)

    if required_role is not None and participant.role != required_role:
        details = dict(forbidden_details or {})
        details.setdefault("participant_id", participant_id)
        details.setdefault("participant_role", participant.role)
        details.setdefault("required_role", required_role)
        raise RoomApplicationError(
            forbidden_code or "participant_role_forbidden",
            forbidden_message or f"participant role must be {required_role}",
            details=details,
        )

    return RoomParticipantIdentity(
        participant=participant,
        caller_identity=f"god:{god_session_id}:{participant_id}",
    )
