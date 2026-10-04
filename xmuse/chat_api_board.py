"""HTTP surface for the Room coordination board read model v2.

All ``GET`` routes are read-only projections over ``chat.db``: they open a
read-only SQLite connection and call the pure builders in
``xmuse_core.chat.room_board_projection``.  They never mutate and never touch
the write-capable ``RoomBoardStore`` paths.  Errors use the contract §1 shape
(``operator_error``); no response ever carries exception text or SQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.room_api_models import (
    RoomBoardReviewDecisionRequest,
    RoomBoardSplitDecisionRequest,
)
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_board import DECIDED_VIA_RE
from xmuse_core.chat.room_board_projection import (
    board_events_page,
    build_board_projection,
    build_board_summary,
    build_contract_detail,
)
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.runtime.frontend_api import operator_error

logger = logging.getLogger(__name__)

_CONFLICT_CODES = {
    "room_board_split_decided",
    "room_board_split_not_proposed",
    "room_board_charter_active",
    "room_board_split_digest_mismatch",
}

_POLL_INTERVAL_S = 0.25
_HEARTBEAT_INTERVAL_S = 15.0
_EVENTS_FIRST_PAGE_LIMIT = 200


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.startswith("room_board_"):
        return code
    value = str(exc).split(":", 1)[0].strip()
    if value.startswith("room_board_") and len(value) <= 200:
        return value
    return "room_board_action_failed"


def _store_error(exc: Exception) -> HTTPException:
    code = _error_code(exc)
    if code == "room_board_split_unknown":
        http_status = status.HTTP_404_NOT_FOUND
    elif code in _CONFLICT_CODES:
        http_status = status.HTTP_409_CONFLICT
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=http_status,
        detail=operator_error(code, "Room board split was not decided"),
    )


def _unknown_conversation(conversation_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=operator_error(
            "room_conversation_unknown",
            f"Conversation {conversation_id} is unknown",
        ),
    )


def _require_conversation(root: Path, conversation_id: str) -> None:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        exists = conn.execute(
            "select 1 from conversations where id = ?", (conversation_id,)
        ).fetchone()
    if exists is None:
        raise _unknown_conversation(conversation_id)


def _read_projection(root: Path, conversation_id: str) -> dict[str, Any]:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        return build_board_projection(conn, conversation_id, now=datetime.now(UTC))


def _read_events_page(
    root: Path, conversation_id: str, *, after_seq: int, limit: int
) -> dict[str, Any]:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        return board_events_page(conn, conversation_id, after_seq=after_seq, limit=limit)


def _read_board_seq(root: Path, conversation_id: str) -> int:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select coalesce(max(seq), 0) from room_activities "
            "where conversation_id = ? and activity_type like 'board.%'",
            (conversation_id,),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def _etag_matches(if_none_match: str | None, revision: str) -> bool:
    if not if_none_match or not if_none_match.strip():
        return False
    quoted = f'"{revision}"'
    return any(
        token in (quoted, revision) for token in (part.strip() for part in if_none_match.split(","))
    )


def _not_modified(revision: str) -> Response:
    return Response(
        status_code=status.HTTP_304_NOT_MODIFIED,
        headers={"ETag": f'"{revision}"', "Cache-Control": "no-store"},
    )


def _invalid_query(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=operator_error("room_board_query_invalid", message),
    )


def _parse_events_query(query: Any) -> tuple[int, int, float, str | None]:
    raw_after = query.get("after_seq", "0")
    raw_limit = query.get("limit", "100")
    raw_wait = query.get("wait", "0")
    try:
        after_seq = int(str(raw_after))
    except (TypeError, ValueError):
        raise _invalid_query("after_seq must be an integer >= 0") from None
    if after_seq < 0:
        raise _invalid_query("after_seq must be an integer >= 0")
    try:
        limit = int(str(raw_limit))
    except (TypeError, ValueError):
        raise _invalid_query("limit must be an integer between 1 and 200") from None
    if not 1 <= limit <= 200:
        raise _invalid_query("limit must be an integer between 1 and 200")
    try:
        wait = float(str(raw_wait))
    except (TypeError, ValueError):
        raise _invalid_query("wait must be a number of seconds between 0 and 30") from None
    if not math.isfinite(wait) or not 0 <= wait <= 30:
        raise _invalid_query("wait must be a number of seconds between 0 and 30")
    raw_revision = query.get("revision")
    revision = str(raw_revision) if raw_revision is not None else None
    return after_seq, limit, wait, revision


def _encode_board_event(name: str, page: dict[str, Any]) -> bytes:
    data = json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"event: {name}\nid: {page['board_seq']}\ndata: {data}\n\n".encode()


def register_room_board_routes(
    app: FastAPI,
    *,
    root: Path,
    operator_token: str | None = None,
) -> None:
    @app.get("/api/chat/conversations/{conversation_id}/board")
    def room_board(conversation_id: str, request: Request, response: Response) -> Any:
        response.headers["Cache-Control"] = "no-store"
        _require_conversation(root, conversation_id)
        projection = _read_projection(root, conversation_id)
        revision = str(projection["revision"])
        if _etag_matches(request.headers.get("if-none-match"), revision):
            return _not_modified(revision)
        response.headers["ETag"] = f'"{revision}"'
        return projection

    @app.get("/api/chat/conversations/{conversation_id}/board/summary")
    def room_board_summary(conversation_id: str, request: Request, response: Response) -> Any:
        response.headers["Cache-Control"] = "no-store"
        _require_conversation(root, conversation_id)
        summary = build_board_summary(_read_projection(root, conversation_id))
        revision = str(summary["revision"])
        if _etag_matches(request.headers.get("if-none-match"), revision):
            return _not_modified(revision)
        response.headers["ETag"] = f'"{revision}"'
        return summary

    @app.get("/api/chat/conversations/{conversation_id}/board/events")
    async def room_board_events(
        conversation_id: str, request: Request, response: Response
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        _require_conversation(root, conversation_id)
        after_seq, limit, wait, revision = _parse_events_query(request.query_params)
        page = await asyncio.to_thread(
            _read_events_page, root, conversation_id, after_seq=after_seq, limit=limit
        )

        def _is_fresh(candidate: dict[str, Any]) -> bool:
            if candidate["events"]:
                return True
            return revision is not None and candidate["revision"] != revision

        if wait <= 0 or _is_fresh(page):
            return page
        deadline = time.monotonic() + wait
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return page
            await asyncio.sleep(min(_POLL_INTERVAL_S, remaining))
            if await request.is_disconnected():
                return page
            page = await asyncio.to_thread(
                _read_events_page, root, conversation_id, after_seq=after_seq, limit=limit
            )
            if _is_fresh(page):
                return page

    @app.get("/api/chat/conversations/{conversation_id}/board/stream")
    async def room_board_stream(conversation_id: str, request: Request) -> StreamingResponse:
        _require_conversation(root, conversation_id)
        board_seq = await asyncio.to_thread(_read_board_seq, root, conversation_id)
        raw_last_id = (request.headers.get("last-event-id") or "").strip()
        try:
            start = int(raw_last_id) if raw_last_id else board_seq
        except (TypeError, ValueError):
            start = board_seq
        if start < 0:
            start = board_seq
        first = await asyncio.to_thread(
            _read_events_page,
            root,
            conversation_id,
            after_seq=start,
            limit=_EVENTS_FIRST_PAGE_LIMIT,
        )
        first_name = "reset" if start > board_seq else "board"

        async def events() -> AsyncIterator[bytes]:
            last_seq = int(first["board_seq"])
            last_revision = str(first["revision"])
            last_heartbeat = time.monotonic()
            yield _encode_board_event(first_name, first)
            while not await request.is_disconnected():
                await asyncio.sleep(_POLL_INTERVAL_S)
                current = await asyncio.to_thread(
                    _read_events_page,
                    root,
                    conversation_id,
                    after_seq=last_seq,
                    limit=_EVENTS_FIRST_PAGE_LIMIT,
                )
                if (
                    int(current["board_seq"]) != last_seq
                    or str(current["revision"]) != last_revision
                ):
                    last_seq = int(current["board_seq"])
                    last_revision = str(current["revision"])
                    last_heartbeat = time.monotonic()
                    yield _encode_board_event("board", current)
                    continue
                now = time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_INTERVAL_S:
                    last_heartbeat = now
                    yield b": heartbeat\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/chat/conversations/{conversation_id}/board/contracts/{contract_id}")
    def room_board_contract(
        conversation_id: str,
        contract_id: str,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        _require_conversation(root, conversation_id)
        raw_version = request.query_params.get("version")
        version: int | None = None
        if raw_version is not None:
            try:
                version = int(raw_version)
            except (TypeError, ValueError):
                version = None
            if version is None or version <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=operator_error(
                        "room_board_version_invalid",
                        "Contract version must be a positive integer",
                    ),
                )
        with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
            detail = build_contract_detail(conn, conversation_id, contract_id, version)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=operator_error(
                    "room_board_contract_unknown",
                    f"Contract {contract_id} is unknown",
                ),
            )
        return detail

    @app.post("/api/chat/operator/board-splits/{split_id}/decision")
    def decide_room_board_split(
        split_id: str,
        request: Request,
        payload: RoomBoardSplitDecisionRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        if not isinstance(payload.decided_via, str) or not DECIDED_VIA_RE.match(
            payload.decided_via
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=operator_error(
                    "room_board_decided_via_invalid",
                    "decided_via must be web, cli, or plugin:<host>",
                ),
            )
        try:
            result = RoomApplicationService(
                root / "chat.db", root / "god_sessions.json"
            ).board_decide_split(
                conversation_id=payload.conversation_id,
                split_id=split_id,
                decision=payload.decision,
                operator_identity="operator:local",
                decided_via=payload.decided_via,
                expected_digest=payload.expected_digest,
            )
        except RoomApplicationError as exc:
            raise _store_error(exc) from exc
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        try:
            refresh_board_views(root, payload.conversation_id)
        except Exception as exc:
            logger.warning("room board refresh after decision failed: %s", exc)
        return dict(result)

    @app.post("/api/chat/operator/board-reviews/{review_id}/decision")
    def decide_room_board_review(
        review_id: str,
        request: Request,
        payload: RoomBoardReviewDecisionRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        try:
            result = RoomApplicationService(
                root / "chat.db", root / "god_sessions.json"
            ).board_decide_review(
                conversation_id=payload.conversation_id,
                review_id=review_id,
                verdict=payload.verdict,
                summary=payload.summary,
                findings=[dict(item) for item in payload.findings],
                operator_identity="operator:local",
                decided_via="web",
            )
        except RoomApplicationError as exc:
            raise _store_error(exc) from exc
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _store_error(exc) from exc
        try:
            refresh_board_views(root, payload.conversation_id)
        except Exception as exc:
            logger.warning("room board refresh after review decision failed: %s", exc)
        return dict(result)
