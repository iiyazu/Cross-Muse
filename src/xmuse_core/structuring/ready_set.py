from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from xmuse_core.namespaces import build_projection_lane_id

_READY_STATUSES = ("pending", "reworking")
_SUCCESS_STATUSES = {"done", "merged", "completed"}


def build_graph_ready_set(
    lanes: Sequence[Mapping[str, Any]],
    *,
    graph_id: str | None,
    resolution_id: str | None,
) -> list[dict[str, Any]]:
    """Build the graph-native ready set without cutting over runner dispatch."""

    lane_status_by_id = _lane_status_by_identity(lanes)
    ready: list[dict[str, Any]] = []
    for status in _READY_STATUSES:
        for lane in lanes:
            if lane.get("status") != status:
                continue
            if graph_id is not None and lane.get("graph_id") != graph_id:
                continue
            if resolution_id is not None and lane.get("resolution_id") != resolution_id:
                continue
            if not _dependencies_satisfied(lane, lane_status_by_id):
                continue
            ready.append(dict(lane))
    return ready


def build_ready_set_parity_evidence(
    *,
    legacy_candidates: Sequence[Mapping[str, Any]],
    ready_set_candidates: Sequence[Mapping[str, Any]],
    graph_id: str | None,
    resolution_id: str | None,
) -> dict[str, Any]:
    legacy_ids = [_lane_feature_id(lane) for lane in legacy_candidates]
    ready_set_ids = [_lane_feature_id(lane) for lane in ready_set_candidates]
    legacy_only = sorted(set(legacy_ids) - set(ready_set_ids))
    ready_set_only = sorted(set(ready_set_ids) - set(legacy_ids))
    return {
        "matches": legacy_ids == ready_set_ids,
        "runner_source": "legacy_projection",
        "ready_set_source": "graph_native",
        "graph_id": graph_id,
        "resolution_id": resolution_id,
        "legacy_candidate_lane_ids": legacy_ids,
        "ready_set_lane_ids": ready_set_ids,
        "legacy_only_lane_ids": legacy_only,
        "ready_set_only_lane_ids": ready_set_only,
    }


def _lane_status_by_identity(
    lanes: Sequence[Mapping[str, Any]],
) -> dict[str, str | None]:
    status_by_id: dict[str, str | None] = {}
    for lane in lanes:
        feature_id = _optional_text(lane.get("feature_id"))
        if feature_id is None:
            continue
        status_by_id[_lane_identity(lane)] = _optional_text(lane.get("status"))
    return status_by_id


def _dependencies_satisfied(
    lane: Mapping[str, Any],
    lane_status_by_id: Mapping[str, str | None],
) -> bool:
    return all(
        lane_status_by_id.get(dependency_id) in _SUCCESS_STATUSES
        for dependency_id in _lane_dependency_ids(lane)
    )


def _lane_dependency_ids(lane: Mapping[str, Any]) -> list[str]:
    scoped_dependencies = _text_list(lane.get("lane_depends_on_ids"))
    if scoped_dependencies:
        return scoped_dependencies

    dependencies = _text_list(lane.get("depends_on"))
    conversation_id = _optional_text(lane.get("conversation_id"))
    graph_id = _optional_text(lane.get("graph_id"))
    if conversation_id is None or graph_id is None:
        return dependencies
    return [
        dependency
        if dependency.startswith("lane:")
        else build_projection_lane_id(
            conversation_id=conversation_id,
            graph_id=graph_id,
            lane_local_id=dependency,
        )
        for dependency in dependencies
    ]


def _lane_identity(lane: Mapping[str, Any]) -> str:
    conversation_id = _optional_text(lane.get("conversation_id"))
    graph_id = _optional_text(lane.get("graph_id"))
    lane_local_id = _optional_text(lane.get("lane_local_id")) or _optional_text(
        lane.get("feature_id")
    )
    if (
        conversation_id is not None
        and graph_id is not None
        and lane_local_id is not None
    ):
        return build_projection_lane_id(
            conversation_id=conversation_id,
            graph_id=graph_id,
            lane_local_id=lane_local_id,
        )
    lane_id = _optional_text(lane.get("lane_id"))
    if lane_id is not None:
        return lane_id
    feature_id = _lane_feature_id(lane)
    if feature_id is None:
        raise ValueError("lane is missing feature_id")
    return feature_id


def _lane_feature_id(lane: Mapping[str, Any]) -> str:
    feature_id = _optional_text(lane.get("feature_id"))
    if feature_id is None:
        raise ValueError("lane is missing feature_id")
    return feature_id


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]
