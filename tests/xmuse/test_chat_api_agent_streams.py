from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.chat_api_agent_streams import register_room_agent_stream_routes


def _client(root: Path) -> TestClient:
    app = FastAPI()
    register_room_agent_stream_routes(app, root=root)
    return TestClient(app)


def test_agent_stream_sse_rejects_unknown_room(tmp_path: Path) -> None:
    RoomTestStore(tmp_path / "chat.db")

    response = _client(tmp_path).get("/api/chat/conversations/missing/agent-streams")

    assert response.status_code == 404


@pytest.fixture
def disconnect_after_first_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def disconnected(_request: Request) -> bool:
        return True

    monkeypatch.setattr(Request, "is_disconnected", disconnected)


def test_agent_stream_sse_starts_with_safe_full_projection(
    tmp_path: Path,
    disconnect_after_first_event: None,
) -> None:
    room = RoomTestStore(tmp_path / "chat.db").create_conversation("Room")

    with _client(tmp_path).stream(
        "GET", f"/api/chat/conversations/{room.id}/agent-streams"
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store, no-cache"
        lines = response.iter_lines()
        assert next(lines) == "event: projection"
        event_id = next(lines)
        data = next(lines)

    assert event_id == "id: unavailable:0"
    assert data.startswith("data: ")
    payload = json.loads(data.removeprefix("data: "))
    assert payload == {
        "conversation_id": room.id,
        "epoch": None,
        "projection_available": False,
        "proof_boundary": "provider_preview_not_room_or_codex_authority",
        "schema_version": "room_agent_stream_projection/v1",
        "stream_seq": 0,
        "streams": [],
    }


def test_agent_stream_last_event_id_mismatch_resets(
    tmp_path: Path,
    disconnect_after_first_event: None,
) -> None:
    room = RoomTestStore(tmp_path / "chat.db").create_conversation("Room")

    with _client(tmp_path).stream(
        "GET",
        f"/api/chat/conversations/{room.id}/agent-streams",
        headers={"Last-Event-ID": "old:9"},
    ) as response:
        assert next(response.iter_lines()) == "event: reset"
