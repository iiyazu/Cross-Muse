from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, status

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.room_api_models import RoomObservationControlRequest
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.runtime.frontend_api import operator_error

_CONFLICT_CODES = {
    "room_control_idempotency_conflict",
    "room_control_state_conflict",
    "room_control_attempt_conflict",
    "room_control_seq_conflict",
    "room_observation_already_completed",
    "room_observation_not_cancellable",
    "room_observation_not_retryable",
    "room_observation_retry_not_settled",
    "room_attempt_generation_lost",
}


def _control_action(
    *,
    root: Path,
    observation_id: str,
    request: Request,
    payload: RoomObservationControlRequest,
    action: Literal["cancel", "retry"],
) -> dict[str, object]:
    controls = RoomObservationControlStore(root / "chat.db")
    try:
        method = controls.request_cancel if action == "cancel" else controls.request_retry
        result = method(
            observation_id=observation_id,
            client_action_id=payload.client_action_id,
            operator_identity="operator:local",
            expected_state=payload.expected_state,
            expected_attempt_count=payload.expected_attempt_count,
            expected_control_seq=payload.expected_control_seq,
        )
    except RoomControlError as exc:
        if exc.code == "room_observation_not_found":
            raise HTTPException(status_code=404, detail=operator_error(exc.code, exc.code)) from exc
        http_status = (
            status.HTTP_409_CONFLICT if exc.code in _CONFLICT_CODES else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=http_status,
            detail=operator_error(exc.code, exc.code),
        ) from exc
    projection = result["projection"]
    return {
        "action_id": payload.client_action_id,
        "status": "succeeded",
        "result_ref": f"room-observation:{observation_id}",
        "changed_refs": [f"room-observation:{observation_id}"],
        "event_cursor": result.get("event_cursor"),
        "projection_revision": result.get("event_cursor"),
        "room_observation_control": projection,
        "error": None,
    }


def register_room_control_routes(
    app: FastAPI,
    *,
    root: Path,
    operator_token: str | None = None,
) -> None:
    @app.post("/api/chat/operator/room-observations/{observation_id}/cancel")
    def cancel_room_observation(
        observation_id: str,
        request: Request,
        payload: RoomObservationControlRequest,
    ) -> dict[str, object]:
        require_operator_token(request, configured_token=operator_token)
        return _control_action(
            root=root,
            observation_id=observation_id,
            request=request,
            payload=payload,
            action="cancel",
        )

    @app.post("/api/chat/operator/room-observations/{observation_id}/retry")
    def retry_room_observation(
        observation_id: str,
        request: Request,
        payload: RoomObservationControlRequest,
    ) -> dict[str, object]:
        require_operator_token(request, configured_token=operator_token)
        return _control_action(
            root=root,
            observation_id=observation_id,
            request=request,
            payload=payload,
            action="retry",
        )
