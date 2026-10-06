from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat import room_setup
from xmuse_core.chat.participant_store import ParticipantStore

AVAILABLE_PROVIDER_CAPABILITIES = {
    "codex": {"available": True, "enabled": True, "confinement": "read_only_sandbox"},
    "claude": {"available": True, "enabled": True, "confinement": "client_permission_gated"},
    "antigravity": {"available": True, "enabled": True, "confinement": "os_read_only_sandbox"},
    "opencode": {"available": True, "enabled": True, "confinement": "os_read_only_sandbox"},
}


def _client(
    root: Path,
    *,
    capabilities: dict[str, dict[str, object]] | None = None,
) -> TestClient:
    resolved = AVAILABLE_PROVIDER_CAPABILITIES if capabilities is None else capabilities
    return TestClient(
        create_app(
            root,
            workroom_runtime_inspector=lambda *_: {
                "state": "stopped",
                "ready": False,
                "code": "room_runtime_stopped",
            },
            provider_capabilities_provider=lambda: resolved,
        )
    )


def test_default_room_setup_creates_only_room_participants(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/api/chat/conversations",
        json={
            "title": "Clean Room",
            "client_request_id": "setup-clean-room",
            "roster_template_id": "builtin.development",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["client_request_id"] == "setup-clean-room"
    assert payload["setup"] == {
        "schema_version": "room_setup/v2",
        "roster_template_id": "builtin.development",
        "participant_count": 4,
        "authority": "chat.db",
    }
    assert payload["participant_sessions"] == []
    assert [item["role"] for item in payload["participants"]] == [
        "architect",
        "execute",
        "review",
        "critic",
    ]
    assert all(item["role"] != "init" for item in payload["participants"])
    assert all(
        item["persona_snapshot"]["schema_version"] == "persona_snapshot/v1"
        and item["persona_snapshot"]["role_description"]
        and item["persona_snapshot"]["collaboration_focus"]
        and item["persona_snapshot_sha256"].startswith("sha256:")
        for item in payload["participants"]
    )
    assert not (tmp_path / "god_sessions.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        tables = {
            row[0] for row in conn.execute("select name from sqlite_schema where type = 'table'")
        }
        assert (
            not {
                "role_templates",
                "chat_inbox_items",
                "groupchat_worklist",
            }
            & tables
        )
        assert (
            conn.execute(
                "select count(*) from messages where conversation_id = ?", (payload["id"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "select count(*) from room_memory_bindings where conversation_id = ?",
                (payload["id"],),
            ).fetchone()[0]
            == 3
        )
        assert (
            conn.execute(
                "select count(*) from room_memory_outbox where conversation_id = ?",
                (payload["id"],),
            ).fetchone()[0]
            == 0
        )


def test_room_setup_options_are_safe_bounded_and_keep_builtin_when_custom_is_invalid(
    tmp_path: Path,
) -> None:
    (tmp_path / "workroom_roster_templates.json").write_text(
        '{"roster_templates":[{"template_id":"broken","roles":[]},'
        '{"template_id":"custom.review","display_name":"Review pair",'
        '"description":"Focused review","roles":['
        '{"role_id":"reviewer","provider_profile_ref":"codex.review"}]}]}',
        encoding="utf-8",
    )

    response = _client(tmp_path).get("/api/chat/room-setup-options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "room_setup_options/v1"
    assert payload["default_roster_template_id"] == "builtin.development"
    assert payload["review_policies"] == ["off", "cross_family"]
    assert [item["template_id"] for item in payload["roster_templates"]] == [
        "builtin.development",
        "builtin.heterogeneous-duo",
        "builtin.heterogeneous-trio",
        "builtin.heterogeneous-trio-opencode",
        "custom.review",
    ]
    assert len(payload["roster_templates"][0]["participants"]) == 4
    assert set(payload["roster_templates"][0]["participants"][0]) == {
        "role_id",
        "role",
        "display_name",
        "description",
        "collaboration_focus",
    }
    serialized = response.text
    assert "provider_profile" not in serialized
    assert "model" not in serialized


def test_room_setup_options_mark_templates_with_unavailable_providers(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            tmp_path,
            workroom_runtime_inspector=lambda *_: {
                "state": "stopped",
                "ready": False,
                "code": "room_runtime_stopped",
            },
            provider_capabilities_provider=lambda: {
                "codex": {
                    "available": False,
                    "enabled": False,
                    "confinement": "read_only_sandbox",
                },
                "claude": {
                    "available": True,
                    "enabled": True,
                    "confinement": "client_permission_gated",
                },
                "antigravity": {
                    "available": False,
                    "enabled": False,
                    "confinement": "os_read_only_sandbox",
                },
            },
        )
    )

    payload = client.get("/api/chat/room-setup-options").json()

    by_id = {item["template_id"]: item for item in payload["roster_templates"]}
    assert by_id["builtin.development"]["available"] is False
    assert by_id["builtin.development"]["unavailable_providers"] == ["codex"]
    assert by_id["builtin.heterogeneous-duo"]["available"] is False
    assert by_id["builtin.heterogeneous-duo"]["unavailable_providers"] == ["antigravity"]
    assert by_id["builtin.heterogeneous-trio"]["available"] is False
    assert by_id["builtin.heterogeneous-trio"]["unavailable_providers"] == [
        "antigravity",
        "codex",
    ]


def test_room_setup_options_return_roster_collaboration_presets(tmp_path: Path) -> None:
    payload = _client(tmp_path).get("/api/chat/room-setup-options").json()

    by_id = {item["template_id"]: item for item in payload["roster_templates"]}
    addressed = {"mode": "addressed", "lead_role": "architect"}
    assert by_id["builtin.heterogeneous-duo"]["collaboration"] == addressed
    assert by_id["builtin.heterogeneous-trio"]["collaboration"] == addressed
    assert by_id["builtin.heterogeneous-trio-opencode"]["collaboration"] == addressed
    assert by_id["builtin.development"]["collaboration"] is None


def test_room_setup_rejects_unavailable_template_provider_before_writing(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        capabilities={
            **AVAILABLE_PROVIDER_CAPABILITIES,
            "antigravity": {
                "available": False,
                "enabled": False,
                "confinement": "os_read_only_sandbox",
            },
        },
    )

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Missing researcher provider",
            "client_request_id": "setup-unavailable-template",
            "roster_template_id": "builtin.heterogeneous-duo",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "room_provider_unavailable"
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0
        assert conn.execute("select count(*) from participants").fetchone()[0] == 0
        assert conn.execute("select count(*) from room_setup_requests").fetchone()[0] == 0

    allowed = client.post(
        "/api/chat/conversations",
        json={
            "title": "Codex-only roster",
            "client_request_id": "setup-available-template",
            "roster_template_id": "builtin.development",
        },
    )
    assert allowed.status_code == 201


def test_room_setup_replay_survives_a_provider_becoming_unavailable(tmp_path: Path) -> None:
    body = {
        "title": "Duo",
        "client_request_id": "setup-replay-duo",
        "roster_template_id": "builtin.heterogeneous-duo",
    }
    created = _client(tmp_path).post("/api/chat/conversations", json=body)
    assert created.status_code == 201

    degraded = _client(
        tmp_path,
        capabilities={
            **AVAILABLE_PROVIDER_CAPABILITIES,
            "antigravity": {
                "available": False,
                "enabled": False,
                "confinement": "os_read_only_sandbox",
            },
        },
    )
    replay = degraded.post("/api/chat/conversations", json=body)
    assert replay.status_code == 201
    assert replay.json()["id"] == created.json()["id"]

    fresh = degraded.post(
        "/api/chat/conversations", json={**body, "client_request_id": "setup-new-duo"}
    )
    assert fresh.status_code == 422
    assert fresh.json()["detail"]["code"] == "room_provider_unavailable"


def test_room_setup_rejects_default_roster_with_unavailable_provider(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        capabilities={
            kind: {"available": False, "enabled": False, "confinement": "read_only_sandbox"}
            for kind in ("codex", "claude", "antigravity", "opencode")
        },
    )

    response = client.post(
        "/api/chat/conversations",
        json={"title": "No providers", "client_request_id": "setup-default-unavailable"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "room_provider_unavailable"
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0


def test_room_setup_rejects_unavailable_explicit_participant_provider(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        capabilities={
            **AVAILABLE_PROVIDER_CAPABILITIES,
            "codex": {
                "available": False,
                "enabled": False,
                "confinement": "read_only_sandbox",
            },
        },
    )

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Unavailable participant provider",
            "client_request_id": "setup-unavailable-participant",
            "initial_participants": [
                {
                    "role": "review",
                    "provider_id": "codex",
                    "profile_id": "review",
                    "cli_kind": "codex",
                    "model": "gpt-5.4",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "room_provider_unavailable"
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0
        assert conn.execute("select count(*) from room_setup_requests").fetchone()[0] == 0


@pytest.mark.parametrize("provider", ["a2a"])
def test_room_setup_public_request_rejects_retired_providers_before_writing(
    tmp_path: Path,
    provider: str,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Unsupported remote observer",
            "initial_participants": [
                {
                    "role": "review",
                    "provider_id": provider,
                    "cli_kind": provider,
                    "model": "remote-reviewer",
                }
            ],
        },
    )

    assert response.status_code == 422
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0


@pytest.mark.parametrize("provider", ["claude", "antigravity"])
def test_room_setup_accepts_multi_provider_local_agents(
    tmp_path: Path,
    provider: str,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": f"{provider} Room",
            "client_request_id": f"setup-{provider}-agent",
            "initial_participants": [
                {
                    "role": "review",
                    "display_name": f"{provider} Reviewer",
                    "provider_id": provider,
                    "cli_kind": provider,
                    "model": "reviewer-v1",
                }
            ],
        },
    )

    assert response.status_code == 201
    participant = response.json()["participants"][0]
    assert participant["cli_kind"] == provider
    assert participant["provider_id"] == provider
    assert participant["model"] == "reviewer-v1"
    stored = ParticipantStore(tmp_path / "chat.db").get(participant["participant_id"])
    assert stored.cli_kind == provider
    assert stored.provider_id == provider
    assert stored.status == "active"


def test_room_setup_rejects_unknown_cli_kind_without_writing(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Unknown provider",
            "initial_participants": [
                {
                    "role": "review",
                    "provider_id": "gemini",
                    "cli_kind": "gemini",
                    "model": "gemini-2.5-pro",
                }
            ],
        },
    )

    assert response.status_code == 422
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0
        assert conn.execute("select count(*) from participants").fetchone()[0] == 0


def test_room_setup_accepts_bounded_custom_local_roster(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Focused review",
            "initial_participants": [
                {
                    "role": "review",
                    "display_name": "Security Reviewer",
                    "provider_id": "codex",
                    "profile_id": "review",
                    "cli_kind": "codex",
                    "model": "gpt-5.4",
                }
            ],
        },
    )

    assert response.status_code == 201
    participant = response.json()["participants"][0]
    assert participant["display_name"] == "Security Reviewer"
    stored = ParticipantStore(tmp_path / "chat.db").get(participant["participant_id"])
    assert stored.role == "review"
    assert stored.persona_snapshot is None


def test_default_room_api_rejects_legacy_setup_fields(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/api/chat/conversations",
        json={"title": "No bootstrap", "init_mode": "deterministic"},
    )

    assert response.status_code == 422


def test_room_setup_is_idempotent_and_conflicting_reuse_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    request = {
        "title": "Idempotent Room",
        "client_request_id": "setup-replay",
        "roster_template_id": "builtin.development",
    }

    first = client.post("/api/chat/conversations", json=request)
    replay = client.post("/api/chat/conversations", json=request)
    conflict = client.post(
        "/api/chat/conversations",
        json={**request, "title": "Different Room"},
    )

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "room_setup_idempotency_conflict"
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 1
        assert conn.execute("select count(*) from room_setup_requests").fetchone()[0] == 1
        assert conn.execute("select count(*) from room_memory_bindings").fetchone()[0] == 3


def test_concurrent_room_setup_replay_creates_one_complete_roster(tmp_path: Path) -> None:
    create_app(tmp_path)
    request = room_setup.RoomConversationCreate(
        title="Concurrent Room",
        client_request_id="setup-concurrent",
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: room_setup.RoomSetupService(tmp_path).create_conversation(request),
                range(2),
            )
        )

    assert results[0] == results[1]
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 1
        assert conn.execute("select count(*) from participants").fetchone()[0] == 4
        assert conn.execute("select count(*) from room_setup_requests").fetchone()[0] == 1


def test_room_setup_uses_one_write_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_app(tmp_path)
    original_connect = room_setup.RoomDatabase.connect
    connection_modes: list[bool] = []

    def counting_connect(
        database: room_setup.RoomDatabase,
        *,
        readonly: bool = False,
    ) -> sqlite3.Connection:
        connection_modes.append(readonly)
        return original_connect(database, readonly=readonly)

    monkeypatch.setattr(room_setup.RoomDatabase, "connect", counting_connect)

    result = room_setup.RoomSetupService(tmp_path).create_conversation(
        room_setup.RoomConversationCreate(
            title="Single Connection Room",
            client_request_id="setup-single-connection",
        )
    )

    assert result["client_request_id"] == "setup-single-connection"
    assert connection_modes == [False]
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        conversation_id = result["id"]
        assert (
            conn.execute(
                "select count(*) from conversations where id = ?", (conversation_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "select count(*) from participants where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 4
        )


def test_room_setup_rolls_back_conversation_roster_and_receipt_on_insert_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_app(tmp_path)
    original = room_setup.insert_participant_conn
    calls = 0

    def fail_second(conn: sqlite3.Connection, participant) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected_participant_failure")
        original(conn, participant)

    monkeypatch.setattr(room_setup, "insert_participant_conn", fail_second)
    with pytest.raises(RuntimeError, match="injected_participant_failure"):
        room_setup.RoomSetupService(tmp_path).create_conversation(
            room_setup.RoomConversationCreate(
                title="Rollback Room",
                client_request_id="setup-rollback",
            )
        )

    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0
        assert conn.execute("select count(*) from participants").fetchone()[0] == 0
        assert conn.execute("select count(*) from room_setup_requests").fetchone()[0] == 0
        assert conn.execute("select count(*) from room_memory_bindings").fetchone()[0] == 0


def test_room_setup_rejects_duplicate_roles_and_unbounded_or_extra_participants(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    duplicate = {
        "role": "review",
        "provider_id": "codex",
        "profile_id": "review",
        "cli_kind": "codex",
        "model": "gpt-5.4",
    }

    duplicate_response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Duplicate",
            "client_request_id": "duplicate",
            "initial_participants": [duplicate, duplicate],
        },
    )
    extra_response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Extra",
            "client_request_id": "extra",
            "initial_participants": [{**duplicate, "unexpected": True}],
        },
    )
    too_many_response = client.post(
        "/api/chat/conversations",
        json={
            "title": "Too many",
            "client_request_id": "too-many",
            "initial_participants": [
                {
                    "role": f"custom-{index}",
                    "provider_id": "codex",
                    "cli_kind": "codex",
                    "model": "gpt-5.4",
                }
                for index in range(9)
            ],
        },
    )

    assert duplicate_response.status_code == 422
    assert duplicate_response.json()["detail"]["code"] == "room_participant_role_duplicate"
    assert extra_response.status_code == 422
    assert too_many_response.status_code == 422
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "r" * 65),
        ("display_name", "n" * 121),
        ("model", "m" * 201),
        ("role_template_id", "t" * 201),
    ],
)
def test_room_setup_rejects_oversized_participant_identity_fields(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    participant = {
        "role": "review",
        "display_name": "Reviewer",
        "provider_id": "codex",
        "profile_id": "review",
        "cli_kind": "codex",
        "model": "gpt-5.4",
        field: value,
    }

    response = _client(tmp_path).post(
        "/api/chat/conversations",
        json={"title": "Bounded identity", "initial_participants": [participant]},
    )

    assert response.status_code == 422
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        assert conn.execute("select count(*) from conversations").fetchone()[0] == 0


def test_default_room_api_business_route_allowlist(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    routes = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if route.path.startswith("/api/")
    }

    assert routes == {
        ("/api/chat/conversations", "POST"),
        ("/api/chat/room-setup-options", "GET"),
        ("/api/chat/rooms", "GET"),
        ("/api/chat/bootstrap", "GET"),
        ("/api/chat/conversations/{conversation_id}/room-projection", "GET"),
        ("/api/chat/conversations/{conversation_id}/agent-streams", "GET"),
        ("/api/chat/conversations/{conversation_id}/events", "GET"),
        ("/api/chat/threads/{conversation_id}/messages", "POST"),
        ("/api/chat/operator/room-observations/{observation_id}/cancel", "POST"),
        ("/api/chat/operator/room-observations/{observation_id}/retry", "POST"),
        ("/api/chat/runtime/operations", "GET"),
        ("/api/chat/operator/room-runtime/recover", "POST"),
        ("/api/chat/conversations/{conversation_id}/executions", "GET"),
        ("/api/chat/execution-candidates/{candidate_id}", "GET"),
        ("/api/chat/operator/conversations/{conversation_id}/execution-policy", "PUT"),
        ("/api/chat/operator/execution-candidates/{candidate_id}/decision", "POST"),
        ("/api/chat/operator/execution-runs/{run_id}/cancel", "POST"),
        ("/api/chat/conversations/{conversation_id}/memory", "GET"),
        ("/api/chat/operator/memory-candidates/{candidate_id}/resolve", "POST"),
        ("/api/chat/operator/memory-runtime/rebuild", "POST"),
        ("/api/chat/conversations/{conversation_id}/codex-agents", "GET"),
        ("/api/chat/operator/room-participants/{participant_id}/codex-actions", "POST"),
        ("/api/chat/conversations/{conversation_id}/board", "GET"),
        ("/api/chat/conversations/{conversation_id}/board/summary", "GET"),
        ("/api/chat/conversations/{conversation_id}/board/events", "GET"),
        ("/api/chat/conversations/{conversation_id}/board/stream", "GET"),
        ("/api/chat/conversations/{conversation_id}/board/contracts/{contract_id}", "GET"),
        ("/api/chat/conversations/{conversation_id}/board/reviews/{review_id}", "GET"),
        ("/api/chat/conversations/{conversation_id}/board/verifications/{verification_id}", "GET"),
        (
            "/api/chat/conversations/{conversation_id}/board/integrations/{integration_id}",
            "GET",
        ),
        ("/api/chat/operator/board-splits/{split_id}/decision", "POST"),
        ("/api/chat/operator/board-reviews/{review_id}/material", "GET"),
        ("/api/chat/operator/board-reviews/{review_id}/decision", "POST"),
        ("/api/chat/operator/plugin-grants", "POST"),
        ("/api/chat/operator/plugin-grants", "GET"),
        ("/api/chat/operator/plugin-grants/{grant_id}/revoke", "POST"),
        ("/api/chat/plugin/grants/exchange", "POST"),
        ("/api/chat/plugin/grants/revoke", "POST"),
        ("/api/chat/plugin/board-splits/{split_id}/decision", "POST"),
        ("/api/chat/operator/plugin-grants/revoke-host", "POST"),
        ("/api/chat/plugin/rooms", "POST"),
        ("/api/chat/plugin/rooms/{conversation_id}/messages", "POST"),
        ("/api/chat/plugin/board-reviews/{review_id}/decision", "POST"),
        ("/api/chat/plugin/board-reviews/{review_id}/material", "GET"),
    }
