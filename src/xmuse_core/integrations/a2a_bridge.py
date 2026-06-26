from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.context_assembler import (
    build_participant_profile,
    build_participant_session_binding,
)
from xmuse_core.chat.participant_store import Participant, ParticipantStore


def build_participant_agent_card(
    participant: Participant,
    *,
    base_url: str,
    version: str = "0.1.0",
    active_participants: list[Participant] | None = None,
    session_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only A2A-compatible card for an xmuse participant."""

    url = base_url.rstrip("/")
    profile = build_participant_profile(
        participant,
        session_binding=session_binding,
        active_participants=active_participants,
    )
    return {
        "protocolVersion": "1.0",
        "name": participant.display_name,
        "description": f"xmuse {participant.role} participant",
        "url": f"{url}/a2a/agents/{participant.participant_id}",
        "version": version,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "skills": [
            {
                "id": f"xmuse-{participant.role}",
                "name": participant.role,
                "description": (
                    f"Participates in xmuse natural groupchat as {participant.role}."
                ),
                "tags": ["xmuse", "groupchat", participant.role],
            }
        ],
        "metadata": {
            "authority": "chat.db",
            "participant_id": participant.participant_id,
            "conversation_id": participant.conversation_id,
            "role": participant.role,
            "mention_handle": profile["mention_handle"],
            "aliases": profile["aliases"],
            "capabilities": profile["capabilities"],
            "default_skill_refs": profile["default_skill_refs"],
            "provider_id": profile["provider_id"],
            "profile_id": profile["profile_id"],
            "cli_kind": participant.cli_kind,
            "model": participant.model,
            "natural_profile": profile,
        },
    }


def build_participant_agent_card_from_store(
    db_path: Path,
    *,
    participant_id: str,
    base_url: str,
    session_registry_path: Path | None = None,
) -> dict[str, Any]:
    participants = ParticipantStore(db_path)
    participant = participants.get(participant_id)
    active_participants = [
        item
        for item in participants.list_by_conversation(participant.conversation_id)
        if item.status == "active"
    ]
    session = None
    if session_registry_path is not None and session_registry_path.exists():
        try:
            session = GodSessionRegistry(
                session_registry_path
            ).find_by_conversation_participant(
                participant.conversation_id,
                participant.participant_id,
            )
        except KeyError:
            session = None
    return build_participant_agent_card(
        participant,
        base_url=base_url,
        active_participants=active_participants,
        session_binding=build_participant_session_binding(participant, session),
    )
