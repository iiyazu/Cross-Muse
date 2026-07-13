from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response, status

from xmuse.chat_api_runtime import (
    WorkroomRuntimeInspector,
    WorkroomRuntimeRecoverer,
)
from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.memoryos_supervisor import (
    browser_memoryos_status,
    memoryos_rebuildability,
    read_memoryos_status,
)
from xmuse_core.chat.room_api_models import (
    RoomMemoryRebuildRequest,
    RoomRuntimeRecoverRequest,
)
from xmuse_core.chat.room_database import RoomDatabase, RoomDatabaseError
from xmuse_core.chat.room_memory_rebuild_store import (
    RoomMemoryRebuildActionStore,
    RoomMemoryRebuildError,
    safe_memory_rebuild_action,
)
from xmuse_core.chat.room_operations import (
    RoomRuntimeOperatorActionStore,
    build_room_operations_projection,
    runtime_incident_guard,
    runtime_recoverability,
)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _memory_runtime_status(root: Path) -> dict[str, Any]:
    safe = browser_memoryos_status(root)
    private = read_memoryos_status(root)
    return {**(private or {}), **safe}


def _memory_terminal_response(action: Mapping[str, Any]) -> dict[str, Any]:
    safe = safe_memory_rebuild_action(action)
    action_status = action.get("status")
    if action_status in {"requested", "applied"}:
        return safe
    reason = str(action.get("reason_code") or "room_memory_rebuild_failed")
    http_status = (
        status.HTTP_409_CONFLICT
        if action_status == "rejected"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    raise HTTPException(
        status_code=http_status,
        detail={"code": reason, "message": "MemoryOS derived index rebuild was not applied"},
    )


def rebuild_memory_index_action(*, root: Path, payload: RoomMemoryRebuildRequest) -> dict[str, Any]:
    request_payload = {
        "client_action_id": payload.client_action_id,
        "expected_incident_id": payload.expected_incident_id,
    }
    fingerprint = _fingerprint(request_payload)
    current = _memory_runtime_status(root)
    current_state = str(current.get("state") or "unknown")
    current_code = str(current.get("code") or "memoryos_status_unverifiable")
    rebuildability = memoryos_rebuildability(current)
    actions = RoomMemoryRebuildActionStore(root / "chat.db")
    try:
        action, _created = actions.reserve(
            client_action_id=payload.client_action_id,
            request_fingerprint=fingerprint,
            incident_guard=payload.expected_incident_id,
            runtime_generation=(
                str(current["generation"]) if isinstance(current.get("generation"), str) else None
            ),
            before_state=current_state,
            before_code=current_code,
        )
    except RoomMemoryRebuildError as exc:
        http_status = (
            status.HTTP_409_CONFLICT
            if exc.code.endswith("conflict")
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=http_status,
            detail={"code": exc.code, "message": "Memory rebuild action was not reserved"},
        ) from exc
    if action["status"] != "requested":
        return _memory_terminal_response(action)
    # Once the manager crossed the stopping boundary, the private topology is
    # expected to change; only the manager may resume that authorized phase.
    if action.get("phase") == "requested":
        current_guard = rebuildability.get("incident_id")
        if current_guard != payload.expected_incident_id:
            action = actions.finish(
                client_action_id=payload.client_action_id,
                status="rejected",
                after_state=current_state,
                after_code=current_code,
                reason_code="room_memory_rebuild_incident_changed",
            )
            return _memory_terminal_response(action)
        if not rebuildability.get("available"):
            action = actions.finish(
                client_action_id=payload.client_action_id,
                status="rejected",
                after_state=current_state,
                after_code=current_code,
                reason_code="room_memory_rebuild_not_available",
            )
            return _memory_terminal_response(action)
    return _memory_terminal_response(action)


def _safe_state(runtime: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(runtime.get("state") or "unknown"),
        str(runtime.get("code") or "room_runtime_unverifiable"),
    )


def _terminal_response(action: Mapping[str, Any]) -> dict[str, Any]:
    action_status = action.get("status")
    if action_status == "applied":
        return dict(action)
    reason = str(action.get("reason_code") or "room_runtime_recovery_failed")
    http_status = (
        status.HTTP_409_CONFLICT
        if action_status == "rejected"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    raise HTTPException(
        status_code=http_status,
        detail={"code": reason, "message": "Room runtime recovery was not applied"},
    )


def _error_code(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
        return str(detail["code"])
    return "room_runtime_recovery_failed"


def recover_room_runtime_action(
    *,
    root: Path,
    execution_root: Path,
    payload: RoomRuntimeRecoverRequest,
    inspector: WorkroomRuntimeInspector,
    recoverer: WorkroomRuntimeRecoverer,
) -> dict[str, Any]:
    request_payload = {
        "client_action_id": payload.client_action_id,
        "expected_incident_id": payload.expected_incident_id,
    }
    fingerprint = _fingerprint(request_payload)
    actions = RoomRuntimeOperatorActionStore(root / "chat.db")
    try:
        current = inspector(root, execution_root)
    except Exception:
        try:
            action, _created = actions.reserve(
                client_action_id=payload.client_action_id,
                request_fingerprint=fingerprint,
                incident_guard=payload.expected_incident_id,
                before_state="unknown",
                before_code="room_runtime_unverifiable",
            )
        except ValueError as exc:
            if str(exc) == "room_runtime_action_idempotency_conflict":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "room_runtime_action_idempotency_conflict",
                        "message": ("client_action_id was already used with different arguments"),
                    },
                ) from exc
            raise
        if action["status"] == "requested":
            action = actions.finish(
                client_action_id=payload.client_action_id,
                status="failed",
                after_state="unknown",
                after_code="room_runtime_unverifiable",
                reason_code="room_runtime_unverifiable",
            )
        return _terminal_response(action)
    current_state, current_code = _safe_state(current)
    try:
        action, created = actions.reserve(
            client_action_id=payload.client_action_id,
            request_fingerprint=fingerprint,
            incident_guard=payload.expected_incident_id,
            before_state=current_state,
            before_code=current_code,
        )
    except ValueError as exc:
        if str(exc) == "room_runtime_action_idempotency_conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "room_runtime_action_idempotency_conflict",
                    "message": "client_action_id was already used with different arguments",
                },
            ) from exc
        raise
    if action["status"] != "requested":
        return _terminal_response(action)

    # A replay after the API crashed between process recovery and ledger finalization
    # may safely close its own requested row when the runtime is now proven ready.
    if not created and current.get("ready") is True and current_state == "ready":
        applied = actions.finish(
            client_action_id=payload.client_action_id,
            status="applied",
            after_state="ready",
            after_code=current_code,
            reason_code=None,
            result={"source": "ready_reconciliation"},
        )
        return applied

    current_guard = runtime_incident_guard(current)
    recoverability = runtime_recoverability(current)
    resume_after_partial_stop = (
        not created and current_state == "stopped" and bool(recoverability["available"])
    )
    execution_guard = current_guard if resume_after_partial_stop else payload.expected_incident_id
    if current_guard != execution_guard:
        rejected = actions.finish(
            client_action_id=payload.client_action_id,
            status="rejected",
            after_state=current_state,
            after_code=current_code,
            reason_code="room_runtime_incident_changed",
        )
        return _terminal_response(rejected)
    if not recoverability["available"]:
        error_status: Literal["failed", "rejected"] = (
            "failed" if current_state == "unknown" else "rejected"
        )
        rejected = actions.finish(
            client_action_id=payload.client_action_id,
            status=error_status,
            after_state=current_state,
            after_code=current_code,
            reason_code="room_runtime_not_recoverable",
        )
        return _terminal_response(rejected)

    try:
        result = recoverer(root, execution_root, execution_guard)
    except HTTPException as exc:
        final_status: Literal["rejected", "failed"] = (
            "rejected" if exc.status_code == 409 else "failed"
        )
        failed = actions.finish(
            client_action_id=payload.client_action_id,
            status=final_status,
            after_state=current_state,
            after_code=current_code,
            reason_code=_error_code(exc),
        )
        return _terminal_response(failed)
    except Exception:
        failed = actions.finish(
            client_action_id=payload.client_action_id,
            status="failed",
            after_state=current_state,
            after_code=current_code,
            reason_code="room_runtime_recovery_failed",
        )
        return _terminal_response(failed)

    after_payload = result.get("after")
    after_payload = after_payload if isinstance(after_payload, Mapping) else {}
    after_state = str(after_payload.get("state") or "ready")
    after_code = str(after_payload.get("code") or "ready")
    applied = actions.finish(
        client_action_id=payload.client_action_id,
        status="applied",
        after_state=after_state,
        after_code=after_code,
        reason_code=None,
        result={"source": "guarded_recovery"},
    )
    return applied


def register_room_operations_routes(
    app: FastAPI,
    *,
    root: Path,
    execution_root: Path,
    runtime_inspector: WorkroomRuntimeInspector,
    runtime_recoverer: WorkroomRuntimeRecoverer,
    operator_token: str | None = None,
) -> None:
    @app.get("/api/chat/runtime/operations")
    def room_runtime_operations(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
                conn.execute("select 1 from chat_schema_meta limit 1").fetchone()
        except (RoomDatabaseError, sqlite3.Error, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "room_database_unavailable",
                    "message": "Room database is unavailable",
                },
            ) from exc
        try:
            runtime = runtime_inspector(root, execution_root)
        except Exception:
            runtime = {
                "state": "unknown",
                "code": "room_runtime_unverifiable",
                "ready": False,
                "services": {},
                "host": {"state": "unknown", "code": "room_host_unknown"},
            }
        return build_room_operations_projection(
            root / "chat.db",
            runtime,
            memory_runtime=_memory_runtime_status(root),
        )

    @app.post("/api/chat/operator/room-runtime/recover")
    def recover_room_runtime(
        request: Request,
        payload: RoomRuntimeRecoverRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        return recover_room_runtime_action(
            root=root,
            execution_root=execution_root,
            payload=payload,
            inspector=runtime_inspector,
            recoverer=runtime_recoverer,
        )

    @app.post("/api/chat/operator/memory-runtime/rebuild")
    def rebuild_memory_runtime(
        request: Request,
        response: Response,
        payload: RoomMemoryRebuildRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        result = rebuild_memory_index_action(root=root, payload=payload)
        response.headers["Cache-Control"] = "no-store"
        if result.get("status") == "requested":
            response.status_code = status.HTTP_202_ACCEPTED
        return result
