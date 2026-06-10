from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.platform.projection.syncer import (
    LaneProjectionSyncer,
    ProjectionWriteSkipped,
    sanitize_projection_lane,
)
from xmuse_core.platform.state_machine import stage0_projection_syncer
from xmuse_core.structuring.models import FeatureGraphSet, FeaturePlanFeature, LaneGraph, LaneNode

_COMPLETED_STATUSES = {"merged", "done", "completed"}
FEATURE_LANE_FIELD_CLASSIFICATIONS: dict[str, str] = {
    "feature_id": "projection",
    "task_type": "projection",
    "status": "legacy",
    "prompt_summary": "projection",
    "prompt_ref": "projection",
    "capabilities": "projection",
    "priority": "projection",
    "depends_on": "projection",
    "conversation_id": "projection",
    "resolution_id": "projection",
    "graph_id": "projection",
    "graph_version": "projection",
    "gate_profile": "projection",
    "gate_profiles": "projection",
    "source_lane_id": "projection",
    "feature_group": "projection",
    "graph_set_id": "projection",
    "graph_set_version": "projection",
    "feature_plan_id": "projection",
    "feature_plan_version": "projection",
    "lane_id": "projection",
    "lane_local_id": "projection",
    "lane_depends_on_ids": "projection",
    "projection_source": "projection",
    "projection_revision": "projection",
    "plan_feature_id": "projection",
    "feature_plan_feature_id": "projection",
    "acceptance_criteria": "projection",
    "blueprint_refs": "projection",
    "branch": "operational",
    "worktree": "operational",
    "base_head_sha": "operational",
    "dispatch_attempt_id": "operational",
    "dispatch_status_guard": "operational",
    "dispatch_projection_revision": "operational",
    "dispatched_at": "operational",
    "runner_id": "operational",
    "god": "operational",
    "god_runtime": "operational",
    "worker_pid": "operational",
    "worker_started_at": "operational",
    "worker_heartbeat_at": "operational",
    "worker_worktree": "operational",
    "review_runner_id": "operational",
    "review_attempt_id": "operational",
    "review_task_id": "operational",
    "memory_refs": "operational",
}


def project_ready_lanes(
    graph: LaneGraph,
    lanes_path: Path | str,
    *,
    operational_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    path = Path(lanes_path)
    projected: list[dict[str, Any]] = []

    def mutate(data: dict[str, Any]) -> None:
        existing = _existing_lanes(data)
        existing_ids = {str(lane["feature_id"]) for lane in existing}
        _validate_graph_dependencies(graph, external_lane_ids=existing_ids)
        completed_ids = _completed_lane_ids(existing)

        for node in graph.lanes:
            if node.feature_id in existing_ids:
                continue
            if not _is_dependency_ready(node, completed_ids):
                continue
            payload = sanitize_projection_lane(
                {
                    **_lane_payload(graph, node),
                    **(operational_metadata or {}),
                },
                projection_root=path.parent,
            )
            existing.append(payload)
            existing_ids.add(node.feature_id)
            projected.append(payload)

        if not projected:
            raise ProjectionWriteSkipped()
        data["lanes"] = existing

    result = _stage0_projection_syncer(path).update(mutate)
    return _with_projection_revision(projected, result.projection_revision)


def project_feature_graph_set_ready_lanes(
    graph_set: FeatureGraphSet,
    lanes_path: Path | str,
    *,
    terminal_success_feature_ids: set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    """Project ready lanes from eligible feature graphs into the flat queue."""

    _validate_feature_graph_set_projection(graph_set)
    features_by_graph_id = {
        feature.graph_id: feature for feature in graph_set.feature_plan.features
    }
    path = Path(lanes_path)
    projected: list[dict[str, Any]] = []

    def mutate(data: dict[str, Any]) -> None:
        existing = _existing_lanes(data)
        existing_ids = _existing_feature_graph_lane_ids(existing)
        completed_ids = _completed_feature_graph_lane_ids(existing)

        projected.extend(
            _feature_graph_set_projection_payloads(
                graph_set,
                projection_root=path.parent,
                existing_ids=existing_ids,
                completed_ids=completed_ids,
                terminal_success_feature_ids=set(terminal_success_feature_ids),
                features_by_graph_id=features_by_graph_id,
            )
        )
        if not projected:
            raise ProjectionWriteSkipped()
        data["lanes"] = [*existing, *projected]

    result = _stage0_projection_syncer(path).update(mutate)
    return _with_projection_revision(projected, result.projection_revision)


def _stage0_projection_syncer(path: Path) -> LaneProjectionSyncer:
    return stage0_projection_syncer(path)


def _with_projection_revision(
    lanes: list[dict[str, Any]],
    projection_revision: int,
) -> list[dict[str, Any]]:
    return [{**lane, "projection_revision": projection_revision} for lane in lanes]


def _feature_graph_set_projection_payloads(
    graph_set: FeatureGraphSet,
    *,
    projection_root: Path,
    existing_ids: set[str],
    completed_ids: set[str],
    terminal_success_feature_ids: set[str],
    features_by_graph_id: dict[str, FeaturePlanFeature],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    projected_ids: set[str] = set()

    for graph in graph_set.graphs:
        feature = features_by_graph_id[graph.id]
        if feature.feature_id in terminal_success_feature_ids:
            continue
        if not set(feature.dependencies).issubset(terminal_success_feature_ids):
            continue

        for node in graph.lanes:
            lane_id = _feature_graph_lane_id(
                conversation_id=graph.conversation_id,
                graph_id=graph.id,
                lane_local_id=node.feature_id,
            )
            if lane_id in existing_ids:
                continue
            if not _is_feature_graph_dependency_ready(graph, node, completed_ids):
                continue
            if lane_id in projected_ids:
                raise ValueError(f"duplicate projected lane id: {node.feature_id}")

            projected_ids.add(lane_id)
            projected.append(
                sanitize_projection_lane(
                    _lane_payload(
                        graph,
                        node,
                        graph_set_id=graph_set.id,
                        graph_set_version=graph_set.feature_plan.version,
                        feature_plan_id=graph_set.feature_plan.id,
                        feature_plan_version=graph_set.feature_plan.version,
                        plan_feature_id=feature.feature_id,
                        acceptance_criteria=(
                            node.acceptance_criteria or feature.acceptance_criteria
                        ),
                        projection_source="graph_set",
                    ),
                    projection_root=projection_root,
                )
            )
    return projected


def _validate_feature_graph_set_projection(graph_set: FeatureGraphSet) -> None:
    feature_ids = {feature.feature_id for feature in graph_set.feature_plan.features}
    for feature in graph_set.feature_plan.features:
        missing_feature_dependencies = [
            dependency for dependency in feature.dependencies if dependency not in feature_ids
        ]
        if missing_feature_dependencies:
            missing = ", ".join(sorted(missing_feature_dependencies))
            raise ValueError(f"unknown feature dependency: {missing}")

    for graph in graph_set.graphs:
        _validate_graph_dependencies(graph)


def _validate_graph_dependencies(
    graph: LaneGraph,
    *,
    external_lane_ids: set[str] | None = None,
) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for node in graph.lanes:
        if node.feature_id in seen:
            duplicates.add(node.feature_id)
        seen.add(node.feature_id)
    if duplicates:
        duplicate = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate lane id: {duplicate}")
    known_lane_ids = {node.feature_id for node in graph.lanes}
    allowed_external_ids = external_lane_ids or set()
    for node in graph.lanes:
        for dependency in node.depends_on:
            if dependency not in known_lane_ids and dependency not in allowed_external_ids:
                raise ValueError(f"unknown lane dependency: {dependency}")


def _existing_lanes(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        lane
        for lane in data.get("lanes", [])
        if isinstance(lane, dict) and isinstance(lane.get("feature_id"), str)
    ]


def _completed_lane_ids(existing: list[dict[str, Any]]) -> set[str]:
    return {
        str(lane["feature_id"])
        for lane in existing
        if lane.get("status") in _COMPLETED_STATUSES
    }


def _existing_feature_graph_lane_ids(existing: list[dict[str, Any]]) -> set[str]:
    return {_existing_feature_graph_lane_id(lane) for lane in existing}


def _completed_feature_graph_lane_ids(existing: list[dict[str, Any]]) -> set[str]:
    return {
        _existing_feature_graph_lane_id(lane)
        for lane in existing
        if lane.get("status") in _COMPLETED_STATUSES
    }


def _is_dependency_ready(node: LaneNode, completed_ids: set[str]) -> bool:
    return all(dep in completed_ids for dep in node.depends_on)


def _is_feature_graph_dependency_ready(
    graph: LaneGraph,
    node: LaneNode,
    completed_ids: set[str],
) -> bool:
    return all(
        _feature_graph_lane_id(
            conversation_id=graph.conversation_id,
            graph_id=graph.id,
            lane_local_id=dependency,
        )
        in completed_ids
        for dependency in node.depends_on
    )


def _existing_feature_graph_lane_id(lane: dict[str, Any]) -> str:
    graph_id = lane.get("graph_id")
    lane_local_id = lane.get("lane_local_id")
    # Prefer scoped identity reconstructed from lineage fields so legacy rows with
    # unscoped lane_id values do not collapse graph-native projection uniqueness.
    if (
        isinstance(graph_id, str)
        and graph_id
        and isinstance(lane_local_id, str)
        and lane_local_id
    ):
        return _feature_graph_lane_id(
            conversation_id=str(lane.get("conversation_id") or ""),
            graph_id=graph_id,
            lane_local_id=lane_local_id,
        )
    if isinstance(lane.get("lane_id"), str):
        return str(lane["lane_id"])
    if (
        isinstance(lane.get("feature_id"), str)
        and str(lane["feature_id"]).startswith("lane:")
    ):
        return str(lane["feature_id"])
    return _feature_graph_lane_id(
        conversation_id=str(lane.get("conversation_id") or ""),
        graph_id=str(lane.get("graph_id") or ""),
        lane_local_id=str(lane["feature_id"]),
    )


def _feature_graph_lane_id(
    *,
    conversation_id: str,
    graph_id: str,
    lane_local_id: str,
) -> str:
    return build_projection_lane_id(
        conversation_id=conversation_id,
        graph_id=graph_id,
        lane_local_id=lane_local_id,
    )


def _lane_payload(
    graph: LaneGraph,
    node: LaneNode,
    *,
    graph_set_id: str | None = None,
    graph_set_version: int | None = None,
    feature_plan_id: str | None = None,
    feature_plan_version: int | None = None,
    plan_feature_id: str | None = None,
    acceptance_criteria: list[str] | None = None,
    projection_source: str | None = None,
) -> dict[str, Any]:
    scoped_lane_id = _feature_graph_lane_id(
        conversation_id=graph.conversation_id,
        graph_id=graph.id,
        lane_local_id=node.feature_id,
    )
    scoped_depends_on = [
        _feature_graph_lane_id(
            conversation_id=graph.conversation_id,
            graph_id=graph.id,
            lane_local_id=dependency,
        )
        for dependency in node.depends_on
    ]
    payload: dict[str, Any] = {
        "feature_id": node.feature_id,
        "task_type": node.task_type,
        "status": "pending",
        "prompt": node.prompt,
        "capabilities": list(node.capabilities),
        "priority": node.priority,
        "depends_on": list(node.depends_on),
        "conversation_id": graph.conversation_id,
        "resolution_id": graph.resolution_id,
        "graph_id": graph.id,
        "graph_version": graph.version,
        **({"gate_profile": node.gate_profile} if node.gate_profile else {}),
        **({"gate_profiles": list(node.gate_profiles)} if node.gate_profiles else {}),
        **({"source_lane_id": node.source_lane_id} if node.source_lane_id else {}),
        **({"feature_group": node.feature_group} if node.feature_group else {}),
    }
    if feature_plan_id is not None:
        payload["feature_id"] = scoped_lane_id
        payload["depends_on"] = list(scoped_depends_on)
        if graph_set_id is not None:
            payload["graph_set_id"] = graph_set_id
        if graph_set_version is not None:
            payload["graph_set_version"] = graph_set_version
        payload["feature_plan_id"] = feature_plan_id
        if feature_plan_version is not None:
            payload["feature_plan_version"] = feature_plan_version
        payload["lane_id"] = scoped_lane_id
        payload["lane_local_id"] = node.feature_id
        payload["lane_depends_on_ids"] = list(scoped_depends_on)
        if projection_source is not None:
            payload["projection_source"] = projection_source
    if plan_feature_id is not None:
        payload["plan_feature_id"] = plan_feature_id
        payload["feature_plan_feature_id"] = plan_feature_id
    criteria = acceptance_criteria if acceptance_criteria is not None else node.acceptance_criteria
    if criteria:
        payload["acceptance_criteria"] = list(criteria)
    if node.blueprint_refs:
        payload["blueprint_refs"] = list(node.blueprint_refs)
    return payload
