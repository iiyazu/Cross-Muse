from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.mentions import normalize_address
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.store import ChatStore


@dataclass(frozen=True)
class ContextAssembler:
    participants: ParticipantStore
    chat: ChatStore
    recent_limit: int = 8
    max_message_chars: int = 4000
    session_registry_path: Path | None = None
    db_path: Path | None = None

    def group_chat_context(self, conversation_id: str) -> dict[str, Any]:
        active_participants = [
            participant
            for participant in self.participants.list_by_conversation(conversation_id)
            if participant.status == "active"
        ]
        messages = self.chat.list_messages(conversation_id)[-self.recent_limit :]
        recent_messages = [
            _message_context(message, max_chars=self.max_message_chars)
            for message in messages
        ]
        session_bindings = _session_bindings(
            active_participants,
            conversation_id=conversation_id,
            session_registry_path=self.session_registry_path,
        )
        session_bindings_by_participant = {
            str(binding["participant_id"]): binding for binding in session_bindings
        }
        participants = [
            {
                "participant_id": participant.participant_id,
                "role": participant.role,
                "display_name": participant.display_name,
                "status": participant.status,
            }
            for participant in active_participants
        ]
        source_refs = [f"chat.db:conversation:{conversation_id}"]
        if self.session_registry_path is not None:
            source_refs.append(f"god_sessions:{self.session_registry_path.name}")
        if self.db_path is not None:
            source_refs.append(f"chat.db:structured_state:{conversation_id}")
        return {
            "mode": "group_chat",
            "context_layers": [
                "xmuse_l0_governance",
                "member_identity",
                "provider_session_binding_summary",
                "roster",
                "recent_transcript",
                "structured_state_refs",
            ],
            "source_refs": source_refs,
            "participants": participants,
            "participant_profiles": [
                build_participant_profile(
                    participant,
                    session_binding=session_bindings_by_participant.get(
                        participant.participant_id
                    ),
                    active_participants=active_participants,
                )
                for participant in active_participants
            ],
            "session_bindings": session_bindings,
            "structured_state": _structured_state(
                conversation_id=conversation_id,
                db_path=self.db_path,
            ),
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
            "context_budget": {
                "recent_limit": self.recent_limit,
                "max_message_chars": self.max_message_chars,
                "message_count": len(recent_messages),
                "truncated_messages": sum(
                    1 for message in recent_messages if message["truncated"]
                ),
            },
            "turn_guidance": [
                "Treat the conversation as shared group context.",
                "Avoid repeated greetings and low-information acknowledgement loops.",
                "Mention another GOD only with that member's exact "
                "participant_profiles[].mention_handle when the next turn is useful.",
                "Do not invent aliases such as @him; use the roster mention handles.",
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


def build_participant_profile(
    participant: Participant,
    *,
    session_binding: dict[str, Any] | None,
    active_participants: list[Participant] | None = None,
) -> dict[str, Any]:
    return {
        "god_id": f"god:{participant.conversation_id}:{participant.participant_id}",
        "participant_id": participant.participant_id,
        "role": participant.role,
        "display_name": participant.display_name,
        "mention_handle": _preferred_mention_handle(
            participant,
            active_participants=active_participants,
        ),
        "aliases": _participant_aliases(
            participant,
            active_participants=active_participants,
        ),
        "capabilities": _role_capabilities(participant.role),
        "default_skill_refs": _default_skill_refs(participant.role),
        "provider_id": _enum_value(participant.provider_id),
        "profile_id": _enum_value(participant.profile_id),
        "cli_kind": participant.cli_kind,
        "model": participant.model,
        "provider_session_binding_ref": _provider_session_binding_ref(
            session_binding
        ),
        "a2a_agent_card_ref": f"/a2a/agents/{participant.participant_id}",
        "identity_authority_refs": [
            f"chat.db:participant:{participant.participant_id}",
            f"chat.db:conversation:{participant.conversation_id}",
        ],
    }


def build_participant_session_binding(
    participant: Participant,
    session: GodSessionRecord | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "participant_id": participant.participant_id,
        "role": participant.role,
        "display_name": participant.display_name,
        "provider_id": _enum_value(participant.provider_id),
        "profile_id": _enum_value(participant.profile_id),
        "cli_kind": participant.cli_kind,
        "model": participant.model,
        "god_session_id": None,
        "session_address": None,
        "session_inbox_id": None,
        "session_status": "unbound",
        "provider_session_id": None,
        "provider_session_kind": None,
        "provider_binding_status": None,
        "provider_binding_failure_reason": None,
        "has_provider_session": False,
    }
    if session is None:
        return payload
    payload.update(
        {
            "god_session_id": session.god_session_id,
            "session_address": session.session_address,
            "session_inbox_id": session.session_inbox_id,
            "session_status": session.status,
            "provider_session_id": session.provider_session_id,
            "provider_session_kind": session.provider_session_kind,
            "provider_binding_status": session.provider_binding_status,
            "provider_binding_failure_reason": session.provider_binding_failure_reason,
            "has_provider_session": bool(session.provider_session_id),
        }
    )
    return payload


def _preferred_mention_handle(
    participant: Participant,
    *,
    active_participants: list[Participant] | None,
) -> str:
    role_handle = f"@{participant.role}"
    if active_participants is None or _alias_resolves_to_self(
        role_handle,
        participant=participant,
        active_participants=active_participants,
    ):
        return role_handle
    return f"@participant:{participant.participant_id}"


def _participant_aliases(
    participant: Participant,
    *,
    active_participants: list[Participant] | None,
) -> list[str]:
    candidates = [
        f"@{participant.role}",
        f"@participant:{participant.participant_id}",
    ]
    display_alias = (
        "@" + participant.display_name.strip().lower().replace(" ", "-")
        if participant.display_name.strip()
        else ""
    )
    if display_alias:
        candidates.append(display_alias)
    aliases: list[str] = []
    for alias in candidates:
        if alias in aliases:
            continue
        if active_participants is not None and not _alias_resolves_to_self(
            alias,
            participant=participant,
            active_participants=active_participants,
        ):
            continue
        aliases.append(alias)
    return aliases


def _alias_resolves_to_self(
    alias: str,
    *,
    participant: Participant,
    active_participants: list[Participant],
) -> bool:
    normalized = normalize_address(alias)
    matches = [
        candidate
        for candidate in active_participants
        if _participant_alias_matches(candidate, normalized)
    ]
    return len(matches) == 1 and matches[0].participant_id == participant.participant_id


def _participant_alias_matches(participant: Participant, normalized: str) -> bool:
    return normalized in {
        normalize_address(f"@{participant.role}"),
        normalize_address(f"@participant:{participant.participant_id}"),
        normalize_address(f"@{participant.display_name}"),
    }


def _role_capabilities(role: str) -> list[str]:
    normalized = role.strip().lower()
    if normalized == "architect":
        return ["blueprint", "planning", "proposal", "handoff"]
    if normalized == "review":
        return ["review", "blocker", "evidence_check"]
    if normalized == "execute":
        return ["execution_feasibility", "implementation", "evidence"]
    return ["chat", "handoff"]


def _default_skill_refs(role: str) -> list[str]:
    normalized = role.strip().lower()
    if normalized in {"architect", "review", "execute"}:
        return [f"xmuse://skills/groupchat/{normalized}"]
    return ["xmuse://skills/groupchat/member"]


def _provider_session_binding_ref(binding: dict[str, Any] | None) -> str | None:
    if binding is None:
        return None
    god_session_id = binding.get("god_session_id")
    if not isinstance(god_session_id, str) or not god_session_id.strip():
        return None
    return f"god_session:{god_session_id}"


def _message_context(message: Any, *, max_chars: int) -> dict[str, Any]:
    content, truncated, original_chars = _truncate_head_tail(
        message.content,
        max_chars=max_chars,
    )
    return {
        "id": message.id,
        "author": message.author,
        "role": message.role,
        "content": content,
        "created_at": message.created_at,
        "mentions": list(message.mentions),
        "truncated": truncated,
        "original_chars": original_chars,
    }


def _truncate_head_tail(content: str, *, max_chars: int) -> tuple[str, bool, int]:
    original_chars = len(content)
    if max_chars <= 0 or original_chars <= max_chars:
        return content, False, original_chars
    marker = f"\n\n[...truncated {original_chars - max_chars} chars...]\n\n"
    if max_chars <= len(marker) + 2:
        return content[:max_chars], True, original_chars
    available = max_chars - len(marker)
    head_chars = max(1, int(available * 0.4))
    tail_chars = max(1, available - head_chars)
    return (
        content[:head_chars] + marker + content[-tail_chars:],
        True,
        original_chars,
    )


def _session_bindings(
    participants: list[Participant],
    *,
    conversation_id: str,
    session_registry_path: Path | None,
) -> list[dict[str, Any]]:
    sessions = _sessions_by_participant(
        conversation_id=conversation_id,
        session_registry_path=session_registry_path,
    )
    return [
        build_participant_session_binding(
            participant,
            sessions.get(participant.participant_id),
        )
        for participant in participants
    ]


def _sessions_by_participant(
    *,
    conversation_id: str,
    session_registry_path: Path | None,
) -> dict[str, GodSessionRecord]:
    if session_registry_path is None or not session_registry_path.exists():
        return {}
    result: dict[str, GodSessionRecord] = {}
    for record in GodSessionRegistry(session_registry_path).list():
        if record.conversation_id != conversation_id or record.participant_id is None:
            continue
        result[record.participant_id] = record
    return result


def _structured_state(
    *,
    conversation_id: str,
    db_path: Path | None,
) -> dict[str, Any]:
    if db_path is None:
        return {"source": "unavailable", "reason": "db_path_not_provided"}
    inbox_items = ChatInboxStore(db_path).list_by_conversation(
        conversation_id,
        include_terminal=True,
    )
    proposals = ChatStore(db_path).list_proposals(conversation_id)
    resolutions = ChatStore(db_path).list_resolutions(conversation_id)
    collaborations = ChatCollaborationStore(db_path).list_runs(conversation_id)
    dispatch_entries = ChatDispatchQueueStore(db_path).list_entries(
        conversation_id,
        limit=10,
    )
    spines = AcceptanceSpineStore(db_path).list_by_conversation(conversation_id)
    open_inbox = [
        item
        for item in inbox_items
        if item.status in {"unread", "claimed"}
    ]
    blockers = [
        item
        for item in inbox_items
        if item.item_type.endswith("blocker")
        or item.payload.get("blocks_dispatch") is True
    ]
    return {
        "source": "chat.db",
        "conversation_id": conversation_id,
        "counts": {
            "open_inbox": len(open_inbox),
            "blockers": len(blockers),
            "open_proposals": sum(
                1 for proposal in proposals if _enum_value(proposal.status) == "open"
            ),
            "accepted_proposals": sum(
                1
                for proposal in proposals
                if _enum_value(proposal.status) == "accepted"
            ),
            "approved_resolutions": sum(
                1
                for resolution in resolutions
                if _enum_value(resolution.status) == "approved"
            ),
            "collaborations": len(collaborations),
            "collaboration_responses": sum(
                len(run.responses) for run in collaborations
            ),
            "dispatch_entries": len(dispatch_entries),
            "acceptance_spines": len(spines),
        },
        "open_inbox": [
            {
                "id": item.id,
                "type": item.item_type,
                "status": item.status,
                "target_role": item.target_role,
                "route_kind": item.payload.get("route_kind"),
                "source_message_id": item.source_message_id,
            }
            for item in open_inbox[-8:]
        ],
        "blockers": [
            {
                "id": item.id,
                "type": item.item_type,
                "status": item.status,
                "target_role": item.target_role,
                "blocks_dispatch": item.payload.get("blocks_dispatch") is True,
                "blocker_reason": item.payload.get("blocker_reason"),
                "route_kind": item.payload.get("route_kind"),
                "natural_route_status": _natural_route_status(item.payload),
            }
            for item in blockers[-8:]
        ],
        "proposals": [
            {
                "id": proposal.id,
                "type": proposal.proposal_type,
                "status": _enum_value(proposal.status),
                "accepted_resolution_id": proposal.accepted_resolution_id,
            }
            for proposal in proposals[-8:]
        ],
        "resolutions": [
            {
                "id": resolution.id,
                "status": _enum_value(resolution.status),
                "approval_mode": resolution.approval_mode,
            }
            for resolution in resolutions[-8:]
        ],
        "collaborations": [
            {
                "run_id": run.run_id,
                "status": _enum_value(run.status),
                "targets": list(run.targets),
                "responses": [
                    {
                        "target": response.target,
                        "status": response.status,
                        "content": response.content,
                    }
                    for response in run.responses[-4:]
                ],
            }
            for run in collaborations[-8:]
        ],
        "dispatch_queue": [
            {
                "entry_id": entry.entry_id,
                "status": entry.status,
                "proposal_id": entry.proposal_id,
                "resolution_id": entry.resolution_id,
                "dispatch_policy": entry.dispatch_policy,
            }
            for entry in dispatch_entries
        ],
        "acceptance_spines": [
            {
                "spine_id": spine.spine_id,
                "status": spine.status.value,
                "proposal_id": spine.proposal_id,
                "review_trigger_inbox_id": spine.review_trigger_inbox_id,
                "dispatch_item_id": spine.dispatch_item_id,
                "final_action_ref": spine.final_action_ref,
                "github_gate_evidence_ref": spine.github_gate_evidence_ref,
                "manual_gaps": spine.manual_gaps,
            }
            for spine in spines[-8:]
        ],
    }


def _natural_route_status(payload: dict[str, Any]) -> str | None:
    natural_route = payload.get("natural_route")
    if isinstance(natural_route, dict):
        status = natural_route.get("status")
        if isinstance(status, str):
            return status
    return None


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))
