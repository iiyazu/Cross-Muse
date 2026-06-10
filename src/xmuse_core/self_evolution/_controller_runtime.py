from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.state_normalizer import normalize_lane_state, summarize_lane_states
from xmuse_core.self_evolution import clarification as clarification_lifecycle
from xmuse_core.self_evolution import dedup as dedup_identity_mod
from xmuse_core.self_evolution.adapters import ChatReader, LanesReader
from xmuse_core.self_evolution.budget import (
    budget_window_for,
    consume_budget_window,
    get_budget_window,
)
from xmuse_core.self_evolution.evidence import aggregator as evidence_aggregator
from xmuse_core.self_evolution.evidence import text as evidence_text
from xmuse_core.self_evolution.models import (
    ClarificationRequest,
    ClarificationResolution,
    EvolutionBudgetWindow,
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
    RunTerminalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.planner import build_lane_graph
from xmuse_core.structuring.projection import project_ready_lanes
from xmuse_core.structuring.verdict_store import VerdictStore

if TYPE_CHECKING:
    from xmuse_core.self_evolution.decomposer import TrackDecomposer

_DEFAULT_SELECTION_POLICY_ID = "xmuse-self-evolution-bootstrap"
_DEFAULT_SELECTION_POLICY_VERSION = "21"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class SelfEvolutionControllerRuntime:
    def __init__(
        self,
        *,
        xmuse_root: Path | str,
        blueprint_path: Path | str,
        store_root: Path | str | None = None,
        lanes_path: Path | str | None = None,
        chat_db_path: Path | str | None = None,
        lanes_reader: LanesReader | None = None,
        chat_reader: ChatReader | None = None,
        decomposer: TrackDecomposer | None = None,
        verdict_store_path: Path | str | None = None,
    ) -> None:
        self._root = Path(xmuse_root)
        self._blueprint_path = Path(blueprint_path)
        self._lanes_path = (
            Path(lanes_path) if lanes_path is not None else self._root / "feature_lanes.json"
        )
        self._store = SelfEvolutionStore(store_root or self._root / "self_evolution")
        _chat_db_path = Path(chat_db_path) if chat_db_path is not None else self._root / "chat.db"
        self._lanes_reader = lanes_reader or LanesReader(
            self._lanes_path,
            xmuse_root=self._root,
        )
        self._chat_reader = chat_reader or ChatReader(_chat_db_path)
        self._chat = ChatStore(_chat_db_path)
        self._graph_store = LaneGraphStore(self._root / "lane_graphs")
        # Resolve the verdict store path.  When an explicit path is given, use
        # it.  Otherwise fall back to the canonical review_plane.json location
        # inside the xmuse root so that run terminal aggregation automatically
        # reads from the authoritative ReviewPlaneController store without
        # requiring explicit wiring at every call site.
        _resolved_verdict_path: Path | None
        if verdict_store_path is not None:
            _resolved_verdict_path = Path(verdict_store_path)
        else:
            _default = self._root / "review_plane.json"
            _resolved_verdict_path = _default if _default.exists() else None
        self._verdict_store: VerdictStore | None = (
            VerdictStore(_resolved_verdict_path) if _resolved_verdict_path is not None else None
        )
        if decomposer is None:
            from xmuse_core.self_evolution.decomposer import SingleLaneDecomposer

            decomposer = SingleLaneDecomposer(
                lane_id_factory=self._candidate_lane_id_for_track,
                prompt_factory=self._candidate_prompt_for_track,
            )
        self._decomposer = decomposer

    @property
    def store(self) -> SelfEvolutionStore:
        return self._store

    def aggregate_run_terminal(self, graph_id: str) -> RunTerminalAggregation:
        graph = self._graph_store.get(graph_id)
        lanes = self._read_lanes()
        lane_by_id = {
            str(lane.get("feature_id")): lane
            for lane in lanes
            if isinstance(lane, dict) and lane.get("feature_id")
        }
        graph_lane_ids = [node.feature_id for node in graph.lanes]
        lineage_lane_ids = self._lineage_lane_ids(graph.id, graph_lane_ids)
        lane_statuses: list[dict[str, Any]] = []
        blocked_objects: list[dict[str, Any]] = []

        for lane_id in lineage_lane_ids:
            lane = lane_by_id.get(lane_id)
            if lane is None:
                lane_statuses.append(
                    {
                        "feature_id": lane_id,
                        "raw_status": "unprojected",
                        "normalized_status": "waiting_dependency",
                        "terminal": False,
                    }
                )
                continue
            normalized = normalize_lane_state(lane)
            lane_status = {
                "feature_id": lane_id,
                "raw_status": normalized.raw_status,
                "normalized_status": normalized.normalized_status,
                "terminal": normalized.is_terminal,
            }
            if lane.get("review_decision"):
                lane_status["review_decision"] = str(lane["review_decision"])
            if lane.get("review_verdict_id"):
                lane_status["review_verdict_id"] = str(lane["review_verdict_id"])
            lane_statuses.append(lane_status)
            blocked = self._blocked_object_for_lane(lane)
            if blocked is not None and (
                normalized.raw_status == "blocked_for_input" or not normalized.is_terminal
            ):
                blocked_objects.append(blocked)

        present_lineage_lanes = [
            lane_by_id[lane_id] for lane_id in lineage_lane_ids if lane_id in lane_by_id
        ]
        lane_counts = summarize_lane_states(present_lineage_lanes)
        final_action_holds: list[dict[str, Any]] = []
        for lane_id in lineage_lane_ids:
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            hold = self._final_action_hold_for_lane(lane)
            if hold is not None:
                final_action_holds.append(hold)
        verdict_lineage = self._build_verdict_lineage(lineage_lane_ids, lane_by_id)
        status, reason = self._aggregate_status(
            lane_statuses,
            blocked_objects,
            final_action_holds,
            verdict_lineage=verdict_lineage,
        )
        aggregation = RunTerminalAggregation(
            aggregation_id=_new_id("runagg"),
            run_id=graph.id,
            resolution_id=graph.resolution_id,
            graph_id=graph.id,
            status=status,
            terminal=status is not RunTerminalStatus.RUNNING,
            reason=reason,
            lane_counts=lane_counts,
            lane_statuses=lane_statuses,
            open_lineages=self._open_lineages(lane_by_id),
            blocked_objects=blocked_objects,
            final_action_holds=final_action_holds,
            verdict_lineage=verdict_lineage,
            created_at=_utc_now(),
        )
        return self._store.save_aggregation(aggregation)

    def build_evidence_bundle(
        self,
        aggregation: RunTerminalAggregation,
        *,
        selection_policy_id: str = _DEFAULT_SELECTION_POLICY_ID,
        selection_policy_version: str = _DEFAULT_SELECTION_POLICY_VERSION,
    ) -> StructuredEvidenceBundle:
        return evidence_aggregator.build_evidence_bundle(
            aggregation=aggregation,
            store=self._store,
            lanes_path=self._lanes_path,
            xmuse_root=self._root,
            blueprint_path=self._blueprint_path,
            selection_policy_id=selection_policy_id,
            selection_policy_version=selection_policy_version,
        )

    def draft_evolution_proposal(
        self,
        evidence: StructuredEvidenceBundle,
        *,
        author_session_id: str = "god-session-architect",
    ) -> EvolutionProposal:
        blueprint = self._read_blueprint()
        blueprint_set_id = self._extract_blueprint_field(blueprint, "blueprint_set_id") or (
            "xmuse-self-evolution-v0"
        )
        target_tracks = self._select_target_tracks(evidence, blueprint)
        primary_track = target_tracks[0] if target_tracks else "graph_authority"
        candidate_lanes = self._decomposer.decompose(primary_track, evidence)
        if not candidate_lanes:
            candidate_lanes = [
                {
                    "feature_id": self._candidate_lane_id(evidence, target_tracks),
                    "title": "Bootstrap the next xmuse self-evolution improvement",
                    "prompt": self._candidate_prompt(evidence, target_tracks),
                    "priority": 100,
                    "capabilities": ["code", "test"],
                    "depends_on": [],
                    "task_type": "execute",
                    "gate_profiles": ["xmuse-core"],
                    "feature_group": primary_track,
                }
            ]
        candidate_lanes = self._candidate_lanes_with_blueprint_refs(candidate_lanes)
        proposal = EvolutionProposal(
            proposal_id=_new_id("evprop"),
            source_run_id=evidence.source_run_id,
            blueprint_set_id=blueprint_set_id,
            target_track_ids=target_tracks,
            status=EvolutionProposalStatus.AWAITING_REVIEW,
            draft_version=1,
            author_session_id=author_session_id,
            scope_summary=self._compose_scope_summary(target_tracks),
            why_now=evidence.summary,
            evidence_bundle_id=evidence.bundle_id,
            candidate_graph={
                "lanes": candidate_lanes,
                "self_evolution": {
                    "source_run_id": evidence.source_run_id,
                    "evidence_bundle_id": evidence.bundle_id,
                    "blueprint_set_id": blueprint_set_id,
                    "target_track_ids": target_tracks,
                },
            },
            review_status="awaiting_review",
            created_at=_utc_now(),
        )
        return self._store.save_proposal(proposal)

    def _candidate_lanes_with_blueprint_refs(self, lanes: list[dict]) -> list[dict]:
        blueprint_ref = self._relative_ref(self._blueprint_path)
        stamped: list[dict] = []
        for lane in lanes:
            lane_payload = dict(lane)
            refs = lane_payload.get("blueprint_refs")
            if isinstance(refs, list):
                ref_values = [str(ref).strip() for ref in refs if str(ref).strip()]
            else:
                ref_values = []
            if blueprint_ref not in ref_values:
                ref_values.append(blueprint_ref)
            lane_payload["blueprint_refs"] = ref_values
            stamped.append(lane_payload)
        return stamped

    def review_proposal(
        self,
        proposal: EvolutionProposal,
        *,
        review_session_id: str = "god-session-review",
    ) -> EvolutionReviewDecision:
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

        review = EvolutionReviewDecision(
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
        self._store.save_review_decision(review)

        proposal.review_status = decision.value
        proposal.status = (
            EvolutionProposalStatus.APPROVED
            if decision is EvolutionReviewKind.APPROVE
            else EvolutionProposalStatus.REJECTED
            if decision is EvolutionReviewKind.REJECT
            else EvolutionProposalStatus.NARROWED_FOR_REDRAFT
        )
        self._store.save_proposal(proposal)
        return review

    def guardrail_check(
        self,
        proposal: EvolutionProposal,
        review: EvolutionReviewDecision,
        aggregation: RunTerminalAggregation,
    ) -> EvolutionGuardrailDecision:
        lanes = proposal.candidate_graph.get("lanes")
        base_checks = {
            "source_run_terminal": aggregation.terminal,
            "review_approved": review.decision is EvolutionReviewKind.APPROVE,
            "mission_envelope": proposal.blueprint_set_id.startswith("xmuse-self-evolution"),
            "candidate_lanes_serializable": isinstance(lanes, list) and bool(lanes),
            "target_tracks_present": bool(proposal.target_track_ids),
        }
        budget_window: EvolutionBudgetWindow | None = None
        budget_ok = True
        dedupe_ok = True
        dedup_key: str | None = None

        if all(base_checks.values()):
            now = _utc_now()
            budget_window, budget_ok = self._budget_window_for(proposal.source_run_id, now)
            dedup_key = self._dedup_identity(proposal)[0]
            dedupe_ok = not self._has_duplicate_evolution(proposal, dedup_key)

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
            budget_window_id=budget_window.window_id if budget_window is not None else None,
            dedup_key=dedup_key,
            terminal_aggregation_ref=aggregation.aggregation_id,
            checks=checks,
            created_at=_utc_now(),
        )
        self._store.save_guardrail_decision(decision)
        if action is not EvolutionGuardrailAction.CONTINUE:
            proposal.status = EvolutionProposalStatus.GUARDRAIL_BLOCKED
            self._store.save_proposal(proposal)
        return decision

    def land_evolution_run(
        self,
        proposal: EvolutionProposal,
        review: EvolutionReviewDecision,
        guardrail: EvolutionGuardrailDecision,
        evidence: StructuredEvidenceBundle,
    ) -> EvolutionLineageRecord:
        if guardrail.action is not EvolutionGuardrailAction.CONTINUE:
            raise RuntimeError("cannot land self-evolution proposal without continue guardrail")

        conversation = self._chat.create_conversation(
            title=f"xmuse self-evolution: {','.join(proposal.target_track_ids)}"
        )
        self._chat.add_message(
            conversation_id=conversation.id,
            author="evolution-controller",
            role="system",
            content=(
                "System-authored self-evolution run opened from "
                f"{evidence.source_run_id} using blueprint {proposal.blueprint_set_id}."
            ),
        )
        chat_proposal = self._chat.create_proposal(
            conversation_id=conversation.id,
            author=proposal.author_session_id,
            proposal_type="self-evolution-lane-plan",
            content=proposal.scope_summary,
            references=evidence.primary_refs,
        )
        resolution = self._chat.approve_proposal(
            proposal_id=chat_proposal.id,
            approved_by=[review.review_session_id],
            approval_mode="god-review",
            goal_summary=proposal.scope_summary,
            content=proposal.candidate_graph,
        )
        graph = build_lane_graph(resolution)
        self._graph_store.save(graph)
        project_ready_lanes(graph, self._lanes_path)
        self._record_landed_guardrail_side_effects(
            proposal,
            guardrail,
            spawned_run_id=graph.id,
        )

        proposal.status = EvolutionProposalStatus.LANDED
        proposal.spawned_conversation_id = conversation.id
        proposal.spawned_resolution_id = resolution.id
        self._store.save_proposal(proposal)
        self._store.save_conversation(
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
        return self._store.save_lineage(lineage)

    def dry_run_from_graph(self, graph_id: str) -> EvolutionLineageRecord:
        aggregation = self.aggregate_run_terminal(graph_id)
        if not aggregation.terminal:
            raise RuntimeError(f"source run is not terminal: {aggregation.status.value}")
        evidence = self.build_evidence_bundle(aggregation)
        proposal = self.draft_evolution_proposal(evidence)
        review = self.review_proposal(proposal)
        guardrail = self.guardrail_check(proposal, review, aggregation)
        return self.land_evolution_run(proposal, review, guardrail, evidence)

    def run_from_evidence_bundle(self, bundle_id: str) -> EvolutionLineageRecord:
        evidence = self._get_evidence_bundle(bundle_id)
        aggregation = self._aggregation_for_evidence(evidence)
        if not aggregation.terminal:
            raise RuntimeError(f"source run is not terminal: {aggregation.status.value}")
        evidence = self._hydrate_evidence_bundle(evidence, aggregation)
        proposal = self.draft_evolution_proposal(evidence)
        review = self.review_proposal(proposal)
        guardrail = self.guardrail_check(proposal, review, aggregation)
        return self.land_evolution_run(proposal, review, guardrail, evidence)

    def record_clarification_request(
        self,
        aggregation: RunTerminalAggregation,
    ) -> ClarificationRequest:
        """Persist a ClarificationRequest for a blocked_for_input run."""
        return clarification_lifecycle.record(aggregation, store=self._store)

    def expire_clarification(
        self,
        request: ClarificationRequest,
        *,
        reason: str = "no response received within the expected window",
    ) -> ClarificationRequest:
        """Mark an open ClarificationRequest as expired."""
        return clarification_lifecycle.expire(request, store=self._store, reason=reason)

    def resolve_clarification(
        self,
        request: ClarificationRequest,
        provided_information: str,
        *,
        provided_by: str = "human",
        provided_context: dict[str, Any] | None = None,
    ) -> ClarificationResolution:
        """Accept provided information and spawn a follow-up resolution."""
        return clarification_lifecycle.resolve(
            request,
            provided_information,
            store=self._store,
            chat=self._chat,
            graph_store=self._graph_store,
            lanes_path=self._lanes_path,
            provided_by=provided_by,
            provided_context=provided_context,
        )

    def _aggregate_status(
        self,
        lane_statuses: list[dict[str, Any]],
        blocked_objects: list[dict[str, Any]],
        final_action_holds: list[dict[str, Any]] | None = None,
        verdict_lineage: list[dict[str, Any]] | None = None,
    ) -> tuple[RunTerminalStatus, str]:
        if blocked_objects:
            return RunTerminalStatus.BLOCKED_FOR_INPUT, "one or more lanes request clarification"

        if not lane_statuses:
            return RunTerminalStatus.RUNNING, "no graph lanes have been projected yet"
        if any(not bool(item["terminal"]) for item in lane_statuses):
            if final_action_holds:
                return (
                    RunTerminalStatus.RUNNING,
                    "one or more lanes are awaiting final-action approval",
                )
            return RunTerminalStatus.RUNNING, "at least one graph lineage lane is not terminal"
        if all(item["normalized_status"] == "merged" for item in lane_statuses):
            return RunTerminalStatus.MERGED, "all graph lineage lanes merged"
        if self._has_unmerged_terminal_lineage(lane_statuses, verdict_lineage or []):
            return (
                RunTerminalStatus.RUNNING,
                "graph lineage merge coordination pending",
            )
        return RunTerminalStatus.TERMINATED, "at least one graph lineage terminalized without merge"

    def _has_unmerged_terminal_lineage(
        self,
        lane_statuses: list[dict[str, Any]],
        verdict_lineage: list[dict[str, Any]],
    ) -> bool:
        """Return True when a terminal lane still needs merge coordination."""

        merged_lane_ids = {
            str(entry.get("lane_id"))
            for entry in verdict_lineage
            if str(entry.get("decision", "")).lower() == "merge"
        }
        closed_lane_ids = merged_lane_ids | {
            str(entry.get("lane_id"))
            for entry in verdict_lineage
            if str(entry.get("decision", "")).lower() == "terminate"
        }
        for status in lane_statuses:
            lane_id = str(status.get("feature_id") or "")
            if not lane_id or lane_id in closed_lane_ids:
                continue
            if (
                bool(status.get("terminal"))
                and status.get("normalized_status") != "merged"
                and self._needs_lineage_merge_coordination(status)
            ):
                return True
        return False

    def _needs_lineage_merge_coordination(self, lane_status: dict[str, Any]) -> bool:
        """Review-rework terminal lanes are still active until merged or closed."""
        review_decision = str(lane_status.get("review_decision", "")).lower()
        return review_decision in {"rework", "patch-forward", "patch_forward"}

    def _get_evidence_bundle(self, bundle_id: str) -> StructuredEvidenceBundle:
        for bundle in self._store.list_evidence_bundles():
            if bundle.bundle_id == bundle_id:
                return bundle
        raise KeyError(f"unknown evidence bundle: {bundle_id}")

    def _aggregation_for_evidence(
        self,
        evidence: StructuredEvidenceBundle,
    ) -> RunTerminalAggregation:
        return self.aggregate_run_terminal(evidence.source_run_id)

    def _budget_window_for(
        self,
        source_run_id: str,
        now: str,
    ) -> tuple[EvolutionBudgetWindow, bool]:
        return budget_window_for(source_run_id, now, store=self._store)

    def _consume_budget_window(
        self,
        budget_window: EvolutionBudgetWindow,
        source_run_id: str,
    ) -> None:
        consume_budget_window(budget_window, source_run_id, store=self._store)

    def _record_landed_guardrail_side_effects(
        self,
        proposal: EvolutionProposal,
        guardrail: EvolutionGuardrailDecision,
        *,
        spawned_run_id: str,
    ) -> None:
        if guardrail.budget_window_id:
            budget_window = self._get_budget_window(guardrail.budget_window_id)
            self._consume_budget_window(budget_window, proposal.source_run_id)
            self._consume_budget_window(budget_window, spawned_run_id)
        if guardrail.dedup_key:
            dedup_key, signal_fingerprint, source_lineage_key = self._dedup_identity(proposal)
            self._record_dedup_continue(
                dedup_key=dedup_key,
                signal_fingerprint=signal_fingerprint,
                source_lineage_key=source_lineage_key,
                proposal=proposal,
            )

    def _get_budget_window(self, window_id: str) -> EvolutionBudgetWindow:
        return get_budget_window(window_id, store=self._store)

    def _dedup_identity(self, proposal: EvolutionProposal) -> tuple[str, str, str]:
        return dedup_identity_mod.dedup_identity(proposal, store=self._store)

    def _dedup_signal_refs(self, signal_refs: list[str]) -> list[str]:
        return dedup_identity_mod.dedup_signal_refs(signal_refs)

    def _has_duplicate_evolution(
        self,
        proposal: EvolutionProposal,
        dedup_key: str,
    ) -> bool:
        return dedup_identity_mod.has_duplicate_evolution(
            proposal, dedup_key, store=self._store
        )

    def _record_dedup_continue(
        self,
        *,
        dedup_key: str,
        signal_fingerprint: str,
        source_lineage_key: str,
        proposal: EvolutionProposal,
    ) -> None:
        dedup_identity_mod.record_dedup_continue(
            dedup_key=dedup_key,
            signal_fingerprint=signal_fingerprint,
            source_lineage_key=source_lineage_key,
            proposal=proposal,
            store=self._store,
        )

    def _read_lanes(self) -> list[dict[str, Any]]:
        return self._lanes_reader.list_lanes()

    def _lineage_lane_ids(
        self,
        graph_id: str,
        graph_lane_ids: list[str],
    ) -> list[str]:
        ordered = list(self._lanes_reader.lineage_lane_ids(graph_id))
        seen = set(ordered)
        for lane_id in graph_lane_ids:
            if lane_id not in seen:
                ordered.append(lane_id)
                seen.add(lane_id)
        return ordered

    def _blocked_object_for_lane(self, lane: dict[str, Any]) -> dict[str, Any] | None:
        return self._lanes_reader.blocked_object_for_lane(lane)

    def _final_action_hold_for_lane(self, lane: dict[str, Any]) -> dict[str, Any] | None:
        return self._lanes_reader.final_action_hold_for_lane(lane)

    def _open_lineages(self, lane_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return self._lanes_reader.open_lineages(lane_by_id)

    def _build_verdict_lineage(
        self,
        lineage_lane_ids: list[str],
        lane_by_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build verdict lineage entries for each lane in the aggregation.

        When a VerdictStore is wired in, verdicts are read from the authoritative
        store.  When no store is available, the lane metadata field
        ``review_verdict_id`` is used as a fallback so the aggregation is still
        explainable from loose lane state.
        """
        result: list[dict[str, Any]] = []
        for lane_id in lineage_lane_ids:
            lane = lane_by_id.get(lane_id)
            if lane is None:
                continue
            if self._verdict_store is not None:
                verdicts = self._verdict_store.list_verdicts_for_lane(lane_id)
                for verdict in verdicts:
                    result.append(
                        {
                            "lane_id": lane_id,
                            "verdict_id": verdict.id,
                            "decision": verdict.decision.value
                            if hasattr(verdict.decision, "value")
                            else str(verdict.decision),
                            "summary": verdict.summary,
                            "source": "verdict_store",
                        }
                    )
            elif lane.get("review_verdict_id"):
                # Fallback: surface the verdict reference from lane metadata
                entry: dict[str, Any] = {
                    "lane_id": lane_id,
                    "verdict_id": str(lane["review_verdict_id"]),
                    "source": "lane_metadata",
                }
                if lane.get("review_decision"):
                    entry["decision"] = str(lane["review_decision"])
                if lane.get("review_summary"):
                    entry["summary"] = evidence_text.compact_signal_text(
                        str(lane["review_summary"]), 160
                    )
                result.append(entry)
        return result

    def _hydrate_evidence_bundle(
        self,
        evidence: StructuredEvidenceBundle,
        aggregation: RunTerminalAggregation,
    ) -> StructuredEvidenceBundle:
        lanes = self._read_lanes()
        relevant_lanes = evidence_aggregator._relevant_lanes_for_aggregation(
            lanes, aggregation
        )
        gate_report_refs = self._merge_refs(
            evidence.gate_report_refs,
            evidence_aggregator._gate_report_refs(relevant_lanes, self._root),
        )
        signal_refs = self._merge_refs(
            [
                signal for signal in evidence.signal_refs
                if not evidence_aggregator._is_generated_signal_ref(signal)
            ],
            [
                evidence_aggregator._lane_counts_ref(aggregation),
                *evidence_aggregator._lane_signal_refs(relevant_lanes, aggregation),
                *evidence_aggregator._gate_report_signal_refs(gate_report_refs),
                *evidence_aggregator._gate_report_resolution_signal_refs(
                    gate_report_refs,
                    self._root,
                ),
                *evidence_aggregator._gate_report_diagnostic_signal_refs(
                    gate_report_refs,
                    self._root,
                ),
                *evidence_aggregator._gate_report_result_signal_refs(
                    gate_report_refs,
                    self._root,
                ),
            ],
        )
        verdict_refs = self._merge_refs(
            evidence.verdict_refs,
            [
                str(lane["review_verdict_id"])
                for lane in relevant_lanes
                if lane.get("review_verdict_id")
            ],
        )
        lineage_refs = self._merge_refs(
            evidence.lineage_refs,
            [
                f"lane:{lane['source_lane_id']}->{lane['feature_id']}"
                for lane in relevant_lanes
                if lane.get("source_lane_id") and lane.get("feature_id")
            ],
        )
        primary_refs = self._merge_refs(
            evidence.primary_refs,
            [
                self._relative_ref(self._lanes_path),
                f"lane_graphs/{aggregation.graph_id}.json",
                self._relative_ref(self._blueprint_path),
            ],
        )
        updated = evidence.model_copy(
            update={
                "summary": evidence_aggregator._evidence_summary(
                    aggregation,
                    signal_refs,
                    self._root,
                ),
                "run_terminal_status": aggregation.status,
                "selection_policy_version": self._hydrated_selection_policy_version(evidence),
                "verdict_refs": verdict_refs,
                "gate_report_refs": gate_report_refs,
                "lineage_refs": lineage_refs,
                "artifact_refs": self._merge_refs(evidence.artifact_refs, primary_refs),
                "signal_refs": signal_refs,
                "primary_refs": primary_refs,
            }
        )
        if updated != evidence:
            self._store.save_evidence_bundle(updated)
        return updated

    def _read_blueprint(self) -> str:
        return self._blueprint_path.read_text(encoding="utf-8")

    def _extract_blueprint_field(self, blueprint: str, field_name: str) -> str | None:
        match = re.search(rf"- `{re.escape(field_name)}`:\s*`([^`]+)`", blueprint)
        return match.group(1) if match else None

    def _select_target_tracks(
        self,
        evidence: StructuredEvidenceBundle,
        blueprint: str,
    ) -> list[str]:
        if evidence.run_terminal_status is RunTerminalStatus.BLOCKED_FOR_INPUT:
            return ["clarification_recovery"]
        track_order = self._blueprint_track_order(blueprint)
        if not track_order:
            return ["graph_authority"]
        landed_counts = self._landed_track_counts()
        return [
            min(
                track_order,
                key=lambda track: (landed_counts.get(track, 0), track_order.index(track)),
            )
        ]

    def _blueprint_track_order(self, blueprint: str) -> list[str]:
        priority_block = re.search(
            r"##\s*Priority\s*Policy.*?(?=\n##\s)", blueprint, flags=re.DOTALL | re.IGNORECASE
        )
        if priority_block:
            ordered = re.findall(r"\d+\.\s+`([a-z0-9_]+)`", priority_block.group(0))
            if ordered:
                return ordered
        track_block = re.search(
            r"##\s*Tracks(.*?)(?=\n##\s|\Z)", blueprint, flags=re.DOTALL | re.IGNORECASE
        )
        if track_block:
            return re.findall(r"###\s+([a-z0-9_]+)", track_block.group(1))
        return []

    def _landed_track_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self._store.list_lineage():
            for track in record.target_track_ids:
                counts[track] = counts.get(track, 0) + 1
        return counts

    def _compose_scope_summary(self, target_tracks: list[str]) -> str:
        if not target_tracks:
            return "Advance xmuse autonomous delivery through the next blueprint track."
        primary = target_tracks[0]
        return (
            f"Advance xmuse blueprint track '{primary}' for autonomous delivery: "
            f"address its next milestone with focused tests and lane evidence."
        )

    def _candidate_lane_id(
        self,
        evidence: StructuredEvidenceBundle,
        target_tracks: list[str],
    ) -> str:
        raw = f"self-evolution-{target_tracks[0]}-{evidence.source_run_id}"
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-").lower()
        return slug[:120]

    def _candidate_lane_id_for_track(
        self,
        evidence: StructuredEvidenceBundle,
        target_track: str,
    ) -> str:
        return self._candidate_lane_id(evidence, [target_track])

    def _candidate_prompt(
        self,
        evidence: StructuredEvidenceBundle,
        target_tracks: list[str],
    ) -> str:
        return (
            "Implement the next xmuse self-evolution improvement for tracks "
            f"{', '.join(target_tracks)}. Use evidence bundle {evidence.bundle_id}. "
            "Focus first on evidence signals: "
            f"{evidence_aggregator._signal_summary(evidence.signal_refs, self._root)}. "
            "Preserve chat -> proposal -> approved resolution -> lane graph -> execution "
            "as the mainline, and add focused tests for the touched substrate."
        )

    def _candidate_prompt_for_track(
        self,
        evidence: StructuredEvidenceBundle,
        target_track: str,
    ) -> str:
        return self._candidate_prompt(evidence, [target_track])

    def _hydrated_selection_policy_version(
        self,
        evidence: StructuredEvidenceBundle,
    ) -> str:
        if evidence.selection_policy_id == _DEFAULT_SELECTION_POLICY_ID:
            return _DEFAULT_SELECTION_POLICY_VERSION
        return evidence.selection_policy_version

    def _merge_refs(self, existing: list[str], additional: list[str]) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()
        for ref in [*existing, *additional]:
            if ref and ref not in seen:
                refs.append(ref)
                seen.add(ref)
        return refs

    def _relative_ref(self, path: Path) -> str:
        try:
            return path.relative_to(self._root).as_posix()
        except ValueError:
            try:
                return path.relative_to(self._root.parent).as_posix()
            except ValueError:
                return path.as_posix()
