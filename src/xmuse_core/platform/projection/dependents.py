from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from xmuse_core.observability import (
    log_event,
    observability_context,
    timed_core_operation,
)
from xmuse_core.platform.state_normalizer import normalize_lane_state, summarize_lane_states
from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.models import FeatureGraphSet
from xmuse_core.structuring.projection import (
    project_feature_graph_set_ready_lanes,
    project_ready_lanes,
)

logger = logging.getLogger(__name__)
_COMPLETED_STATUSES = {"merged", "done", "completed"}


@runtime_checkable
class _LaneStateMachine(Protocol):
    _path: Path

    def get_lane(self, lane_id: str) -> dict[str, Any]: ...

    def update_metadata(self, lane_id: str, metadata: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AggregatedStatus:
    graph_id: str
    status: str
    terminal: bool
    reason: str
    lane_counts: dict[str, int]
    lane_statuses: list[dict[str, Any]]


async def reproject_dependents_if_needed(
    lane_id: str,
    *,
    sm: _LaneStateMachine,
    graph_store: LaneGraphStore,
) -> None:
    lane = sm.get_lane(lane_id)
    graph_id = _lane_graph_id(lane)
    with observability_context(
        lane_id=lane_id,
        graph_id=graph_id,
    ), timed_core_operation(
        component="projection",
        operation="reproject_dependents",
        logger=logger,
        lane_id=lane_id,
    ):
        if not graph_id:
            return

        if not _lane_completed_successfully(lane):
            return

        if _dependency_projection_already_processed(lane):
            return

        try:
            graph = graph_store.get(graph_id)
        except KeyError:
            graph_set = _find_graph_set_for_lane(
                graph_store,
                lane,
                graph_id=graph_id,
            )
            if graph_set is None:
                _record_missing_graph_once(lane, lane_id, graph_id, sm)
                lane = sm.get_lane(lane_id)
                _record_missing_graph_set_once(lane, lane_id, graph_id, sm)
                return

            projected = project_feature_graph_set_ready_lanes(
                graph_set,
                _lanes_path(sm),
                terminal_success_feature_ids=_terminal_success_feature_ids(
                    graph_set,
                    _projected_lanes(_lanes_path(sm)),
                ),
            )
            metadata = _projection_metadata(
                len(projected),
                lane=sm.get_lane(lane_id),
                source="graph_set",
            )
            sm.update_metadata(lane_id, metadata)
            return

        projected = project_ready_lanes(graph, _lanes_path(sm))
        metadata = _projection_metadata(len(projected), lane=lane, source="lane_graph")
        sm.update_metadata(lane_id, metadata)


def aggregate_status(lanes: list[dict[str, Any]], graph_id: str) -> AggregatedStatus:
    graph_lanes = [
        lane
        for lane in lanes
        if isinstance(lane, dict) and str(lane.get("graph_id") or "") == graph_id
    ]
    lane_statuses = [_lane_status(lane) for lane in graph_lanes]
    lane_counts = summarize_lane_states(graph_lanes)

    if not lane_statuses:
        return AggregatedStatus(
            graph_id=graph_id,
            status="in_progress",
            terminal=False,
            reason="no graph lanes have been projected yet",
            lane_counts=lane_counts,
            lane_statuses=lane_statuses,
        )

    if any(not item["terminal"] for item in lane_statuses):
        return AggregatedStatus(
            graph_id=graph_id,
            status="in_progress",
            terminal=False,
            reason="at least one graph lane is not terminal",
            lane_counts=lane_counts,
            lane_statuses=lane_statuses,
        )

    if all(item["normalized_status"] == "merged" for item in lane_statuses):
        return AggregatedStatus(
            graph_id=graph_id,
            status="merged",
            terminal=True,
            reason="all graph lanes merged",
            lane_counts=lane_counts,
            lane_statuses=lane_statuses,
        )

    return AggregatedStatus(
        graph_id=graph_id,
        status="terminated",
        terminal=True,
        reason="at least one graph lane terminalized without merge",
        lane_counts=lane_counts,
        lane_statuses=lane_statuses,
    )


def _lane_graph_id(lane: dict[str, Any] | None) -> str | None:
    graph_id = lane.get("graph_id") if isinstance(lane, dict) else None
    return str(graph_id) if graph_id else None


def _lane_conversation_id(lane: dict[str, Any] | None) -> str | None:
    conversation_id = lane.get("conversation_id") if isinstance(lane, dict) else None
    return str(conversation_id) if conversation_id else None


def _record_missing_graph_once(
    lane: dict[str, Any],
    lane_id: str,
    graph_id: str,
    sm: _LaneStateMachine,
) -> None:
    if lane.get("dependency_projection_missing_graph_id") == graph_id:
        return
    log_event(
        logger,
        logging.WARNING,
        "lane_graph_not_found",
        lane_id=lane_id,
        graph_id=graph_id,
    )
    sm.update_metadata(
        lane_id,
        {
            "dependency_projection_missing_graph_id": graph_id,
            "dependency_projection_missing_graph_at": time.time(),
        },
    )


def _record_missing_graph_set_once(
    lane: dict[str, Any],
    lane_id: str,
    graph_id: str,
    sm: _LaneStateMachine,
) -> None:
    if lane.get("dependency_projection_missing_graph_set_graph_id") == graph_id:
        return
    log_event(
        logger,
        logging.WARNING,
        "feature_graph_set_not_found",
        lane_id=lane_id,
        graph_id=graph_id,
    )
    sm.update_metadata(
        lane_id,
        {
            "dependency_projection_missing_graph_set_graph_id": graph_id,
            "dependency_projection_missing_graph_set_at": time.time(),
        },
    )


def _find_graph_set_by_graph_id(
    graph_store: LaneGraphStore,
    graph_id: str,
    *,
    conversation_id: str | None = None,
) -> FeatureGraphSet | None:
    root = getattr(graph_store, "_root", None)
    if not isinstance(root, Path):
        return None

    for graph_sets_root in (root, root.parent / "graph_sets"):
        if not graph_sets_root.exists():
            continue
        for path in sorted(graph_sets_root.glob("*.json")):
            try:
                graph_set = FeatureGraphSet.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if _graph_set_contains_graph(
                graph_set,
                graph_id,
                conversation_id=conversation_id,
            ):
                return graph_set
    return None


def _find_graph_set_for_lane(
    graph_store: LaneGraphStore,
    lane: dict[str, Any] | None,
    *,
    graph_id: str,
) -> FeatureGraphSet | None:
    graph_set_id = _optional_str(lane.get("graph_set_id") if isinstance(lane, dict) else None)
    conversation_id = _lane_conversation_id(lane)
    if graph_set_id:
        graph_set = _find_graph_set_by_id(
            graph_store,
            graph_set_id,
            conversation_id=conversation_id,
        )
        if graph_set is not None and _graph_set_contains_graph(
            graph_set,
            graph_id,
            conversation_id=conversation_id,
        ):
            return graph_set
    return _find_graph_set_by_graph_id(
        graph_store,
        graph_id,
        conversation_id=conversation_id,
    )


def _find_graph_set_by_id(
    graph_store: LaneGraphStore,
    graph_set_id: str,
    *,
    conversation_id: str | None,
) -> FeatureGraphSet | None:
    root = getattr(graph_store, "_root", None)
    if not isinstance(root, Path):
        return None
    for graph_sets_root in (root, root.parent / "graph_sets"):
        if not graph_sets_root.exists():
            continue
        store = FeatureGraphSetStore(graph_sets_root)
        try:
            return store.get(graph_set_id, conversation_id=conversation_id)
        except (KeyError, ValueError):
            graph_set = _scan_graph_set_by_id(
                graph_sets_root,
                graph_set_id,
                conversation_id=conversation_id,
            )
            if graph_set is not None:
                return graph_set
    return None


def _scan_graph_set_by_id(
    graph_sets_root: Path,
    graph_set_id: str,
    *,
    conversation_id: str | None,
) -> FeatureGraphSet | None:
    for path in sorted(graph_sets_root.glob("*.json")):
        try:
            graph_set = FeatureGraphSet.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        if graph_set.id != graph_set_id:
            continue
        if (
            conversation_id is not None
            and graph_set.feature_plan.conversation_id != conversation_id
        ):
            continue
        return graph_set
    return None


def _graph_set_contains_graph(
    graph_set: FeatureGraphSet,
    graph_id: str,
    *,
    conversation_id: str | None,
) -> bool:
    if conversation_id is None:
        return any(graph.id == graph_id for graph in graph_set.graphs)

    if graph_set.feature_plan.conversation_id != conversation_id:
        return False
    return any(
        graph.id == graph_id and graph.conversation_id == conversation_id
        for graph in graph_set.graphs
    )


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _projected_lanes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [lane for lane in data.get("lanes", []) if isinstance(lane, dict)]


def _terminal_success_feature_ids(
    graph_set: FeatureGraphSet,
    lanes: list[dict[str, Any]],
) -> set[str]:
    completed_lane_keys = {
        (
            str(lane.get("conversation_id") or ""),
            str(lane["graph_id"]),
            _lane_local_id(lane),
        )
        for lane in lanes
        if isinstance(lane.get("graph_id"), str)
        and _lane_local_id(lane)
        and str(lane.get("status") or "") in _COMPLETED_STATUSES
    }
    graphs_by_id = {graph.id: graph for graph in graph_set.graphs}
    terminal_success: set[str] = set()
    for feature in graph_set.feature_plan.features:
        graph = graphs_by_id.get(feature.graph_id)
        if graph is None or not graph.lanes:
            continue
        graph_lane_keys = {
            (graph.conversation_id, graph.id, node.feature_id) for node in graph.lanes
        }
        if graph_lane_keys.issubset(completed_lane_keys):
            terminal_success.add(feature.feature_id)
    return terminal_success


def _lane_local_id(lane: dict[str, Any]) -> str:
    if isinstance(lane.get("lane_local_id"), str):
        return str(lane["lane_local_id"])
    if isinstance(lane.get("feature_id"), str):
        return str(lane["feature_id"])
    return ""


def _lane_completed_successfully(lane: dict[str, Any] | None) -> bool:
    if not isinstance(lane, dict):
        return False
    return str(lane.get("status") or "") in _COMPLETED_STATUSES


def _dependency_projection_already_processed(lane: dict[str, Any]) -> bool:
    if not lane.get("dependency_projection_processed_at"):
        return False
    processed_status = lane.get("dependency_projection_processed_status")
    if processed_status is None:
        # Older projections wrote a marker without recording the lane state.
        # Reprocess once so lanes marked too early can still release dependents.
        return False
    return str(processed_status) == str(lane.get("status") or "")


def _projection_metadata(
    projected_count: int,
    *,
    lane: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    now = time.time()
    metadata: dict[str, Any] = {
        "dependency_projection_processed_at": now,
        "dependency_projection_count": projected_count,
        "dependency_projection_source": source,
        "dependency_projection_processed_status": str(lane.get("status") or ""),
    }
    if lane.get("dependency_projection_missing_graph_id"):
        metadata["dependency_projection_missing_graph_id"] = None
        metadata["dependency_projection_missing_graph_resolved_at"] = now
    if lane.get("dependency_projection_missing_graph_set_graph_id"):
        metadata["dependency_projection_missing_graph_set_graph_id"] = None
        metadata["dependency_projection_missing_graph_set_resolved_at"] = now
    return metadata


def _lanes_path(sm: _LaneStateMachine) -> Path:
    path = getattr(sm, "_path", None)
    if not isinstance(path, Path):
        raise TypeError("state machine must expose a pathlib.Path _path")
    return path


def _lane_status(lane: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_lane_state(lane)
    return {
        "lane_id": normalized.feature_id,
        "raw_status": normalized.raw_status,
        "normalized_status": normalized.normalized_status,
        "terminal": normalized.is_terminal,
    }
