from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.room_codex_bridge import RoomCodexBridgeStore, opaque_guard
from xmuse_core.chat.room_codex_projection import _action_descriptors
from xmuse_core.chat.room_codex_projection_cache import RoomCodexProjectionCache
from xmuse_core.chat.room_database import RoomDatabase


def _seed(root: Path) -> tuple[str, str, str, str]:
    path = root / "chat.db"
    RoomDatabase(path).initialize()
    with RoomDatabase(path).connect() as conn:
        conn.execute("insert into conversations values ('room-1', 'Room', 'now')")
        conn.execute(
            """insert into participants
               (participant_id, conversation_id, role, display_name, cli_kind, model,
                status, created_at) values ('participant-1', 'room-1', 'reviewer',
                'Reviewer', 'codex', 'gpt-test', 'active', 'now')"""
        )
        conn.commit()
    session = opaque_guard("session")
    goal = opaque_guard("goal")
    settings = opaque_guard("settings")
    bridge = RoomCodexBridgeStore(path)
    bridge.begin_reconcile(
        conversation_id="room-1",
        participant_id="participant-1",
        session_guard=session,
    )
    bridge.apply_native_snapshot(
        conversation_id="room-1",
        participant_id="participant-1",
        expected_session_guard=session,
        state="accepting",
        goal_guard=goal,
        settings_guard=settings,
        active_turn_guard=None,
    )
    return session, goal, settings, "participant-1"


def _cache(root: Path, session: str, goal: str, settings: str) -> None:
    cache = RoomCodexProjectionCache(root)
    cache.replace_current(
        conversation_id="room-1",
        participant_id="participant-1",
        snapshot={
            "schema_version": "room_codex_native_snapshot/v1",
            "source": "codex_app_server",
            "observed_at": "now",
            "goal": None,
            "settings": {"model": "gpt-test", "effort": "high"},
            "active_turn": False,
            "guards": {
                "session": session,
                "goal": goal,
                "settings": settings,
                "turn": None,
                "thread_id": "private-thread",
            },
        },
        capabilities={
            "schema_version": "room_codex_native_capabilities/v1",
            "source": "codex_app_server",
            "capabilities": [
                {
                    "capability_id": "goal_set",
                    "native_source": "thread/goal/set",
                    "availability": "available",
                    "disabled_reason": None,
                    "session_guard": session,
                },
                {
                    "capability_id": "goal_get",
                    "native_source": "thread/goal/get",
                    "availability": "available",
                    "disabled_reason": None,
                    "session_guard": session,
                },
                {
                    "capability_id": "models_list",
                    "native_source": "model/list",
                    "availability": "available",
                    "disabled_reason": None,
                    "session_guard": session,
                },
            ],
            "models": [
                {
                    "id": "gpt-test",
                    "model": "gpt-test",
                    "display_name": "private-model-description",
                    "description": "provider private prose",
                    "is_default": True,
                    "default_effort": "high",
                    "efforts": ["medium", "high", "max"],
                }
            ],
        },
    )
    cache.append_notification(
        conversation_id="room-1",
        participant_id="participant-1",
        notification={
            "method": "turn/started",
            "params": {
                "turn": {"id": "private-turn", "status": "inProgress"},
                "token": "browser-secret",
                "cwd": "/private/worktree",
            },
        },
    )


def test_api_combines_native_cache_and_durable_bridge_without_private_ids(
    tmp_path: Path,
) -> None:
    session, goal, settings, participant_id = _seed(tmp_path)
    _cache(tmp_path, session, goal, settings)

    with TestClient(create_app(tmp_path, auth_token="operator-secret")) as client:
        response = client.get("/api/chat/conversations/room-1/codex-agents")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["schema_version"] == "room_codex_projection/v1"
    assert payload["native_events"]["event_seq_domain"] == "room_codex_projection_cache"
    agent = payload["participants"][0]
    assert agent["participant"]["participant_id"] == participant_id
    descriptor = agent["capabilities"]["actions"][0]
    assert descriptor["capability_id"] == "goal_set"
    assert descriptor["available"] is True
    assert descriptor["expected_session_guard"] == session
    assert descriptor["confirmation_required"] is False
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "private-thread",
        "private-turn",
        "browser-secret",
        "/private/worktree",
        "provider private prose",
        "private-model-description",
    ):
        assert forbidden not in serialized


def test_missing_or_future_cache_is_non_authoritative_unavailable(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    with TestClient(create_app(tmp_path, auth_token="operator-secret")) as client:
        missing = client.get("/api/chat/conversations/room-1/codex-agents")
        assert missing.status_code == 200
        assert missing.json()["native_events"]["projection_available"] is False
        assert missing.json()["participants"][0]["room_bridge"]["hold"]["state"] == "accepting"

    cache = RoomCodexProjectionCache(tmp_path)
    cache.initialize()
    with sqlite3.connect(cache.path) as conn:
        conn.execute("update projection_meta set schema_version = 'future/v99'")
        conn.commit()
    with TestClient(create_app(tmp_path, auth_token="operator-secret")) as client:
        future = client.get("/api/chat/conversations/room-1/codex-agents")
    assert future.status_code == 200
    assert future.json()["native_events"] == {
        "source": "codex_app_server_projection_cache",
        "projection_available": False,
        "reason_code": "codex_projection_schema_unsupported",
        "event_seq_domain": "room_codex_projection_cache",
        "items": [],
        "latest_event_seq": 0,
        "has_older": False,
        "has_newer": False,
        "next_before_event_seq": None,
        "next_after_event_seq": None,
    }


def test_unfinished_action_disables_every_descriptor_including_read_native_calls(
    tmp_path: Path,
) -> None:
    session, goal, settings, participant_id = _seed(tmp_path)
    _cache(tmp_path, session, goal, settings)
    bridge = RoomCodexBridgeStore(tmp_path / "chat.db")
    action, created = bridge.request_action(
        conversation_id="room-1",
        participant_id=participant_id,
        capability_id="goal_get",
        safe_request={},
        client_action_id="unfinished-goal-get",
        expected_session_guard=session,
        expected_goal_guard=goal,
    )
    assert created is True and action["status"] == "requested"

    with TestClient(create_app(tmp_path, auth_token="operator-secret")) as client:
        response = client.get("/api/chat/conversations/room-1/codex-agents")

    descriptors = response.json()["participants"][0]["capabilities"]["actions"]
    assert {item["capability_id"] for item in descriptors} == {
        "goal_set",
        "goal_get",
        "models_list",
    }
    assert all(item["available"] is False for item in descriptors)
    assert {item["disabled_reason"] for item in descriptors} == {"codex_native_action_pending"}


@pytest.mark.parametrize(
    ("capability_id", "goal_status", "active_turn", "hold_state", "available"),
    [
        ("goal_pause", "active", True, "goal_active", True),
        ("goal_pause", "active", True, "turn_active", False),
        ("goal_resume", "paused", False, "accepting", True),
        ("goal_resume", "paused", True, "turn_active", False),
        ("goal_clear", "paused", False, "accepting", True),
        ("goal_clear", "paused", False, "turn_active", False),
    ],
)
def test_goal_descriptors_require_matching_durable_hold_state(
    capability_id: str,
    goal_status: str,
    active_turn: bool,
    hold_state: str,
    available: bool,
) -> None:
    session = opaque_guard("session")
    goal = opaque_guard("goal")
    descriptors = _action_descriptors(
        "participant-1",
        snapshot={
            "goal": {"status": goal_status},
            "active_turn": active_turn,
            "guards": {"session": session, "goal": goal, "settings": None, "turn": None},
        },
        capabilities={
            "capabilities": [
                {
                    "capability_id": capability_id,
                    "availability": "available",
                    "disabled_reason": None,
                }
            ]
        },
        hold={"session_guard": session, "state": hold_state},
        unresolved_count=0,
        active_attempt_count=0,
        unfinished_action=False,
    )

    assert descriptors[0]["available"] is available
