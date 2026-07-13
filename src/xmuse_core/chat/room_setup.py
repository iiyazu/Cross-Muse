"""Room-native conversation setup without compatibility bootstrap state."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.chat.participant_store import (
    PersonaSnapshot,
    insert_participant_conn,
    prepare_participant,
    provider_profile_id_for_role,
    resolve_current_chat_cli_kind,
)
from xmuse_core.chat.room_api_models import ParticipantInit, RoomConversationCreate
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_binding_conn import ensure_room_memory_bindings_conn
from xmuse_core.chat.roster_templates import (
    WorkroomRosterTemplateStore,
    builtin_workroom_catalog,
    persona_snapshot_for_role_profile,
    template_to_participant_inits,
    validate_roster_template,
)
from xmuse_core.providers.models import ProviderProfileId
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    DEFAULT_CODEX_REVIEW_MODEL_ID,
    DEFAULT_CODEX_WORKER_MODEL_ID,
    build_default_provider_registry,
)

DEFAULT_ROOM_ROSTER_TEMPLATE_ID = "builtin.development"


@dataclass(frozen=True)
class RoomSetupError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class _ParticipantSpec:
    role: str
    display_name: str
    model: str
    role_template_id: str | None
    persona_snapshot: PersonaSnapshot | None


@dataclass(frozen=True)
class _RequestedParticipant:
    participant: ParticipantInit
    persona_snapshot: PersonaSnapshot | None = None


class RoomSetupService:
    """Create a durable Room and its observers without init/bootstrap artifacts."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._db_path = self._root / "chat.db"

    def create_conversation(self, request: RoomConversationCreate) -> dict[str, object]:
        if request.roster_template_id is not None and request.initial_participants is not None:
            raise RoomSetupError(
                "room_roster_conflict",
                "roster_template_id and initial_participants are mutually exclusive",
            )
        requested = self._requested_participants(request)
        specs = [self._normalize_participant(item) for item in requested]
        roles = [spec.role for spec in specs]
        if len(roles) != len(set(roles)):
            raise RoomSetupError(
                "room_participant_role_duplicate",
                "Room participant roles must be unique",
            )
        client_request_id = request.client_request_id or f"room_setup_{uuid.uuid4().hex}"
        roster_template_id = self._effective_roster_template_id(request)
        fingerprint = _request_fingerprint(
            title=request.title,
            roster_template_id=roster_template_id,
            specs=specs,
        )
        conversation_id = f"conv_{uuid.uuid4().hex}"
        created_at = _utc_now()
        created = [
            prepare_participant(
                conversation_id=conversation_id,
                role=spec.role,
                display_name=spec.display_name,
                cli_kind="codex",
                model=spec.model,
                role_template_id=spec.role_template_id,
                persona_snapshot=spec.persona_snapshot,
                created_at=created_at,
            )
            for spec in specs
        ]
        result: dict[str, object] = {
            "id": conversation_id,
            "title": request.title,
            "created_at": created_at,
            "client_request_id": client_request_id,
            "participants": [item.model_dump(mode="json") for item in created],
            "participant_sessions": [],
            "setup": {
                "schema_version": "room_setup/v2",
                "roster_template_id": roster_template_id,
                "participant_count": len(created),
                "authority": "chat.db",
            },
        }
        database = RoomDatabase(self._db_path)
        with database.connect() as conn:
            conn.execute("begin immediate")
            try:
                prior = conn.execute(
                    "select request_fingerprint, result_json from room_setup_requests "
                    "where client_request_id = ?",
                    (client_request_id,),
                ).fetchone()
                if prior is not None:
                    if prior["request_fingerprint"] != fingerprint:
                        raise RoomSetupError(
                            "room_setup_idempotency_conflict",
                            "client_request_id was already used with different Room setup",
                        )
                    replay = json.loads(prior["result_json"])
                    conn.commit()
                    return replay
                conn.execute(
                    "insert into conversations(id, title, created_at) values (?, ?, ?)",
                    (conversation_id, request.title, created_at),
                )
                for participant in created:
                    insert_participant_conn(conn, participant)
                ensure_room_memory_bindings_conn(
                    conn,
                    conversation_id=conversation_id,
                    stamp=created_at,
                )
                conn.execute(
                    """insert into room_setup_requests(
                           client_request_id, request_fingerprint, conversation_id,
                           result_json, created_at
                       ) values (?, ?, ?, ?, ?)""",
                    (
                        client_request_id,
                        fingerprint,
                        conversation_id,
                        _json(result),
                        created_at,
                    ),
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _effective_roster_template_id(
        request: RoomConversationCreate,
    ) -> str | None:
        if request.initial_participants is not None:
            return None
        return request.roster_template_id or DEFAULT_ROOM_ROSTER_TEMPLATE_ID

    def _requested_participants(
        self,
        request: RoomConversationCreate,
    ) -> list[_RequestedParticipant]:
        if request.initial_participants is not None:
            return [
                _RequestedParticipant(participant=item) for item in request.initial_participants
            ]
        template_id = request.roster_template_id or DEFAULT_ROOM_ROSTER_TEMPLATE_ID
        catalog = builtin_workroom_catalog()
        try:
            template = WorkroomRosterTemplateStore(
                self._root / "workroom_roster_templates.json"
            ).get(template_id, catalog=catalog)
            validated = validate_roster_template(template, catalog=catalog)
            participants = template_to_participant_inits(validated, catalog=catalog)
            return [
                _RequestedParticipant(
                    participant=participant,
                    persona_snapshot=persona_snapshot_for_role_profile(
                        catalog.role_profiles[binding.role_id]
                    ),
                )
                for binding, participant in zip(
                    validated.roles,
                    participants,
                    strict=True,
                )
            ]
        except KeyError as exc:
            raise RoomSetupError(
                "room_roster_not_found",
                "roster template not found",
            ) from exc
        except ValueError as exc:
            raise RoomSetupError("room_roster_invalid", str(exc)) from exc

    def _normalize_participant(self, requested: _RequestedParticipant) -> _ParticipantSpec:
        participant = requested.participant
        if (
            str(participant.provider_id or "").strip().lower() == "a2a"
            or str(participant.profile_id or "").strip().lower() == "remote"
        ):
            raise RoomSetupError(
                "room_provider_not_supported",
                "default Room participants must use the local Codex runtime",
            )
        expected_profile = provider_profile_id_for_role(participant.role)
        try:
            cli_kind = resolve_current_chat_cli_kind(
                cli_kind=participant.cli_kind,
                provider_id=participant.provider_id,
                profile_id=participant.profile_id,
                expected_profile_id=expected_profile,
                subject="Room participants",
            )
        except (TypeError, ValueError) as exc:
            raise RoomSetupError("room_participant_invalid", str(exc)) from exc
        if cli_kind != "codex":
            raise RoomSetupError(
                "room_provider_not_supported",
                "default Room participants must use the local Codex runtime",
            )
        model = participant.model or _default_model(expected_profile)
        display_name = participant.display_name or participant.role.replace("_", " ").title()
        return _ParticipantSpec(
            role=participant.role,
            display_name=display_name,
            model=model,
            role_template_id=participant.role_template_id,
            persona_snapshot=requested.persona_snapshot,
        )


def _default_model(profile_id: ProviderProfileId) -> str:
    if profile_id is ProviderProfileId.GOD:
        return DEFAULT_CODEX_GOD_MODEL_ID
    if profile_id is ProviderProfileId.REVIEW:
        return DEFAULT_CODEX_REVIEW_MODEL_ID
    if profile_id is ProviderProfileId.WORKER:
        return DEFAULT_CODEX_WORKER_MODEL_ID
    return build_default_provider_registry().get("codex.default").model_id


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_fingerprint(
    *,
    title: str,
    roster_template_id: str | None,
    specs: list[_ParticipantSpec],
) -> str:
    payload = {
        "title": title,
        "roster_template_id": roster_template_id,
        "participants": [
            {
                "role": item.role,
                "display_name": item.display_name,
                "model": item.model,
                "role_template_id": item.role_template_id,
                "persona_snapshot": (
                    item.persona_snapshot.model_dump(mode="json")
                    if item.persona_snapshot is not None
                    else None
                ),
                "provider_id": "codex",
                "cli_kind": "codex",
            }
            for item in specs
        ],
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
