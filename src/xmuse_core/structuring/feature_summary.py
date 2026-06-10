from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.structuring.models import FeatureGraphSet, FeaturePlanFeature, LaneGraph

FeatureSummaryGroup = str

_GROUPS: tuple[FeatureSummaryGroup, ...] = (
    "planned",
    "ready",
    "active",
    "terminal",
    "blocked",
    "unsafe",
)
_UNSAFE_STATUSES = {
    "failed",
    "exec_failed",
    "gate_failed",
    "rejected",
    "reworking",
}
_TAKEOVER_EVIDENCE_FIELDS = {
    "takeover_decision_id",
    "takeover_evidence_ref",
    "takeover_evidence_refs",
}
_MERGED_STATUSES = {"merged", "done", "completed"}
_BLOCKED_STATUSES = {"blocked", "blocked_for_input"}


@dataclass(frozen=True)
class FeatureSummary:
    groups: dict[FeatureSummaryGroup, list[str]]
    counts: dict[FeatureSummaryGroup, int]
    graph_statuses: dict[str, str] = field(default_factory=dict)


def summarize_feature_graph_set(
    graph_set: FeatureGraphSet,
    *,
    terminal_success_feature_ids: set[str] | frozenset[str],
    live_lanes: list[dict[str, Any]] | None = None,
    live_lanes_path: Path | str | None = None,
) -> FeatureSummary:
    """Summarize feature-level progress from graph authority plus live observations.

    ``terminal_success_feature_ids`` is the authoritative completion input.
    Live lane records are only observations for active/unsafe state and are
    never used to declare feature-level terminal success.
    """

    observed_lanes = _resolve_live_lanes(
        live_lanes=live_lanes,
        live_lanes_path=live_lanes_path,
    )
    lanes_by_id = _lanes_by_id(observed_lanes)
    lanes_by_graph_local_id = _lanes_by_graph_local_id(observed_lanes)
    graphs_by_id = {graph.id: graph for graph in graph_set.graphs}
    terminal_success = set(terminal_success_feature_ids)
    groups: dict[FeatureSummaryGroup, list[str]] = {name: [] for name in _GROUPS}
    graph_statuses = {
        feature.feature_id: _feature_graph_status(
            graphs_by_id[feature.graph_id],
            lanes_by_id=lanes_by_id,
            lanes_by_graph_local_id=lanes_by_graph_local_id,
            terminal_success=feature.feature_id in terminal_success,
        )
        for feature in graph_set.feature_plan.features
    }

    unsafe_feature_ids = {
        feature.feature_id
        for feature in graph_set.feature_plan.features
        if feature.feature_id not in terminal_success
        if graph_statuses[feature.feature_id] == "failed"
    }

    for feature in graph_set.feature_plan.features:
        group = _feature_group(
            feature,
            graph=graphs_by_id[feature.graph_id],
            lanes_by_id=lanes_by_id,
            lanes_by_graph_local_id=lanes_by_graph_local_id,
            terminal_success_feature_ids=terminal_success,
            unsafe_feature_ids=unsafe_feature_ids,
            graph_statuses=graph_statuses,
        )
        groups[group].append(feature.feature_id)
        if group == "blocked":
            graph_statuses[feature.feature_id] = "blocked"

    return FeatureSummary(
        groups=groups,
        counts={name: len(feature_ids) for name, feature_ids in groups.items()},
        graph_statuses=graph_statuses,
    )


def _feature_group(
    feature: FeaturePlanFeature,
    *,
    graph: LaneGraph,
    lanes_by_id: dict[str, dict[str, Any]],
    lanes_by_graph_local_id: dict[tuple[str | None, str, str], dict[str, Any]],
    terminal_success_feature_ids: set[str],
    unsafe_feature_ids: set[str],
    graph_statuses: dict[str, str],
) -> FeatureSummaryGroup:
    graph_status = graph_statuses[feature.feature_id]
    if feature.feature_id in unsafe_feature_ids:
        return "unsafe"
    if feature.feature_id in terminal_success_feature_ids:
        return "terminal"
    if graph_status == "merged":
        return "terminal"
    if any(dependency in unsafe_feature_ids for dependency in feature.dependencies):
        return "blocked"
    if graph_status == "blocked":
        return "blocked"
    terminal_feature_ids = terminal_success_feature_ids | {
        feature_id for feature_id, status in graph_statuses.items() if status == "merged"
    }
    if not set(feature.dependencies).issubset(terminal_feature_ids):
        return "planned"
    if graph_status == "in_progress":
        return "active"
    if _feature_has_observed_lane(graph, lanes_by_id, lanes_by_graph_local_id):
        return "active"
    return "ready"


def _feature_graph_status(
    graph: LaneGraph,
    *,
    lanes_by_id: dict[str, dict[str, Any]],
    lanes_by_graph_local_id: dict[tuple[str | None, str, str], dict[str, Any]],
    terminal_success: bool,
) -> str:
    if terminal_success:
        return "merged"

    graph_lanes = [
        _graph_lane(
            node.feature_id,
            graph,
            lanes_by_id,
            lanes_by_graph_local_id,
        )
        for node in graph.lanes
    ]
    observed_graph_lanes = [lane for lane in graph_lanes if lane is not None]
    if any(
        _lane_is_failed_or_rework(lane) and not _has_release_safety_evidence(lane)
        for lane in observed_graph_lanes
    ):
        return "failed"
    if any(_lane_is_blocked(lane) for lane in observed_graph_lanes):
        return "blocked"
    if graph_lanes and all(lane is not None and _lane_is_merged(lane) for lane in graph_lanes):
        return "merged"
    if observed_graph_lanes:
        return "in_progress"
    return "planned"


def _graph_lane(
    lane_id: str,
    graph: LaneGraph,
    lanes_by_id: dict[str, dict[str, Any]],
    lanes_by_graph_local_id: dict[tuple[str | None, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    scoped_lane_id = build_projection_lane_id(
        conversation_id=graph.conversation_id,
        graph_id=graph.id,
        lane_local_id=lane_id,
    )
    lane = lanes_by_id.get(scoped_lane_id)
    if lane is not None:
        return lane
    lane = lanes_by_graph_local_id.get((graph.conversation_id, graph.id, lane_id))
    if lane is not None:
        return lane
    lane = lanes_by_id.get(lane_id)
    if lane is not None:
        lane_graph_id = lane.get("graph_id")
        lane_conversation_id = lane.get("conversation_id")
        if (lane_graph_id is None or lane_graph_id == graph.id) and (
            lane_conversation_id is None or lane_conversation_id == graph.conversation_id
        ):
            return lane
    return lanes_by_graph_local_id.get((None, graph.id, lane_id))


def _feature_has_unsafe_lane(
    graph: LaneGraph,
    lanes_by_id: dict[str, dict[str, Any]],
    lanes_by_graph_local_id: dict[tuple[str | None, str, str], dict[str, Any]],
) -> bool:
    for node in graph.lanes:
        lane = _graph_lane(
            node.feature_id,
            graph,
            lanes_by_id,
            lanes_by_graph_local_id,
        )
        if lane is None:
            continue
        if _lane_is_failed_or_rework(lane) and not _has_release_safety_evidence(lane):
            return True
    return False


def _feature_has_observed_lane(
    graph: LaneGraph,
    lanes_by_id: dict[str, dict[str, Any]],
    lanes_by_graph_local_id: dict[tuple[str | None, str, str], dict[str, Any]],
) -> bool:
    return any(
        _graph_lane(
            node.feature_id,
            graph,
            lanes_by_id,
            lanes_by_graph_local_id,
        )
        is not None
        for node in graph.lanes
    )


def _lane_is_failed_or_rework(lane: dict[str, Any]) -> bool:
    status = lane.get("status")
    if status in _UNSAFE_STATUSES:
        return True
    return lane.get("review_decision") == "rework"


def _lane_is_blocked(lane: dict[str, Any]) -> bool:
    return lane.get("status") in _BLOCKED_STATUSES


def _lane_is_merged(lane: dict[str, Any]) -> bool:
    return lane.get("status") in _MERGED_STATUSES


def _has_release_safety_evidence(lane: dict[str, Any]) -> bool:
    if any(lane.get(field) for field in _TAKEOVER_EVIDENCE_FIELDS):
        return True
    if lane.get("review_decision") == "rework":
        return False
    return bool(lane.get("review_decision") and lane.get("review_verdict_id"))


def _lanes_by_id(lanes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        feature_id = lane.get("feature_id")
        if isinstance(feature_id, str):
            keyed[feature_id] = lane
        lane_id = lane.get("lane_id")
        if isinstance(lane_id, str):
            keyed[lane_id] = lane
    return keyed


def _lanes_by_graph_local_id(
    lanes: list[dict[str, Any]],
) -> dict[tuple[str | None, str, str], dict[str, Any]]:
    keyed: dict[tuple[str | None, str, str], dict[str, Any]] = {}
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        graph_id = lane.get("graph_id")
        if not isinstance(graph_id, str) or not graph_id:
            continue
        local_lane_id = lane.get("lane_local_id")
        if not isinstance(local_lane_id, str) or not local_lane_id:
            feature_id = lane.get("feature_id")
            if not isinstance(feature_id, str) or not feature_id:
                continue
            local_lane_id = feature_id
        conversation_id = lane.get("conversation_id")
        scoped_conversation_id = (
            str(conversation_id)
            if isinstance(conversation_id, str) and conversation_id
            else None
        )
        keyed[(scoped_conversation_id, graph_id, local_lane_id)] = lane
    return keyed


def _resolve_live_lanes(
    *,
    live_lanes: list[dict[str, Any]] | None,
    live_lanes_path: Path | str | None,
) -> list[dict[str, Any]]:
    if live_lanes is not None:
        return list(live_lanes)
    if live_lanes_path is None:
        return []

    path = Path(live_lanes_path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    lanes = data.get("lanes", [])
    if not isinstance(lanes, list):
        return []
    return [lane for lane in lanes if isinstance(lane, dict)]
