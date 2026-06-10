import json
from pathlib import Path

from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.structuring.feature_summary import summarize_feature_graph_set
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)


def _graph_set() -> FeatureGraphSet:
    plan = FeaturePlan(
        id="plan-b4",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=7,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add graph-set schema.",
                acceptance_criteria=["Schema validates."],
                graph_id="graph-schema",
            ),
            FeaturePlanFeature(
                feature_id="projection",
                title="Projection",
                goal="Project ready lanes.",
                acceptance_criteria=["Projection is safe."],
                dependencies=["schema"],
                graph_id="graph-projection",
            ),
            FeaturePlanFeature(
                feature_id="summary",
                title="Summary",
                goal="Summarize features.",
                acceptance_criteria=["Summary is read-only."],
                dependencies=["projection"],
                graph_id="graph-summary",
            ),
        ],
    )
    return FeatureGraphSet(
        id="graph-set-b4",
        feature_plan=plan,
        graphs=[
            LaneGraph(
                id="graph-schema",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[LaneNode(feature_id="schema-root", prompt="Implement schema.")],
            ),
            LaneGraph(
                id="graph-projection",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[
                    LaneNode(feature_id="projection-root", prompt="Implement projection."),
                    LaneNode(
                        feature_id="projection-dependent",
                        prompt="Wire dependents.",
                        depends_on=["projection-root"],
                    ),
                ],
            ),
            LaneGraph(
                id="graph-summary",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[LaneNode(feature_id="summary-root", prompt="Implement summary.")],
            ),
        ],
    )


def test_summary_groups_features_from_authoritative_completion_not_noisy_lane_status() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[
            {"feature_id": "schema-root", "status": "pending"},
            {"feature_id": "projection-root", "status": "merged"},
        ],
    )

    assert summary.groups == {
        "planned": ["summary"],
        "ready": [],
        "active": ["projection"],
        "terminal": ["schema"],
        "blocked": [],
        "unsafe": [],
    }
    assert summary.counts == {
        "planned": 1,
        "ready": 0,
        "active": 1,
        "terminal": 1,
        "blocked": 0,
        "unsafe": 0,
    }


def test_summary_reports_dependency_ready_feature_when_no_lanes_are_active() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[],
    )

    assert summary.groups["ready"] == ["projection"]
    assert summary.groups["planned"] == ["summary"]
    assert summary.groups["terminal"] == ["schema"]


def test_summary_keeps_authoritative_terminal_success_over_noisy_failed_lane() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[{"feature_id": "schema-root", "status": "failed"}],
    )

    assert summary.groups["terminal"] == ["schema"]
    assert summary.groups["unsafe"] == []
    assert summary.groups["ready"] == ["projection"]


def test_summary_treats_failed_and_rework_lanes_as_unsafe_without_safety_evidence() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[
            {
                "feature_id": "projection-root",
                "status": "failed",
                "failure_reason": "gate_failed",
            },
            {
                "feature_id": "summary-root",
                "status": "reworking",
                "review_decision": "rework",
            },
        ],
    )

    assert summary.groups["unsafe"] == ["projection", "summary"]
    assert summary.groups["blocked"] == []


def test_summary_accepts_recorded_review_or_takeover_evidence_for_release_safety() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[
            {
                "feature_id": "projection-root",
                "status": "failed",
                "review_decision": "terminate",
                "review_verdict_id": "verdict-projection-safe",
            },
            {
                "feature_id": "summary-root",
                "status": "reworking",
                "takeover_decision_id": "takeover-summary-safe",
            },
        ],
    )

    assert summary.groups["unsafe"] == []
    assert summary.groups["active"] == ["projection"]
    assert summary.groups["planned"] == ["summary"]


def test_summary_does_not_treat_failed_lane_with_merge_review_as_merged() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema", "projection"},
        live_lanes=[
            {
                "feature_id": "summary-root",
                "status": "exec_failed",
                "review_decision": "merge",
                "review_verdict_id": "verdict-summary-reviewed",
            },
        ],
    )

    assert summary.graph_statuses["summary"] == "in_progress"
    assert summary.groups["terminal"] == ["schema", "projection"]
    assert summary.groups["active"] == ["summary"]
    assert summary.groups["unsafe"] == []


def test_summary_does_not_treat_rework_verdict_as_release_safety() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[
            {
                "feature_id": "projection-root",
                "status": "rejected",
                "review_decision": "rework",
                "review_verdict_id": "verdict-projection-rework",
            },
        ],
    )

    assert summary.groups["unsafe"] == ["projection"]
    assert summary.groups["blocked"] == ["summary"]


def test_summary_blocks_features_that_depend_on_unsafe_features() -> None:
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[{"feature_id": "projection-root", "status": "failed"}],
    )

    assert summary.groups["unsafe"] == ["projection"]
    assert summary.groups["blocked"] == ["summary"]
    assert summary.groups["planned"] == []


def test_summary_ignores_same_graph_lane_from_other_conversation() -> None:
    other_lane_id = build_projection_lane_id(
        conversation_id="conv-2",
        graph_id="graph-projection",
        lane_local_id="projection-root",
    )
    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes=[
            {
                "feature_id": other_lane_id,
                "lane_id": other_lane_id,
                "lane_local_id": "projection-root",
                "conversation_id": "conv-2",
                "graph_id": "graph-projection",
                "status": "failed",
            }
        ],
    )

    assert summary.groups["unsafe"] == []
    assert summary.groups["ready"] == ["projection"]
    assert summary.groups["planned"] == ["summary"]


def test_summary_can_read_live_projection_without_mutating_it(tmp_path: Path) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    before = json.dumps(
        {"lanes": [{"feature_id": "projection-root", "status": "dispatched"}]},
        indent=2,
    ) + "\n"
    lanes_path.write_text(before, encoding="utf-8")

    summary = summarize_feature_graph_set(
        _graph_set(),
        terminal_success_feature_ids={"schema"},
        live_lanes_path=lanes_path,
    )

    assert summary.groups["active"] == ["projection"]
    assert lanes_path.read_text(encoding="utf-8") == before
