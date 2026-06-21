from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "mcp_server.py"


def load_mcp_module():
    spec = importlib.util.spec_from_file_location("xmuse_mcp_server", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def mcp_call(client: TestClient, name: str, arguments: dict | None = None) -> dict:
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": f"call-{name}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    result = payload["result"]
    assert result["isError"] is False
    return result["structuredContent"]


def mcp_chat_call(client: TestClient, name: str, arguments: dict | None = None) -> dict:
    response = client.post(
        "/mcp/chat",
        json={
            "jsonrpc": "2.0",
            "id": f"call-{name}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "error" not in payload, payload
    result = payload["result"]
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert "error" not in structured, structured
    return structured


def test_sse_endpoint_and_tools_list(tmp_path: Path) -> None:
    server = load_mcp_module()

    client = TestClient(server.create_app(xmuse_root=tmp_path / "xmuse"))

    sse = client.get("/sse")
    assert sse.status_code == 200
    assert sse.headers["content-type"].startswith("text/event-stream")
    assert "event: endpoint" in sse.text
    assert "/messages?session_id=" in sse.text

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
    )

    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert {
        "list_lanes",
        "enqueue_lane",
        "get_status",
        "abort_lane",
        "get_error_knowledge",
        "get_logs",
        "get_tool_inventory",
        "get_lane",
        "get_gate_report",
        "get_diff",
        "query_knowledge",
        "read_lane_contract",
        "read_blueprint_contract",
        "read_feature_plan_contract",
        "read_review_contract",
        "read_health_contract",
        "read_graph_set_contract",
        "read_graph_set_summary",
        "read_evidence_refs",
        "read_review_verdict",
        "read_takeover_context",
        "read_run_health",
        "read_provider_inventory",
        "update_lane_status",
    }.issubset(names)
    assert {"chat_post_message", "chat_read_inbox", "chat_emit_proposal"}.issubset(names)


def test_peer_chat_mcp_endpoint_exposes_writeback_and_explicit_handoff_tools(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()

    client = TestClient(server.create_app(xmuse_root=tmp_path / "xmuse"))

    response = client.post(
        "/mcp/chat",
        json={"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
    )

    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {
        "chat_create_collaboration_request",
        "chat_emit_proposal",
        "chat_evaluate_dispatch_gate",
        "chat_inspect_conversation",
        "chat_mention",
        "chat_post_message",
        "chat_raise_collaboration_blocker",
        "chat_read_inbox",
        "chat_record_collaboration_response",
        "chat_resolve_collaboration_blocker",
    }
    assert "reply_to_inbox_item_id" in tools["chat_post_message"]["inputSchema"]["required"]
    assert "target_address" in tools["chat_mention"]["inputSchema"]["required"]
    assert "lanes" in tools["chat_emit_proposal"]["inputSchema"]["required"]
    assert (
        "reply_to_inbox_item_id"
        in tools["chat_emit_proposal"]["inputSchema"]["properties"]
    )
    lane_item_properties = tools["chat_emit_proposal"]["inputSchema"]["properties"]["lanes"][
        "items"
    ]["properties"]
    assert lane_item_properties["review_runtime"] == {"type": "string"}
    assert "run_id" in tools["chat_record_collaboration_response"]["inputSchema"]["required"]
    response_tool_description = tools["chat_record_collaboration_response"]["description"]
    assert '"status":"executable"' in response_tool_description
    assert '"evidence_refs":["<ref>"]' in response_tool_description
    assert "verdict=feasible" in response_tool_description


def test_chat_emit_proposal_can_complete_current_peer_inbox_item(tmp_path: Path) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))
    created = mcp_call(mcp_client, "chat_create_conversation", {"title": "Proposal reply"})
    conversation_id = created["conversation"]["id"]
    execute = next(item for item in created["participants"] if item["role"] == "execute")
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=execute["participant_id"],
    )
    assert session is not None
    chat = ChatStore(xmuse_root / "chat.db")
    human = chat.add_message(conversation_id, "human", "human", "@execute propose")
    inbox = ChatInboxStore(xmuse_root / "chat.db")
    item = inbox.create_item(
        conversation_id=conversation_id,
        target_participant_id=execute["participant_id"],
        target_role="execute",
        target_address="@execute",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=human.id,
        item_type="mention",
        payload={"content": human.content},
    )

    result = mcp_chat_call(
        mcp_client,
        "chat_emit_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": execute["participant_id"],
            "god_session_id": session.god_session_id,
            "client_request_id": "proposal-reply",
            "summary": "Bounded execution proposal",
            "lanes": [
                {
                    "feature_id": "bounded-execution-proposal",
                    "prompt": "Implement the bounded execution proposal.",
                    "depends_on": [],
                    "capabilities": ["code", "test"],
                }
            ],
            "references": [],
            "reply_to_inbox_item_id": item.id,
        },
    )

    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == result["message"]["id"]
    stages = PeerTurnLatencyTraceStore(xmuse_root / "chat.db").list_mcp_tool_stages(
        conversation_id,
        item.id,
    )
    assert "chat_emit_proposal" in stages
    assert registry.get(session.god_session_id).status == "running"


def test_chat_emit_proposal_without_reply_id_closes_single_claimed_inbox_item(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))
    created = mcp_call(mcp_client, "chat_create_conversation", {"title": "Claimed proposal"})
    conversation_id = created["conversation"]["id"]
    execute = next(item for item in created["participants"] if item["role"] == "execute")
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=execute["participant_id"],
    )
    assert session is not None
    chat = ChatStore(xmuse_root / "chat.db")
    human = chat.add_message(conversation_id, "human", "human", "@execute fresh proposal")
    inbox = ChatInboxStore(xmuse_root / "chat.db")
    item = inbox.create_item(
        conversation_id=conversation_id,
        target_participant_id=execute["participant_id"],
        target_role="execute",
        target_address="@execute",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=human.id,
        item_type="mention",
        payload={"content": human.content},
    )
    claimed = inbox.claim_next(owner="scheduler-test", item_id=item.id)
    assert claimed is not None
    assert claimed.status == "claimed"

    result = mcp_chat_call(
        mcp_client,
        "chat_emit_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": execute["participant_id"],
            "god_session_id": session.god_session_id,
            "client_request_id": "proposal-claimed-reply",
            "summary": "Claimed inbox proposal",
            "lanes": [
                {
                    "feature_id": "claimed-inbox-proposal",
                    "prompt": "Implement the claimed inbox proposal.",
                    "depends_on": [],
                    "capabilities": ["code", "test"],
                }
            ],
            "references": [],
        },
    )

    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == result["message"]["id"]
    stages = PeerTurnLatencyTraceStore(xmuse_root / "chat.db").list_mcp_tool_stages(
        conversation_id,
        item.id,
    )
    assert "chat_emit_proposal" in stages
    assert registry.get(session.god_session_id).status == "running"


def test_sse_chat_mention_without_reply_id_closes_single_claimed_inbox_item(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))
    created = mcp_call(mcp_client, "chat_create_conversation", {"title": "SSE handoff"})
    conversation_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    architect = participants["architect"]
    execute = participants["execute"]
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=architect["participant_id"],
    )
    assert session is not None
    chat = ChatStore(xmuse_root / "chat.db")
    human = chat.add_message(conversation_id, "human", "human", "@architect hand off")
    inbox = ChatInboxStore(xmuse_root / "chat.db")
    item = inbox.create_item(
        conversation_id=conversation_id,
        target_participant_id=architect["participant_id"],
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=human.id,
        item_type="mention",
        payload={"content": human.content},
    )
    claimed = inbox.claim_next(owner="scheduler-test", item_id=item.id)
    assert claimed is not None
    assert claimed.status == "claimed"

    response = mcp_client.post(
        "/sse",
        json={
            "jsonrpc": "2.0",
            "id": "sse-chat-mention",
            "method": "tools/call",
            "params": {
                "name": "chat_mention",
                "arguments": {
                    "conversation_id": conversation_id,
                    "participant_id": architect["participant_id"],
                    "god_session_id": session.god_session_id,
                    "client_request_id": "handoff-without-reply-id",
                    "target_address": "@execute",
                    "content": "Please record the execute feasibility verdict.",
                },
            },
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    payload = result["structuredContent"]
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == payload["message"]["id"]
    assert payload["inbox_items"][0]["target_participant_id"] == execute["participant_id"]
    stages = PeerTurnLatencyTraceStore(xmuse_root / "chat.db").list_mcp_tool_stages(
        conversation_id,
        item.id,
    )
    assert "chat_mention" in stages
    assert registry.get(session.god_session_id).status == "running"


def test_peer_chat_mcp_structured_execution_proposal_approval_enqueues_dispatch(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))

    created = mcp_call(mcp_client, "chat_create_conversation", {"title": "Execution closure"})
    conversation_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    architect_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["architect"]["participant_id"],
    )
    execute_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["execute"]["participant_id"],
    )
    assert architect_session is not None
    assert execute_session is not None

    run = mcp_chat_call(
        mcp_client,
        "chat_create_collaboration_request",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "collab-execution-closure",
            "goal": "Implement a production-ready TUI command palette slice.",
            "targets": ["execute"],
            "callback_target": "architect",
            "question": "Confirm executable scope and produce a lane graph proposal.",
            "context_refs": ["message:latest"],
            "idempotency_key": "execution-closure",
            "timeout_s": 480,
        },
    )["run"]
    run_id = run["run_id"]

    response = mcp_chat_call(
        mcp_client,
        "chat_record_collaboration_response",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["execute"]["participant_id"],
            "god_session_id": execute_session.god_session_id,
            "run_id": run_id,
            "content": json.dumps(
                {
                    "type": "execute_feasibility_verdict",
                    "status": "executable",
                    "summary": "The lane has bounded files and a focused verification gate.",
                    "evidence_refs": ["message:latest", "contract:tui-command-palette"],
                }
            ),
            "status": "received",
        },
    )["run"]
    assert response["status"] == "done"

    proposal = mcp_chat_call(
        mcp_client,
        "chat_emit_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["execute"]["participant_id"],
            "god_session_id": execute_session.god_session_id,
            "client_request_id": "proposal-execution-closure",
            "summary": "TUI command palette production slice",
            "lanes": [
                {
                    "feature_id": "tui-command-palette-production-slice",
                    "prompt": "Implement the approved TUI command palette slice.",
                    "depends_on": [],
                    "capabilities": ["code", "test"],
                }
            ],
            "references": [f"collaboration:{run_id}"],
        },
    )["proposal"]

    from xmuse.chat_api import create_app as create_chat_app
    from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore

    approved = TestClient(create_chat_app(xmuse_root)).post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve execution closure proposal",
        },
    )

    assert approved.status_code == 200, approved.text
    entries = ChatDispatchQueueStore(xmuse_root / "chat.db").list_entries(conversation_id)
    assert len(entries) == 1
    assert entries[0].status == "queued"
    assert entries[0].proposal_id == proposal["id"]
    assert entries[0].collaboration_run_id == run_id


def test_chat_create_collaboration_request_enqueues_normalized_target_inbox(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))

    created = mcp_call(
        mcp_client,
        "chat_create_conversation",
        {"title": "Collaboration target delivery"},
    )
    conversation_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    architect_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["architect"]["participant_id"],
    )
    execute_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["execute"]["participant_id"],
    )
    assert architect_session is not None
    assert execute_session is not None

    result = mcp_chat_call(
        mcp_client,
        "chat_create_collaboration_request",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "collab-target-delivery",
            "goal": "Confirm bounded execution scope.",
            "targets": ["execute", "@execute"],
            "callback_target": "@architect",
            "question": "Record an execute_feasibility_verdict for this lane.",
            "context_refs": ["message:intake"],
            "idempotency_key": "collab-target-delivery",
            "timeout_s": 480,
        },
    )
    run = result["run"]

    assert run["targets"] == ["@execute"]
    assert run["callback_target"] == "@architect"
    assert result["message"]["envelope_type"] == "collaboration_request"
    assert [item["target_address"] for item in result["inbox_items"]] == ["@execute"]
    assert result["inbox_items"][0]["item_type"] == "collaboration_request"
    assert result["inbox_items"][0]["target_participant_id"] == (
        participants["execute"]["participant_id"]
    )

    inbox = ChatInboxStore(xmuse_root / "chat.db").list_for_participant(
        conversation_id=conversation_id,
        participant_id=participants["execute"]["participant_id"],
    )
    assert len(inbox) == 1
    assert inbox[0].payload["collaboration_run_id"] == run["run_id"]
    assert "chat_record_collaboration_response" in inbox[0].payload["content"]

    repeated = mcp_chat_call(
        mcp_client,
        "chat_create_collaboration_request",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "collab-target-delivery",
            "goal": "Confirm bounded execution scope.",
            "targets": ["execute", "@execute"],
            "callback_target": "@architect",
            "question": "Record an execute_feasibility_verdict for this lane.",
            "context_refs": ["message:intake"],
            "idempotency_key": "collab-target-delivery",
            "timeout_s": 480,
        },
    )
    assert repeated["run"]["run_id"] == run["run_id"]
    assert len(repeated["inbox_items"]) == 1
    assert len(
        ChatInboxStore(xmuse_root / "chat.db").list_for_participant(
            conversation_id=conversation_id,
            participant_id=participants["execute"]["participant_id"],
        )
    ) == 1

    response = mcp_chat_call(
        mcp_client,
        "chat_record_collaboration_response",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["execute"]["participant_id"],
            "god_session_id": execute_session.god_session_id,
            "run_id": run["run_id"],
            "content": json.dumps(
                {
                    "type": "execute_feasibility_verdict",
                    "status": "executable",
                    "summary": "The lane is bounded and has a focused gate.",
                    "evidence_refs": ["message:intake"],
                }
            ),
            "status": "received",
        },
    )["run"]

    assert response["status"] == "done"
    assert response["responses"][0]["target"] == "@execute"

    closed_inbox = ChatInboxStore(xmuse_root / "chat.db").get(inbox[0].id)
    assert closed_inbox.status == "read"
    stages = PeerTurnLatencyTraceStore(xmuse_root / "chat.db").list_mcp_tool_stages(
        conversation_id,
        inbox[0].id,
    )
    assert "chat_record_collaboration_response" in stages


def test_chat_emit_proposal_deduplicates_collaboration_lane_graph_feature(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))

    created = mcp_call(
        mcp_client,
        "chat_create_conversation",
        {"title": "Duplicate proposal guard"},
    )
    conversation_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    architect_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["architect"]["participant_id"],
    )
    execute_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["execute"]["participant_id"],
    )
    assert architect_session is not None
    assert execute_session is not None

    run = mcp_chat_call(
        mcp_client,
        "chat_create_collaboration_request",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "collab-dedup",
            "goal": "Confirm one bounded docs lane.",
            "targets": ["execute"],
            "callback_target": "architect",
            "question": "Return an execute feasibility verdict.",
            "context_refs": ["message:latest"],
            "idempotency_key": "collab-dedup",
            "timeout_s": 480,
        },
    )["run"]
    run_id = run["run_id"]

    response = mcp_chat_call(
        mcp_client,
        "chat_record_collaboration_response",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["execute"]["participant_id"],
            "god_session_id": execute_session.god_session_id,
            "run_id": run_id,
            "content": json.dumps(
                {
                    "type": "execute_feasibility_verdict",
                    "status": "executable",
                    "summary": "One bounded docs lane is executable.",
                    "evidence_refs": ["message:latest"],
                }
            ),
            "status": "received",
        },
    )["run"]
    assert response["status"] == "done"

    callback_items = ChatInboxStore(xmuse_root / "chat.db").list_for_participant(
        conversation_id=conversation_id,
        participant_id=participants["architect"]["participant_id"],
    )
    callback_item = next(
        item for item in callback_items if item.item_type == "collaboration_callback"
    )
    assert callback_item.status == "unread"

    first = mcp_chat_call(
        mcp_client,
        "chat_emit_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "proposal-dedup-first",
            "summary": "Docs sentinel",
            "lanes": [
                {
                    "feature_id": "docs-sentinel",
                    "prompt": "Create the docs sentinel.",
                    "depends_on": [],
                    "capabilities": ["docs"],
                }
            ],
            "references": [f"collaboration:{run_id}"],
        },
    )
    second = mcp_chat_call(
        mcp_client,
        "chat_emit_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "proposal-dedup-second",
            "summary": "Docs sentinel duplicate",
            "lanes": [
                {
                    "feature_id": "docs-sentinel",
                    "prompt": "Create the docs sentinel again.",
                    "depends_on": [],
                    "capabilities": ["docs"],
                }
            ],
            "references": [f"collaboration:{run_id}"],
        },
    )

    assert second["proposal"]["id"] == first["proposal"]["id"]
    assert second["message"]["id"] == first["message"]["id"]
    assert second["semantic_deduplication"]["reason"] == (
        "collaboration_lane_graph_feature_overlap"
    )
    assert second["semantic_deduplication"]["feature_ids"] == ["docs-sentinel"]

    closed_callback = ChatInboxStore(xmuse_root / "chat.db").get(callback_item.id)
    assert closed_callback.status == "read"
    assert closed_callback.responded_message_id == first["message"]["id"]
    stages = PeerTurnLatencyTraceStore(xmuse_root / "chat.db").list_mcp_tool_stages(
        conversation_id,
        callback_item.id,
    )
    assert "chat_emit_proposal" in stages

    chat = ChatStore(xmuse_root / "chat.db")
    proposals = chat.list_proposals(conversation_id)
    assert [proposal.id for proposal in proposals] == [first["proposal"]["id"]]
    proposal_messages = [
        message
        for message in chat.list_messages(conversation_id)
        if message.envelope_type == "proposal"
    ]
    assert [message.id for message in proposal_messages] == [first["message"]["id"]]


def test_mcp_health_reports_chat_writeback_endpoint_and_state_files(tmp_path: Path) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "xmuse-mcp",
        "server": "xmuse-mcp",
        "version": server.SERVER_VERSION,
        "endpoints": {
            "mcp": "/mcp",
            "mcp_chat": "/mcp/chat",
            "sse": "/sse",
        },
        "state_files": {
            "chat_db": {
                "path": str(xmuse_root / "chat.db"),
                "exists": False,
            },
            "god_sessions": {
                "path": str(xmuse_root / "god_sessions.json"),
                "exists": False,
            },
        },
    }


def test_peer_chat_mcp_endpoint_rejects_post_without_reply_to_inbox(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()

    client = TestClient(server.create_app(xmuse_root=tmp_path / "xmuse"))

    response = client.post(
        "/mcp/chat",
        json={
            "jsonrpc": "2.0",
            "id": "call-chat-post",
            "method": "tools/call",
            "params": {
                "name": "chat_post_message",
                "arguments": {
                    "conversation_id": "conv-1",
                    "participant_id": "part-1",
                    "god_session_id": "god-1",
                    "client_request_id": "req-1",
                    "content": "missing reply target",
                },
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "reply_to_inbox_item_id" in result["content"][0]["text"]


def test_get_tool_inventory_groups_existing_mcp_tools(tmp_path: Path) -> None:
    server = load_mcp_module()

    client = TestClient(server.create_app(xmuse_root=tmp_path / "xmuse"))

    inventory = mcp_call(client, "get_tool_inventory")

    assert inventory["kind"] == "tool_inventory"
    assert inventory["read_only"] is True
    assert inventory["counts"]["total"] >= 10
    assert "list_lanes" in inventory["families"]["control"]["tool_names"]
    assert "get_lane" in inventory["families"]["platform"]["tool_names"]
    assert "chat_post_message" in inventory["families"]["chat"]["tool_names"]
    assert "read_lane_contract" in inventory["families"]["contracts"]["tool_names"]
    tools = {
        tool["name"]: tool
        for family in inventory["families"].values()
        for tool in family["tools"]
    }
    assert tools["enqueue_lane"]["access"] == "write"
    assert tools["enqueue_lane"]["mutation_contract"] == "audit_guard_required"
    assert tools["abort_lane"]["mutation_contract"] == "audit_guard_required"
    assert tools["update_lane_status"]["mutation_contract"] == "audit_guard_required"
    assert tools["chat_post_message"]["access"] == "write"
    assert tools["chat_post_message"]["mutation_contract"] == "chat_identity_idempotency"
    assert tools["chat_emit_proposal"]["mutation_contract"] == "chat_identity_idempotency"
    assert tools["read_lane_contract"]["mutation_contract"] == "read_only"


def test_chat_post_message_reply_marks_inbox_read_with_responded_message_id(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    created = mcp_call(client, "chat_create_conversation", {"title": "MCP writeback"})
    conversation_id = created["conversation"]["id"]
    architect = next(
        participant
        for participant in created["participants"]
        if participant["role"] == "architect"
    )
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=architect["participant_id"],
    )
    assert session is not None
    chat = ChatStore(xmuse_root / "chat.db")
    human = chat.add_message(conversation_id, "human-1", "human", "@architect hello")
    inbox = ChatInboxStore(xmuse_root / "chat.db")
    item = inbox.create_item(
        conversation_id=conversation_id,
        target_participant_id=architect["participant_id"],
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=human.id,
        item_type="mention",
        payload={"content": human.content},
    )

    read_result = mcp_call(
        client,
        "chat_read_inbox",
        {
            "conversation_id": conversation_id,
            "participant_id": architect["participant_id"],
            "god_session_id": session.god_session_id,
        },
    )
    assert [read_item["id"] for read_item in read_result["inbox_items"]] == [item.id]
    result = mcp_call(
        client,
        "chat_post_message",
        {
            "conversation_id": conversation_id,
            "participant_id": architect["participant_id"],
            "god_session_id": session.god_session_id,
            "client_request_id": "architect-mcp-reply-1",
            "content": "Architect GOD: received.",
            "reply_to_inbox_item_id": item.id,
        },
    )

    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == result["message"]["id"]
    assert result["message"]["envelope_type"] == "message"
    assert result["message"]["envelope_json"]["type"] == "message"
    stages = PeerTurnLatencyTraceStore(xmuse_root / "chat.db").list_mcp_tool_stages(
        conversation_id,
        item.id,
    )
    assert {"chat_read_inbox", "chat_post_message"}.issubset(stages)
    assert "mcp_tool_call_started" in stages
    assert "mcp_tool_call_completed" in stages
    assert "chat_post_message_persisted" in stages
    assert registry.get(session.god_session_id).status == "running"


def test_chat_record_collaboration_response_promotes_session_status_to_running(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()
    xmuse_root = tmp_path / "xmuse"
    mcp_client = TestClient(server.create_app(xmuse_root=xmuse_root))

    created = mcp_call(
        mcp_client,
        "chat_create_conversation",
        {"title": "Collaboration response writeback"},
    )
    conversation_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    registry = GodSessionRegistry(xmuse_root / "god_sessions.json")
    architect_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["architect"]["participant_id"],
    )
    execute_session = registry.find_by_conversation_participant(
        conversation_id=conversation_id,
        participant_id=participants["execute"]["participant_id"],
    )

    run = mcp_chat_call(
        mcp_client,
        "chat_create_collaboration_request",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "collab-status-promote",
            "goal": "Confirm bounded execution scope.",
            "targets": ["execute"],
            "callback_target": "architect",
            "question": "Return an execute feasibility verdict.",
            "context_refs": ["message:latest"],
            "timeout_s": 480,
        },
    )["run"]

    response = mcp_chat_call(
        mcp_client,
        "chat_record_collaboration_response",
        {
            "conversation_id": conversation_id,
            "participant_id": participants["execute"]["participant_id"],
            "god_session_id": execute_session.god_session_id,
            "run_id": run["run_id"],
            "content": "Executable as one bounded lane.",
            "status": "received",
        },
    )["run"]

    assert response["status"] == "done"
    assert registry.get(execute_session.god_session_id).status == "running"


def test_read_provider_inventory_returns_sanitized_static_profile_metadata(
    tmp_path: Path,
) -> None:
    server = load_mcp_module()

    client = TestClient(server.create_app(xmuse_root=tmp_path / "xmuse"))

    inventory = mcp_call(client, "read_provider_inventory")

    assert inventory["kind"] == "provider_inventory"
    assert inventory["read_only"] is True
    assert inventory["counts"] == {"providers": 2, "profiles": 6}
    assert inventory["provider_ids"] == ["codex", "opencode"]

    providers = {provider["provider_id"]: provider for provider in inventory["providers"]}
    assert providers["codex"]["profile_refs"] == [
        "codex.default",
        "codex.worker",
        "codex.review",
        "codex.god",
        "codex.final_quality",
    ]
    assert providers["opencode"]["profile_refs"] == ["opencode.deepseek_flash_worker"]

    profiles = {
        profile["ref"]: profile
        for provider in inventory["providers"]
        for profile in provider["profiles"]
    }

    assert profiles["codex.worker"] == {
        "ref": "codex.worker",
        "provider_id": "codex",
        "profile_id": "worker",
        "adapter_kind": "codex_cli",
        "model_id": "gpt-5.4-mini",
        "supports_mcp": True,
        "supports_persistent_sessions": True,
        "persistent_capability": "supported",
        "support_level": "primary",
        "cost_tier": "low",
        "risk_tier": "low",
        "task_capabilities": ["bounded_code_writing"],
        "model_id_env_name": None,
        "api_base_env_name": None,
        "env_requirement_names": [],
    }
    assert profiles["codex.final_quality"] == {
        "ref": "codex.final_quality",
        "provider_id": "codex",
        "profile_id": "final_quality",
        "adapter_kind": "codex_cli",
        "model_id": "gpt-5.5",
        "supports_mcp": True,
        "supports_persistent_sessions": True,
        "persistent_capability": "supported",
        "support_level": "primary",
        "cost_tier": "high",
        "risk_tier": "high",
        "task_capabilities": ["merge_final_review"],
        "model_id_env_name": None,
        "api_base_env_name": None,
        "env_requirement_names": [],
    }
    assert profiles["opencode.deepseek_flash_worker"] == {
        "ref": "opencode.deepseek_flash_worker",
        "provider_id": "opencode",
        "profile_id": "deepseek_flash_worker",
        "adapter_kind": "opencode_cli",
        "model_id": "deepseek-v4-flash",
        "supports_mcp": False,
        "supports_persistent_sessions": False,
        "persistent_capability": "unsupported",
        "support_level": "secondary",
        "cost_tier": "low",
        "risk_tier": "low",
        "task_capabilities": ["bounded_code_writing", "bounded_deliberation"],
        "model_id_env_name": "DEEPSEEK_MODEL",
        "api_base_env_name": "DEEPSEEK_BASE_URL",
        "env_requirement_names": ["DEEPSEEK_API_KEY"],
    }

    serialized = json.dumps(inventory, sort_keys=True)
    for forbidden in (
        "command",
        "stderr",
        "api_key",
        "secret",
        "DEEPSEEK_API_KEY=",
        "OPENAI_API_KEY",
    ):
        assert forbidden not in serialized


def test_sse_advertised_messages_endpoint_accepts_json_rpc(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    write_json(xmuse_root / "feature_lanes.json", {"lanes": []})
    client = TestClient(server.create_app(xmuse_root=xmuse_root))
    sse = client.get("/sse")
    endpoint_line = next(line for line in sse.text.splitlines() if line.startswith("data: "))
    endpoint = endpoint_line.removeprefix("data: ")

    initialize = client.post(
        endpoint,
        json={"jsonrpc": "2.0", "id": "init", "method": "initialize"},
    )
    assert initialize.status_code == 200
    assert initialize.json()["result"]["serverInfo"]["name"] == "xmuse-mcp"

    response = client.post(
        endpoint,
        json={
            "jsonrpc": "2.0",
            "id": "call-list-lanes",
            "method": "tools/call",
            "params": {"name": "list_lanes", "arguments": {}},
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"lanes": []}


def test_post_sse_accepts_json_rpc_for_clients_that_probe_sse_url(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    write_json(xmuse_root / "feature_lanes.json", {"lanes": []})
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    response = client.post(
        "/sse",
        json={
            "jsonrpc": "2.0",
            "id": "call-list-lanes",
            "method": "tools/call",
            "params": {"name": "list_lanes", "arguments": {}},
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"lanes": []}


def test_list_lanes_and_enqueue_lane_update_feature_lanes(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    lanes_path = xmuse_root / "feature_lanes.json"
    write_json(
        lanes_path,
        {"lanes": [{"feature_id": "existing", "task_type": "execute", "status": "done"}]},
    )
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    assert mcp_call(client, "list_lanes") == read_json(lanes_path)

    unsafe = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "unsafe-enqueue",
            "method": "tools/call",
            "params": {
                "name": "enqueue_lane",
                "arguments": {
                    "feature_id": "new-lane",
                    "prompt": "Implement the new lane.",
                    "capabilities": ["code", "test"],
                },
            },
        },
    )
    assert unsafe.status_code == 200
    unsafe_result = unsafe.json()["result"]
    assert unsafe_result["isError"] is True
    assert "audit" in unsafe_result["content"][0]["text"]

    created = mcp_call(
        client,
        "enqueue_lane",
        {
            "feature_id": "new-lane",
            "prompt": "Implement the new lane.",
            "capabilities": ["code", "test"],
            "audit": {
                "actor": "execute_god",
                "reason": "queue bounded worker lane",
                "request_id": "req-enqueue-1",
            },
            "guard": {"expected_revision": 0},
        },
    )

    assert created["status"] == "pending"
    lanes = read_json(lanes_path)
    assert lanes["projection_revision"] == 1
    assert lanes["lanes"][-1] == {
        "feature_id": "new-lane",
        "task_type": "execute",
        "prompt_summary": "Implement the new lane.",
        "prompt_ref": "logs/lane_prompts/new-lane.md",
        "capabilities": ["code", "test"],
        "status": "pending",
        "last_mutation_audit": {
            "actor": "execute_god",
            "reason": "queue bounded worker lane",
            "request_id": "req-enqueue-1",
            "tool": "enqueue_lane",
        },
    }
    assert (xmuse_root / "logs" / "lane_prompts" / "new-lane.md").read_text(
        encoding="utf-8"
    ) == "Implement the new lane."

    duplicate = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "duplicate",
            "method": "tools/call",
            "params": {
                "name": "enqueue_lane",
                "arguments": {
                    "feature_id": "new-lane",
                    "prompt": "Duplicate lane.",
                    "capabilities": ["code"],
                    "audit": {
                        "actor": "execute_god",
                        "reason": "duplicate queue attempt",
                        "request_id": "req-enqueue-2",
                    },
                    "guard": {"expected_revision": 1},
                },
            },
        },
    )
    assert duplicate.status_code == 200
    result = duplicate.json()["result"]
    assert result["isError"] is True
    assert "lane already exists" in result["content"][0]["text"]
    assert read_json(lanes_path)["projection_revision"] == 1


def test_get_status_and_abort_lane_include_active_session(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    write_json(
        xmuse_root / "feature_lanes.json",
        {"lanes": [{"feature_id": "active-lane", "status": "running"}]},
    )
    write_json(
        xmuse_root / "active_sessions.json",
        {
            "sessions": {
                "active-lane": {
                    "session_id": "sess-1",
                    "pid": 999999,
                    "status": "running",
                }
            }
        },
    )
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    status = mcp_call(client, "get_status", {"feature_id": "active-lane"})
    assert status["lane"]["status"] == "running"
    assert status["active_session"]["session_id"] == "sess-1"

    aborted = mcp_call(
        client,
        "abort_lane",
        {
            "feature_id": "active-lane",
            "audit": {
                "actor": "operator",
                "reason": "request safe stop",
                "request_id": "req-abort-1",
            },
            "guard": {"lane_status": "running", "session_status": "running"},
        },
    )

    assert aborted["aborted"] is True
    assert aborted["lane"]["status"] == "running"
    assert aborted["lane"]["abort_requested"] is True
    assert aborted["active_session"]["status"] == "abort_requested"
    lanes = read_json(xmuse_root / "feature_lanes.json")
    assert lanes["lanes"][0]["status"] == "running"
    assert lanes["lanes"][0]["abort_requested"] is True
    assert lanes["projection_revision"] == 1
    sessions = read_json(xmuse_root / "active_sessions.json")["sessions"]
    assert sessions["active-lane"]["abort_requested"] is True
    assert sessions["active-lane"]["status"] == "abort_requested"


def test_abort_lane_requires_session_guard_when_active_session_exists(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    write_json(
        xmuse_root / "feature_lanes.json",
        {
            "projection_revision": 4,
            "lanes": [{"feature_id": "active-lane", "status": "running"}],
        },
    )
    write_json(
        xmuse_root / "active_sessions.json",
        {
            "sessions": {
                "active-lane": {
                    "session_id": "sess-1",
                    "status": "running",
                }
            }
        },
    )
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "abort-missing-session-guard",
            "method": "tools/call",
            "params": {
                "name": "abort_lane",
                "arguments": {
                    "feature_id": "active-lane",
                    "audit": {
                        "actor": "operator",
                        "reason": "request safe stop",
                        "request_id": "req-abort-missing-session-guard",
                    },
                    "guard": {"lane_status": "running"},
                },
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "requires guard.session_status" in result["content"][0]["text"]
    assert read_json(xmuse_root / "feature_lanes.json") == {
        "projection_revision": 4,
        "lanes": [{"feature_id": "active-lane", "status": "running"}],
    }
    assert read_json(xmuse_root / "active_sessions.json") == {
        "sessions": {
            "active-lane": {
                "session_id": "sess-1",
                "status": "running",
            }
        }
    }


def test_abort_lane_session_guard_mismatch_keeps_lane_and_session_unchanged(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    write_json(
        xmuse_root / "feature_lanes.json",
        {
            "projection_revision": 4,
            "lanes": [{"feature_id": "active-lane", "status": "running"}],
        },
    )
    write_json(
        xmuse_root / "active_sessions.json",
        {
            "sessions": {
                "active-lane": {
                    "session_id": "sess-1",
                    "status": "paused",
                }
            }
        },
    )
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "abort-guard-mismatch",
            "method": "tools/call",
            "params": {
                "name": "abort_lane",
                "arguments": {
                    "feature_id": "active-lane",
                    "audit": {
                        "actor": "operator",
                        "reason": "request safe stop",
                        "request_id": "req-abort-guard-mismatch",
                    },
                    "guard": {
                        "lane_status": "running",
                        "session_status": "running",
                    },
                },
            },
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert "guard.session_status mismatch" in result["content"][0]["text"]
    assert read_json(xmuse_root / "feature_lanes.json") == {
        "projection_revision": 4,
        "lanes": [{"feature_id": "active-lane", "status": "running"}],
    }
    assert read_json(xmuse_root / "active_sessions.json") == {
        "sessions": {
            "active-lane": {
                "session_id": "sess-1",
                "status": "paused",
            }
        }
    }


def test_error_knowledge_search_and_lane_logs(tmp_path: Path) -> None:
    server = load_mcp_module()

    xmuse_root = tmp_path / "xmuse"
    write_json(
        xmuse_root / "error_knowledge.json",
        {
            "entries": [
                {
                    "entry_id": "ek-1",
                    "pit": "ruff failed on unused import",
                    "root_cause": "stale import after refactor",
                    "fix": "remove the import",
                    "lesson": "run ruff before review",
                },
                {
                    "entry_id": "ek-2",
                    "pit": "timeout during public benchmark",
                    "lesson": "separate network-bound evals",
                },
            ]
        },
    )
    log_dir = xmuse_root / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "round-001-alpha.log").write_text("first log\n", encoding="utf-8")
    (log_dir / "round-002-alpha.log").write_text("second log\n", encoding="utf-8")
    (log_dir / "round-001-beta.log").write_text("other log\n", encoding="utf-8")
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    matches = mcp_call(client, "get_error_knowledge", {"query": "unused import ruff"})
    assert matches["matches"][0]["entry"]["entry_id"] == "ek-1"
    assert matches["matches"][0]["score"] > 0

    logs = mcp_call(client, "get_logs", {"feature_id": "alpha"})
    assert [entry["path"] for entry in logs["logs"]] == [
        "logs/round-001-alpha.log",
        "logs/round-002-alpha.log",
    ]
    assert "first log" in logs["combined"]
    assert "second log" in logs["combined"]
