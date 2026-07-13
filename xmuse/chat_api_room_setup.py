"""Default Room conversation setup routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, status

from xmuse_core.chat.room_api_models import RoomConversationCreate
from xmuse_core.chat.room_setup import RoomSetupError, RoomSetupService


def register_room_setup_routes(app: FastAPI, *, root: Path) -> None:
    @app.post("/api/chat/conversations", status_code=status.HTTP_201_CREATED)
    def create_room(request: RoomConversationCreate) -> dict[str, object]:
        try:
            return RoomSetupService(root).create_conversation(request)
        except RoomSetupError as exc:
            http_status = (
                404
                if exc.code == "room_roster_not_found"
                else 409
                if exc.code == "room_setup_idempotency_conflict"
                else 422
            )
            raise HTTPException(
                status_code=http_status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
