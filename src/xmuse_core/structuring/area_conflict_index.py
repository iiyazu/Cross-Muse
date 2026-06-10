from __future__ import annotations

from typing import Protocol


class AreaScopedLane(Protocol):
    lane_id: str
    expected_touched_areas: list[str]


def serial_edges_for_touched_areas(lanes: list[AreaScopedLane]) -> list[tuple[str, str]]:
    """Return deterministic dependency edges for lanes that touch the same repo area."""

    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    last_lane_by_area: dict[str, str] = {}
    for lane in lanes:
        for area in sorted(set(lane.expected_touched_areas)):
            previous_lane_id = last_lane_by_area.get(area)
            if previous_lane_id is not None and previous_lane_id != lane.lane_id:
                edge = (previous_lane_id, lane.lane_id)
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    edges.append(edge)
            last_lane_by_area[area] = lane.lane_id
    return edges
