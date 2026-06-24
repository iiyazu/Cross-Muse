from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore


@dataclass(frozen=True)
class ContextAssembler:
    participants: ParticipantStore
    chat: ChatStore
    inbox: ChatInboxStore | None = None
    acceptance_spines: AcceptanceSpineStore | None = None
    dispatch_queue: ChatDispatchQueueStore | None = None
    collaboration_store: ChatCollaborationStore | None = None
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
                "intake_kind": (message.envelope_json or {}).get("intake_kind"),
                "source_refs": [f"chat.db#messages:{message.id}"],
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
        proposals = self.chat.list_proposals(conversation_id)
        inbox_summary = self._inbox_summary(conversation_id)
        acceptance_spines = self._acceptance_spines(conversation_id)
        dispatch_summary = self._dispatch_summary(conversation_id)
        collaboration_summary = self._collaboration_summary(conversation_id)
        source_refs = _context_source_refs(
            recent_messages=recent_messages,
            inbox_summary=inbox_summary,
            acceptance_spines=acceptance_spines,
            dispatch_summary=dispatch_summary,
            collaboration_summary=collaboration_summary,
        )
        return {
            "mode": "group_chat",
            "participants": participants,
            "recent_messages": recent_messages,
            "context_capsule": {
                "version": "xmuse-groupchat-context-v2",
                "source_authority": "chat_store",
                "source_refs": source_refs,
                "recent_message_count": len(recent_messages),
                "recent_messages": recent_messages,
                "human_intake": _human_intake_summary(recent_messages),
                "inbox_summary": inbox_summary,
                "proposal_summary": _proposal_summary(proposals),
                "acceptance_spines": acceptance_spines,
                "dispatch_queue": dispatch_summary,
                "collaboration_summary": collaboration_summary,
                "review_summary": _review_summary(acceptance_spines),
                "open_questions": [],
                "commitments": [],
                "proposal_state": _proposal_state(proposals),
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

    def _inbox_summary(self, conversation_id: str) -> dict[str, Any]:
        if self.inbox is None:
            return {
                "source_authority": "chat_inbox_items",
                "source_refs": [],
                "counts_by_status": {},
                "counts_by_type": {},
                "pending": [],
            }
        items = self.inbox.list_by_conversation(conversation_id, include_terminal=True)
        counts_by_status: dict[str, int] = {}
        counts_by_type: dict[str, int] = {}
        pending = []
        for item in items:
            counts_by_status[item.status] = counts_by_status.get(item.status, 0) + 1
            counts_by_type[item.item_type] = counts_by_type.get(item.item_type, 0) + 1
            if item.status in {"unread", "claimed"}:
                pending.append(
                    {
                        "id": item.id,
                        "target_role": item.target_role,
                        "item_type": item.item_type,
                        "status": item.status,
                        "source_refs": [f"chat.db#chat_inbox_items:{item.id}"],
                    }
                )
        return {
            "source_authority": "chat_inbox_items",
            "source_refs": [f"chat.db#chat_inbox_items:{item.id}" for item in items],
            "counts_by_status": counts_by_status,
            "counts_by_type": counts_by_type,
            "pending": pending[-8:],
        }

    def _acceptance_spines(self, conversation_id: str) -> list[dict[str, Any]]:
        if self.acceptance_spines is None:
            return []
        return [
            {
                "spine_id": spine.spine_id,
                "status": spine.status.value,
                "intake_message_id": spine.intake_message_id,
                "proposal_id": spine.proposal_id,
                "review_trigger_inbox_id": spine.review_trigger_inbox_id,
                "review_or_execute_verdict_ref": spine.review_or_execute_verdict_ref,
                "dispatch_item_id": spine.dispatch_item_id,
                "review_verdict_ref": spine.review_verdict_ref,
                "final_action_ref": spine.final_action_ref,
                "github_gate_evidence_ref": spine.github_gate_evidence_ref,
                "blocked_reason": spine.blocked_reason,
                "source_refs": [f"chat.db#acceptance_spines:{spine.spine_id}"],
            }
            for spine in self.acceptance_spines.list_by_conversation(conversation_id)
        ]

    def _dispatch_summary(self, conversation_id: str) -> dict[str, Any]:
        if self.dispatch_queue is None:
            return {
                "source_authority": "chat_dispatch_queue",
                "source_refs": [],
                "counts_by_status": {},
                "entries": [],
            }
        entries = self.dispatch_queue.list_entries(conversation_id, limit=10)
        counts_by_status: dict[str, int] = {}
        rows = []
        for entry in entries:
            counts_by_status[entry.status] = counts_by_status.get(entry.status, 0) + 1
            rows.append(
                {
                    "entry_id": entry.entry_id,
                    "target": entry.target,
                    "status": entry.status,
                    "proposal_id": entry.proposal_id,
                    "resolution_id": entry.resolution_id,
                    "dispatch_evidence": entry.dispatch_evidence,
                    "failure_reason": entry.failure_reason,
                    "source_refs": [f"chat.db#chat_dispatch_queue:{entry.entry_id}"],
                }
            )
        return {
            "source_authority": "chat_dispatch_queue",
            "source_refs": [f"chat.db#chat_dispatch_queue:{entry.entry_id}" for entry in entries],
            "counts_by_status": counts_by_status,
            "entries": rows,
        }

    def _collaboration_summary(self, conversation_id: str) -> dict[str, Any]:
        if self.collaboration_store is None:
            return {
                "source_authority": "collaboration_runs",
                "source_refs": [],
                "counts_by_status": {},
                "runs": [],
                "pending_handoffs": [],
                "open_blockers": [],
            }
        runs = self.collaboration_store.list_runs(conversation_id)
        counts_by_status: dict[str, int] = {}
        rows = []
        pending_handoffs = []
        open_blockers = []
        source_refs: list[str] = []
        for run in runs[-10:]:
            counts_by_status[run.status.value] = (
                counts_by_status.get(run.status.value, 0) + 1
            )
            responded_by_target = {response.target: response for response in run.responses}
            completed_targets = [
                target
                for target, response in responded_by_target.items()
                if response.status == "received"
            ]
            failed_targets = [
                target
                for target, response in responded_by_target.items()
                if response.status in {"failed", "timeout"}
            ]
            pending_targets = [
                target for target in run.targets if target not in responded_by_target
            ]
            run_ref = f"chat.db#collaboration_runs:{run.run_id}"
            source_refs.append(run_ref)
            row = {
                "run_id": run.run_id,
                "status": run.status.value,
                "initiator": run.initiator,
                "targets": list(run.targets),
                "callback_target": run.callback_target,
                "pending_targets": pending_targets,
                "completed_targets": completed_targets,
                "failed_targets": failed_targets,
                "source_refs": [run_ref],
            }
            rows.append(row)
            if pending_targets:
                pending_handoffs.append(row)
            for blocker in run.blockers:
                blocker_ref = f"chat.db#collaboration_blockers:{blocker.blocker_id}"
                source_refs.append(blocker_ref)
                if blocker.active:
                    open_blockers.append(
                        {
                            "blocker_id": blocker.blocker_id,
                            "run_id": blocker.run_id,
                            "issuer": blocker.issuer,
                            "severity": blocker.severity,
                            "reason": blocker.reason,
                            "affected_ref": blocker.affected_ref,
                            "blocks_dispatch": blocker.blocks_dispatch,
                            "source_refs": [blocker_ref],
                        }
                    )
        return {
            "source_authority": "collaboration_runs",
            "source_refs": _dedupe_refs(source_refs),
            "counts_by_status": counts_by_status,
            "runs": rows,
            "pending_handoffs": pending_handoffs,
            "open_blockers": open_blockers,
        }


def _proposal_summary(proposals: list[Any]) -> dict[str, Any]:
    return {
        "source_authority": "proposals",
        "source_refs": [f"chat.db#proposals:{proposal.id}" for proposal in proposals],
        "count": len(proposals),
        "latest": (
            {
                "proposal_id": proposals[-1].id,
                "status": proposals[-1].status.value,
                "proposal_type": proposals[-1].proposal_type,
                "source_refs": [f"chat.db#proposals:{proposals[-1].id}"],
            }
            if proposals
            else None
        ),
    }


def _proposal_state(proposals: list[Any]) -> str:
    if not proposals:
        return "none"
    return proposals[-1].status.value


def _human_intake_summary(recent_messages: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    latest = None
    for message in recent_messages:
        intake_kind = message.get("intake_kind")
        if not isinstance(intake_kind, str) or not intake_kind:
            continue
        counts[intake_kind] = counts.get(intake_kind, 0) + 1
        latest = {
            "message_id": message.get("id"),
            "intake_kind": intake_kind,
            "source_refs": message.get("source_refs", []),
        }
    return {"counts": counts, "latest": latest}


def _review_summary(acceptance_spines: list[dict[str, Any]]) -> dict[str, Any]:
    trigger_refs = [
        spine["review_trigger_inbox_id"]
        for spine in acceptance_spines
        if spine.get("review_trigger_inbox_id")
    ]
    verdict_refs = [
        spine["review_verdict_ref"]
        for spine in acceptance_spines
        if spine.get("review_verdict_ref")
    ]
    return {
        "source_authority": "acceptance_spines",
        "review_trigger_count": len(trigger_refs),
        "review_verdict_refs": verdict_refs,
        "source_refs": [
            ref
            for spine in acceptance_spines
            for ref in spine.get("source_refs", [])
        ],
    }


def _context_source_refs(
    *,
    recent_messages: list[dict[str, Any]],
    inbox_summary: dict[str, Any],
    acceptance_spines: list[dict[str, Any]],
    dispatch_summary: dict[str, Any],
    collaboration_summary: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    refs.extend(
        ref
        for message in recent_messages
        for ref in message.get("source_refs", [])
        if isinstance(ref, str) and ref
    )
    refs.extend(
        ref
        for ref in inbox_summary.get("source_refs", [])
        if isinstance(ref, str) and ref
    )
    refs.extend(
        ref
        for spine in acceptance_spines
        for ref in spine.get("source_refs", [])
        if isinstance(ref, str) and ref
    )
    refs.extend(
        ref
        for ref in dispatch_summary.get("source_refs", [])
        if isinstance(ref, str) and ref
    )
    refs.extend(
        ref
        for ref in collaboration_summary.get("source_refs", [])
        if isinstance(ref, str) and ref
    )
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped
