from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore


@dataclass(frozen=True)
class ContextAssembler:
    participants: ParticipantStore
    chat: ChatStore
    recent_limit: int = 8

    def group_chat_context(self, conversation_id: str) -> dict[str, Any]:
        active_participants = [
            participant
            for participant in self.participants.list_by_conversation(conversation_id)
            if participant.status == "active"
        ]
        messages = self.chat.list_messages(conversation_id)[-self.recent_limit :]
        recent_messages = [
            {
                "id": message.id,
                "author": message.author,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
                "mentions": list(message.mentions),
            }
            for message in messages
        ]
        participants = [
            {
                "participant_id": participant.participant_id,
                "role": participant.role,
                "display_name": participant.display_name,
                "status": participant.status,
            }
            for participant in active_participants
        ]
        return {
            "mode": "group_chat",
            "participants": participants,
            "recent_messages": recent_messages,
            "context_capsule": {
                "version": "xmuse-local-context-capsule-v1",
                "recent_message_count": len(recent_messages),
                "recent_messages": recent_messages,
                "open_questions": [],
                "commitments": [],
                "proposal_state": "unknown",
                "degraded_state": None,
            },
            "turn_guidance": [
                "Treat the conversation as shared group context.",
                "Avoid repeated greetings and low-information acknowledgement loops.",
                "Mention another GOD by exact @role only when the next turn is useful.",
                "Do not invent aliases such as @him; use the roster roles.",
                "Use structured collaboration/proposal tools for execution closure; "
                "plain chat does not dispatch work.",
            ],
        }

    def turn_context(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        god_session_id: str,
        inbox_item: Any,
        group_chat: dict[str, Any],
        prompt_artifact: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "participant_id": participant_id,
            "god_session_id": god_session_id,
            "inbox_item": inbox_item.model_dump(mode="json"),
            "group_chat": group_chat,
            "context_capsule": group_chat.get("context_capsule", {}),
            "xmuse_prompt": prompt_artifact,
        }
