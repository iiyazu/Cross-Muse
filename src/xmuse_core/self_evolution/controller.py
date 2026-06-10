from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from xmuse_core.chat.store import ChatStore
from xmuse_core.self_evolution import clarification as clarification_lifecycle
from xmuse_core.self_evolution._controller_runtime import SelfEvolutionControllerRuntime
from xmuse_core.self_evolution.adapters import ChatReader, LanesReader
from xmuse_core.self_evolution.evidence import aggregator as evidence_aggregator
from xmuse_core.self_evolution.models import (
    ClarificationRequest,
    ClarificationResolution,
    EvolutionGuardrailDecision,
    EvolutionLineageRecord,
    EvolutionProposal,
    EvolutionReviewDecision,
    RunTerminalAggregation,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.proposal import drafter, reviewer
from xmuse_core.self_evolution.store import SelfEvolutionStore
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.verdict_store import VerdictStore

if TYPE_CHECKING:
    from xmuse_core.self_evolution.decomposer import TrackDecomposer


class SelfEvolutionController:
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
        self._runtime = SelfEvolutionControllerRuntime(
            xmuse_root=xmuse_root,
            blueprint_path=blueprint_path,
            store_root=store_root,
            lanes_path=lanes_path,
            chat_db_path=chat_db_path,
            lanes_reader=lanes_reader,
            chat_reader=chat_reader,
            decomposer=decomposer,
            verdict_store_path=verdict_store_path,
        )
        for name in (
            "_root",
            "_blueprint_path",
            "_lanes_path",
            "_store",
            "_lanes_reader",
            "_chat_reader",
            "_chat",
            "_graph_store",
            "_verdict_store",
            "_decomposer",
        ):
            setattr(self, name, getattr(self._runtime, name))

    @property
    def store(self) -> SelfEvolutionStore:
        return self._runtime.store

    def aggregate_run_terminal(self, graph_id: str) -> RunTerminalAggregation:
        return evidence_aggregator.aggregate_run_terminal(
            graph_id,
            lanes_reader=self._lanes_reader,
            store=self._store,
            verdict_store=self._verdict_store,
        )

    def build_evidence_bundle(
        self,
        aggregation: RunTerminalAggregation,
        *,
        selection_policy_id: str = "xmuse-self-evolution-bootstrap",
        selection_policy_version: str = "21",
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
        blueprint = self._blueprint_path.read_text(encoding="utf-8")
        target_track = drafter.select_target_track(
            evidence,
            blueprint,
            store=self._store,
        )
        return drafter.draft(
            evidence=evidence,
            target_track=target_track,
            decomposer=self._decomposer,
            store=self._store,
            author_session_id=author_session_id,
            blueprint_set_id=drafter.blueprint_set_id(blueprint),
            blueprint_ref=drafter.blueprint_ref(self._blueprint_path, root=self._root),
            fallback_lane_id=self._runtime._candidate_lane_id(evidence, [target_track]),
            fallback_prompt=self._runtime._candidate_prompt(evidence, [target_track]),
        )

    def review_proposal(
        self,
        proposal: EvolutionProposal,
        *,
        review_session_id: str = "god-session-review",
    ) -> EvolutionReviewDecision:
        return reviewer.review(
            proposal,
            store=self._store,
            review_session_id=review_session_id,
        )

    def guardrail_check(
        self,
        proposal: EvolutionProposal,
        review: EvolutionReviewDecision,
        aggregation: RunTerminalAggregation,
    ) -> EvolutionGuardrailDecision:
        return reviewer.guardrail_check(
            proposal,
            review,
            aggregation,
            store=self._store,
        )

    def land_evolution_run(
        self,
        proposal: EvolutionProposal,
        review: EvolutionReviewDecision,
        guardrail: EvolutionGuardrailDecision,
        evidence: StructuredEvidenceBundle,
    ) -> EvolutionLineageRecord:
        return reviewer.land(
            proposal,
            store=self._store,
            lanes_reader=self._lanes_reader,
            chat=self._chat,
            graph_store=self._graph_store,
            lanes_path=self._lanes_path,
            review=review,
            guardrail=guardrail,
            evidence=evidence,
        )

    def dry_run_from_graph(self, graph_id: str) -> EvolutionLineageRecord:
        return self._dry_run_from_graph(graph_id)

    def _dry_run_from_graph(self, graph_id: str) -> EvolutionLineageRecord:
        aggregation = self.aggregate_run_terminal(graph_id)
        if not aggregation.terminal:
            raise RuntimeError(f"source run is not terminal: {aggregation.status.value}")
        evidence = self.build_evidence_bundle(aggregation)
        proposal = self.draft_evolution_proposal(evidence)
        review = self.review_proposal(proposal)
        guardrail = self.guardrail_check(proposal, review, aggregation)
        return self.land_evolution_run(proposal, review, guardrail, evidence)

    def run_from_evidence_bundle(self, bundle_id: str) -> EvolutionLineageRecord:
        return self._run_from_evidence_bundle(bundle_id)

    def _run_from_evidence_bundle(self, bundle_id: str) -> EvolutionLineageRecord:
        evidence = self._runtime._get_evidence_bundle(bundle_id)
        aggregation = self.aggregate_run_terminal(evidence.source_run_id)
        if not aggregation.terminal:
            raise RuntimeError(f"source run is not terminal: {aggregation.status.value}")
        hydrated = self._runtime._hydrate_evidence_bundle(evidence, aggregation)
        proposal = self.draft_evolution_proposal(hydrated)
        review = self.review_proposal(proposal)
        guardrail = self.guardrail_check(proposal, review, aggregation)
        return self.land_evolution_run(proposal, review, guardrail, hydrated)

    def record_clarification_request(
        self,
        aggregation: RunTerminalAggregation,
    ) -> ClarificationRequest:
        return clarification_lifecycle.record(aggregation, store=self._store)

    def expire_clarification(
        self,
        request: ClarificationRequest,
        *,
        reason: str = "no response received within the expected window",
    ) -> ClarificationRequest:
        return clarification_lifecycle.expire(request, store=self._store, reason=reason)

    def resolve_clarification(
        self,
        request: ClarificationRequest,
        provided_information: str,
        *,
        provided_by: str = "human",
        provided_context: dict[str, Any] | None = None,
    ) -> ClarificationResolution:
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


__all__ = [
    "ChatReader",
    "ChatStore",
    "LaneGraphStore",
    "LanesReader",
    "SelfEvolutionController",
    "SelfEvolutionStore",
    "VerdictStore",
]
