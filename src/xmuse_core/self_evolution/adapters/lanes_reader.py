from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.platform.state_normalizer import normalize_lane_state
from xmuse_core.structuring.graph_store import LaneGraphStore
from xmuse_core.structuring.models import LaneGraph


class LanesReader:
    """Read-only adapter for xmuse feature_lanes.json."""

    def __init__(
        self,
        lanes_path: Path | str,
        *,
        xmuse_root: Path | str | None = None,
    ) -> None:
        self._lanes_path = Path(lanes_path)
        self._xmuse_root = Path(xmuse_root) if xmuse_root is not None else self._lanes_path.parent

    @property
    def lanes_path(self) -> Path:
        return self._lanes_path

    @property
    def xmuse_root(self) -> Path:
        return self._xmuse_root

    def list_lanes(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if not self._lanes_path.exists():
            return []
        data = json.loads(self._lanes_path.read_text(encoding="utf-8"))
        lanes = data.get("lanes", []) if isinstance(data, dict) else []
        result = [lane for lane in lanes if isinstance(lane, dict)]
        if status is not None:
            result = [lane for lane in result if lane.get("status") == status]
        return result

    def get_lane(self, lane_id: str) -> dict[str, Any] | None:
        for lane in self.list_lanes():
            if lane.get("feature_id") == lane_id:
                return lane
        return None

    def lineage_lane_ids(self, graph_id: str) -> list[str]:
        lanes = self.list_lanes()
        lane_by_id = {
            str(lane.get("feature_id")): lane
            for lane in lanes
            if lane.get("feature_id")
        }
        graph_lane_ids = self.graph_lane_ids(graph_id, lanes=lanes)
        return self._lineage_lane_ids_from_roots(graph_lane_ids, lane_by_id)

    def graph_lane_ids(
        self,
        graph_id: str,
        *,
        lanes: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        graph = self.get_graph(graph_id)
        if graph is None:
            source_lanes = lanes if lanes is not None else self.list_lanes()
            return [
                str(lane["feature_id"])
                for lane in source_lanes
                if lane.get("graph_id") == graph_id and lane.get("feature_id")
            ]
        return [node.feature_id for node in graph.lanes]

    def graph_resolution_id(self, graph_id: str) -> str | None:
        graph = self.get_graph(graph_id)
        return graph.resolution_id if graph is not None else None

    def get_graph(self, graph_id: str) -> LaneGraph | None:
        try:
            return LaneGraphStore(self.xmuse_root / "lane_graphs").get(graph_id)
        except KeyError:
            return None

    def _lineage_lane_ids_from_roots(
        self,
        graph_lane_ids: list[str],
        lane_by_id: dict[str, dict[str, Any]],
    ) -> list[str]:
        ordered = list(graph_lane_ids)
        seen = set(ordered)
        changed = True
        while changed:
            changed = False
            for lane_id, lane in lane_by_id.items():
                source_lane_id = lane.get("source_lane_id")
                if source_lane_id in seen and lane_id not in seen:
                    ordered.append(lane_id)
                    seen.add(lane_id)
                    changed = True
        return ordered

    def open_lineages(self, lane_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "source_lane_id": lane.get("source_lane_id"),
                "feature_id": lane_id,
                "status": lane.get("status"),
            }
            for lane_id, lane in lane_by_id.items()
            if lane.get("source_lane_id") and not normalize_lane_state(lane).is_terminal
        ]

    def blocked_object_for_lane(self, lane: dict[str, Any]) -> dict[str, Any] | None:
        clarification = lane.get("clarification_request")
        if isinstance(clarification, dict):
            return {
                "lane_id": lane.get("feature_id"),
                "missing_input": clarification.get("missing_input", "unspecified"),
                "owner": clarification.get("owner", "human"),
                "resume_path": clarification.get(
                    "resume_path",
                    "provide information and reproject graph",
                ),
            }
        if lane.get("status") == "blocked_for_input":
            return {
                "lane_id": lane.get("feature_id"),
                "missing_input": lane.get("missing_input", "unspecified"),
                "owner": lane.get("input_owner", "human"),
                "resume_path": lane.get("resume_path", "provide information and resume lane"),
            }
        return None

    def final_action_hold_for_lane(self, lane: dict[str, Any]) -> dict[str, Any] | None:
        if lane.get("status") != "awaiting_final_action":
            return None
        hold: dict[str, Any] = {
            "lane_id": lane.get("feature_id"),
            "action": lane.get("final_action", "merge"),
            "verdict_id": lane.get("review_verdict_id"),
        }
        if lane.get("review_summary"):
            hold["summary"] = self._compact_signal_text(str(lane["review_summary"]), 160)
        return hold

    def _compact_signal_text(self, value: str, max_chars: int) -> str:
        compact = " ".join(value.split())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 3].rstrip() + "..."
