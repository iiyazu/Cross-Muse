"""Safe HTTP boundary for participant-bound native Codex capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response, status

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.participant_store import ParticipantStore, participant_summary
from xmuse_core.chat.room_api_models import RoomCodexActionRequest
from xmuse_core.chat.room_codex_bridge import RoomCodexBridgeStore
from xmuse_core.chat.room_codex_projection import build_room_codex_projection
from xmuse_core.chat.room_codex_projection_cache import (
    RoomCodexProjectionCache,
    RoomCodexProjectionCacheError,
)
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.runtime.frontend_api import operator_error

_PROOF_BOUNDARY = "operator_action_receipt_not_codex_or_room_authority"


def _identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and len(cleaned.encode("utf-8")) <= 200 else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("codex_native_"):
        return code
    return "codex_native_action_failed"


def _store_error(exc: Exception) -> HTTPException:
    code = "codex_native_participant_not_found" if isinstance(exc, KeyError) else _error_code(exc)
    if code.endswith("_not_found"):
        http_status = status.HTTP_404_NOT_FOUND
    elif any(
        marker in code
        for marker in (
            "conflict",
            "guard_required",
            "confirmation_required",
            "idempotency",
            "reconcile_required",
        )
    ):
        http_status = status.HTTP_409_CONFLICT
    elif code.endswith("_unavailable"):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=http_status,
        detail=operator_error(code, "Native Codex action was not accepted"),
    )


def _safe_action_result(
    result: Mapping[str, Any], *, client_action_id: str, participant_id: str
) -> dict[str, Any]:
    return {
        "action_id": _identifier(result.get("action_id")),
        "client_action_id": _identifier(result.get("client_action_id")) or client_action_id,
        "status": _identifier(result.get("status")) or "requested",
        "participant_id": _identifier(result.get("participant_id")) or participant_id,
        "conversation_id": _identifier(result.get("conversation_id")),
        "control_seq": _integer(result.get("control_seq")),
        "capability_id": _identifier(result.get("capability_id")),
        "reason_code": _identifier(result.get("reason_code")),
        "updated_at": _identifier(result.get("updated_at")),
        "proof_boundary": _PROOF_BOUNDARY,
    }


def register_room_codex_routes(
    app: FastAPI,
    *,
    root: Path,
    operator_token: str | None = None,
) -> None:
    @app.get("/api/chat/conversations/{conversation_id}/codex-agents")
    def room_codex_agents(
        conversation_id: str,
        response: Response,
        limit: int = Query(default=100, ge=1, le=100),
        before_event_seq: int | None = Query(default=None, ge=1),
        after_event_seq: int | None = Query(default=None, ge=0),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        if before_event_seq is not None and after_event_seq is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="codex_projection_cursor_conflict",
            )
        with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
            exists = conn.execute(
                "select 1 from conversations where id = ?", (conversation_id,)
            ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        try:
            cache_page = RoomCodexProjectionCache(root).read_conversation(
                conversation_id,
                limit=limit,
                before_event_seq=before_event_seq,
                after_event_seq=after_event_seq,
            )
        except RoomCodexProjectionCacheError as exc:
            cache_page = {
                "projection_available": False,
                "participants": [],
                "events": [],
                "latest_event_seq": 0,
                "has_older": False,
                "has_newer": False,
                "next_before_event_seq": None,
                "next_after_event_seq": None,
                "reason_code": exc.code,
            }
        participants = [
            participant_summary(item)
            for item in ParticipantStore(root / "chat.db").list_by_conversation(
                conversation_id
            )
            if item.role != "init"
        ]
        try:
            return build_room_codex_projection(
                conversation_id,
                participants=participants,
                bridge_store=RoomCodexBridgeStore(root / "chat.db"),
                cache_page=cache_page,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="codex_projection_invalid",
            ) from exc

    @app.post("/api/chat/operator/room-participants/{participant_id}/codex-actions")
    def request_codex_action(
        participant_id: str,
        request: Request,
        payload: RoomCodexActionRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        try:
            participant = ParticipantStore(root / "chat.db").get(participant_id)
            result, _created = RoomCodexBridgeStore(root / "chat.db").request_action(
                conversation_id=participant.conversation_id,
                participant_id=participant_id,
                capability_id=payload.capability_id,
                safe_request=payload.request,
                client_action_id=payload.client_action_id,
                expected_session_guard=payload.expected_session_guard,
                expected_goal_guard=payload.expected_goal_guard,
                expected_settings_guard=payload.expected_settings_guard,
                expected_turn_guard=payload.expected_turn_guard,
                confirmed_pending_observations=payload.confirmed_pending_observations,
                operator_identity="operator:local",
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        return _safe_action_result(
            result,
            client_action_id=payload.client_action_id,
            participant_id=participant_id,
        )


__all__ = ["register_room_codex_routes"]
