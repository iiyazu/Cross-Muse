"""Main-window control (``docs/contracts/main_window_control_v1.md``).

Plugin routes for Room creation, Human messages and Human review decisions,
the terminal ``pair`` command and the Workroom operator token file. Grant
basics (pairing, bearer checks, splits) are covered in ``test_plugin_grant.py``.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.xmuse.board_scenarios import build_scenario
from xmuse.chat_api import create_app
from xmuse.chat_api_board import register_room_board_routes
from xmuse.chat_api_grants import register_plugin_grant_routes
from xmuse.workroom_operator_token import (
    OperatorTokenFileError,
    read_operator_token,
    remove_operator_token,
    write_operator_token,
)
from xmuse.workroom_pair import PairDependencies, run_pair
from xmuse_core.chat.room_database import RoomDatabase

OPERATOR_TOKEN = "operator-secret"
OPERATOR_HEADERS = {"X-XMuse-Operator-Token": OPERATOR_TOKEN}
ALL_SCOPES = ["board.review.decide", "board.split.decide", "room.create", "room.message"]
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "docs/contracts/schemas/plugin_grant.v2.json").read_text())


def _available() -> dict[str, dict[str, object]]:
    return {kind: {"available": True} for kind in ("codex", "claude", "antigravity", "opencode")}


def _app_client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path, auth_token=OPERATOR_TOKEN, provider_capabilities_provider=_available)
    return TestClient(app)


def _pair(
    client: TestClient,
    *,
    scopes: list[str] | None = None,
    rooms: list[str] | None = None,
    host: str = "claude-code",
) -> tuple[dict[str, Any], dict[str, str]]:
    issued = client.post(
        "/api/chat/operator/plugin-grants",
        json={"host": host, "scopes": scopes or ALL_SCOPES, "conversation_ids": rooms or []},
        headers=OPERATOR_HEADERS,
    )
    assert issued.status_code == 201, issued.text
    exchanged = client.post(
        "/api/chat/plugin/grants/exchange",
        json={"pairing_code": issued.json()["pairing_code"], "host": host},
    )
    assert exchanged.status_code == 200, exchanged.text
    payload = exchanged.json()
    return payload["grant"], {"Authorization": f"Bearer {payload['secret']}"}


def _room_body(key: str = "k1", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "client_request_id": key,
        "title": "Coordinate the refactor",
        "lead": {"cli_kind": "opencode"},
        "owners": [{"cli_kind": "opencode"}, {"cli_kind": "claude"}],
        "reviewer": None,
        "review_policy": "off",
    }
    body.update(overrides)
    return body


def _clear_rate_limit(root: Path, grant_id: str) -> None:
    with RoomDatabase(root / "chat.db").connect() as conn:
        conn.execute(
            "update plugin_grants_v2 set last_room_create_at = null where grant_id = ?",
            (grant_id,),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 4.1 Room creation
# ---------------------------------------------------------------------------


def test_room_create_builds_an_addressed_owner_room_and_joins_the_grant(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    grant, bearer = _pair(client)

    created = client.post("/api/chat/plugin/rooms", json=_room_body(), headers=bearer)
    assert created.status_code == 201, created.text
    body = created.json()
    jsonschema.validate(body, SCHEMA)
    assert [item["role"] for item in body["participants"]] == ["lead", "owner-1", "owner-2"]
    assert body["room_count"] == 1 and body["replayed"] is False

    listed = client.get(
        "/api/chat/operator/plugin-grants",
        params={"host": "claude-code"},
        headers=OPERATOR_HEADERS,
    ).json()["grants"]
    assert listed[0]["conversation_ids"] == [body["conversation_id"]]
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        owners = conn.execute(
            "select workspace_access from participants where conversation_id = ? "
            "and role like 'owner-%'",
            (body["conversation_id"],),
        ).fetchall()
        policy = conn.execute(
            "select mode from room_collaboration_policies where conversation_id = ?",
            (body["conversation_id"],),
        ).fetchone()
    assert {row["workspace_access"] for row in owners} == {"workspace_write"}
    assert policy is not None and policy["mode"] == "addressed"
    assert grant["grant_id"]


def test_room_create_scope_and_body_validation(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    _grant, message_only = _pair(client, scopes=["room.message"])
    denied = client.post("/api/chat/plugin/rooms", json=_room_body(), headers=message_only)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "plugin_grant_scope_denied"

    _grant2, bearer = _pair(client, host="opencode")
    invalid = [
        _room_body(workspace="/etc"),
        _room_body(owners=[]),
        _room_body(owners=[{"cli_kind": "codex"}]),
        _room_body(owners=[{"cli_kind": "opencode"}] * 7),
        _room_body(owners=[{"cli_kind": "opencode", "model": "x"}]),
        _room_body(lead={"cli_kind": "a2a"}),
        _room_body(title=""),
        _room_body(review_policy="always"),
    ]
    for body in invalid:
        response = client.post("/api/chat/plugin/rooms", json=body, headers=bearer)
        assert response.status_code == 422, body
        assert response.json()["detail"]["code"] == "plugin_room_request_invalid"


def test_room_create_idempotency_is_per_grant(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    _first, bearer = _pair(client)
    _second, other_bearer = _pair(client)

    created = client.post("/api/chat/plugin/rooms", json=_room_body("same"), headers=bearer)
    replay = client.post("/api/chat/plugin/rooms", json=_room_body("same"), headers=bearer)
    assert replay.status_code == 201
    assert replay.json()["conversation_id"] == created.json()["conversation_id"]
    assert replay.json()["replayed"] is True

    other = client.post("/api/chat/plugin/rooms", json=_room_body("same"), headers=other_bearer)
    assert other.status_code == 201
    assert other.json()["conversation_id"] != created.json()["conversation_id"]


def test_room_create_accepts_a_maximum_length_key(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    _grant, bearer = _pair(client)
    created = client.post("/api/chat/plugin/rooms", json=_room_body("k" * 200), headers=bearer)
    assert created.status_code == 201, created.text
    too_long = client.post("/api/chat/plugin/rooms", json=_room_body("k" * 201), headers=bearer)
    assert too_long.status_code == 422


def test_room_create_rate_limit_and_room_cap(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    grant, bearer = _pair(client)
    assert (
        client.post("/api/chat/plugin/rooms", json=_room_body("a"), headers=bearer).status_code
        == 201
    )
    limited = client.post("/api/chat/plugin/rooms", json=_room_body("b"), headers=bearer)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "plugin_room_rate_limited"
    assert int(limited.headers["retry-after"]) >= 1

    for index in range(15):
        _clear_rate_limit(tmp_path, grant["grant_id"])
        response = client.post(
            "/api/chat/plugin/rooms", json=_room_body(f"fill-{index}"), headers=bearer
        )
        assert response.status_code == 201, response.text
    _clear_rate_limit(tmp_path, grant["grant_id"])
    capped = client.post("/api/chat/plugin/rooms", json=_room_body("over"), headers=bearer)
    assert capped.status_code == 409
    assert capped.json()["detail"]["code"] == "plugin_grant_room_limit"


# ---------------------------------------------------------------------------
# 4.2 Human messages
# ---------------------------------------------------------------------------


def test_message_records_provenance_and_checks_room_and_mentions(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    grant, bearer = _pair(client)
    room = client.post("/api/chat/plugin/rooms", json=_room_body(), headers=bearer).json()
    conversation_id = room["conversation_id"]
    owner = next(item for item in room["participants"] if item["role"] == "owner-1")

    posted = client.post(
        f"/api/chat/plugin/rooms/{conversation_id}/messages",
        json={
            "client_request_id": "m1",
            "message": "Please own the parser module.",
            "mentions": [owner["participant_id"]],
        },
        headers=bearer,
    )
    assert posted.status_code == 201, posted.text
    activity_id = posted.json()["activity_id"]
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select payload_json from room_activities where activity_id = ?", (activity_id,)
        ).fetchone()
        audience = conn.execute(
            "select participant_id from room_observations where activity_id = ?",
            (activity_id,),
        ).fetchall()
    payload = json.loads(row["payload_json"])
    assert payload["via"] == "plugin:claude-code"
    assert payload["grant_id"] == grant["grant_id"]
    assert [item["participant_id"] for item in audience] == [owner["participant_id"]]

    stranger = client.post(
        f"/api/chat/plugin/rooms/{conversation_id}/messages",
        json={"client_request_id": "m2", "message": "hi", "mentions": ["participant_nope"]},
        headers=bearer,
    )
    assert stranger.status_code == 422
    assert stranger.json()["detail"]["code"] == "plugin_message_mention_invalid"

    _outsider_grant, outsider = _pair(client, host="opencode")
    outside = client.post(
        f"/api/chat/plugin/rooms/{conversation_id}/messages",
        json={"client_request_id": "m3", "message": "hi"},
        headers=outsider,
    )
    assert outside.status_code == 404
    assert outside.json()["detail"]["code"] == "room_conversation_unknown"

    _create_only, create_only = _pair(client, scopes=["room.create"], rooms=[conversation_id])
    no_scope = client.post(
        f"/api/chat/plugin/rooms/{conversation_id}/messages",
        json={"client_request_id": "m4", "message": "hi"},
        headers=create_only,
    )
    assert no_scope.status_code == 403


def test_message_without_bearer_or_with_origin_is_refused_first(tmp_path: Path) -> None:
    client = _app_client(tmp_path)
    _grant, bearer = _pair(client)
    room = client.post("/api/chat/plugin/rooms", json=_room_body(), headers=bearer).json()
    url = f"/api/chat/plugin/rooms/{room['conversation_id']}/messages"
    body = {"client_request_id": "m1", "message": "hi"}
    assert client.post(url, json=body).status_code == 401
    assert client.post(url, json=body, headers={**bearer, "Origin": "http://x"}).status_code == 403
    assert (
        client.post(
            url, content=json.dumps(body), headers={**bearer, "Content-Type": "text/plain"}
        ).status_code
        == 415
    )


# ---------------------------------------------------------------------------
# 4.4 / 4.5 Human review decisions and material
# ---------------------------------------------------------------------------


def _review_client(tmp_path: Path, scenario: str) -> tuple[TestClient, str, str]:
    ctx = build_scenario(scenario, tmp_path)
    target = tmp_path / "chat.db"
    if Path(ctx["db"]) != target:
        shutil.copy(ctx["db"], target)
    app = FastAPI()
    register_room_board_routes(app, root=tmp_path, operator_token=OPERATOR_TOKEN)
    register_plugin_grant_routes(app, root=tmp_path, operator_token=OPERATOR_TOKEN)
    with RoomDatabase(target).connect(readonly=True) as conn:
        row = conn.execute(
            "select review_id from room_board_reviews where status = 'pending' "
            "order by rowid desc limit 1"
        ).fetchone()
    assert row is not None
    return TestClient(app), str(ctx["conversation_id"]), str(row["review_id"])


def test_review_waiting_for_a_participant_is_not_decidable(tmp_path: Path) -> None:
    client, conversation_id, review_id = _review_client(tmp_path, "review_participant_pending")
    _grant, bearer = _pair(client, rooms=[conversation_id])
    material = client.get(
        f"/api/chat/plugin/board-reviews/{review_id}/material",
        params={"conversation_id": conversation_id},
        headers=bearer,
    )
    assert material.status_code == 409
    assert material.json()["detail"]["code"] == "plugin_review_not_human"
    decided = client.post(
        f"/api/chat/plugin/board-reviews/{review_id}/decision",
        json={
            "conversation_id": conversation_id,
            "verdict": "endorse",
            "expected_digest": "sha256:" + "0" * 64,
            "summary": "ok",
            "findings": [],
        },
        headers=bearer,
    )
    assert decided.status_code == 409
    assert decided.json()["detail"]["code"] == "plugin_review_not_human"


def test_human_review_decided_from_the_plugin(tmp_path: Path) -> None:
    client, conversation_id, review_id = _review_client(tmp_path, "review_operator_pending")
    grant, bearer = _pair(client, rooms=[conversation_id])

    material = client.get(
        f"/api/chat/plugin/board-reviews/{review_id}/material",
        params={"conversation_id": conversation_id},
        headers=bearer,
    )
    assert material.status_code == 200, material.text
    digest = material.json()["digest"]
    body = {
        "conversation_id": conversation_id,
        "verdict": "endorse",
        "expected_digest": digest,
        "summary": "Read the diff; looks right.",
        "findings": [],
    }
    with_via = client.post(
        f"/api/chat/plugin/board-reviews/{review_id}/decision",
        json={**body, "decided_via": "web"},
        headers=bearer,
    )
    assert with_via.status_code == 422

    decided = client.post(
        f"/api/chat/plugin/board-reviews/{review_id}/decision", json=body, headers=bearer
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "endorsed"
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select decided_via, operator_identity, verdict_json from room_board_reviews "
            "where review_id = ?",
            (review_id,),
        ).fetchone()
    assert row["decided_via"] == "plugin:claude-code"
    assert row["operator_identity"] == f"plugin-grant:{grant['grant_id']}"
    assert json.loads(row["verdict_json"])["grant_id"] == grant["grant_id"]

    board = client.get(f"/api/chat/conversations/{conversation_id}/board").json()
    reviews = [event for event in board["events"] if event["kind"] == "review"]
    assert any(event["data"]["decided_via"] == "plugin:claude-code" for event in reviews)

    again = client.post(
        f"/api/chat/plugin/board-reviews/{review_id}/decision", json=body, headers=bearer
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "plugin_review_not_human"


def test_review_routes_require_scope_and_room(tmp_path: Path) -> None:
    client, conversation_id, review_id = _review_client(tmp_path, "review_operator_pending")
    _g1, split_only = _pair(client, scopes=["board.split.decide"], rooms=[conversation_id])
    denied = client.get(
        f"/api/chat/plugin/board-reviews/{review_id}/material",
        params={"conversation_id": conversation_id},
        headers=split_only,
    )
    assert denied.status_code == 403
    _g2, no_room = _pair(client, host="opencode")
    outside = client.get(
        f"/api/chat/plugin/board-reviews/{review_id}/material",
        params={"conversation_id": conversation_id},
        headers=no_room,
    )
    assert outside.status_code == 404
    assert outside.json()["detail"]["code"] == "room_board_review_unknown"


# ---------------------------------------------------------------------------
# 3. Terminal pairing and the operator token file
# ---------------------------------------------------------------------------


def test_operator_token_file_is_private_and_removable(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "operator-token"
    write_operator_token(path, "tok-1")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert read_operator_token(path) == "tok-1"
    write_operator_token(path, "tok-2")
    assert read_operator_token(path) == "tok-2"

    os.chmod(path, 0o640)
    with pytest.raises(OperatorTokenFileError) as unsafe:
        read_operator_token(path)
    assert unsafe.value.code == "operator_token_file_unsafe"

    os.chmod(path, 0o600)
    link = tmp_path / "runtime" / "linked-token"
    link.symlink_to(path)
    with pytest.raises(OperatorTokenFileError) as linked:
        read_operator_token(link)
    assert linked.value.code == "operator_token_file_unsafe"

    remove_operator_token(path)
    remove_operator_token(path)
    with pytest.raises(OperatorTokenFileError) as missing:
        read_operator_token(path)
    assert missing.value.code == "workroom_not_running"


class _FakeApi:
    def __init__(self, *, activate_after: int = 1) -> None:
        self.calls: list[tuple[str, str, dict[str, str], Any]] = []
        self.polls = 0
        self.activate_after = activate_after

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, Any]:
        decoded = json.loads(body) if body else None
        self.calls.append((method, url, headers, decoded))
        if url.endswith("/api/chat/rooms"):
            return 200, {"rooms": [{"conversation_id": "conv_abc123"}]}
        if method == "POST" and url.endswith("/api/chat/operator/plugin-grants"):
            return 201, {
                "grant": {
                    "grant_id": "grant_1",
                    "scopes": decoded["scopes"],
                    "conversation_ids": decoded["conversation_ids"],
                },
                "pairing_code": "ABCD-EFGH",
            }
        if method == "GET" and "plugin-grants?" in url:
            self.polls += 1
            activated = "2026-10-06T10:00:00Z" if self.polls >= self.activate_after else None
            return 200, {
                "grants": [
                    {
                        "grant_id": "grant_1",
                        "host": "claude-code",
                        "status": "active",
                        "activated_at": activated,
                    }
                ]
            }
        return 404, None


def _pair_deps(
    api: _FakeApi, *, tty: bool = True, token: str | None = "operator-tok-7731"
) -> PairDependencies:
    def read_token(_path: Path) -> str:
        if token is None:
            raise OperatorTokenFileError("workroom_not_running")
        return token

    clock = iter(range(0, 10_000, 2))
    return PairDependencies(
        stdin_isatty=lambda: tty,
        stdout_isatty=lambda: tty,
        http=api,
        sleep=lambda _s: None,
        monotonic=lambda: float(next(clock)),
        out=io.StringIO(),
        read_token=read_token,
    )


def _run(deps: PairDependencies, tmp_path: Path, **kwargs: Any) -> int:
    options: dict[str, Any] = {
        "root": tmp_path,
        "host": "claude-code",
        "room_prefixes": [],
        "scopes": None,
        "ttl_seconds": None,
        "revoke": False,
        "list_only": False,
    }
    options.update(kwargs)
    return run_pair(deps=deps, **options)


def test_pair_refuses_without_a_terminal_before_any_request(tmp_path: Path) -> None:
    api = _FakeApi()
    deps = _pair_deps(api, tty=False)
    assert _run(deps, tmp_path) == 2
    assert api.calls == []
    assert deps.out is not None and "plugin_pair_tty_required" in deps.out.getvalue()


def test_pair_requires_a_running_workroom(tmp_path: Path) -> None:
    api = _FakeApi()
    assert _run(_pair_deps(api, token=None), tmp_path) == 3
    assert api.calls == []


def test_pair_issues_prints_code_and_reports_the_exchange(tmp_path: Path) -> None:
    api = _FakeApi(activate_after=2)
    deps = _pair_deps(api)
    assert _run(deps, tmp_path, room_prefixes=["conv_a"]) == 0
    issue = next(call for call in api.calls if call[0] == "POST")
    assert issue[2]["X-XMuse-Operator-Token"] == "operator-tok-7731"
    assert issue[3] == {
        "host": "claude-code",
        "scopes": ALL_SCOPES,
        "conversation_ids": ["conv_abc123"],
    }
    assert deps.out is not None
    output = deps.out.getvalue()
    assert "ABCD-EFGH" in output
    assert "exchanged by claude-code" in output
    assert "operator-tok-7731" not in output


def test_pair_reports_an_unused_code(tmp_path: Path) -> None:
    api = _FakeApi(activate_after=10_000)
    deps = _pair_deps(api)
    assert _run(deps, tmp_path) == 1
    assert deps.out is not None and "expired unused" in deps.out.getvalue()


def test_pair_exchange_report_names_the_exchanging_host(tmp_path: Path) -> None:
    """A code used by someone else names that host, not our CLI host arg."""

    class _OtherHostApi(_FakeApi):
        def __call__(
            self, method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> tuple[int, Any]:
            status, payload = super().__call__(method, url, headers, body)
            if method == "GET" and isinstance(payload, dict):
                for grant in payload.get("grants", []):
                    grant["host"] = "opencode"
            return status, payload

    api = _OtherHostApi(activate_after=1)
    deps = _pair_deps(api)
    assert _run(deps, tmp_path) == 0
    assert deps.out is not None
    output = deps.out.getvalue()
    assert "exchanged by opencode" in output
    assert "exchanged by claude-code" not in output


def test_pair_room_prefix_must_be_unique(tmp_path: Path) -> None:
    api = _FakeApi()
    assert _run(_pair_deps(api), tmp_path, room_prefixes=["nope"]) == 4


class _PendingApi(_FakeApi):
    """A Room with one proposed split and one operator-pending review."""

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, Any]:
        if method == "GET" and url.endswith("/conversations/conv_abc123/board"):
            self.calls.append((method, url, headers, None))
            return 200, {
                "participants": [{"participant_id": "part_o", "display_name": "Owner 1"}],
                "splits": [
                    {
                        "split_id": "split_1",
                        "status": "proposed",
                        "digest": "sha256:fa827c" + "0" * 58,
                        "modules": [
                            {
                                "module_id": "reports",
                                "owner_participant_id": "part_o",
                                "paths": ["src/reports.py\x1b[2J"],
                            }
                        ],
                    },
                    {"split_id": "split_0", "status": "approved", "digest": "sha256:" + "1" * 64},
                ],
                "modules": [
                    {
                        "module_id": "reports",
                        "review": {
                            "status": "pending",
                            "reviewer_kind": "operator",
                            "review_id": "boardreview_1",
                            "digest": "sha256:70eaa1" + "0" * 58,
                        },
                    }
                ],
            }
        return super().__call__(method, url, headers, body)


def test_pair_pending_prints_what_waits_with_the_digest_prefix(tmp_path: Path) -> None:
    api = _PendingApi()
    deps = _pair_deps(api, token=None)  # read-only: no operator token is needed
    assert _run(deps, tmp_path, pending=True) == 0
    assert deps.out is not None
    output = deps.out.getvalue()
    assert "split split_1" in output and "confirm with: fa827c" in output
    assert "review boardreview_1" in output and "confirm with: 70eaa1" in output
    assert "split_0" not in output
    assert "owner Owner 1" in output and "src/reports.py" in output
    assert "\x1b" not in output
    assert all(call[0] == "GET" for call in api.calls)


def test_pair_pending_is_terminal_only(tmp_path: Path) -> None:
    api = _PendingApi()
    deps = _pair_deps(api, tty=False)
    assert _run(deps, tmp_path, pending=True) == 2
    assert api.calls == []
