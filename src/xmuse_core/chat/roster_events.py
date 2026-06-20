from __future__ import annotations

from typing import Any

from xmuse_core.chat.models import ChatMessage
from xmuse_core.chat.participant_store import Participant, participant_summary

ROSTER_EVENT_ENVELOPE_TYPE = "roster_event"
ROSTER_EVENT_ADDED = "participant_added"


def participant_added_event_payload(participant: Participant) -> dict[str, Any]:
    return {
        "type": ROSTER_EVENT_ENVELOPE_TYPE,
        "action": ROSTER_EVENT_ADDED,
        "source_authority": "participants",
        "participant_id": participant.participant_id,
        "participant": {
            **participant_summary(participant),
            "conversation_id": participant.conversation_id,
            "created_at": participant.created_at,
        },
    }


def roster_event_content(participant: Participant) -> str:
    return (
        f"{participant.display_name} joined the groupchat as "
        f"{participant.role} via {participant.cli_kind}."
    )


def build_roster_events(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for message in messages:
        if message.envelope_type != ROSTER_EVENT_ENVELOPE_TYPE:
            continue
        envelope = message.envelope_json or {}
        participant = envelope.get("participant")
        if not isinstance(participant, dict):
            participant = {}
        events.append(
            {
                "source_authority": envelope.get("source_authority") or "messages",
                "source_id": message.id,
                "message_id": message.id,
                "conversation_id": message.conversation_id,
                "action": envelope.get("action") or ROSTER_EVENT_ENVELOPE_TYPE,
                "participant_id": envelope.get("participant_id")
                or participant.get("participant_id"),
                "role": participant.get("role"),
                "display_name": participant.get("display_name"),
                "provider_id": participant.get("provider_id"),
                "profile_id": participant.get("profile_id"),
                "cli_kind": participant.get("cli_kind"),
                "model": participant.get("model"),
                "status": participant.get("status"),
                "created_at": message.created_at,
                "content": message.content,
            }
        )
    return events


def roster_event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"total": len(events)}
    for event in events:
        action = str(event.get("action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts
