from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from xmuse.chat_api_codex import register_room_codex_routes
from xmuse_core.chat.room_codex_bridge import RoomCodexBridgeStore, opaque_guard
from xmuse_core.chat.room_database import RoomDatabase

TOKEN = "operator-secret"
PARTICIPANT_ID = "participant-1"
CONVERSATION_ID = "room-1"


def _seed(root: Path) -> dict[str, str]:
    path = root / "chat.db"
    RoomDatabase(path).initialize()
    with RoomDatabase(path).connect() as conn:
        conn.execute("begin immediate")
        conn.execute(
            "insert into conversations (id, title, created_at) values (?, 'Room', 'now')",
            (CONVERSATION_ID,),
        )
        conn.execute(
            """insert into participants
               (participant_id, conversation_id, role, display_name, cli_kind, model,
                status, created_at) values (?, ?, 'reviewer', 'Reviewer', 'codex',
                'gpt-test', 'active', 'now')""",
            (PARTICIPANT_ID, CONVERSATION_ID),
        )
        conn.commit()
    guards = {
        "session": opaque_guard(PARTICIPANT_ID, "session"),
        "goal": opaque_guard(PARTICIPANT_ID, "goal"),
        "settings": opaque_guard(PARTICIPANT_ID, "settings"),
    }
    bridge = RoomCodexBridgeStore(path)
    bridge.begin_reconcile(
        conversation_id=CONVERSATION_ID,
        participant_id=PARTICIPANT_ID,
        session_guard=guards["session"],
    )
    bridge.apply_native_snapshot(
        conversation_id=CONVERSATION_ID,
        participant_id=PARTICIPANT_ID,
        expected_session_guard=guards["session"],
        state="accepting",
        goal_guard=guards["goal"],
        settings_guard=guards["settings"],
        active_turn_guard=None,
    )
    return guards


def _client(root: Path, *, token: str | None = TOKEN) -> TestClient:
    app = FastAPI()
    register_room_codex_routes(app, root=root, operator_token=token)
    return TestClient(app)


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"X-XMuse-Operator-Token": token}


def _body(guards: dict[str, str], **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "client_action_id": "client-action-1",
        "capability_id": "goal_get",
        "request": {},
        "expected_session_guard": guards["session"],
        "expected_goal_guard": guards["goal"],
        "expected_settings_guard": guards["settings"],
        "expected_turn_guard": None,
    }
    body.update(overrides)
    return body


def _path(participant_id: str = PARTICIPANT_ID) -> str:
    return f"/api/chat/operator/room-participants/{participant_id}/codex-actions"


def test_codex_action_requires_server_operator_auth_and_known_participant(
    tmp_path: Path,
) -> None:
    guards = _seed(tmp_path)
    client = _client(tmp_path)
    body = _body(guards)

    assert client.post(_path(), json=body).status_code == 401
    assert client.post(_path(), headers=_headers("wrong"), json=body).status_code == 401
    missing = client.post(_path("missing"), headers=_headers(), json=body)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "codex_native_participant_not_found"

    unavailable = _client(tmp_path, token=None).post(_path(), json=body)
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "operator_auth_not_configured"


def test_codex_action_is_guarded_idempotent_and_returns_only_safe_receipt(
    tmp_path: Path,
) -> None:
    guards = _seed(tmp_path)
    client = _client(tmp_path)
    body = _body(guards)

    first = client.post(_path(), headers=_headers(), json=body)
    replay = client.post(_path(), headers=_headers(), json=body)

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json() == {
        "action_id": first.json()["action_id"],
        "client_action_id": "client-action-1",
        "status": "requested",
        "participant_id": PARTICIPANT_ID,
        "conversation_id": CONVERSATION_ID,
        "control_seq": 1,
        "capability_id": "goal_get",
        "reason_code": None,
        "updated_at": first.json()["updated_at"],
        "proof_boundary": "operator_action_receipt_not_codex_or_room_authority",
    }
    encoded = json.dumps(first.json(), sort_keys=True)
    for forbidden in (
        guards["session"],
        guards["goal"],
        guards["settings"],
        "expected_session_guard",
        "safe_request",
        "request_json",
        "ack_summary",
        "thread_id",
        "provider_output",
    ):
        assert forbidden not in encoded

    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_codex_bridge_actions").fetchone()[0] == 1
        assert (
            conn.execute(
                """select count(*) from chat_frontend_events
                   where source_authority = 'chat.db:room_codex_bridge'
                     and resource_ref = ?""",
                (first.json()["action_id"],),
            ).fetchone()[0]
            == 1
        )


def test_codex_action_rejects_guard_drift_and_idempotency_conflict(
    tmp_path: Path,
) -> None:
    guards = _seed(tmp_path)
    client = _client(tmp_path)

    stale = client.post(
        _path(),
        headers=_headers(),
        json=_body(guards, expected_goal_guard=opaque_guard("stale")),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "codex_native_goal_guard_conflict"

    accepted = client.post(_path(), headers=_headers(), json=_body(guards))
    assert accepted.status_code == 200
    conflict = client.post(
        _path(),
        headers=_headers(),
        json=_body(guards, capability_id="models_list"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "codex_native_action_idempotency_conflict"


def test_codex_action_rejects_extra_raw_or_capability_invalid_payloads_before_write(
    tmp_path: Path,
) -> None:
    guards = _seed(tmp_path)
    client = _client(tmp_path)
    invalid_payloads = [
        {**_body(guards), "href": "https://evil.invalid"},
        _body(guards, capability_id="raw_rpc"),
        _body(guards, request={"method": "thread/read", "params": {}}),
        _body(
            guards,
            capability_id="goal_set",
            request={"objective": "unsafe", "token_budget": 9_999},
        ),
        _body(
            guards,
            capability_id="settings_update",
            request={"effort": "ultra"},
        ),
        _body(guards, expected_session_guard="thread-private-identifier"),
    ]

    for payload in invalid_payloads:
        response = client.post(_path(), headers=_headers(), json=payload)
        assert response.status_code == 422, response.text

    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_codex_bridge_actions").fetchone()[0] == 0


def test_codex_action_requires_capability_specific_opaque_guards(tmp_path: Path) -> None:
    guards = _seed(tmp_path)
    client = _client(tmp_path)
    cases: tuple[tuple[str, dict[str, object], str], ...] = (
        ("goal_set", {"objective": "Ship", "token_budget": 10_000}, "expected_goal_guard"),
        ("settings_update", {"model": "gpt-test"}, "expected_settings_guard"),
        ("turn_interrupt", {}, "expected_turn_guard"),
    )
    for index, (capability, request, missing_guard) in enumerate(cases):
        response = client.post(
            _path(),
            headers=_headers(),
            json=_body(
                guards,
                client_action_id=f"missing-guard-{index}",
                capability_id=capability,
                request=request,
                **{missing_guard: None},
            ),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"].endswith("_guard_required")

    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_codex_bridge_actions").fetchone()[0] == 0
