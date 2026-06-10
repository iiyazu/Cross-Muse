from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from xmuse_core.platform.state_normalizer import (
    normalize_lane_state,
    summarize_lane_states,
)


def build_derived_graph_state(base_dir: Path, graph_id: str | None) -> dict[str, Any] | None:
    """Compute dashboard graph state from lane graph snapshots and Stage-0 lanes."""

    graph = read_lane_graph(base_dir, graph_id)
    if graph is None:
        return None

    lane_data = _load_lanes(base_dir)
    lanes = [lane for lane in lane_data["lanes"] if isinstance(lane, dict)]
    lane_by_id = {
        str(lane["feature_id"]): lane
        for lane in lanes
        if isinstance(lane.get("feature_id"), str) and lane.get("feature_id")
    }
    lineage_ids = _lineage_lane_ids(_graph_lane_ids(graph), lane_by_id)
    review_verdict_decisions = _finalized_review_verdict_decisions(base_dir)
    merge_verdict_lane_ids = {
        lane_id
        for lane_id, decision in review_verdict_decisions.items()
        if decision == "merge"
    }
    closed_verdict_lane_ids = {
        lane_id
        for lane_id, decision in review_verdict_decisions.items()
        if decision in {"merge", "terminate"}
    }

    lane_statuses: list[dict[str, Any]] = []
    blocked_objects: list[dict[str, Any]] = []
    final_action_holds: list[dict[str, Any]] = []
    merged_lineages: list[str] = []
    failed_lineages: list[str] = []
    open_lane_lineages: list[str] = []
    unmerged_terminal_lineages: list[str] = []

    for lane_id in lineage_ids:
        lane = lane_by_id.get(lane_id)
        if lane is None:
            lane_statuses.append(
                {
                    "feature_id": lane_id,
                    "raw_status": "unprojected",
                    "normalized_status": "waiting_dependency",
                    "terminal": False,
                }
            )
            open_lane_lineages.append(lane_id)
            continue

        normalized = normalize_lane_state(lane)
        has_merge_verdict = _lane_has_merge_verdict(
            lane_id,
            lane,
            merge_verdict_lane_ids,
        )
        lane_status = {
            "feature_id": lane_id,
            "raw_status": normalized.raw_status,
            "normalized_status": normalized.normalized_status,
            "terminal": normalized.is_terminal,
            "has_merge_verdict": has_merge_verdict,
        }
        if lane.get("review_decision"):
            lane_status["review_decision"] = str(lane["review_decision"])
        if lane_id in review_verdict_decisions:
            lane_status["review_verdict_decision"] = review_verdict_decisions[lane_id]
        lane_statuses.append(lane_status)

        blocked = _blocked_object_for_lane(lane)
        if blocked is not None and (
            normalized.raw_status == "blocked_for_input" or not normalized.is_terminal
        ):
            blocked_objects.append(blocked)
        hold = _final_action_hold_for_lane(lane)
        if hold is not None:
            final_action_holds.append(hold)

        if not normalized.is_terminal:
            open_lane_lineages.append(lane_id)
        elif normalized.normalized_status == "merged" or has_merge_verdict:
            merged_lineages.append(lane_id)
        else:
            failed_lineages.append(lane_id)
            if _needs_lineage_merge_coordination(
                lane_id,
                lane_status,
                closed_verdict_lane_ids,
            ):
                unmerged_terminal_lineages.append(lane_id)

    present_lanes = [lane_by_id[lane_id] for lane_id in lineage_ids if lane_id in lane_by_id]
    lane_counts = summarize_lane_states(present_lanes)

    if blocked_objects:
        merge_state = "blocked_for_input"
        terminal = True
        reason = "one or more lanes request clarification"
        graph_lineage_status = "blocked_for_input"
    elif not lane_statuses:
        merge_state = "running"
        terminal = False
        reason = "no graph lanes have been projected yet"
        graph_lineage_status = "open"
    elif final_action_holds:
        merge_state = "running"
        terminal = False
        reason = "one or more lanes are awaiting final-action approval"
        graph_lineage_status = "awaiting_final_action"
    elif open_lane_lineages:
        merge_state = "running"
        terminal = False
        reason = "at least one graph lineage lane is not terminal"
        graph_lineage_status = "open"
    elif all(item["normalized_status"] == "merged" for item in lane_statuses):
        merge_state = "merged"
        terminal = True
        reason = "all graph lineage lanes merged"
        graph_lineage_status = "merged"
    elif unmerged_terminal_lineages:
        merge_state = "running"
        terminal = False
        reason = "graph lineage merge coordination pending"
        graph_lineage_status = "incomplete_termination"
    else:
        merge_state = "terminated"
        terminal = True
        reason = "at least one graph lineage terminalized without merge"
        graph_lineage_status = "terminated"

    return {
        "source": "lane_graph",
        "status": merge_state,
        "terminal": terminal,
        "reason": reason,
        "graph_lineage_status": graph_lineage_status,
        "lane_counts": lane_counts,
        "lane_statuses": lane_statuses,
        "open_lane_lineages": open_lane_lineages,
        "failed_lineages": failed_lineages,
        "merged_lineages": merged_lineages,
        "unmerged_terminal_lineages": unmerged_terminal_lineages,
        "blocked_objects": blocked_objects,
        "final_action_holds": final_action_holds,
    }


def read_lane_graph(base_dir: Path, graph_id: str | None) -> dict[str, Any] | None:
    if not graph_id:
        return None
    path = base_dir / "lane_graphs" / f"{graph_id}.json"
    if not path.exists():
        return None
    data = _read_json(path, {})
    return data if _is_lane_graph_snapshot(data) else None


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError) as exc:
        raise ValueError(f"could not read dashboard graph state JSON {path}: {exc}") from exc


def _load_lanes(base_dir: Path) -> dict[str, Any]:
    data = _read_json(base_dir / "feature_lanes.json", {"lanes": []})
    if not isinstance(data, dict):
        return {"lanes": []}
    lanes = data.get("lanes", [])
    if not isinstance(lanes, list):
        return {"lanes": []}
    return data


def _is_feature_graph_set_snapshot(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    feature_plan = data.get("feature_plan")
    if not isinstance(feature_plan, dict):
        return False
    return isinstance(feature_plan.get("features"), list) and isinstance(
        data.get("graphs"),
        list,
    )


def _is_lane_graph_snapshot(data: Any) -> bool:
    if not isinstance(data, dict) or _is_feature_graph_set_snapshot(data):
        return False
    return isinstance(data.get("lanes"), list)


def _graph_lane_ids(graph: dict[str, Any] | None) -> list[str]:
    if graph is None:
        return []
    lanes = graph.get("lanes", [])
    if not isinstance(lanes, list):
        return []
    lane_ids: list[str] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        feature_id = lane.get("feature_id")
        if isinstance(feature_id, str) and feature_id:
            lane_ids.append(feature_id)
    return lane_ids


def _lineage_lane_ids(
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


def _finalized_review_verdict_decisions(base_dir: Path) -> dict[str, str]:
    data = _read_json(base_dir / "review_plane.json", {"review_verdicts": []})
    if not isinstance(data, dict):
        return {}
    verdicts = data.get("review_verdicts", [])
    if not isinstance(verdicts, list):
        return {}
    decisions: dict[str, str] = {}
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        lane_id = verdict.get("lane_id")
        if (
            isinstance(lane_id, str)
            and str(verdict.get("status", "finalized")).lower() == "finalized"
        ):
            decisions[lane_id] = str(verdict.get("decision", "")).lower()
    return decisions


def _lane_has_merge_verdict(
    lane_id: str,
    lane: dict[str, Any] | None,
    merge_verdict_lane_ids: set[str],
) -> bool:
    if lane_id in merge_verdict_lane_ids:
        return True
    if lane is None:
        return False
    return str(lane.get("review_decision", "")).lower() == "merge"


def _needs_lineage_merge_coordination(
    lane_id: str,
    lane_status: dict[str, Any],
    closed_verdict_lane_ids: set[str],
) -> bool:
    if lane_id in closed_verdict_lane_ids:
        return False
    review_decision = str(lane_status.get("review_decision", "")).lower()
    return review_decision in {"rework", "patch-forward", "patch_forward"}


def _blocked_object_for_lane(lane: dict[str, Any]) -> dict[str, Any] | None:
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


def _final_action_hold_for_lane(lane: dict[str, Any]) -> dict[str, Any] | None:
    if lane.get("status") != "awaiting_final_action":
        return None
    hold: dict[str, Any] = {
        "lane_id": lane.get("feature_id"),
        "action": lane.get("final_action", "merge"),
        "verdict_id": lane.get("review_verdict_id"),
    }
    if lane.get("review_summary"):
        hold["summary"] = str(lane["review_summary"])[:160]
    return hold
