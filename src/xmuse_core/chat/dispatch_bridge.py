from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from xmuse_core.chat.dispatch_queue import ChatDispatchQueueEntry, ChatDispatchQueueStore
from xmuse_core.chat.store import ChatStore


@dataclass(frozen=True)
class ChatDispatchBridgeOutcome:
    claimed: int = 0
    dispatched: int = 0
    failed: int = 0


class ChatDispatchBridge:
    """Bridge gated chat dispatch queue entries to the lane-worker authority path."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        god_layer,
        worktree: Path | str,
        bridge_id: str,
        lanes_path: Path | str | None = None,
        response_wait_s: float = 300.0,
        claim_ttl_s: int = 360,
    ) -> None:
        self._db_path = Path(db_path)
        self._god_layer = god_layer
        self._worktree = Path(worktree)
        self._lanes_path = Path(lanes_path) if lanes_path is not None else None
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
            lane_context = _dispatch_lane_context(
                entry,
                lanes_path=self._lanes_path,
            )
            if lane_context is None:
                queue.mark_failed(
                    entry.entry_id,
                    failure_reason="lane_worker_projection_missing",
                )
                return ChatDispatchBridgeOutcome(claimed=1, failed=1)

            message_id = self._create_lane_worker_handoff_message(entry, lane_context)
            queue.mark_dispatched(
                entry.entry_id,
                provider_run_ref=f"lane_worker:{lane_context['feature_id']}",
                dispatch_evidence=(
                    f"dispatch_handoff:{message_id}:"
                    f"feature_lanes:{lane_context['feature_id']}:{lane_context['status']}"
                ),
            )
            return ChatDispatchBridgeOutcome(claimed=1, dispatched=1)
        except Exception as exc:
            try:
                queue.mark_failed(entry.entry_id, failure_reason=str(exc) or "dispatch_failed")
            except Exception:
                pass
            return ChatDispatchBridgeOutcome(claimed=1, failed=1)

    def _create_lane_worker_handoff_message(
        self,
        entry: ChatDispatchQueueEntry,
        lane_context: dict[str, str],
    ) -> str:
        artifact_context = _dispatch_artifact_context(self._db_path, entry)
        execution_worktree = lane_context["worktree"]
        content = _lane_worker_handoff_content(
            entry,
            lane_context=lane_context,
            execution_worktree=execution_worktree,
            artifact_context=artifact_context,
        )
        message = ChatStore(self._db_path).add_message(
            conversation_id=entry.conversation_id,
            author="dispatch-bridge",
            role="system",
            content=content,
            envelope_type="dispatch_handoff",
            envelope_json={
                "type": "dispatch_handoff",
                "dispatch_queue_entry_id": entry.entry_id,
                "proposal_id": entry.proposal_id,
                "resolution_id": entry.resolution_id,
                "collaboration_run_id": entry.collaboration_run_id,
                "artifact_ref": entry.artifact_ref,
                "dispatch_policy": entry.dispatch_policy,
                "lane_worker_authority": "feature_lanes",
                "lane_id": lane_context["feature_id"],
                "lane_status": lane_context["status"],
                "execution_worktree": execution_worktree,
                **artifact_context,
            },
            mentions=[],
        )
        return message.id


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


def _dispatch_lane_context(
    entry: ChatDispatchQueueEntry,
    *,
    lanes_path: Path | None,
) -> dict[str, str] | None:
    if lanes_path is None or not lanes_path.exists():
        return None
    try:
        payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    lanes = payload.get("lanes") if isinstance(payload, dict) else None
    if not isinstance(lanes, list):
        return None
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if entry.resolution_id and lane.get("resolution_id") != entry.resolution_id:
            continue
        feature_id = lane.get("feature_id")
        if not isinstance(feature_id, str) or not feature_id.strip():
            continue
        worktree = lane.get("worktree")
        if not isinstance(worktree, str) or not worktree.strip():
            continue
        status = lane.get("status")
        return {
            "feature_id": feature_id.strip(),
            "status": status.strip() if isinstance(status, str) and status.strip() else "unknown",
            "worktree": worktree.strip(),
        }
    return None


def _lane_worker_handoff_content(
    entry: ChatDispatchQueueEntry,
    *,
    lane_context: dict[str, str],
    execution_worktree: str,
    artifact_context: dict[str, object] | None = None,
) -> str:
    lines = [
        "LANE_WORKER_HANDOFF",
        "This chat dispatch queue entry is delegated to the platform lane worker.",
        "",
        f"- Dispatch entry: {entry.entry_id}",
        f"- Proposal: {entry.proposal_id or 'unknown'}",
        f"- Resolution: {entry.resolution_id or 'unknown'}",
        f"- Collaboration run: {entry.collaboration_run_id or 'unknown'}",
        f"- Artifact: {entry.artifact_ref or 'unknown'}",
        f"- Dispatch policy: {entry.dispatch_policy}",
        f"- Lane: {lane_context['feature_id']}",
        f"- Lane status at handoff: {lane_context['status']}",
        f"- Execution worktree: {execution_worktree}",
        "",
        "Boundary:",
        "- This message is not peer-chat execution truth.",
        "- Final execution/review truth remains with feature_lanes and review artifacts.",
    ]
    artifact_context = artifact_context or {}
    proposal = artifact_context.get("proposal")
    resolution = artifact_context.get("resolution")
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
