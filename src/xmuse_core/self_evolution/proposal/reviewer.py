from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.store import ChatStore
from xmuse_core.self_evolution.budget import (
    budget_window_for,
    consume_budget_window,
    get_budget_window,
)
from xmuse_core.self_evolution.dedup.identity import (
    dedup_identity,
    has_duplicate_evolution,
    record_dedup_continue,
)
from xmuse_core.self_evolution.models import (
    EvolutionConversation,
    EvolutionGuardrailAction,
    EvolutionGuardrailDecision,
    EvolutionLineageRecord,
    EvolutionProposal,
    EvolutionProposalStatus,
    EvolutionReviewDecision,
    EvolutionReviewKind,
    NarrowingDecision,
    RunTerminalAggregation,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.planner import build_lane_graph
from xmuse_core.structuring.projection import project_ready_lanes


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def review(
    proposal: EvolutionProposal,
    *,
    store: SelfEvolutionStore,
    review_session_id: str = "god-session-review",
) -> EvolutionReviewDecision:
    """Review a drafted proposal and persist the decision."""
    lanes = proposal.candidate_graph.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        decision = EvolutionReviewKind.REJECT
        rationale = "candidate graph has no executable lanes"
    elif not proposal.target_track_ids:
        decision = EvolutionReviewKind.REJECT
        rationale = "proposal targets no blueprint track"
    elif any(not isinstance(lane, dict) or not lane.get("feature_id") for lane in lanes):
        decision = EvolutionReviewKind.NARROW
        rationale = "candidate graph contains lanes without stable feature_id"
    else:
        decision = EvolutionReviewKind.APPROVE
        rationale = "candidate graph is scoped to the active blueprint and enters through lanes"

    review_decision = EvolutionReviewDecision(
        decision_id=_new_id("evreview"),
        proposal_id=proposal.proposal_id,
        review_session_id=review_session_id,
        decision=decision,
        rationale=rationale,
        narrowing_decision=(
            NarrowingDecision(
                decision_id=_new_id("narrow"),
                proposal_id=proposal.proposal_id,
                source_review_session_id=review_session_id,
                source_draft_version=proposal.draft_version,
                target_draft_version=proposal.draft_version + 1,
                scope_constraints=["retain blueprint target and reduce invalid lane scope"],
                required_graph_changes=["assign stable feature_id to every candidate lane"],
                required_evidence_focus=[proposal.evidence_bundle_id],
                rationale=rationale,
                created_at=_utc_now(),
            )
            if decision is EvolutionReviewKind.NARROW
            else None
        ),
        created_at=_utc_now(),
    )
    store.save_review_decision(review_decision)
    proposal.review_status = decision.value
    proposal.status = (
        EvolutionProposalStatus.APPROVED
        if decision is EvolutionReviewKind.APPROVE
        else EvolutionProposalStatus.REJECTED
        if decision is EvolutionReviewKind.REJECT
        else EvolutionProposalStatus.NARROWED_FOR_REDRAFT
    )
    store.save_proposal(proposal)
    return review_decision


def guardrail_check(
    proposal: EvolutionProposal,
    review: EvolutionReviewDecision | None = None,
    aggregation: RunTerminalAggregation | None = None,
    *,
    store: SelfEvolutionStore,
) -> EvolutionGuardrailDecision:
    """Run proposal guardrails and persist the decision."""
    lanes = proposal.candidate_graph.get("lanes")
    base_checks = {
        "source_run_terminal": aggregation.terminal if aggregation is not None else False,
        "review_approved": (
            review.decision is EvolutionReviewKind.APPROVE if review is not None else False
        ),
        "mission_envelope": proposal.blueprint_set_id.startswith("xmuse-self-evolution"),
        "candidate_lanes_serializable": isinstance(lanes, list) and bool(lanes),
        "target_tracks_present": bool(proposal.target_track_ids),
    }
    budget_window_id: str | None = None
    budget_ok = True
    dedupe_ok = True
    dedup_key: str | None = None
    if all(base_checks.values()):
        budget_window, budget_ok = budget_window_for(
            proposal.source_run_id,
            _utc_now(),
            store=store,
        )
        budget_window_id = budget_window.window_id
        dedup_key = dedup_identity(proposal, store=store)[0]
        dedupe_ok = not has_duplicate_evolution(
            proposal,
            dedup_key,
            store=store,
        )
    checks = {
        **base_checks,
        "budget_window_active": budget_ok,
        "dedupe_clear": dedupe_ok,
    }
    reason_codes = [name for name, passed in checks.items() if not passed]
    action = (
        EvolutionGuardrailAction.CONTINUE
        if all(checks.values())
        else EvolutionGuardrailAction.HOLD
    )
    decision = EvolutionGuardrailDecision(
        decision_id=_new_id("evguard"),
        proposal_id=proposal.proposal_id,
        action=action,
        rationale=(
            "all bootstrap guardrails passed"
            if action is EvolutionGuardrailAction.CONTINUE
            else f"one or more bootstrap guardrails failed: {', '.join(reason_codes)}"
        ),
        source_run_id=proposal.source_run_id,
        reason_codes=reason_codes,
        budget_window_id=budget_window_id,
        dedup_key=dedup_key,
        terminal_aggregation_ref=(
            aggregation.aggregation_id if aggregation is not None else None
        ),
        checks=checks,
        created_at=_utc_now(),
    )
    store.save_guardrail_decision(decision)
    if action is not EvolutionGuardrailAction.CONTINUE:
        proposal.status = EvolutionProposalStatus.GUARDRAIL_BLOCKED
        store.save_proposal(proposal)
    return decision


def land(
    proposal: EvolutionProposal,
    *,
    store: SelfEvolutionStore,
    lanes_reader: Any,
    chat: ChatStore | None = None,
    graph_store: LaneGraphStore | None = None,
    lanes_path: Path | None = None,
    review: EvolutionReviewDecision | None = None,
    guardrail: EvolutionGuardrailDecision | None = None,
    evidence: StructuredEvidenceBundle | None = None,
) -> EvolutionLineageRecord:
    """Land an approved self-evolution proposal."""
    if review is None or guardrail is None or evidence is None:
        raise ValueError("land requires review, guardrail, and evidence")
    if guardrail.action is not EvolutionGuardrailAction.CONTINUE:
        raise RuntimeError("cannot land self-evolution proposal without continue guardrail")

    root = store.path_for("lineage").parent.parent
    resolved_chat = chat or ChatStore(root / "chat.db")
    resolved_graph_store = graph_store or LaneGraphStore(root / "lane_graphs")
    resolved_lanes_path = lanes_path or lanes_reader.lanes_path
    conversation = resolved_chat.create_conversation(
        title=f"xmuse self-evolution: {','.join(proposal.target_track_ids)}"
    )
    resolved_chat.add_message(
        conversation_id=conversation.id,
        author="evolution-controller",
        role="system",
        content=(
            "System-authored self-evolution run opened from "
            f"{evidence.source_run_id} using blueprint {proposal.blueprint_set_id}."
        ),
    )
    chat_proposal = resolved_chat.create_proposal(
        conversation_id=conversation.id,
        author=proposal.author_session_id,
        proposal_type="self-evolution-lane-plan",
        content=proposal.scope_summary,
        references=evidence.primary_refs,
    )
    resolution = resolved_chat.approve_proposal(
        proposal_id=chat_proposal.id,
        approved_by=[review.review_session_id],
        approval_mode="god-review",
        goal_summary=proposal.scope_summary,
        content=proposal.candidate_graph,
    )
    graph = build_lane_graph(resolution)
    resolved_graph_store.save(graph)
    project_ready_lanes(graph, resolved_lanes_path)
    if guardrail.budget_window_id:
        budget_window = get_budget_window(guardrail.budget_window_id, store=store)
        consume_budget_window(budget_window, proposal.source_run_id, store=store)
        consume_budget_window(budget_window, graph.id, store=store)
    if guardrail.dedup_key:
        dedup_key, signal_fingerprint, source_lineage_key = dedup_identity(
            proposal,
            store=store,
        )
        record_dedup_continue(
            dedup_key=dedup_key,
            signal_fingerprint=signal_fingerprint,
            source_lineage_key=source_lineage_key,
            proposal=proposal,
            store=store,
        )
    proposal.status = EvolutionProposalStatus.LANDED
    proposal.spawned_conversation_id = conversation.id
    proposal.spawned_resolution_id = resolution.id
    store.save_proposal(proposal)
    store.save_conversation(
        EvolutionConversation(
            conversation_id=conversation.id,
            proposal_id=proposal.proposal_id,
            source_run_id=proposal.source_run_id,
            created_by="evolution-controller",
            created_at=_utc_now(),
        )
    )
    lineage = EvolutionLineageRecord(
        lineage_id=_new_id("evlineage"),
        source_run_id=proposal.source_run_id,
        source_resolution_id=evidence.source_resolution_id,
        evidence_bundle_id=evidence.bundle_id,
        evolution_proposal_id=proposal.proposal_id,
        review_decision_id=review.decision_id,
        guardrail_decision_id=guardrail.decision_id,
        spawned_conversation_id=conversation.id,
        spawned_proposal_id=chat_proposal.id,
        spawned_resolution_id=resolution.id,
        spawned_graph_id=graph.id,
        blueprint_set_id=proposal.blueprint_set_id,
        target_track_ids=list(proposal.target_track_ids),
        terminal_aggregation_ref=guardrail.terminal_aggregation_ref,
        created_at=_utc_now(),
    )
    return store.save_lineage(lineage)
