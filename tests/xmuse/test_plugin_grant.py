"""Plugin grant backend tests (``docs/contracts/plugin_grant_v1.md``, threats T1-T15).

Threat-to-test map (the ``p3`` threat-model rows are named by the contract):
T1 privilege confusion both directions; T2 cross-conversation confusion;
T3 split-decision rules and provenance; T4 clock rollback; T5 operator-token
rotation/absence; T6 scope confinement (only ``board.split.decide``);
T7 secrets never in logs or payloads; T8 indistinguishable 401s plus five
strikes; T9/T15 Origin and content-type refusal; T10 credential strength and
digest-only storage; T11 structured responses only; T12 provenance and
accounting; T13 one live grant per room and host; T14 pairing-channel
handling and no echo in errors; T15 global pairing limiter.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import logging
import os
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.xmuse.board_scenarios import build_scenario
from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.chat_api import create_app
from xmuse.chat_api_board import register_room_board_routes
from xmuse.chat_api_grants import register_plugin_grant_routes
from xmuse_core.chat import room_plugin_grants as grants_mod
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_board import RoomBoardStore
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_plugin_grants import PluginGrantStore

OPERATOR_TOKEN = "operator-secret"
OPERATOR_HEADERS = {"X-XMuse-Operator-Token": OPERATOR_TOKEN}
OTHER_TOKEN = "operator-rotated"

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "docs/contracts/schemas/plugin_grant.v1.json").read_text())
FIXTURE_DIR = ROOT / "docs/contracts/fixtures/plugin_grant_v1"

GRANT_KEYS = frozenset(
    {
        "grant_id",
        "conversation_id",
        "host",
        "scope",
        "status",
        "created_at",
        "activated_at",
        "expires_at",
        "revoked_at",
        "last_used_at",
        "use_count",
    }
)


def _grant_client(root: Path, *, token: str | None = OPERATOR_TOKEN) -> TestClient:
    app = FastAPI()
    register_room_board_routes(app, root=root, operator_token=token)
    register_plugin_grant_routes(app, root=root, operator_token=token)
    return TestClient(app)


def _room(tmp_path: Path) -> tuple[TestClient, str, dict[str, Any], dict[str, Any]]:
    ctx = build_scenario("split_pending", tmp_path)
    target = tmp_path / "chat.db"
    if Path(ctx["db"]) != target:
        shutil.copy(ctx["db"], target)
    client = _grant_client(tmp_path)
    board = client.get(f"/api/chat/conversations/{ctx['conversation_id']}/board").json()
    split = board["splits"][0]
    assert split["status"] == "proposed"
    return client, ctx["conversation_id"], split, ctx


def _issue(
    client: TestClient,
    conversation_id: str,
    *,
    host: str = "claude-code",
    scope: str = "board.split.decide",
    ttl: int | None = None,
    headers: dict[str, str] | None = OPERATOR_HEADERS,
) -> Any:
    body: dict[str, Any] = {
        "conversation_id": conversation_id,
        "host": host,
        "scope": scope,
    }
    if ttl is not None:
        body["ttl_seconds"] = ttl
    return client.post("/api/chat/operator/plugin-grants", json=body, headers=headers)


def _exchange(client: TestClient, code: str, host: str) -> Any:
    return client.post(
        "/api/chat/plugin/grants/exchange", json={"pairing_code": code, "host": host}
    )


def _activate(
    client: TestClient, conversation_id: str, *, host: str = "claude-code"
) -> tuple[dict[str, Any], str, str]:
    issued = _issue(client, conversation_id, host=host)
    assert issued.status_code == 201, issued.text
    code = issued.json()["pairing_code"]
    exchanged = _exchange(client, code, host)
    assert exchanged.status_code == 200, exchanged.text
    payload = exchanged.json()
    return payload["grant"], payload["secret"], code


def _decide(
    client: TestClient,
    split_id: str,
    *,
    secret: str,
    conversation_id: str,
    decision: str = "approve",
    digest: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Any:
    body: dict[str, Any] = {
        "conversation_id": conversation_id,
        "decision": decision,
        "expected_digest": digest or "",
    }
    if extra:
        body.update(extra)
    return client.post(
        f"/api/chat/plugin/board-splits/{split_id}/decision",
        json=body,
        headers={"Authorization": f"Bearer {secret}"},
    )


def _grant_row(db: Path, grant_id: str) -> dict[str, Any]:
    with RoomDatabase(db).connect(readonly=True) as conn:
        row = conn.execute("select * from plugin_grants where grant_id = ?", (grant_id,)).fetchone()
    assert row is not None
    return dict(row)


def _bad_secret(secret: str) -> str:
    tail = "A" if not secret.endswith("A") else "B"
    return secret[:-1] + tail


def _second_room_with_split(tmp_path: Path, conversation_id: str) -> str:
    """Propose a fresh pending split in ``conversation_id`` via a lead lease."""

    db = tmp_path / "chat.db"
    store = RoomBoardStore(db)
    with RoomDatabase(db).connect(readonly=True) as conn:
        rows = conn.execute(
            "select participant_id from participants where conversation_id = ? order by rowid",
            (conversation_id,),
        ).fetchall()
    if len(rows) < 2:
        participants = ParticipantStore(db)
        lead = participants.add(
            conversation_id=conversation_id,
            role="lead",
            display_name="Lead",
            cli_kind="codex",
            model="gpt-5",
        )
        owner = participants.add(
            conversation_id=conversation_id,
            role="owner",
            display_name="Owner",
            cli_kind="codex",
            model="gpt-5",
        )
        with RoomDatabase(db).connect() as conn:
            write_room_collaboration_policy_conn(
                conn,
                conversation_id=conversation_id,
                mode="broadcast",
                lead_participant_id=lead.participant_id,
                updated_at="2026-01-01T00:00:00.000000Z",
            )
            conn.commit()
        RoomKernelStore(db).post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content="kickoff",
            client_request_id=f"kickoff-{conversation_id}",
        )
        lead_id, owner_id = lead.participant_id, owner.participant_id
    else:
        lead_id, owner_id = str(rows[0]["participant_id"]), str(rows[1]["participant_id"])
    claimed = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=lead_id,
        lease_owner="host-lead-second",
        lease_ttl_s=300.0,
    )
    assert claimed is not None
    observation = claimed["observation"]
    proposed = store.propose_split(
        conversation_id=conversation_id,
        participant_id=lead_id,
        caller_identity=f"god:testsess:{lead_id}",
        observation_id=observation["observation_id"],
        lease_token=observation["lease_token"],
        client_request_id="propose-second",
        modules=[
            {
                "module_id": "gamma",
                "title": "Gamma module",
                "paths": ["src/gamma/**"],
                "provides": ["api.gamma"],
                "depends": [],
                "acceptance": ["gamma works"],
                "report_to": lead_id,
            }
        ],
        assignments={"gamma": owner_id},
        contracts=[
            {
                "contract_id": "api.gamma",
                "provider_module_id": "gamma",
                "kind": "api_schema",
                "content": '{"gamma": 1}',
                "rationale": "gamma surface",
            }
        ],
    )
    return str(proposed["split_id"])


# ---------------------------------------------------------------------------
# T1: privilege confusion, both directions
# ---------------------------------------------------------------------------


def test_t1_grant_bearer_rejected_on_operator_routes(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    _grant, secret, _code = _activate(client, conversation_id)
    bearer = {"Authorization": f"Bearer {secret}"}

    issue = client.post(
        "/api/chat/operator/plugin-grants",
        json={"conversation_id": conversation_id, "host": "x", "scope": "y"},
        headers=bearer,
    )
    assert issue.status_code == 401
    assert issue.json()["detail"]["code"] == "operator_auth_invalid"

    revoke = client.post(
        "/api/chat/operator/plugin-grants/grant_nope/revoke",
        json={"conversation_id": conversation_id},
        headers=bearer,
    )
    assert revoke.status_code == 401
    assert revoke.json()["detail"]["code"] == "operator_auth_invalid"

    decide = client.post(
        f"/api/chat/operator/board-splits/{split['split_id']}/decision",
        json={"conversation_id": conversation_id, "decision": "approve"},
        headers=bearer,
    )
    assert decide.status_code == 401
    assert decide.json()["detail"]["code"] == "operator_auth_invalid"


def test_t1_operator_header_never_authenticates_plugin_routes(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    _grant, _secret, code = _activate(client, conversation_id)

    exchange = client.post(
        "/api/chat/plugin/grants/exchange",
        json={"pairing_code": "WRONG-C0DE", "host": "claude-code"},
        headers=OPERATOR_HEADERS,
    )
    assert exchange.status_code == 401
    assert exchange.json()["detail"]["code"] == "plugin_pairing_invalid"

    decide = client.post(
        f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
        json={
            "conversation_id": conversation_id,
            "decision": "approve",
            "expected_digest": split["digest"],
        },
        headers=OPERATOR_HEADERS,
    )
    assert decide.status_code == 401
    assert decide.json()["detail"]["code"] == "plugin_grant_invalid"

    # The pairing code itself is untouched by the failed attempt above.
    assert _exchange(client, code, "claude-code").status_code == 401


# ---------------------------------------------------------------------------
# T2: cross-conversation confusion
# ---------------------------------------------------------------------------


def test_t2_cross_conversation_confusion(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    other = RoomTestStore(tmp_path / "chat.db").create_conversation("other room")
    grant, secret, _code = _activate(client, conversation_id)

    foreign = client.post(
        f"/api/chat/operator/plugin-grants/{grant['grant_id']}/revoke",
        json={"conversation_id": other.id},
        headers=OPERATOR_HEADERS,
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "plugin_grant_unknown"

    wrong_room = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=other.id,
        digest=split["digest"],
    )
    assert wrong_room.status_code == 401
    assert wrong_room.json()["detail"]["code"] == "plugin_grant_invalid"

    missing_split = _decide(
        client, "split_missing", secret=secret, conversation_id=conversation_id, digest="x"
    )
    assert missing_split.status_code == 404
    assert missing_split.json()["detail"]["code"] == "room_board_split_unknown"

    second_split = _second_room_with_split(tmp_path, other.id)
    cross = _decide(
        client,
        second_split,
        secret=secret,
        conversation_id=conversation_id,
        digest="sha256:" + "0" * 64,
    )
    assert cross.status_code == 404
    assert cross.json()["detail"]["code"] == "room_board_split_unknown"

    unknown_issue = _issue(client, "conv_missing", headers=OPERATOR_HEADERS)
    assert unknown_issue.status_code == 404
    assert unknown_issue.json()["detail"]["code"] == "room_conversation_unknown"

    unknown_list = client.get(
        "/api/chat/operator/plugin-grants",
        params={"conversation_id": "conv_missing"},
        headers=OPERATOR_HEADERS,
    )
    assert unknown_list.status_code == 404
    assert unknown_list.json()["detail"]["code"] == "room_conversation_unknown"


# ---------------------------------------------------------------------------
# T3: split-decision rules and provenance
# ---------------------------------------------------------------------------


def test_t3_decision_rules_and_provenance(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)

    refused_via = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
        extra={"decided_via": "web"},
    )
    assert refused_via.status_code == 422
    assert refused_via.json()["detail"]["code"] == "plugin_grant_request_invalid"

    refused_extra = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
        extra={"note": "hi"},
    )
    assert refused_extra.status_code == 422

    missing_digest = client.post(
        f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
        json={"conversation_id": conversation_id, "decision": "approve"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert missing_digest.status_code == 422
    assert missing_digest.json()["detail"]["code"] == "plugin_grant_request_invalid"

    mismatch = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest="sha256:" + "0" * 64,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "room_board_split_digest_mismatch"

    approved = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    board = client.get(f"/api/chat/conversations/{conversation_id}/board").json()
    decided = {item["split_id"]: item for item in board["splits"]}[split["split_id"]]
    assert decided["decided_via"] == "plugin:claude-code"
    assigned = [event for event in board["events"] if event["kind"] == "charter_assigned"]
    assert assigned and all(
        event["data"]["decided_via"] == "plugin:claude-code" for event in assigned
    )
    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        row = conn.execute(
            "select approved_by from room_board_splits where split_id = ?",
            (split["split_id"],),
        ).fetchone()
    assert row is not None and row["approved_by"] == f"plugin-grant:{grant['grant_id']}"

    replay = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["code"] == "room_board_split_decided"

    superseded_id = _second_room_with_split(tmp_path, conversation_id)
    superseded = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert superseded.status_code == 409
    assert superseded.json()["detail"]["code"] == "room_board_split_decided"

    pending = client.get(f"/api/chat/conversations/{conversation_id}/board").json()
    live = next(item for item in pending["splits"] if item["split_id"] == superseded_id)
    stale = _decide(
        client,
        superseded_id,
        secret=secret,
        conversation_id=conversation_id,
        digest="sha256:" + "0" * 64,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "room_board_split_digest_mismatch"
    assert live["status"] == "proposed"


def test_t3_superseded_split_answers_not_proposed(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)
    # A newer proposal supersedes the pending one; the old split is stale,
    # so the plugin treats the 409 as "can no longer be decided" (§7).
    _second_room_with_split(tmp_path, conversation_id)

    stale = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "room_board_split_not_proposed"


# ---------------------------------------------------------------------------
# T4: clock moved backwards
# ---------------------------------------------------------------------------


def test_t4_clock_rollback_invalidates_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)
    activated = datetime.fromisoformat(grant["activated_at"].replace("Z", "+00:00"))

    monkeypatch.setattr(grants_mod, "_utcnow", lambda: activated - timedelta(seconds=10))
    rolled = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert rolled.status_code == 401
    assert rolled.json()["detail"]["code"] == "plugin_grant_invalid"
    monkeypatch.undo()

    approved = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert approved.status_code == 200

    used = PluginGrantStore(tmp_path / "chat.db").list_grants(conversation_id)[0]
    last_used = datetime.fromisoformat(used["last_used_at"].replace("Z", "+00:00"))
    monkeypatch.setattr(grants_mod, "_utcnow", lambda: last_used - timedelta(seconds=10))
    stale_use = client.post(
        "/api/chat/plugin/grants/revoke",
        json={},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert stale_use.status_code == 401
    assert stale_use.json()["detail"]["code"] == "plugin_grant_invalid"


def test_t4_rotated_token_invalidates_grant(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    _grant, secret, _code = _activate(client, conversation_id)
    rotated = _grant_client(tmp_path, token=OTHER_TOKEN)

    decide = rotated.post(
        f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
        json={
            "conversation_id": conversation_id,
            "decision": "approve",
            "expected_digest": split["digest"],
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert decide.status_code == 401
    assert decide.json()["detail"]["code"] == "plugin_grant_invalid"


# ---------------------------------------------------------------------------
# T5: operator-token rotation and absence
# ---------------------------------------------------------------------------


def test_t5_token_rotation_and_absence(tmp_path: Path) -> None:
    client, conversation_id, split, ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)

    row = _grant_row(tmp_path / "chat.db", grant["grant_id"])
    expected = hmac.new(OPERATOR_TOKEN.encode(), b"plugin-grant/v1", hashlib.sha256).hexdigest()
    assert row["operator_token_fingerprint"] == expected
    assert row["operator_token_fingerprint"] != OPERATOR_TOKEN
    assert row["secret_digest"] != secret

    unconfigured = _grant_client(tmp_path, token=None)
    decide = unconfigured.post(
        f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
        json={
            "conversation_id": conversation_id,
            "decision": "approve",
            "expected_digest": split["digest"],
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert decide.status_code == 401
    assert decide.json()["detail"]["code"] == "plugin_grant_invalid"

    issue = unconfigured.post(
        "/api/chat/operator/plugin-grants",
        json={"conversation_id": conversation_id, "host": "h", "scope": "s"},
    )
    assert issue.status_code == 503


# ---------------------------------------------------------------------------
# T6: scope confinement
# ---------------------------------------------------------------------------


def test_t6_only_board_split_decide_scope(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)

    bad_scope = _issue(client, conversation_id, scope="board.split.approve")
    assert bad_scope.status_code == 422
    assert bad_scope.json()["detail"]["code"] == "plugin_grant_scope_invalid"

    grant, secret, _code = _activate(client, conversation_id)
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            "update plugin_grants set scope = ? where grant_id = ?",
            ("board.split.approve", grant["grant_id"]),
        )
    denied = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "plugin_grant_invalid"


# ---------------------------------------------------------------------------
# T7: never in logs or payloads
# ---------------------------------------------------------------------------


def test_t7_secrets_absent_from_logs_and_payloads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    with caplog.at_level(logging.DEBUG):
        issued = _issue(client, conversation_id)
        assert issued.status_code == 201
        code = issued.json()["pairing_code"]
        exchanged = _exchange(client, code, "claude-code")
        assert exchanged.status_code == 200
        secret = exchanged.json()["secret"]
        digest_value = _grant_row(tmp_path / "chat.db", exchanged.json()["grant"]["grant_id"])[
            "secret_digest"
        ]
        decided = _decide(
            client,
            split["split_id"],
            secret=secret,
            conversation_id=conversation_id,
            digest=split["digest"],
        )
        assert decided.status_code == 200
        listed = client.get(
            "/api/chat/operator/plugin-grants",
            params={"conversation_id": conversation_id},
            headers=OPERATOR_HEADERS,
        )
        assert listed.status_code == 200
        revoked = client.post(
            "/api/chat/plugin/grants/revoke",
            json={},
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert revoked.status_code == 200
    logs = caplog.text
    assert secret not in logs
    assert code not in logs
    assert str(digest_value) not in logs

    # The issue response shows the pairing code exactly once by design; it
    # must appear nowhere else.
    assert issued.text.count(code) == 1
    bodies = [
        listed.text,
        decided.text,
        revoked.text,
    ]
    for body in bodies:
        assert secret not in body
        assert code not in body
        assert str(digest_value) not in body
    assert code not in exchanged.text
    assert exchanged.json()["secret"] == secret


# ---------------------------------------------------------------------------
# T8: indistinguishable failures, five strikes
# ---------------------------------------------------------------------------


def test_t8_indistinguishable_401_and_five_strikes(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)

    failures = [
        _decide(
            client,
            split["split_id"],
            secret="xpg_grant_" + "0" * 32 + "_" + "A" * 43,
            conversation_id=conversation_id,
            digest=split["digest"],
        ),
        client.post(
            f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
            json={
                "conversation_id": conversation_id,
                "decision": "approve",
                "expected_digest": split["digest"],
            },
        ),
        client.post(
            f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
            json={
                "conversation_id": conversation_id,
                "decision": "approve",
                "expected_digest": split["digest"],
            },
            headers={"Authorization": "Bearer not-a-secret"},
        ),
    ]
    for response in failures:
        assert response.status_code == 401
        assert response.json() == {
            "detail": {
                "code": "plugin_grant_invalid",
                "message": "Plugin grant is missing or invalid",
                "details": {},
                "field_errors": {},
                "retryable": False,
                "correlation_id": None,
            }
        }

    for _ in range(5):
        bad = _decide(
            client,
            split["split_id"],
            secret=_bad_secret(secret),
            conversation_id=conversation_id,
            digest=split["digest"],
        )
        assert bad.status_code == 401
        assert bad.json()["detail"]["code"] == "plugin_grant_invalid"
    assert _grant_row(tmp_path / "chat.db", grant["grant_id"])["revoked_at"] is not None

    revoked_use = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert revoked_use.status_code == 401
    assert revoked_use.json()["detail"]["code"] == "plugin_grant_invalid"

    expired_grant, expired_secret, _c = _activate(client, conversation_id, host="x-code")
    with RoomDatabase(tmp_path / "chat.db").connect() as conn:
        conn.execute(
            "update plugin_grants set expires_at = ? where grant_id = ?",
            ("2020-01-01T00:00:00.000000Z", expired_grant["grant_id"]),
        )
    expired = _decide(
        client,
        split["split_id"],
        secret=expired_secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert expired.status_code == 401
    assert expired.json() == failures[0].json()


# ---------------------------------------------------------------------------
# T9/T15: Origin and content-type refusal before anything else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_request",
    [
        "exchange",
        "decide",
        "self_revoke",
    ],
)
def test_t9_t15_origin_and_content_type_refused_first(tmp_path: Path, make_request: str) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    _grant, secret, code = _activate(client, conversation_id)

    if make_request == "exchange":
        valid = {"pairing_code": code, "host": "claude-code"}
        url = "/api/chat/plugin/grants/exchange"
        bearer: dict[str, str] = {}
    elif make_request == "decide":
        valid = {
            "conversation_id": conversation_id,
            "decision": "approve",
            "expected_digest": split["digest"],
        }
        url = f"/api/chat/plugin/board-splits/{split['split_id']}/decision"
        bearer = {"Authorization": f"Bearer {secret}"}
    else:
        valid = {}
        url = "/api/chat/plugin/grants/revoke"
        bearer = {"Authorization": f"Bearer {secret}"}

    origin = client.post(url, json=valid, headers={**bearer, "Origin": "http://app"})
    assert origin.status_code == 403
    assert origin.json()["detail"]["code"] == "plugin_origin_forbidden"

    plain = client.post(
        url,
        content=json.dumps(valid),
        headers={**bearer, "Content-Type": "text/plain", "Origin": "http://app"},
    )
    assert plain.status_code == 403

    no_json = client.post(
        url, content=json.dumps(valid), headers={**bearer, "Content-Type": "text/plain"}
    )
    assert no_json.status_code == 415
    assert no_json.json()["detail"]["code"] == "plugin_content_type_invalid"

    # A wrong grant plus a forbidden transport still reports the transport.
    wrong = client.post(
        url,
        json={"nope": True},
        headers={"Authorization": "Bearer wrong", "Origin": "http://app"},
    )
    assert wrong.status_code == 403


# ---------------------------------------------------------------------------
# T10: credential strength, digest-only storage
# ---------------------------------------------------------------------------


def test_t10_secret_strength_and_digest_only_storage(tmp_path: Path) -> None:
    import base64

    client, conversation_id, _split, _ctx = _room(tmp_path)
    _grant, secret, code = _activate(client, conversation_id)

    assert re.fullmatch(r"xpg_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{43}", secret)
    raw = secret[-43:]
    assert len(base64.urlsafe_b64decode(raw + "=")) == 32
    assert re.fullmatch(
        r"[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}", code
    )

    row = _grant_row(tmp_path / "chat.db", _grant["grant_id"])
    assert row["secret_digest"] == hashlib.sha256(secret.encode()).hexdigest()
    assert row["pairing_code_digest"] == hashlib.sha256(code.encode()).hexdigest()

    with RoomDatabase(tmp_path / "chat.db").connect(readonly=True) as conn:
        dump = "\n".join(
            str(value)
            for grant_row in conn.execute("select * from plugin_grants").fetchall()
            for value in dict(grant_row).values()
        )
        failures = conn.execute("select * from plugin_grant_exchange_failures").fetchall()
    assert secret not in dump
    assert code not in dump
    assert failures == []


# ---------------------------------------------------------------------------
# T11: structured responses only
# ---------------------------------------------------------------------------


def test_t11_responses_carry_only_structured_fields(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    issued = _issue(client, conversation_id)
    assert set(issued.json()) == {
        "schema_version",
        "grant",
        "pairing_code",
        "pairing_expires_at",
    }
    assert set(issued.json()["grant"]) == GRANT_KEYS
    assert issued.json()["schema_version"] == "plugin_grant_issue/v1"

    listed = client.get(
        "/api/chat/operator/plugin-grants",
        params={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert set(listed.json()) == {"schema_version", "conversation_id", "grants"}
    assert all(set(item) == GRANT_KEYS for item in listed.json()["grants"])

    exchanged = _exchange(client, issued.json()["pairing_code"], "claude-code")
    assert set(exchanged.json()) == {"schema_version", "grant", "secret"}
    assert set(exchanged.json()["grant"]) == GRANT_KEYS

    decided = _decide(
        client,
        split["split_id"],
        secret=exchanged.json()["secret"],
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert set(decided.json()) == {
        "split_id",
        "status",
        "modules",
        "contracts",
        "activity_ids",
    }
    body_text = decided.text
    assert "Ignore previous instructions" not in body_text


# ---------------------------------------------------------------------------
# T12: provenance and accounting
# ---------------------------------------------------------------------------


def test_t12_provenance_and_accounting(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)

    before = PluginGrantStore(tmp_path / "chat.db").list_grants(conversation_id)
    assert before[0]["use_count"] == 0
    assert before[0]["last_used_at"] is None

    # A failed bearer never counts as use.
    denied = _decide(
        client,
        split["split_id"],
        secret=_bad_secret(secret),
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert denied.status_code == 401
    assert PluginGrantStore(tmp_path / "chat.db").list_grants(conversation_id)[0]["use_count"] == 0

    decided = _decide(
        client,
        split["split_id"],
        secret=secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert decided.status_code == 200

    after = PluginGrantStore(tmp_path / "chat.db").list_grants(conversation_id)
    assert after[0]["use_count"] == 1
    assert after[0]["last_used_at"] is not None
    listed = client.get(
        "/api/chat/operator/plugin-grants",
        params={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    ).json()["grants"][0]
    assert listed["use_count"] == 1
    assert listed["last_used_at"] is not None
    assert listed["status"] == "active"


# ---------------------------------------------------------------------------
# T13: one live grant per room and host
# ---------------------------------------------------------------------------


def test_t13_second_issue_revokes_first(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    first_grant, first_secret, first_code = _activate(client, conversation_id)
    _other_grant, _other_secret, _other_code = _activate(client, conversation_id, host="opencode")

    second = _issue(client, conversation_id)
    assert second.status_code == 201
    assert second.json()["grant"]["grant_id"] != first_grant["grant_id"]

    stale_secret = _decide(
        client,
        split["split_id"],
        secret=first_secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert stale_secret.status_code == 401
    assert _exchange(client, first_code, "claude-code").status_code == 401

    row = _grant_row(tmp_path / "chat.db", first_grant["grant_id"])
    assert row["revoked_at"] is not None

    other_ok = _decide(
        client,
        split["split_id"],
        secret=_other_secret,
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert other_ok.status_code == 200


# ---------------------------------------------------------------------------
# T14: pairing channel handling, no echo in errors
# ---------------------------------------------------------------------------


def test_t14_pairing_failures_indistinguishable_and_consuming(tmp_path: Path) -> None:
    client, conversation_id, _split, _ctx = _room(tmp_path)
    issued = _issue(client, conversation_id)
    code = issued.json()["pairing_code"]

    wrong_host = _exchange(client, code, "opencode")
    assert wrong_host.status_code == 401
    assert wrong_host.json()["detail"]["code"] == "plugin_pairing_invalid"

    consumed = _exchange(client, code, "claude-code")
    assert consumed.status_code == 401
    assert consumed.json() == wrong_host.json()

    again = _exchange(client, code, "claude-code")
    assert again.status_code == 401
    assert again.json() == wrong_host.json()

    missing = client.post(
        "/api/chat/plugin/grants/exchange",
        json={"pairing_code": "ZZZZ-2222", "host": "claude-code"},
    )
    assert missing.status_code == 401
    assert missing.json() == wrong_host.json()


def test_t14_error_messages_never_echo_body_or_headers(tmp_path: Path) -> None:
    client, conversation_id, split, _ctx = _room(tmp_path)
    _grant, secret, _code = _activate(client, conversation_id)
    canary = "CANARY-echo-probe-9371"

    probes = [
        client.post(
            "/api/chat/plugin/grants/exchange",
            json={"pairing_code": canary, "host": "claude-code"},
            headers={"Authorization": f"Bearer {canary}"},
        ),
        client.post(
            f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
            json={
                "conversation_id": canary,
                "decision": "approve",
                "expected_digest": split["digest"],
            },
            headers={"Authorization": f"Bearer {canary}"},
        ),
        client.post(
            "/api/chat/plugin/grants/revoke",
            json={},
            headers={"Authorization": f"Bearer {canary}"},
        ),
        client.post(
            f"/api/chat/plugin/board-splits/{split['split_id']}/decision",
            json={"conversation_id": conversation_id, "decision": canary},
            headers={"Authorization": f"Bearer {secret}"},
        ),
    ]
    for response in probes:
        assert response.status_code in {401, 404, 422}
        assert canary not in response.text


# ---------------------------------------------------------------------------
# T15: global pairing limiter
# ---------------------------------------------------------------------------


def test_t15_global_pairing_limiter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, conversation_id, _split, _ctx = _room(tmp_path)
    issued = _issue(client, conversation_id)
    code = issued.json()["pairing_code"]
    real_now = grants_mod._utcnow()

    for _ in range(10):
        attempt = _exchange(client, "ZZZZ-2222", "claude-code")
        assert attempt.status_code == 401

    locked = _exchange(client, "ZZZZ-2222", "claude-code")
    assert locked.status_code == 429
    assert locked.json()["detail"]["code"] == "plugin_pairing_locked"
    assert int(locked.headers["retry-after"]) >= 1

    correct_while_locked = _exchange(client, code, "claude-code")
    assert correct_while_locked.status_code == 429

    monkeypatch.setattr(grants_mod, "_utcnow", lambda: real_now + timedelta(seconds=61))
    recovered = _exchange(client, code, "claude-code")
    assert recovered.status_code == 200, recovered.text


# ---------------------------------------------------------------------------
# Operator route validation, idempotency, list order
# ---------------------------------------------------------------------------


def test_operator_grant_validation_and_idempotent_revoke(tmp_path: Path) -> None:
    client, conversation_id, _split, _ctx = _room(tmp_path)

    assert _issue(client, conversation_id, host="Bad Host!").status_code == 422
    bad_host = _issue(client, conversation_id, host="Bad Host!")
    assert bad_host.json()["detail"]["code"] == "plugin_grant_host_invalid"

    bad_scope = _issue(client, conversation_id, scope="memory.read")
    assert bad_scope.json()["detail"]["code"] == "plugin_grant_scope_invalid"

    bad_ttl = _issue(client, conversation_id, ttl=30)
    assert bad_ttl.status_code == 422
    assert bad_ttl.json()["detail"]["code"] == "plugin_grant_request_invalid"

    extra_key = client.post(
        "/api/chat/operator/plugin-grants",
        json={
            "conversation_id": conversation_id,
            "host": "claude-code",
            "scope": "board.split.decide",
            "ttl_seconds": 600,
            "decided_via": "web",
        },
        headers=OPERATOR_HEADERS,
    )
    assert extra_key.status_code == 422

    missing_token = client.post(
        "/api/chat/operator/plugin-grants",
        json={"conversation_id": conversation_id, "host": "h", "scope": "s"},
    )
    assert missing_token.status_code == 401

    pending = _issue(client, conversation_id, ttl=60)
    assert pending.status_code == 201
    payload = pending.json()
    assert payload["grant"]["status"] == "pending"
    assert payload["grant"]["expires_at"] == payload["pairing_expires_at"]

    for host in ("host-a", "host-b", "host-c"):
        assert _issue(client, conversation_id, host=host).status_code == 201
    listed = client.get(
        "/api/chat/operator/plugin-grants",
        params={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert listed.status_code == 200
    grants = listed.json()["grants"]
    assert len(grants) <= 50
    created = [item["created_at"] for item in grants]
    assert created == sorted(created, reverse=True)

    unknown_revoke = client.post(
        "/api/chat/operator/plugin-grants/grant_missing/revoke",
        json={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert unknown_revoke.status_code == 404
    assert unknown_revoke.json()["detail"]["code"] == "plugin_grant_unknown"

    grant_id = payload["grant"]["grant_id"]
    first = client.post(
        f"/api/chat/operator/plugin-grants/{grant_id}/revoke",
        json={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["grant"]["status"] == "revoked"
    second = client.post(
        f"/api/chat/operator/plugin-grants/{grant_id}/revoke",
        json={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert second.status_code == 200
    assert second.json()["grant"]["status"] == "revoked"

    bad_body = client.post(
        f"/api/chat/operator/plugin-grants/{grant_id}/revoke",
        json={"conversation_id": conversation_id, "extra": 1},
        headers=OPERATOR_HEADERS,
    )
    assert bad_body.status_code == 422

    self_revoke = client.post(
        "/api/chat/plugin/grants/revoke",
        json={"unexpected": True},
        headers={"Authorization": "Bearer x"},
    )
    assert self_revoke.status_code == 401 or self_revoke.status_code == 422


def test_plugin_self_revoke_round_trip(tmp_path: Path) -> None:
    client, conversation_id, _split, _ctx = _room(tmp_path)
    grant, secret, _code = _activate(client, conversation_id)

    revoked = client.post(
        "/api/chat/plugin/grants/revoke",
        json={},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["grant"]["status"] == "revoked"
    assert set(revoked.json()) == {"schema_version", "grant"}

    again = client.post(
        "/api/chat/plugin/grants/revoke",
        json={},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert again.status_code == 401
    assert again.json()["detail"]["code"] == "plugin_grant_invalid"
    assert _grant_row(tmp_path / "chat.db", grant["grant_id"])["revoked_at"] is not None


# ---------------------------------------------------------------------------
# Wiring through the real app (foundation exemption, Host guard)
# ---------------------------------------------------------------------------


def test_plugin_routes_wired_in_create_app(tmp_path: Path) -> None:
    app = create_app(tmp_path, auth_token=OPERATOR_TOKEN)
    source = build_scenario("split_pending", tmp_path / "source")
    shutil.copy(Path(source["db"]), tmp_path / "chat.db")
    conversation_id = source["conversation_id"]
    client = TestClient(app)

    blocked = client.post(
        "/api/chat/operator/plugin-grants",
        json={"conversation_id": conversation_id, "host": "h", "scope": "s"},
    )
    assert blocked.status_code == 401

    issued = client.post(
        "/api/chat/operator/plugin-grants",
        json={
            "conversation_id": conversation_id,
            "host": "claude-code",
            "scope": "board.split.decide",
        },
        headers=OPERATOR_HEADERS,
    )
    assert issued.status_code == 201

    # No operator token: the plugin exchange passes the write-auth guard.
    exchanged = client.post(
        "/api/chat/plugin/grants/exchange",
        json={"pairing_code": issued.json()["pairing_code"], "host": "claude-code"},
    )
    assert exchanged.status_code == 200

    rebound = client.post(
        "/api/chat/plugin/grants/exchange",
        json={"pairing_code": "ZZZZ-2222", "host": "claude-code"},
        headers={"Host": "evil.example:8201"},
    )
    assert rebound.status_code == 400
    assert rebound.json()["detail"]["code"] == "room_host_invalid"


# ---------------------------------------------------------------------------
# Golden fixtures (contract §9 + task: deterministic example responses)
# ---------------------------------------------------------------------------


def _fixture_app(tmp_path: Path) -> tuple[TestClient, str, dict[str, Any]]:
    return _room(tmp_path)


def test_plugin_grant_golden_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(grants_mod, "_utcnow", lambda: fixed)
    board_ids = itertools.count(10**6)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(board_ids)))
    counter = {"next": 0}

    def fake_grant_id() -> str:
        counter["next"] += 1
        return f"grant_fixture{counter['next']:026d}"

    codes = ["ABCD-EFGH", "JKMP-NQRS", "TVWX-YZ23"]

    def fake_code() -> str:
        return codes[counter["next"] % len(codes)]

    def fake_secret(grant_id: str) -> str:
        return f"xpg_{grant_id}_" + "C" * 43

    monkeypatch.setattr(grants_mod, "_new_grant_id", fake_grant_id)
    monkeypatch.setattr(grants_mod, "_new_pairing_code", fake_code)
    monkeypatch.setattr(grants_mod, "_new_secret", fake_secret)

    client, conversation_id, split, _ctx = _fixture_app(tmp_path)
    responses: dict[str, Any] = {}

    issued = _issue(client, conversation_id)
    assert issued.status_code == 201
    responses["issue"] = issued.json()

    listed = client.get(
        "/api/chat/operator/plugin-grants",
        params={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert listed.status_code == 200
    responses["list"] = listed.json()

    exchanged = _exchange(client, responses["issue"]["pairing_code"], "claude-code")
    assert exchanged.status_code == 200
    responses["exchange"] = exchanged.json()

    decided = _decide(
        client,
        split["split_id"],
        secret=responses["exchange"]["secret"],
        conversation_id=conversation_id,
        digest=split["digest"],
    )
    assert decided.status_code == 200
    responses["decision"] = decided.json()

    self_revoked = client.post(
        "/api/chat/plugin/grants/revoke",
        json={},
        headers={"Authorization": f"Bearer {responses['exchange']['secret']}"},
    )
    assert self_revoked.status_code == 200
    responses["plugin_revoke"] = self_revoked.json()

    second = _issue(client, conversation_id, host="opencode")
    assert second.status_code == 201
    operator_revoked = client.post(
        f"/api/chat/operator/plugin-grants/{second.json()['grant']['grant_id']}/revoke",
        json={"conversation_id": conversation_id},
        headers=OPERATOR_HEADERS,
    )
    assert operator_revoked.status_code == 200
    responses["operator_revoke"] = operator_revoked.json()

    jsonschema.validate(responses["issue"], SCHEMA)
    jsonschema.validate(responses["list"], SCHEMA)
    jsonschema.validate(responses["exchange"], SCHEMA)
    grant_schema = {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/grant"}
    for name in ("plugin_revoke", "operator_revoke"):
        jsonschema.validate(responses[name]["grant"], grant_schema)
        assert set(responses[name]) == {"schema_version", "grant"}
    assert responses["decision"]["status"] == "approved"

    update = os.environ.get("UPDATE_PLUGIN_GRANT_FIXTURES") == "1"
    if update:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, payload in responses.items():
            (FIXTURE_DIR / f"{name}.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    for name, payload in responses.items():
        path = FIXTURE_DIR / f"{name}.json"
        assert path.is_file(), f"run with UPDATE_PLUGIN_GRANT_FIXTURES=1 to generate {name}"
        assert json.loads(path.read_text(encoding="utf-8")) == payload
