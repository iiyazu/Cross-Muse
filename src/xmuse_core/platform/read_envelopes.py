from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.platform.read_contracts import build_scoped_query, optional_text
from xmuse_core.platform.run_health import (
    build_run_health_model_from_lanes,
    build_run_health_scope,
    discover_xmuse_runtime_processes,
)
from xmuse_core.platform.state_normalizer import normalize_lane_state


class ApiRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_href: str
    label: str


class WorklistItemDebugRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane: ApiRef
    takeover: ApiRef


class WorklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    lane_local_id: str
    plan_feature_id: str
    feature_label: str
    effective_status: str
    ready: bool
    blocked: bool
    rework: bool
    scoped_dependency_ids: list[str] = Field(default_factory=list)
    priority: int = 0
    provider_selection_ref: ApiRef
    debug_refs: WorklistItemDebugRefs
    prompt_summary: str = ""


class ProviderSelectionRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory: ApiRef
    records: ApiRef


class DegradationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degraded: bool
    stale: bool
    warning_codes: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class RuntimeBackendSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: str
    source_authority: str


class FallbackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    count: int
    lane_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class GraphLineageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degraded: bool
    authoritative_graph_id: str | None = None
    checked_graph_ids: list[str] = Field(default_factory=list)
    mismatched_graph_ids: list[str] = Field(default_factory=list)
    missing_projection_lane_ids: list[str] = Field(default_factory=list)
    unexpected_projection_lane_ids: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)


class DebugDrilldownRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self: ApiRef
    run_health: ApiRef
    lanes: ApiRef


class TuiWorklistEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1"
    read_model_version: str = "1"
    source_authority: str = "feature_lanes_projection"
    projection_revision: int = 0
    generated_at: str
    items: list[WorklistItem] = Field(default_factory=list)
    run_health: dict[str, Any]
    degraded: bool
    stale: bool
    provider_selection_refs: ProviderSelectionRefs
    degradation: DegradationSummary
    runtime_backend: RuntimeBackendSummary
    fallback_reason: str | None = None
    fallback: FallbackSummary
    graph_lineage: GraphLineageSummary
    debug_drilldown_refs: DebugDrilldownRefs
    debug_refs: DebugDrilldownRefs


def build_tui_worklist_envelope(
    root: Path,
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
    process_inventory: dict[str, Any] | None = None,
    configured_backend: str | None = None,
) -> TuiWorklistEnvelope:
    data = _load_lanes_read_only(root)
    projection_revision = data.get("projection_revision", 0)
    if not isinstance(projection_revision, int) or isinstance(projection_revision, bool):
        projection_revision = 0

    lanes = _filter_lanes_by_scope(
        data.get("lanes", []),
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    inventory = process_inventory or discover_xmuse_runtime_processes(xmuse_root=root)
    run_health = build_run_health_model_from_lanes(
        lanes,
        process_inventory=inventory,
        xmuse_root=root,
        scope=build_run_health_scope(
            conversation_id=optional_text(conversation_id),
            workspace_id=optional_text(workspace_id),
        ),
    )
    graph_lineage = _build_graph_lineage_summary(
        root,
        lanes=lanes,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )

    warning_codes = [
        code
        for warning in run_health.get("warnings", [])
        if isinstance(warning, dict)
        if isinstance((code := warning.get("code")), str)
    ]
    warning_codes.extend(graph_lineage.warning_codes)
    warning_codes = _ordered_unique(warning_codes)

    stale = bool(run_health.get("counts", {}).get("stale", 0))
    fallback_lane_ids = [
        lane_id
        for lane_id in run_health.get("groups", {}).get("degraded_fallback", [])
        if isinstance(lane_id, str)
    ]
    fallback_reason = (
        "provider fallback lanes present" if fallback_lane_ids else None
    )
    reasons: list[str] = []
    if graph_lineage.degraded:
        reasons.append("projection lanes do not match graph lineage")
    if fallback_reason is not None:
        reasons.append(fallback_reason)

    degraded = bool(warning_codes or stale or fallback_lane_ids)
    scope_query = build_scoped_query(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    debug_refs = DebugDrilldownRefs(
        self=ApiRef(
            api_href=f"/api/tui/worklist-envelope{scope_query}",
            label="Worklist envelope",
        ),
        run_health=ApiRef(
            api_href=f"/api/run-health{scope_query}",
            label="Run health",
        ),
        lanes=ApiRef(
            api_href="/api/lanes",
            label="Projected lanes",
        ),
    )
    resolved_backend = (
        configured_backend or os.environ.get("XMUSE_RUNTIME_BACKEND", "ray")
    ).strip() or "ray"

    return TuiWorklistEnvelope(
        generated_at=_utc_now(),
        projection_revision=projection_revision,
        items=[
            _compact_tui_item(
                lane,
                conversation_id=conversation_id,
                workspace_id=workspace_id,
            )
            for lane in lanes
        ],
        run_health=run_health,
        degraded=degraded,
        stale=stale,
        provider_selection_refs=ProviderSelectionRefs(
            inventory=ApiRef(
                api_href="/api/tui/provider-inventory",
                label="Provider inventory",
            ),
            records=ApiRef(
                api_href="/api/tui/provider-selection-records",
                label="Provider selection records",
            ),
        ),
        degradation=DegradationSummary(
            degraded=degraded,
            stale=stale,
            warning_codes=warning_codes,
            reasons=reasons,
        ),
        runtime_backend=RuntimeBackendSummary(
            configured=resolved_backend,
            source_authority="runtime_backend_config",
        ),
        fallback_reason=fallback_reason,
        fallback=FallbackSummary(
            active=bool(fallback_lane_ids),
            count=len(fallback_lane_ids),
            lane_ids=fallback_lane_ids,
            reason=fallback_reason,
        ),
        graph_lineage=graph_lineage,
        debug_drilldown_refs=debug_refs,
        debug_refs=debug_refs,
    )


def _compact_tui_item(
    lane: dict[str, Any],
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> WorklistItem:
    normalized = normalize_lane_state(lane)
    lane_id = optional_text(lane.get("feature_id")) or "unknown"
    lane_local_id = optional_text(lane.get("lane_local_id")) or lane_id
    plan_feature_id = optional_text(lane.get("plan_feature_id")) or "?"
    feature_label = optional_text(lane.get("feature_label")) or lane_local_id
    scoped_dependency_ids = lane.get("lane_depends_on_ids")
    if not isinstance(scoped_dependency_ids, list):
        scoped_dependency_ids = lane.get("depends_on")
    if not isinstance(scoped_dependency_ids, list):
        scoped_dependency_ids = []
    priority = lane.get("priority")
    if not isinstance(priority, int) or isinstance(priority, bool):
        priority = 0
    scope_query = build_scoped_query(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    return WorklistItem(
        lane_id=lane_id,
        lane_local_id=lane_local_id,
        plan_feature_id=plan_feature_id,
        feature_label=feature_label,
        effective_status=normalized.normalized_status,
        ready=normalized.normalized_status == "ready",
        blocked=normalized.normalized_status == "awaiting_final_action",
        rework=normalized.normalized_status == "requeued",
        scoped_dependency_ids=[
            str(item) for item in scoped_dependency_ids if isinstance(item, str)
        ],
        priority=priority,
        provider_selection_ref=ApiRef(
            api_href=f"/api/tui/provider-selection-records?lane_id={quote(lane_id, safe='')}",
            label="Provider selection",
        ),
        debug_refs=WorklistItemDebugRefs(
            lane=ApiRef(
                api_href=f"/api/lanes/{quote(lane_id, safe='')}",
                label="Lane detail",
            ),
            takeover=ApiRef(
                api_href=f"/api/lanes/{quote(lane_id, safe='')}/takeover-context{scope_query}",
                label="Takeover context",
            ),
        ),
        prompt_summary=optional_text(lane.get("prompt_summary")) or "",
    )


def _build_graph_lineage_summary(
    root: Path,
    *,
    lanes: list[dict[str, Any]],
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> GraphLineageSummary:
    scoped_scope_id = optional_text(conversation_id) or optional_text(workspace_id)
    lineage_records = _read_lineage_records(root)
    matching_lineage = [
        record
        for record in lineage_records
        if scoped_scope_id is not None
        and optional_text(record.get("spawned_conversation_id")) == scoped_scope_id
    ]
    latest_lineage = (
        sorted(matching_lineage, key=_record_timestamp)[-1]
        if matching_lineage
        else None
    )
    authoritative_graph_id = (
        optional_text(latest_lineage.get("spawned_graph_id"))
        if latest_lineage is not None
        else None
    )
    checked_graph_ids = _ordered_unique(
        [
            *(
                [authoritative_graph_id]
                if authoritative_graph_id is not None
                else []
            ),
            *[
                graph_id
                for lane in lanes
                if isinstance(lane, dict)
                if (graph_id := optional_text(lane.get("graph_id"))) is not None
            ],
        ]
    )
    if not checked_graph_ids:
        return GraphLineageSummary(degraded=False)

    lane_by_id = {
        lane_id: lane
        for lane in lanes
        if isinstance(lane, dict)
        if (lane_id := optional_text(lane.get("feature_id"))) is not None
    }
    mismatched_graph_ids: list[str] = []
    missing_projection_lane_ids: list[str] = []
    unexpected_projection_lane_ids: list[str] = []

    for graph_id in checked_graph_ids:
        graph = _read_lane_graph(root, graph_id)
        if graph is None:
            continue
        expected_ids = set(_lineage_lane_ids(_graph_lane_ids(graph), lane_by_id))
        projected_ids = {
            lane_id
            for lane_id, lane in lane_by_id.items()
            if lane_id in expected_ids
            or optional_text(lane.get("graph_id")) == graph_id
            or optional_text(lane.get("source_lane_id")) in expected_ids
        }
        missing_ids = sorted(expected_ids - projected_ids)
        unexpected_ids = sorted(projected_ids - expected_ids)
        if missing_ids or unexpected_ids:
            mismatched_graph_ids.append(graph_id)
            missing_projection_lane_ids.extend(missing_ids)
            unexpected_projection_lane_ids.extend(unexpected_ids)

    degraded = bool(mismatched_graph_ids)
    return GraphLineageSummary(
        degraded=degraded,
        authoritative_graph_id=authoritative_graph_id,
        checked_graph_ids=checked_graph_ids,
        mismatched_graph_ids=mismatched_graph_ids,
        missing_projection_lane_ids=sorted(set(missing_projection_lane_ids)),
        unexpected_projection_lane_ids=sorted(set(unexpected_projection_lane_ids)),
        warning_codes=(
            ["graph_lineage_projection_mismatch"]
            if degraded
            else []
        ),
    )


def _filter_lanes_by_scope(
    lanes: list[Any],
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    scoped_conversation_id = optional_text(conversation_id)
    scoped_workspace_id = optional_text(workspace_id)
    filtered: list[dict[str, Any]] = []
    for item in lanes:
        if not isinstance(item, dict):
            continue
        if (
            scoped_conversation_id is not None
            and optional_text(item.get("conversation_id")) != scoped_conversation_id
        ):
            continue
        if (
            scoped_workspace_id is not None
            and optional_text(item.get("workspace_id")) != scoped_workspace_id
        ):
            continue
        filtered.append(item)
    return filtered


def _load_lanes_read_only(root: Path) -> dict[str, Any]:
    path = root / "feature_lanes.json"
    if not path.exists():
        return {"lanes": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lanes": []}
    if not isinstance(payload, dict):
        return {"lanes": []}
    lanes = payload.get("lanes", [])
    if not isinstance(lanes, list):
        return {"lanes": []}
    payload["lanes"] = lanes
    return payload


def _read_lineage_records(root: Path) -> list[dict[str, Any]]:
    path = root / "self_evolution" / "lineage.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    records = payload.get("lineage", []) if isinstance(payload, dict) else []
    return [record for record in records if isinstance(record, dict)]


def _read_lane_graph(root: Path, graph_id: str) -> dict[str, Any] | None:
    path = root / "lane_graphs" / f"{graph_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("lanes"), list) else None


def _graph_lane_ids(graph: dict[str, Any]) -> list[str]:
    lane_ids: list[str] = []
    for lane in graph.get("lanes", []):
        if not isinstance(lane, dict):
            continue
        lane_id = optional_text(lane.get("feature_id"))
        if lane_id is not None:
            lane_ids.append(lane_id)
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
            source_lane_id = optional_text(lane.get("source_lane_id"))
            if source_lane_id in seen and lane_id not in seen:
                ordered.append(lane_id)
                seen.add(lane_id)
                changed = True
    return ordered


def _record_timestamp(record: dict[str, Any]) -> datetime:
    created_at = optional_text(record.get("created_at"))
    if created_at is None:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
