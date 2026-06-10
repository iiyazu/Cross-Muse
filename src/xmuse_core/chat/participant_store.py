"""SQLite-backed stores for chat participants and role templates.

Participant and RoleTemplate Pydantic models match the type signatures in
xmuse/FRONTEND_VISION.md (Layer 1 contract).  The stores share the same
chat.db connection that ChatStore uses; they are initialised by ChatStore._init_db
via two CREATE TABLE IF NOT EXISTS statements added there.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from xmuse_core.providers.models import ProviderId, ProviderProfileId
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    DEFAULT_CODEX_REVIEW_MODEL_ID,
    DEFAULT_CODEX_WORKER_MODEL_ID,
    normalize_codex_model_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Pydantic models (match FRONTEND_VISION.md type signatures exactly)
# ---------------------------------------------------------------------------

CliKind = Literal["codex", "opencode"]
INIT_GOD_ROLE = "init"
INIT_GOD_DISPLAY_NAME = "init-god"


def _require_supported_cli_kind(cli_kind: str) -> CliKind:
    normalized = cli_kind.strip()
    if normalized not in {"codex", "opencode"}:
        raise ValueError(f"unsupported xmuse chat participant cli_kind: {cli_kind!r}")
    return normalized  # type: ignore[return-value]


def _read_cli_kind(cli_kind: str) -> CliKind:
    normalized = cli_kind.strip().lower()
    if normalized == "opencode":
        return "opencode"
    # Older chat.db files may contain unsupported runtime ids. Fall back to the
    # closest supported runtime instead of making old conversations unloadable.
    return "codex"


def _read_model(
    cli_kind: str,
    model: str,
    *,
    profile_id: ProviderProfileId,
) -> str:
    return _normalize_model_for_cli_kind(
        _read_cli_kind(cli_kind),
        model,
        profile_id=profile_id,
    )


def _normalize_model_for_cli_kind(
    cli_kind: CliKind,
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


def provider_profile_id_for_template_slug(slug: str) -> ProviderProfileId:
    if slug == "architect":
        return ProviderProfileId.GOD
    if slug == "review":
        return ProviderProfileId.REVIEW
    if slug == "execute":
        return ProviderProfileId.WORKER
    return ProviderProfileId.DEFAULT


def provider_id_for_cli_kind(cli_kind: CliKind) -> ProviderId:
    if cli_kind == "opencode":
        return ProviderId.OPENCODE
    return ProviderId.CODEX


def resolve_codex_cli_kind(
    *,
    cli_kind: str | None,
    provider_id: ProviderId | str | None,
    profile_id: ProviderProfileId | str | None,
    expected_profile_id: ProviderProfileId,
    subject: str,
) -> CliKind:
    normalized_cli_kind = (
        _require_supported_cli_kind(cli_kind.strip()) if isinstance(cli_kind, str) else None
    )
    normalized_provider_id = _parse_provider_id(provider_id)
    normalized_profile_id = _parse_profile_id(profile_id)

    if normalized_provider_id is None and normalized_profile_id is not None:
        normalized_provider_id = ProviderId.CODEX
    if normalized_provider_id is None and normalized_cli_kind is not None:
        normalized_provider_id = provider_id_for_cli_kind(normalized_cli_kind)

    if normalized_provider_id is not None and normalized_cli_kind is not None:
        expected_provider_id = provider_id_for_cli_kind(normalized_cli_kind)
        if normalized_provider_id is not expected_provider_id:
            raise ValueError(
                f"{subject} must use provider_id {expected_provider_id.value!r}, "
                f"got {normalized_provider_id.value!r}"
            )
    if normalized_profile_id is not None and normalized_profile_id is not expected_profile_id:
        raise ValueError(
            f"{subject} must use profile_id {expected_profile_id.value!r}, "
            f"got {normalized_profile_id.value!r}"
        )

    if normalized_cli_kind is not None:
        return normalized_cli_kind
    if normalized_provider_id is ProviderId.OPENCODE:
        return "opencode"
    return "codex"


def _parse_provider_id(value: ProviderId | str | None) -> ProviderId | None:
    if value is None:
        return None
    if isinstance(value, ProviderId):
        return value
    return ProviderId(value.strip())


def _parse_profile_id(value: ProviderProfileId | str | None) -> ProviderProfileId | None:
    if value is None:
        return None
    if isinstance(value, ProviderProfileId):
        return value
    return ProviderProfileId(value.strip())


class Participant(BaseModel):
    participant_id: str
    conversation_id: str
    role: str
    display_name: str
    provider_id: ProviderId
    profile_id: ProviderProfileId
    cli_kind: CliKind
    model: str
    role_template_id: str | None
    status: Literal["active", "stopped"]
    last_seen_at: str | None
    created_at: str


def participant_summary(participant: Participant) -> dict[str, str]:
    return {
        "participant_id": participant.participant_id,
        "role": participant.role,
        "display_name": participant.display_name,
        "provider_id": participant.provider_id,
        "profile_id": participant.profile_id,
        "cli_kind": participant.cli_kind,
        "model": participant.model,
        "status": participant.status,
    }


class RoleTemplate(BaseModel):
    id: str
    slug: str
    display_name: str
    prompt: str
    provider_id: ProviderId
    profile_id: ProviderProfileId
    cli_kind: CliKind
    default_model: str
    predefined: bool
    created_at: str
    updated_at: str


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
        cli_kind: CliKind,
        model: str,
        role_template_id: str | None = None,
        status: Literal["active", "stopped"] = "active",
    ) -> Participant:
        normalized_cli_kind = _require_supported_cli_kind(cli_kind)
        profile_id = provider_profile_id_for_role(role)
        participant = Participant(
            participant_id=_new_id("part"),
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
            status=status,
            last_seen_at=None,
            created_at=_utc_now(),
        )
        with self._connect() as conn:
            if role == INIT_GOD_ROLE:
                self._assert_init_god_available(conn, conversation_id)
            conn.execute(
                """
                insert into participants (
                    participant_id, conversation_id, role, display_name,
                    cli_kind, model, role_template_id, status,
                    last_seen_at, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    participant.participant_id,
                    participant.conversation_id,
                    participant.role,
                    participant.display_name,
                    participant.cli_kind,
                    participant.model,
                    participant.role_template_id,
                    participant.status,
                    participant.last_seen_at,
                    participant.created_at,
                ),
            )
        return participant

    def ensure_init_god(
        self,
        *,
        conversation_id: str,
        model: str,
        cli_kind: CliKind = "codex",
        display_name: str = INIT_GOD_DISPLAY_NAME,
        role_template_id: str | None = None,
    ) -> Participant:
        normalized_model = _normalize_model_for_cli_kind(
            cli_kind,
            model,
            profile_id=ProviderProfileId.GOD,
        )
        existing = self._find_init_god(conversation_id)
        if existing is not None:
            if (
                existing.display_name != display_name
                or existing.cli_kind != cli_kind
                or existing.model != normalized_model
                or existing.role_template_id != role_template_id
            ):
                raise ValueError(
                    "existing init god participant does not match requested "
                    "identity/config"
                )
            if existing.status != "active":
                return self.update_status(existing.participant_id, "active")
            return existing
        return self.add(
            conversation_id=conversation_id,
            role=INIT_GOD_ROLE,
            display_name=display_name,
            cli_kind=cli_kind,
            model=normalized_model,
            role_template_id=role_template_id,
        )

    def ensure_bootstrap_participant(
        self,
        *,
        conversation_id: str,
        role: str,
        display_name: str,
        cli_kind: CliKind,
        model: str,
        role_template_id: str | None = None,
    ) -> Participant:
        normalized_model = _normalize_model_for_cli_kind(
            cli_kind,
            model,
            profile_id=provider_profile_id_for_role(role),
        )
        existing = self._find_bootstrap_participant(
            conversation_id=conversation_id,
            role=role,
            display_name=display_name,
        )
        if existing is not None:
            if (
                existing.cli_kind != cli_kind
                or existing.model != normalized_model
                or existing.role_template_id != role_template_id
            ):
                raise ValueError(
                    "existing bootstrap participant does not match requested "
                    "identity/config"
                )
            if existing.status != "active":
                return self.update_status(existing.participant_id, "active")
            return existing
        return self.add(
            conversation_id=conversation_id,
            role=role,
            display_name=display_name,
            cli_kind=cli_kind,
            model=normalized_model,
            role_template_id=role_template_id,
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
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _from_row(self, row: sqlite3.Row) -> Participant:
        d = dict(row)
        profile_id = provider_profile_id_for_role(d["role"])
        return Participant(
            participant_id=d["participant_id"],
            conversation_id=d["conversation_id"],
            role=d["role"],
            display_name=d["display_name"],
            provider_id=provider_id_for_cli_kind(_read_cli_kind(d["cli_kind"])),
            profile_id=profile_id,
            cli_kind=_read_cli_kind(d["cli_kind"]),
            model=_read_model(d["cli_kind"], d["model"], profile_id=profile_id),
            role_template_id=d.get("role_template_id"),
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


# ---------------------------------------------------------------------------
# RoleTemplateStore
# ---------------------------------------------------------------------------

# Prompts for 'architect' and 'review' are sourced from
# xmuse_core/chat/driver.py:_ROLE_PROMPTS and kept here verbatim so the store
# can seed them without importing the driver.
#
# NOTE: 'execute' is NOT present in driver.py:_ROLE_PROMPTS (driver.py only
# defines architect and review).  The execute prompt below was authored here
# directly.  A future lane that wires ChatDriver to ParticipantStore should
# reconcile the two by adding 'execute' to driver.py:_ROLE_PROMPTS and
# sourcing it from there.
_PREDEFINED_TEMPLATES: list[dict] = [
    {
        "slug": "architect",
        "display_name": "Architect GOD",
        "prompt": (
            "You are the Architect GOD of xmuse, a multi-agent autonomous "
            "delivery system. You participate in a group chat with a human "
            "operator and other GODs (review, etc).\n\n"
            "Your job: read the conversation, understand what the human or "
            "another GOD is asking for, and respond. You may:\n"
            "- ask a clarifying question\n"
            "- propose a concrete next step\n"
            "- @mention another GOD if their input is needed\n"
            "- emit a structured proposal that, when approved, becomes a lane "
            "graph the platform will execute\n\n"
            "Output format (strict): emit ONE of:\n"
            '  {"type": "message", "text": "<reply text>"}\n'
            '  {"type": "mention", "to": "review", "text": "<reply text>"}\n'
            '  {"type": "proposal", "summary": "<short>", "lanes": [{"feature_id": "...", '
            '"prompt": "...", "depends_on": [], "capabilities": ["code"], '
            '"feature_group": "..."}]}\n\n'
            "Always output ONLY the JSON object, no markdown fence, no commentary. "
            "If unsure, emit type=message asking for clarification."
        ),
        "cli_kind": "codex",
        "default_model": DEFAULT_CODEX_GOD_MODEL_ID,
    },
    {
        "slug": "review",
        "display_name": "Review GOD",
        "prompt": (
            "You are the Review GOD of xmuse. You participate in the group "
            "chat to evaluate proposals from the architect or human.\n\n"
            "When you respond, emit ONE of:\n"
            '  {"type": "message", "text": "<reply text>"}\n'
            '  {"type": "verdict", "decision": "approve"|"narrow"|"reject", '
            '"rationale": "<short>"}\n\n'
            "Always output ONLY the JSON object, no markdown fence, no commentary."
        ),
        "cli_kind": "codex",
        "default_model": DEFAULT_CODEX_REVIEW_MODEL_ID,
    },
    {
        "slug": "execute",
        "display_name": "Execute GOD",
        "prompt": (
            "You are the Execute GOD of xmuse. You implement lanes inside the "
            "worktree. You do not escape the sandbox or run arbitrary shell "
            "commands outside the allowed tool set.\n\n"
            "When you respond, emit ONE of:\n"
            '  {"type": "message", "text": "<status update>"}\n'
            '  {"type": "execute_feasibility_verdict", "status": "executable", '
            '"summary": "<why this can be dispatched>", '
            '"evidence_refs": ["<proposal/artifact/blocker refs>"]}\n'
            '  {"type": "execute_feasibility_verdict", "status": "blocked", '
            '"summary": "<why dispatch is blocked>", '
            '"evidence_refs": ["<proposal/artifact/blocker refs>"]}\n'
            '  {"type": "done", "summary": "<what was implemented>"}\n\n'
            "Use execute_feasibility_verdict when asked to confirm whether a "
            "collaboration proposal can enter real-provider dispatch. "
            "Executable verdicts require at least one concrete evidence ref. "
            "Always output ONLY the JSON object, no markdown fence, no commentary."
        ),
        "cli_kind": "codex",
        "default_model": DEFAULT_CODEX_WORKER_MODEL_ID,
    },
]


def _predefined_template_needs_refresh(
    row: sqlite3.Row,
    template: dict,
) -> bool:
    return any(
        row[field] != template[field]
        for field in ("display_name", "prompt", "cli_kind", "default_model")
    )


class RoleTemplateStore:
    """CRUD store for the `role_templates` table in chat.db.

    On first init the three predefined templates (architect, review, execute)
    are seeded automatically.  Predefined templates cannot be deleted via
    :meth:`delete` (raises ``ValueError``).
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._seed_predefined()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_all(self) -> list[RoleTemplate]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from role_templates order by rowid asc"
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def get(self, template_id: str) -> RoleTemplate:
        with self._connect() as conn:
            row = conn.execute(
                "select * from role_templates where id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown role_template: {template_id}")
        return self._from_row(row)

    def get_by_slug(self, slug: str) -> RoleTemplate | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from role_templates where slug = ?",
                (slug,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def create(
        self,
        *,
        slug: str,
        display_name: str,
        prompt: str,
        cli_kind: CliKind,
        default_model: str,
    ) -> RoleTemplate:
        profile_id = provider_profile_id_for_template_slug(slug)
        now = _utc_now()
        normalized_cli_kind = _require_supported_cli_kind(cli_kind)
        template = RoleTemplate(
            id=_new_id("tmpl"),
            slug=slug,
            display_name=display_name,
            prompt=prompt,
            provider_id=provider_id_for_cli_kind(normalized_cli_kind),
            profile_id=profile_id,
            cli_kind=normalized_cli_kind,
            default_model=_normalize_model_for_cli_kind(
                normalized_cli_kind,
                default_model,
                profile_id=profile_id,
            ),
            predefined=False,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into role_templates (
                    id, slug, display_name, prompt, cli_kind,
                    default_model, predefined, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template.id,
                    template.slug,
                    template.display_name,
                    template.prompt,
                    template.cli_kind,
                    template.default_model,
                    1 if template.predefined else 0,
                    template.created_at,
                    template.updated_at,
                ),
            )
        return template

    def update(
        self,
        template_id: str,
        *,
        display_name: str | None = None,
        prompt: str | None = None,
        cli_kind: CliKind | None = None,
        default_model: str | None = None,
    ) -> RoleTemplate:
        existing = self.get(template_id)
        now = _utc_now()
        new_display_name = display_name if display_name is not None else existing.display_name
        new_prompt = prompt if prompt is not None else existing.prompt
        new_cli_kind = (
            _require_supported_cli_kind(cli_kind)
            if cli_kind is not None
            else existing.cli_kind
        )
        new_default_model = _normalize_model_for_cli_kind(
            new_cli_kind,
            default_model if default_model is not None else existing.default_model,
            profile_id=existing.profile_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                update role_templates
                set display_name = ?, prompt = ?, cli_kind = ?,
                    default_model = ?, updated_at = ?
                where id = ?
                """,
                (new_display_name, new_prompt, new_cli_kind, new_default_model, now, template_id),
            )
        return self.get(template_id)

    def delete(self, template_id: str) -> None:
        existing = self.get(template_id)
        if existing.predefined:
            raise ValueError(f"cannot delete predefined role template: {existing.slug!r}")
        with self._connect() as conn:
            conn.execute("delete from role_templates where id = ?", (template_id,))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _seed_predefined(self) -> None:
        """Insert the three builtin templates if they are not yet present."""
        now = _utc_now()
        with self._connect() as conn:
            for tpl in _PREDEFINED_TEMPLATES:
                existing = conn.execute(
                    "select * from role_templates where slug = ?",
                    (tpl["slug"],),
                ).fetchone()
                if existing is not None:
                    if bool(existing["predefined"]) and _predefined_template_needs_refresh(
                        existing,
                        tpl,
                    ):
                        conn.execute(
                            """
                            update role_templates
                            set display_name = ?,
                                prompt = ?,
                                cli_kind = ?,
                                default_model = ?,
                                predefined = 1,
                                updated_at = ?
                            where id = ?
                            """,
                            (
                                tpl["display_name"],
                                tpl["prompt"],
                                tpl["cli_kind"],
                                tpl["default_model"],
                                now,
                                existing["id"],
                            ),
                        )
                    continue
                conn.execute(
                    """
                    insert into role_templates (
                        id, slug, display_name, prompt, cli_kind,
                        default_model, predefined, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("tmpl"),
                        tpl["slug"],
                        tpl["display_name"],
                        tpl["prompt"],
                        tpl["cli_kind"],
                        tpl["default_model"],
                        1,  # predefined = true
                        now,
                        now,
                    ),
                )

    def _from_row(self, row: sqlite3.Row) -> RoleTemplate:
        d = dict(row)
        profile_id = provider_profile_id_for_template_slug(d["slug"])
        return RoleTemplate(
            id=d["id"],
            slug=d["slug"],
            display_name=d["display_name"],
            prompt=d["prompt"],
                provider_id=provider_id_for_cli_kind(_read_cli_kind(d["cli_kind"])),
                profile_id=profile_id,
                cli_kind=_read_cli_kind(d["cli_kind"]),
            default_model=_read_model(
                d["cli_kind"],
                d["default_model"],
                profile_id=profile_id,
            ),
            predefined=bool(d["predefined"]),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )
