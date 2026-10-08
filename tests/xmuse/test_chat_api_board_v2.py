"""HTTP tests for the Room board read model v2 routes (contract §7/§8).

TestClient style follows ``test_chat_api_agent_streams.py``: the board routes
are registered on a bare app and scenarios come from the P0a builders in
``tests/xmuse/board_scenarios.py``.
"""

from __future__ import annotations

import json
import re
import shutil
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
    "integration_conflicted",
    "integration_gate_failed",
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
    if path.endswith(".patch.text") or path.endswith("patch.text"):
        return
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


def test_board_contract_detail_cross_conversation_404(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("contract_revised_stale_dependent", tmp_path)
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            """insert into conversations (id, title, created_at)
               values ('conv_other_123', 'Other', '2026-01-01T00:00:00Z')"""
        )
        conn.commit()

    other_conv = client.get(_board_url("conv_other_123") + "/contracts/api.backend")
    assert other_conv.status_code == 404
    assert other_conv.json()["detail"]["code"] == "room_board_contract_unknown"


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
        f"{base}/board/integrations/boardintegration_unknown",
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
        json={**body, "expected_digest": split["digest"], "decided_via": "web"},
        headers=OPERATOR_HEADERS,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    decided = client.get(_board_url(conversation_id)).json()
    assert decided["splits"][0]["status"] == "approved"
    assert decided["splits"][0]["decided_via"] == "web"
    assert decided["splits"][0]["actions"]["decide"]["available"] is False
    assigned = [event for event in decided["events"] if event["kind"] == "charter_assigned"]
    assert assigned and all(event["data"]["decided_via"] == "web" for event in assigned)
    assert assigned and all(event["data"]["grant_id"] is None for event in assigned)

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
    assert events[0]["data"]["grant_id"] is None


def test_board_decide_split_reused_contract_id_is_409_not_500(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("split_pending", tmp_path)
    split = client.get(_board_url(conversation_id)).json()["splits"][0]
    db = tmp_path / "chat.db"
    with RoomDatabase(db).connect() as conn:
        split_json = json.loads(
            conn.execute(
                "select split_json from room_board_splits where split_id = ?",
                (split["split_id"],),
            ).fetchone()[0]
        )
        taken = split_json["contracts"][0]["contract_id"]
        author = next(iter(split_json["assignments"].values()))
        # Another module published the same contract id after the proposal.
        conn.execute(
            """insert into room_board_contracts
               (conversation_id, contract_id, version, provider_module_id, kind, content,
                digest, author_participant_id, rationale, activity_id, created_at)
               values (?, ?, 1, 'elsewhere', 'text', 'x', 'sha256:x', ?, 'r', null,
                       '2026-01-01T00:00:00.000000Z')""",
            (conversation_id, taken, author),
        )
        conn.commit()

    response = client.post(
        f"/api/chat/operator/board-splits/{split['split_id']}/decision",
        json={
            "conversation_id": conversation_id,
            "decision": "approve",
            "expected_digest": split["digest"],
            "decided_via": "web",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "room_board_contract_exists"
    assert client.get(_board_url(conversation_id)).json()["splits"][0]["status"] == "proposed"


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


@pytest.mark.parametrize(
    "decided_via",
    ["bogus", "plugin:", "PLUGIN:x", "web ", "plugin:a!b", "plugin:claude-code"],
)
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
    assigned = [event for event in board["events"] if event["kind"] == "charter_assigned"]
    assert assigned and all(
        event["data"]["decided_via"] == "plugin:claude-code" for event in assigned
    )
    assert assigned and all(
        event["data"]["grant_id"] == "grant_split_approved_via_plugin" for event in assigned
    )
    refused = [event for event in board["events"] if event["kind"] == "split_rejected"]
    assert len(refused) == 1
    assert refused[0]["data"]["decided_via"] == "cli"
    assert refused[0]["data"]["grant_id"] is None


def test_board_decide_split_cross_conversation_404(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("split_pending", tmp_path)
    split_id = client.get(_board_url(conversation_id)).json()["splits"][0]["split_id"]
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            """insert into conversations (id, title, created_at)
               values ('conv_other_123', 'Other', '2026-01-01T00:00:00Z')"""
        )
        conn.commit()

    other_conv = client.post(
        f"/api/chat/operator/board-splits/{split_id}/decision",
        json={"conversation_id": "conv_other_123", "decision": "approve"},
        headers=OPERATOR_HEADERS,
    )
    assert other_conv.status_code == 404
    assert other_conv.json()["detail"]["code"] == "room_board_split_unknown"

    unknown = client.post(
        "/api/chat/operator/board-splits/split_unknown/decision",
        json={"conversation_id": conversation_id, "decision": "approve"},
        headers=OPERATOR_HEADERS,
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "room_board_split_unknown"

    # Nothing was decided by the failed attempts.
    assert client.get(_board_url(conversation_id)).json()["splits"][0]["status"] == "proposed"


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

    # Best of five: shared CI runners are noisy, a real regression slows every run.
    assert min(samples) < 50, f"summary samples ms: {samples}"


# ---------------------------------------------------------------------------
# review detail, verification detail, material, and decision routes
# ---------------------------------------------------------------------------


def test_board_reviews_detail_and_cache_control(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("review_endorsed", tmp_path)
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select review_id from room_board_reviews where conversation_id = ? limit 1",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    review_id = str(row["review_id"])

    url = f"/api/chat/conversations/{conversation_id}/board/reviews/{review_id}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    jsonschema.validate(body, _load_schema("room_board_review.v1.json"))
    _walk_privacy(body, "$")
    assert body["review"]["status"] == "endorsed"
    assert body["summary"]["untrusted"] is True

    # Cross-conversation 404
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            """insert into conversations (id, title, created_at)
               values ('conv_other_123', 'Other', '2026-01-01T00:00:00Z')"""
        )
        conn.commit()
    other_conv = client.get(f"/api/chat/conversations/conv_other_123/board/reviews/{review_id}")
    assert other_conv.status_code == 404
    assert other_conv.json()["detail"]["code"] == "room_board_review_unknown"

    unknown_conv = client.get(f"/api/chat/conversations/conv_nonexistent/board/reviews/{review_id}")
    assert unknown_conv.status_code == 404
    assert unknown_conv.json()["detail"]["code"] == "room_conversation_unknown"

    # Unknown review in conversation
    unknown = client.get(
        f"/api/chat/conversations/{conversation_id}/board/reviews/boardreview_unknown"
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "room_board_review_unknown"


def test_board_verifications_detail_and_cache_control(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("verification_failed_rework", tmp_path)
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            """select verification_id from room_board_verifications
               where conversation_id = ? limit 1""",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    verification_id = str(row["verification_id"])

    url = f"/api/chat/conversations/{conversation_id}/board/verifications/{verification_id}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    jsonschema.validate(body, _load_schema("room_board_verification.v1.json"))
    _walk_privacy(body, "$")
    assert body["status"] == "failed"
    tail = body["gates"][0]["output_tail"]
    assert tail["untrusted"] is True
    assert "<host-path>" in tail["text"]

    # Cross-conversation 404
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            """insert into conversations (id, title, created_at)
               values ('conv_other_123', 'Other', '2026-01-01T00:00:00Z')"""
        )
        conn.commit()
    other_conv = client.get(
        f"/api/chat/conversations/conv_other_123/board/verifications/{verification_id}"
    )
    assert other_conv.status_code == 404
    assert other_conv.json()["detail"]["code"] == "room_board_verification_unknown"

    unknown_conv = client.get(
        f"/api/chat/conversations/conv_nonexistent/board/verifications/{verification_id}"
    )
    assert unknown_conv.status_code == 404
    assert unknown_conv.json()["detail"]["code"] == "room_conversation_unknown"

    # Unknown verification in conversation
    unknown = client.get(
        f"/api/chat/conversations/{conversation_id}/board/verifications/boardverify_unknown"
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "room_board_verification_unknown"


def _latest_integration_id(root: Path, conversation_id: str) -> str:
    with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select integration_id from room_board_integrations where conversation_id = ? "
            "order by created_at desc, rowid desc limit 1",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    return str(row["integration_id"])


def test_board_integrations_detail_and_cache_control(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("integration_conflicted", tmp_path)
    integration_id = _latest_integration_id(tmp_path, conversation_id)

    url = f"/api/chat/conversations/{conversation_id}/board/integrations/{integration_id}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    jsonschema.validate(body, _load_schema("room_board_integration.v1.json"))
    _walk_privacy(body, "$")
    assert body["schema_version"] == "room_board_integration/v1"
    assert body["status"] == "integrated"
    assert body["green_head_commit"] is not None
    assert [item["order"] for item in body["items"]] == [1, 2, 3]
    by_module = {item["module_id"]: item for item in body["items"]}
    assert by_module["mb"]["conflicts"] == [
        {"path": "docs/shared.txt", "attributed_module_ids": ["ma", "mb"]}
    ]
    assert by_module["mb"]["conflicts_total"] == 1
    assert by_module["mc"]["status"] == "waiting"

    # Cross-conversation 404 (never reveals whether the id exists elsewhere).
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            """insert into conversations (id, title, created_at)
               values ('conv_other_123', 'Other', '2026-01-01T00:00:00Z')"""
        )
        conn.commit()
    other_conv = client.get(
        f"/api/chat/conversations/conv_other_123/board/integrations/{integration_id}"
    )
    assert other_conv.status_code == 404
    assert other_conv.json()["detail"]["code"] == "room_board_integration_unknown"

    unknown_conv = client.get(
        "/api/chat/conversations/conv_nonexistent/board/integrations/boardintegration_unknown"
    )
    assert unknown_conv.status_code == 404
    assert unknown_conv.json()["detail"]["code"] == "room_conversation_unknown"

    # Unknown integration in conversation.
    unknown = client.get(
        f"/api/chat/conversations/{conversation_id}/board/integrations/boardintegration_unknown"
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "room_board_integration_unknown"


def test_board_integrations_gate_tails(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("integration_gate_failed", tmp_path)
    integration_id = _latest_integration_id(tmp_path, conversation_id)

    body = client.get(
        f"/api/chat/conversations/{conversation_id}/board/integrations/{integration_id}"
    ).json()
    assert body["status"] == "gate_failed"
    assert isinstance(body["result_commit"], str) and len(body["result_commit"]) == 40
    assert len(body["gates"]) == 1
    tail = body["gates"][0]["output_tail"]
    assert tail["untrusted"] is True
    assert "AssertionError" in tail["text"]
    assert len(tail["text"]) <= 2000


def test_board_integrations_pending_detail(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("integration_pending_running", tmp_path)
    integration_id = _latest_integration_id(tmp_path, conversation_id)

    body = client.get(
        f"/api/chat/conversations/{conversation_id}/board/integrations/{integration_id}"
    ).json()
    assert body["status"] == "pending"
    assert body["finished_at"] is None
    assert body["gates"] == []
    assert all(item["status"] == "not_applied" for item in body["items"])


def test_board_integrations_route_is_read_only(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("integration_dependency_upgrade", tmp_path)
    integration_id = _latest_integration_id(tmp_path, conversation_id)

    def snapshot() -> dict[str, Any]:
        with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
            return {
                "board_seq": int(
                    conn.execute(
                        "select coalesce(max(seq), 0) from room_activities "
                        "where conversation_id = ? and activity_type like 'board.%'",
                        (conversation_id,),
                    ).fetchone()[0]
                ),
                "jobs": [
                    dict(row)
                    for row in conn.execute("select * from room_board_integrations").fetchall()
                ],
                "items": [
                    dict(row)
                    for row in conn.execute("select * from room_board_integration_items").fetchall()
                ],
                "activities": conn.execute(
                    "select count(*) from room_activities where conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0],
            }

    before = snapshot()
    response = client.get(
        f"/api/chat/conversations/{conversation_id}/board/integrations/{integration_id}"
    )
    assert response.status_code == 200
    assert snapshot() == before


def test_board_reviews_material_route_and_exclusion(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("review_operator_pending", tmp_path)
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            """select review_id from room_board_reviews
               where conversation_id = ? and reviewer_kind = 'operator'
                 and status = 'pending' limit 1""",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    review_id = str(row["review_id"])

    url = f"/api/chat/operator/board-reviews/{review_id}/material"

    # Operator token required
    no_auth = client.get(url, params={"conversation_id": conversation_id})
    assert no_auth.status_code == 401
    bad_auth = client.get(
        url,
        params={"conversation_id": conversation_id},
        headers={"X-XMuse-Operator-Token": "wrong"},
    )
    assert bad_auth.status_code == 401

    # Missing conversation_id query param
    no_conv = client.get(url, headers=OPERATOR_HEADERS)
    assert no_conv.status_code == 422

    # Cross-conversation / unknown review
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            """insert into conversations (id, title, created_at)
               values ('conv_other_123', 'Other', '2026-01-01T00:00:00Z')"""
        )
        conn.commit()
    cross_conv = client.get(
        url, params={"conversation_id": "conv_other_123"}, headers=OPERATOR_HEADERS
    )
    assert cross_conv.status_code == 404
    assert cross_conv.json()["detail"]["code"] == "room_board_review_unknown"

    unknown_rev = client.get(
        "/api/chat/operator/board-reviews/boardreview_unknown/material",
        params={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert unknown_rev.status_code == 404
    assert unknown_rev.json()["detail"]["code"] == "room_board_review_unknown"

    # Success
    response = client.get(
        url, params={"conversation_id": conversation_id}, headers=OPERATOR_HEADERS
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    jsonschema.validate(body, _load_schema("room_board_review_material.v1.json"))
    _walk_privacy(body, "$")

    # Excludes stacked patch (alpha) and only shows reviewed module (beta)
    assert "src/beta/b.py" in body["patch"]["text"]
    assert "src/alpha/a.py" not in body["patch"]["text"]

    # Shows markers and hidden char count
    assert "<U+202E>" in body["patch"]["text"]
    assert "<U+001B>" in body["patch"]["text"]
    assert body["patch"]["hidden_char_count"] == 3

    # Review where reviewer_kind != operator returns 409 room_board_review_not_operator
    p_client, p_conv, _p_ctx = _scenario("review_participant_pending", tmp_path / "part")
    with RoomDatabase(tmp_path / "part" / "chat.db").connect(readonly=True) as conn:
        p_row = conn.execute(
            "select review_id from room_board_reviews where conversation_id = ? limit 1",
            (p_conv,),
        ).fetchone()
    assert p_row is not None
    p_rev_id = str(p_row["review_id"])
    not_op = p_client.get(
        f"/api/chat/operator/board-reviews/{p_rev_id}/material",
        params={"conversation_id": p_conv},
        headers=OPERATOR_HEADERS,
    )
    assert not_op.status_code == 409
    assert not_op.json()["detail"]["code"] == "room_board_review_not_operator"


REVIEW_SCENARIOS = [
    "review_participant_pending",
    "review_operator_pending",
    "review_endorsed",
    "review_objected",
    "review_superseded",
    "review_escalated",
]


@pytest.mark.parametrize("scenario_name", REVIEW_SCENARIOS)
def test_board_review_route_privacy(tmp_path: Path, scenario_name: str) -> None:
    client, conversation_id, _ctx = _scenario(scenario_name, tmp_path)
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        rows = conn.execute(
            "select review_id from room_board_reviews where conversation_id = ?",
            (conversation_id,),
        ).fetchall()
    assert rows
    for row in rows:
        rev_id = str(row["review_id"])
        url = f"/api/chat/conversations/{conversation_id}/board/reviews/{rev_id}"
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        body = response.json()
        jsonschema.validate(body, _load_schema("room_board_review.v1.json"))
        _walk_privacy(body, "$")


def test_board_reviews_decision_check_order_end_to_end(tmp_path: Path) -> None:
    client, conversation_id, _ctx = _scenario("review_operator_pending", tmp_path)
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            """select review_id, verification_id from room_board_reviews
               where conversation_id = ? and reviewer_kind = 'operator'
                 and status = 'pending' limit 1""",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    review_id = str(row["review_id"])

    store = RoomBoardStore(tmp_path / "chat.db")
    material = store.review_material(conversation_id, review_id)
    expected_digest = material["digest"]

    url = f"/api/chat/operator/board-reviews/{review_id}/decision"

    valid_payload = {
        "conversation_id": conversation_id,
        "expected_digest": expected_digest,
        "verdict": "object",
        "summary": "blocking issue",
        "findings": [{"severity": "blocker", "path": "src/beta/b.py", "text": "bad"}],
    }

    # Auth check
    no_auth = client.post(url, json=valid_payload)
    assert no_auth.status_code == 401

    # Check 1: Body > 64 KiB -> 413 room_board_review_request_too_large
    huge_data = json.dumps({**valid_payload, "summary": "x" * 70000}).encode()
    r1 = client.post(
        url, content=huge_data, headers={"Content-Type": "application/json", **OPERATOR_HEADERS}
    )
    assert r1.status_code == 413
    assert r1.json()["detail"]["code"] == "room_board_review_request_too_large"

    # Check 2: Invalid JSON -> 422 room_board_review_request_invalid
    r2 = client.post(
        url, content=b"{not json", headers={"Content-Type": "application/json", **OPERATOR_HEADERS}
    )
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "room_board_review_request_invalid"

    # Check 3: Body not object -> 422 room_board_review_request_invalid
    r3 = client.post(url, json=[1, 2, 3], headers=OPERATOR_HEADERS)
    assert r3.status_code == 422
    assert r3.json()["detail"]["code"] == "room_board_review_request_invalid"

    # Check 4: Unknown keys -> 422 room_board_review_request_invalid
    r4 = client.post(url, json={**valid_payload, "extra": "forbidden"}, headers=OPERATOR_HEADERS)
    assert r4.status_code == 422
    assert r4.json()["detail"]["code"] == "room_board_review_request_invalid"

    # Check 5: Missing required keys -> 422 room_board_review_request_invalid
    no_sum = dict(valid_payload)
    del no_sum["summary"]
    r5 = client.post(url, json=no_sum, headers=OPERATOR_HEADERS)
    assert r5.status_code == 422
    assert r5.json()["detail"]["code"] == "room_board_review_request_invalid"

    no_digest = dict(valid_payload)
    del no_digest["expected_digest"]
    r5b = client.post(url, json=no_digest, headers=OPERATOR_HEADERS)
    assert r5b.status_code == 422
    assert r5b.json()["detail"]["code"] == "room_board_review_request_invalid"

    # Check 6: Bad verdict -> 422 room_board_review_request_invalid
    r6 = client.post(url, json={**valid_payload, "verdict": "pass"}, headers=OPERATOR_HEADERS)
    assert r6.status_code == 422
    assert r6.json()["detail"]["code"] == "room_board_review_request_invalid"

    # Check 7: Bad summary -> 422 room_board_review_summary_invalid
    r7_empty = client.post(url, json={**valid_payload, "summary": "   "}, headers=OPERATOR_HEADERS)
    assert r7_empty.status_code == 422
    assert r7_empty.json()["detail"]["code"] == "room_board_review_summary_invalid"

    r7_long = client.post(
        url, json={**valid_payload, "summary": "x" * 4001}, headers=OPERATOR_HEADERS
    )
    assert r7_long.status_code == 422
    assert r7_long.json()["detail"]["code"] == "room_board_review_summary_invalid"

    # Check 8: Findings > 32 -> 422 room_board_review_findings_invalid
    too_many = [{"severity": "minor", "path": None, "text": f"issue {i}"} for i in range(33)]
    r8 = client.post(url, json={**valid_payload, "findings": too_many}, headers=OPERATOR_HEADERS)
    assert r8.status_code == 422
    assert r8.json()["detail"]["code"] == "room_board_review_findings_invalid"

    # Check 9: Finding invalid path / severity / text -> 422 room_board_review_findings_invalid
    r9_bidi = client.post(
        url,
        json={
            **valid_payload,
            "findings": [{"severity": "blocker", "path": "src/\u202etest.py", "text": "bad"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert r9_bidi.status_code == 422
    assert r9_bidi.json()["detail"]["code"] == "room_board_review_findings_invalid"

    r9_sev = client.post(
        url,
        json={
            **valid_payload,
            "findings": [{"severity": "critical", "path": "src/a.py", "text": "bad"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert r9_sev.status_code == 422
    assert r9_sev.json()["detail"]["code"] == "room_board_review_findings_invalid"

    # Check 10: Object verdict without blocker or major -> 422 room_board_review_findings_invalid
    r10 = client.post(
        url,
        json={
            **valid_payload,
            "verdict": "object",
            "findings": [{"severity": "minor", "path": "src/a.py", "text": "minor only"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert r10.status_code == 422
    assert r10.json()["detail"]["code"] == "room_board_review_findings_invalid"

    # Check 11: decided_via not web -> 422 room_board_decided_via_invalid
    r11_cli = client.post(
        url, json={**valid_payload, "decided_via": "cli"}, headers=OPERATOR_HEADERS
    )
    assert r11_cli.status_code == 422
    assert r11_cli.json()["detail"]["code"] == "room_board_decided_via_invalid"

    r11_plugin = client.post(
        url, json={**valid_payload, "decided_via": "plugin:claude-code"}, headers=OPERATOR_HEADERS
    )
    assert r11_plugin.status_code == 422
    assert r11_plugin.json()["detail"]["code"] == "room_board_decided_via_invalid"

    # Check 12: Review unknown or of another conversation -> 404 room_board_review_unknown
    r12_other = client.post(
        url,
        json={**valid_payload, "conversation_id": "conv_other_123"},
        headers=OPERATOR_HEADERS,
    )
    assert r12_other.status_code == 404
    assert r12_other.json()["detail"]["code"] == "room_board_review_unknown"

    r12_unknown = client.post(
        "/api/chat/operator/board-reviews/boardreview_unknown/decision",
        json=valid_payload,
        headers=OPERATOR_HEADERS,
    )
    assert r12_unknown.status_code == 404
    assert r12_unknown.json()["detail"]["code"] == "room_board_review_unknown"

    # Check 13: Review not pending with reviewer_kind == operator
    # -> 409 room_board_review_not_pending
    p_client, p_conv, _ = _scenario("review_participant_pending", tmp_path / "part2")
    with RoomDatabase(tmp_path / "part2" / "chat.db").connect(readonly=True) as conn:
        p_row = conn.execute(
            "select review_id from room_board_reviews where conversation_id = ? limit 1",
            (p_conv,),
        ).fetchone()
    assert p_row is not None
    p_rev_id = str(p_row["review_id"])
    r13 = p_client.post(
        f"/api/chat/operator/board-reviews/{p_rev_id}/decision",
        json={**valid_payload, "conversation_id": p_conv},
        headers=OPERATOR_HEADERS,
    )
    assert r13.status_code == 409
    assert r13.json()["detail"]["code"] == "room_board_review_not_pending"

    # Check 14: Digest mismatch -> 409 room_board_review_digest_mismatch
    r14 = client.post(
        url,
        json={**valid_payload, "expected_digest": "sha256:" + "0" * 64},
        headers=OPERATOR_HEADERS,
    )
    assert r14.status_code == 409
    assert r14.json()["detail"]["code"] == "room_board_review_digest_mismatch"

    # Check 15: Material incomplete refuses endorse, allows object
    # -> 409 room_board_review_material_incomplete
    # Expand stored patch so marked text exceeds MAX_REVIEW_MATERIAL_PATCH_BYTES (262144 bytes)
    # Each "\x1b[31m" becomes "<U+001B>[31m" (14 bytes replacing 5 bytes, growing by 9 bytes)
    huge_patch = (
        "--- a/src/beta/b.py\n+++ b/src/beta/b.py\n@@ -1 +1 @@\n" + "+\x1b[31mred\x1b[0m\n" * 20000
    )
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            "update room_board_verifications set patch_text = ? where verification_id = ?",
            (huge_patch, str(row["verification_id"])),
        )
        conn.commit()
    huge_material = store.review_material(conversation_id, review_id)
    assert huge_material["patch"]["truncated"] is True
    huge_digest = huge_material["digest"]

    # Endorse must be refused
    r15_endorse = client.post(
        url,
        json={
            "conversation_id": conversation_id,
            "expected_digest": huge_digest,
            "verdict": "endorse",
            "summary": "ok",
            "findings": [],
        },
        headers=OPERATOR_HEADERS,
    )
    assert r15_endorse.status_code == 409
    assert r15_endorse.json()["detail"]["code"] == "room_board_review_material_incomplete"

    # But object remains allowed on incomplete material
    r15_object = client.post(
        url,
        json={
            "conversation_id": conversation_id,
            "expected_digest": huge_digest,
            "verdict": "object",
            "summary": "objecting even on truncated",
            "findings": [{"severity": "blocker", "path": "src/beta/b.py", "text": "bad"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert r15_object.status_code == 200
    assert r15_object.json()["status"] == "objected"
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        decided_row = conn.execute(
            "select status, decided_via from room_board_reviews where review_id = ?",
            (review_id,),
        ).fetchone()
        assert decided_row is not None
        assert decided_row["status"] == "objected"
        assert decided_row["decided_via"] == "web"
