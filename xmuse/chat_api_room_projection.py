"""Bounded projections used by the default Room-first browser."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from xmuse_core.chat.room_database import (
    RoomDatabaseError,
    RoomEventReadStore,
)
from xmuse_core.chat.room_projection import (
    build_room_chat_projection,
    build_room_list_projection,
)


def _database_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "room_database_unavailable",
            "message": "Room database is unavailable",
        },
    )


def _room_projection(
    root: Path,
    conversation_id: str,
    *,
    limit: int,
    before_room_seq: int | None,
    after_room_seq: int | None,
) -> dict[str, Any]:
    try:
        return build_room_chat_projection(
            conversation_id,
            root,
            limit=limit,
            before_room_seq=before_room_seq,
            after_room_seq=after_room_seq,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (RoomDatabaseError, sqlite3.DatabaseError) as exc:
        raise _database_unavailable(exc) from exc


def _events(
    root: Path,
    conversation_id: str,
    *,
    after_seq: int,
    limit: int,
) -> dict[str, object]:
    store = RoomEventReadStore(root / "chat.db")
    try:
        if not store.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        cursor = max(0, after_seq)
        events = store.list_frontend_events(
            conversation_id,
            after_seq=cursor,
            limit=limit,
        )
        latest_seq = store.latest_frontend_event_seq(conversation_id)
    except HTTPException:
        raise
    except (RoomDatabaseError, sqlite3.DatabaseError) as exc:
        raise _database_unavailable(exc) from exc
    return {
        "schema_version": "chat_frontend_events/v1",
        "projection_only": True,
        "proof_boundary": "frontend_event_not_authority",
        "conversation_id": conversation_id,
        "after_seq": cursor,
        "latest_seq": latest_seq,
        "has_more": bool(events) and int(events[-1]["sequence"]) < latest_seq,
        "events": events,
    }


def register_room_projection_routes(app: FastAPI, *, root: Path) -> None:
    @app.get("/api/chat/rooms")
    def room_list_projection() -> dict[str, object]:
        try:
            return build_room_list_projection(root)
        except (RoomDatabaseError, sqlite3.DatabaseError) as exc:
            raise _database_unavailable(exc) from exc

    @app.get("/api/chat/conversations/{conversation_id}/room-projection")
    def room_chat_projection(
        conversation_id: str,
        limit: int = Query(default=60, ge=1, le=100),
        before_room_seq: int | None = Query(default=None, ge=0),
        after_room_seq: int | None = Query(default=None, ge=0),
    ) -> dict[str, object]:
        return _room_projection(
            root,
            conversation_id,
            limit=limit,
            before_room_seq=before_room_seq,
            after_room_seq=after_room_seq,
        )

    @app.get("/api/chat/conversations/{conversation_id}/events")
    def room_frontend_events(
        conversation_id: str,
        after_seq: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
    ) -> dict[str, object]:
        return _events(
            root,
            conversation_id,
            after_seq=after_seq,
            limit=limit,
        )
