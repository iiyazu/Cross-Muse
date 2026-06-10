from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from xmuse_core.self_evolution import SelfEvolutionController
from xmuse_core.self_evolution.adapters import LanesReader
from xmuse_core.self_evolution.budget.window import BudgetWindow
from xmuse_core.self_evolution.clarification.lifecycle import resume_lanes
from xmuse_core.self_evolution.evidence.aggregator import (
    aggregate_run_terminal,
    build_evidence_bundle,
)
from xmuse_core.self_evolution.models import (
    EvolutionGuardrailAction,
    EvolutionProposal,
    EvolutionProposalStatus,
    EvolutionReviewKind,
    RunTerminalAggregation,
    RunTerminalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.proposal.drafter import dedup_signal_refs
from xmuse_core.self_evolution.proposal.reviewer import guardrail_check, review
from xmuse_core.self_evolution.store import SelfEvolutionStore
from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict
from xmuse_core.structuring.verdict_store import VerdictStore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_blueprint(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
# xmuse Initial Self-Evolution Blueprint

- `blueprint_set_id`: `xmuse-self-evolution-v0`

## Tracks

### graph_authority
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _seed_graph(root: Path, graph_id: str = "res-decomp-graph-v1") -> str:
    _write_json(
        root / "lane_graphs" / f"{graph_id}.json",
        {
            "id": graph_id,
            "conversation_id": "conv-decomp",
            "resolution_id": "res-decomp",
            "version": 1,
            "lanes": [{"feature_id": "lane-decomp", "prompt": "do it"}],
        },
    )
    _write_json(
        root / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-decomp",
                    "graph_id": graph_id,
                    "resolution_id": "res-decomp",
                    "status": "merged",
                    "review_verdict_id": "verdict-decomp",
                }
            ]
        },
    )
    return graph_id


def _seed_partially_projected_graph(root: Path) -> str:
    graph_id = "res-partial-graph-v1"
    _write_json(
        root / "lane_graphs" / f"{graph_id}.json",
        {
            "id": graph_id,
            "conversation_id": "conv-partial",
            "resolution_id": "res-partial",
            "version": 1,
            "lanes": [
                {"feature_id": "lane-a", "prompt": "first"},
                {
                    "feature_id": "lane-b",
                    "prompt": "second",
                    "depends_on": ["lane-a"],
                },
            ],
        },
    )
    _write_json(
        root / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-a",
                    "graph_id": graph_id,
                    "resolution_id": "res-partial",
                    "status": "merged",
                }
            ]
        },
    )
    return graph_id


def _proposal_for_landing() -> EvolutionProposal:
    return EvolutionProposal(
        proposal_id="evprop-land",
        source_run_id="source-graph",
        blueprint_set_id="xmuse-self-evolution-v0",
        target_track_ids=["graph_authority"],
        status=EvolutionProposalStatus.APPROVED,
        draft_version=1,
        author_session_id="god-session-architect",
        scope_summary="land a configured-path graph",
        why_now="terminal run",
        evidence_bundle_id="evbundle-land",
        candidate_graph={
            "lanes": [
                {
                    "feature_id": "landed-lane",
                    "prompt": "implement configured landing",
                    "depends_on": [],
                    "task_type": "execute",
                    "capabilities": ["code"],
                    "priority": 100,
                }
            ]
        },
        review_status="approve",
        created_at="2026-05-30T00:00:00Z",
    )



def test_evidence_aggregator_module_builds_and_persists_aggregation(tmp_path: Path) -> None:
    graph_id = _seed_graph(tmp_path)
    blueprint = tmp_path / "blueprint.md"
    _write_blueprint(blueprint)
    controller = SelfEvolutionController(xmuse_root=tmp_path, blueprint_path=blueprint)

    aggregation = aggregate_run_terminal(graph_id, lanes_reader=controller._lanes_reader)
    evidence = build_evidence_bundle(aggregation=aggregation, store=controller.store)

    assert aggregation.status is RunTerminalStatus.MERGED
    assert controller.store.list_aggregations()[-1].aggregation_id == aggregation.aggregation_id
    assert evidence.source_run_id == graph_id
    assert controller.store.list_evidence_bundles()[-1].bundle_id == evidence.bundle_id


def test_evidence_aggregator_uses_supplied_lanes_reader_without_controller_runtime(
    tmp_path: Path,
) -> None:
    graph_id = _seed_graph(tmp_path, "graph-from-lanes")
    lanes_reader = LanesReader(tmp_path / "feature_lanes.json")

    aggregation = aggregate_run_terminal(graph_id, lanes_reader=lanes_reader)

    assert aggregation.graph_id == graph_id
    assert aggregation.status is RunTerminalStatus.MERGED


def test_controller_aggregation_uses_configured_store_root(tmp_path: Path) -> None:
    graph_id = _seed_graph(tmp_path)
    blueprint = tmp_path / "blueprint.md"
    store_root = tmp_path / "custom-self-evolution"
    _write_blueprint(blueprint)
    controller = SelfEvolutionController(
        xmuse_root=tmp_path,
        blueprint_path=blueprint,
        store_root=store_root,
    )

    aggregation = controller.aggregate_run_terminal(graph_id)

    assert controller.store.list_aggregations()[-1].aggregation_id == aggregation.aggregation_id
    assert (store_root / "run_aggregations.json").exists()
    assert not (tmp_path / "self_evolution" / "run_aggregations.json").exists()


def test_controller_aggregation_uses_configured_verdict_store_path(tmp_path: Path) -> None:
    graph_id = _seed_graph(tmp_path)
    blueprint = tmp_path / "blueprint.md"
    verdict_store_path = tmp_path / "review" / "custom-review-plane.json"
    _write_blueprint(blueprint)
    VerdictStore(verdict_store_path).save_verdict(
        ReviewVerdict(
            id="verdict-configured",
            lane_id="lane-decomp",
            decision=ReviewDecision.MERGE,
            summary="Configured verdict store was used.",
        )
    )
    controller = SelfEvolutionController(
        xmuse_root=tmp_path,
        blueprint_path=blueprint,
        verdict_store_path=verdict_store_path,
    )

    aggregation = controller.aggregate_run_terminal(graph_id)

    assert aggregation.verdict_lineage == [
        {
            "lane_id": "lane-decomp",
            "verdict_id": "verdict-configured",
            "decision": "merge",
            "summary": "Configured verdict store was used.",
            "source": "verdict_store",
        }
    ]


def test_lanes_reader_uses_configured_xmuse_root_for_graph_snapshots(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "xmuse-root"
    lanes_root = tmp_path / "queue-root"
    graph_id = _seed_graph(xmuse_root)
    (lanes_root).mkdir()
    (lanes_root / "feature_lanes.json").write_text(
        (xmuse_root / "feature_lanes.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    lanes_reader = LanesReader(
        lanes_root / "feature_lanes.json",
        xmuse_root=xmuse_root,
    )

    aggregation = aggregate_run_terminal(graph_id, lanes_reader=lanes_reader)

    assert aggregation.status is RunTerminalStatus.MERGED
    assert [item["feature_id"] for item in aggregation.lane_statuses] == ["lane-decomp"]
    assert not (lanes_root / "lane_graphs").exists()


def test_aggregator_preserves_graph_resolution_id_from_snapshot(tmp_path: Path) -> None:
    graph_id = "graph-without-resolution-prefix"
    _write_json(
        tmp_path / "lane_graphs" / f"{graph_id}.json",
        {
            "id": graph_id,
            "conversation_id": "conv-snapshot",
            "resolution_id": "authoritative-resolution",
            "version": 1,
            "lanes": [{"feature_id": "lane-snapshot", "prompt": "do it"}],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-snapshot",
                    "graph_id": graph_id,
                    "status": "merged",
                }
            ]
        },
    )
    lanes_reader = LanesReader(tmp_path / "feature_lanes.json", xmuse_root=tmp_path)
    store = SelfEvolutionStore(tmp_path / "self_evolution")

    aggregation = aggregate_run_terminal(graph_id, lanes_reader=lanes_reader, store=store)
    evidence = build_evidence_bundle(
        aggregation=aggregation,
        store=store,
        xmuse_root=tmp_path,
        lanes_path=tmp_path / "feature_lanes.json",
    )

    assert aggregation.resolution_id == "authoritative-resolution"
    assert evidence.source_resolution_id == "authoritative-resolution"


def test_evidence_aggregator_keeps_unprojected_graph_lanes_open(tmp_path: Path) -> None:
    graph_id = _seed_partially_projected_graph(tmp_path)
    lanes_reader = LanesReader(tmp_path / "feature_lanes.json")

    aggregation = aggregate_run_terminal(graph_id, lanes_reader=lanes_reader)

    assert aggregation.status is RunTerminalStatus.RUNNING
    assert aggregation.terminal is False
    assert {
        (item["feature_id"], item["raw_status"], item["terminal"])
        for item in aggregation.lane_statuses
    } == {
        ("lane-a", "merged", True),
        ("lane-b", "unprojected", False),
    }


def test_controller_evidence_bundle_uses_configured_blueprint_path(tmp_path: Path) -> None:
    graph_id = _seed_graph(tmp_path)
    blueprint = tmp_path / "docs" / "custom-blueprint.md"
    _write_blueprint(blueprint)
    controller = SelfEvolutionController(xmuse_root=tmp_path, blueprint_path=blueprint)

    aggregation = controller.aggregate_run_terminal(graph_id)
    evidence = controller.build_evidence_bundle(aggregation)

    assert "docs/custom-blueprint.md" in evidence.primary_refs
    assert "docs/custom-blueprint.md" in evidence.artifact_refs
    assert "blueprint.md" not in evidence.primary_refs


def test_controller_landing_uses_configured_chat_graph_and_lanes_paths(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "xmuse-root"
    store_root = tmp_path / "runtime" / "self-evolution"
    lanes_path = tmp_path / "queue" / "feature_lanes.json"
    chat_db_path = tmp_path / "chat" / "configured-chat.db"
    blueprint = xmuse_root / "blueprint.md"
    _write_blueprint(blueprint)
    _write_json(lanes_path, {"lanes": []})
    controller = SelfEvolutionController(
        xmuse_root=xmuse_root,
        blueprint_path=blueprint,
        store_root=store_root,
        lanes_path=lanes_path,
        chat_db_path=chat_db_path,
    )
    proposal = _proposal_for_landing()
    controller.store.save_proposal(proposal)
    review_decision = controller.review_proposal(proposal)
    aggregation = RunTerminalAggregation(
        aggregation_id="runagg-land",
        run_id=proposal.source_run_id,
        resolution_id="res-land",
        graph_id="source-graph",
        status=RunTerminalStatus.MERGED,
        terminal=True,
        reason="merged",
        created_at="2026-05-30T00:00:00Z",
    )
    guardrail = controller.guardrail_check(proposal, review_decision, aggregation)
    evidence = StructuredEvidenceBundle(
        bundle_id=proposal.evidence_bundle_id,
        source_run_id=proposal.source_run_id,
        source_resolution_id=aggregation.resolution_id,
        selection_policy_id="policy",
        selection_policy_version="1",
        summary="summary",
        run_terminal_status=RunTerminalStatus.MERGED,
        primary_refs=["feature_lanes.json"],
        created_at="2026-05-30T00:00:00Z",
    )

    lineage = controller.land_evolution_run(
        proposal,
        review_decision,
        guardrail,
        evidence,
    )

    assert chat_db_path.exists()
    assert len(controller._chat.list_conversations()) == 1
    assert (xmuse_root / "lane_graphs" / f"{lineage.spawned_graph_id}.json").exists()
    assert not (store_root.parent / "chat.db").exists()
    assert not (store_root.parent / "lane_graphs").exists()
    projected = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in projected] == ["landed-lane"]


def test_budget_window_class_reuses_and_consumes_window(tmp_path: Path) -> None:
    store = SelfEvolutionStore(tmp_path / "self_evolution")
    budget = BudgetWindow(store=store)

    window = budget.for_track("graph_authority")
    consumed = budget.consume(window.window_id, 2)

    assert consumed.window_id == window.window_id
    assert consumed.consumed_run_ids == ["graph_authority", "graph_authority#2"]
    assert budget.get(window.window_id).consumed_run_ids == consumed.consumed_run_ids


def test_proposal_drafter_reexports_dedup_signal_refs() -> None:
    refs = dedup_signal_refs(
        [
            "lane_signal:{\"feature_id\":\"a\",\"manual_recovery\":\"x\"}",
            "gate_report:logs/gates/a/report.json",
        ]
    )

    assert refs == ["lane_signal:{\"feature_id\":\"a\"}"]


def test_proposal_drafter_restores_empty_decomposer_fallback_lane(tmp_path: Path) -> None:
    class EmptyDecomposer:
        def decompose(self, target_track, evidence):
            return []

    graph_id = _seed_graph(tmp_path)
    blueprint = tmp_path / "blueprint.md"
    _write_blueprint(blueprint)
    controller = SelfEvolutionController(
        xmuse_root=tmp_path,
        blueprint_path=blueprint,
        decomposer=EmptyDecomposer(),
    )
    aggregation = controller.aggregate_run_terminal(graph_id)
    evidence = controller.build_evidence_bundle(aggregation)

    proposal = controller.draft_evolution_proposal(evidence)

    lanes = proposal.candidate_graph["lanes"]
    assert len(lanes) == 1
    assert lanes[0]["feature_id"].startswith("self-evolution-graph_authority-")
    assert lanes[0]["prompt"]
    assert lanes[0]["gate_profiles"] == ["xmuse-core"]


def test_proposal_reviewer_module_persists_review_and_guardrail(tmp_path: Path) -> None:
    store = SelfEvolutionStore(tmp_path / "self_evolution")
    proposal = EvolutionProposal(
        proposal_id="evprop-test",
        source_run_id="run-1",
        blueprint_set_id="xmuse-self-evolution-v0",
        target_track_ids=["graph_authority"],
        status=EvolutionProposalStatus.AWAITING_REVIEW,
        draft_version=1,
        author_session_id="god-session-architect",
        scope_summary="scope",
        why_now="why",
        evidence_bundle_id="evbundle-test",
        candidate_graph={"lanes": [{"feature_id": "lane-a", "prompt": "do it"}]},
        created_at="2026-05-30T00:00:00Z",
    )
    store.save_proposal(proposal)

    decision = review(proposal, store=store)
    aggregation = RunTerminalAggregation(
        aggregation_id="runagg-test",
        run_id=proposal.source_run_id,
        resolution_id="res-test",
        graph_id="graph-test",
        status=RunTerminalStatus.MERGED,
        terminal=True,
        reason="merged",
        created_at="2026-05-30T00:00:00Z",
    )
    guardrail = guardrail_check(proposal, decision, aggregation, store=store)

    assert decision.decision is EvolutionReviewKind.APPROVE
    assert guardrail.action is EvolutionGuardrailAction.CONTINUE
    assert guardrail.terminal_aggregation_ref == aggregation.aggregation_id
    assert store.list_review_decisions()[-1].decision_id == decision.decision_id
    assert store.list_guardrail_decisions()[-1].decision_id == guardrail.decision_id
    assert store.list_proposals()[-1].status is EvolutionProposalStatus.APPROVED


def test_proposal_reviewer_guardrail_holds_without_review_and_terminal_aggregation(
    tmp_path: Path,
) -> None:
    store = SelfEvolutionStore(tmp_path / "self_evolution")
    proposal = EvolutionProposal(
        proposal_id="evprop-no-safety-inputs",
        source_run_id="run-missing",
        blueprint_set_id="xmuse-self-evolution-v0",
        target_track_ids=["graph_authority"],
        status=EvolutionProposalStatus.AWAITING_REVIEW,
        draft_version=1,
        author_session_id="god-session-architect",
        scope_summary="scope",
        why_now="why",
        evidence_bundle_id="evbundle-test",
        candidate_graph={"lanes": [{"feature_id": "lane-a", "prompt": "do it"}]},
        created_at="2026-05-30T00:00:00Z",
    )
    store.save_proposal(proposal)

    guardrail = guardrail_check(proposal, store=store)

    assert guardrail.action is EvolutionGuardrailAction.HOLD
    assert guardrail.checks["source_run_terminal"] is False
    assert guardrail.checks["review_approved"] is False
    assert "source_run_terminal" in guardrail.reason_codes
    assert "review_approved" in guardrail.reason_codes
    assert guardrail.terminal_aggregation_ref is None
    assert store.list_proposals()[-1].status is EvolutionProposalStatus.GUARDRAIL_BLOCKED


def test_clarification_resume_lanes_returns_projected_graph_lanes(tmp_path: Path) -> None:
    graph_id = _seed_graph(tmp_path)
    controller = SelfEvolutionController(
        xmuse_root=tmp_path,
        blueprint_path=tmp_path / "blueprint.md",
    )

    assert resume_lanes(graph_id, lanes_reader=controller._lanes_reader) == ["lane-decomp"]


def test_controller_public_methods_are_small_facade_delegates() -> None:
    source = inspect.getsource(SelfEvolutionController)
    tree = ast.parse(source)
    public_methods = [
        node
        for node in tree.body[0].body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]

    assert public_methods
    for method in public_methods:
        if method.name in {"store"}:
            continue
        assert len(method.body) <= 5, method.name


def test_controller_runtime_build_evidence_bundle_delegates_to_evidence_aggregator() -> None:
    from xmuse_core.self_evolution import _controller_runtime

    source = inspect.getsource(
        _controller_runtime.SelfEvolutionControllerRuntime.build_evidence_bundle
    )
    assert "evidence_aggregator.build_evidence_bundle" in source
