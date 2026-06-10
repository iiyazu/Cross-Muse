"""Clarification-request lifecycle extracted from SelfEvolutionController.

A ClarificationRequest formalizes a blocked-for-input run so it can be
resumed once the missing information arrives. ``resolve`` re-enters the
standard mainline (chat -> proposal -> approved resolution -> lane graph).
Collaborators (chat store, graph store, lanes path) are passed explicitly so
these functions stay free of controller state.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.store import ChatStore
from xmuse_core.self_evolution.models import (
    ClarificationRequest,
    ClarificationResolution,
    ClarificationStatus,
    RunTerminalAggregation,
    RunTerminalStatus,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.planner import build_lane_graph
from xmuse_core.structuring.projection import project_ready_lanes


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def build_resume_lanes(
    request: ClarificationRequest,
    resolution: ClarificationResolution,
) -> list[dict[str, Any]]:
    """Build candidate lanes for a clarification-recovery follow-up run."""
    lane_id = f"clarification-recovery-{request.source_run_id}-{resolution.resolution_id}"
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", lane_id).strip("-").lower()
    lane_id = slug[:120]
    prompt = (
        f"Resume the blocked run {request.source_run_id} using the provided information. "
        f"Missing input was: {request.missing_input_summary}. "
        f"Provided information: {resolution.provided_information}. "
        f"Resume path: {request.resume_path}. "
        "Re-enter the standard mainline: chat -> proposal -> approved resolution "
        "-> lane graph -> execution."
    )
    return [
        {
            "feature_id": lane_id,
            "title": f"Resume blocked run {request.source_run_id}",
            "prompt": prompt,
            "priority": 100,
            "capabilities": ["code", "test"],
            "depends_on": [],
            "task_type": "execute",
            "gate_profiles": ["xmuse-core"],
            "feature_group": "clarification_recovery",
        }
    ]


def resume_lanes(graph_id: str, *, lanes_reader: Any) -> list[str]:
    """Return lane IDs that belong to the graph lineage to be resumed."""
    return list(lanes_reader.lineage_lane_ids(graph_id))


def record(
    aggregation: RunTerminalAggregation,
    *,
    store: SelfEvolutionStore,
) -> ClarificationRequest:
    """Persist a ClarificationRequest for a blocked_for_input run.

    Converts the loose blocked_objects from the aggregation into a formal,
    resumable ClarificationRequest. The request stays open until ``resolve``
    is called with the provided information.
    """
    if aggregation.status is not RunTerminalStatus.BLOCKED_FOR_INPUT:
        raise ValueError(
            f"cannot record clarification request for non-blocked run: "
            f"{aggregation.status.value}"
        )
    blocked = aggregation.blocked_objects
    missing_parts = [
        str(obj.get("missing_input", "unspecified"))
        for obj in blocked
        if isinstance(obj, dict)
    ]
    missing_summary = "; ".join(missing_parts) if missing_parts else "unspecified"
    owner = "human"
    for obj in blocked:
        if isinstance(obj, dict) and obj.get("owner"):
            owner = str(obj["owner"])
            break
    resume_parts = [
        str(obj.get("resume_path", "provide information and resume graph"))
        for obj in blocked
        if isinstance(obj, dict) and obj.get("resume_path")
    ]
    resume_path = resume_parts[0] if resume_parts else "provide information and reproject graph"
    request = ClarificationRequest(
        request_id=_new_id("clarreq"),
        source_run_id=aggregation.run_id,
        aggregation_id=aggregation.aggregation_id,
        blocked_objects=list(blocked),
        missing_input_summary=missing_summary,
        owner=owner,
        resume_path=resume_path,
        status=ClarificationStatus.OPEN,
        created_at=_utc_now(),
    )
    return store.save_clarification_request(request)


def expire(
    request: ClarificationRequest,
    *,
    store: SelfEvolutionStore,
    reason: str = "no response received within the expected window",
) -> ClarificationRequest:
    """Mark an open ClarificationRequest as expired.

    The run remains blocked; a new clarification request can be opened if the
    information later becomes available. Raises ValueError if not open.
    """
    if request.status is not ClarificationStatus.OPEN:
        raise ValueError(
            f"cannot expire clarification request with status: {request.status.value}"
        )
    request.status = ClarificationStatus.EXPIRED
    request.resolved_at = _utc_now()
    return store.save_clarification_request(request)


def resolve(
    request: ClarificationRequest,
    provided_information: str,
    *,
    store: SelfEvolutionStore,
    chat: ChatStore,
    graph_store: LaneGraphStore,
    lanes_path: Path,
    provided_by: str = "human",
    provided_context: dict[str, Any] | None = None,
) -> ClarificationResolution:
    """Accept provided information and spawn a follow-up resolution.

    The follow-up resolution re-enters the standard mainline:
    chat -> proposal -> approved resolution -> lane graph -> execution.
    The spawned graph carries the original blocked lane context plus the
    provided information so the next execution attempt has full context.
    """
    if request.status is not ClarificationStatus.OPEN:
        raise ValueError(
            f"cannot resolve clarification request with status: {request.status.value}"
        )
    now = _utc_now()
    resolution = ClarificationResolution(
        resolution_id=_new_id("clarres"),
        request_id=request.request_id,
        source_run_id=request.source_run_id,
        provided_information=provided_information,
        provided_context=provided_context or {},
        provided_by=provided_by,
        created_at=now,
    )
    candidate_lanes = build_resume_lanes(request, resolution)
    conversation = chat.create_conversation(
        title=f"xmuse clarification-recovery: {request.source_run_id}"
    )
    chat.add_message(
        conversation_id=conversation.id,
        author="evolution-controller",
        role="system",
        content=(
            f"Clarification provided for blocked run {request.source_run_id}. "
            f"Missing input: {request.missing_input_summary}. "
            f"Provided by: {provided_by}."
        ),
    )
    chat_proposal = chat.create_proposal(
        conversation_id=conversation.id,
        author=provided_by,
        proposal_type="clarification-recovery",
        content=(
            f"Resume blocked run {request.source_run_id} with provided information: "
            f"{provided_information}"
        ),
        references=[f"clarification_requests/{request.request_id}"],
    )
    candidate_graph: dict[str, Any] = {
        "lanes": candidate_lanes,
        "clarification_recovery": {
            "source_run_id": request.source_run_id,
            "request_id": request.request_id,
            "resolution_id": resolution.resolution_id,
            "provided_information": provided_information,
        },
    }
    chat_resolution = chat.approve_proposal(
        proposal_id=chat_proposal.id,
        approved_by=[provided_by],
        approval_mode="clarification-recovery",
        goal_summary=(
            f"Resume blocked run {request.source_run_id} with provided information"
        ),
        content=candidate_graph,
    )
    graph = build_lane_graph(chat_resolution)
    graph_store.save(graph)
    project_ready_lanes(graph, lanes_path)
    request.status = ClarificationStatus.RESOLVED
    request.resolved_at = now
    store.save_clarification_request(request)
    resolution.spawned_conversation_id = conversation.id
    resolution.spawned_resolution_id = chat_resolution.id
    resolution.spawned_graph_id = graph.id
    return store.save_clarification_resolution(resolution)
