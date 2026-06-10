import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore
from xmuse_core.structuring.feature_summary import summarize_feature_graph_set
from xmuse_core.structuring.models import (
    DecompositionReviewWarning,
    FeatureDecompositionReviewPacket,
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    GraphSetDecompositionReviewPacket,
    LaneDecompositionReviewPacket,
    LaneGraph,
    LaneNode,
)


def _lane_graph(
    graph_id: str,
    feature_id: str,
    *,
    conversation_id: str = "conv-1",
    resolution_id: str = "res-1",
) -> LaneGraph:
    return LaneGraph(
        id=graph_id,
        conversation_id=conversation_id,
        resolution_id=resolution_id,
        version=1,
        lanes=[LaneNode(feature_id=f"{feature_id}-lane-1", prompt="Implement the lane.")],
    )


def _feature_graph_set(graph_set_id: str = "graph-set-1") -> FeatureGraphSet:
    plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add schemas.",
                acceptance_criteria=["Models validate."],
                graph_id="graph-schema",
            )
        ],
    )
    return FeatureGraphSet(
        id=graph_set_id,
        feature_plan=plan,
        graphs=[_lane_graph("graph-schema", "schema")],
    )


def _decomposition_review_packet() -> GraphSetDecompositionReviewPacket:
    return GraphSetDecompositionReviewPacket(
        packet_id="decomp-review-1",
        source_blueprint_ref="resolution:res-blueprint-1:mission_blueprint",
        supporting_refs=[
            "resolution:res-blueprint-1:mission_blueprint",
            "docs/superpowers/specs/2026-05-31-xmuse-b-class-autonomy-product-contracts-blueprint-design.md",
        ],
        feature_packet=FeatureDecompositionReviewPacket(
            packet_id="feature-decomp-1",
            source_blueprint_ref="resolution:res-blueprint-1:mission_blueprint",
            feature_ids=["schema"],
            dependency_edges=[],
            review_warnings=[
                DecompositionReviewWarning(
                    code="feature_warning",
                    message="Feature warning stays compact.",
                    subject_ids=["schema"],
                )
            ],
            blueprint_refs=["resolution:res-blueprint-1:mission_blueprint"],
        ),
        lane_packets=[
            LaneDecompositionReviewPacket(
                packet_id="lane-decomp-schema",
                graph_id="graph-schema",
                source_feature_id="schema",
                lane_ids=["schema-lane-1"],
                dependency_edges=[],
                review_warnings=[
                    DecompositionReviewWarning(
                        code="lane_warning",
                        message="Lane warning stays compact.",
                        subject_ids=["schema-lane-1"],
                    )
                ],
                blueprint_refs=["resolution:res-blueprint-1:mission_blueprint"],
            )
        ],
    )


def test_feature_plan_validates_ids_dependencies_and_acceptance_criteria() -> None:
    with pytest.raises(ValidationError, match="feature_id"):
        FeaturePlanFeature(
            feature_id="",
            title="Schema",
            goal="Add schemas.",
            acceptance_criteria=["Models validate."],
            graph_id="graph-schema",
        )

    with pytest.raises(ValidationError, match="acceptance_criteria"):
        FeaturePlanFeature(
            feature_id="schema",
            title="Schema",
            goal="Add schemas.",
            acceptance_criteria=[],
            graph_id="graph-schema",
        )

    with pytest.raises(ValidationError, match="dependencies"):
        FeaturePlan(
            id="plan-1",
            conversation_id="conv-1",
            resolution_id="res-1",
            version=1,
            features=[
                FeaturePlanFeature(
                    feature_id="schema",
                    title="Schema",
                    goal="Add schemas.",
                    acceptance_criteria=["Models validate."],
                    dependencies=["missing"],
                    graph_id="graph-schema",
                )
            ],
        )


def test_feature_plan_rejects_duplicate_feature_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate feature_id"):
        FeaturePlan(
            id="plan-1",
            conversation_id="conv-1",
            resolution_id="res-1",
            version=1,
            features=[
                FeaturePlanFeature(
                    feature_id="schema",
                    title="Schema",
                    goal="Add schemas.",
                    acceptance_criteria=["Models validate."],
                    graph_id="graph-schema",
                ),
                FeaturePlanFeature(
                    feature_id="schema",
                    title="Store",
                    goal="Persist graph sets.",
                    acceptance_criteria=["Store round-trips."],
                    graph_id="graph-store",
                ),
            ],
        )


def test_feature_graph_set_validates_feature_graph_ids() -> None:
    plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add schemas.",
                acceptance_criteria=["Models validate."],
                graph_id="graph-schema",
            )
        ],
    )

    with pytest.raises(ValidationError, match="graph id"):
        FeatureGraphSet(
            id="graph-set-1",
            feature_plan=plan,
            graphs=[_lane_graph("wrong-graph", "schema")],
        )


def test_feature_graph_set_rejects_graphs_from_different_conversation() -> None:
    plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add schemas.",
                acceptance_criteria=["Models validate."],
                graph_id="graph-schema",
            )
        ],
    )

    with pytest.raises(ValidationError, match="graph conversation_id must match feature plan"):
        FeatureGraphSet(
            id="graph-set-1",
            feature_plan=plan,
            graphs=[_lane_graph("graph-schema", "schema", conversation_id="other-conv")],
        )


def test_feature_graph_set_rejects_graphs_from_different_resolution() -> None:
    plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add schemas.",
                acceptance_criteria=["Models validate."],
                graph_id="graph-schema",
            )
        ],
    )

    with pytest.raises(ValidationError, match="graph resolution_id must match feature plan"):
        FeatureGraphSet(
            id="graph-set-1",
            feature_plan=plan,
            graphs=[_lane_graph("graph-schema", "schema", resolution_id="other-res")],
        )


def test_feature_graph_set_store_round_trips_without_touching_live_lane_projection(
    tmp_path: Path,
) -> None:
    live_projection_path = tmp_path / "xmuse" / "feature_lanes.json"
    live_projection_path.parent.mkdir(parents=True)
    live_projection_path.write_text(
        json.dumps({"lanes": [{"feature_id": "existing", "status": "running"}]}) + "\n",
        encoding="utf-8",
    )
    before_projection = live_projection_path.read_text(encoding="utf-8")
    store = FeatureGraphSetStore(tmp_path / "graph_sets")
    plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add schemas.",
                acceptance_criteria=["Models validate.", "Store round-trips."],
                graph_id="graph-schema",
            ),
            FeaturePlanFeature(
                feature_id="projection",
                title="Projection",
                goal="Project ready graphs.",
                acceptance_criteria=["Projection remains compatible."],
                dependencies=["schema"],
                graph_id="graph-projection",
            ),
        ],
    )
    graph_set = FeatureGraphSet(
        id="graph-set-1",
        feature_plan=plan,
        graphs=[
            _lane_graph("graph-schema", "schema"),
            _lane_graph("graph-projection", "projection"),
        ],
    )

    saved_path = store.save(graph_set)
    loaded = store.load("graph-set-1")

    assert saved_path == tmp_path / "graph_sets" / "conv-1--graph-set-1.json"
    assert loaded == graph_set
    assert live_projection_path.read_text(encoding="utf-8") == before_projection


def test_feature_graph_set_store_scopes_same_local_id_by_conversation(
    tmp_path: Path,
) -> None:
    store = FeatureGraphSetStore(tmp_path / "graph_sets")
    first = _feature_graph_set("graph-set-shared")
    second = _feature_graph_set("graph-set-shared")
    second.feature_plan.conversation_id = "conv-2"
    second.graphs[0].conversation_id = "conv-2"

    first_path = store.save(first)
    second_path = store.save(second)

    assert first_path != second_path
    assert store.load("graph-set-shared", conversation_id="conv-1") == first
    assert store.load("graph-set-shared", conversation_id="conv-2") == second
    with pytest.raises(ValueError, match="ambiguous feature graph set id"):
        store.load("graph-set-shared")


def test_feature_graph_set_store_round_trips_compact_decomposition_review_packet(
    tmp_path: Path,
) -> None:
    store = FeatureGraphSetStore(tmp_path / "graph_sets")
    graph_set = _feature_graph_set().model_copy(
        update={"decomposition_review": _decomposition_review_packet()},
        deep=True,
    )

    store.save(graph_set)
    loaded = store.load("graph-set-1")

    assert loaded.decomposition_review == graph_set.decomposition_review
    assert loaded.decomposition_review is not None
    assert loaded.decomposition_review.feature_packet.dependency_edges == []
    assert loaded.decomposition_review.supporting_refs == [
        "resolution:res-blueprint-1:mission_blueprint",
        "docs/superpowers/specs/2026-05-31-xmuse-b-class-autonomy-product-contracts-blueprint-design.md",
    ]


@pytest.mark.parametrize(
    "graph_set_id",
    [
        "../xmuse/feature_lanes",
        "/tmp/feature_lanes",
        "nested/feature_lanes",
        r"nested\feature_lanes",
    ],
)
def test_feature_graph_set_store_rejects_ids_that_escape_store_root(
    tmp_path: Path,
    graph_set_id: str,
) -> None:
    live_projection_path = tmp_path / "xmuse" / "feature_lanes.json"
    live_projection_path.parent.mkdir(parents=True)
    live_projection_path.write_text(
        json.dumps({"lanes": [{"feature_id": "existing", "status": "running"}]}) + "\n",
        encoding="utf-8",
    )
    before_projection = live_projection_path.read_text(encoding="utf-8")
    store = FeatureGraphSetStore(tmp_path / "graph_sets")
    graph_set = _feature_graph_set(graph_set_id)

    with pytest.raises(ValueError, match="unsafe feature graph set id"):
        store.save(graph_set)

    with pytest.raises(ValueError, match="unsafe feature graph set id"):
        store.load(graph_set_id)

    assert live_projection_path.read_text(encoding="utf-8") == before_projection


def test_feature_summary_derives_graph_terminal_state_from_projected_graph_lanes() -> None:
    plan = FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="merged",
                title="Merged",
                goal="Complete merged graph.",
                acceptance_criteria=["Merged graph is complete."],
                graph_id="graph-merged",
            ),
            FeaturePlanFeature(
                feature_id="progress",
                title="Progress",
                goal="Keep progress graph open.",
                acceptance_criteria=["Progress graph is in progress."],
                graph_id="graph-progress",
            ),
            FeaturePlanFeature(
                feature_id="blocked",
                title="Blocked",
                goal="Represent graph blocked for input.",
                acceptance_criteria=["Blocked graph is explicit."],
                graph_id="graph-blocked",
            ),
            FeaturePlanFeature(
                feature_id="failed",
                title="Failed",
                goal="Represent failed graph.",
                acceptance_criteria=["Failed graph is unsafe."],
                graph_id="graph-failed",
            ),
            FeaturePlanFeature(
                feature_id="dependent",
                title="Dependent",
                goal="Wait on failed graph safely.",
                acceptance_criteria=["Unsafe dependency remains explicit."],
                dependencies=["failed"],
                graph_id="graph-dependent",
            ),
        ],
    )
    graph_set = FeatureGraphSet(
        id="graph-set-1",
        feature_plan=plan,
        graphs=[
            _lane_graph("graph-merged", "merged"),
            _lane_graph("graph-progress", "progress"),
            _lane_graph("graph-blocked", "blocked"),
            _lane_graph("graph-failed", "failed"),
            _lane_graph("graph-dependent", "dependent"),
        ],
    )

    summary = summarize_feature_graph_set(
        graph_set,
        terminal_success_feature_ids=set(),
        live_lanes=[
            {"feature_id": "merged-lane-1", "status": "merged", "graph_id": "graph-merged"},
            {"feature_id": "progress-lane-1", "status": "dispatched", "graph_id": "graph-progress"},
            {
                "feature_id": "blocked-lane-1",
                "status": "blocked_for_input",
                "graph_id": "graph-blocked",
            },
            {"feature_id": "failed-lane-1", "status": "gate_failed", "graph_id": "graph-failed"},
            # Flat feature-plan records and phantom graph records are observations, not graph truth.
            {"feature_id": "progress", "status": "merged", "graph_id": "graph-progress"},
            {"feature_id": "phantom-merged", "status": "merged", "graph_id": "graph-dependent"},
        ],
    )

    assert summary.groups["terminal"] == ["merged"]
    assert summary.groups["active"] == ["progress"]
    assert summary.groups["blocked"] == ["blocked", "dependent"]
    assert summary.groups["unsafe"] == ["failed"]
    assert summary.graph_statuses == {
        "merged": "merged",
        "progress": "in_progress",
        "blocked": "blocked",
        "failed": "failed",
        "dependent": "blocked",
    }
