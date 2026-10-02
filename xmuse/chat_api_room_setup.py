"""Default Room conversation setup routes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException, status

from xmuse.provider_capabilities import ROOM_PROVIDER_KINDS, detect_provider_capabilities
from xmuse_core.chat.room_api_models import RoomConversationCreate
from xmuse_core.chat.room_setup import (
    DEFAULT_ROOM_ROSTER_TEMPLATE_ID,
    RoomSetupError,
    RoomSetupService,
)
from xmuse_core.chat.roster_templates import (
    RosterTemplate,
    WorkroomCatalog,
    WorkroomRosterTemplateStore,
    builtin_workroom_catalog,
    validate_roster_template,
)

ROOM_SETUP_OPTION_LIMIT = 20

ProviderCapabilitiesProvider = Callable[[], Mapping[str, Mapping[str, object]]]


def _provider_availability(
    provider: ProviderCapabilitiesProvider | None,
) -> Mapping[str, Mapping[str, object]] | None:
    """Detection failure degrades to "unknown": templates stay usable."""

    reader = provider or detect_provider_capabilities
    try:
        return reader()
    except Exception:
        return None


def _provider_unavailable(
    capabilities: Mapping[str, Mapping[str, object]],
    kind: str,
) -> bool:
    record = capabilities.get(kind)
    return not (isinstance(record, Mapping) and bool(record.get("available", False)))


def _template_cli_kinds(template: RosterTemplate, catalog: WorkroomCatalog) -> list[str]:
    kinds = {
        catalog.provider_profiles[binding.provider_profile_ref].cli_kind
        for binding in template.roles
        if binding.provider_profile_ref in catalog.provider_profiles
    }
    return sorted(kinds)


def _requested_cli_kinds(root: Path, request: RoomConversationCreate) -> list[str]:
    """Provider kinds a Room creation would instantiate from its roster.

    Unknown or invalid rosters stay with RoomSetupService's durable error codes.
    """

    if request.initial_participants is not None:
        if request.roster_template_id is not None:
            return []
        kinds: list[str] = []
        for participant in request.initial_participants:
            kind = str(participant.cli_kind or participant.provider_id or "").strip().lower()
            if kind in ROOM_PROVIDER_KINDS and kind not in kinds:
                kinds.append(kind)
        return kinds
    template_id = request.roster_template_id or DEFAULT_ROOM_ROSTER_TEMPLATE_ID
    catalog = builtin_workroom_catalog()
    try:
        template = WorkroomRosterTemplateStore(root / "workroom_roster_templates.json").get(
            template_id, catalog=catalog
        )
        validated = validate_roster_template(template, catalog=catalog)
    except (KeyError, ValueError):
        return []
    return _template_cli_kinds(validated, catalog)


def _reject_unavailable_roster_providers(
    root: Path,
    request: RoomConversationCreate,
    provider_capabilities_provider: ProviderCapabilitiesProvider | None,
) -> None:
    capabilities = _provider_availability(provider_capabilities_provider)
    if capabilities is None:
        return
    unavailable = [
        kind
        for kind in _requested_cli_kinds(root, request)
        if _provider_unavailable(capabilities, kind)
    ]
    if unavailable:
        raise RoomSetupError(
            "room_provider_unavailable",
            "room providers are unavailable: " + ", ".join(unavailable),
        )


def _room_setup_options(
    root: Path,
    *,
    provider_capabilities_provider: ProviderCapabilitiesProvider | None = None,
) -> dict[str, object]:
    capabilities = _provider_availability(provider_capabilities_provider)
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
        if capabilities is None:
            unavailable_providers: list[str] = []
        else:
            unavailable_providers = [
                kind
                for kind in _template_cli_kinds(template, catalog)
                if _provider_unavailable(capabilities, kind)
            ]
        projected.append(
            {
                "template_id": template.template_id,
                "display_name": template.display_name,
                "description": template.description,
                "participants": participants,
                "collaboration": (
                    None
                    if template.collaboration is None
                    else {
                        "mode": template.collaboration.mode,
                        "lead_role": template.collaboration.lead_role,
                    }
                ),
                "available": not unavailable_providers,
                "unavailable_providers": unavailable_providers,
            }
        )
    return {
        "schema_version": "room_setup_options/v1",
        "default_roster_template_id": DEFAULT_ROOM_ROSTER_TEMPLATE_ID,
        "roster_templates": projected,
    }


def register_room_setup_routes(
    app: FastAPI,
    *,
    root: Path,
    provider_capabilities_provider: ProviderCapabilitiesProvider | None = None,
) -> None:
    @app.get("/api/chat/room-setup-options")
    def room_setup_options() -> dict[str, object]:
        return _room_setup_options(
            root,
            provider_capabilities_provider=provider_capabilities_provider,
        )

    @app.post("/api/chat/conversations", status_code=status.HTTP_201_CREATED)
    def create_room(request: RoomConversationCreate) -> dict[str, object]:
        try:
            service = RoomSetupService(root)
            # A retried create replays (or conflicts) as before; admission applies only to
            # a Room that does not exist yet.
            if not service.has_setup_request(request.client_request_id):
                _reject_unavailable_roster_providers(
                    root,
                    request,
                    provider_capabilities_provider,
                )
            return service.create_conversation(request)
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
