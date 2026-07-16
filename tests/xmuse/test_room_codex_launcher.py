from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.agents import room_codex_launcher
from xmuse_core.agents.codex_persistent_session import CodexAppServerSession
from xmuse_core.agents.room_codex_scopes import (
    ROOM_DELIVERY_SESSION_SCOPE,
    ROOM_NATIVE_SESSION_SCOPE,
)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("architect", "medium"),
        ("reviewer", "medium"),
        ("execute", "high"),
        ("critic", "high"),
        ("unknown", "high"),
    ],
)
def test_room_default_effort_is_role_bound(role: str, expected: str) -> None:
    assert room_codex_launcher._default_reasoning_effort_for_role(role) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected"),
    [("architect", "medium"), ("review", "medium"), ("builder", "high")],
)
async def test_room_launcher_passes_role_effort_to_codex_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    role: str,
    expected: str,
) -> None:
    captured: dict[str, object] = {}

    async def fake_spawn(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(CodexAppServerSession, "spawn", fake_spawn)

    launcher = room_codex_launcher.RoomCodexLauncher()
    await launcher.spawn_persistent_session(role=role, worktree=tmp_path)

    assert captured["model"] == launcher.model
    assert captured["reasoning_effort"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected_mcp"),
    [
        (ROOM_DELIVERY_SESSION_SCOPE, True),
        (ROOM_NATIVE_SESSION_SCOPE, False),
    ],
)
async def test_room_launcher_separates_delivery_and_native_mcp_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scope: str,
    expected_mcp: bool,
) -> None:
    captured: dict[str, object] = {}

    async def fake_spawn(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(CodexAppServerSession, "spawn", fake_spawn)

    launcher = room_codex_launcher.RoomCodexLauncher()
    await launcher.spawn_persistent_session(
        role="review",
        worktree=tmp_path,
        feature_scope_id=scope,
    )

    assert captured["enable_mcp"] is expected_mcp


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected_resume"),
    [
        (ROOM_DELIVERY_SESSION_SCOPE, None),
        (ROOM_NATIVE_SESSION_SCOPE, "thread-existing"),
    ],
)
async def test_room_launcher_resumes_only_native_provider_threads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scope: str,
    expected_resume: str | None,
) -> None:
    captured: dict[str, object] = {}

    async def fake_spawn(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(CodexAppServerSession, "spawn", fake_spawn)

    launcher = room_codex_launcher.RoomCodexLauncher()
    await launcher.spawn_persistent_session(
        role="review",
        worktree=tmp_path,
        provider_session_id="thread-existing",
        feature_scope_id=scope,
    )

    assert captured["resume_thread_id"] == expected_resume
