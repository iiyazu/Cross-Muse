from __future__ import annotations

from collections import defaultdict

from xmuse_core.structuring.models import (
    DecompositionReviewHeuristics,
    DecompositionReviewWarning,
    FeatureDecompositionReviewPacket,
    FeatureGraphSet,
    FeaturePlanFeature,
    FeaturePlanProposal,
    GraphSetDecompositionReviewPacket,
    LaneDecompositionReviewPacket,
    LaneNode,
)


def review_feature_decomposition(
    features: list[FeaturePlanFeature],
    *,
    heuristics: DecompositionReviewHeuristics | None = None,
) -> list[DecompositionReviewWarning]:
    active_heuristics = heuristics or DecompositionReviewHeuristics()
    return _graph_review_warnings(
        node_ids=[feature.feature_id for feature in features],
        dependencies={feature.feature_id: list(feature.dependencies) for feature in features},
        heuristics=active_heuristics,
    )


def review_lane_decomposition(
    lanes: list[LaneNode],
    *,
    heuristics: DecompositionReviewHeuristics | None = None,
) -> list[DecompositionReviewWarning]:
    active_heuristics = heuristics or DecompositionReviewHeuristics()
    warnings = _graph_review_warnings(
        node_ids=[lane.feature_id for lane in lanes],
        dependencies={lane.feature_id: list(lane.depends_on) for lane in lanes},
        heuristics=active_heuristics,
    )
    warnings.extend(_lane_size_review_warnings(lanes, heuristics=active_heuristics))
    return warnings


def build_graph_set_decomposition_review(
    proposal: FeaturePlanProposal,
    graph_set: FeatureGraphSet,
) -> GraphSetDecompositionReviewPacket:
    source_blueprint_ref = proposal.source_blueprint.blueprint_ref
    supporting_refs = _dedupe_refs(
        [
            source_blueprint_ref,
            *proposal.source_blueprint.references,
            *(
                ref
                for feature in proposal.features
                for ref in feature.blueprint_refs
            ),
        ]
    )
    feature_packet = FeatureDecompositionReviewPacket(
        packet_id=f"{proposal.id}:feature-review",
        source_blueprint_ref=source_blueprint_ref,
        feature_ids=[feature.feature_id for feature in proposal.features],
        dependency_edges=_feature_dependency_edges(
            proposal.features,
            default_evidence_ref=source_blueprint_ref,
        ),
        review_warnings=review_feature_decomposition(proposal.features),
        blueprint_refs=_dedupe_refs(
            [source_blueprint_ref, *proposal.source_blueprint.references]
        ),
    )
    graph_by_id = {graph.id: graph for graph in graph_set.graphs}
    lane_packets = [
        LaneDecompositionReviewPacket(
            packet_id=f"{proposal.id}:{feature.graph_id}:lane-review",
            graph_id=feature.graph_id,
            source_feature_id=feature.feature_id,
            lane_ids=[lane.feature_id for lane in graph_by_id[feature.graph_id].lanes],
            dependency_edges=_lane_dependency_edges(
                graph_by_id[feature.graph_id].lanes,
                default_evidence_refs=feature.blueprint_refs or [source_blueprint_ref],
            ),
            review_warnings=review_lane_decomposition(graph_by_id[feature.graph_id].lanes),
            blueprint_refs=_dedupe_refs(feature.blueprint_refs or [source_blueprint_ref]),
        )
        for feature in proposal.features
    ]
    return GraphSetDecompositionReviewPacket(
        packet_id=f"{proposal.id}:graph-set-review",
        source_blueprint_ref=source_blueprint_ref,
        supporting_refs=supporting_refs,
        feature_packet=feature_packet,
        lane_packets=lane_packets,
    )


def _graph_review_warnings(
    *,
    node_ids: list[str],
    dependencies: dict[str, list[str]],
    heuristics: DecompositionReviewHeuristics,
) -> list[DecompositionReviewWarning]:
    if len(node_ids) < heuristics.over_serialized_min_node_count:
        return []

    groups = _compute_concurrency_groups(node_ids, dependencies)
    if not groups:
        return []

    critical_path_length = _compute_critical_path_length(node_ids, dependencies)
    critical_path_ratio = critical_path_length / len(node_ids)
    max_parallel_width = max(len(group) for group in groups)

    if (
        critical_path_ratio < heuristics.over_serialized_min_critical_path_ratio
        or max_parallel_width > heuristics.over_serialized_max_parallel_width
    ):
        return []

    return [
        DecompositionReviewWarning(
            code="over_serialized_graph",
            message=(
                "Graph is effectively serialized under the current heuristic; "
                "re-check whether any work can be split into parallel root or sibling lanes."
            ),
            subject_ids=list(node_ids),
            metrics={
                "node_count": len(node_ids),
                "critical_path_length": critical_path_length,
                "critical_path_ratio": round(critical_path_ratio, 3),
                "max_parallel_width": max_parallel_width,
                "concurrency_group_count": len(groups),
            },
        )
    ]


def _lane_size_review_warnings(
    lanes: list[LaneNode],
    *,
    heuristics: DecompositionReviewHeuristics,
) -> list[DecompositionReviewWarning]:
    warnings: list[DecompositionReviewWarning] = []
    for lane in lanes:
        prompt_word_count = _word_count(lane.prompt)
        acceptance_criteria_count = len(lane.acceptance_criteria)

        if (
            prompt_word_count >= heuristics.broad_lane_min_prompt_words
            or acceptance_criteria_count
            >= heuristics.broad_lane_min_acceptance_criteria
        ):
            warnings.append(
                DecompositionReviewWarning(
                    code="lane_too_broad",
                    message=(
                        f"Lane {lane.feature_id} looks too broad for a bounded worker "
                        "under the current heuristic."
                    ),
                    subject_ids=[lane.feature_id],
                    metrics={
                        "prompt_word_count": prompt_word_count,
                        "acceptance_criteria_count": acceptance_criteria_count,
                    },
                )
            )
            continue

        if (
            prompt_word_count <= heuristics.tiny_lane_max_prompt_words
            and acceptance_criteria_count
            <= heuristics.tiny_lane_max_acceptance_criteria
        ):
            warnings.append(
                DecompositionReviewWarning(
                    code="lane_too_tiny",
                    message=(
                        f"Lane {lane.feature_id} looks too small and may belong with a "
                        "neighboring lane under the current heuristic."
                    ),
                    subject_ids=[lane.feature_id],
                    metrics={
                        "prompt_word_count": prompt_word_count,
                        "acceptance_criteria_count": acceptance_criteria_count,
                    },
                )
            )
    return warnings


def _compute_concurrency_groups(
    node_ids: list[str],
    dependencies: dict[str, list[str]],
) -> list[list[str]]:
    in_degree = {node_id: 0 for node_id in node_ids}
    adjacency: dict[str, list[str]] = defaultdict(list)
    for node_id in node_ids:
        for dependency in dependencies.get(node_id, []):
            if dependency in in_degree:
                in_degree[node_id] += 1
                adjacency[dependency].append(node_id)

    groups: list[list[str]] = []
    ready = sorted(node_id for node_id, degree in in_degree.items() if degree == 0)
    while ready:
        groups.append(ready)
        next_ready: list[str] = []
        for node_id in ready:
            for dependent in adjacency[node_id]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_ready.append(dependent)
        ready = sorted(next_ready)
    return groups


def _compute_critical_path_length(
    node_ids: list[str],
    dependencies: dict[str, list[str]],
) -> int:
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree = {node_id: 0 for node_id in node_ids}
    distances = {node_id: 1 for node_id in node_ids}

    for node_id in node_ids:
        for dependency in dependencies.get(node_id, []):
            if dependency in in_degree:
                adjacency[dependency].append(node_id)
                in_degree[node_id] += 1

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    order: list[str] = []
    while queue:
        node_id = queue.pop(0)
        order.append(node_id)
        for dependent in adjacency[node_id]:
            distances[dependent] = max(distances[dependent], distances[node_id] + 1)
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    return max((distances[node_id] for node_id in order), default=0)


def _word_count(text: str) -> int:
    return len([part for part in text.split() if part.strip()])


def _feature_dependency_edges(
    features: list[FeaturePlanFeature],
    *,
    default_evidence_ref: str,
):
    return [
        _dependency_edge(
            source_id=dependency,
            target_id=feature.feature_id,
            rationale=(
                f"Feature {feature.feature_id} depends on {dependency} because "
                "it declares that dependency."
            ),
            evidence_refs=feature.blueprint_refs or [default_evidence_ref],
        )
        for feature in features
        for dependency in feature.dependencies
    ]


def _lane_dependency_edges(
    lanes: list[LaneNode],
    *,
    default_evidence_refs: list[str],
):
    return [
        _dependency_edge(
            source_id=dependency,
            target_id=lane.feature_id,
            rationale=(
                f"Lane {lane.feature_id} depends on {dependency} because it "
                "declares that dependency."
            ),
            evidence_refs=default_evidence_refs,
        )
        for lane in lanes
        for dependency in lane.depends_on
    ]


def _dependency_edge(
    *,
    source_id: str,
    target_id: str,
    rationale: str,
    evidence_refs: list[str],
):
    from xmuse_core.structuring.models import DependencyEdgeRationale

    return DependencyEdgeRationale(
        source_id=source_id,
        target_id=target_id,
        rationale=rationale,
        evidence_refs=_dedupe_refs(evidence_refs),
    )


def _dedupe_refs(refs: list[str]) -> list[str]:
    ordered: list[str] = []
    for ref in refs:
        if ref and ref not in ordered:
            ordered.append(ref)
    return ordered
