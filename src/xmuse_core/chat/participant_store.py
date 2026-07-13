"""SQLite-backed durable Room participant identities."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.providers.models import ProviderId, ProviderProfileId
from xmuse_core.providers.registry import normalize_codex_model_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Pydantic models (match FRONTEND_API.md participant/role-template shapes)
# ---------------------------------------------------------------------------

CurrentChatCliKind = Literal["codex"]
StoredChatCliKind = Literal["codex", "a2a", "opencode"]
StoredProviderIdValue = ProviderId | Literal["a2a", "opencode"]
INIT_GOD_ROLE = "init"
INIT_GOD_DISPLAY_NAME = "init-god"
_CURRENT_CHAT_CLI_KINDS = {"codex"}
_STORED_ONLY_CLI_KINDS = {"a2a", "opencode"}
_STORED_CHAT_CLI_KINDS = _CURRENT_CHAT_CLI_KINDS | _STORED_ONLY_CLI_KINDS
PERSONA_SNAPSHOT_SCHEMA: Literal["persona_snapshot/v1"] = "persona_snapshot/v1"
MAX_PERSONA_SNAPSHOT_BYTES = 2 * 1024


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PersonaSnapshot(BaseModel):
    """Server-authored, immutable participant collaboration identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["persona_snapshot/v1"] = PERSONA_SNAPSHOT_SCHEMA
    role_description: str = Field(min_length=1)
    collaboration_focus: str = Field(min_length=1)

    @field_validator("role_description", "collaboration_focus", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("persona text must not be blank")
            return stripped
        return value

    @model_validator(mode="after")
    def _bounded(self) -> PersonaSnapshot:
        if len(persona_snapshot_json(self).encode("utf-8")) > MAX_PERSONA_SNAPSHOT_BYTES:
            raise ValueError("persona_snapshot_too_large")
        return self


def persona_snapshot_json(snapshot: PersonaSnapshot) -> str:
    return _canonical_json(snapshot.model_dump(mode="json"))


def persona_snapshot_digest(snapshot: PersonaSnapshot) -> str:
    return f"sha256:{sha256(persona_snapshot_json(snapshot).encode('utf-8')).hexdigest()}"


def _require_stored_cli_kind(cli_kind: str) -> StoredChatCliKind:
    normalized = cli_kind.strip().lower()
    if normalized not in _STORED_CHAT_CLI_KINDS:
        raise ValueError(f"unsupported xmuse chat participant cli_kind: {cli_kind!r}")
    return normalized  # type: ignore[return-value]


def _require_current_cli_kind(cli_kind: str) -> CurrentChatCliKind:
    normalized = _require_stored_cli_kind(cli_kind)
    if normalized not in _CURRENT_CHAT_CLI_KINDS:
        raise ValueError("xmuse Room participant writes support only cli_kind 'codex'")
    return cast(CurrentChatCliKind, normalized)


def _read_cli_kind(cli_kind: str) -> StoredChatCliKind:
    normalized = cli_kind.strip().lower()
    if normalized in _STORED_CHAT_CLI_KINDS:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"unsupported stored xmuse chat participant cli_kind: {cli_kind!r}")


def _read_model(
    cli_kind: str,
    model: str,
    *,
    profile_id: ProviderProfileId,
) -> str:
    raw_cli_kind = cli_kind.strip().lower()
    return _normalize_model_for_cli_kind(
        _read_cli_kind(raw_cli_kind),
        model,
        profile_id=profile_id,
    )


def _normalize_model_for_cli_kind(
    cli_kind: StoredChatCliKind,
    model: str | None,
    *,
    profile_id: ProviderProfileId,
) -> str:
    if cli_kind == "codex":
        return normalize_codex_model_id(model, profile_id=profile_id)
    normalized = (model or "").strip()
    if not normalized:
        raise ValueError("non-codex chat participants require an explicit model")
    return normalized


def provider_profile_id_for_role(role: str) -> ProviderProfileId:
    if role in {"architect", INIT_GOD_ROLE}:
        return ProviderProfileId.GOD
    if role == "review":
        return ProviderProfileId.REVIEW
    if role == "execute":
        return ProviderProfileId.WORKER
    return ProviderProfileId.DEFAULT


def provider_profile_id_for_cli_kind_role(
    cli_kind: StoredChatCliKind,
    role: str,
) -> ProviderProfileId:
    return provider_profile_id_for_role(role)


def provider_id_for_cli_kind(cli_kind: StoredChatCliKind) -> StoredProviderIdValue:
    if cli_kind == "opencode":
        return "opencode"
    if cli_kind == "a2a":
        return "a2a"
    return ProviderId.CODEX


def resolve_current_chat_cli_kind(
    *,
    cli_kind: str | None,
    provider_id: StoredProviderIdValue | str | None,
    profile_id: ProviderProfileId | str | None,
    expected_profile_id: ProviderProfileId,
    subject: str,
) -> CurrentChatCliKind:
    resolved = _resolve_chat_cli_kind(
        cli_kind=cli_kind,
        provider_id=provider_id,
        profile_id=profile_id,
        expected_profile_id=expected_profile_id,
        subject=subject,
    )
    if resolved != "codex":
        raise ValueError(f"{subject} supports only the local Codex provider")
    return resolved


def _resolve_chat_cli_kind(
    *,
    cli_kind: str | None,
    provider_id: StoredProviderIdValue | str | None,
    profile_id: ProviderProfileId | str | None,
    expected_profile_id: ProviderProfileId,
    subject: str,
) -> StoredChatCliKind:
    normalized_cli_kind = (
        _require_stored_cli_kind(cli_kind.strip()) if isinstance(cli_kind, str) else None
    )
    normalized_provider_id = _parse_provider_id(provider_id)
    normalized_profile_id = _parse_profile_id(profile_id)

    if normalized_provider_id is None and normalized_profile_id is not None:
        normalized_provider_id = ProviderId.CODEX
    if normalized_provider_id is None and normalized_cli_kind is not None:
        normalized_provider_id = provider_id_for_cli_kind(normalized_cli_kind)
    if normalized_cli_kind is None and normalized_provider_id is not None:
        normalized_cli_kind = _cli_kind_for_provider_id(normalized_provider_id)

    if normalized_provider_id is not None and normalized_cli_kind is not None:
        expected_provider_id = provider_id_for_cli_kind(normalized_cli_kind)
        if normalized_provider_id != expected_provider_id:
            raise ValueError(
                f"{subject} must use provider_id {_provider_id_value(expected_provider_id)!r}, "
                f"got {_provider_id_value(normalized_provider_id)!r}"
            )
    effective_expected_profile_id = expected_profile_id
    if (
        normalized_profile_id is not None
        and normalized_profile_id is not effective_expected_profile_id
    ):
        raise ValueError(
            f"{subject} must use profile_id {effective_expected_profile_id.value!r}, "
            f"got {normalized_profile_id.value!r}"
        )

    if normalized_cli_kind is not None:
        return normalized_cli_kind
    if normalized_provider_id == "opencode":
        return "opencode"
    return "codex"


def _cli_kind_for_provider_id(provider_id: StoredProviderIdValue) -> StoredChatCliKind:
    if provider_id == "opencode":
        return "opencode"
    if provider_id == "a2a":
        return "a2a"
    return "codex"


def _parse_provider_id(
    value: StoredProviderIdValue | str | None,
) -> StoredProviderIdValue | None:
    if value is None:
        return None
    if isinstance(value, ProviderId):
        return value
    normalized = value.strip().lower()
    if normalized in {"a2a", "opencode"}:
        return normalized  # type: ignore[return-value]
    return ProviderId(normalized)


def _provider_id_value(provider_id: StoredProviderIdValue) -> str:
    if isinstance(provider_id, ProviderId):
        return provider_id.value
    return provider_id


def _parse_profile_id(value: ProviderProfileId | str | None) -> ProviderProfileId | None:
    if value is None:
        return None
    if isinstance(value, ProviderProfileId):
        return value
    return ProviderProfileId(value.strip())


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    participant_id: str
    conversation_id: str
    role: str
    display_name: str
    provider_id: StoredProviderIdValue
    profile_id: ProviderProfileId
    cli_kind: StoredChatCliKind
    model: str
    role_template_id: str | None
    persona_snapshot: PersonaSnapshot | None = None
    persona_snapshot_sha256: str | None = None
    status: Literal["active", "stopped"]
    last_seen_at: str | None
    created_at: str

    @model_validator(mode="after")
    def _persona_binding_is_valid(self) -> Participant:
        if self.persona_snapshot is None:
            if self.persona_snapshot_sha256 is not None:
                raise ValueError("participant_persona_snapshot_missing")
            return self
        expected = persona_snapshot_digest(self.persona_snapshot)
        if self.persona_snapshot_sha256 != expected:
            raise ValueError("participant_persona_snapshot_digest_mismatch")
        return self


def prepare_participant(
    *,
    conversation_id: str,
    role: str,
    display_name: str,
    cli_kind: CurrentChatCliKind,
    model: str,
    role_template_id: str | None = None,
    persona_snapshot: PersonaSnapshot | dict[str, Any] | None = None,
    status: Literal["active", "stopped"] = "active",
    participant_id: str | None = None,
    created_at: str | None = None,
) -> Participant:
    """Build and validate a participant without opening a database connection."""

    normalized_cli_kind = _require_current_cli_kind(cli_kind)
    profile_id = provider_profile_id_for_cli_kind_role(normalized_cli_kind, role)
    normalized_persona = (
        PersonaSnapshot.model_validate(persona_snapshot) if persona_snapshot is not None else None
    )
    return Participant(
        participant_id=participant_id or _new_id("part"),
        conversation_id=conversation_id,
        role=role,
        display_name=display_name,
        provider_id=provider_id_for_cli_kind(normalized_cli_kind),
        profile_id=profile_id,
        cli_kind=normalized_cli_kind,
        model=_normalize_model_for_cli_kind(
            normalized_cli_kind,
            model,
            profile_id=profile_id,
        ),
        role_template_id=role_template_id,
        persona_snapshot=normalized_persona,
        persona_snapshot_sha256=(
            persona_snapshot_digest(normalized_persona) if normalized_persona is not None else None
        ),
        status=status,
        last_seen_at=None,
        created_at=created_at or _utc_now(),
    )


def insert_participant_conn(conn: sqlite3.Connection, participant: Participant) -> None:
    """Insert a prepared participant in the caller-owned transaction."""

    columns = {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1])
        for row in conn.execute("pragma table_info(participants)").fetchall()
    }
    values: list[object] = [
        participant.participant_id,
        participant.conversation_id,
        participant.role,
        participant.display_name,
        participant.cli_kind,
        participant.model,
        participant.role_template_id,
    ]
    insert_columns = [
        "participant_id",
        "conversation_id",
        "role",
        "display_name",
        "cli_kind",
        "model",
        "role_template_id",
    ]
    if {"persona_snapshot_json", "persona_snapshot_sha256"} <= columns:
        insert_columns.extend(("persona_snapshot_json", "persona_snapshot_sha256"))
        values.extend(
            (
                persona_snapshot_json(participant.persona_snapshot)
                if participant.persona_snapshot is not None
                else None,
                participant.persona_snapshot_sha256,
            )
        )
    elif participant.persona_snapshot is not None:
        raise ValueError("participant_persona_schema_unavailable")
    insert_columns.extend(("status", "last_seen_at", "created_at"))
    values.extend((participant.status, participant.last_seen_at, participant.created_at))
    placeholders = ", ".join("?" for _ in insert_columns)
    conn.execute(
        f"insert into participants ({', '.join(insert_columns)}) values ({placeholders})",
        values,
    )


def participant_summary(participant: Participant) -> dict[str, Any]:
    return {
        "participant_id": participant.participant_id,
        "role": participant.role,
        "display_name": participant.display_name,
        "provider_id": participant.provider_id,
        "profile_id": participant.profile_id,
        "cli_kind": participant.cli_kind,
        "model": participant.model,
        "persona_snapshot": (
            participant.persona_snapshot.model_dump(mode="json")
            if participant.persona_snapshot is not None
            else None
        ),
        "persona_snapshot_sha256": participant.persona_snapshot_sha256,
        "status": participant.status,
    }


# ---------------------------------------------------------------------------
# ParticipantStore
# ---------------------------------------------------------------------------


class ParticipantStore:
    """CRUD store for the `participants` table in chat.db."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        *,
        conversation_id: str,
        role: str,
        display_name: str,
        cli_kind: CurrentChatCliKind,
        model: str,
        role_template_id: str | None = None,
        persona_snapshot: PersonaSnapshot | dict[str, Any] | None = None,
        status: Literal["active", "stopped"] = "active",
    ) -> Participant:
        participant = prepare_participant(
            conversation_id=conversation_id,
            role=role,
            display_name=display_name,
            cli_kind=cli_kind,
            model=model,
            role_template_id=role_template_id,
            persona_snapshot=persona_snapshot,
            status=status,
        )
        with self._connect() as conn:
            if role == INIT_GOD_ROLE:
                self._assert_init_god_available(conn, conversation_id)
            insert_participant_conn(conn, participant)
        return participant

    def ensure_init_god(
        self,
        *,
        conversation_id: str,
        model: str,
        cli_kind: CurrentChatCliKind = "codex",
        display_name: str = INIT_GOD_DISPLAY_NAME,
        role_template_id: str | None = None,
        persona_snapshot: PersonaSnapshot | dict[str, Any] | None = None,
    ) -> Participant:
        normalized_cli_kind = _require_current_cli_kind(cli_kind)
        profile_id = provider_profile_id_for_cli_kind_role(
            normalized_cli_kind,
            INIT_GOD_ROLE,
        )
        normalized_model = _normalize_model_for_cli_kind(
            normalized_cli_kind,
            model,
            profile_id=profile_id,
        )
        normalized_persona = (
            PersonaSnapshot.model_validate(persona_snapshot)
            if persona_snapshot is not None
            else None
        )
        existing = self._find_init_god(conversation_id)
        if existing is not None:
            if (
                existing.display_name != display_name
                or existing.cli_kind != normalized_cli_kind
                or existing.model != normalized_model
                or existing.role_template_id != role_template_id
                or existing.persona_snapshot != normalized_persona
            ):
                raise ValueError(
                    "existing init god participant does not match requested identity/config"
                )
            if existing.status != "active":
                return self.update_status(existing.participant_id, "active")
            return existing
        return self.add(
            conversation_id=conversation_id,
            role=INIT_GOD_ROLE,
            display_name=display_name,
            cli_kind=normalized_cli_kind,
            model=normalized_model,
            role_template_id=role_template_id,
            persona_snapshot=normalized_persona,
        )

    def ensure_bootstrap_participant(
        self,
        *,
        conversation_id: str,
        role: str,
        display_name: str,
        cli_kind: CurrentChatCliKind,
        model: str,
        role_template_id: str | None = None,
        persona_snapshot: PersonaSnapshot | dict[str, Any] | None = None,
    ) -> Participant:
        normalized_cli_kind = _require_current_cli_kind(cli_kind)
        profile_id = provider_profile_id_for_cli_kind_role(normalized_cli_kind, role)
        normalized_model = _normalize_model_for_cli_kind(
            normalized_cli_kind,
            model,
            profile_id=profile_id,
        )
        normalized_persona = (
            PersonaSnapshot.model_validate(persona_snapshot)
            if persona_snapshot is not None
            else None
        )
        existing = self._find_bootstrap_participant(
            conversation_id=conversation_id,
            role=role,
            display_name=display_name,
        )
        if existing is not None:
            if (
                existing.cli_kind != normalized_cli_kind
                or existing.model != normalized_model
                or existing.role_template_id != role_template_id
                or existing.persona_snapshot != normalized_persona
            ):
                raise ValueError(
                    "existing bootstrap participant does not match requested identity/config"
                )
            if existing.status != "active":
                return self.update_status(existing.participant_id, "active")
            return existing
        return self.add(
            conversation_id=conversation_id,
            role=role,
            display_name=display_name,
            cli_kind=normalized_cli_kind,
            model=normalized_model,
            role_template_id=role_template_id,
            persona_snapshot=normalized_persona,
        )

    def get(self, participant_id: str) -> Participant:
        with self._connect() as conn:
            row = conn.execute(
                "select * from participants where participant_id = ?",
                (participant_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown participant: {participant_id}")
        return self._from_row(row)

    def list_by_conversation(self, conversation_id: str) -> list[Participant]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from participants
                where conversation_id = ?
                order by rowid asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def update_status(
        self,
        participant_id: str,
        status: Literal["active", "stopped"],
        last_seen_at: str | None = None,
    ) -> Participant:
        now = last_seen_at or _utc_now()
        with self._connect() as conn:
            participant = conn.execute(
                "select cli_kind from participants where participant_id = ?",
                (participant_id,),
            ).fetchone()
            if participant is not None and status == "active":
                _require_current_cli_kind(str(participant["cli_kind"]))
            conn.execute(
                """
                update participants
                set status = ?, last_seen_at = ?
                where participant_id = ?
                """,
                (status, now, participant_id),
            )
        return self.get(participant_id)

    def delete(self, participant_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "delete from participants where participant_id = ?",
                (participant_id,),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        return RoomDatabase(self._path).connect()

    def _from_row(self, row: sqlite3.Row) -> Participant:
        d = dict(row)
        cli_kind = _read_cli_kind(d["cli_kind"])
        profile_id = provider_profile_id_for_cli_kind_role(cli_kind, d["role"])
        raw_persona = d.get("persona_snapshot_json")
        persona = (
            PersonaSnapshot.model_validate(json.loads(raw_persona))
            if isinstance(raw_persona, str) and raw_persona.strip()
            else None
        )
        return Participant(
            participant_id=d["participant_id"],
            conversation_id=d["conversation_id"],
            role=d["role"],
            display_name=d["display_name"],
            provider_id=provider_id_for_cli_kind(cli_kind),
            profile_id=profile_id,
            cli_kind=cli_kind,
            model=_read_model(d["cli_kind"], d["model"], profile_id=profile_id),
            role_template_id=d.get("role_template_id"),
            persona_snapshot=persona,
            persona_snapshot_sha256=d.get("persona_snapshot_sha256"),
            status=d["status"],
            last_seen_at=d.get("last_seen_at"),
            created_at=d["created_at"],
        )

    def _find_init_god(self, conversation_id: str) -> Participant | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from participants
                where conversation_id = ? and role = ?
                order by rowid asc
                """,
                (conversation_id, INIT_GOD_ROLE),
            ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(
                f"duplicate init god participant for conversation_id: {conversation_id}"
            )
        return self._from_row(rows[0])

    def _find_bootstrap_participant(
        self,
        *,
        conversation_id: str,
        role: str,
        display_name: str,
    ) -> Participant | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from participants
                where conversation_id = ? and role = ? and display_name = ?
                order by rowid asc
                """,
                (conversation_id, role, display_name),
            ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(
                "duplicate bootstrap participant for "
                f"conversation_id={conversation_id}, role={role}, "
                f"display_name={display_name}"
            )
        return self._from_row(rows[0])

    def _assert_init_god_available(
        self,
        conn: sqlite3.Connection,
        conversation_id: str,
    ) -> None:
        row = conn.execute(
            """
            select participant_id from participants
            where conversation_id = ? and role = ?
            limit 1
            """,
            (conversation_id, INIT_GOD_ROLE),
        ).fetchone()
        if row is not None:
            raise ValueError(
                f"duplicate init god participant for conversation_id: {conversation_id}"
            )
