from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.chat.models import ChatMessage, Conversation
from xmuse_core.chat.store import ChatStore


def write_minimal_fullchain_proof(
    xmuse_root: Path | str,
    *,
    conversation_id: str,
    proposal_id: str,
    resolution_id: str,
    lane_id: str,
    proof_path: Path | str,
    command_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write a proof artifact by reading existing authority records only."""
    root = Path(xmuse_root)
    chat = ChatStore(root / "chat.db")
    conversation = _require_conversation(chat, conversation_id)
    proposal = chat.get_proposal(proposal_id)
    if proposal.conversation_id != conversation_id:
        raise ValueError("proposal_conversation_mismatch")
    resolution = chat.get_resolution(resolution_id)
    if resolution.conversation_id != conversation_id:
        raise ValueError("resolution_conversation_mismatch")
    if proposal.accepted_resolution_id != resolution_id:
        raise ValueError("proposal_resolution_mismatch")
    if proposal.id not in resolution.derived_from_proposal_ids:
        raise ValueError("resolution_missing_proposal_ref")

    human_demand = _require_human_demand_message(
        chat,
        conversation_id=conversation_id,
        proposal_references=proposal.references,
    )
    lanes = _read_json(root / "feature_lanes.json").get("lanes", [])
    lane = _require_lane(lanes, lane_id=lane_id)
    if lane.get("resolution_id") != resolution_id:
        raise ValueError("lane_resolution_mismatch")

    review_plane = _read_json(root / "review_plane.json")
    review_task = _require_review_task(review_plane, lane_id=lane_id)
    review_verdict = _require_review_verdict(
        review_plane,
        lane_id=lane_id,
        task_id=str(review_task.get("task_id") or ""),
    )
    final_action_hold = _require_final_action_hold(
        _read_json(root / "final_actions.json"),
        lane_id=lane_id,
        verdict_id=str(review_verdict.get("id") or ""),
    )
    graph_ref = _require_lane_graph(root, lane)

    proof = {
        "proof_type": "minimal_groupchat_fullchain",
        "proof_level": "local_runtime_proof",
        "status": lane.get("status"),
        "conversation": conversation.model_dump(mode="json"),
        "human_demand_message": human_demand.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "resolution": resolution.model_dump(mode="json"),
        "lane": lane,
        "lane_graph_ref": graph_ref,
        "review_task": review_task,
        "review_verdict": review_verdict,
        "final_action_hold": final_action_hold,
        "authority_refs": {
            "chat_db": str(root / "chat.db"),
            "lane_graphs": str(root / "lane_graphs"),
            "feature_lanes": str(root / "feature_lanes.json"),
            "review_plane": str(root / "review_plane.json"),
            "final_actions": str(root / "final_actions.json"),
        },
        "command_evidence": command_evidence or [],
        "forbidden_claims": [
            "natural_peer_god_groupchat",
            "github_server_merge",
            "live_memoryos_write",
            "full_autonomous_overnight_readiness",
        ],
    }
    target = Path(proof_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(proof, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return proof


def _require_conversation(chat: ChatStore, conversation_id: str) -> Conversation:
    for conversation in chat.list_conversations():
        if conversation.id == conversation_id:
            return conversation
    raise ValueError("conversation_missing")


def _require_human_demand_message(
    chat: ChatStore,
    *,
    conversation_id: str,
    proposal_references: list[str],
) -> ChatMessage:
    referenced_message_ids = {
        ref.removeprefix("message:")
        for ref in proposal_references
        if ref.startswith("message:") and ref.removeprefix("message:")
    }
    messages = chat.list_messages(conversation_id)
    for message in messages:
        if message.id in referenced_message_ids and message.role == "user":
            return message
    raise ValueError("human_demand_message_missing")


def _require_lane(lanes: object, *, lane_id: str) -> dict[str, Any]:
    if not isinstance(lanes, list):
        raise ValueError("feature_lanes_malformed")
    for lane in lanes:
        if isinstance(lane, dict) and lane.get("feature_id") == lane_id:
            return lane
    raise ValueError("lane_missing")


def _require_review_task(review_plane: dict[str, Any], *, lane_id: str) -> dict[str, Any]:
    tasks = review_plane.get("review_tasks")
    if not isinstance(tasks, list):
        raise ValueError("review_tasks_missing")
    matches = [
        task
        for task in tasks
        if isinstance(task, dict) and task.get("lane_id") == lane_id
    ]
    if not matches:
        raise ValueError("review_task_missing")
    return matches[-1]


def _require_review_verdict(
    review_plane: dict[str, Any],
    *,
    lane_id: str,
    task_id: str,
) -> dict[str, Any]:
    verdicts = review_plane.get("review_verdicts")
    if not isinstance(verdicts, list):
        raise ValueError("review_verdicts_missing")
    for verdict in reversed(verdicts):
        if (
            isinstance(verdict, dict)
            and verdict.get("lane_id") == lane_id
            and verdict.get("task_id") == task_id
        ):
            return verdict
    raise ValueError("review_verdict_missing")


def _require_final_action_hold(
    final_actions: dict[str, Any],
    *,
    lane_id: str,
    verdict_id: str,
) -> dict[str, Any]:
    holds = final_actions.get("holds")
    if not isinstance(holds, list):
        raise ValueError("final_action_holds_missing")
    for hold in reversed(holds):
        if (
            isinstance(hold, dict)
            and hold.get("lane_id") == lane_id
            and hold.get("verdict_id") == verdict_id
            and hold.get("status") == "pending"
        ):
            return hold
    raise ValueError("pending_final_action_hold_missing")


def _require_lane_graph(root: Path, lane: dict[str, Any]) -> str:
    graph_id = lane.get("graph_id")
    if not isinstance(graph_id, str) or not graph_id:
        raise ValueError("lane_graph_id_missing")
    path = root / "lane_graphs" / f"{graph_id}.json"
    if not path.exists():
        raise ValueError("lane_graph_missing")
    return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{path.name}_missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}_malformed")
    return data
