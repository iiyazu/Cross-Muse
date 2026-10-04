"""HTTP surface for the Room coordination board operator projection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status

from xmuse.operator_auth import require_operator_token
from xmuse_core.chat.room_api_models import (
    RoomBoardReviewDecisionRequest,
    RoomBoardSplitDecisionRequest,
)
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_board import RoomBoardStore
from xmuse_core.chat.room_board_view import refresh_board_views
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.runtime.frontend_api import operator_error

logger = logging.getLogger(__name__)

_CONFLICT_CODES = {
    "room_board_split_decided",
    "room_board_split_not_proposed",
    "room_board_charter_active",
}


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
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(
        status_code=http_status,
        detail=operator_error(code, "Room board split was not decided"),
    )


def register_room_board_routes(
    app: FastAPI,
    *,
    root: Path,
    operator_token: str | None = None,
) -> None:
    def require_conversation(conversation_id: str) -> None:
        with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
            exists = conn.execute(
                "select 1 from conversations where id = ?", (conversation_id,)
            ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="conversation not found")

    @app.get("/api/chat/conversations/{conversation_id}/board")
    def room_board(conversation_id: str, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        require_conversation(conversation_id)
        try:
            return RoomBoardStore(root / "chat.db").board_projection(
                conversation_id=conversation_id
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=_error_code(exc)) from exc

    @app.get("/api/chat/conversations/{conversation_id}/board/contracts/{contract_id}")
    def room_board_contract(
        conversation_id: str, contract_id: str, response: Response, version: int | None = None
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        require_conversation(conversation_id)
        try:
            detail = RoomBoardStore(root / "chat.db").board_contract_detail(
                conversation_id=conversation_id,
                contract_id=contract_id,
                version=version,
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=_error_code(exc)) from exc
        if detail is None:
            raise HTTPException(status_code=404, detail="contract not found")
        return detail

    @app.post("/api/chat/operator/board-splits/{split_id}/decision")
    def decide_room_board_split(
        split_id: str,
        request: Request,
        payload: RoomBoardSplitDecisionRequest,
    ) -> dict[str, Any]:
        require_operator_token(request, configured_token=operator_token)
        try:
            result = RoomApplicationService(
                root / "chat.db", root / "god_sessions.json"
            ).board_decide_split(
                conversation_id=payload.conversation_id,
                split_id=split_id,
                decision=payload.decision,
                operator_identity="operator:local",
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
