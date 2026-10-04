"""HTTP tests for the Room board read model v2 routes (contract §7/§8).

TestClient style follows ``test_chat_api_agent_streams.py``: the board routes
are registered on a bare app and scenarios come from the P0a builders in
``tests/xmuse/board_scenarios.py``.
"""

from __future__ import annotations

import json
import re
import shutil
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.xmuse.board_scenarios import build_scenario
from xmuse.chat_api_board import register_room_board_routes
from xmuse_core.chat.room_board import RoomBoardStore
from xmuse_core.chat.room_database import RoomDatabase

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "docs" / "contracts" / "schemas"
FIXTURE_DIR = ROOT / "docs" / "contracts" / "fixtures" / "board_v2"

OPERATOR_HEADERS = {"X-XMuse-Operator-Token": "operator-secret"}

_SCHEMA_SCENARIOS = [
    "empty",
    "split_pending",
    "verified",
    "contract_revised_stale_dependent",
    "injection_text",
]

FORBIDDEN_KEYS = frozenset(
    {
        "patch_digest",
        "patch_text",
        "base_commit",
        "payload",
        "content",
        "lease_token",
        "evidence",
        "audience",
        "id",
        "author",
        "changed_paths",
    }
)
DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _client(root: Path) -> TestClient:
    app = FastAPI()
    register_room_board_routes(app, root=root, operator_token="operator-secret")
    return TestClient(app)


def _scenario(name: str, tmp_path: Path) -> tuple[TestClient, str, dict[str, Any]]:
    """Build a deterministic scenario into ``tmp_path/chat.db`` with a client."""

    ctx = build_scenario(name, tmp_path)
    target = tmp_path / "chat.db"
    if Path(ctx["db"]) != target:
        shutil.copy(ctx["db"], target)
    return _client(tmp_path), ctx["conversation_id"], ctx


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _walk_privacy(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in FORBIDDEN_KEYS, f"forbidden key {key} at {path}"
            _walk_privacy(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_privacy(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if path.endswith(".href"):
            assert value.startswith("/api/"), f"unexpected href at {path}: {value[:60]}"
        else:
            assert not value.startswith("/"), f"absolute path at {path}: {value[:60]}"
        assert not DRIVE_RE.match(value), f"drive path at {path}: {value[:60]}"


def _board_url(conversation_id: str) -> str:
    return f"/api/chat/conversations/{conversation_id}/board"


# ---------------------------------------------------------------------------
# projection / summary bodies, schemas, fixtures, ETag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _SCHEMA_SCENARIOS)
def test_board_projection_matches_schema_and_fixture(tmp_path: Path, name: str) -> None:
    client, conversation_id, _ctx = _scenario(name, tmp_path)

    response = client.get(_board_url(conversation_id))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    jsonschema.validate(body, _load_schema("room_board_projection.v2.json"))
    expected = _fixture(name)["projection"]
    Mine = {key: value for key, value in body.items() if key != "server_time"}
    theirs = {key: value for key, value in expected.items() if key != "server_time"}
    assert Mine == theirs
    assert response.headers["etag"] == f'"{body["revision"]}"'


@pytest.mark.parametrize("name", _SCHEMA_SCENARIOS)
def test_board_summary_matches_schema_and_fixture(tmp_path: Path, name: str) -> None:
    client, conversation_id, _ctx = _scenario(name, tmp_path)

    response = client.get(_board_url(conversation_id) + "/summary")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    jsonschema.validate(body, _load_schema("room_board_summary.v1.json"))
    expected = _fixture(name)["summary"]
    Mine = {key: value for key, value in body.items() if key != "server_time"}
    theirs = {key: value for key, value in expected.items() if key != "server_time"}
    assert Mine == theirs
    assert response.headers["etag"] == f'"{body["revision"]}"'


def test_board_etag_304_round_trip(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)

    for suffix in ("", "/summary"):
        first = client.get(_board_url(conversation_id) + suffix)
        assert first.status_code == 200
        etag = first.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"')

        quoted = client.get(_board_url(conversation_id) + suffix, headers={"If-None-Match": etag})
        assert quoted.status_code == 304
        assert quoted.headers["etag"] == etag
        assert quoted.content == b""

        bare = client.get(
            _board_url(conversation_id) + suffix,
            headers={"If-None-Match": etag.strip('"')},
        )
        assert bare.status_code == 304

        listed = client.get(
            _board_url(conversation_id) + suffix,
            headers={"If-None-Match": f'"stale:revision", {etag}'},
        )
        assert listed.status_code == 304

        changed = client.get(
            _board_url(conversation_id) + suffix,
            headers={"If-None-Match": '"0:deadbeefcafe"'},
        )
        assert changed.status_code == 200


def test_board_etag_changes_when_verification_flips_without_new_activity(
    tmp_path: Path,
) -> None:
    client, conversation_id, ctx = _scenario("verifying_and_waiting", tmp_path)

    before = client.get(_board_url(conversation_id))
    assert before.status_code == 200
    etag_before = before.headers["etag"]
    assert before.json()["board_seq"] > 0

    claimed = RoomBoardStore(tmp_path / "chat.db").claim_next_board_verification(worker_id="w-etag")
    assert claimed is not None

    after = client.get(_board_url(conversation_id))
    assert after.status_code == 200
    assert after.json()["board_seq"] == before.json()["board_seq"]
    assert after.headers["etag"] != etag_before

    stale = client.get(_board_url(conversation_id), headers={"If-None-Match": etag_before})
    assert stale.status_code == 200


# ---------------------------------------------------------------------------
# events: paging, reset, invalid queries, long-poll
# ---------------------------------------------------------------------------


def test_board_events_paging_and_reset(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)
    url = _board_url(conversation_id) + "/events"

    full = client.get(url)
    assert full.status_code == 200
    assert full.headers["cache-control"] == "no-store"
    page = full.json()
    jsonschema.validate(page, _load_schema("room_board_events.v1.json"))
    assert page["has_more"] is False
    assert page["reset"] is False
    assert [event["seq"] for event in page["events"]] == sorted(
        event["seq"] for event in page["events"]
    )

    first = client.get(url, params={"after_seq": 0, "limit": 2}).json()
    assert len(first["events"]) == 2
    assert first["has_more"] is True

    second = client.get(url, params={"after_seq": first["events"][-1]["seq"], "limit": 100}).json()
    assert [event["seq"] for event in second["events"]] == [
        event["seq"] for event in page["events"][2:]
    ]

    ahead = client.get(url, params={"after_seq": page["board_seq"] + 10}).json()
    assert ahead["events"] == []
    assert ahead["reset"] is True
    assert ahead["revision"] == page["revision"]


@pytest.mark.parametrize(
    "params",
    [
        {"after_seq": -1},
        {"after_seq": "abc"},
        {"after_seq": "1.5"},
        {"limit": 0},
        {"limit": 201},
        {"limit": "abc"},
        {"wait": -1},
        {"wait": 31},
        {"wait": "abc"},
        {"wait": "nan"},
    ],
)
def test_board_events_invalid_query(tmp_path: Path, params: dict[str, Any]) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)

    response = client.get(_board_url(conversation_id) + "/events", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "room_board_query_invalid"


def _append_progress_activity(db: Path, conversation_id: str, summary: str) -> int:
    with RoomDatabase(db).connect() as conn:
        seq = int(
            conn.execute(
                "select coalesce(max(seq), 0) + 1 from room_activities where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, causal_depth,
                delivery_mode, created_at)
               values (?, ?, ?, 'board.progress', 'participant', 'god:testsess:perf',
                       null, 'causation_probe', 'board_correlation_probe', 'room',
                       ?, ?, 0, 'active', '2026-01-01T00:00:00.000000Z')""",
            (
                f"activity_probe_{seq}",
                conversation_id,
                seq,
                json.dumps({"type": "board", "conversation_id": conversation_id}),
                json.dumps(
                    {
                        "schema_version": "room_board_activity/v1",
                        "progress_id": f"progress_probe_{seq}",
                        "module_id": "alpha",
                        "status": "working",
                        "summary": summary,
                        "claims": [],
                    }
                ),
            ),
        )
        conn.commit()
    return seq


def test_board_events_long_poll_returns_promptly_on_new_activity(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)
    url = _board_url(conversation_id) + "/events"
    board_seq = client.get(url).json()["board_seq"]

    def _append_later() -> None:
        time.sleep(0.5)
        _append_progress_activity(tmp_path / "chat.db", conversation_id, "late progress")

    worker = threading.Thread(target=_append_later)
    worker.start()
    try:
        begin = time.monotonic()
        response = client.get(url, params={"after_seq": board_seq, "wait": 5})
        elapsed = time.monotonic() - begin
    finally:
        worker.join()

    assert response.status_code == 200
    page = response.json()
    assert [event["seq"] for event in page["events"]] == [board_seq + 1]
    assert page["board_seq"] == board_seq + 1
    assert elapsed < 5


def test_board_events_long_poll_timeout_returns_empty_page(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)
    url = _board_url(conversation_id) + "/events"
    board_seq = client.get(url).json()["board_seq"]

    begin = time.monotonic()
    response = client.get(url, params={"after_seq": board_seq, "wait": 1})
    elapsed = time.monotonic() - begin

    assert response.status_code == 200
    page = response.json()
    assert page["events"] == []
    assert page["board_seq"] == board_seq
    assert page["reset"] is False
    assert elapsed >= 1


def test_board_events_long_poll_returns_on_revision_only_change(tmp_path: Path) -> None:
    client, conversation_id, ctx = _scenario("verifying_and_waiting", tmp_path)
    url = _board_url(conversation_id) + "/events"
    first = client.get(url).json()
    board_seq = first["board_seq"]
    revision = first["revision"]

    def _flip_later() -> None:
        time.sleep(0.5)
        RoomBoardStore(tmp_path / "chat.db").claim_next_board_verification(worker_id="w-poll")

    worker = threading.Thread(target=_flip_later)
    worker.start()
    try:
        begin = time.monotonic()
        response = client.get(url, params={"after_seq": board_seq, "wait": 5, "revision": revision})
        elapsed = time.monotonic() - begin
    finally:
        worker.join()

    assert response.status_code == 200
    page = response.json()
    assert page["events"] == []
    assert page["board_seq"] == board_seq
    assert page["revision"] != revision
    assert elapsed < 5


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------


@pytest.fixture
def disconnect_after_first_event(monkeypatch: pytest.MonkeyPatch) -> None:
    async def disconnected(_request: Request) -> bool:
        return True

    monkeypatch.setattr(Request, "is_disconnected", disconnected)


def _read_sse_first_event(response: Any) -> tuple[str, str, dict[str, Any]]:
    lines = response.iter_lines()
    event = next(lines)
    event_id = next(lines)
    data = next(lines)
    assert event.startswith("event: ")
    assert event_id.startswith("id: ")
    assert data.startswith("data: ")
    return (
        event.removeprefix("event: "),
        event_id.removeprefix("id: "),
        json.loads(data.removeprefix("data: ")),
    )


def test_board_stream_first_event(tmp_path: Path, disconnect_after_first_event: None) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)

    with client.stream("GET", _board_url(conversation_id) + "/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store, no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        name, event_id, payload = _read_sse_first_event(response)

    # Absent Last-Event-ID means "already at the current seq": an empty page.
    assert name == "board"
    jsonschema.validate(payload, _load_schema("room_board_events.v1.json"))
    assert payload["events"] == []
    assert payload["reset"] is False
    assert event_id == str(payload["board_seq"])


def test_board_stream_resume_has_no_gap_or_duplicate(
    tmp_path: Path, disconnect_after_first_event: None
) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)
    url = _board_url(conversation_id) + "/events"
    full = client.get(url).json()
    assert len(full["events"]) >= 3
    resume_from = full["events"][1]["seq"]

    with client.stream(
        "GET",
        _board_url(conversation_id) + "/stream",
        headers={"Last-Event-ID": str(resume_from)},
    ) as response:
        name, event_id, payload = _read_sse_first_event(response)

    direct = client.get(url, params={"after_seq": resume_from}).json()
    assert name == "board"
    assert payload["events"] == direct["events"]
    assert [event["seq"] for event in payload["events"]] == [
        event["seq"] for event in full["events"] if event["seq"] > resume_from
    ]
    assert event_id == str(payload["board_seq"])


def test_board_stream_reset_when_last_event_id_ahead(
    tmp_path: Path, disconnect_after_first_event: None
) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)
    board_seq = client.get(_board_url(conversation_id) + "/events").json()["board_seq"]

    with client.stream(
        "GET",
        _board_url(conversation_id) + "/stream",
        headers={"Last-Event-ID": str(board_seq + 100)},
    ) as response:
        name, _event_id, payload = _read_sse_first_event(response)

    assert name == "reset"
    assert payload["events"] == []
    assert payload["reset"] is True


def test_board_stream_garbage_last_event_id_means_current(
    tmp_path: Path, disconnect_after_first_event: None
) -> None:
    client, conversation_id, _ctx = _scenario("verified", tmp_path)

    with client.stream(
        "GET",
        _board_url(conversation_id) + "/stream",
        headers={"Last-Event-ID": "not-a-seq"},
    ) as response:
        name, _event_id, payload = _read_sse_first_event(response)

    assert name == "board"
    assert payload["events"] == []
    assert payload["reset"] is False


def test_board_stream_heartbeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("xmuse.chat_api_board._HEARTBEAT_INTERVAL_S", 0)
    monkeypatch.setattr("xmuse.chat_api_board._POLL_INTERVAL_S", 0.01)
    calls = {"count": 0}

    async def flaky(_request: Request) -> bool:
        calls["count"] += 1
        return calls["count"] > 2

    monkeypatch.setattr(Request, "is_disconnected", flaky)
    client, conversation_id, _ctx = _scenario("verified", tmp_path)

    with client.stream("GET", _board_url(conversation_id) + "/stream") as response:
        lines = list(response.iter_lines())

    assert ": heartbeat" in lines


# ---------------------------------------------------------------------------
# contract detail
# ---------------------------------------------------------------------------


def test_board_contract_detail_versions_and_content(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("contract_revised_stale_dependent", tmp_path)
    url = _board_url(conversation_id) + "/contracts/api.backend"

    latest = client.get(url)
    assert latest.status_code == 200
    body = latest.json()
    jsonschema.validate(body, _load_schema("room_board_contract.v2.json"))
    assert body["version"] == 2
    assert [entry["version"] for entry in body["versions"]] == [1, 2]
    assert body["content"] == {"text": '{"backend": 2}', "untrusted": True, "truncated": False}

    pinned = client.get(url, params={"version": 1}).json()
    assert pinned["version"] == 1
    assert pinned["content"]["text"] == '{"backend": 1}'
    assert [entry["version"] for entry in pinned["versions"]] == [1, 2]


@pytest.mark.parametrize("version", ["0", "-3", "abc", "1.5"])
def test_board_contract_detail_invalid_version(tmp_path: Path, version: str) -> None:
    client, conversation_id, _ctx = _scenario("contract_revised_stale_dependent", tmp_path)

    response = client.get(
        _board_url(conversation_id) + "/contracts/api.backend", params={"version": version}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "room_board_version_invalid"


def test_board_contract_detail_unknown(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("contract_revised_stale_dependent", tmp_path)

    missing = client.get(_board_url(conversation_id) + "/contracts/api.missing")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "room_board_contract_unknown"

    bad_version = client.get(
        _board_url(conversation_id) + "/contracts/api.backend", params={"version": 9}
    )
    assert bad_version.status_code == 404
    assert bad_version.json()["detail"]["code"] == "room_board_contract_unknown"


# ---------------------------------------------------------------------------
# unknown conversation, privacy, host header
# ---------------------------------------------------------------------------


def test_board_unknown_conversation_on_every_get_route(
    tmp_path: Path, disconnect_after_first_event: None
) -> None:
    _scenario("verified", tmp_path)
    client = _client(tmp_path)
    base = "/api/chat/conversations/missing"

    for url in (
        f"{base}/board",
        f"{base}/board/summary",
        f"{base}/board/events",
        f"{base}/board/contracts/api.backend",
    ):
        response = client.get(url)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "room_conversation_unknown"

    with client.stream("GET", f"{base}/board/stream") as response:
        assert response.status_code == 404


@pytest.mark.parametrize("name", _SCHEMA_SCENARIOS)
def test_board_route_privacy(tmp_path: Path, name: str, disconnect_after_first_event: None) -> None:
    client, conversation_id, _ctx = _scenario(name, tmp_path)
    base = _board_url(conversation_id)

    for url in (base, base + "/summary", base + "/events"):
        _walk_privacy(client.get(url).json(), "$")

    with client.stream("GET", base + "/stream", headers={"Last-Event-ID": "0"}) as response:
        _name, _event_id, payload = _read_sse_first_event(response)
    _walk_privacy(payload, "$")

    detail = client.get(base + "/contracts/api.alpha") if name != "empty" else None
    if detail is not None and detail.status_code == 200:
        body = detail.json()
        content = body.pop("content")
        _walk_privacy(body, "$")
        assert set(content) == {"text", "untrusted", "truncated"}


# ---------------------------------------------------------------------------
# split decision guard + provenance through HTTP
# ---------------------------------------------------------------------------


def test_board_decide_split_digest_and_provenance(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("split_pending", tmp_path)
    board = client.get(_board_url(conversation_id)).json()
    assert len(board["splits"]) == 1
    split = board["splits"][0]
    assert split["status"] == "proposed"
    decide = split["actions"]["decide"]
    assert decide["available"] is True
    assert decide["method"] == "POST"
    assert decide["href"] == f"/api/chat/operator/board-splits/{split['split_id']}/decision"
    assert decide["expected_digest"] == split["digest"]
    assert decide["allowed_decisions"] == ["approve", "reject"]
    path = decide["href"]
    body = {"conversation_id": conversation_id, "decision": "approve"}

    mismatch = client.post(
        path, json={**body, "expected_digest": "sha256:" + "0" * 64}, headers=OPERATOR_HEADERS
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "room_board_split_digest_mismatch"
    still = client.get(_board_url(conversation_id)).json()
    assert still["splits"][0]["status"] == "proposed"

    approved = client.post(
        path,
        json={**body, "expected_digest": split["digest"], "decided_via": "plugin:claude-code"},
        headers=OPERATOR_HEADERS,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    decided = client.get(_board_url(conversation_id)).json()
    assert decided["splits"][0]["status"] == "approved"
    assert decided["splits"][0]["decided_via"] == "plugin:claude-code"
    assert decided["splits"][0]["actions"]["decide"]["available"] is False
    assigned = [event for event in decided["events"] if event["kind"] == "charter_assigned"]
    assert assigned and all(
        event["data"]["decided_via"] == "plugin:claude-code" for event in assigned
    )

    replay = client.post(path, json=body, headers=OPERATOR_HEADERS)
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "room_board_split_decided"


def test_board_decide_split_reject_records_cli_provenance(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("split_pending", tmp_path)
    split_id = client.get(_board_url(conversation_id)).json()["splits"][0]["split_id"]

    rejected = client.post(
        f"/api/chat/operator/board-splits/{split_id}/decision",
        json={"conversation_id": conversation_id, "decision": "reject", "decided_via": "cli"},
        headers=OPERATOR_HEADERS,
    )

    assert rejected.status_code == 200
    board = client.get(_board_url(conversation_id)).json()
    assert board["splits"][0]["status"] == "rejected"
    assert board["splits"][0]["decided_via"] == "cli"
    events = [event for event in board["events"] if event["kind"] == "split_rejected"]
    assert len(events) == 1
    assert events[0]["data"]["decided_via"] == "cli"


def test_board_decide_split_defaults_to_web(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("split_pending", tmp_path)
    split_id = client.get(_board_url(conversation_id)).json()["splits"][0]["split_id"]

    approved = client.post(
        f"/api/chat/operator/board-splits/{split_id}/decision",
        json={"conversation_id": conversation_id, "decision": "approve"},
        headers=OPERATOR_HEADERS,
    )

    assert approved.status_code == 200
    board = client.get(_board_url(conversation_id)).json()
    assert board["splits"][0]["decided_via"] == "web"


@pytest.mark.parametrize("decided_via", ["bogus", "plugin:", "PLUGIN:x", "web ", "plugin:a!b"])
def test_board_decide_split_invalid_decided_via(tmp_path: Path, decided_via: str) -> None:
    client, conversation_id, _ctx = _scenario("split_pending", tmp_path)
    split_id = client.get(_board_url(conversation_id)).json()["splits"][0]["split_id"]

    response = client.post(
        f"/api/chat/operator/board-splits/{split_id}/decision",
        json={
            "conversation_id": conversation_id,
            "decision": "approve",
            "decided_via": decided_via,
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "room_board_decided_via_invalid"
    assert client.get(_board_url(conversation_id)).json()["splits"][0]["status"] == "proposed"


def test_board_decide_split_fixture_provenance(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("split_approved_via_plugin", tmp_path)

    board = client.get(_board_url(conversation_id)).json()

    by_id = {split["split_id"]: split for split in board["splits"]}
    assert by_id and {split["status"] for split in by_id.values()} == {"approved", "rejected"}
    approved = next(split for split in by_id.values() if split["status"] == "approved")
    rejected = next(split for split in by_id.values() if split["status"] == "rejected")
    assert approved["decided_via"] == "plugin:claude-code"
    assert rejected["decided_via"] == "cli"


# ---------------------------------------------------------------------------
# performance
# ---------------------------------------------------------------------------


def test_board_summary_with_10000_activities_answers_in_50ms(tmp_path: Path) -> None:
    from tests.xmuse.room_fixtures import RoomTestStore

    db = tmp_path / "chat.db"
    conversation = RoomTestStore(db).create_conversation("perf room")
    with RoomDatabase(db).connect() as conn:
        start_seq = int(
            conn.execute(
                "select coalesce(max(seq), 0) from room_activities where conversation_id = ?",
                (conversation.id,),
            ).fetchone()[0]
        )
        rows = [
            (
                f"activity_perf_{index:05d}",
                conversation.id,
                start_seq + index + 1,
                "board.progress",
                "participant",
                "god:testsess:perf",
                None,
                "causation_perf",
                f"board_correlation_perf_{index:05d}",
                "room",
                json.dumps(
                    {
                        "type": "board",
                        "conversation_id": conversation.id,
                        "participant_ids": [],
                    }
                ),
                json.dumps(
                    {
                        "schema_version": "room_board_activity/v1",
                        "progress_id": f"progress_{index:05d}",
                        "module_id": "alpha",
                        "status": "working",
                        "summary": f"steady {index}",
                        "claims": [],
                        "content": "perf",
                    }
                ),
                0,
                "active",
                "2026-01-01T00:00:00.000000Z",
            )
            for index in range(10_000)
        ]
        conn.executemany(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, causal_depth,
                delivery_mode, created_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
    client = _client(tmp_path)
    url = _board_url(conversation.id) + "/summary"

    warmup = client.get(url)
    assert warmup.status_code == 200
    samples = []
    for _ in range(5):
        begin = time.perf_counter()
        response = client.get(url)
        samples.append((time.perf_counter() - begin) * 1000)
        assert response.status_code == 200

    assert statistics.median(samples) < 50, f"summary samples ms: {samples}"
