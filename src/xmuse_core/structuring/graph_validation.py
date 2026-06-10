from __future__ import annotations

from typing import Any


def duplicates(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def duplicate_edge_labels(edges: list[tuple[str, str]]) -> list[str]:
    seen: set[tuple[str, str]] = set()
    duplicate_labels: set[str] = set()
    for edge in edges:
        if edge in seen:
            duplicate_labels.add(f"{edge[0]} -> {edge[1]}")
        seen.add(edge)
    return sorted(duplicate_labels)


def validate_lane_collection(lanes: list[Any]) -> None:
    lane_ids = [lane.feature_id for lane in lanes]
    duplicate_ids = duplicates(lane_ids)
    if duplicate_ids:
        raise ValueError(f"duplicate lane id: {', '.join(duplicate_ids)}")

    known_lane_ids = set(lane_ids)
    validate_acyclic_dependencies(
        known_ids=known_lane_ids,
        expected_edges={
            (dependency, lane.feature_id)
            for lane in lanes
            for dependency in lane.depends_on
            if dependency in known_lane_ids
        },
    )


def validate_dependency_edges(
    edges: list[Any],
    *,
    known_ids: set[str],
    expected_edges: set[tuple[str, str]],
) -> None:
    actual_edges = [(edge.source_id, edge.target_id) for edge in edges]
    duplicate_edges = duplicate_edge_labels(actual_edges)
    if duplicate_edges:
        raise ValueError(f"duplicate dependency_edges: {', '.join(duplicate_edges)}")

    unknown_ids = sorted(
        {
            node_id
            for source_id, target_id in actual_edges
            for node_id in (source_id, target_id)
            if node_id not in known_ids
        }
    )
    if unknown_ids:
        raise ValueError(
            "dependency_edges reference unknown node ids: " + ", ".join(unknown_ids)
        )

    actual_edge_set = set(actual_edges)
    missing = sorted(expected_edges - actual_edge_set)
    extra = sorted(actual_edge_set - expected_edges)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(
                "missing: " + ", ".join(f"{source} -> {target}" for source, target in missing)
            )
        if extra:
            details.append(
                "extra: " + ", ".join(f"{source} -> {target}" for source, target in extra)
            )
        raise ValueError(
            "dependency_edges must match declared dependencies "
            f"({'; '.join(details)})"
        )


def validate_acyclic_dependencies(
    *,
    known_ids: set[str],
    expected_edges: set[tuple[str, str]],
) -> None:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in known_ids}
    for source_id, target_id in expected_edges:
        adjacency[source_id].append(target_id)
    for neighbors in adjacency.values():
        neighbors.sort()

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    stack_positions: dict[str, int] = {}

    def visit(node_id: str) -> None:
        visiting.add(node_id)
        stack_positions[node_id] = len(stack)
        stack.append(node_id)

        for dependent_id in adjacency[node_id]:
            if dependent_id in visited:
                continue
            if dependent_id in visiting:
                cycle_nodes = stack[stack_positions[dependent_id] :] + [dependent_id]
                raise ValueError("dependency cycle detected: " + " -> ".join(cycle_nodes))
            visit(dependent_id)

        visiting.remove(node_id)
        visited.add(node_id)
        stack.pop()
        stack_positions.pop(node_id, None)

    for node_id in sorted(known_ids):
        if node_id not in visited:
            visit(node_id)
