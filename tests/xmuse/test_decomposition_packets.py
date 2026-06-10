from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.structuring.models import (
    DecompositionReviewHeuristics,
    DependencyEdgeRationale,
    FeatureDecompositionCandidatePacket,
    FeaturePlanFeature,
    LaneDecompositionCandidatePacket,
    LaneNode,
)


def test_feature_decomposition_candidate_packet_round_trips_with_edge_rationale() -> None:
    packet = FeatureDecompositionCandidatePacket(
        packet_id="feature-packet-1",
        conversation_id="conv-1",
        source_blueprint_ref="resolution:res-1:mission_blueprint",
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Define the DAG candidate schema.",
                acceptance_criteria=["Schema validates."],
                graph_id="graph-schema",
            ),
            FeaturePlanFeature(
                feature_id="review",
                title="Review packet",
                goal="Expose the review packet contract.",
                acceptance_criteria=["Review packet carries rationale."],
                dependencies=["schema"],
                graph_id="graph-review",
            ),
        ],
        dependency_edges=[
            DependencyEdgeRationale(
                source_id="schema",
                target_id="review",
                rationale="Review depends on the schema contract being stable first.",
                evidence_refs=[
                    "docs/superpowers/specs/2026-05-31-xmuse-b-class-autonomy-product-contracts-blueprint-design.md",
                ],
            )
        ],
    )

    restored = FeatureDecompositionCandidatePacket.model_validate_json(
        packet.model_dump_json()
    )

    assert restored == packet
    assert restored.dependency_edges[0].rationale.startswith("Review depends")


def test_feature_decomposition_candidate_packet_requires_rationale_for_each_dependency() -> None:
    with pytest.raises(
        ValidationError,
        match="dependency_edges must match declared dependencies",
    ):
        FeatureDecompositionCandidatePacket(
            packet_id="feature-packet-2",
            conversation_id="conv-1",
            source_blueprint_ref="resolution:res-1:mission_blueprint",
            features=[
                FeaturePlanFeature(
                    feature_id="schema",
                    title="Schema",
                    goal="Define the DAG candidate schema.",
                    acceptance_criteria=["Schema validates."],
                    graph_id="graph-schema",
                ),
                FeaturePlanFeature(
                    feature_id="review",
                    title="Review packet",
                    goal="Expose the review packet contract.",
                    acceptance_criteria=["Review packet carries rationale."],
                    dependencies=["schema"],
                    graph_id="graph-review",
                ),
            ],
            dependency_edges=[],
        )


def test_feature_decomposition_candidate_packet_rejects_dependency_cycles() -> None:
    with pytest.raises(ValidationError, match="dependency cycle detected: alpha -> beta -> alpha"):
        FeatureDecompositionCandidatePacket(
            packet_id="feature-packet-3",
            conversation_id="conv-1",
            source_blueprint_ref="resolution:res-1:mission_blueprint",
            features=[
                FeaturePlanFeature(
                    feature_id="alpha",
                    title="Alpha",
                    goal="First feature.",
                    acceptance_criteria=["Alpha is defined."],
                    dependencies=["beta"],
                    graph_id="graph-alpha",
                ),
                FeaturePlanFeature(
                    feature_id="beta",
                    title="Beta",
                    goal="Second feature.",
                    acceptance_criteria=["Beta is defined."],
                    dependencies=["alpha"],
                    graph_id="graph-beta",
                ),
            ],
            dependency_edges=[
                DependencyEdgeRationale(
                    source_id="beta",
                    target_id="alpha",
                    rationale="Alpha is intentionally blocked on beta for the test.",
                ),
                DependencyEdgeRationale(
                    source_id="alpha",
                    target_id="beta",
                    rationale="Beta is intentionally blocked on alpha for the test.",
                ),
            ],
        )


def test_feature_decomposition_candidate_packet_flags_over_serialized_graph() -> None:
    packet = FeatureDecompositionCandidatePacket(
        packet_id="feature-packet-serial",
        conversation_id="conv-1",
        source_blueprint_ref="resolution:res-1:mission_blueprint",
        features=[
            FeaturePlanFeature(
                feature_id="design",
                title="Design",
                goal="Draft the decomposition approach.",
                acceptance_criteria=["Design scope is explicit."],
                graph_id="graph-design",
            ),
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Define the DAG packet schema.",
                acceptance_criteria=["Schema exists."],
                dependencies=["design"],
                graph_id="graph-schema",
            ),
            FeaturePlanFeature(
                feature_id="validator",
                title="Validator",
                goal="Validate DAG warnings.",
                acceptance_criteria=["Warnings are deterministic."],
                dependencies=["schema"],
                graph_id="graph-validator",
            ),
            FeaturePlanFeature(
                feature_id="review",
                title="Review",
                goal="Expose the review packet.",
                acceptance_criteria=["Review packet is serialized."],
                dependencies=["validator"],
                graph_id="graph-review",
            ),
        ],
        dependency_edges=[
            DependencyEdgeRationale(
                source_id="design",
                target_id="schema",
                rationale="Schema work follows the design contract.",
            ),
            DependencyEdgeRationale(
                source_id="schema",
                target_id="validator",
                rationale="Validation waits for the schema shape.",
            ),
            DependencyEdgeRationale(
                source_id="validator",
                target_id="review",
                rationale="Review wiring depends on warning output.",
            ),
        ],
    )

    assert [warning.code for warning in packet.review_warnings] == [
        "over_serialized_graph"
    ]
    assert packet.review_warnings[0].subject_ids == [
        "design",
        "schema",
        "validator",
        "review",
    ]
    assert packet.review_warnings[0].metrics["critical_path_length"] == 4
    assert packet.review_warnings[0].metrics["max_parallel_width"] == 1


def test_lane_decomposition_candidate_packet_round_trips_with_edge_rationale() -> None:
    packet = LaneDecompositionCandidatePacket(
        packet_id="lane-packet-1",
        conversation_id="conv-1",
        source_feature_id="review",
        graph_id="graph-review",
        lanes=[
            LaneNode(
                feature_id="review-contract",
                title="Review contract",
                prompt="Define the review packet shape.",
            ),
            LaneNode(
                feature_id="edge-validator",
                title="Edge validator",
                prompt="Validate rationale edges against declared dependencies.",
                depends_on=["review-contract"],
            ),
        ],
        dependency_edges=[
            DependencyEdgeRationale(
                source_id="review-contract",
                target_id="edge-validator",
                rationale="Validation depends on the packet contract existing first.",
            )
        ],
    )

    restored = LaneDecompositionCandidatePacket.model_validate_json(
        packet.model_dump_json()
    )

    assert restored == packet
    assert restored.dependency_edges[0].target_id == "edge-validator"


def test_lane_decomposition_candidate_packet_classifies_broad_and_tiny_lanes() -> None:
    packet = LaneDecompositionCandidatePacket(
        packet_id="lane-packet-sizing",
        conversation_id="conv-1",
        source_feature_id="review",
        graph_id="graph-review",
        lanes=[
            LaneNode(
                feature_id="broad-lane",
                title="Broad lane",
                prompt=(
                    "Implement the planner validator, packet serializer, review "
                    "warning renderer, and the focused regression coverage for "
                    "the decomposition review flow."
                ),
                acceptance_criteria=[
                    "Validator computes warnings.",
                    "Warnings serialize in packets.",
                    "Review packet preserves warning codes.",
                    "Focused regression tests cover classification.",
                ],
            ),
            LaneNode(
                feature_id="tiny-lane",
                title="Tiny lane",
                prompt="Rename one flag.",
            ),
        ],
        dependency_edges=[],
    )

    warnings_by_code = {warning.code: warning for warning in packet.review_warnings}

    assert warnings_by_code["lane_too_broad"].subject_ids == ["broad-lane"]
    assert warnings_by_code["lane_too_broad"].metrics["acceptance_criteria_count"] == 4
    assert warnings_by_code["lane_too_tiny"].subject_ids == ["tiny-lane"]
    assert warnings_by_code["lane_too_tiny"].metrics["prompt_word_count"] == 3


def test_lane_decomposition_candidate_packet_respects_custom_warning_thresholds() -> None:
    packet = LaneDecompositionCandidatePacket(
        packet_id="lane-packet-custom-thresholds",
        conversation_id="conv-1",
        source_feature_id="review",
        graph_id="graph-review",
        review_heuristics=DecompositionReviewHeuristics(
            broad_lane_min_prompt_words=100,
            broad_lane_min_acceptance_criteria=10,
            tiny_lane_max_prompt_words=2,
            tiny_lane_max_acceptance_criteria=0,
        ),
        lanes=[
            LaneNode(
                feature_id="right-sized",
                title="Right sized lane",
                prompt="Rename one flag.",
                acceptance_criteria=["Update the validator name."],
            ),
        ],
        dependency_edges=[],
    )

    assert packet.review_warnings == []


def test_lane_decomposition_candidate_packet_rejects_unknown_edge_targets() -> None:
    with pytest.raises(
        ValidationError,
        match="dependency_edges reference unknown node ids: missing-lane",
    ):
        LaneDecompositionCandidatePacket(
            packet_id="lane-packet-2",
            conversation_id="conv-1",
            source_feature_id="review",
            graph_id="graph-review",
            lanes=[
                LaneNode(
                    feature_id="review-contract",
                    title="Review contract",
                    prompt="Define the review packet shape.",
                ),
            ],
            dependency_edges=[
                DependencyEdgeRationale(
                    source_id="review-contract",
                    target_id="missing-lane",
                    rationale="This should fail because the target lane is unknown.",
                )
            ],
        )


def test_lane_decomposition_candidate_packet_rejects_dependency_cycles() -> None:
    with pytest.raises(
        ValidationError,
        match="dependency cycle detected: lane-a -> lane-b -> lane-a",
    ):
        LaneDecompositionCandidatePacket(
            packet_id="lane-packet-3",
            conversation_id="conv-1",
            source_feature_id="review",
            graph_id="graph-review",
            lanes=[
                LaneNode(
                    feature_id="lane-a",
                    title="Lane A",
                    prompt="Implement lane A.",
                    depends_on=["lane-b"],
                ),
                LaneNode(
                    feature_id="lane-b",
                    title="Lane B",
                    prompt="Implement lane B.",
                    depends_on=["lane-a"],
                ),
            ],
            dependency_edges=[
                DependencyEdgeRationale(
                    source_id="lane-b",
                    target_id="lane-a",
                    rationale="Lane A waits on lane B in this cycle test.",
                ),
                DependencyEdgeRationale(
                    source_id="lane-a",
                    target_id="lane-b",
                    rationale="Lane B waits on lane A in this cycle test.",
                ),
            ],
        )
