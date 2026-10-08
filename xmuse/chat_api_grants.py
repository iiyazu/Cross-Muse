"""HTTP surface for scoped plugin grants.

Contracts ``plugin_grant_v1`` and ``main_window_control_v1``. Operator routes
require the operator token. Plugin routes authenticate only with
``Authorization: Bearer`` grant secrets (exchange excepted); the operator header
is never read there. Every plugin route refuses requests with an ``Origin``
header (403) and every plugin route with a body refuses a non-JSON
``Content-Type`` (415) before anything else. Check order after that: bearer
(401), scope (403), body (422), Room membership (404), the action's own rules.
Error messages are static: they never echo request bodies or headers.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from xmuse.chat_api_room_messages import post_room_human_message
from xmuse.chat_api_room_setup import (
    ProviderCapabilitiesProvider,
    create_admitted_room,
    room_setup_http_error,
)
from xmuse.chat_api_runtime import WorkroomRuntimeStarter
from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.participant_store import WORKSPACE_WRITE_CLI_KINDS, ParticipantStore
from xmuse_core.chat.room_api_models import (
    ParticipantInit,
    RoomCollaborationInit,
    RoomConversationCreate,
    ThreadMessageCreate,
)
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_board import RoomBoardStore
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_plugin_grants import (
    SCOPE_BOARD_REVIEW_DECIDE,
    SCOPE_BOARD_SPLIT_DECIDE,
    SCOPE_ROOM_CREATE,
    SCOPE_ROOM_MESSAGE,
    PluginGrantError,
    PluginGrantStore,
)
from xmuse_core.chat.room_setup import RoomSetupError, RoomSetupService
from xmuse_core.chat.roster_templates import builtin_workroom_catalog
from xmuse_core.runtime.frontend_api import operator_error

logger = logging.getLogger(__name__)

_MESSAGES = {
    "plugin_origin_forbidden": "Cross-origin plugin requests are forbidden",
    "plugin_content_type_invalid": "Plugin routes require a JSON body",
    "plugin_grant_invalid": "Plugin grant is missing or invalid",
    "plugin_pairing_invalid": "Pairing code is missing or invalid",
    "plugin_pairing_locked": "Too many failed pairing attempts",
    "plugin_grant_request_invalid": "Plugin grant request is invalid",
    "plugin_grant_scope_invalid": "Plugin grant scope is invalid",
    "plugin_grant_scope_denied": "Plugin grant does not cover this action",
    "plugin_grant_host_invalid": "Plugin grant host is invalid",
    "plugin_grant_unknown": "Plugin grant is unknown",
    "plugin_grant_room_limit": "Plugin grant Room limit reached",
    "plugin_room_request_invalid": "Room request is invalid",
    "plugin_room_rate_limited": "Rooms are created too quickly",
    "plugin_message_mention_invalid": "Message mentions are invalid",
    "plugin_review_not_human": "Review is not waiting for the Human",
    "room_conversation_unknown": "Conversation is unknown",
    "room_board_split_unknown": "Board split is unknown",
    "room_board_split_decided": "Board split was already decided",
    "room_board_split_not_proposed": "Board split can no longer be decided",
    "room_board_split_digest_mismatch": "Board split digest does not match",
    "room_board_charter_active": "Board charter is already active",
    "room_board_review_unknown": "Board review is unknown",
    "room_board_review_digest_mismatch": "Board review digest does not match",
    "room_board_review_material_incomplete": "Review material is incomplete",
    "room_board_review_request_invalid": "Review decision is invalid",
}

_STATUS = {
    "plugin_origin_forbidden": status.HTTP_403_FORBIDDEN,
    "plugin_content_type_invalid": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "plugin_grant_invalid": status.HTTP_401_UNAUTHORIZED,
    "plugin_pairing_invalid": status.HTTP_401_UNAUTHORIZED,
    "plugin_pairing_locked": status.HTTP_429_TOO_MANY_REQUESTS,
    "plugin_grant_request_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_grant_scope_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_grant_scope_denied": status.HTTP_403_FORBIDDEN,
    "plugin_grant_host_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_grant_unknown": status.HTTP_404_NOT_FOUND,
    "plugin_grant_room_limit": status.HTTP_409_CONFLICT,
    "plugin_room_request_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_room_rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "plugin_message_mention_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_review_not_human": status.HTTP_409_CONFLICT,
    "room_conversation_unknown": status.HTTP_404_NOT_FOUND,
    "room_board_split_unknown": status.HTTP_404_NOT_FOUND,
    "room_board_split_decided": status.HTTP_409_CONFLICT,
    "room_board_split_not_proposed": status.HTTP_409_CONFLICT,
    "room_board_split_digest_mismatch": status.HTTP_409_CONFLICT,
    "room_board_charter_active": status.HTTP_409_CONFLICT,
    "room_board_review_unknown": status.HTTP_404_NOT_FOUND,
    "room_board_review_digest_mismatch": status.HTTP_409_CONFLICT,
    "room_board_review_material_incomplete": status.HTTP_409_CONFLICT,
    "room_board_review_request_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
}

_LEAD_CLI_KINDS = ("claude", "opencode", "antigravity", "codex")
_REVIEWER_CLI_KINDS = ("claude", "opencode", "antigravity", "codex")
_MAX_OWNERS = 6
_MAX_PARTICIPANTS = 8
_MAX_MESSAGE_CHARS = 32768
_MAX_REQUEST_ID_CHARS = 200


def _deny(code: str, *, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(
        status_code=_STATUS[code],
        detail=operator_error(code, _MESSAGES[code]),
        headers=headers,
    )


def _map_store_error(exc: PluginGrantError, mapping: dict[str, str]) -> HTTPException:
    """Map a store failure to HTTP; unmapped codes are 500s, never echoes."""

    if exc.code in mapping:
        return _deny(mapping[exc.code])
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=operator_error(exc.code, "Plugin grant store is unavailable"),
    )


def _require_no_origin(request: Request) -> None:
    if "origin" in request.headers:
        raise _deny("plugin_origin_forbidden")


def _require_plugin_transport(request: Request) -> None:
    _require_no_origin(request)
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise _deny("plugin_content_type_invalid")


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization")
    if value is None:
        return None
    scheme, separator, token = value.partition(" ")
    if not separator or scheme != "Bearer":
        return None
    if not token or token.strip() != token or any(char.isspace() for char in token):
        return None
    return token


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        raise _deny("plugin_grant_request_invalid") from None


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _valid_request_id(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= _MAX_REQUEST_ID_CHARS


def _split_status(root: Path, split_id: str) -> str | None:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select status from room_board_splits where split_id = ?", (split_id,)
        ).fetchone()
    return str(row["status"]) if row is not None else None


def _review_waiting_for_human(root: Path, conversation_id: str, review_id: str) -> bool | None:
    """None when the review is not in this Room; else whether the Human may decide it."""

    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select status, reviewer_kind from room_board_reviews "
            "where review_id = ? and conversation_id = ?",
            (review_id, conversation_id),
        ).fetchone()
    if row is None:
        return None
    return str(row["status"]) == "pending" and str(row["reviewer_kind"]) == "operator"


def _scoped_request_id(grant_id: str, client_request_id: str) -> str:
    # Idempotency keys are per grant: the same key under another grant never
    # replays another grant's object (main_window_control_v1 section 4). The
    # caller's key is hashed so the scoped key stays within the 200-character
    # limit of the setup and message idempotency columns.
    digest = hashlib.sha256(client_request_id.encode("utf-8")).hexdigest()[:32]
    return f"plugin:{grant_id}:{digest}"


def _provenance(auth: Mapping[str, Any]) -> dict[str, str]:
    return {"via": f"plugin:{auth['host']}", "grant_id": str(auth["grant_id"])}


def _default_model(cli_kind: str) -> str | None:
    """The built-in provider profile's model; the body never names one (T17).

    Codex fills its own default (None); the Room runner resolves the provider's
    real model from these profile ids, as for Web-created Rooms.
    """

    if cli_kind == "codex":
        return None
    profile = builtin_workroom_catalog().provider_profiles.get(f"{cli_kind}.default")
    return profile.model_id if profile is not None else None


def _participant(role: str, display_name: str, cli_kind: str, **extra: Any) -> ParticipantInit:
    return ParticipantInit(
        role=role,
        display_name=display_name,
        cli_kind=cli_kind,  # type: ignore[arg-type]
        model=_default_model(cli_kind),
        **extra,
    )


def _room_participants(body: Mapping[str, Any]) -> list[ParticipantInit]:
    lead = body.get("lead")
    owners = body.get("owners")
    reviewer = body.get("reviewer")
    if not isinstance(lead, dict) or set(lead) != {"cli_kind"}:
        raise _deny("plugin_room_request_invalid")
    if lead["cli_kind"] not in _LEAD_CLI_KINDS:
        raise _deny("plugin_room_request_invalid")
    if not isinstance(owners, list) or not 1 <= len(owners) <= _MAX_OWNERS:
        raise _deny("plugin_room_request_invalid")
    for owner in owners:
        if not isinstance(owner, dict) or set(owner) != {"cli_kind"}:
            raise _deny("plugin_room_request_invalid")
        if owner["cli_kind"] not in WORKSPACE_WRITE_CLI_KINDS:
            raise _deny("plugin_room_request_invalid")
    if reviewer is not None and (
        not isinstance(reviewer, dict)
        or set(reviewer) != {"cli_kind"}
        or reviewer["cli_kind"] not in _REVIEWER_CLI_KINDS
    ):
        raise _deny("plugin_room_request_invalid")
    participants = [
        _participant("lead", "Lead", lead["cli_kind"]),
        *[
            _participant(
                f"owner-{index}",
                f"Owner {index}",
                owner["cli_kind"],
                workspace_access="workspace_write",
            )
            for index, owner in enumerate(owners, start=1)
        ],
    ]
    if reviewer is not None:
        participants.append(_participant("reviewer", "Reviewer", reviewer["cli_kind"]))
    if len(participants) > _MAX_PARTICIPANTS:
        raise _deny("plugin_room_request_invalid")
    return participants


def register_plugin_grant_routes(
    app: FastAPI,
    *,
    root: Path,
    operator_token: str | None = None,
    execution_root: Path | None = None,
    runtime_starter: WorkroomRuntimeStarter | None = None,
    explicit_runtime_starter: bool = False,
    provider_capabilities_provider: ProviderCapabilitiesProvider | None = None,
) -> None:
    db_path = root / "chat.db"

    def _authenticate(request: Request) -> dict[str, Any]:
        secret = _bearer_token(request)
        if secret is None:
            raise _deny("plugin_grant_invalid")
        try:
            return PluginGrantStore(db_path).authenticate_bearer(
                secret, operator_token=operator_token
            )
        except PluginGrantError:
            raise _deny("plugin_grant_invalid") from None

    def _require_scope(auth: Mapping[str, Any], scope: str) -> None:
        if scope not in auth["scopes"]:
            raise _deny("plugin_grant_scope_denied")

    def _record_use(grant_id: str) -> None:
        try:
            PluginGrantStore(db_path).record_grant_use(grant_id)
        except PluginGrantError as exc:
            raise _map_store_error(exc, {}) from exc

    def _refresh(conversation_id: str) -> None:
        try:
            refresh_board_views(root, conversation_id)
        except Exception as exc:
            logger.warning("plugin grant board refresh failed: %s", type(exc).__name__)

    # -- operator routes ----------------------------------------------------

    @app.post("/api/chat/operator/plugin-grants", status_code=status.HTTP_201_CREATED)
    async def issue_plugin_grant(request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        body = await _json_body(request)
        if not isinstance(body, dict):
            raise _deny("plugin_grant_request_invalid")
        v2_keys = {"host", "scopes", "conversation_ids", "ttl_seconds"}
        v1_keys = {"conversation_id", "host", "scope", "ttl_seconds"}
        if set(body) <= v2_keys and {"host", "scopes", "conversation_ids"} <= set(body):
            scopes = body.get("scopes")
            rooms = body.get("conversation_ids")
        elif set(body) <= v1_keys and {"conversation_id", "host", "scope"} <= set(body):
            # v1 body: one Room, one scope.
            if not _valid_text(body.get("conversation_id")):
                raise _deny("plugin_grant_request_invalid")
            scopes = [body.get("scope")]
            rooms = [body["conversation_id"]]
        else:
            raise _deny("plugin_grant_request_invalid")
        store = PluginGrantStore(db_path)
        try:
            grant, pairing_code, pairing_expires_at = store.issue(
                host=body.get("host"),
                scopes=scopes,
                conversation_ids=rooms,
                ttl_seconds=body.get("ttl_seconds"),
                operator_token=operator_token,
            )
        except PluginGrantError as exc:
            raise _map_store_error(
                exc,
                {
                    "room_conversation_unknown": "room_conversation_unknown",
                    "plugin_grant_scope_invalid": "plugin_grant_scope_invalid",
                    "plugin_grant_host_invalid": "plugin_grant_host_invalid",
                    "plugin_grant_request_invalid": "plugin_grant_request_invalid",
                },
            ) from exc
        return {
            "schema_version": "plugin_grant_issue/v2",
            "grant": grant,
            "pairing_code": pairing_code,
            "pairing_expires_at": pairing_expires_at,
        }

    @app.get("/api/chat/operator/plugin-grants")
    def list_plugin_grants(request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        conversation_id = request.query_params.get("conversation_id")
        host = request.query_params.get("host")
        if (conversation_id is None) == (host is None):
            raise _deny("plugin_grant_request_invalid")
        store = PluginGrantStore(db_path)
        try:
            if conversation_id is not None:
                if not _valid_text(conversation_id):
                    raise _deny("plugin_grant_request_invalid")
                if not store.conversation_exists(conversation_id):
                    raise _deny("room_conversation_unknown")
                grants = store.list_grants(conversation_id=conversation_id)
            else:
                if not _valid_text(host):
                    raise _deny("plugin_grant_request_invalid")
                grants = store.list_grants(host=host)
        except PluginGrantError as exc:
            raise _map_store_error(exc, {}) from exc
        payload: dict[str, Any] = {"schema_version": "plugin_grant_list/v2", "grants": grants}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        else:
            payload["host"] = host
        return payload

    @app.post("/api/chat/operator/plugin-grants/revoke-host")
    async def revoke_host_plugin_grants(request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        body = await _json_body(request)
        if not isinstance(body, dict) or set(body) != {"host"}:
            raise _deny("plugin_grant_request_invalid")
        try:
            grants = PluginGrantStore(db_path).revoke_host(body["host"])
        except PluginGrantError as exc:
            raise _map_store_error(
                exc, {"plugin_grant_host_invalid": "plugin_grant_host_invalid"}
            ) from exc
        return {"schema_version": "plugin_grant_revoke_host/v1", "grants": grants}

    @app.post("/api/chat/operator/plugin-grants/{grant_id}/revoke")
    async def revoke_plugin_grant(grant_id: str, request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        body = await _json_body(request)
        if not isinstance(body, dict) or not set(body) <= {"conversation_id"}:
            raise _deny("plugin_grant_request_invalid")
        conversation_id = body.get("conversation_id")
        if "conversation_id" in body and not _valid_text(conversation_id):
            raise _deny("plugin_grant_request_invalid")
        try:
            grant = PluginGrantStore(db_path).revoke_grant(
                grant_id, conversation_id if isinstance(conversation_id, str) else None
            )
        except PluginGrantError as exc:
            raise _map_store_error(
                exc,
                {
                    "plugin_grant_unknown": "plugin_grant_unknown",
                    "plugin_grant_request_invalid": "plugin_grant_request_invalid",
                },
            ) from exc
        return {"schema_version": "plugin_grant_revoke/v2", "grant": grant}

    # -- plugin routes --------------------------------------------------------

    @app.post("/api/chat/plugin/grants/exchange")
    async def exchange_plugin_grant(request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        body = await _json_body(request)
        if (
            not isinstance(body, dict)
            or set(body) != {"pairing_code", "host"}
            or not _valid_text(body.get("pairing_code"))
            or not _valid_text(body.get("host"))
        ):
            raise _deny("plugin_grant_request_invalid")
        try:
            grant, secret = PluginGrantStore(db_path).exchange(
                str(body["pairing_code"]), str(body["host"])
            )
        except PluginGrantError as exc:
            if exc.code == "plugin_pairing_locked":
                raise _deny(
                    "plugin_pairing_locked",
                    headers={"Retry-After": str(exc.retry_after or 60)},
                ) from exc
            raise _map_store_error(
                exc, {"plugin_pairing_invalid": "plugin_pairing_invalid"}
            ) from exc
        return {
            "schema_version": "plugin_grant_exchange/v2",
            "grant": grant,
            "secret": secret,
        }

    @app.post("/api/chat/plugin/board-splits/{split_id}/decision")
    async def decide_board_split_via_grant(split_id: str, request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        auth = _authenticate(request)
        _require_scope(auth, SCOPE_BOARD_SPLIT_DECIDE)
        body = await _json_body(request)
        if (
            not isinstance(body, dict)
            or set(body) != {"conversation_id", "decision", "expected_digest"}
            or not _valid_text(body.get("conversation_id"))
            or body.get("decision") not in ("approve", "reject")
            or not _valid_text(body.get("expected_digest"))
        ):
            raise _deny("plugin_grant_request_invalid")
        conversation_id = str(body["conversation_id"])
        if not PluginGrantStore.has_room(auth, conversation_id):
            raise _deny("room_board_split_unknown")
        try:
            result = RoomBoardStore(db_path).decide_split(
                conversation_id=conversation_id,
                split_id=split_id,
                decision=str(body["decision"]),
                operator_identity=f"plugin-grant:{auth['grant_id']}",
                decided_via=f"plugin:{auth['host']}",
                grant_id=auth["grant_id"],
                expected_digest=str(body["expected_digest"]),
            )
        except (KeyError, ValueError) as exc:
            code = str(exc).split(":", 1)[0].strip()
            if code == "room_board_split_unknown":
                raise _deny("room_board_split_unknown") from exc
            if code == "room_board_split_digest_mismatch":
                raise _deny("room_board_split_digest_mismatch") from exc
            if code == "room_board_split_decided":
                if _split_status(root, split_id) == "superseded":
                    raise _deny("room_board_split_not_proposed") from exc
                raise _deny("room_board_split_decided") from exc
            if code == "room_board_charter_active":
                raise _deny("room_board_charter_active") from exc
            raise _deny("plugin_grant_request_invalid") from exc
        _record_use(auth["grant_id"])
        _refresh(conversation_id)
        return dict(result)

    @app.post("/api/chat/plugin/rooms", status_code=status.HTTP_201_CREATED)
    async def create_room_via_grant(request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        auth = _authenticate(request)
        _require_scope(auth, SCOPE_ROOM_CREATE)
        body = await _json_body(request)
        allowed = {"client_request_id", "title", "lead", "owners", "reviewer", "review_policy"}
        if (
            not isinstance(body, dict)
            or not set(body) <= allowed
            or {"client_request_id", "title", "lead", "owners"} - set(body)
            or not _valid_request_id(body.get("client_request_id"))
            or not isinstance(body.get("title"), str)
            or not 1 <= len(str(body["title"]).strip()) <= 200
            or body.get("review_policy", "off") not in ("off", "cross_family")
        ):
            raise _deny("plugin_room_request_invalid")
        participants = _room_participants(body)
        setup_request = RoomConversationCreate(
            title=str(body["title"]).strip(),
            client_request_id=_scoped_request_id(auth["grant_id"], body["client_request_id"]),
            collaboration=RoomCollaborationInit(
                mode="addressed",
                lead_role="lead",
                review_policy=body.get("review_policy", "off"),
            ),
            initial_participants=participants,
        )
        store = PluginGrantStore(db_path)
        replay = False
        try:
            replay = RoomSetupService(root).has_setup_request(setup_request.client_request_id)
            if not replay:
                store.reserve_room_create(auth["grant_id"])
        except PluginGrantError as exc:
            if exc.code == "plugin_room_rate_limited":
                raise _deny(
                    "plugin_room_rate_limited",
                    headers={"Retry-After": str(exc.retry_after or 10)},
                ) from exc
            raise _map_store_error(
                exc,
                {
                    "plugin_grant_room_limit": "plugin_grant_room_limit",
                    "plugin_grant_invalid": "plugin_grant_invalid",
                },
            ) from exc
        try:
            created = create_admitted_room(root, setup_request, provider_capabilities_provider)
        except RoomSetupError as exc:
            raise room_setup_http_error(exc) from exc
        conversation_id = str(created["id"])
        try:
            room_count = store.add_rooms(auth["grant_id"], [conversation_id])
        except PluginGrantError as exc:
            raise _map_store_error(exc, {}) from exc
        _record_use(auth["grant_id"])
        stored = ParticipantStore(db_path).list_by_conversation(conversation_id)
        return {
            "schema_version": "plugin_room_create/v1",
            "conversation_id": conversation_id,
            "participants": [
                {
                    "participant_id": item.participant_id,
                    "role": item.role,
                    "cli_kind": item.cli_kind,
                }
                for item in stored
                if item.status == "active"
            ],
            "room_count": room_count,
            "replayed": replay,
        }

    @app.post(
        "/api/chat/plugin/rooms/{conversation_id}/messages",
        status_code=status.HTTP_201_CREATED,
    )
    async def post_message_via_grant(conversation_id: str, request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        auth = _authenticate(request)
        _require_scope(auth, SCOPE_ROOM_MESSAGE)
        body = await _json_body(request)
        if (
            not isinstance(body, dict)
            or not set(body) <= {"client_request_id", "message", "mentions"}
            or {"client_request_id", "message"} - set(body)
            or not _valid_request_id(body.get("client_request_id"))
            or not isinstance(body.get("message"), str)
            or not 1 <= len(body["message"]) <= _MAX_MESSAGE_CHARS
            or not body["message"].strip()
        ):
            raise _deny("plugin_grant_request_invalid")
        if not PluginGrantStore.has_room(auth, conversation_id):
            raise _deny("room_conversation_unknown")
        mentions = body.get("mentions", [])
        if not isinstance(mentions, list) or any(not _valid_text(item) for item in mentions):
            raise _deny("plugin_message_mention_invalid")
        members = {
            item.participant_id
            for item in ParticipantStore(db_path).list_by_conversation(conversation_id)
            if item.status == "active"
        }
        if any(item not in members for item in mentions):
            raise _deny("plugin_message_mention_invalid")
        if runtime_starter is None or execution_root is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=operator_error("room_runtime_unavailable", "Room runtime is unavailable"),
            )
        result = post_room_human_message(
            root=root,
            execution_root=execution_root,
            runtime_starter=runtime_starter,
            explicit_runtime_starter=explicit_runtime_starter,
            request=request,
            conversation_id=conversation_id,
            payload=ThreadMessageCreate(message=body["message"]),
            client_request_id=_scoped_request_id(auth["grant_id"], body["client_request_id"]),
            extra_mentions=[str(item) for item in mentions],
            provenance=_provenance(auth),
        )
        _record_use(auth["grant_id"])
        return result

    @app.post("/api/chat/plugin/board-reviews/{review_id}/decision")
    async def decide_review_via_grant(review_id: str, request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        auth = _authenticate(request)
        _require_scope(auth, SCOPE_BOARD_REVIEW_DECIDE)
        body = await _json_body(request)
        required = {"conversation_id", "verdict", "expected_digest", "summary", "findings"}
        if not isinstance(body, dict) or set(body) != required:
            raise _deny("plugin_grant_request_invalid")
        conversation_id = body.get("conversation_id")
        if not _valid_text(conversation_id) or not _valid_text(body.get("expected_digest")):
            raise _deny("plugin_grant_request_invalid")
        assert isinstance(conversation_id, str)
        if not PluginGrantStore.has_room(auth, conversation_id):
            raise _deny("room_board_review_unknown")
        waiting = _review_waiting_for_human(root, conversation_id, review_id)
        if waiting is None:
            raise _deny("room_board_review_unknown")
        if not waiting:
            raise _deny("plugin_review_not_human")
        findings = body.get("findings")
        summary = body.get("summary")
        if not isinstance(findings, list) or not isinstance(summary, str):
            raise _deny("room_board_review_request_invalid")
        try:
            result = RoomApplicationService(
                db_path, root / "god_sessions.json"
            ).board_decide_review(
                conversation_id=conversation_id,
                review_id=review_id,
                verdict=str(body.get("verdict")),
                summary=summary,
                findings=findings,
                expected_digest=str(body["expected_digest"]),
                operator_identity=f"plugin-grant:{auth['grant_id']}",
                decided_via=f"plugin:{auth['host']}",
                grant_id=str(auth["grant_id"]),
            )
        except RoomApplicationError as exc:
            # The status check above and the store's own check can race: a participant
            # verdict committed in between is "not waiting for the Human" (409).
            mapping = {
                "room_board_review_not_pending": "plugin_review_not_human",
                "room_board_review_unknown": "room_board_review_unknown",
                "room_board_review_digest_mismatch": "room_board_review_digest_mismatch",
                "room_board_review_material_incomplete": "room_board_review_material_incomplete",
            }
            raise _deny(mapping.get(exc.code, "room_board_review_request_invalid")) from exc
        _record_use(auth["grant_id"])
        _refresh(conversation_id)
        return dict(result)

    @app.get("/api/chat/plugin/board-reviews/{review_id}/material")
    def review_material_via_grant(review_id: str, request: Request) -> dict[str, Any]:
        _require_no_origin(request)
        auth = _authenticate(request)
        _require_scope(auth, SCOPE_BOARD_REVIEW_DECIDE)
        conversation_id = request.query_params.get("conversation_id")
        if not _valid_text(conversation_id):
            raise _deny("plugin_grant_request_invalid")
        assert isinstance(conversation_id, str)
        if not PluginGrantStore.has_room(auth, conversation_id):
            raise _deny("room_board_review_unknown")
        waiting = _review_waiting_for_human(root, conversation_id, review_id)
        if waiting is None:
            raise _deny("room_board_review_unknown")
        if not waiting:
            raise _deny("plugin_review_not_human")
        try:
            return RoomBoardStore(db_path).review_material(
                conversation_id=conversation_id, review_id=review_id
            )
        except ValueError as exc:
            code = str(exc).split(":", 1)[0].strip()
            if code == "room_board_review_not_operator":
                raise _deny("plugin_review_not_human") from exc
            raise _deny("room_board_review_unknown") from exc

    @app.post("/api/chat/plugin/grants/revoke")
    async def revoke_own_grant(request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        auth = _authenticate(request)
        body = await _json_body(request)
        if not isinstance(body, dict) or set(body) != set():
            raise _deny("plugin_grant_request_invalid")
        try:
            grant = PluginGrantStore(db_path).revoke_grant(auth["grant_id"])
        except PluginGrantError as exc:
            raise _map_store_error(exc, {"plugin_grant_unknown": "plugin_grant_unknown"}) from exc
        return {"schema_version": "plugin_grant_revoke/v2", "grant": grant}
