from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI

from xmuse import chat_api_bootstrap
from xmuse.chat_api_bootstrap import BOOTSTRAP_SCHEMA, register_bootstrap_route
from xmuse.memoryos_companion import MemoryOSCompanion


def _endpoint(app: FastAPI):
    return next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", None) == "/api/chat/bootstrap"
    )


def test_bootstrap_is_safe_and_reports_companion(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table conversations (conversation_id text primary key)")
        conn.execute("insert into conversations values ('room-1')")
    companion = MemoryOSCompanion(
        root=tmp_path / "private-memory",
        executable=tmp_path / "private-memory" / ".venv" / "bin" / "memoryos",
        version="0.2.1",
        profile="full-local",
        capability_digest="sha256:" + "a" * 64,
    )
    monkeypatch.setattr(chat_api_bootstrap, "discover_managed_companion", lambda: companion)
    app = FastAPI()
    register_bootstrap_route(
        app,
        root=tmp_path,
        memory_status_provider=lambda: {"state": "ready", "code": "ok", "path": str(tmp_path)},
        execution_profile_provider=lambda: {
            "profile_id": "xmuse-monorepo/v2",
            "readiness": {"state": "ready", "ready": True},
            "profile_digest": "secret",
        },
    )

    payload = _endpoint(app)()

    assert payload["schema_version"] == BOOTSTRAP_SCHEMA
    assert payload["has_rooms"] is True
    assert payload["memory"] == {
        "mode": "auto",
        "companion": "installed",
        "version": "0.2.1",
        "profile": "full-local",
        "runtime": {"state": "ready", "code": "ok"},
        "capability_digest": "sha256:" + "a" * 64,
    }
    assert payload["recommended_action"] == "open_room"
    assert str(tmp_path) not in json.dumps(payload)


def test_bootstrap_missing_companion_recommends_install(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(chat_api_bootstrap, "discover_managed_companion", lambda: None)
    monkeypatch.setattr(chat_api_bootstrap.shutil, "which", lambda _name: None)
    app = FastAPI()
    register_bootstrap_route(
        app,
        root=tmp_path,
        memory_status_provider=lambda: {"state": "disabled", "code": "memoryos_disabled"},
        execution_profile_provider=lambda: {
            "profile_id": None,
            "readiness": {"state": "unknown", "ready": False},
        },
    )

    payload = _endpoint(app)()

    assert payload["memory"]["companion"] == "missing"
    assert payload["codex"] == {"launcher_available": False}
    assert payload["recommended_action"] == "install_memory"
