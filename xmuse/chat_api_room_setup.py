"""Default Room conversation setup routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, status

from xmuse_core.chat.room_api_models import RoomConversationCreate
from xmuse_core.chat.room_setup import (
    DEFAULT_ROOM_ROSTER_TEMPLATE_ID,
    RoomSetupError,
    RoomSetupService,
)
from xmuse_core.chat.roster_templates import (
    WorkroomRosterTemplateStore,
    builtin_workroom_catalog,
    validate_roster_template,
)

ROOM_SETUP_OPTION_LIMIT = 20


def _room_setup_options(root: Path) -> dict[str, object]:
    catalog = builtin_workroom_catalog()
    templates = WorkroomRosterTemplateStore(root / "workroom_roster_templates.json").list_valid(
        catalog=catalog
    )
    ordered = sorted(
        templates,
        key=lambda item: (
            item.template_id != DEFAULT_ROOM_ROSTER_TEMPLATE_ID,
            item.display_name.casefold(),
            item.template_id,
        ),
    )[:ROOM_SETUP_OPTION_LIMIT]
    projected: list[dict[str, object]] = []
    for source in ordered:
        template = validate_roster_template(source, catalog=catalog)
        participants: list[dict[str, str]] = []
        for binding in template.roles[:8]:
            role = catalog.role_profiles[binding.role_id]
            participants.append(
                {
                    "role_id": role.role_id,
                    "role": role.participant_role,
                    "display_name": binding.display_name or role.display_name,
                    "description": role.description,
                    "collaboration_focus": role.collaboration_focus,
                }
            )
        projected.append(
            {
                "template_id": template.template_id,
                "display_name": template.display_name,
                "description": template.description,
                "participants": participants,
            }
        )
    return {
        "schema_version": "room_setup_options/v1",
        "default_roster_template_id": DEFAULT_ROOM_ROSTER_TEMPLATE_ID,
        "roster_templates": projected,
    }


def register_room_setup_routes(app: FastAPI, *, root: Path) -> None:
    @app.get("/api/chat/room-setup-options")
    def room_setup_options() -> dict[str, object]:
        return _room_setup_options(root)

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
