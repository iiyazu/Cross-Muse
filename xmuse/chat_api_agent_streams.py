"""SSE boundary for disposable Room Agent response previews."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from xmuse_core.chat.room_agent_stream import (
    RoomAgentStreamCache,
    RoomAgentStreamError,
    build_room_agent_stream_projection,
    encode_stream_projection_event,
)
from xmuse_core.chat.room_database import RoomDatabase

_POLL_INTERVAL_S = 0.1
_HEARTBEAT_INTERVAL_S = 15.0


def _unavailable_projection(conversation_id: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": "room_agent_stream_projection/v1",
        "proof_boundary": "provider_preview_not_room_or_codex_authority",
        "projection_available": False,
        "reason_code": code,
        "conversation_id": conversation_id,
        "epoch": None,
        "stream_seq": 0,
        "streams": [],
    }


def _read_cache(root: Path, conversation_id: str) -> dict[str, Any]:
    try:
        return RoomAgentStreamCache(root).read_raw(conversation_id)
    except (RoomAgentStreamError, OSError, RuntimeError, ValueError) as exc:
        code = getattr(exc, "code", "room_agent_stream_projection_unavailable")
        if not isinstance(code, str) or not code.startswith("room_agent_stream_"):
            code = "room_agent_stream_projection_unavailable"
        return _unavailable_projection(conversation_id, code)


def _prove_projection(
    root: Path,
    conversation_id: str,
    raw_cache: dict[str, Any],
) -> dict[str, Any]:
    if raw_cache.get("schema_version") == "room_agent_stream_projection/v1":
        return raw_cache
    try:
        return build_room_agent_stream_projection(
            root,
            conversation_id,
            raw_cache=raw_cache,
        )
    except (RoomAgentStreamError, OSError, RuntimeError, ValueError):
        return _unavailable_projection(conversation_id, "room_agent_stream_projection_unavailable")


def _cache_event_id(raw_cache: dict[str, Any]) -> str:
    return f"{raw_cache.get('epoch') or 'unavailable'}:{raw_cache.get('stream_seq') or 0}"


def _event_id(projection: dict[str, Any]) -> str:
    return f"{projection.get('epoch') or 'unavailable'}:{projection.get('stream_seq') or 0}"


def register_room_agent_stream_routes(app: FastAPI, *, root: Path) -> None:
    @app.get("/api/chat/conversations/{conversation_id}/agent-streams")
    async def room_agent_streams(
        conversation_id: str,
        request: Request,
    ) -> StreamingResponse:
        with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
            exists = conn.execute(
                "select 1 from conversations where id = ?", (conversation_id,)
            ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="conversation not found")

        initial_raw = await asyncio.to_thread(_read_cache, root, conversation_id)
        initial = await asyncio.to_thread(_prove_projection, root, conversation_id, initial_raw)
        last_event_id = request.headers.get("last-event-id", "").strip()
        initial_event = (
            "reset" if last_event_id and last_event_id != _event_id(initial) else ("projection")
        )

        async def events() -> AsyncIterator[bytes]:
            projection = initial
            last_id = _event_id(projection)
            last_heartbeat = time.monotonic()
            yield encode_stream_projection_event(initial_event, projection)
            while not await request.is_disconnected():
                await asyncio.sleep(_POLL_INTERVAL_S)
                current_raw = await asyncio.to_thread(_read_cache, root, conversation_id)
                current_id = _cache_event_id(current_raw)
                if current_id != last_id:
                    current = await asyncio.to_thread(
                        _prove_projection, root, conversation_id, current_raw
                    )
                    event = (
                        "reset" if current.get("epoch") != projection.get("epoch") else "projection"
                    )
                    projection = current
                    last_id = current_id
                    last_heartbeat = time.monotonic()
                    yield encode_stream_projection_event(event, current)
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


__all__ = ["register_room_agent_stream_routes"]
