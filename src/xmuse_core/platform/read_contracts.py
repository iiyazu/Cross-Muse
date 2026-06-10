from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from xmuse_core.chat.store import ChatStore
from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.platform import provider_read_contracts, read_tool_inventory
from xmuse_core.platform.lane_context import build_lane_context_bundle
from xmuse_core.platform.lane_takeover import build_lane_takeover_bundle
from xmuse_core.platform.run_health import build_run_health_model, summarize_run_health
from xmuse_core.structuring.feature_plan_store import (
    FeatureGraphSetStore,
    FeaturePlanStore,
    read_approved_mission_blueprint,
)
from xmuse_core.structuring.feature_summary import summarize_feature_graph_set
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlanProposal,
    FeaturePlanProposalStatus,
    LaneGraph,
    PlanningRun,
    ReviewGodTakeoverAction,
    ReviewTask,
    ReviewVerdict,
)

READ_CONTRACT_TOOL_SCHEMAS = read_tool_inventory.READ_CONTRACT_TOOL_SCHEMAS
build_tool_inventory = read_tool_inventory.build_tool_inventory
build_provider_inventory = provider_read_contracts.build_provider_inventory
build_provider_selection_records = provider_read_contracts.build_provider_selection_records

_EXECUTION_CARD_REF_TYPES = {
    "planning_run",
    "feature_plan",
    "graph_set",
    "runner_evidence",
    "takeover_evidence",
}

def build_lane_contract(
    *,
    lane: dict[str, Any],
    xmuse_root: Path,
) -> dict[str, Any]:
    lane_id = str(lane.get("feature_id") or lane.get("id") or "")
    graph_id = lane.get("graph_id")
    graph_set_id = (
        _find_graph_set_id_by_graph_id(xmuse_root, str(graph_id))
        if isinstance(graph_id, str) and graph_id
        else None
    )
    refs: dict[str, Any] = {
        "gate_report": {"tool": "get_gate_report", "arguments": {"lane_id": lane_id}},
        "diff": {"tool": "get_diff", "arguments": {"lane_id": lane_id}},
        "review": {"tool": "read_review_contract", "arguments": {"lane_id": lane_id}},
        "health": {"tool": "read_health_contract", "arguments": {}},
    }
    if graph_set_id is not None:
        refs["graph_set"] = {
            "tool": "read_graph_set_contract",
            "arguments": {"graph_set_id": graph_set_id},
        }
        refs["graph_set_summary"] = {
            "tool": "read_graph_set_summary",
            "arguments": {"graph_set_id": graph_set_id},
        }
        graph_set = _find_graph_set_by_id(xmuse_root, graph_set_id)
        if graph_set is not None:
            refs["feature_plan"] = {
                "tool": "read_feature_plan_contract",
                "arguments": {"feature_plan_id": graph_set.feature_plan.id},
            }
    return {
        "kind": "lane_contract",
        "read_only": True,
        "lane_id": lane_id,
        "lane": dict(lane),
        "refs": refs,
    }


def build_blueprint_contract(
    *,
    xmuse_root: Path,
    blueprint_ref: str | None = None,
    resolution_id: str | None = None,
) -> dict[str, Any]:
    blueprint, resolution = _load_blueprint_snapshot(
        xmuse_root=xmuse_root,
        blueprint_ref=blueprint_ref,
        resolution_id=resolution_id,
    )
    feature_plan_ids = _feature_plan_ids_for_blueprint(xmuse_root, blueprint.blueprint_ref)
    return {
        "kind": "blueprint_contract",
        "read_only": True,
        "blueprint": blueprint.model_dump(mode="json"),
        "resolution": {
            "id": resolution.id,
            "conversation_id": resolution.conversation_id,
            "version": resolution.version,
            "status": resolution.status.value,
            "goal_summary": resolution.goal_summary,
            "approved_by": list(resolution.approved_by),
            "approval_mode": resolution.approval_mode,
            "created_at": resolution.created_at,
        },
        "counts": {
            "acceptance_criteria": len(blueprint.acceptance_criteria),
            "references": len(blueprint.references),
            "related_feature_plans": len(feature_plan_ids),
        },
        "refs": {
            "feature_plans": [
                {
                    "tool": "read_feature_plan_contract",
                    "arguments": {"feature_plan_id": feature_plan_id},
                }
                for feature_plan_id in feature_plan_ids
            ]
        },
    }


def build_feature_plan_contract(
    *,
    feature_plan_id: str,
    lanes_path: Path,
    xmuse_root: Path,
) -> dict[str, Any]:
    proposal = _feature_plan_store(xmuse_root).get(feature_plan_id)
    if proposal.status != FeaturePlanProposalStatus.APPROVED or proposal.approval is None:
        raise ValueError(f"approved feature plan not found: {feature_plan_id}")
    graph_set = _find_graph_set_by_feature_plan_id(xmuse_root, feature_plan_id)
    if graph_set is None:
        feature_plan = proposal.to_feature_plan(
            resolution_id=proposal.source_blueprint.resolution_id,
            version=proposal.source_blueprint.version,
            plan_id=feature_plan_id,
        )
        progress_counts = {
            "planned": len(feature_plan.features),
            "ready": 0,
            "active": 0,
            "terminal": 0,
            "blocked": 0,
            "unsafe": 0,
        }
        graph_ids = [feature.graph_id for feature in feature_plan.features]
        graph_count = 0
    else:
        feature_plan = graph_set.feature_plan
        progress = summarize_feature_graph_set(
            graph_set,
            terminal_success_feature_ids=set(),
            live_lanes_path=lanes_path,
        )
        progress_counts = progress.counts
        graph_ids = [graph.id for graph in graph_set.graphs]
        graph_count = len(graph_set.graphs)
    refs: dict[str, Any] = {
        "blueprint": {
            "tool": "read_blueprint_contract",
            "arguments": {"blueprint_ref": proposal.source_blueprint.blueprint_ref},
        },
    }
    if graph_set is not None:
        refs["graph_set"] = {
            "tool": "read_graph_set_contract",
            "arguments": {"graph_set_id": graph_set.id},
        }
        refs["graph_set_summary"] = {
            "tool": "read_graph_set_summary",
            "arguments": {"graph_set_id": graph_set.id},
        }
    return {
        "kind": "feature_plan_contract",
        "read_only": True,
        "feature_plan": feature_plan.model_dump(mode="json"),
        "source_blueprint": proposal.source_blueprint.model_dump(mode="json"),
        "approval": (
            proposal.approval.model_dump(mode="json")
            if proposal.approval is not None
            else None
        ),
        "summary": {
            "counts": {
                "features": len(feature_plan.features),
                "graphs": graph_count,
                "dependency_edges": sum(
                    len(feature.dependencies) for feature in feature_plan.features
                ),
            },
            "feature_ids": [feature.feature_id for feature in feature_plan.features],
            "graph_ids": graph_ids,
            "progress": progress_counts,
        },
        "refs": refs,
    }


def build_review_contract(
    *,
    lane_id: str,
    xmuse_root: Path,
) -> dict[str, Any]:
    review_store_path = _review_store_path(xmuse_root)
    tasks = _read_review_tasks_for_lane(review_store_path, lane_id)
    verdicts = _read_review_verdicts_for_lane(review_store_path, lane_id)
    return {
        "kind": "review_contract",
        "read_only": True,
        "lane_id": lane_id,
        "counts": {"tasks": len(tasks), "verdicts": len(verdicts)},
        "latest_task": (
            tasks[-1].model_dump(mode="json")
            if tasks
            else None
        ),
        "latest_verdict": (
            verdicts[-1].model_dump(mode="json")
            if verdicts
            else None
        ),
    }


def build_health_contract(
    *,
    lanes_path: Path,
    xmuse_root: Path,
) -> dict[str, Any]:
    return {
        "kind": "health_contract",
        "read_only": True,
        "run_health": build_run_health_snapshot(
            lanes_path=lanes_path,
            xmuse_root=xmuse_root,
        )["run_health"],
    }


def build_graph_set_contract(
    *,
    graph_set_id: str,
    lanes_path: Path,
    xmuse_root: Path,
) -> dict[str, Any]:
    graph_set = _find_graph_set_by_id(xmuse_root, graph_set_id)
    if graph_set is None:
        raise KeyError(f"feature graph set not found: {graph_set_id}")
    _ensure_graph_set_read_allowed(graph_set, xmuse_root)
    summary = summarize_feature_graph_set(
        graph_set,
        terminal_success_feature_ids=set(),
        live_lanes_path=lanes_path,
    )
    return {
        "kind": "graph_set_contract",
        "read_only": True,
        "graph_set": graph_set.model_dump(mode="json"),
        "summary": {
            "groups": summary.groups,
            "counts": summary.counts,
            "graph_statuses": summary.graph_statuses,
        },
        "refs": {
            "feature_plan": {
                "tool": "read_feature_plan_contract",
                "arguments": {"feature_plan_id": graph_set.feature_plan.id},
            },
            "summary": {
                "tool": "read_graph_set_summary",
                "arguments": {"graph_set_id": graph_set.id},
            },
        },
    }


def build_graph_set_summary(
    *,
    graph_set_id: str,
    lanes_path: Path,
    xmuse_root: Path,
) -> dict[str, Any]:
    graph_set = _find_graph_set_by_id(xmuse_root, graph_set_id)
    if graph_set is None:
        raise KeyError(f"feature graph set not found: {graph_set_id}")
    _ensure_graph_set_read_allowed(graph_set, xmuse_root)
    progress = summarize_feature_graph_set(
        graph_set,
        terminal_success_feature_ids=set(),
        live_lanes_path=lanes_path,
    )
    return {
        "kind": "graph_set_summary",
        "read_only": True,
        "graph_set_id": graph_set.id,
        "summary": {
            "counts": {
                "features": len(graph_set.feature_plan.features),
                "graphs": len(graph_set.graphs),
                **progress.counts,
            },
            "graph_statuses": progress.graph_statuses,
            "features": [
                {
                    "feature_id": feature.feature_id,
                    "title": feature.title,
                    "graph_id": feature.graph_id,
                    "dependencies": list(feature.dependencies),
                    "status": progress.graph_statuses[feature.feature_id],
                    "blueprint_refs": list(feature.blueprint_refs),
                }
                for feature in graph_set.feature_plan.features
            ],
        },
        "refs": {
            "feature_plan": {
                "tool": "read_feature_plan_contract",
                "arguments": {"feature_plan_id": graph_set.feature_plan.id},
            },
            "graph_set": {
                "tool": "read_graph_set_contract",
                "arguments": {"graph_set_id": graph_set.id},
            },
        },
    }


def build_evidence_refs(
    *,
    lane: dict[str, Any],
    all_lanes: list[dict[str, Any]],
    xmuse_root: Path,
) -> dict[str, Any]:
    lane_id = str(lane.get("feature_id") or lane.get("id") or "")
    bundle = build_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    review_contract = build_review_contract(lane_id=lane_id, xmuse_root=xmuse_root)
    review_evidence_refs = _dedupe_refs(
        [
            *_string_list(lane.get("review_evidence_refs")),
            *_string_list((review_contract.get("latest_verdict") or {}).get("evidence_refs")),
        ]
    )
    return {
        "kind": "evidence_refs",
        "read_only": True,
        "lane_id": lane_id,
        "lane_context_ref": bundle.get("lane_context_ref"),
        "primary_evidence_refs": list(bundle.get("primary_evidence_refs", [])),
        "compact_primary_evidence_refs": list(bundle.get("compact_primary_evidence_refs", [])),
        "review_evidence_refs": review_evidence_refs,
        "gate_refs": list(bundle.get("gate_refs", [])),
        "worker_refs": list(bundle.get("worker_refs", [])),
    }


def build_review_verdict(
    *,
    lane_id: str,
    xmuse_root: Path,
) -> dict[str, Any]:
    contract = build_review_contract(lane_id=lane_id, xmuse_root=xmuse_root)
    latest_task = contract.get("latest_task")
    latest_verdict = contract.get("latest_verdict")
    return {
        "kind": "review_verdict",
        "read_only": True,
        "lane_id": lane_id,
        "counts": dict(contract.get("counts", {})),
        "task_id": latest_task.get("task_id") if isinstance(latest_task, dict) else None,
        "verdict_id": latest_verdict.get("id") if isinstance(latest_verdict, dict) else None,
        "latest_task": latest_task,
        "latest_verdict": latest_verdict,
    }


def build_takeover_context(
    *,
    lane: dict[str, Any],
    all_lanes: list[dict[str, Any]],
    xmuse_root: Path,
) -> dict[str, Any]:
    lane_id = str(lane.get("feature_id") or lane.get("id") or "")
    bundle = build_lane_takeover_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    health = summarize_run_health(all_lanes, live_pids=set(), xmuse_root=xmuse_root)
    needed = next(
        (
            item
            for item in health["takeover_context"]["needed_lanes"]
            if item.get("lane_id") == lane_id
        ),
        None,
    )
    return {
        "kind": "takeover_context",
        "read_only": True,
        "lane_id": lane_id,
        "needs_takeover": needed is not None,
        "takeover_reason": needed.get("reason") if isinstance(needed, dict) else None,
        "lane_context_ref": (
            needed.get("lane_context_ref") if isinstance(needed, dict) else None
        ),
        "supported_actions": [action.value for action in ReviewGodTakeoverAction],
        "bundle": asdict(bundle),
        "prompt_context": bundle.as_prompt_context(),
    }


def build_run_health_snapshot(
    *,
    lanes_path: Path,
    xmuse_root: Path,
) -> dict[str, Any]:
    return {
        "kind": "run_health",
        "read_only": True,
        "run_health": build_run_health_model(
            lanes_path,
            live_pids=set(),
            runner_pids=[],
            mcp_pids=[],
            xmuse_root=xmuse_root,
        ),
    }


def build_planning_run_contract(
    *,
    planning_run_id: str,
    xmuse_root: Path,
) -> dict[str, Any]:
    planning_run = _find_planning_run(xmuse_root, planning_run_id)
    if planning_run is None:
        raise KeyError(f"planning run not found: {planning_run_id}")
    refs: dict[str, Any] = {}
    feature_plan_id = _optional_text(planning_run.get("feature_plan_id"))
    graph_set_id = _optional_text(planning_run.get("graph_set_id"))
    if feature_plan_id is not None:
        refs["feature_plan"] = {
            "tool": "read_feature_plan_contract",
            "arguments": {"feature_plan_id": feature_plan_id},
        }
    if graph_set_id is not None:
        refs["graph_set"] = {
            "tool": "read_graph_set_contract",
            "arguments": {"graph_set_id": graph_set_id},
        }
        refs["graph_set_summary"] = {
            "tool": "read_graph_set_summary",
            "arguments": {"graph_set_id": graph_set_id},
        }
    return {
        "kind": "planning_run_contract",
        "read_only": True,
        "planning_run": dict(planning_run),
        "refs": refs,
    }


def build_graph_set_runner_evidence(
    *,
    graph_set_id: str,
    lanes_path: Path,
    xmuse_root: Path,
) -> dict[str, Any]:
    graph_set = _find_graph_set_by_id(xmuse_root, graph_set_id)
    if graph_set is None:
        raise KeyError(f"feature graph set not found: {graph_set_id}")
    all_lanes = _load_live_lanes(lanes_path)
    lanes_by_id = {
        lane_id: lane
        for lane in all_lanes
        if (lane_id := _optional_text(lane.get("feature_id"))) is not None
    }
    lanes_by_graph_local_id = {
        (conversation_id, graph_id, lane_local_id): lane
        for lane in all_lanes
        if (graph_id := _optional_text(lane.get("graph_id"))) is not None
        if (lane_local_id := _optional_text(lane.get("lane_local_id"))) is not None
        for conversation_id in [_optional_text(lane.get("conversation_id"))]
    }
    lane_rows: list[dict[str, Any]] = []
    for graph in graph_set.graphs:
        for lane_node in graph.lanes:
            lane = _find_graph_lane(
                lane_node.feature_id,
                graph,
                lanes_by_id,
                lanes_by_graph_local_id,
            )
            if lane is None:
                continue
            evidence = build_evidence_refs(
                lane=lane,
                all_lanes=all_lanes,
                xmuse_root=xmuse_root,
            )
            lane_rows.append(
                {
                    "lane_id": lane_node.feature_id,
                    "lane_context_ref": evidence.get("lane_context_ref"),
                    "primary_evidence_refs": list(
                        evidence.get("primary_evidence_refs", [])
                    ),
                    "review_evidence_refs": list(
                        evidence.get("review_evidence_refs", [])
                    ),
                    "gate_refs": [
                        {"ref": ref.get("ref")}
                        for ref in evidence.get("gate_refs", [])
                        if isinstance(ref, dict) and _optional_text(ref.get("ref")) is not None
                    ],
                    "worker_refs": [
                        {"ref": ref.get("ref")}
                        for ref in evidence.get("worker_refs", [])
                        if isinstance(ref, dict) and _optional_text(ref.get("ref")) is not None
                    ]
                    + (
                        [{"ref": lane["diff_ref"]}]
                        if _optional_text(lane.get("diff_ref")) is not None
                        else []
                    ),
                }
            )
    return {
        "kind": "graph_set_runner_evidence",
        "read_only": True,
        "graph_set_id": graph_set_id,
        "lane_count": len(lane_rows),
        "lanes": lane_rows,
    }


def build_execution_drilldown_refs(
    *,
    conversation_id: str,
    planning_run_id: str,
    payload: dict[str, Any],
    xmuse_root: Path,
    existing_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    planning_run = _find_planning_run(xmuse_root, planning_run_id)
    lane = _find_live_lane(
        xmuse_root / "feature_lanes.json",
        _optional_text(payload.get("lane_id")),
        conversation_id=conversation_id,
    )
    graph_set_id = _optional_text(payload.get("graph_set_id"))
    if graph_set_id is None and planning_run is not None:
        graph_set_id = _optional_text(planning_run.get("graph_set_id"))
    if graph_set_id is None and lane is not None:
        graph_id = _optional_text(lane.get("graph_id"))
        if graph_id is not None:
            graph_set_id = _find_graph_set_id_by_graph_id(
                xmuse_root,
                graph_id,
                conversation_id=conversation_id,
            )
    feature_plan_id = _optional_text(payload.get("feature_plan_id"))
    if feature_plan_id is None and planning_run is not None:
        feature_plan_id = _optional_text(planning_run.get("feature_plan_id"))
    if feature_plan_id is None and lane is not None:
        feature_plan_id = _optional_text(lane.get("feature_plan_id"))
    if feature_plan_id is None and graph_set_id is not None:
        graph_set = _find_graph_set_by_id(xmuse_root, graph_set_id)
        if graph_set is not None:
            feature_plan_id = graph_set.feature_plan.id

    refs: list[dict[str, str]] = []
    if existing_refs:
        refs.extend(_normalize_http_refs(existing_refs))
    refs.append(
        _http_ref(
            ref_type="planning_run",
            ref_id=planning_run_id,
            label="Planning run",
            href=f"/dashboard/planning-runs/{planning_run_id}",
            api_href=f"/api/planning-runs/{planning_run_id}",
        )
    )
    if feature_plan_id is not None:
        refs.append(
            _http_ref(
                ref_type="feature_plan",
                ref_id=feature_plan_id,
                label="Feature plan",
                href=f"/dashboard/feature-plans/{feature_plan_id}",
                api_href=f"/api/feature-plans/{feature_plan_id}",
            )
        )
    if graph_set_id is not None:
        refs.append(
            _http_ref(
                ref_type="graph_set",
                ref_id=graph_set_id,
                label="Graph set",
                href=f"/dashboard/feature-graph-sets/{graph_set_id}",
                api_href=f"/api/feature-graph-sets/{graph_set_id}",
            )
        )
        refs.append(
            _http_ref(
                ref_type="runner_evidence",
                ref_id=graph_set_id,
                label="Runner evidence",
                href=f"/dashboard/feature-graph-sets/{graph_set_id}#runner-evidence",
                api_href=f"/api/feature-graph-sets/{graph_set_id}/runner-evidence",
            )
        )
    lane_id = _optional_text(payload.get("lane_id"))
    if lane_id is not None:
        scoped_query = f"?conversation_id={quote(conversation_id, safe='')}"
        refs.append(
            _http_ref(
                ref_type="takeover_evidence",
                ref_id=lane_id,
                label="Takeover evidence",
                href=f"/dashboard/lanes/{lane_id}#takeover",
                api_href=f"/api/lanes/{lane_id}/takeover-context{scoped_query}",
            )
        )
    return _dedupe_http_refs(refs)


def _read_review_store_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"review_tasks": [], "review_verdicts": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"review_tasks": [], "review_verdicts": []}
    return payload if isinstance(payload, dict) else {"review_tasks": [], "review_verdicts": []}


def _read_review_tasks_for_lane(path: Path, lane_id: str) -> list[ReviewTask]:
    tasks: list[ReviewTask] = []
    for row in _read_review_store_snapshot(path).get("review_tasks", []):
        if not isinstance(row, dict) or row.get("lane_id") != lane_id:
            continue
        try:
            tasks.append(ReviewTask.model_validate(row))
        except ValueError:
            continue
    return tasks


def _read_review_verdicts_for_lane(path: Path, lane_id: str) -> list[ReviewVerdict]:
    verdicts: list[ReviewVerdict] = []
    for row in _read_review_store_snapshot(path).get("review_verdicts", []):
        if not isinstance(row, dict) or row.get("lane_id") != lane_id:
            continue
        try:
            verdicts.append(ReviewVerdict.model_validate(row))
        except ValueError:
            continue
    return verdicts


def _review_store_path(xmuse_root: Path) -> Path:
    review_plane_path = xmuse_root / "review_plane.json"
    if review_plane_path.exists():
        return review_plane_path
    verdicts_path = xmuse_root / "verdicts.json"
    if verdicts_path.exists():
        return verdicts_path
    return review_plane_path


def _graph_set_store(xmuse_root: Path) -> FeatureGraphSetStore:
    primary_root = xmuse_root / "lane_graphs"
    if primary_root.exists():
        return FeatureGraphSetStore(primary_root)
    return FeatureGraphSetStore(xmuse_root / "graph_sets")


def _feature_plan_store(xmuse_root: Path) -> FeaturePlanStore:
    return FeaturePlanStore(xmuse_root / "feature_plans")


def _load_blueprint_snapshot(
    *,
    xmuse_root: Path,
    blueprint_ref: str | None,
    resolution_id: str | None,
):
    resolved_blueprint_ref = blueprint_ref.strip() if isinstance(blueprint_ref, str) else ""
    resolved_resolution_id = resolution_id.strip() if isinstance(resolution_id, str) else ""
    if not resolved_blueprint_ref and not resolved_resolution_id:
        raise ValueError("blueprint_ref or resolution_id is required")
    if resolved_blueprint_ref and not resolved_resolution_id:
        resolved_resolution_id = _resolution_id_from_blueprint_ref(resolved_blueprint_ref)
    chat_path = xmuse_root / "chat.db"
    if not chat_path.exists():
        raise KeyError(f"approved mission blueprint not found: {resolved_resolution_id}")
    resolution = ChatStore(chat_path).get_resolution(resolved_resolution_id)
    blueprint = read_approved_mission_blueprint(resolution)
    if resolved_blueprint_ref and blueprint.blueprint_ref != resolved_blueprint_ref:
        raise KeyError(f"approved mission blueprint not found: {resolved_blueprint_ref}")
    return blueprint, resolution


def _resolution_id_from_blueprint_ref(blueprint_ref: str) -> str:
    match = re.fullmatch(r"resolution:(.+):mission_blueprint", blueprint_ref.strip())
    if match is None:
        raise ValueError(f"invalid mission blueprint ref: {blueprint_ref}")
    return match.group(1)


def _feature_plan_ids_for_blueprint(xmuse_root: Path, blueprint_ref: str) -> list[str]:
    root = xmuse_root / "feature_plans"
    if not root.exists():
        return []
    matches: list[str] = []
    for path in sorted(root.glob("*.json")):
        try:
            proposal = FeaturePlanProposal.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            proposal.status == FeaturePlanProposalStatus.APPROVED
            and proposal.source_blueprint.blueprint_ref == blueprint_ref
            and _find_graph_set_by_feature_plan_id(xmuse_root, proposal.id) is not None
        ):
            matches.append(proposal.id)
    return matches


def _load_live_lanes(lanes_path: Path) -> list[dict[str, Any]]:
    if not lanes_path.exists():
        return []
    try:
        payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lanes = payload.get("lanes", []) if isinstance(payload, dict) else []
    return [lane for lane in lanes if isinstance(lane, dict)]


def _find_live_lane(
    lanes_path: Path,
    lane_id: str | None,
    *,
    conversation_id: str | None = None,
) -> dict[str, Any] | None:
    if lane_id is None:
        return None
    for lane in _load_live_lanes(lanes_path):
        if _optional_text(lane.get("feature_id")) == lane_id:
            if conversation_id is not None:
                if _optional_text(lane.get("conversation_id")) != conversation_id:
                    continue
            return lane
    return None


def _find_graph_lane(
    lane_local_id: str,
    graph: LaneGraph,
    lanes_by_id: dict[str, dict[str, Any]],
    lanes_by_graph_local_id: dict[tuple[str | None, str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    scoped_lane_id = build_projection_lane_id(
        conversation_id=graph.conversation_id,
        graph_id=graph.id,
        lane_local_id=lane_local_id,
    )
    lane = lanes_by_id.get(scoped_lane_id)
    if lane is not None:
        return lane
    lane = lanes_by_graph_local_id.get((graph.conversation_id, graph.id, lane_local_id))
    if lane is not None:
        return lane
    lane = lanes_by_id.get(lane_local_id)
    if lane is not None:
        lane_graph_id = _optional_text(lane.get("graph_id"))
        lane_conversation_id = _optional_text(lane.get("conversation_id"))
        if (lane_graph_id is None or lane_graph_id == graph.id) and (
            lane_conversation_id is None or lane_conversation_id == graph.conversation_id
        ):
            return lane
    return lanes_by_graph_local_id.get((None, graph.id, lane_local_id))


def _read_planning_runs(xmuse_root: Path) -> list[dict[str, Any]]:
    sqlite_path = xmuse_root / "planning_runs.sqlite3"
    if sqlite_path.exists():
        try:
            with sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    select *
                    from planning_runs
                    order by rerun_sequence asc, created_at asc, planning_run_id asc
                    """
                ).fetchall()
            if rows:
                return [_planning_run_from_sqlite_row(row) for row in rows]
        except (OSError, sqlite3.Error, KeyError, ValueError):
            pass

    path = xmuse_root / "read_models" / "planning_runs.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = payload.get("planning_runs", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _planning_run_from_sqlite_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["audit_refs"] = json.loads(str(payload.pop("audit_refs_json")))
    payload["chat_card_refs"] = json.loads(str(payload.pop("chat_card_refs_json")))
    return PlanningRun.model_validate(payload).model_dump(mode="json")


def _find_planning_run(xmuse_root: Path, planning_run_id: str) -> dict[str, Any] | None:
    for row in _read_planning_runs(xmuse_root):
        if _optional_text(row.get("planning_run_id")) == planning_run_id:
            return row
    return None


def _find_graph_set_by_id(xmuse_root: Path, graph_set_id: str) -> FeatureGraphSet | None:
    for graph_set in _iter_graph_sets(xmuse_root):
        if graph_set.id == graph_set_id:
            return graph_set
    return None


def _find_graph_set_by_feature_plan_id(
    xmuse_root: Path,
    feature_plan_id: str,
) -> FeatureGraphSet | None:
    for graph_set in _iter_graph_sets(xmuse_root):
        if graph_set.feature_plan.id == feature_plan_id:
            return graph_set
    return None


def _ensure_graph_set_read_allowed(graph_set: FeatureGraphSet, xmuse_root: Path) -> None:
    try:
        proposal = _feature_plan_store(xmuse_root).get(graph_set.feature_plan.id)
    except KeyError:
        return
    if proposal.status != FeaturePlanProposalStatus.APPROVED or proposal.approval is None:
        raise ValueError(f"approved feature plan not found: {graph_set.feature_plan.id}")


def _iter_graph_sets(xmuse_root: Path) -> list[FeatureGraphSet]:
    graph_sets: list[FeatureGraphSet] = []
    for root in (xmuse_root / "lane_graphs", xmuse_root / "graph_sets"):
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                graph_sets.append(
                    FeatureGraphSet.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
    return graph_sets


def _find_graph_set_id_by_graph_id(
    xmuse_root: Path,
    graph_id: str,
    *,
    conversation_id: str | None = None,
) -> str | None:
    for graph_set in _iter_graph_sets(xmuse_root):
        if any(
            graph.id == graph_id
            and (conversation_id is None or graph.conversation_id == conversation_id)
            for graph in graph_set.graphs
        ):
            return graph_set.id
    return None


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    return clean or None


def optional_text(value: Any) -> str | None:
    return _optional_text(value)


def build_scoped_query(
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> str:
    params: list[tuple[str, str]] = []
    scoped_conversation_id = _optional_text(conversation_id)
    scoped_workspace_id = _optional_text(workspace_id)
    if scoped_conversation_id is not None:
        params.append(("conversation_id", scoped_conversation_id))
    if scoped_workspace_id is not None:
        params.append(("workspace_id", scoped_workspace_id))
    return f"?{urlencode(params)}" if params else ""


def _http_ref(
    *,
    ref_type: str,
    ref_id: str,
    label: str,
    href: str,
    api_href: str,
) -> dict[str, str]:
    return {
        "ref_type": ref_type,
        "ref_id": ref_id,
        "label": label,
        "href": href,
        "api_href": api_href,
    }


def _normalize_http_refs(refs: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for ref in refs:
        ref_type = _optional_text(ref.get("ref_type")) if isinstance(ref, dict) else None
        ref_id = _optional_text(ref.get("ref_id")) if isinstance(ref, dict) else None
        label = _optional_text(ref.get("label")) if isinstance(ref, dict) else None
        href = _optional_text(ref.get("href")) if isinstance(ref, dict) else None
        api_href = _optional_text(ref.get("api_href")) if isinstance(ref, dict) else None
        if None in {ref_type, ref_id, label, href, api_href}:
            continue
        if ref_type not in _EXECUTION_CARD_REF_TYPES and not (
            ref_type == "resolution" or ref_type == "run_health" or ref_type == "lane"
        ):
            continue
        normalized.append(
            _http_ref(
                ref_type=ref_type,
                ref_id=ref_id,
                label=label,
                href=href,
                api_href=api_href,
            )
        )
    return normalized


def _dedupe_http_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    ordered: list[dict[str, str]] = []
    for ref in refs:
        key = (ref["ref_type"], ref["ref_id"], ref["api_href"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append(ref)
    return ordered


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _dedupe_refs(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        ordered.append(ref)
    return ordered


def build_conversation_inspector_contract(
    conversation_id: str,
    xmuse_root: Path,
) -> dict[str, Any]:
    """Return a read-only conversation inspector contract.

    Delegates to the shared ``build_conversation_inspector_payload`` builder
    and wraps the result with contract discriminators and drill-down refs.
    """
    from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload

    payload = build_conversation_inspector_payload(conversation_id, xmuse_root)
    payload["kind"] = "conversation_inspector"
    payload["read_only"] = True
    payload["refs"] = {
        "self": {
            "api_href": f"/api/dashboard/peer-chat/conversations/{conversation_id}/inspector",
            "label": "Conversation inspector",
        },
        "conversation_detail": {
            "api_href": f"/api/dashboard/peer-chat/conversations/{conversation_id}",
            "label": "Conversation detail",
        },
    }
    return payload
