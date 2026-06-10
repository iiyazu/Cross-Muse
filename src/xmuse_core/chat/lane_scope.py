from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LaneScope:
    graph_ids: frozenset[str]
    unambiguous_feature_ids: frozenset[str]


def conversation_scoped_lanes(
    base_dir: Path,
    conversation_id: str,
    lanes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scope = build_lane_scope(base_dir, conversation_id)
    return [
        lane
        for lane in lanes
        if lane_belongs_to_conversation(lane, conversation_id, scope)
    ]


def lane_belongs_to_conversation(
    lane: dict[str, Any],
    conversation_id: str,
    scope: LaneScope,
) -> bool:
    lane_conversation_id = _string_value(lane.get("conversation_id"))
    if lane_conversation_id is not None:
        return lane_conversation_id == conversation_id

    graph_id = _string_value(lane.get("graph_id"))
    if graph_id is not None:
        return graph_id in scope.graph_ids

    feature_id = _string_value(lane.get("feature_id"))
    return feature_id in scope.unambiguous_feature_ids


def build_lane_scope(base_dir: Path, conversation_id: str) -> LaneScope:
    graphs_dir = base_dir / "lane_graphs"
    if not graphs_dir.exists():
        return LaneScope(graph_ids=frozenset(), unambiguous_feature_ids=frozenset())

    graph_ids: set[str] = set()
    feature_conversations: dict[str, set[str]] = {}
    for path in sorted(graphs_dir.glob("*.json")):
        data = _read_json_file(path, {})
        if not isinstance(data, dict):
            continue

        graph_conversation_id = _string_value(data.get("conversation_id"))
        graph_id = _string_value(data.get("id")) or path.stem
        if graph_conversation_id == conversation_id:
            graph_ids.add(graph_id)

        lanes = data.get("lanes", [])
        if not isinstance(lanes, list) or graph_conversation_id is None:
            continue
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            feature_id = _string_value(lane.get("feature_id"))
            if feature_id is not None:
                feature_conversations.setdefault(feature_id, set()).add(
                    graph_conversation_id
                )

    feature_ids = {
        feature_id
        for feature_id, conversation_ids in feature_conversations.items()
        if conversation_ids == {conversation_id}
    }
    return LaneScope(
        graph_ids=frozenset(graph_ids),
        unambiguous_feature_ids=frozenset(feature_ids),
    )


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError):
        return default


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
