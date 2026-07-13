from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_mcp_contract import room_tool_schemas

TOOL = "chat_room_submit_outcome"
REQUIRED = {
    "conversation_id",
    "participant_id",
    "god_session_id",
    "observation_id",
    "lease_token",
    "client_request_id",
    "outcome_type",
}
FORBIDDEN = {
    "caller_identity",
    "author",
    "role",
    "max_causal_depth",
    "registry_path",
    "now",
    "delivery_mode",
    "scheduler",
}


def _room(tmp_path: Path):
    db = tmp_path / "chat.db"
    registry = tmp_path / "god_sessions.json"
    conversation_id = RoomTestStore(db).create_conversation("room").id
    participant = ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="observer",
        display_name="Observer",
        cli_kind="codex",
        model="gpt-5",
    )
    session = GodSessionRegistry(registry).create(
        participant.role,
        participant.display_name,
        "codex",
        "address",
        "inbox",
        conversation_id,
        participant.participant_id,
    )
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="observe this",
        client_request_id="human-1",
    )
    claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="worker",
    )
    return db, registry, conversation_id, participant, session, claim


def _arguments(conversation_id, participant, session, claim, **extra):
    return {
        "conversation_id": conversation_id,
        "participant_id": participant.participant_id,
        "god_session_id": session.god_session_id,
        "observation_id": claim["observation"]["observation_id"],
        "observation_batch_id": claim["batch"]["batch_id"],
        "lease_token": claim["observation"]["lease_token"],
        "client_request_id": "outcome-1",
        "outcome_type": "respond",
        **extra,
    }


def _counts(db: Path) -> dict[str, int]:
    with sqlite3.connect(db) as conn:
        tables = [
            "messages",
            "room_activities",
            "room_observations",
            "chat_request_log",
            "chat_frontend_events",
        ]
        return {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0] for table in tables
        }


def _chat_call(client: TestClient, arguments: dict, *, headers=None):
    response = client.post(
        "/mcp/room",
        json={
            "jsonrpc": "2.0",
            "id": "outcome",
            "method": "tools/call",
            "params": {"name": TOOL, "arguments": arguments},
        },
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_room_outcome_schema_is_exact_and_bounded():
    schema = room_tool_schemas()[0]
    input_schema = schema["inputSchema"]
    assert set(input_schema["required"]) == REQUIRED
    assert set(input_schema["properties"]) == REQUIRED | {
        "observation_batch_id",
        "reply_to_activity_id",
        "outcome_payload",
        "proposal_assessments",
        "memory_candidates",
    }
    assert input_schema["additionalProperties"] is False
    assert input_schema["properties"]["outcome_type"]["enum"] == [
        "respond",
        "handoff",
        "propose",
        "defer",
        "noop",
    ]
    payload = input_schema["properties"]["outcome_payload"]
    assert set(payload["properties"]) == {
        "content",
        "mentioned_participant_ids",
        "target_participant_ids",
        "proposal_type",
        "references",
        "execution_patch",
        "wake_condition",
    }
    assert payload["additionalProperties"] is False
    memory = input_schema["properties"]["memory_candidates"]
    assert memory["maxItems"] == 3
    assert memory["items"]["additionalProperties"] is False
    assert not FORBIDDEN & set(input_schema["properties"])


def test_room_endpoint_exposes_only_outcome_and_denies_other_writes(tmp_path: Path):
    db, _, conversation_id, participant, session, claim = _room(tmp_path)
    from xmuse.room_mcp_server import create_app

    client = TestClient(create_app(tmp_path))
    listed = client.post(
        "/mcp/room",
        json={"jsonrpc": "2.0", "id": "list", "method": "tools/list"},
    ).json()
    assert [item["name"] for item in listed["result"]["tools"]] == [TOOL]
    assert [item["name"] for item in room_tool_schemas()] == [TOOL]

    before = _counts(db)
    denied = client.post(
        "/mcp/room",
        json={
            "jsonrpc": "2.0",
            "id": "denied",
            "method": "tools/call",
            "params": {
                "name": "chat_post_message",
                "arguments": {
                    "conversation_id": conversation_id,
                    "participant_id": participant.participant_id,
                    "god_session_id": session.god_session_id,
                    "client_request_id": "forbidden-room-write",
                    "content": "must not be written",
                },
            },
        },
    ).json()
    assert "not exposed on this MCP endpoint" in str(denied["result"])
    assert _counts(db) == before

    accepted = client.post(
        "/mcp/room",
        json={
            "jsonrpc": "2.0",
            "id": "outcome",
            "method": "tools/call",
            "params": {
                "name": TOOL,
                "arguments": _arguments(
                    conversation_id,
                    participant,
                    session,
                    claim,
                    outcome_payload={"content": "durable room response"},
                ),
            },
        },
    ).json()
    assert accepted["result"]["isError"] is False


def test_direct_service_submit_is_durable_replayable_and_room_only(tmp_path: Path):
    db, registry, conversation_id, participant, session, claim = _room(tmp_path)
    service = RoomApplicationService(db, registry)
    args = _arguments(
        conversation_id,
        participant,
        session,
        claim,
        reply_to_activity_id=claim["activity"]["activity_id"],
        outcome_payload={"content": "answer"},
    )
    before = _counts(db)
    first = service.submit_participant_outcome(**args)
    after = _counts(db)
    replay = service.submit_participant_outcome(**args)
    assert first == replay
    assert first["produced_activity"]["actor_participant_id"] == participant.participant_id
    assert first["produced_message"]["content"] == "answer"
    assert first["produced_message"]["reply_to_message_id"] is not None
    assert after["messages"] == before["messages"] + 1
    assert after["room_activities"] == before["room_activities"] + 1
    assert after["chat_request_log"] == before["chat_request_log"] + 1
    assert after["chat_frontend_events"] == before["chat_frontend_events"] + 1
    assert _counts(db) == after


def test_wrong_or_unknown_session_rejects_without_writes(tmp_path: Path):
    db, registry, conversation_id, participant, session, claim = _room(tmp_path)
    service = RoomApplicationService(db, registry)
    before = _counts(db)
    for session_id in ("unknown", session.god_session_id + "-wrong"):
        with pytest.raises(RoomApplicationError):
            service.submit_participant_outcome(
                **_arguments(
                    conversation_id,
                    participant,
                    session,
                    claim,
                    god_session_id=session_id,
                ),
            )
        assert _counts(db) == before


def test_http_respond_and_invalid_authority_arguments(tmp_path: Path):
    db, registry, conversation_id, participant, session, claim = _room(tmp_path)
    from xmuse.room_mcp_server import create_app

    client = TestClient(create_app(tmp_path))
    result = _chat_call(
        client,
        _arguments(
            conversation_id,
            participant,
            session,
            claim,
            outcome_payload={"content": "http"},
        ),
    )
    assert result["isError"] is False
    assert (
        result["structuredContent"]["produced_activity"]["actor_participant_id"]
        == participant.participant_id
    )
    missing = _arguments(conversation_id, participant, session, claim)
    missing.pop("observation_id")
    missing_result = _chat_call(client, missing)
    assert missing_result["isError"] is True
    assert missing_result["structuredContent"]["error"]["code"] == "invalid_arguments"
    extra = _arguments(conversation_id, participant, session, claim, author="caller")
    extra_result = _chat_call(client, extra)
    assert extra_result["isError"] is True
    error = extra_result["structuredContent"]["error"]
    assert error["code"] == "invalid_arguments"
    assert _counts(db)["messages"] == 2
    extra["author"] = None
    extra["max_causal_depth"] = 1
    extra_result = _chat_call(client, extra)
    assert extra_result["isError"] is True
    error = extra_result["structuredContent"]["error"]
    assert error["code"] == "invalid_arguments"
    assert _counts(db)["messages"] == 2


def test_http_unknown_nested_outcome_authority_fields_reject_without_writes(tmp_path: Path):
    db, registry, conversation_id, participant, session, claim = _room(tmp_path)
    from xmuse.room_mcp_server import create_app

    before = _counts(db)
    result = _chat_call(
        TestClient(create_app(tmp_path)),
        _arguments(
            conversation_id,
            participant,
            session,
            claim,
            outcome_payload={
                "content": "rejected",
                "author": "caller",
                "role": "observer",
                "caller_identity": "fake",
                "max_causal_depth": 99,
                "budget": 1,
            },
        ),
    )
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "room_observation_payload_invalid"
    assert _counts(db) == before
    observation = RoomKernelStore(db).get_observation(claim["observation"]["observation_id"])
    assert observation["status"] == "claimed"
    assert observation["lease_token"] == claim["observation"]["lease_token"]


def test_http_execution_patch_contract_error_is_a_failed_tool_result(tmp_path: Path):
    db, _, conversation_id, participant, session, claim = _room(tmp_path)
    from xmuse.room_mcp_server import create_app

    path = "src/xmuse_core/example.py"
    before = _counts(db)
    result = _chat_call(
        TestClient(create_app(tmp_path)),
        _arguments(
            conversation_id,
            participant,
            session,
            claim,
            outcome_type="propose",
            outcome_payload={
                "proposal_type": "execution_patch",
                "content": "invalid exact patch",
                "references": [],
                "execution_patch": {
                    "schema_version": "room_execution_patch/v1",
                    "base_head": "a" * 40,
                    "summary": "Change the example",
                    "unified_diff": (
                        f"diff --git a/{path} b/{path}\n"
                        "index 1111111..2222222 100644\n"
                        f"--- a/{path}\n+++ b/{path}\n"
                        "@@ -1 +1 @@\n-old\n+new\n"
                    ),
                    "allowed_files": [path, "extra.py"],
                },
            },
        ),
    )

    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == (
        "room_execution_patch_allowed_files_mismatch"
    )
    assert _counts(db) == before


def test_http_noop_returns_null_materializations(tmp_path: Path):
    db, registry, conversation_id, participant, session, claim = _room(tmp_path)
    from xmuse.room_mcp_server import create_app

    result = _chat_call(
        TestClient(create_app(tmp_path)),
        _arguments(conversation_id, participant, session, claim, outcome_type="noop"),
    )
    durable = result["structuredContent"]
    assert durable["produced_activity"] is None
    assert durable["produced_message"] is None
    assert durable["produced_proposal"] is None


def test_adapter_is_thin_and_uses_room_application_only():
    adapter_source = Path("xmuse/room_mcp_server.py").read_text()
    assert "RoomApplicationService" in adapter_source
    forbidden = (
        "RoomKernelStore",
        "PeerChatScheduler",
        "ImmediateTurnRouter",
        "final_text",
        "platform_orchestration",
    )
    assert not any(token in adapter_source for token in forbidden)
