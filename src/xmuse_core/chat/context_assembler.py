from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.groupchat_worklist import GroupchatWorklistStore
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
            _message_context(message, max_chars=self.max_message_chars) for message in messages
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
                    session_binding=session_bindings_by_participant.get(participant.participant_id),
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
                "truncated_messages": sum(1 for message in recent_messages if message["truncated"]),
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
        "provider_session_binding_ref": _provider_session_binding_ref(session_binding),
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
    context = {
        "id": message.id,
        "author": message.author,
        "role": message.role,
        "content": content,
        "created_at": message.created_at,
        "mentions": list(message.mentions),
        "truncated": truncated,
        "original_chars": original_chars,
    }
    envelope = _compact_message_envelope(message, max_chars=max_chars)
    if envelope is not None:
        context["envelope"] = envelope
    return context


def _compact_message_envelope(
    message: Any,
    *,
    max_chars: int,
) -> dict[str, Any] | None:
    envelope_type = getattr(message, "envelope_type", None)
    envelope_json = getattr(message, "envelope_json", None)
    if not isinstance(envelope_type, str) or not envelope_type.strip():
        envelope_type = None
    if not isinstance(envelope_json, dict):
        envelope_json = {}
    if envelope_type is None and not envelope_json:
        return None
    compact: dict[str, Any] = {}
    if envelope_type is not None:
        compact["type"] = envelope_type
    for key in (
        "provider_profile_ref",
        "provider_request_id",
        "provider_status",
        "failure_kind",
        "authority",
        "proof_boundary",
        "dispatch_queue_entry_id",
        "proposal_id",
        "resolution_id",
        "collaboration_run_id",
        "artifact_ref",
        "dispatch_evidence_ref",
        "final_action_id",
        "final_action_ref",
        "lane_id",
        "status",
        "github_gate_evidence_ref",
        "github_gate_gap_ref",
        "acceptance_spine_ref",
    ):
        value = envelope_json.get(key)
        if isinstance(value, str) and value.strip():
            compact[key] = value
    a2a_is_authority = envelope_json.get("a2a_is_authority")
    if isinstance(a2a_is_authority, bool):
        compact["a2a_is_authority"] = a2a_is_authority
    source_refs = _payload_str_list(envelope_json, "source_refs")
    if source_refs:
        compact["source_refs"] = source_refs[:8]
    github_gate = envelope_json.get("github_gate")
    if isinstance(github_gate, dict):
        compact_github_gate = _compact_github_gate(github_gate)
        if compact_github_gate:
            compact["github_gate"] = compact_github_gate
    diagnostic = envelope_json.get("diagnostic_payload")
    if isinstance(diagnostic, dict):
        artifacts = _compact_artifacts(diagnostic, max_chars=max_chars)
        if artifacts:
            compact["artifacts"] = artifacts
            compact["artifact_count"] = _artifact_count(diagnostic)
    return compact or None


def _compact_github_gate(github_gate: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "status",
        "proof_level",
        "repo",
        "head_sha",
    ):
        value = github_gate.get(key)
        if isinstance(value, str) and value.strip():
            compact[key] = value
    for key in ("pull_request_number", "workflow_run_id", "check_suite_id"):
        value = github_gate.get(key)
        if isinstance(value, int):
            compact[key] = value
    check_runs = github_gate.get("check_runs")
    if isinstance(check_runs, list):
        compact_runs = [
            {
                clean_key: clean_value
                for clean_key, clean_value in {
                    "id": item.get("id") if isinstance(item, dict) else None,
                    "name": item.get("name") if isinstance(item, dict) else None,
                    "head_sha": item.get("head_sha") if isinstance(item, dict) else None,
                }.items()
                if isinstance(clean_value, (int, str))
                and (not isinstance(clean_value, str) or clean_value.strip())
            }
            for item in check_runs[:8]
            if isinstance(item, dict)
        ]
        compact_runs = [item for item in compact_runs if item]
        if compact_runs:
            compact["check_runs"] = compact_runs
    main_ci = github_gate.get("main_ci")
    if isinstance(main_ci, dict):
        compact_main_ci = _compact_github_main_ci(main_ci)
        if compact_main_ci:
            compact["main_ci"] = compact_main_ci
    return compact


def _compact_github_main_ci(main_ci: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    workflow_run_id = main_ci.get("workflow_run_id")
    if isinstance(workflow_run_id, int):
        compact["workflow_run_id"] = workflow_run_id
    for key in ("workflow_name", "head_sha", "status", "conclusion"):
        value = main_ci.get(key)
        if isinstance(value, str) and value.strip():
            compact[key] = value
    return compact


def _compact_artifacts(
    diagnostic: dict[str, Any],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    raw_artifacts = diagnostic.get("a2a_artifacts")
    if not isinstance(raw_artifacts, list):
        return []
    compact: list[dict[str, Any]] = []
    for raw_artifact in raw_artifacts[:4]:
        if not isinstance(raw_artifact, dict):
            continue
        artifact: dict[str, Any] = {}
        for key in ("artifact_id", "artifactId", "id", "name", "type"):
            value = raw_artifact.get(key)
            if isinstance(value, str) and value.strip():
                artifact[key] = value
        text = _artifact_text(raw_artifact)
        if text:
            artifact["text"] = _truncate_head_tail(
                text,
                max_chars=min(max_chars, 1000),
            )[0]
        if artifact:
            compact.append(artifact)
    return compact


def _artifact_count(diagnostic: dict[str, Any]) -> int:
    artifacts = diagnostic.get("a2a_artifacts")
    return len(artifacts) if isinstance(artifacts, list) else 0


def _artifact_text(artifact: dict[str, Any]) -> str:
    text = artifact.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    parts = artifact.get("parts")
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        value = part.get("text")
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return "\n".join(texts)


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
    worklist = _groupchat_worklist_state(conversation_id=conversation_id, db_path=db_path)
    open_inbox = [item for item in inbox_items if item.status in {"unread", "claimed"}]
    blockers = [
        item
        for item in inbox_items
        if item.item_type.endswith("blocker") or item.payload.get("blocks_dispatch") is True
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
                1 for proposal in proposals if _enum_value(proposal.status) == "accepted"
            ),
            "approved_resolutions": sum(
                1 for resolution in resolutions if _enum_value(resolution.status) == "approved"
            ),
            "collaborations": len(collaborations),
            "collaboration_responses": sum(len(run.responses) for run in collaborations),
            "dispatch_entries": len(dispatch_entries),
            "acceptance_spines": len(spines),
            "groupchat_worklist_terminal": len(worklist["items"]),
        },
        "open_inbox": [
            {
                "id": item.id,
                "type": item.item_type,
                "status": item.status,
                "target_role": item.target_role,
                "route_kind": item.payload.get("route_kind"),
                "route_key": _payload_str(item.payload, "route_key"),
                "route_depth": _payload_int(item.payload, "route_depth"),
                "source_kind": _payload_str(item.payload, "source_kind"),
                "source_refs": _payload_str_list(item.payload, "source_refs"),
                "natural_route": _compact_natural_route(item.payload),
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
                "route_key": _payload_str(item.payload, "route_key"),
                "route_depth": _payload_int(item.payload, "route_depth"),
                "source_kind": _payload_str(item.payload, "source_kind"),
                "source_refs": _payload_str_list(item.payload, "source_refs"),
                "natural_route": _compact_natural_route(item.payload),
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
                "gate_refs": list(entry.gate_refs),
                "source_refs": _dispatch_source_refs(entry),
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
                "review_or_execute_verdict_ref": spine.review_or_execute_verdict_ref,
                "dispatch_item_id": spine.dispatch_item_id,
                "final_action_ref": spine.final_action_ref,
                "github_gate_evidence_ref": spine.github_gate_evidence_ref,
                "manual_gaps": spine.manual_gaps,
                "blocked_reason": spine.blocked_reason,
                "source_refs": _acceptance_spine_source_refs(spine),
            }
            for spine in spines[-8:]
        ],
        "groupchat_worklist": worklist,
    }


def _dispatch_source_refs(entry: Any) -> list[str]:
    refs = []
    if entry.entry_id:
        refs.append(f"chat_dispatch_queue:{entry.entry_id}")
    if entry.proposal_id:
        refs.append(f"proposal:{entry.proposal_id}")
    refs.extend(entry.gate_refs)
    if entry.resolution_id:
        refs.append(f"resolution:{entry.resolution_id}")
    if entry.collaboration_run_id:
        refs.append(f"collaboration:{entry.collaboration_run_id}")
    if entry.artifact_ref:
        refs.append(entry.artifact_ref)
    return _dedupe_strings(refs)


def _acceptance_spine_source_refs(spine: Any) -> list[str]:
    refs = [
        f"chat.db:acceptance_spines#spine={spine.spine_id}",
        f"message:{spine.intake_message_id}",
    ]
    if spine.proposal_id:
        refs.append(f"proposal:{spine.proposal_id}")
    if spine.review_trigger_inbox_id:
        refs.append(f"inbox:{spine.review_trigger_inbox_id}")
    if spine.review_or_execute_verdict_ref:
        refs.append(spine.review_or_execute_verdict_ref)
    if spine.dispatch_item_id:
        refs.append(f"chat_dispatch_queue:{spine.dispatch_item_id}")
    refs.extend(spine.execution_evidence_refs)
    if spine.review_verdict_ref:
        refs.append(spine.review_verdict_ref)
    if spine.final_action_ref:
        refs.append(spine.final_action_ref)
    if spine.github_gate_evidence_ref:
        refs.append(spine.github_gate_evidence_ref)
    return _dedupe_strings(refs)


def _groupchat_worklist_state(
    *,
    conversation_id: str,
    db_path: Path,
) -> dict[str, Any]:
    worklist_store = GroupchatWorklistStore(db_path)
    chat = ChatStore(db_path)
    messages_by_id = {
        message.id: message for message in chat.list_messages(conversation_id)
    }
    chains = worklist_store.list_chains(conversation_id)
    items = []
    for chain in chains:
        for item in worklist_store.list_items(chain.chain_id):
            if item.status not in {"blocked", "failed", "canceled"}:
                continue
            source_message = messages_by_id.get(item.source_message_id)
            proof_boundary = _worklist_proof_boundary(item.terminal_reason, source_message)
            items.append(
                {
                    "item_id": item.item_id,
                    "chain_id": item.chain_id,
                    "status": item.status,
                    "target_role": item.target_role,
                    "target_participant_id": item.target_participant_id,
                    "route_kind": item.route_kind,
                    "depth": item.depth,
                    "terminal_reason": item.terminal_reason,
                    "source_message_id": item.source_message_id,
                    "source_refs": _worklist_source_refs(item.source_message_id, source_message),
                    "proof_boundary": proof_boundary,
                    "next_authority_boundary": _next_worklist_authority_boundary(
                        item.terminal_reason
                    ),
                    "authority_boundary": _groupchat_worklist_authority_boundary(
                        consumer="group_chat_context",
                        condition="read_only_structured_state",
                        proof_boundary=proof_boundary,
                    ),
                }
            )
    return {
        "source_authority": [
            "chat.db:groupchat_chains",
            "chat.db:groupchat_worklist",
            "chat.db:messages",
        ],
        "items": items[-8:],
    }


def _worklist_source_refs(source_message_id: str, source_message: Any | None) -> list[str]:
    refs = [f"chat:message:{source_message_id}"]
    envelope = getattr(source_message, "envelope_json", None)
    if isinstance(envelope, dict):
        refs.extend(_payload_str_list(envelope, "source_refs"))
    return _dedupe_strings(refs)


def _worklist_proof_boundary(
    terminal_reason: str | None,
    source_message: Any | None,
) -> str:
    envelope = getattr(source_message, "envelope_json", None)
    if isinstance(envelope, dict):
        proof_boundary = _payload_str(envelope, "proof_boundary")
        if proof_boundary is not None:
            return proof_boundary
    if terminal_reason:
        return terminal_reason
    return "groupchat_worklist_terminal_boundary"


def _next_worklist_authority_boundary(terminal_reason: str | None) -> str:
    if terminal_reason == "dispatch_acknowledgement_not_execution_proof":
        return "execution_evidence_or_final_action_writeback"
    if terminal_reason == "final_action_github_gate_gap":
        return "github_gate_evidence_or_manual_gap_resolution"
    if terminal_reason == "callback_missing":
        return "structured_callback_writeback"
    return "operator_or_upstream_authority_resolution"


def _groupchat_worklist_authority_boundary(
    *,
    consumer: str,
    condition: str,
    proof_boundary: str,
) -> dict[str, str]:
    return {
        "producer": "chat.db:groupchat_worklist",
        "consumer": consumer,
        "condition": condition,
        "proof_boundary": proof_boundary,
    }


def _compact_natural_route(payload: dict[str, Any]) -> dict[str, Any] | None:
    natural_route = payload.get("natural_route")
    if not isinstance(natural_route, dict):
        return None
    compact: dict[str, Any] = {}
    for key in (
        "route_id",
        "route_key",
        "source_kind",
        "route_kind",
        "origin_message_id",
        "target_participant_id",
        "status",
        "blocker_reason",
    ):
        value = natural_route.get(key)
        if isinstance(value, str) and value.strip():
            compact[key] = value
    depth = natural_route.get("depth")
    if isinstance(depth, int):
        compact["depth"] = depth
    source_refs = _payload_str_list(natural_route, "source_refs")
    if source_refs:
        compact["source_refs"] = source_refs
    return compact or None


def _natural_route_status(payload: dict[str, Any]) -> str | None:
    natural_route = payload.get("natural_route")
    if isinstance(natural_route, dict):
        status = natural_route.get("status")
        if isinstance(status, str):
            return status
    return None


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _payload_str_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _enum_value(value: Any) -> str:
    return getattr(value, "value", str(value))
