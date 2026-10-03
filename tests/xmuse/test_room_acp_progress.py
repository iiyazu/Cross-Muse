from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from xmuse_core.chat.room_acp_transport import (
    AcpRoomObservationTransport,
    AcpTransportConfig,
    _AcpSession,
    _RoomAcpClient,
    _tool_call_fingerprint,
)
from xmuse_core.chat.room_host import RoomTurnProgress


def _client(tmp_path: Path) -> _RoomAcpClient:
    transport = AcpRoomObservationTransport(
        config=AcpTransportConfig(workspace=tmp_path, command=("true",)),
        registry_path=tmp_path / "god_sessions.json",
    )
    session = _AcpSession(
        generation=1,
        god_session_id="god-1",
        acp_session_id="sess-1",
        process=SimpleNamespace(returncode=None),
    )
    return _RoomAcpClient(transport, session)


def _message(text: str = "hello") -> Any:
    return SimpleNamespace(
        session_update="agent_message_chunk",
        content=SimpleNamespace(text=text),
    )


async def _drive(tmp_path: Path, updates: list[Any], **kwargs: Any) -> list[RoomTurnProgress]:
    client = _client(tmp_path)
    events: list[RoomTurnProgress] = []
    client.begin_turn("turn-1", progress=events.append)
    for update in updates:
        await client.session_update("sess-1", update, **kwargs)
    return events


def test_session_update_drives_progress_kinds(tmp_path: Path) -> None:
    updates = [
        _message(),
        SimpleNamespace(
            session_update="agent_thought_chunk",
            content=SimpleNamespace(text="thinking"),
        ),
        SimpleNamespace(session_update="plan", content=[{"text": "step"}]),
        SimpleNamespace(
            session_update="tool_call",
            tool_call_id="t1",
            title="Read foo.txt",
            raw_input={"path": "foo.txt"},
            status="pending",
        ),
        SimpleNamespace(
            session_update="tool_call_update",
            tool_call_id="t1",
            title=None,
            raw_input=None,
            status="completed",
        ),
        SimpleNamespace(session_update="available_commands_update"),
    ]
    events = asyncio.run(_drive(tmp_path, updates))

    # The announcement only proves liveness; the finished call carries the identity.
    assert [event.kind for event in events] == [
        "message",
        "thought",
        "plan",
        "tool_update",
        "tool_call",
        "other",
    ]
    assert all(event.fingerprint is None for event in events if event.kind != "tool_call")
    expected = hashlib.sha256(
        (
            "Read foo.txt\0"
            + json.dumps({"path": "foo.txt"}, sort_keys=True, separators=(",", ":"))
        ).encode()
    ).hexdigest()
    assert events[4].fingerprint == expected


def test_placeholder_announcements_do_not_make_distinct_commands_identical(
    tmp_path: Path,
) -> None:
    # Claude announces every shell call as "Terminal" with empty input and fills
    # in the real command in a later update.
    updates: list[Any] = []
    for index, command in enumerate(["ls", "cat a.txt", "git status"]):
        call_id = f"t{index}"
        updates += [
            SimpleNamespace(
                session_update="tool_call",
                tool_call_id=call_id,
                title="Terminal",
                raw_input={},
                status="pending",
            ),
            SimpleNamespace(
                session_update="tool_call_update",
                tool_call_id=call_id,
                title=command,
                raw_input={"command": command},
                status="in_progress",
            ),
            SimpleNamespace(
                session_update="tool_call_update",
                tool_call_id=call_id,
                title=None,
                raw_input=None,
                status="completed",
            ),
        ]
    events = asyncio.run(_drive(tmp_path, updates))
    fingerprints = [event.fingerprint for event in events if event.kind == "tool_call"]
    assert len(fingerprints) == 3
    assert len(set(fingerprints)) == 3


def test_tool_call_fingerprint_is_stable_and_argument_sensitive() -> None:
    first = _tool_call_fingerprint("Read a", {"path": "a", "n": 1})
    again = _tool_call_fingerprint("Read a", {"n": 1, "path": "a"})
    assert first == again
    assert _tool_call_fingerprint("Read a", {"path": "b"}) != first
    assert _tool_call_fingerprint("Read other", {"path": "a", "n": 1}) != first


def test_progress_ignores_foreign_session_and_missing_callback(tmp_path: Path) -> None:
    client = _client(tmp_path)
    events: list[RoomTurnProgress] = []
    client.begin_turn("turn-1", progress=events.append)
    asyncio.run(client.session_update("other-session", _message()))
    assert events == []

    quiet = _client(tmp_path)
    quiet.begin_turn("turn-1")
    asyncio.run(quiet.session_update("sess-1", _message()))

    client.end_turn()
    asyncio.run(client.session_update("sess-1", _message()))
    assert events == []


def test_raising_progress_callback_does_not_break_turn(tmp_path: Path) -> None:
    client = _client(tmp_path)

    def bad(_progress: RoomTurnProgress) -> None:
        raise RuntimeError("boom")

    client.begin_turn("turn-1", progress=bad)
    asyncio.run(client.session_update("sess-1", _message()))
    asyncio.run(
        client.session_update(
            "sess-1",
            SimpleNamespace(
                session_update="tool_call",
                title="mcp__xmuse-room__chat_room_submit_outcome",
                raw_input={},
                status="pending",
            ),
        )
    )
    client.end_turn()
