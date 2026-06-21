from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xmuse_core.chat.dispatch_queue import ChatDispatchQueueEntry, ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.peer_scheduler import PeerChatScheduler
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


@dataclass(frozen=True)
class ChatDispatchBridgeOutcome:
    claimed: int = 0
    dispatched: int = 0
    failed: int = 0


class ChatDispatchBridge:
    """Bridge gated chat dispatch queue entries into the peer provider path."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        god_layer,
        worktree: Path | str,
        bridge_id: str,
        response_wait_s: float = 180.0,
        claim_ttl_s: int = 240,
    ) -> None:
        self._db_path = Path(db_path)
        self._god_layer = god_layer
        self._worktree = Path(worktree)
        self._bridge_id = _required(bridge_id, "bridge_id")
        self._response_wait_s = response_wait_s
        self._claim_ttl_s = claim_ttl_s

    async def tick_once(self, *, conversation_id: str) -> ChatDispatchBridgeOutcome:
        queue = ChatDispatchQueueStore(self._db_path)
        entry = queue.claim_next_auto_dispatch(
            conversation_id=conversation_id,
            claimed_by=self._bridge_id,
            claim_ttl_s=self._claim_ttl_s,
        )
        if entry is None:
            return ChatDispatchBridgeOutcome()

        try:
            participant = self._target_participant(entry)
            if participant is None:
                queue.mark_failed(
                    entry.entry_id,
                    failure_reason=f"dispatch_target_not_found:{entry.target}",
                )
                return ChatDispatchBridgeOutcome(claimed=1, failed=1)

            inbox_item_id = self._create_dispatch_inbox_item(entry, participant)
            scheduler = PeerChatScheduler(
                db_path=self._db_path,
                god_layer=self._god_layer,
                worktree=self._worktree,
                scheduler_id=f"{self._bridge_id}:{entry.entry_id}",
                claim_ttl_s=self._claim_ttl_s,
                response_wait_s=self._response_wait_s,
                degraded_fallback_enabled=False,
                only_inbox_item_id=inbox_item_id,
            )
            scheduler_outcome = await scheduler.tick_once()
            if scheduler_outcome.happy_path == 1:
                if not self._has_dispatch_ack_marker(inbox_item_id):
                    queue.mark_failed(
                        entry.entry_id,
                        failure_reason="dispatch_ack_marker_missing",
                    )
                    return ChatDispatchBridgeOutcome(claimed=1, failed=1)
                queue.mark_dispatched(
                    entry.entry_id,
                    provider_run_ref=(
                        f"peer_ack:{participant.role}:{participant.participant_id}"
                    ),
                    dispatch_evidence=f"mcp_writeback:{inbox_item_id}",
                )
                return ChatDispatchBridgeOutcome(claimed=1, dispatched=1)

            queue.mark_failed(
                entry.entry_id,
                failure_reason=self._dispatch_failure_reason(inbox_item_id),
            )
            return ChatDispatchBridgeOutcome(claimed=1, failed=1)
        except Exception as exc:
            try:
                queue.mark_failed(entry.entry_id, failure_reason=str(exc) or "dispatch_failed")
            except Exception:
                pass
            return ChatDispatchBridgeOutcome(claimed=1, failed=1)

    def _target_participant(self, entry: ChatDispatchQueueEntry) -> Participant | None:
        for participant in ParticipantStore(self._db_path).list_by_conversation(
            entry.conversation_id
        ):
            if participant.status == "active" and participant.role == entry.target:
                return participant
        return None

    def _create_dispatch_inbox_item(
        self,
        entry: ChatDispatchQueueEntry,
        participant: Participant,
    ) -> str:
        artifact_context = _dispatch_artifact_context(self._db_path, entry)
        content = _dispatch_prompt(entry, participant, artifact_context=artifact_context)
        payload = ChatStore(self._db_path).create_message_inbox_and_log(
            conversation_id=entry.conversation_id,
            tool_name="chat_dispatch_bridge_enqueue",
            caller_identity=f"dispatch-bridge:{self._bridge_id}",
            client_request_id=f"{entry.entry_id}:dispatch-inbox",
            author="dispatch-bridge",
            role="system",
            content=content,
            envelope_type="dispatch_request",
            envelope_json={
                "type": "dispatch_request",
                "dispatch_queue_entry_id": entry.entry_id,
                "proposal_id": entry.proposal_id,
                "resolution_id": entry.resolution_id,
                "collaboration_run_id": entry.collaboration_run_id,
                "artifact_ref": entry.artifact_ref,
                "dispatch_policy": entry.dispatch_policy,
                **artifact_context,
            },
            mentions=[f"@{participant.role}"],
            inbox_items=[
                {
                    "target_participant_id": participant.participant_id,
                    "target_role": participant.role,
                    "target_address": f"@{participant.role}",
                    "sender_participant_id": None,
                    "sender_address": "@dispatch-bridge",
                    "item_type": "dispatch",
                    "payload": {
                        "content": content,
                        "mention": f"@{participant.role}",
                        "dispatch_queue_entry_id": entry.entry_id,
                        "proposal_id": entry.proposal_id,
                        "resolution_id": entry.resolution_id,
                        "collaboration_run_id": entry.collaboration_run_id,
                        "artifact_ref": entry.artifact_ref,
                        **artifact_context,
                    },
                }
            ],
        )
        items = payload.get("inbox_items")
        if not isinstance(items, list) or not items:
            raise RuntimeError("dispatch bridge did not create an inbox item")
        item_id = items[0].get("id") if isinstance(items[0], dict) else None
        if not isinstance(item_id, str) or not item_id:
            raise RuntimeError("dispatch bridge inbox item is missing an id")
        return item_id

    def _dispatch_failure_reason(self, inbox_item_id: str) -> str:
        trace_reason = self._trace_failure_reason(inbox_item_id)
        if trace_reason:
            return trace_reason
        try:
            item = ChatInboxStore(self._db_path).get(inbox_item_id)
        except KeyError:
            return "dispatch_inbox_item_missing"
        if item.failure_reason:
            return item.failure_reason
        if item.status != "read":
            return f"dispatch_inbox_not_read:{item.status}"
        return "provider_dispatch_failed"

    def _trace_failure_reason(self, inbox_item_id: str) -> str | None:
        try:
            item = ChatInboxStore(self._db_path).get(inbox_item_id)
        except KeyError:
            return None
        traces = PeerTurnLatencyTraceStore(self._db_path).list_recent(
            item.conversation_id,
            limit=20,
        )
        for trace in traces:
            if trace.get("inbox_item_id") != inbox_item_id:
                continue
            reason = trace.get("degraded_reason")
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
        return None

    def _has_dispatch_ack_marker(self, inbox_item_id: str) -> bool:
        try:
            item = ChatInboxStore(self._db_path).get(inbox_item_id)
        except KeyError:
            return False
        if not item.responded_message_id:
            return False
        messages = ChatStore(self._db_path).list_messages(item.conversation_id)
        for message in messages:
            if message.id != item.responded_message_id:
                continue
            return "DISPATCH_ACKNOWLEDGED" in message.content
        return False


def _dispatch_artifact_context(
    db_path: Path,
    entry: ChatDispatchQueueEntry,
) -> dict[str, object]:
    chat = ChatStore(db_path)
    context: dict[str, object] = {}
    if entry.proposal_id:
        try:
            context["proposal"] = chat.get_proposal(entry.proposal_id).model_dump(
                mode="json"
            )
        except KeyError:
            context["proposal"] = {"id": entry.proposal_id, "missing": True}
    if entry.resolution_id:
        try:
            context["resolution"] = chat.get_resolution(entry.resolution_id).model_dump(
                mode="json"
            )
        except KeyError:
            context["resolution"] = {"id": entry.resolution_id, "missing": True}
    return context


def _dispatch_prompt(
    entry: ChatDispatchQueueEntry,
    participant: Participant,
    *,
    artifact_context: dict[str, object] | None = None,
) -> str:
    lines = [
        f"@{participant.role}",
        "Acknowledge this approved xmuse dispatch queue entry as a chat-plane "
        "handoff notice.",
        "",
        f"- Dispatch entry: {entry.entry_id}",
        f"- Proposal: {entry.proposal_id or 'unknown'}",
        f"- Resolution: {entry.resolution_id or 'unknown'}",
        f"- Collaboration run: {entry.collaboration_run_id or 'unknown'}",
        f"- Artifact: {entry.artifact_ref or 'unknown'}",
        f"- Dispatch policy: {entry.dispatch_policy}",
        "",
        "Acknowledgement contract:",
        "- This chat nudge does not execute the lane and must not claim execution.",
        "- Do not edit files, run tests, or inspect unrelated repository state.",
        "- Real worktree execution is handled by the platform lane worker.",
        "- xmuse MCP tools are configured for this dispatch turn; do not claim "
        "that MCP writeback tools are unavailable.",
        "- You must call the MCP tool chat_post_message exactly once after reading "
        "this dispatch context.",
        "- Do not answer with plain text; a plain text acknowledgement is not a "
        "durable dispatch acknowledgement.",
        "- The chat_post_message content must include DISPATCH_ACKNOWLEDGED and "
        "the dispatch entry id.",
        "- If you cannot acknowledge the handoff, still call chat_post_message; "
        "the content must include DISPATCH_ACK_FAILED and the reason.",
    ]
    context = artifact_context or {}
    proposal = context.get("proposal")
    resolution = context.get("resolution")
    if proposal or resolution:
        lines.extend(["", "Approved artifact context:"])
    if isinstance(proposal, dict):
        lines.extend(
            [
                "",
                "Proposal:",
                _compact_json(proposal),
            ]
        )
    if isinstance(resolution, dict):
        lines.extend(
            [
                "",
                "Resolution:",
                _compact_json(resolution),
            ]
        )
    return "\n".join(lines)


def _compact_json(value: dict[str, object], *, max_chars: int = 8000) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _required(value: str, name: str) -> str:
    clean = value.strip() if isinstance(value, str) else ""
    if not clean:
        raise ValueError(f"{name} must not be blank")
    return clean
