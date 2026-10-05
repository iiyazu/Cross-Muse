"""HTTP surface for scoped plugin grants (contract ``plugin_grant_v1``).

Operator routes (section 3) require the operator token. Plugin routes
(section 4) authenticate only with ``Authorization: Bearer`` grant secrets
(exchange excepted); the operator header is never read there. Every plugin
route refuses requests with an ``Origin`` header (403) or a non-JSON
``Content-Type`` (415) before anything else. Error messages are static: they
never echo request bodies or headers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.room_board import RoomBoardStore
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_plugin_grants import PluginGrantError, PluginGrantStore
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
    "plugin_grant_host_invalid": "Plugin grant host is invalid",
    "plugin_grant_unknown": "Plugin grant is unknown",
    "room_conversation_unknown": "Conversation is unknown",
    "room_board_split_unknown": "Board split is unknown",
    "room_board_split_decided": "Board split was already decided",
    "room_board_split_not_proposed": "Board split can no longer be decided",
    "room_board_split_digest_mismatch": "Board split digest does not match",
    "room_board_charter_active": "Board charter is already active",
}

_STATUS = {
    "plugin_origin_forbidden": status.HTTP_403_FORBIDDEN,
    "plugin_content_type_invalid": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "plugin_grant_invalid": status.HTTP_401_UNAUTHORIZED,
    "plugin_pairing_invalid": status.HTTP_401_UNAUTHORIZED,
    "plugin_pairing_locked": status.HTTP_429_TOO_MANY_REQUESTS,
    "plugin_grant_request_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_grant_scope_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_grant_host_invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "plugin_grant_unknown": status.HTTP_404_NOT_FOUND,
    "room_conversation_unknown": status.HTTP_404_NOT_FOUND,
    "room_board_split_unknown": status.HTTP_404_NOT_FOUND,
    "room_board_split_decided": status.HTTP_409_CONFLICT,
    "room_board_split_not_proposed": status.HTTP_409_CONFLICT,
    "room_board_split_digest_mismatch": status.HTTP_409_CONFLICT,
    "room_board_charter_active": status.HTTP_409_CONFLICT,
}


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


def _require_plugin_transport(request: Request) -> None:
    if "origin" in request.headers:
        raise _deny("plugin_origin_forbidden")
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


def _split_status(root: Path, split_id: str) -> str | None:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select status from room_board_splits where split_id = ?", (split_id,)
        ).fetchone()
    return str(row["status"]) if row is not None else None


def register_plugin_grant_routes(
    app: FastAPI,
    *,
    root: Path,
    operator_token: str | None = None,
) -> None:
    db_path = root / "chat.db"

    @app.post("/api/chat/operator/plugin-grants", status_code=status.HTTP_201_CREATED)
    async def issue_plugin_grant(request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        body = await _json_body(request)
        allowed = {"conversation_id", "host", "scope", "ttl_seconds"}
        if (
            not isinstance(body, dict)
            or not set(body) <= allowed
            or {"conversation_id", "host", "scope"} - set(body)
            or not _valid_text(body.get("conversation_id"))
        ):
            raise _deny("plugin_grant_request_invalid")
        store = PluginGrantStore(db_path)
        try:
            grant, pairing_code, pairing_expires_at = store.issue(
                conversation_id=body["conversation_id"],
                host=body.get("host"),
                scope=body.get("scope"),
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
            "schema_version": "plugin_grant_issue/v1",
            "grant": grant,
            "pairing_code": pairing_code,
            "pairing_expires_at": pairing_expires_at,
        }

    @app.get("/api/chat/operator/plugin-grants")
    def list_plugin_grants(request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        conversation_id = request.query_params.get("conversation_id")
        if not _valid_text(conversation_id):
            raise _deny("plugin_grant_request_invalid")
        assert isinstance(conversation_id, str)
        store = PluginGrantStore(db_path)
        try:
            if not store.conversation_exists(conversation_id):
                raise _deny("room_conversation_unknown")
            grants = store.list_grants(conversation_id)
        except PluginGrantError as exc:
            raise _map_store_error(exc, {}) from exc
        return {
            "schema_version": "plugin_grant_list/v1",
            "conversation_id": conversation_id,
            "grants": grants,
        }

    @app.post("/api/chat/operator/plugin-grants/{grant_id}/revoke")
    async def revoke_plugin_grant(grant_id: str, request: Request) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        body = await _json_body(request)
        if (
            not isinstance(body, dict)
            or set(body) != {"conversation_id"}
            or not _valid_text(body.get("conversation_id"))
        ):
            raise _deny("plugin_grant_request_invalid")
        try:
            grant = PluginGrantStore(db_path).revoke_grant(grant_id, str(body["conversation_id"]))
        except PluginGrantError as exc:
            raise _map_store_error(
                exc,
                {
                    "plugin_grant_unknown": "plugin_grant_unknown",
                    "plugin_grant_request_invalid": "plugin_grant_request_invalid",
                },
            ) from exc
        return {"schema_version": "plugin_grant_revoke/v1", "grant": grant}

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
            "schema_version": "plugin_grant_exchange/v1",
            "grant": grant,
            "secret": secret,
        }

    @app.post("/api/chat/plugin/board-splits/{split_id}/decision")
    async def decide_board_split_via_grant(split_id: str, request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        secret = _bearer_token(request)
        if secret is None:
            raise _deny("plugin_grant_invalid")
        body = await _json_body(request)
        claimed = body.get("conversation_id") if isinstance(body, dict) else None
        try:
            auth = PluginGrantStore(db_path).authenticate_bearer(
                secret,
                conversation_id=claimed if isinstance(claimed, str) else None,
                operator_token=operator_token,
            )
        except PluginGrantError:
            raise _deny("plugin_grant_invalid") from None
        if (
            not isinstance(body, dict)
            or set(body) != {"conversation_id", "decision", "expected_digest"}
            or not _valid_text(body.get("conversation_id"))
            or body.get("decision") not in ("approve", "reject")
            or not _valid_text(body.get("expected_digest"))
        ):
            raise _deny("plugin_grant_request_invalid")
        try:
            result = RoomBoardStore(db_path).decide_split(
                conversation_id=auth["conversation_id"],
                split_id=split_id,
                decision=str(body["decision"]),
                operator_identity=f"plugin-grant:{auth['grant_id']}",
                decided_via=f"plugin:{auth['host']}",
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
        try:
            PluginGrantStore(db_path).record_grant_use(auth["grant_id"])
        except PluginGrantError as exc:
            raise _map_store_error(exc, {}) from exc
        try:
            refresh_board_views(root, auth["conversation_id"])
        except Exception as exc:
            logger.warning("plugin grant board refresh failed: %s", type(exc).__name__)
        return dict(result)

    @app.post("/api/chat/plugin/grants/revoke")
    async def revoke_own_grant(request: Request) -> dict[str, Any]:
        _require_plugin_transport(request)
        secret = _bearer_token(request)
        if secret is None:
            raise _deny("plugin_grant_invalid")
        body = await _json_body(request)
        if not isinstance(body, dict) or set(body) != set():
            raise _deny("plugin_grant_request_invalid")
        try:
            auth = PluginGrantStore(db_path).authenticate_bearer(
                secret,
                operator_token=operator_token,
            )
        except PluginGrantError:
            raise _deny("plugin_grant_invalid") from None
        try:
            grant = PluginGrantStore(db_path).revoke_grant(
                auth["grant_id"], auth["conversation_id"]
            )
        except PluginGrantError as exc:
            raise _map_store_error(exc, {"plugin_grant_unknown": "plugin_grant_unknown"}) from exc
        return {"schema_version": "plugin_grant_revoke/v1", "grant": grant}
