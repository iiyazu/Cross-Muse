"""Dashboard API read-model and drill-down helpers."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException, status

from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.chat.health_cards import build_run_health_chat_card
from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.chat.participant_store import ParticipantStore, participant_summary
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform import dashboard_audit_details as _dashboard_audit_details
from xmuse_core.platform import dashboard_graph_authority as _dashboard_graph_authority
from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.projection.syncer import LaneProjectionSyncer
from xmuse_core.platform.read_contracts import (
    build_execution_drilldown_refs,
)
from xmuse_core.platform.read_envelopes import (
    build_tui_worklist_envelope as build_tui_worklist_envelope_model,
)
from xmuse_core.platform.review_rework import classify_review_rework_lane
from xmuse_core.platform.run_health import (
    build_run_health_model,
    build_run_health_model_from_lanes,
    build_run_health_scope,
    discover_xmuse_runtime_processes,
)
from xmuse_core.platform.state_normalizer import (
    normalize_lane_state,
)

_aggregation_summary = _dashboard_graph_authority._aggregation_summary
_build_lineage_graph = _dashboard_graph_authority._build_lineage_graph
_feature_graph_set_summary = _dashboard_graph_authority._feature_graph_set_summary
_find_feature_graph_set_snapshot = (
    _dashboard_graph_authority._find_feature_graph_set_snapshot
)
_graph_authority_state = _dashboard_graph_authority._graph_authority_state
_is_feature_graph_set_snapshot = _dashboard_graph_authority._is_feature_graph_set_snapshot
_is_lane_graph_snapshot = _dashboard_graph_authority._is_lane_graph_snapshot
_iter_feature_graph_set_snapshots = _dashboard_graph_authority._iter_feature_graph_set_snapshots
_latest_aggregation_for_graph = _dashboard_graph_authority._latest_aggregation_for_graph
_read_lineage_records = _dashboard_graph_authority._read_lineage_records
_read_run_aggregations = _dashboard_graph_authority._read_run_aggregations
_read_runtime_snapshot = _dashboard_graph_authority._read_runtime_snapshot
_record_timestamp = _dashboard_graph_authority._record_timestamp
_read_audit_events = _dashboard_audit_details._read_audit_events
_read_errors = _dashboard_audit_details._read_errors
_read_model_entries = _dashboard_audit_details._read_model_entries
_read_state_history = _dashboard_audit_details._read_state_history


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_path(base_dir: Path, name: str) -> Path:
    return base_dir / name


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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _load_lanes(base_dir: Path) -> dict[str, Any]:
    try:
        data = LaneProjectionSyncer(_json_path(base_dir, "feature_lanes.json")).read()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="feature_lanes.json must contain an object")
    lanes = data.setdefault("lanes", [])
    if not isinstance(lanes, list):
        raise HTTPException(status_code=500, detail="feature_lanes.json lanes must be a list")
    return data


def _load_lanes_read_only(base_dir: Path) -> dict[str, Any]:
    data = _read_json(_json_path(base_dir, "feature_lanes.json"), {"lanes": []})
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="feature_lanes.json must contain an object")
    lanes = data.get("lanes", [])
    if not isinstance(lanes, list):
        raise HTTPException(status_code=500, detail="feature_lanes.json lanes must be a list")
    return data


def _dashboard_run_health(
    root: Path,
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    lanes_path = _json_path(root, "feature_lanes.json")
    if not lanes_path.exists():
        return None
    try:
        return _build_dashboard_run_health(
            root,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
    except (JSONDecodeError, OSError, ValueError):
        return None


def _build_dashboard_run_health(
    root: Path,
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    resolved_scope_id = _resolve_run_health_scope_id(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    process_inventory = discover_xmuse_runtime_processes(xmuse_root=root)
    runner_pids = process_inventory["runner_pids"]
    mcp_pids = process_inventory["mcp_pids"]
    lanes_path = _json_path(root, "feature_lanes.json")
    if resolved_scope_id is None:
        return build_run_health_model(
            lanes_path,
            runner_pids=runner_pids,
            mcp_pids=mcp_pids,
            process_inventory=process_inventory,
            xmuse_root=root,
        )

    lanes = _scoped_run_health_lanes(
        root,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    return build_run_health_model_from_lanes(
        lanes,
        runner_pids=runner_pids,
        mcp_pids=mcp_pids,
        process_inventory=process_inventory,
        xmuse_root=root,
        scope=build_run_health_scope(
            conversation_id=_optional_text(conversation_id),
            workspace_id=_optional_text(workspace_id),
        ),
    )


def _resolve_run_health_scope_id(
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> str | None:
    scoped_conversation_id = _optional_text(conversation_id)
    scoped_workspace_id = _optional_text(workspace_id)
    if (
        scoped_conversation_id is not None
        and scoped_workspace_id is not None
        and scoped_conversation_id != scoped_workspace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="conversation_id and workspace_id must match when both are provided",
        )
    return scoped_conversation_id or scoped_workspace_id


def _conversation_scoped_run_health_lanes(
    base_dir: Path,
    conversation_id: str,
) -> list[dict[str, Any]]:
    return PeerChatService(base_dir / "chat.db")._conversation_scoped_lanes(
        conversation_id,
        _load_lanes(base_dir)["lanes"],
    )


def _scoped_run_health_lanes(
    base_dir: Path,
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    scope_id = _resolve_run_health_scope_id(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    if scope_id is not None:
        scoped_lanes = _conversation_scoped_run_health_lanes(base_dir, scope_id)
        if _optional_text(workspace_id) is not None:
            scoped_lanes = [
                *scoped_lanes,
                *_filter_lanes_by_scope(
                    _load_lanes(base_dir)["lanes"],
                    workspace_id=workspace_id,
                ),
            ]
        return _dedupe_lane_rows(scoped_lanes)
    return _filter_lanes_by_scope(
        _load_lanes(base_dir)["lanes"],
        workspace_id=_optional_text(workspace_id),
    )


def _dedupe_lane_rows(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None, str | None]] = set()
    for lane in lanes:
        key = (
            _optional_text(lane.get("feature_id")),
            _optional_text(lane.get("graph_id")),
            _optional_text(lane.get("conversation_id")),
            _optional_text(lane.get("workspace_id")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(lane)
    return deduped


def _lane_with_status(
    lane: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    normalized = dict(lane)
    state = normalize_lane_state(normalized)
    normalized["status"] = state.raw_status
    normalized["effective_status"] = state.normalized_status
    normalized["review_rework_alignment"] = classify_review_rework_lane(
        normalized,
        xmuse_root=base_dir,
    )
    return normalized


def _find_lane(
    data: dict[str, Any],
    feature_id: str,
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    for lane in _filter_lanes_by_scope(
        data.get("lanes", []),
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    ):
        if lane.get("feature_id") == feature_id:
            return lane
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lane not found")


def _filter_lanes_by_conversation(
    lanes: list[Any],
    conversation_id: str | None,
) -> list[dict[str, Any]]:
    scoped_conversation_id = _optional_text(conversation_id)
    if scoped_conversation_id is None:
        return [item for item in lanes if isinstance(item, dict)]
    return [
        item
        for item in lanes
        if isinstance(item, dict)
        and _optional_text(item.get("conversation_id")) == scoped_conversation_id
    ]


def _filter_lanes_by_scope(
    lanes: list[Any],
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    scoped_conversation_id = _optional_text(conversation_id)
    scoped_workspace_id = _optional_text(workspace_id)
    filtered: list[dict[str, Any]] = []
    for item in lanes:
        if not isinstance(item, dict):
            continue
        if (
            scoped_conversation_id is not None
            and _optional_text(item.get("conversation_id")) != scoped_conversation_id
        ):
            continue
        if (
            scoped_workspace_id is not None
            and _optional_text(item.get("workspace_id")) != scoped_workspace_id
        ):
            continue
        filtered.append(item)
    return filtered


def _tui_scope_query(
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


def _compact_tui_item(
    lane: dict[str, Any],
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    lane_id = _optional_text(lane.get("feature_id")) or "unknown"
    lane_local_id = _optional_text(lane.get("lane_local_id")) or lane_id
    plan_feature_id = _first_text(lane, ("plan_feature_id", "feature_plan_feature_id"))
    feature_label = (
        _first_text(lane, ("feature_label", "feature_group"))
        or plan_feature_id
        or lane_local_id
        or lane_id
    )
    normalized = normalize_lane_state(lane)
    scoped_dependency_ids = lane.get("lane_depends_on_ids")
    if not isinstance(scoped_dependency_ids, list):
        scoped_dependency_ids = lane.get("depends_on")
    if not isinstance(scoped_dependency_ids, list):
        scoped_dependency_ids = []
    priority = lane.get("priority")
    if not isinstance(priority, int) or isinstance(priority, bool):
        priority = 0
    takeover_query = _tui_scope_query(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    return {
        "lane_id": lane_id,
        "lane_local_id": lane_local_id,
        "plan_feature_id": plan_feature_id,
        "feature_label": feature_label,
        "effective_status": normalized.normalized_status,
        "ready": normalized.normalized_status == "ready",
        "blocked": normalized.normalized_status == "awaiting_final_action",
        "rework": normalized.normalized_status == "requeued",
        "scoped_dependency_ids": [
            str(item) for item in scoped_dependency_ids if isinstance(item, str)
        ],
        "priority": priority,
        "provider_selection_ref": {
            "api_href": (
                f"/api/tui/provider-selection-records?lane_id={quote(lane_id, safe='')}"
            ),
            "label": "Provider selection",
        },
        "debug_refs": {
            "lane": {
                "api_href": f"/api/lanes/{quote(lane_id, safe='')}",
                "label": "Lane detail",
            },
            "takeover": {
                "api_href": (
                    f"/api/lanes/{quote(lane_id, safe='')}/takeover-context{takeover_query}"
                ),
                "label": "Takeover context",
            },
        },
        "prompt_summary": _optional_text(lane.get("prompt_summary")) or "",
    }


def _build_tui_worklist_envelope(
    root: Path,
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    _resolve_run_health_scope_id(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
    return build_tui_worklist_envelope_model(
        root,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        process_inventory=discover_xmuse_runtime_processes(xmuse_root=root),
    ).model_dump(mode="json")


def _log_entries(base_dir: Path, feature_id: str) -> list[dict[str, str]]:
    logs_dir = base_dir / "logs"
    if not logs_dir.exists():
        return []

    entries: list[dict[str, str]] = []
    for path in sorted(p for p in logs_dir.rglob("*") if p.is_file()):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if feature_id not in path.name and feature_id not in content:
            continue
        entries.append(
            {
                "path": path.relative_to(base_dir).as_posix(),
                "content": content,
            }
        )
    return entries


def _read_sessions(base_dir: Path) -> list[Any]:
    data = _read_json(_json_path(base_dir, "active_sessions.json"), {"sessions": []})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        sessions = data.get("sessions", [])
        if isinstance(sessions, list):
            return sessions
        if isinstance(sessions, dict):
            normalized: list[Any] = []
            for feature_id, session in sessions.items():
                if isinstance(session, dict):
                    normalized.append({"feature_id": feature_id, **session})
            return normalized
        return []
    return []


def _sessions_by_conversation(base_dir: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in _read_sessions(base_dir):
        if not isinstance(raw, dict):
            continue
        conversation_id = raw.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            continue
        session = dict(raw)
        god_session_id = session.get("god_session_id") or session.get("session_id")
        if isinstance(god_session_id, str) and god_session_id:
            session.setdefault("href", f"/dashboard/peer-chat/sessions/{god_session_id}")
            session.setdefault(
                "api_href",
                f"/api/dashboard/peer-chat/sessions/{god_session_id}",
            )
        grouped.setdefault(conversation_id, []).append(session)
    return grouped


def _session_identifier(session: dict[str, Any]) -> str | None:
    for field in ("god_session_id", "session_id"):
        value = session.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _find_peer_session(base_dir: Path, god_session_id: str) -> dict[str, Any] | None:
    for raw in _read_sessions(base_dir):
        if not isinstance(raw, dict):
            continue
        if _session_identifier(raw) == god_session_id:
            return dict(raw)
    return None


def _compact_peer_session(session: dict[str, Any]) -> dict[str, Any]:
    god_session_id = _session_identifier(session)
    compact: dict[str, Any] = {}
    for key in (
        "god_session_id",
        "session_id",
        "conversation_id",
        "participant_id",
        "role",
        "runtime",
        "model",
        "status",
        "feature_scope_id",
        "assignment_feature_id",
    ):
        value = session.get(key)
        if isinstance(value, str) and value:
            compact[key] = value
    pid = session.get("pid")
    if isinstance(pid, int):
        compact["pid"] = pid
    if god_session_id is not None:
        compact.setdefault("god_session_id", god_session_id)
        compact["href"] = f"/dashboard/peer-chat/sessions/{god_session_id}"
        compact["api_href"] = f"/api/dashboard/peer-chat/sessions/{god_session_id}"
    return compact


def _conversation_summary(base_dir: Path, conversation_id: str | None) -> dict[str, Any] | None:
    if conversation_id is None:
        return None
    for conversation in ChatStore(base_dir / "chat.db").list_conversations():
        if conversation.id == conversation_id:
            return conversation.model_dump(mode="json")
    return None


def _participant_detail(base_dir: Path, participant_id: str | None) -> dict[str, Any] | None:
    if participant_id is None:
        return None
    try:
        participant = ParticipantStore(base_dir / "chat.db").get(participant_id)
    except KeyError:
        return None
    return {
        **participant_summary(participant),
        "conversation_id": participant.conversation_id,
    }


_PEER_REQUEST_SPECS: tuple[dict[str, Any], ...] = (
    {
        "message_type": "review",
        "participant_field": "review_peer_id",
        "request_field": "peer_request_id",
        "delivery_mode_field": "peer_delivery_mode",
        "routing_mode_field": "peer_routing_mode",
        "degraded_reason_fields": ("peer_degraded_reason", "failure_reason"),
    },
    {
        "message_type": "execute",
        "participant_field": "execute_peer_id",
        "request_field": "execute_peer_request_id",
        "delivery_mode_field": "execute_peer_delivery_mode",
        "routing_mode_field": "execute_peer_routing_mode",
        "degraded_reason_fields": (
            "execute_peer_degraded_reason",
            "persistent_execute_degraded_reason",
            "failure_reason",
        ),
    },
)


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_text(data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = _optional_text(data.get(field))
        if value is not None:
            return value
    return None


def _lane_feature_ref(lane: dict[str, Any]) -> str | None:
    for field in (
        "feature_plan_feature_id",
        "plan_feature_id",
        "feature_scope_id",
        "feature_id",
    ):
        value = _optional_text(lane.get(field))
        if value is not None:
            return value
    return None


def _find_peer_lane(
    base_dir: Path,
    request_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    data = _read_json(_json_path(base_dir, "feature_lanes.json"), {"lanes": []})
    lanes = data.get("lanes", []) if isinstance(data, dict) else []
    if not isinstance(lanes, list):
        return None
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        for spec in _PEER_REQUEST_SPECS:
            if _optional_text(lane.get(spec["request_field"])) == request_id:
                return lane, spec
    return None


def _find_peer_card(
    base_dir: Path,
    request_id: str,
    *,
    card_type: str,
) -> dict[str, Any] | None:
    service = PeerChatService(base_dir / "chat.db")
    for conversation in ChatStore(base_dir / "chat.db").list_conversations():
        timeline = service.list_conversation_timeline(conversation.id)
        for card in timeline["cards"]:
            if card.get("card_type") == card_type and card.get("source_id") == request_id:
                return card
    return None


def _find_conversation_card(
    base_dir: Path,
    conversation_id: str,
    *,
    card_type: str,
    source_id: str,
) -> dict[str, Any] | None:
    timeline = PeerChatService(base_dir / "chat.db").list_conversation_timeline(conversation_id)
    for card in timeline["cards"]:
        if card.get("card_type") == card_type and card.get("source_id") == source_id:
            return card
    return None


def _compact_peer_lane(lane: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_lane_state(lane)
    compact: dict[str, Any] = {
        "feature_id": lane.get("feature_id"),
        "status": normalized.raw_status,
        "effective_status": normalized.normalized_status,
    }
    for source_key, target_key in (
        ("conversation_id", "conversation_id"),
        ("graph_id", "graph_id"),
    ):
        value = _optional_text(lane.get(source_key))
        if value is not None:
            compact[target_key] = value
    feature_ref = _lane_feature_ref(lane)
    if feature_ref is not None:
        compact["feature_ref"] = feature_ref
    return compact


def _session_for_peer_request(
    base_dir: Path,
    *,
    conversation_id: str | None,
    participant_id: str | None,
    god_session_id: str | None,
) -> dict[str, Any] | None:
    for raw in _read_sessions(base_dir):
        if not isinstance(raw, dict):
            continue
        if god_session_id is not None and _session_identifier(raw) == god_session_id:
            return dict(raw)
        if (
            conversation_id is not None
            and participant_id is not None
            and raw.get("conversation_id") == conversation_id
            and raw.get("participant_id") == participant_id
        ):
            return dict(raw)
    return None


def _peer_request_context(base_dir: Path, request_id: str) -> dict[str, Any]:
    request_card = _find_peer_card(base_dir, request_id, card_type="peer_request")
    if request_card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="peer request not found",
        )
    matched = _find_peer_lane(base_dir, request_id)
    lane: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None
    if matched is not None:
        lane, spec = matched
    metadata = request_card.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    conversation_id = _optional_text(request_card.get("conversation_id"))
    participant_id = _optional_text(metadata.get("participant_id"))
    god_session_id = _optional_text(metadata.get("god_session_id"))
    session = _session_for_peer_request(
        base_dir,
        conversation_id=conversation_id,
        participant_id=participant_id,
        god_session_id=god_session_id,
    )
    return {
        "card": request_card,
        "metadata": metadata,
        "lane": lane,
        "spec": spec,
        "conversation_id": conversation_id,
        "participant_id": participant_id,
        "god_session_id": god_session_id,
        "session": session,
    }


def _peer_request_detail(base_dir: Path, request_id: str) -> dict[str, Any]:
    context = _peer_request_context(base_dir, request_id)
    card = context["card"]
    metadata = context["metadata"]
    lane = context["lane"]
    session = context["session"]
    god_session_id = context["god_session_id"]
    request: dict[str, Any] = {
        "request_id": request_id,
        "message_type": metadata.get("message_type"),
        "status": card.get("status"),
        "conversation_id": context["conversation_id"],
        "participant_id": context["participant_id"],
        "god_session_id": god_session_id,
        "lane_id": metadata.get("lane_id"),
        "feature_id": metadata.get("feature_id"),
        "graph_id": metadata.get("graph_id"),
        "dashboard_href": card.get("href"),
        "api_href": card.get("api_href"),
        "result_api_href": f"/api/peer-requests/{request_id}/result",
    }
    if god_session_id is not None:
        request["session_api_href"] = f"/api/dashboard/peer-chat/sessions/{god_session_id}"
    return {
        "request": request,
        "card": card,
        "lane": _compact_peer_lane(lane) if isinstance(lane, dict) else None,
        "peer": _participant_detail(base_dir, context["participant_id"]),
        "session": _compact_peer_session(session) if isinstance(session, dict) else None,
    }


def _peer_result_detail(base_dir: Path, request_id: str) -> dict[str, Any]:
    result_card = _find_peer_card(base_dir, request_id, card_type="peer_result")
    if result_card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="peer result not found",
        )
    context = _peer_request_context(base_dir, request_id)
    metadata = result_card.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    lane = context["lane"]
    session = context["session"]
    result = {
        "request_id": request_id,
        "message_type": metadata.get("message_type"),
        "status": result_card.get("status"),
        "result_status": metadata.get("result_status"),
        "reason": metadata.get("reason"),
        "conversation_id": context["conversation_id"],
        "participant_id": context["participant_id"],
        "god_session_id": context["god_session_id"],
        "lane_id": metadata.get("lane_id"),
        "feature_id": metadata.get("feature_id"),
        "graph_id": metadata.get("graph_id"),
        "request_api_href": f"/api/peer-requests/{request_id}",
    }
    return {
        "result": result,
        "card": result_card,
        "lane": _compact_peer_lane(lane) if isinstance(lane, dict) else None,
        "peer": _participant_detail(base_dir, context["participant_id"]),
        "session": _compact_peer_session(session) if isinstance(session, dict) else None,
    }


def _lane_graph_card_detail(
    base_dir: Path,
    conversation_id: str,
    graph_id: str,
) -> dict[str, Any]:
    card = _find_conversation_card(
        base_dir,
        conversation_id,
        card_type="lane_graph",
        source_id=graph_id,
    )
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="lane graph card not found",
        )
    path = base_dir / "lane_graphs" / f"{graph_id}.json"
    data = _read_json(path, {})
    if not _is_lane_graph_snapshot(data) or data.get("conversation_id") != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="lane graph not found",
        )
    lanes = data.get("lanes", [])
    graph = {
        "id": graph_id,
        "conversation_id": conversation_id,
        "status": data.get("status", "planned"),
        "resolution_id": data.get("resolution_id"),
        "version": data.get("version"),
        "lane_count": len(lanes) if isinstance(lanes, list) else 0,
        "dashboard_href": f"/dashboard/lane-graphs/{graph_id}",
        "raw_api_href": f"/api/lane-graphs/{graph_id}",
    }
    return {"card": card, "graph": graph}


def _feature_graph_set_card_detail(
    base_dir: Path,
    conversation_id: str,
    graph_set_id: str,
) -> dict[str, Any]:
    card = _find_conversation_card(
        base_dir,
        conversation_id,
        card_type="feature_graph_set",
        source_id=graph_set_id,
    )
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="feature graph set card not found",
        )
    path = base_dir / "lane_graphs" / f"{graph_set_id}.json"
    data = _read_json(path, {})
    if not _is_feature_graph_set_snapshot(data):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="feature graph set not found",
        )
    summary = _feature_graph_set_summary(data, path)
    if summary.get("conversation_id") != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="feature graph set not found",
        )
    counts = summary.get("counts", {})
    graph_set = {
        "id": graph_set_id,
        "conversation_id": conversation_id,
        "feature_plan_id": summary.get("feature_plan_id"),
        "resolution_id": summary.get("resolution_id"),
        "version": summary.get("version"),
        "feature_count": counts.get("features", 0),
        "lane_graph_count": counts.get("lane_graphs", 0),
        "status": summary.get("status"),
        "dashboard_href": f"/dashboard/feature-graph-sets/{graph_set_id}",
        "raw_api_href": f"/api/feature-graph-sets/{graph_set_id}",
    }
    return {"card": card, "graph_set": graph_set}


def _conversation_run_health_detail(base_dir: Path, conversation_id: str) -> dict[str, Any]:
    card = _find_conversation_card(
        base_dir,
        conversation_id,
        card_type="health_summary",
        source_id="run_health",
    )
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run health card not found",
        )
    process_inventory = discover_xmuse_runtime_processes(xmuse_root=base_dir)
    runner_pids = process_inventory["runner_pids"]
    mcp_pids = process_inventory["mcp_pids"]
    lanes = _conversation_scoped_run_health_lanes(
        base_dir,
        conversation_id,
    )
    run_health = build_run_health_model_from_lanes(
        lanes,
        runner_pids=runner_pids,
        mcp_pids=mcp_pids,
        process_inventory=process_inventory,
        xmuse_root=base_dir,
        scope=build_run_health_scope(
            conversation_id=conversation_id,
            workspace_id=conversation_id,
        ),
    )
    compact_card = build_run_health_chat_card(
        conversation_id,
        run_health,
        created_at=str(card.get("created_at") or utc_now()),
        href=f"/dashboard/peer-chat/conversations/{conversation_id}#run-health",
        api_href=f"/api/dashboard/peer-chat/conversations/{conversation_id}/run-health",
    ).model_dump(mode="json")
    return {
        "conversation_id": conversation_id,
        "card": compact_card,
        "run_health": run_health,
    }


def _conversation_runtime_timeline_detail(
    base_dir: Path,
    conversation_id: str,
) -> dict[str, Any]:
    try:
        inspector = build_conversation_inspector_payload(conversation_id, base_dir)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    try:
        bootstrap = PeerChatService(base_dir / "chat.db").get_bootstrap_status(
            conversation_id
        )
    except Exception:
        bootstrap = None
    api_href = (
        f"/api/dashboard/peer-chat/conversations/{conversation_id}/runtime-timeline"
    )
    href = f"/dashboard/peer-chat/conversations/{conversation_id}#runtime-timeline"
    events = _runtime_timeline_events(
        conversation_id=conversation_id,
        inspector=inspector,
        bootstrap=bootstrap,
        api_href=api_href,
        href=href,
    )
    return {
        "conversation_id": conversation_id,
        "source_authority": "chat_inspector",
        "api_href": api_href,
        "href": href,
        "events": events,
        "counts": _runtime_timeline_counts(events),
    }


def _runtime_timeline_events(
    *,
    conversation_id: str,
    inspector: dict[str, Any],
    bootstrap: dict[str, Any] | None,
    api_href: str,
    href: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if isinstance(bootstrap, dict):
        status = str(bootstrap.get("status") or "").strip()
        if status:
            preset = str(bootstrap.get("preset_id") or "unknown").strip() or "unknown"
            plan = _string_items(bootstrap.get("participant_plan"))
            team = "/".join(plan) if plan else "pending"
            events.append(
                _runtime_event(
                    conversation_id=conversation_id,
                    event_type="bootstrap",
                    event_id=str(
                        bootstrap.get("draft_id")
                        or bootstrap.get("proposal_id")
                        or conversation_id
                    ),
                    title="Bootstrap",
                    summary=f"{status} preset={preset} team={team}",
                    status=status,
                    created_at=_row_timestamp(bootstrap, "updated_at", "created_at"),
                    api_href=api_href,
                    href=href,
                    refs={"preset_id": preset, "participant_plan": plan},
                )
            )

    collaboration = inspector.get("collaboration")
    if isinstance(collaboration, dict):
        run = _latest_dict(collaboration.get("runs"))
        if run is not None:
            run_id = str(run.get("run_id") or "?")
            status = str(run.get("status") or "?")
            mode = str(run.get("orchestration_mode") or "?")
            targets = _string_items(run.get("targets"))
            target_text = ", ".join(targets) if targets else "none"
            responses = int(run.get("response_count") or 0)
            blocker_count = int(run.get("blocker_count") or 0)
            events.append(
                _runtime_event(
                    conversation_id=conversation_id,
                    event_type="collaboration_run",
                    event_id=run_id,
                    title="Discussion run",
                    summary=(
                        f"{run_id} {status} {mode} targets={target_text} "
                        f"responses={responses} blockers={blocker_count}"
                    ),
                    status=status,
                    created_at=_row_timestamp(run, "updated_at", "created_at"),
                    api_href=api_href,
                    href=href,
                    refs={"run_id": run_id, "targets": targets, "orchestration_mode": mode},
                )
            )

    blockers = inspector.get("blockers")
    if isinstance(blockers, dict):
        blocker = _latest_dict(blockers.get("items"))
        if blocker is not None:
            active = bool(blocker.get("active"))
            event_type = "blocker_active" if active else "blocker_resolved"
            blocker_id = str(blocker.get("blocker_id") or "?")
            severity = str(blocker.get("severity") or "?")
            issuer = str(blocker.get("issuer") or "?")
            reason = str(blocker.get("reason") or "").strip()
            status = "active" if active else "resolved"
            summary = f"{blocker_id} {severity} {issuer} {status}"
            if reason:
                summary = f"{summary}: {reason}"
            events.append(
                _runtime_event(
                    conversation_id=conversation_id,
                    event_type=event_type,
                    event_id=blocker_id,
                    title="Blocker",
                    summary=summary,
                    status=status,
                    created_at=_row_timestamp(blocker, "resolved_at", "created_at"),
                    api_href=api_href,
                    href=href,
                    refs={
                        "blocker_id": blocker_id,
                        "run_id": blocker.get("run_id"),
                        "blocks_dispatch": bool(blocker.get("blocks_dispatch")),
                    },
                )
            )

    if isinstance(collaboration, dict):
        for gate in _dict_items(collaboration.get("dispatch_gates")):
            event_id = str(gate.get("event_id") or "?")
            run_id = str(gate.get("run_id") or "?")
            decision = str(gate.get("decision") or "?")
            proposal_ref = str(gate.get("proposal_ref") or "").strip()
            artifact_ref = str(gate.get("artifact_ref") or "").strip()
            suffix = " ".join(ref for ref in (proposal_ref, artifact_ref) if ref)
            summary = f"{event_id} {run_id} {decision}"
            if suffix:
                summary = f"{summary} {suffix}"
            events.append(
                _runtime_event(
                    conversation_id=conversation_id,
                    event_type="dispatch_gate",
                    event_id=event_id,
                    title="Dispatch gate",
                    summary=summary,
                    status=decision,
                    created_at=_row_timestamp(gate, "created_at", "updated_at"),
                    api_href=api_href,
                    href=href,
                    refs={
                        "run_id": run_id,
                        "proposal_ref": proposal_ref,
                        "artifact_ref": artifact_ref,
                    },
                )
            )

    queue = inspector.get("dispatch_queue")
    latest_dispatch = (
        _latest_dict(queue.get("entries"), newest_first=True)
        if isinstance(queue, dict)
        else None
    )
    if latest_dispatch is not None:
        entry_id = str(latest_dispatch.get("entry_id") or "?")
        status = str(latest_dispatch.get("status") or "?")
        source = str(latest_dispatch.get("source") or "?")
        target = str(latest_dispatch.get("target") or "?")
        auto = " auto" if bool(latest_dispatch.get("auto_execute")) else ""
        provider_ref = str(
            latest_dispatch.get("provider_run_ref")
            or latest_dispatch.get("failure_reason")
            or ""
        ).strip()
        summary = f"{entry_id} {status} {source} target={target}{auto}"
        if provider_ref:
            summary = f"{summary} {provider_ref}"
        events.append(
            _runtime_event(
                conversation_id=conversation_id,
                event_type="dispatch_queue",
                event_id=entry_id,
                title="Dispatch queue",
                summary=summary,
                status=status,
                created_at=_row_timestamp(
                    latest_dispatch,
                    "updated_at",
                    "completed_at",
                    "created_at",
                ),
                api_href=api_href,
                href=href,
                refs={
                    "entry_id": entry_id,
                    "target": target,
                    "dispatch_evidence": latest_dispatch.get("dispatch_evidence"),
                },
            )
        )
        writeback = _dispatch_writeback(inspector, latest_dispatch)
        if writeback is not None:
            inbox_id = str(writeback.get("inbox_item_id") or "")
            mode = str(writeback.get("delivery_mode") or "unknown")
            role = str(writeback.get("target_role") or "?")
            reason = str(writeback.get("degraded_reason") or "").strip()
            status = mode if not reason else "degraded"
            summary = f"{mode} {role} evidence={inbox_id}"
            if reason:
                summary = f"{summary} degraded={reason}"
            events.append(
                _runtime_event(
                    conversation_id=conversation_id,
                    event_type="provider_writeback",
                    event_id=inbox_id or entry_id,
                    title="Provider writeback",
                    summary=summary,
                    status=status,
                    created_at=_row_timestamp(writeback, "writeback_at", "created_at"),
                    api_href=api_href,
                    href=href,
                    refs={
                        "inbox_item_id": inbox_id,
                        "dispatch_queue_entry_id": entry_id,
                    },
                )
            )

    order = {
        "bootstrap": 0,
        "collaboration_run": 1,
        "blocker_active": 2,
        "blocker_resolved": 2,
        "dispatch_gate": 3,
        "dispatch_queue": 4,
        "provider_writeback": 5,
    }
    return sorted(
        events,
        key=lambda event: (
            order.get(str(event.get("event_type")), 99),
            str(event.get("created_at") or ""),
            str(event.get("event_id") or ""),
        ),
    )


def _runtime_event(
    *,
    conversation_id: str,
    event_type: str,
    event_id: str,
    title: str,
    summary: str,
    status: str,
    created_at: Any,
    api_href: str,
    href: str,
    refs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "conversation_id": conversation_id,
        "event_type": event_type,
        "title": title,
        "summary": summary,
        "status": status,
        "created_at": created_at,
        "href": href,
        "api_href": api_href,
        "refs": refs,
    }


def _runtime_timeline_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type") or "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _latest_dict(value: Any, *, newest_first: bool = False) -> dict[str, Any] | None:
    rows = _dict_items(value)
    if not rows:
        return None
    index_multiplier = -1 if newest_first else 1
    return max(
        enumerate(rows),
        key=lambda item: (
            str(
                _row_timestamp(
                    item[1],
                    "updated_at",
                    "completed_at",
                    "resolved_at",
                    "created_at",
                )
                or ""
            ),
            item[0] * index_multiplier,
        ),
    )[1]


def _row_timestamp(row: dict[str, Any], *fields: str) -> Any:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value):
            return value
    return None


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dispatch_writeback(
    inspector: dict[str, Any],
    dispatch_entry: dict[str, Any],
) -> dict[str, Any] | None:
    inbox_id = _dispatch_writeback_inbox_id(dispatch_entry)
    if inbox_id is None:
        return None
    latency = inspector.get("peer_latency")
    turns = latency.get("recent_turns") if isinstance(latency, dict) else None
    for turn in _dict_items(turns):
        if str(turn.get("inbox_item_id") or "") == inbox_id:
            return turn
    return None


def _dispatch_writeback_inbox_id(dispatch_entry: dict[str, Any]) -> str | None:
    evidence = str(dispatch_entry.get("dispatch_evidence") or "")
    prefix = "mcp_writeback:"
    if not evidence.startswith(prefix):
        return None
    inbox_id = evidence.removeprefix(prefix).strip()
    return inbox_id or None


def _execution_card_detail(
    base_dir: Path,
    conversation_id: str,
    intent_id: str,
) -> dict[str, Any]:
    emitter = ChatExecutionCardEmitter(base_dir)
    try:
        intent = emitter.get_intent(conversation_id, intent_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="execution card not found",
        ) from exc
    refs = build_execution_drilldown_refs(
        conversation_id=conversation_id,
        planning_run_id=intent.planning_run_id,
        payload=dict(intent.payload),
        xmuse_root=base_dir,
        existing_refs=[ref.model_dump(mode="json") for ref in intent.drilldown_refs],
    )
    card = intent.to_chat_card().model_dump(mode="json")
    metadata = card.get("metadata")
    if isinstance(metadata, dict):
        metadata["drilldown_refs"] = refs
    return {
        "card": card,
        "intent": intent.model_dump(mode="json"),
        "refs": refs,
    }


def _duration_seconds(lane: dict[str, Any]) -> float | None:
    duration = lane.get("duration_seconds")
    if isinstance(duration, int | float):
        return float(duration)

    started = _parse_timestamp(lane.get("started_at"))
    completed = _parse_timestamp(lane.get("completed_at") or lane.get("finished_at"))
    if started is None or completed is None:
        return None
    return max(0.0, (completed - started).total_seconds())


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_self_evolution_entries(base_dir: Path, file_name: str, key: str) -> list[Any]:
    data = _read_json(base_dir / "self_evolution" / file_name, {key: []})
    if not isinstance(data, dict):
        return []
    entries = data.get(key, [])
    return entries if isinstance(entries, list) else []


class FinalActionApprovalError(ValueError):
    pass


def _resolve_pending_final_action(
    base_dir: Path,
    feature_id: str,
    *,
    lane: dict[str, Any] | None = None,
) -> tuple[str, str, str | None] | None:
    store = FinalActionGateStore(base_dir / "final_actions.json")
    for hold in store.list_actions():
        if hold.lane_id == feature_id and hold.status == "pending":
            action = hold.action
            if action == "merge":
                _record_final_action_import(base_dir, hold, lane or {})
                store.resolve(
                    hold.id,
                    status="approved",
                    resolved_by="human",
                    github_gate_gap_ref="github_gate_unverified",
                )
                return "blocked", hold.id, "github_gate_unverified"
            store.resolve(hold.id, status="approved", resolved_by="human")
            if action == "terminate":
                return "failed", hold.id, None
            return None
    return None


def _record_final_action_import(
    base_dir: Path,
    hold: Any,
    lane: dict[str, Any],
) -> None:
    target_worktree = _optional_path(lane.get("final_action_import_target"))
    if target_worktree is None:
        return

    changed_files = _safe_changed_files(lane.get("changed_files"))
    source_worktree = _optional_path(lane.get("worktree"))
    import_decision = _resolve_final_action_import_decision(
        base_dir,
        hold=hold,
        lane=lane,
        target_worktree=target_worktree,
    )
    if source_worktree is None or not source_worktree.exists():
        raise FinalActionApprovalError("final_action_import_source_worktree_missing")
    if not target_worktree.exists() or not target_worktree.is_dir():
        raise FinalActionApprovalError("final_action_import_target_missing")
    dirty_conflicts = _target_dirty_conflicting_paths(target_worktree, changed_files)
    if dirty_conflicts:
        raise FinalActionApprovalError(
            "final_action_import_target_dirty_conflict: " + ", ".join(dirty_conflicts)
        )

    import_plan = _preflight_final_action_import_files(
        source_worktree,
        target_worktree,
        changed_files,
    )
    imported_files: list[dict[str, Any]] = []
    for changed_file, source_path, target_path in import_plan:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        imported_files.append(
            {
                "path": changed_file,
                "source_sha256": _sha256_file(source_path),
                "target_sha256": _sha256_file(target_path),
                "bytes": target_path.stat().st_size,
            }
        )

    _append_final_action_import_record(
        base_dir,
        {
            "id": f"import-{hold.id}",
            "hold_id": hold.id,
            "lane_id": hold.lane_id,
            "verdict_id": hold.verdict_id,
            "action": hold.action,
            "status": "applied",
            "created_at": utc_now(),
            "source_worktree": str(source_worktree),
            "target_worktree": str(target_worktree),
            "changed_files": changed_files,
            "imported_files": imported_files,
            "import_decision": import_decision,
            "proof_level": "local_final_action_import",
            "forbidden_claims": [
                "github_server_merge",
                "github_server_truth",
                "source_root_merge_unless_target_worktree_is_source_root",
                "full_xmuse_closure",
            ],
        },
    )


def _resolve_final_action_import_decision(
    base_dir: Path,
    *,
    hold: Any,
    lane: dict[str, Any],
    target_worktree: Path,
) -> dict[str, Any]:
    data = _read_json(_json_path(base_dir, "final_action_import_decisions.json"), {})
    decisions = data.get("decisions", [])
    if not isinstance(decisions, list):
        raise FinalActionApprovalError("final_action_import_decisions_malformed")

    lane_id = str(hold.lane_id)
    hold_id = str(hold.id)
    target = str(target_worktree)
    candidates = [
        decision
        for decision in decisions
        if isinstance(decision, dict)
        and decision.get("lane_id") == lane_id
        and decision.get("target_worktree") == target
        and decision.get("decision") == "apply_to_target_worktree"
        and decision.get("status", "approved") == "approved"
        and _import_decision_matches_hold(decision, hold_id=hold_id)
    ]
    if not candidates:
        raise FinalActionApprovalError("final_action_import_decision_missing")

    decision = dict(candidates[-1])
    for required in ("decided_by", "reason"):
        value = decision.get(required)
        if not isinstance(value, str) or not value.strip():
            raise FinalActionApprovalError(
                f"final_action_import_decision_missing_{required}"
            )
    if decision.get("source_worktree") not in {None, lane.get("worktree")}:
        raise FinalActionApprovalError("final_action_import_decision_source_mismatch")

    return {
        key: decision[key]
        for key in (
            "id",
            "lane_id",
            "hold_id",
            "final_action_hold_id",
            "decision",
            "status",
            "target_worktree",
            "source_worktree",
            "decided_by",
            "reason",
            "created_at",
            "forbidden_claims",
        )
        if key in decision
    }


def _import_decision_matches_hold(decision: dict[str, Any], *, hold_id: str) -> bool:
    hold_values = [
        value
        for value in (
            decision.get("hold_id"),
            decision.get("final_action_hold_id"),
        )
        if value is not None
    ]
    if not hold_values:
        return False
    return any(value == hold_id for value in hold_values)


def _safe_changed_files(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise FinalActionApprovalError("final_action_import_changed_files_missing")
    files: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise FinalActionApprovalError("final_action_import_changed_files_malformed")
        files.append(item)
    if not files:
        raise FinalActionApprovalError("final_action_import_changed_files_empty")
    for file_path in files:
        path = Path(file_path)
        if path.is_absolute() or ".." in path.parts:
            raise FinalActionApprovalError(
                "final_action_import_changed_file_escapes_worktree"
            )
    return files


def _preflight_final_action_import_files(
    source_worktree: Path,
    target_worktree: Path,
    changed_files: list[str],
) -> list[tuple[str, Path, Path]]:
    import_plan: list[tuple[str, Path, Path]] = []
    for changed_file in changed_files:
        source_path = _safe_child_path(source_worktree, changed_file)
        target_path = _safe_child_path(target_worktree, changed_file)
        if not source_path.exists() or not source_path.is_file():
            raise FinalActionApprovalError(
                f"final_action_import_source_file_missing: {changed_file}"
            )
        _preflight_final_action_import_target_path(
            target_worktree,
            target_path,
            changed_file,
        )
        import_plan.append((changed_file, source_path, target_path))
    return import_plan


def _preflight_final_action_import_target_path(
    target_worktree: Path,
    target_path: Path,
    changed_file: str,
) -> None:
    root = target_worktree.resolve()
    try:
        relative_target = target_path.relative_to(root)
    except ValueError as exc:
        raise FinalActionApprovalError(
            "final_action_import_changed_file_escapes_worktree"
        ) from exc
    current = root
    for part in relative_target.parts[:-1]:
        current = current / part
        if current.exists() and not current.is_dir():
            raise FinalActionApprovalError(
                "final_action_import_target_parent_not_directory: " + changed_file
            )
    if target_path.exists() and not target_path.is_file():
        raise FinalActionApprovalError(
            "final_action_import_target_path_not_file: " + changed_file
        )


def _optional_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _safe_child_path(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    child = (root_resolved / relative_path).resolve()
    try:
        child.relative_to(root_resolved)
    except ValueError as exc:
        raise FinalActionApprovalError(
            "final_action_import_changed_file_escapes_worktree"
        ) from exc
    return child


def _target_dirty_conflicting_paths(
    target_worktree: Path,
    changed_files: list[str],
) -> list[str]:
    _require_git_worktree_root(target_worktree)
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=target_worktree,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise FinalActionApprovalError("final_action_import_target_dirty_check_failed")
    dirty_paths = _git_status_paths(result.stdout)
    return sorted(dirty_paths & set(changed_files))


def _require_git_worktree_root(path: Path) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise FinalActionApprovalError("final_action_import_target_not_git_worktree")
    root = Path(result.stdout.strip()).resolve()
    if path.resolve() != root:
        raise FinalActionApprovalError("final_action_import_target_not_git_worktree_root")


def _git_status_paths(status_output: str) -> set[str]:
    paths: set[str] = set()
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        raw_path = line[3:]
        if " -> " in raw_path:
            paths.update(part for part in raw_path.split(" -> ") if part)
        elif raw_path:
            paths.add(raw_path)
    return paths


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_final_action_import_record(base_dir: Path, record: dict[str, Any]) -> None:
    path = _json_path(base_dir, "final_action_imports.json")
    data = _read_json(path, {"imports": []})
    imports = data.setdefault("imports", [])
    if not isinstance(imports, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="final_action_imports.json imports must be a list",
        )
    data["imports"] = [
        item
        for item in imports
        if not (isinstance(item, dict) and item.get("hold_id") == record["hold_id"])
    ]
    data["imports"].append(record)
    _write_json(path, data)
