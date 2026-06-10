"""Dashboard graph authority, lineage, and graph-set read helpers."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from xmuse_core.platform.dashboard_graph_state import build_derived_graph_state


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"invalid JSON in {path.name}: {exc.msg}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not read {path.name}: {exc}",
        ) from exc


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_lineage_records(base_dir: Path) -> list[dict[str, Any]]:
    """Load raw lineage records from ``self_evolution/lineage.json``."""
    data = _read_json(base_dir / "self_evolution" / "lineage.json", {"lineage": []})
    if not isinstance(data, dict):
        return []
    raw = data.get("lineage", [])
    return [r for r in raw if isinstance(r, dict)]


def _read_run_aggregations(base_dir: Path) -> list[dict[str, Any]]:
    data = _read_json(
        base_dir / "self_evolution" / "run_aggregations.json",
        {"aggregations": []},
    )
    if not isinstance(data, dict):
        return []
    raw = data.get("aggregations", [])
    return [r for r in raw if isinstance(raw, list) and isinstance(r, dict)]


def _record_timestamp(record: dict[str, Any]) -> datetime:
    parsed = _parse_timestamp(record.get("created_at"))
    if parsed is None:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _aggregation_status(aggregation: dict[str, Any] | None, *, default: str) -> str:
    if aggregation is None:
        return default
    status_value = aggregation.get("status")
    if not isinstance(status_value, str) or not status_value:
        return "unknown"
    if status_value == "in_progress":
        return "running"
    return status_value


def _aggregation_terminal(aggregation: dict[str, Any] | None) -> bool:
    if aggregation is None:
        return False
    terminal = aggregation.get("terminal")
    if isinstance(terminal, bool):
        return terminal
    return _aggregation_status(aggregation, default="unknown") in {
        "merged",
        "terminated",
        "blocked_for_input",
    }


def _aggregation_summary(aggregation: dict[str, Any] | None) -> dict[str, Any] | None:
    if aggregation is None:
        return None
    return {
        "aggregation_id": aggregation.get("aggregation_id"),
        "run_id": aggregation.get("run_id"),
        "resolution_id": aggregation.get("resolution_id"),
        "graph_id": aggregation.get("graph_id"),
        "status": _aggregation_status(aggregation, default="unknown"),
        "terminal": _aggregation_terminal(aggregation),
        "reason": aggregation.get("reason"),
        "created_at": aggregation.get("created_at"),
    }


def _read_runtime_snapshot(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError):
        return None


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


def _feature_graph_set_counts(data: dict[str, Any]) -> dict[str, int]:
    feature_plan = data.get("feature_plan", {})
    features = feature_plan.get("features", []) if isinstance(feature_plan, dict) else []
    graphs = data.get("graphs", [])
    return {
        "features": len(features) if isinstance(features, list) else 0,
        "lane_graphs": len(graphs) if isinstance(graphs, list) else 0,
    }


def _feature_graph_set_id(data: dict[str, Any], path: Path) -> str:
    graph_set_id = data.get("id")
    return graph_set_id if isinstance(graph_set_id, str) and graph_set_id else path.stem


def _feature_graph_set_summary(data: dict[str, Any], path: Path) -> dict[str, Any]:
    feature_plan = data.get("feature_plan", {})
    if not isinstance(feature_plan, dict):
        feature_plan = {}
    graph_set_id = _feature_graph_set_id(data, path)
    return {
        "id": graph_set_id,
        "feature_plan_id": feature_plan.get("id"),
        "conversation_id": feature_plan.get("conversation_id"),
        "resolution_id": feature_plan.get("resolution_id"),
        "version": feature_plan.get("version"),
        "status": data.get("status", "planned"),
        "counts": _feature_graph_set_counts(data),
        "href": f"/dashboard/feature-graph-sets/{graph_set_id}",
        "api_href": f"/api/feature-graph-sets/{graph_set_id}",
    }


def _iter_feature_graph_set_snapshots(
    base_dir: Path,
) -> list[tuple[Path, dict[str, Any]]]:
    snapshots: list[tuple[Path, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    for graphs_dir in (base_dir / "lane_graphs", base_dir / "graph_sets"):
        if not graphs_dir.exists():
            continue
        for path in sorted(graphs_dir.glob("*.json")):
            data = _read_runtime_snapshot(path)
            if not _is_feature_graph_set_snapshot(data):
                continue
            graph_set_id = _feature_graph_set_id(data, path)
            if graph_set_id in seen_ids:
                continue
            seen_ids.add(graph_set_id)
            snapshots.append((path, data))
    return snapshots


def _find_feature_graph_set_snapshot(
    base_dir: Path,
    graph_set_id: str,
) -> tuple[Path, dict[str, Any]] | None:
    for path, data in _iter_feature_graph_set_snapshots(base_dir):
        if _feature_graph_set_id(data, path) == graph_set_id:
            return path, data
    return None


def _latest_aggregation_for_graph(
    aggregations: list[dict[str, Any]],
    graph_id: str | None,
) -> dict[str, Any] | None:
    if not graph_id:
        return None
    matches = [
        aggregation
        for aggregation in aggregations
        if aggregation.get("graph_id") == graph_id or aggregation.get("run_id") == graph_id
    ]
    if not matches:
        return None
    return sorted(matches, key=_record_timestamp)[-1]


def _aggregation_by_id(
    aggregations: list[dict[str, Any]],
    aggregation_id: str | None,
) -> dict[str, Any] | None:
    if not aggregation_id:
        return None
    for aggregation in aggregations:
        if aggregation.get("aggregation_id") == aggregation_id:
            return aggregation
    return None


def _build_lineage_graph(
    records: list[dict[str, Any]],
    *,
    from_node: str | None = None,
    depth: int | None = None,
) -> dict[str, Any]:
    """Build a graph representation of execution lineage records."""
    adjacency: dict[str, list[str]] = {}
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    for rec in records:
        src = rec.get("source_run_id")
        dst = rec.get("spawned_graph_id")
        if not src or not dst:
            continue
        node_ids.add(src)
        node_ids.add(dst)
        adjacency.setdefault(src, []).append(dst)
        edges.append(
            {
                "lineage_id": rec.get("lineage_id"),
                "source_node": src,
                "target_node": dst,
                "blueprint_set_id": rec.get("blueprint_set_id"),
                "target_track_ids": rec.get("target_track_ids", []),
                "evolution_proposal_id": rec.get("evolution_proposal_id"),
                "guardrail_decision_id": rec.get("guardrail_decision_id"),
                "created_at": rec.get("created_at"),
            }
        )

    in_degree: dict[str, int] = {node: 0 for node in node_ids}
    for edge in edges:
        in_degree[edge["target_node"]] = in_degree.get(edge["target_node"], 0) + 1
    merge_points = [node for node, degree in in_degree.items() if degree > 1]

    if from_node is not None:
        reachable: set[str] = set()
        queue: list[tuple[str, int]] = [(from_node, 0)]
        while queue:
            current, current_depth = queue.pop(0)
            if current in reachable:
                continue
            reachable.add(current)
            if depth is not None and current_depth >= depth:
                continue
            for neighbor in adjacency.get(current, []):
                if neighbor not in reachable:
                    queue.append((neighbor, current_depth + 1))
        node_ids = node_ids & reachable
        edges = [
            edge
            for edge in edges
            if edge["source_node"] in reachable and edge["target_node"] in reachable
        ]
        merge_points = [node for node in merge_points if node in reachable]

    node_meta: dict[str, dict[str, Any]] = {}
    for rec in records:
        src = rec.get("source_run_id")
        dst = rec.get("spawned_graph_id")
        if src and src in node_ids:
            if src not in node_meta:
                node_meta[src] = {
                    "node_id": src,
                    "node_type": "run",
                    "is_merge_point": src in merge_points,
                }
        if dst and dst in node_ids:
            node_meta[dst] = {
                "node_id": dst,
                "node_type": "graph",
                "is_merge_point": dst in merge_points,
                "spawned_at": rec.get("created_at"),
                "blueprint_set_id": rec.get("blueprint_set_id"),
                "target_track_ids": rec.get("target_track_ids", []),
            }

    nodes = sorted(node_meta.values(), key=lambda node: node["node_id"])

    return {
        "nodes": nodes,
        "edges": edges,
        "merge_points": merge_points,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }


def _graph_authority_state(base_dir: Path) -> dict[str, Any]:
    """Derive graph authority state from lineage and aggregation records."""
    records = _read_lineage_records(base_dir)
    aggregations = _read_run_aggregations(base_dir)

    if not records:
        return {
            "authoritative_graph_id": None,
            "merge_state": "unknown",
            "lineage_terminated": False,
            "lineage_status": "unknown",
            "open_lineage_count": 0,
            "latest_run_id": None,
            "latest_lineage_id": None,
            "source_aggregation": None,
            "graph_aggregation": None,
            "graph_state_source": "none",
            "graph_lineage_status": "unknown",
            "graph_terminal": False,
            "graph_reason": None,
            "graph_lane_counts": {},
            "graph_lane_statuses": [],
            "open_lane_lineages": [],
            "failed_lineages": [],
            "merged_lineages": [],
            "unmerged_terminal_lineages": [],
            "blocked_objects": [],
            "final_action_holds": [],
        }

    sorted_records = sorted(records, key=_record_timestamp, reverse=True)
    latest = sorted_records[0]
    authoritative_graph_id: str | None = latest.get("spawned_graph_id") or None
    latest_run_id: str | None = latest.get("source_run_id") or None
    latest_lineage_id: str | None = latest.get("lineage_id") or None
    source_aggregation = _aggregation_by_id(
        aggregations,
        latest.get("terminal_aggregation_ref"),
    )
    if source_aggregation is None:
        source_aggregation = _latest_aggregation_for_graph(aggregations, latest_run_id)

    graph_aggregation = _latest_aggregation_for_graph(aggregations, authoritative_graph_id)
    derived_graph = build_derived_graph_state(base_dir, authoritative_graph_id)
    merge_state = (
        str(derived_graph["status"])
        if derived_graph is not None
        else _aggregation_status(
            graph_aggregation,
            default="running" if authoritative_graph_id else "unknown",
        )
    )
    lineage_status = _aggregation_status(source_aggregation, default="unknown")
    lineage_terminated = _aggregation_terminal(source_aggregation)

    open_lineage_count = sum(
        1
        for rec in records
        if (gid := rec.get("spawned_graph_id"))
        and not (
            derived["terminal"]
            if (derived := build_derived_graph_state(base_dir, str(gid))) is not None
            else _aggregation_terminal(_latest_aggregation_for_graph(aggregations, str(gid)))
        )
    )

    return {
        "authoritative_graph_id": authoritative_graph_id,
        "merge_state": merge_state,
        "lineage_terminated": lineage_terminated,
        "lineage_status": lineage_status,
        "open_lineage_count": open_lineage_count,
        "latest_run_id": latest_run_id,
        "latest_lineage_id": latest_lineage_id,
        "source_aggregation": _aggregation_summary(source_aggregation),
        "graph_aggregation": _aggregation_summary(graph_aggregation),
        "graph_state_source": derived_graph["source"]
        if derived_graph is not None
        else "run_aggregation",
        "graph_lineage_status": derived_graph["graph_lineage_status"]
        if derived_graph is not None
        else (
            "merged"
            if _aggregation_status(graph_aggregation, default="unknown") == "merged"
            else "terminated"
            if _aggregation_terminal(graph_aggregation)
            else "open"
            if authoritative_graph_id
            else "unknown"
        ),
        "graph_terminal": bool(derived_graph["terminal"])
        if derived_graph is not None
        else _aggregation_terminal(graph_aggregation),
        "graph_reason": derived_graph["reason"]
        if derived_graph is not None
        else (
            graph_aggregation.get("reason")
            if graph_aggregation is not None
            else None
        ),
        "graph_lane_counts": derived_graph["lane_counts"]
        if derived_graph is not None
        else (
            graph_aggregation.get("lane_counts", {})
            if graph_aggregation is not None
            else {}
        ),
        "graph_lane_statuses": derived_graph["lane_statuses"]
        if derived_graph is not None
        else (
            graph_aggregation.get("lane_statuses", [])
            if graph_aggregation is not None
            else []
        ),
        "open_lane_lineages": derived_graph["open_lane_lineages"]
        if derived_graph is not None
        else (
            graph_aggregation.get("open_lineages", [])
            if graph_aggregation is not None
            else []
        ),
        "failed_lineages": derived_graph["failed_lineages"]
        if derived_graph is not None
        else [],
        "merged_lineages": derived_graph["merged_lineages"]
        if derived_graph is not None
        else [],
        "unmerged_terminal_lineages": derived_graph["unmerged_terminal_lineages"]
        if derived_graph is not None
        else [],
        "blocked_objects": derived_graph["blocked_objects"]
        if derived_graph is not None
        else (
            graph_aggregation.get("blocked_objects", [])
            if graph_aggregation is not None
            else []
        ),
        "final_action_holds": derived_graph["final_action_holds"]
        if derived_graph is not None
        else (
            graph_aggregation.get("final_action_holds", [])
            if graph_aggregation is not None
            else []
        ),
    }
