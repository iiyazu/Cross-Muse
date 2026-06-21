#!/usr/bin/env python3
"""REST API for the Xmuse dashboard frontend."""
from __future__ import annotations

from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform import dashboard_details as _dashboard_details
from xmuse_core.platform.dashboard_api_models import LaneCreate, LaneReject
from xmuse_core.platform.dashboard_details import (
    FinalActionApprovalError,
    _aggregation_summary,
    _build_dashboard_run_health,
    _build_lineage_graph,
    _build_tui_worklist_envelope,
    _compact_peer_session,
    _conversation_run_health_detail,
    _conversation_runtime_timeline_detail,
    _conversation_summary,
    _dashboard_run_health,
    _duration_seconds,
    _execution_card_detail,
    _feature_graph_set_card_detail,
    _feature_graph_set_summary,
    _filter_lanes_by_scope,
    _find_feature_graph_set_snapshot,
    _find_lane,
    _find_peer_session,
    _graph_authority_state,
    _is_lane_graph_snapshot,
    _iter_feature_graph_set_snapshots,
    _json_path,
    _lane_graph_card_detail,
    _lane_with_status,
    _latest_aggregation_for_graph,
    _load_lanes,
    _load_lanes_read_only,
    _log_entries,
    _optional_text,
    _parse_timestamp,
    _participant_detail,
    _peer_request_detail,
    _peer_result_detail,
    _read_audit_events,
    _read_errors,
    _read_json,
    _read_lineage_records,
    _read_model_entries,
    _read_run_aggregations,
    _read_runtime_snapshot,
    _read_self_evolution_entries,
    _read_sessions,
    _read_state_history,
    _record_timestamp,
    _resolve_pending_final_action,
    _resolve_run_health_scope_id,
    _sessions_by_conversation,
    utc_now,
)
from xmuse_core.platform.dashboard_graph_state import build_derived_graph_state
from xmuse_core.platform.dashboard_read_models import (
    build_dashboard_dead_letters,
    build_read_model_status,
)
from xmuse_core.platform.projection.syncer import DuplicateLaneError, LaneProjectionSyncer
from xmuse_core.platform.read_contracts import (
    build_feature_plan_contract,
    build_graph_set_runner_evidence,
    build_planning_run_contract,
    build_provider_inventory,
    build_provider_selection_records,
    build_takeover_context,
)
from xmuse_core.platform.run_health import discover_xmuse_runtime_processes
from xmuse_core.platform.state_normalizer import (
    summarize_lane_states,
)
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

DEFAULT_PORT = 8200
DEFAULT_BASE_DIR = default_xmuse_root(Path(__file__).resolve().parent)


def create_app(base_dir: Path | str = DEFAULT_BASE_DIR) -> FastAPI:
    _dashboard_details.discover_xmuse_runtime_processes = discover_xmuse_runtime_processes
    root = Path(base_dir)
    app = FastAPI(title="Xmuse Dashboard API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Return system health including graph authority and lineage status.

        Response fields
        ---------------
        status : "ok" | "degraded"
            "degraded" when the authoritative graph is in a terminal-failure or
            blocked state, or when there are active error entries.
        version : str
            API version string.
        graph_authority : dict
            - authoritative_graph_id: most-recently spawned graph ID, or null
            - merge_state: "merged" | "running" | "terminated" |
              "blocked_for_input" | "unknown"
            - lineage_terminated: true when the latest aggregation is terminal
            - open_lineage_count: lineage records with no terminal aggregation
            - latest_run_id: source_run_id of the most-recent lineage record
            - latest_lineage_id: lineage_id of the most-recent lineage record
        lane_summary : dict
            Normalized lane state counts from the active feature_lanes.json.
        active_session_count : int
            Number of entries in active_sessions.json.
        error_count : int
            Number of entries in error_knowledge.json.
        """
        graph_auth = _graph_authority_state(root)

        # Lane summary
        try:
            lane_data = _load_lanes(root)
            lanes = [lane for lane in lane_data["lanes"] if isinstance(lane, dict)]
            lane_summary = summarize_lane_states(lanes)
        except HTTPException:
            lane_summary = {}

        # Session and error counts (best-effort; missing files return 0)
        active_session_count = len(_read_sessions(root))
        error_count = len(_read_errors(root))

        # Derive overall status
        run_health_model = _dashboard_run_health(root)
        degraded_terminal_states = {"terminated", "blocked_for_input"}
        degraded_lineage_states = {"incomplete_termination", "terminated", "blocked_for_input"}
        overall_status = (
            "degraded"
            if (
                graph_auth["merge_state"] in degraded_terminal_states
                or graph_auth["lineage_status"] in degraded_terminal_states
                or graph_auth["graph_lineage_status"] in degraded_lineage_states
                or (
                    run_health_model is not None
                    and run_health_model.get("counts", {}).get("degraded_fallback", 0)
                    > 0
                )
                or error_count > 0
            )
            else "ok"
        )

        return {
            "status": overall_status,
            "version": "0.1.0",
            "graph_authority": graph_auth,
            "lane_summary": lane_summary,
            "run_health": run_health_model,
            "active_session_count": active_session_count,
            "error_count": error_count,
        }

    @app.get("/api/run-health")
    def run_health(
        conversation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return _build_dashboard_run_health(
                root,
                conversation_id=conversation_id,
                workspace_id=workspace_id,
            )
        except JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"invalid JSON in feature_lanes.json: {exc.msg}",
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @app.get("/api/tui/worklist-envelope")
    def tui_worklist_envelope(
        conversation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        return _build_tui_worklist_envelope(
            root,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )

    @app.get("/api/tui/provider-inventory")
    def tui_provider_inventory() -> dict[str, Any]:
        return build_provider_inventory()

    @app.get("/api/tui/provider-selection-records")
    def tui_provider_selection_records(
        lane_id: str | None = None,
        provider_profile_ref: str | None = None,
        task_type: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return build_provider_selection_records(
            xmuse_root=root,
            lane_id=lane_id,
            provider_profile_ref=provider_profile_ref,
            task_type=task_type,
            limit=limit,
        )

    @app.get("/api/lanes")
    def list_lanes() -> dict[str, list[dict[str, Any]]]:
        data = _load_lanes(root)
        return {
            "lanes": [
                _lane_with_status(lane, base_dir=root)
                for lane in data["lanes"]
                if isinstance(lane, dict)
            ]
        }

    @app.get("/api/lanes/{feature_id}")
    def lane_detail(feature_id: str) -> dict[str, Any]:
        data = _load_lanes(root)
        lane = _lane_with_status(_find_lane(data, feature_id), base_dir=root)
        logs = _log_entries(root, feature_id)
        return {
            "lane": lane,
            "execution_log": "".join(entry["content"] for entry in logs),
            "logs": logs,
        }

    @app.get("/api/lanes/{feature_id}/takeover-context")
    def lane_takeover_context(
        feature_id: str,
        conversation_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        data = _load_lanes_read_only(root)
        _resolve_run_health_scope_id(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
        lane = _find_lane(
            data,
            feature_id,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
        lanes = _filter_lanes_by_scope(
            data["lanes"],
            conversation_id=conversation_id,
            workspace_id=workspace_id,
        )
        return build_takeover_context(
            lane=lane,
            all_lanes=lanes,
            xmuse_root=root,
        )

    @app.post("/api/lanes", status_code=status.HTTP_201_CREATED)
    def create_lane(request: LaneCreate) -> dict[str, Any]:
        feature_id = request.feature_id.strip()
        if not feature_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="feature_id required",
            )

        lane = request.model_dump(exclude_none=True)
        lane["feature_id"] = feature_id
        lane["prompt"] = request.prompt.strip()
        lane["task_type"] = lane.get("task_type") or "execute"
        lane["status"] = lane.get("status") or "pending"
        try:
            created = LaneProjectionSyncer(_json_path(root, "feature_lanes.json")).append_lane(
                lane
            )
        except DuplicateLaneError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return {key: value for key, value in created.items() if key != "projection_revision"}

    @app.post("/api/lanes/{feature_id}/approve")
    def approve_lane(feature_id: str) -> dict[str, Any]:
        def mutate(lane: dict[str, Any]) -> None:
            status_value = lane.get("status") or "pending"
            if status_value == "awaiting_final_action":
                try:
                    resolved = _resolve_pending_final_action(
                        root,
                        feature_id,
                        lane=lane,
                    )
                except FinalActionApprovalError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=str(exc),
                    ) from exc
                if resolved is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="no pending final action hold for lane",
                    )
                lane["status"], lane["final_action_hold_id"], blocker_reason = resolved
                if blocker_reason:
                    lane["blocker_reason"] = blocker_reason
            elif status_value not in {"done", "merged"}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="only completed lanes can be approved",
                )
            lane["approval_status"] = "approved"
            lane["approved_at"] = utc_now()

        try:
            lane = LaneProjectionSyncer(_json_path(root, "feature_lanes.json")).update_lane(
                feature_id,
                mutate,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="lane not found",
            ) from exc
        return _lane_with_status(lane)

    @app.post("/api/lanes/{feature_id}/reject")
    def reject_lane(feature_id: str, request: LaneReject | None = None) -> dict[str, Any]:
        rejection = request or LaneReject()

        def mutate(lane: dict[str, Any]) -> None:
            lane["approval_status"] = "rejected"
            lane["rejected_at"] = utc_now()
            if rejection.reason:
                lane["rejection_reason"] = rejection.reason
            lane["rework_requested"] = rejection.rework
            if rejection.rework:
                lane["status"] = "pending"

        try:
            lane = LaneProjectionSyncer(_json_path(root, "feature_lanes.json")).update_lane(
                feature_id,
                mutate,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="lane not found",
            ) from exc
        return _lane_with_status(lane)

    @app.get("/api/sessions")
    def list_sessions() -> dict[str, list[Any]]:
        return {"sessions": _read_sessions(root)}

    @app.get("/api/errors")
    def list_errors() -> dict[str, list[Any]]:
        return {"errors": _read_errors(root)}

    @app.get("/api/resolutions")
    def list_resolutions() -> dict[str, list[Any]]:
        return {"resolutions": _read_model_entries(root, "resolutions.json", "resolutions")}

    @app.get("/api/verdicts")
    def list_verdicts() -> dict[str, list[Any]]:
        return {"verdicts": _read_model_entries(root, "verdicts.json", "verdicts")}

    @app.get("/api/dashboard/dead-letters")
    def dashboard_dead_letters() -> dict[str, Any]:
        return build_dashboard_dead_letters(root)

    @app.get("/api/dashboard/read-models/status")
    def dashboard_read_model_status() -> dict[str, Any]:
        return build_read_model_status(root)

    @app.get("/api/planning-runs/{planning_run_id}")
    def planning_run_detail(planning_run_id: str) -> dict[str, Any]:
        try:
            return build_planning_run_contract(
                planning_run_id=planning_run_id,
                xmuse_root=root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.get("/api/feature-plans/{feature_plan_id}")
    def feature_plan_detail(feature_plan_id: str) -> dict[str, Any]:
        try:
            return build_feature_plan_contract(
                feature_plan_id=feature_plan_id,
                lanes_path=_json_path(root, "feature_lanes.json"),
                xmuse_root=root,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.get("/api/self-evolution")
    def list_self_evolution() -> dict[str, list[Any]]:
        return {
            "run_aggregations": _read_self_evolution_entries(
                root,
                "run_aggregations.json",
                "aggregations",
            ),
            "evidence_bundles": _read_self_evolution_entries(
                root,
                "evidence_bundles.json",
                "evidence_bundles",
            ),
            "proposals": _read_self_evolution_entries(root, "proposals.json", "proposals"),
            "review_decisions": _read_self_evolution_entries(
                root,
                "review_decisions.json",
                "review_decisions",
            ),
            "guardrail_decisions": _read_self_evolution_entries(
                root,
                "guardrail_decisions.json",
                "guardrail_decisions",
            ),
            "budget_windows": _read_self_evolution_entries(
                root,
                "budget_windows.json",
                "budget_windows",
            ),
            "dedup_records": _read_self_evolution_entries(
                root,
                "dedup_records.json",
                "dedup_records",
            ),
            "lineage": _read_self_evolution_entries(root, "lineage.json", "lineage"),
            "clarification_requests": _read_self_evolution_entries(
                root,
                "clarification_requests.json",
                "clarification_requests",
            ),
            "clarification_resolutions": _read_self_evolution_entries(
                root,
                "clarification_resolutions.json",
                "clarification_resolutions",
            ),
        }

    @app.get("/api/self-evolution/audit")
    def self_evolution_audit() -> dict[str, Any]:
        """Return a structured audit snapshot of all self-evolution runs.

        The snapshot joins lineage records with their proposals, run-terminal
        aggregations, and system-authored conversations so a human can review
        the full self-evolution history without reading raw store files.

        The read model is materialised on demand and cached in
        ``read_models/self_evolution_audit.json``.
        """
        store_root = root / "self_evolution"
        read_models_root = root / "read_models"
        writer = SelfEvolutionAuditWriter(
            store_root=store_root,
            read_models_root=read_models_root,
        )
        try:
            payload = writer.write()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to build self-evolution audit: {exc}",
            ) from exc
        return payload

    @app.get("/api/self-evolution/conversations")
    def self_evolution_conversations() -> dict[str, Any]:
        """Return all system-authored self-evolution conversations.

        Each entry includes the conversation metadata joined with the
        corresponding proposal so the caller can see which blueprint track
        each conversation targets.
        """
        store_root = root / "self_evolution"
        read_models_root = root / "read_models"
        writer = SelfEvolutionAuditWriter(
            store_root=store_root,
            read_models_root=read_models_root,
        )
        try:
            writer.write()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to build self-evolution conversations: {exc}",
            ) from exc
        data = _read_json(read_models_root / SelfEvolutionAuditWriter.CONVERSATIONS_FILE, {})
        if not isinstance(data, dict):
            return {"schema_version": "1", "conversations": []}
        return data

    @app.get("/api/self-evolution/clarifications")
    def self_evolution_clarifications() -> dict[str, Any]:
        """Return all clarification requests and resolutions.

        Each request entry is joined with its resolution (if one exists) so the
        caller can see the full lifecycle of a blocked run: what was missing,
        who provided the information, and which graph was spawned to resume.

        The read model is materialised on demand and cached in
        ``read_models/self_evolution_clarifications.json``.
        """
        store_root = root / "self_evolution"
        read_models_root = root / "read_models"
        writer = SelfEvolutionAuditWriter(
            store_root=store_root,
            read_models_root=read_models_root,
        )
        try:
            writer.write()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to build self-evolution clarifications: {exc}",
            ) from exc
        data = _read_json(
            read_models_root / SelfEvolutionAuditWriter.CLARIFICATION_FILE, {}
        )
        if not isinstance(data, dict):
            return {
                "schema_version": "1",
                "clarification_requests": [],
                "clarification_resolutions": [],
            }
        return data

    @app.get("/api/dashboard/audit-events")
    def list_audit_events(
        event_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Return paginated system events from the event bus audit log.

        Query parameters
        ----------------
        event_type : str, optional
            Filter to events whose ``event_type`` field matches exactly.
        since : str, optional
            ISO-8601 timestamp; only events at or after this time are returned.
        until : str, optional
            ISO-8601 timestamp; only events at or before this time are returned.
        page : int, default 1
            1-based page number.
        page_size : int, default 50
            Maximum number of events per page (capped at 500).
        """
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="page must be >= 1",
            )
        page_size = max(1, min(page_size, 500))

        since_dt: datetime | None = None
        until_dt: datetime | None = None
        if since is not None:
            since_dt = _parse_timestamp(since)
            if since_dt is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid since timestamp: {since!r}",
                )
        if until is not None:
            until_dt = _parse_timestamp(until)
            if until_dt is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid until timestamp: {until!r}",
                )

        events = _read_audit_events(
            root,
            event_type=event_type,
            since=since_dt,
            until=until_dt,
        )

        total = len(events)
        offset = (page - 1) * page_size
        page_events = events[offset : offset + page_size]

        return {
            "events": page_events,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, -(-total // page_size)),  # ceiling division
        }

    @app.get("/api/dashboard/state-history")
    def list_state_history(
        lane_id: str | None = None,
        state_key: str | None = None,
        since: str | None = None,
        until: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Return paginated state snapshots from the state machine history log.

        Query parameters
        ----------------
        lane_id : str, optional
            Filter to snapshots for a specific lane.
        state_key : str, optional
            Filter to snapshots where the state equals this value (e.g. ``"dispatched"``).
        since : str, optional
            ISO-8601 timestamp; only snapshots at or after this time are returned.
        until : str, optional
            ISO-8601 timestamp; only snapshots at or before this time are returned.
        page : int, default 1
            1-based page number.
        page_size : int, default 50
            Maximum number of snapshots per page (capped at 500).
        """
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="page must be >= 1",
            )
        page_size = max(1, min(page_size, 500))

        since_dt: datetime | None = None
        until_dt: datetime | None = None
        if since is not None:
            since_dt = _parse_timestamp(since)
            if since_dt is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid since timestamp: {since!r}",
                )
        if until is not None:
            until_dt = _parse_timestamp(until)
            if until_dt is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"invalid until timestamp: {until!r}",
                )

        snapshots = _read_state_history(
            root,
            lane_id=lane_id,
            state_key=state_key,
            since=since_dt,
            until=until_dt,
        )

        total = len(snapshots)
        offset = (page - 1) * page_size
        page_snapshots = snapshots[offset : offset + page_size]

        return {
            "snapshots": page_snapshots,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, -(-total // page_size)),  # ceiling division
        }

    @app.get("/api/dashboard/lineage")
    def execution_lineage(
        from_node: str | None = None,
        depth: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Return execution graph lineage with node relationships and merge points.

        The response describes a directed graph where each node is a run or
        spawned graph and each edge is an ``EvolutionLineageRecord`` that links
        a source run to the graph it spawned.

        Query parameters
        ----------------
        from_node : str, optional
            Start graph traversal from this node ID (``source_run_id`` or
            ``spawned_graph_id``).  Only nodes reachable from this node are
            returned.  When omitted the full lineage graph is returned.
        depth : int, optional
            Maximum traversal depth from ``from_node``.  Requires ``from_node``
            to be set; ignored otherwise.  Must be >= 1 when provided.
        run_id : str, optional
            Convenience alias for ``from_node`` when the caller wants to anchor
            the traversal on a specific run ID.  Ignored when ``from_node`` is
            also provided.
        """
        if depth is not None and depth < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="depth must be >= 1",
            )

        anchor = from_node or run_id
        records = _read_lineage_records(root)
        graph = _build_lineage_graph(records, from_node=anchor, depth=depth)
        return graph

    @app.get("/api/dashboard/peer-chat/conversations")
    def list_peer_chat_conversations() -> dict[str, object]:
        service = PeerChatService(root / "chat.db")
        rows = []
        for row in service.list_conversations(
            api_href_template="/api/dashboard/peer-chat/conversations/{conversation_id}"
        )["conversations"]:
            compact = dict(row)
            inbox_counts = compact["inbox_counts"]
            compact["unread_count"] = inbox_counts["unread"]
            compact["claimed_count"] = inbox_counts["claimed"]
            rows.append(compact)
        return {"conversations": rows}

    @app.get("/api/dashboard/peer-chat/conversations/{conversation_id}")
    def get_peer_chat_conversation(conversation_id: str) -> dict[str, object]:
        store = ChatStore(root / "chat.db")
        participants = ParticipantStore(root / "chat.db")
        inbox = ChatInboxStore(root / "chat.db")
        timeline = PeerChatService(root / "chat.db").list_conversation_timeline(
            conversation_id
        )
        conversation = next(
            (conv for conv in store.list_conversations() if conv.id == conversation_id),
            None,
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation not found",
            )

        items = []
        for item in inbox.list_by_conversation(conversation_id, include_terminal=True):
            data = item.model_dump(mode="json")
            data["href"] = f"/dashboard/peer-chat/inbox/{item.id}"
            items.append(data)

        return {
            "conversation": conversation.model_dump(mode="json"),
            "participants": [
                p.model_dump(mode="json")
                for p in participants.list_by_conversation(conversation_id)
            ],
            "messages": timeline["messages"],
            "cards": timeline["cards"],
            "items": timeline["items"],
            "inbox_items": items,
            "sessions": _sessions_by_conversation(root).get(conversation_id, []),
        }

    @app.get("/api/dashboard/peer-chat/conversations/{conversation_id}/inspector")
    def peer_chat_conversation_inspector(conversation_id: str) -> dict[str, Any]:
        from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
        from xmuse_core.platform.dashboard_read_models import (
            build_dashboard_dead_letters,
            build_read_model_status,
        )

        try:
            payload = build_conversation_inspector_payload(conversation_id, root)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        # Dashboard-only degradation enrichments
        dl_count = 0
        rm_degraded = False
        try:
            dl = build_dashboard_dead_letters(root)
            dl_count = dl.get("counts", {}).get("dead_letter", 0)
        except Exception:
            pass
        try:
            rm = build_read_model_status(root)
            rm_degraded = bool(rm.get("degraded", False))
        except Exception:
            pass
        payload["degradation"]["dead_letter_count"] = dl_count
        payload["degradation"]["read_model_degraded"] = rm_degraded
        payload["runtime_timeline_refs"] = {
            "dashboard": {
                "href": (
                    f"/dashboard/peer-chat/conversations/{conversation_id}"
                    "#runtime-timeline"
                ),
                "label": "Runtime timeline",
            },
            "api": {
                "api_href": (
                    f"/api/dashboard/peer-chat/conversations/{conversation_id}"
                    "/runtime-timeline"
                ),
                "label": "Runtime timeline",
            },
        }
        return payload

    @app.get("/api/dashboard/peer-chat/conversations/{conversation_id}/runtime-timeline")
    def peer_chat_runtime_timeline(conversation_id: str) -> dict[str, Any]:
        return _conversation_runtime_timeline_detail(root, conversation_id)

    @app.get("/api/dashboard/peer-chat/conversations/{conversation_id}/lane-graphs/{graph_id}")
    def peer_chat_lane_graph_detail(conversation_id: str, graph_id: str) -> dict[str, Any]:
        return _lane_graph_card_detail(root, conversation_id, graph_id)

    @app.get(
        "/api/dashboard/peer-chat/conversations/{conversation_id}/feature-graph-sets/{graph_set_id}"
    )
    def peer_chat_feature_graph_set_detail(
        conversation_id: str,
        graph_set_id: str,
    ) -> dict[str, Any]:
        return _feature_graph_set_card_detail(root, conversation_id, graph_set_id)

    @app.get("/api/dashboard/peer-chat/conversations/{conversation_id}/run-health")
    def peer_chat_run_health_detail(conversation_id: str) -> dict[str, Any]:
        return _conversation_run_health_detail(root, conversation_id)

    @app.get(
        "/api/dashboard/peer-chat/conversations/{conversation_id}/execution-cards/{intent_id}"
    )
    def peer_chat_execution_card_detail(
        conversation_id: str,
        intent_id: str,
    ) -> dict[str, Any]:
        return _execution_card_detail(root, conversation_id, intent_id)

    @app.get("/api/dashboard/peer-chat/sessions/{god_session_id}")
    def peer_chat_session_detail(god_session_id: str) -> dict[str, Any]:
        session = _find_peer_session(root, god_session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="peer session not found",
            )
        compact = _compact_peer_session(session)
        conversation_id = _optional_text(compact.get("conversation_id"))
        participant_id = _optional_text(compact.get("participant_id"))
        return {
            "session": compact,
            "conversation": _conversation_summary(root, conversation_id),
            "participant": _participant_detail(root, participant_id),
        }

    @app.get("/api/dashboard/peer-chat/requests/{request_id}")
    @app.get("/api/peer-requests/{request_id}")
    def peer_request_detail(request_id: str) -> dict[str, Any]:
        return _peer_request_detail(root, request_id)

    @app.get("/api/dashboard/peer-chat/requests/{request_id}/result")
    @app.get("/api/peer-requests/{request_id}/result")
    def peer_result_detail(request_id: str) -> dict[str, Any]:
        return _peer_result_detail(root, request_id)

    @app.get("/api/lane-graphs")
    def list_lane_graphs() -> dict[str, Any]:
        """Return all lane graph snapshots with their derived execution state.

        Each entry includes the full lane graph definition (id, conversation_id,
        resolution_id, version, status, lanes) plus a ``derived_state`` block
        computed from the current lane execution state.

        ``derived_state`` mirrors the shape produced by ``build_derived_graph_state``
        and is the same source used by ``/api/health``.  When no lane graph
        files exist the response is an empty list.

        Response shape
        --------------
        graphs : list
            Each item:
            - id, conversation_id, resolution_id, version, status, lanes
            - derived_state: { status, terminal, reason, graph_lineage_status,
              lane_counts, lane_statuses, open_lane_lineages, failed_lineages,
              merged_lineages, blocked_objects, final_action_holds }
        total : int
            Number of graphs returned.
        """
        graphs_dir = root / "lane_graphs"
        if not graphs_dir.exists():
            return {"graphs": [], "total": 0}

        entries: list[dict[str, Any]] = []
        for path in sorted(graphs_dir.glob("*.json")):
            data = _read_runtime_snapshot(path)
            if not _is_lane_graph_snapshot(data):
                continue
            graph_id = data.get("id") or path.stem
            derived = build_derived_graph_state(root, str(graph_id))
            entry = dict(data)
            entry["derived_state"] = derived if derived is not None else {}
            entries.append(entry)

        # Sort newest-first by graph id (lexicographic; IDs are typically
        # timestamped or sequential so this gives a reasonable default order).
        entries.sort(key=lambda e: str(e.get("id", "")), reverse=True)
        return {"graphs": entries, "total": len(entries)}

    @app.get("/api/feature-graph-sets")
    def list_feature_graph_sets() -> dict[str, Any]:
        """Return feature graph-set snapshots from current and fake artifact roots."""
        entries = [
            _feature_graph_set_summary(data, path)
            for path, data in _iter_feature_graph_set_snapshots(root)
        ]
        entries.sort(key=lambda e: str(e.get("id", "")), reverse=True)
        return {"graph_sets": entries, "total": len(entries)}

    @app.get("/api/feature-graph-sets/{graph_set_id}")
    def feature_graph_set_detail(graph_set_id: str) -> dict[str, Any]:
        """Return one feature graph-set snapshot with a compact summary."""
        snapshot = _find_feature_graph_set_snapshot(root, graph_set_id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"feature graph set not found: {graph_set_id}",
            )
        path, data = snapshot
        return {
            "graph_set": data,
            "summary": _feature_graph_set_summary(data, path),
        }

    @app.get("/api/feature-graph-sets/{graph_set_id}/runner-evidence")
    def feature_graph_set_runner_evidence(graph_set_id: str) -> dict[str, Any]:
        try:
            return build_graph_set_runner_evidence(
                graph_set_id=graph_set_id,
                lanes_path=_json_path(root, "feature_lanes.json"),
                xmuse_root=root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.get("/api/lane-graphs/{graph_id}")
    def lane_graph_detail(graph_id: str) -> dict[str, Any]:
        """Return a single lane graph snapshot with its derived execution state.

        Path parameters
        ---------------
        graph_id : str
            The graph ID (matches the filename stem under ``lane_graphs/``).

        Response shape
        --------------
        graph : dict
            Full lane graph definition plus ``derived_state``.
        lineage : dict | null
            The most-recent ``EvolutionLineageRecord`` that spawned this graph,
            or null when no lineage record references this graph_id.
        aggregation : dict | null
            The most-recent ``RunTerminalAggregation`` for this graph from the
            self-evolution store, or null when none exists.
        """
        path = root / "lane_graphs" / f"{graph_id}.json"
        if not path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"lane graph not found: {graph_id}",
            )
        data = _read_json(path, {})
        if not _is_lane_graph_snapshot(data):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"lane graph not found: {graph_id}",
            )

        derived = build_derived_graph_state(root, graph_id)
        graph = dict(data)
        graph["derived_state"] = derived if derived is not None else {}

        # Join the most-recent lineage record that spawned this graph
        lineage_records = _read_lineage_records(root)
        matching_lineage = [
            rec for rec in lineage_records if rec.get("spawned_graph_id") == graph_id
        ]
        latest_lineage: dict[str, Any] | None = None
        if matching_lineage:
            latest_lineage = sorted(matching_lineage, key=_record_timestamp)[-1]

        # Join the most-recent run aggregation for this graph
        aggregations = _read_run_aggregations(root)
        latest_aggregation = _latest_aggregation_for_graph(aggregations, graph_id)
        aggregation_summary = _aggregation_summary(latest_aggregation)

        return {
            "graph": graph,
            "lineage": latest_lineage,
            "aggregation": aggregation_summary,
        }

    @app.get("/api/metrics")
    def metrics() -> dict[str, int | float | None]:
        data = _load_lanes(root)
        lanes = [lane for lane in data["lanes"] if isinstance(lane, dict)]
        summary = summarize_lane_states(lanes)
        done = summary.get("merged", 0) + summary.get("done", 0)
        failed = max(0, summary.get("terminal", 0) - summary.get("merged", 0))
        pending = len(lanes) - done - failed
        durations = [
            duration
            for lane in lanes
            if (duration := _duration_seconds(lane)) is not None
        ]
        avg_time = round(sum(durations) / len(durations), 2) if durations else None
        return {
            "total": len(lanes),
            "done": done,
            "ready": summary.get("ready", 0),
            "requeued": summary.get("requeued", 0),
            "failed": failed,
            "pending": pending,
            "avg_time_seconds": avg_time,
        }

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=DEFAULT_PORT)
