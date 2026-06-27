from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.natural_routing import (
    DEFAULT_NATURAL_ROUTE_MAX_DEPTH,
    build_natural_route_event,
    natural_route_payload,
)
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _mcp_call(client: TestClient, name: str, arguments: dict):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]["content"][0]["text"]


def _registered_participant(tmp_path: Path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("MCP")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    session = GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role="architect",
        agent_name="Architect GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{participant.participant_id}",
        session_inbox_id=f"inbox-{participant.participant_id}",
        conversation_id=conv.id,
        participant_id=participant.participant_id,
    )
    return chat, conv, participant, session


def _complete_handoff_content() -> str:
    return (
        "what: inspect the implementation risk\n"
        "why: execution depends on this handoff before dispatch\n"
        "tradeoffs: keep the check bounded and avoid broad refactor\n"
        "open_questions: none for this handoff\n"
        "next_action: reply with a concise feasibility note\n"
        "evidence_refs: message:latest"
    )


def test_mcp_lists_chat_tools(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "chat_list_conversations" in names
    assert "chat_create_conversation" in names
    assert "chat_list_participants" in names
    assert "chat_post_message" in names
    assert "chat_read_inbox" in names
    assert "chat_mention" in names
    assert "chat_emit_proposal" in names
    assert "chat_emit_blueprint_proposal" in names
    assert "chat_create_collaboration_request" in names
    assert "chat_record_collaboration_response" in names
    assert "chat_raise_collaboration_blocker" in names
    assert "chat_resolve_collaboration_blocker" in names
    assert "chat_evaluate_dispatch_gate" in names
    mention_tool = next(
        tool for tool in response.json()["result"]["tools"] if tool["name"] == "chat_mention"
    )
    assert "reply_to_inbox_item_id" in mention_tool["inputSchema"]["properties"]


def test_chat_create_conversation_uses_default_codex_participants(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(client, "chat_create_conversation", {"title": "Ops room"})
    )

    assert payload["conversation"]["id"].startswith("conv_")
    assert payload["conversation"]["title"] == "Ops room"
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert {participant["provider_id"] for participant in payload["participants"]} == {"codex"}
    assert {
        participant["role"]: participant["profile_id"] for participant in payload["participants"]
    } == {
        "architect": "god",
        "review": "review",
        "execute": "worker",
    }
    assert {participant["cli_kind"] for participant in payload["participants"]} == {"codex"}
    assert {
        participant["role"]: participant["model"] for participant in payload["participants"]
    } == {
        "architect": "gpt-5.4",
        "review": "gpt-5.4",
        "execute": "gpt-5.4-mini",
    }


def test_mcp_chat_create_conversation_schema_exposes_provider_profile_fields(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    tool = next(
        item
        for item in response.json()["result"]["tools"]
        if item["name"] == "chat_create_conversation"
    )
    participant_schema = tool["inputSchema"]["properties"]["participants"]["items"]

    assert "provider_id" in participant_schema["properties"]
    assert "profile_id" in participant_schema["properties"]
    assert participant_schema["required"] == ["role"]


def test_mcp_chat_create_conversation_accepts_provider_profile_participants(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_create_conversation",
            {
                "title": "Provider compatible",
                "participants": [
                    {
                        "role": "review",
                        "display_name": "Review GOD",
                        "provider_id": "codex",
                        "profile_id": "review",
                        "model": "gpt-5.5",
                    }
                ],
            },
        )
    )

    assert payload["participants"][0]["provider_id"] == "codex"
    assert payload["participants"][0]["profile_id"] == "review"
    assert payload["participants"][0]["cli_kind"] == "codex"


def test_chat_list_participants_is_scoped_to_one_conversation(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    first = json.loads(
        _mcp_call(
            client,
            "chat_create_conversation",
            {
                "title": "First",
                "participants": [
                    {
                        "role": "architect",
                        "display_name": "Architect A",
                        "cli_kind": "codex",
                    }
                ],
            },
        )
    )
    json.loads(
        _mcp_call(
            client,
            "chat_create_conversation",
            {
                "title": "Second",
                "participants": [
                    {
                        "role": "review",
                        "display_name": "Review B",
                        "cli_kind": "codex",
                    }
                ],
            },
        )
    )

    payload = json.loads(
        _mcp_call(
            client,
            "chat_list_participants",
            {"conversation_id": first["conversation"]["id"]},
        )
    )

    assert payload["conversation_id"] == first["conversation"]["id"]
    display_names = {
        participant["display_name"] for participant in payload["participants"]
    }
    assert "Architect A" in display_names
    assert "init-god" in display_names
    assert "Review B" not in display_names


def test_chat_list_conversations_includes_compact_peer_summaries(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Summary")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    message = chat.add_message(conv.id, "Human", "human", "hello")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "hello"},
    )
    claimed_item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "hello again"},
    )
    claimed = inbox.claim_next(owner="scheduler")
    assert claimed is not None
    assert claimed.id != claimed_item.id or claimed.status == "claimed"
    chat.create_proposal(
        conversation_id=conv.id,
        author=participant.participant_id,
        proposal_type="lane_graph",
        content='{"summary": "Build the next lane", "lanes": [{"feature_id": "a"}]}',
        references=[],
    )

    client = TestClient(create_app(tmp_path))
    payload = json.loads(_mcp_call(client, "chat_list_conversations", {}))

    assert len(payload["conversations"]) == 1
    summary = payload["conversations"][0]
    assert summary["id"] == conv.id
    assert summary["title"] == "Summary"
    assert summary["created_at"] == conv.created_at
    assert summary["participants"] == {
        "total": 1,
        "active": 1,
        "stopped": 0,
        "roles": ["architect"],
        "items": [
            {
                "participant_id": participant.participant_id,
                "conversation_id": conv.id,
                "role": "architect",
                "display_name": "Architect GOD",
                "provider_id": "codex",
                "profile_id": "god",
                "cli_kind": "codex",
                "model": "gpt-5.4",
                "status": "active",
            }
        ],
    }
    assert summary["inbox_counts"] == {"unread": 1, "claimed": 1}
    assert summary["card_counts"] == {
        "proposal": 1,
        "worklist_summary": 1,
        "total": 2,
    }
    assert summary["href"] == f"/dashboard/peer-chat/conversations/{conv.id}"
    assert summary["dashboard_href"] == summary["href"]
    assert summary["api_href"] == f"/api/chat/conversations/{conv.id}/messages"
    assert summary["linked_session_ids"] == []
    assert summary["sessions"] == []
    assert [item["id"] for item in summary["recent_messages"]] == [message.id]
    proposal_card = next(
        card for card in summary["recent_cards"] if card["card_type"] == "proposal"
    )
    worklist_card = next(
        card for card in summary["recent_cards"] if card["card_type"] == "worklist_summary"
    )
    assert proposal_card["metadata"] == {"proposal_type": "lane_graph"}
    assert worklist_card["counts"] == {
        "unread_inbox": 1,
        "claimed_inbox": 1,
        "ready_lanes": 0,
        "under_review_lanes": 0,
        "failed_lanes": 0,
        "terminal_lanes": 0,
    }
    assert summary["last_activity_at"] == max(
        conv.created_at,
        message.created_at,
        *(card["created_at"] for card in summary["recent_cards"]),
    )


def test_mcp_chat_inspect_conversation_parity_with_dashboard(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Parity")
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    chat.add_message(conv.id, "Human", "human", "design this")

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(client, "chat_inspect_conversation", {"conversation_id": conv.id})
    )

    assert payload["conversation"]["id"] == conv.id
    assert "participants" in payload
    assert "inbox_summary" in payload["participants"]
    assert "recent_activity" in payload
    assert "current_blueprint" in payload
    assert "current_feature_plan" in payload
    assert "current_graph_set" in payload


def test_mcp_chat_inspect_conversation_returns_session_health(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Health")
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-a",
                    "conversation_id": conv.id,
                    "role": "architect",
                    "status": "running",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(client, "chat_inspect_conversation", {"conversation_id": conv.id})
    )

    assert "session_health" in payload
    assert payload["session_health"]["total"] == 1
    assert payload["session_health"]["by_status"]["running"] == 1


def test_mcp_chat_inspect_conversation_returns_graph_worklist(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Graph")
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "lane-a", "conversation_id": conv.id, "status": "pending"}]},
    )
    # Lane graph file to establish conversation scope
    (tmp_path / "lane_graphs").mkdir(parents=True, exist_ok=True)
    _write_json(
        tmp_path / "lane_graphs" / "graph-alpha.json",
        {
            "id": "graph-alpha",
            "conversation_id": conv.id,
            "version": 1,
            "lanes": [{"feature_id": "lane-a"}],
        },
    )
    _write_json(
        tmp_path / "self_evolution" / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": "lin-1",
                    "source_run_id": "run-a",
                    "spawned_graph_id": "graph-alpha",
                    "blueprint_set_id": "bp-1",
                    "target_track_ids": [],
                    "evolution_proposal_id": "prop-1",
                    "guardrail_decision_id": "guard-1",
                    "created_at": "2026-06-04T00:00:00Z",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(client, "chat_inspect_conversation", {"conversation_id": conv.id})
    )

    assert "graph_worklist" in payload
    assert payload["graph_worklist"]["total_lanes"] == 1
    assert payload["graph_worklist"]["authoritative_graph_id"] == "graph-alpha"


def test_mcp_chat_inspect_conversation_returns_artifacts_and_degradation(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Full")
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "lane-err", "conversation_id": conv.id, "status": "failed"}]},
    )
    _write_json(
        tmp_path / "error_knowledge.json",
        {"entries": [
            {"entry_id": "err-1", "message": "first error", "lane_id": "lane-err"},
            {"entry_id": "err-2", "message": "second error", "lane_id": "lane-err"},
        ]},
    )

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(client, "chat_inspect_conversation", {"conversation_id": conv.id})
    )

    assert "artifacts" in payload
    assert "degradation" in payload
    assert payload["degradation"]["error_count"] == 2
    assert len(payload["degradation"]["errors"]) == 2
    assert any("first error" in str(e) for e in payload["degradation"]["errors"])


def test_mcp_chat_inspect_conversation_empty_when_no_data(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Empty")

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(client, "chat_inspect_conversation", {"conversation_id": conv.id})
    )

    assert payload["session_health"]["total"] == 0
    assert payload["graph_worklist"]["total_lanes"] == 0
    assert payload["artifacts"]["total"] == 0
    assert payload["degradation"]["error_count"] == 0


def test_chat_post_message_rejects_spoofed_session(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("MCP")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    client = TestClient(create_app(tmp_path))

    payload = _mcp_call(
        client,
        "chat_post_message",
        {
            "conversation_id": conv.id,
            "participant_id": participant.participant_id,
            "god_session_id": "unknown-session",
            "client_request_id": "mcp-1",
            "content": "hello",
        },
    )

    assert "unknown_god_session" in payload


def test_chat_post_message_mentions_do_not_create_followup_inbox(tmp_path: Path) -> None:
    chat, conv, participant, session = _registered_participant(tmp_path)
    review = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    source = chat.add_message(conv.id, "Human", "human", "hello @architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": source.content},
    )

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(
            client,
            "chat_post_message",
            {
                "conversation_id": conv.id,
                "participant_id": participant.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "mcp-reply-mentions-only",
                "content": "@review I will ask for review after there is a concrete diff.",
                "reply_to_inbox_item_id": item.id,
            },
        )
    )

    assert payload["message"]["mentions"] == ["@review"]
    assert payload["inbox_items"] == []
    assert ChatInboxStore(tmp_path / "chat.db").list_for_participant(
        conversation_id=conv.id,
        participant_id=review.participant_id,
    ) == []


def test_peer_replies_enqueue_drain_callback_for_original_sender(tmp_path: Path) -> None:
    _chat, conv, architect, architect_session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.4-mini",
    )
    review = participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    execute_session = registry.create(
        role="execute",
        agent_name="Execute GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{execute.participant_id}",
        session_inbox_id=f"inbox-{execute.participant_id}",
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )
    review_session = registry.create(
        role="review",
        agent_name="Review GOD",
        runtime="opencode",
        session_address=f"xmuse://{conv.id}/{review.participant_id}",
        session_inbox_id=f"inbox-{review.participant_id}",
        conversation_id=conv.id,
        participant_id=review.participant_id,
    )
    client = TestClient(create_app(tmp_path))

    _mcp_call(
        client,
        "chat_mention",
        {
            "conversation_id": conv.id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "ask-execute",
            "target_address": "@execute",
            "content": "Implementation-risk note, one sentence.",
        },
    )
    _mcp_call(
        client,
        "chat_mention",
        {
            "conversation_id": conv.id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "ask-review",
            "target_address": "@review",
            "content": "Proof-boundary critique, one sentence.",
        },
    )
    inbox_store = ChatInboxStore(tmp_path / "chat.db")
    execute_item = inbox_store.list_for_participant(
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )[0]
    review_item = inbox_store.list_for_participant(
        conversation_id=conv.id,
        participant_id=review.participant_id,
    )[0]

    review_response = json.loads(
        _mcp_call(
            client,
            "chat_post_message",
            {
                "conversation_id": conv.id,
                "participant_id": review.participant_id,
                "god_session_id": review_session.god_session_id,
                "client_request_id": "review-reply",
                "content": "Proof boundary remains local runtime only.",
                "reply_to_inbox_item_id": review_item.id,
            },
        )
    )

    review_callbacks = [
        item
        for item in review_response["inbox_items"]
        if item["item_type"] == "peer_reply_drain_callback"
    ]
    assert len(review_callbacks) == 1
    assert review_callbacks[0]["payload"]["dependency_targets"] == ["review"]

    response = json.loads(
        _mcp_call(
            client,
            "chat_post_message",
            {
                "conversation_id": conv.id,
                "participant_id": execute.participant_id,
                "god_session_id": execute_session.god_session_id,
                "client_request_id": "execute-reply",
                "content": "Implementation risk is stale summary gating.",
                "reply_to_inbox_item_id": execute_item.id,
            },
        )
    )

    callback_items = [
        item
        for item in response["inbox_items"]
        if item["item_type"] == "peer_reply_drain_callback"
    ]
    assert len(callback_items) == 1
    callback = callback_items[0]
    assert callback["target_participant_id"] == architect.participant_id
    assert callback["target_role"] == "architect"
    assert callback["payload"]["trigger_mode"] == "peer_reply_drain_callback"
    assert callback["payload"]["pending_peer_inbox_count"] == 0
    assert callback["payload"]["dependency_targets"] == ["execute"]

    architect_callbacks = [
        item
        for item in inbox_store.list_for_participant(
            conversation_id=conv.id,
            participant_id=architect.participant_id,
        )
        if item.item_type == "peer_reply_drain_callback"
    ]
    assert len(architect_callbacks) == 2


def test_peer_reply_drain_callback_is_scoped_to_source_handoff(
    tmp_path: Path,
) -> None:
    _chat, conv, architect, architect_session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.4-mini",
    )
    review = participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    execute_session = registry.create(
        role="execute",
        agent_name="Execute GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{execute.participant_id}",
        session_inbox_id=f"inbox-{execute.participant_id}",
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )
    registry.create(
        role="review",
        agent_name="Review GOD",
        runtime="opencode",
        session_address=f"xmuse://{conv.id}/{review.participant_id}",
        session_inbox_id=f"inbox-{review.participant_id}",
        conversation_id=conv.id,
        participant_id=review.participant_id,
    )
    client = TestClient(create_app(tmp_path))

    first = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "client_request_id": "ask-execute-independent",
                "target_address": "@execute",
                "content": "Implementation-risk note, one sentence.",
            },
        )
    )
    _mcp_call(
        client,
        "chat_mention",
        {
            "conversation_id": conv.id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "ask-review-independent",
            "target_address": "@review",
            "content": "Proof-boundary critique, one sentence.",
        },
    )
    inbox_store = ChatInboxStore(tmp_path / "chat.db")
    execute_item = inbox_store.list_for_participant(
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )[0]
    review_item = inbox_store.list_for_participant(
        conversation_id=conv.id,
        participant_id=review.participant_id,
    )[0]

    response = json.loads(
        _mcp_call(
            client,
            "chat_post_message",
            {
                "conversation_id": conv.id,
                "participant_id": execute.participant_id,
                "god_session_id": execute_session.god_session_id,
                "client_request_id": "execute-independent-reply",
                "content": "Implementation risk is stale summary gating.",
                "reply_to_inbox_item_id": execute_item.id,
            },
        )
    )

    callback_items = [
        item
        for item in response["inbox_items"]
        if item["item_type"] == "peer_reply_drain_callback"
    ]
    assert len(callback_items) == 1
    callback = callback_items[0]
    assert callback["target_participant_id"] == architect.participant_id
    assert callback["payload"]["dependency_set_id"] == (
        f"peer-reply-set:{first['message']['id']}"
    )
    assert callback["payload"]["source_message_id"] == first["message"]["id"]
    assert callback["payload"]["dependency_targets"] == ["execute"]
    assert inbox_store.get(review_item.id).status == "unread"


def test_chat_read_inbox_includes_claimed_items_for_verified_session(tmp_path: Path) -> None:
    chat, conv, participant, session = _registered_participant(tmp_path)
    source = chat.add_message(conv.id, "Human", "human", "hello @architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": source.content},
    )
    claimed = inbox.claim_next(owner="scheduler-1")
    assert claimed is not None

    client = TestClient(create_app(tmp_path))
    payload = json.loads(
        _mcp_call(
            client,
            "chat_read_inbox",
            {
                "conversation_id": conv.id,
                "participant_id": participant.participant_id,
                "god_session_id": session.god_session_id,
            },
        )
    )

    assert [inbox_item["id"] for inbox_item in payload["inbox_items"]] == [item.id]
    assert payload["inbox_items"][0]["status"] == "claimed"


def test_chat_mention_surfaces_display_name_routing_and_inbox_delivery(
    tmp_path: Path,
) -> None:
    _chat, conv, sender, session = _registered_participant(tmp_path)
    target = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "display-route-1",
                "target_address": "@Review GOD",
                "content": "please inspect",
            },
        )
    )

    assert payload["message"]["mentions"] == ["@review-god"]
    assert payload["mention_routing"] == {
        "requested_target": "@Review GOD",
        "resolved_mentions": [
            {
                "normalized": "@review-god",
                "conversation_id": conv.id,
                "target_participant_id": target.participant_id,
                "target_role": "review",
                "target_address": "@review-god",
                "inbox_item_id": payload["inbox_items"][0]["id"],
            }
        ],
    }
    assert payload["inbox_items"][0]["conversation_id"] == conv.id
    assert payload["inbox_items"][0]["target_participant_id"] == target.participant_id
    assert payload["natural_route"]["source_kind"] == "chat_mention"
    assert payload["natural_route"]["target_participant_id"] == target.participant_id
    assert payload["natural_route"]["status"] == "pending"
    assert payload["inbox_items"][0]["payload"]["natural_route"] == (
        payload["natural_route"]
    )


def test_chat_mention_can_reply_to_current_inbox_item(tmp_path: Path) -> None:
    chat, conv, sender, session = _registered_participant(tmp_path)
    target = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    source = chat.add_message(conv.id, "Human", "human", "@architect hand off")
    inbox_store = ChatInboxStore(tmp_path / "chat.db")
    source_item = inbox_store.create_item(
        conversation_id=conv.id,
        target_participant_id=sender.participant_id,
        target_role=sender.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": source.content},
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "handoff-reply-1",
                "target_address": "@execute",
                "content": _complete_handoff_content(),
                "reply_to_inbox_item_id": source_item.id,
            },
        )
    )

    replied = inbox_store.get(source_item.id)
    assert replied.status == "read"
    assert replied.responded_message_id == payload["message"]["id"]
    assert payload["inbox_items"][0]["target_participant_id"] == target.participant_id
    assert payload["natural_route"]["source_refs"] == [
        f"message:{source.id}",
        f"inbox:{source_item.id}",
    ]
    assert payload["natural_route"]["route_kind"] == "handoff"
    assert payload["handoff_assessment"]["is_complete"] is True
    assert payload["inbox_items"][0]["payload"]["handoff_assessment"][
        "missing_fields"
    ] == []
    stages = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_mcp_tool_stages(
        conv.id,
        source_item.id,
    )
    assert "chat_mention" in stages


def test_chat_mention_reply_increments_parent_natural_route_depth(
    tmp_path: Path,
) -> None:
    chat, conv, sender, session = _registered_participant(tmp_path)
    target = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    source = chat.add_message(conv.id, "Human", "human", "@architect start")
    parent_route = build_natural_route_event(
        conversation_id=conv.id,
        origin_message_id=source.id,
        source_kind="human_line_start_mention",
        author_participant_id=None,
        target_participant_id=sender.participant_id,
        route_kind="mention",
        source_refs=[f"message:{source.id}"],
        depth=2,
    )
    inbox_store = ChatInboxStore(tmp_path / "chat.db")
    source_item = inbox_store.create_item(
        conversation_id=conv.id,
        target_participant_id=sender.participant_id,
        target_role=sender.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload=natural_route_payload(
            parent_route,
            content=source.content,
            mention="@architect",
        ),
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "route-depth-increment-1",
                "target_address": "@review",
                "content": _complete_handoff_content(),
                "reply_to_inbox_item_id": source_item.id,
            },
        )
    )

    assert payload["inbox_items"][0]["target_participant_id"] == target.participant_id
    assert payload["natural_route"]["depth"] == 3
    assert payload["inbox_items"][0]["payload"]["route_depth"] == 3
    assert payload["natural_route"]["source_refs"] == [
        f"message:{source.id}",
        f"inbox:{source_item.id}",
    ]


def test_chat_mention_reply_blocks_when_natural_route_depth_exceeds_max(
    tmp_path: Path,
) -> None:
    chat, conv, sender, session = _registered_participant(tmp_path)
    target = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    source = chat.add_message(conv.id, "Human", "human", "@architect start")
    parent_route = build_natural_route_event(
        conversation_id=conv.id,
        origin_message_id=source.id,
        source_kind="human_line_start_mention",
        author_participant_id=None,
        target_participant_id=sender.participant_id,
        route_kind="mention",
        source_refs=[f"message:{source.id}"],
        depth=DEFAULT_NATURAL_ROUTE_MAX_DEPTH,
    )
    inbox_store = ChatInboxStore(tmp_path / "chat.db")
    source_item = inbox_store.create_item(
        conversation_id=conv.id,
        target_participant_id=sender.participant_id,
        target_role=sender.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload=natural_route_payload(
            parent_route,
            content=source.content,
            mention="@architect",
        ),
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "route-depth-blocker-1",
                "target_address": "@review",
                "content": _complete_handoff_content(),
                "reply_to_inbox_item_id": source_item.id,
            },
        )
    )

    replied = inbox_store.get(source_item.id)
    assert replied.status == "read"
    assert replied.responded_message_id == payload["message"]["id"]
    assert payload["message"]["mentions"] == []
    assert payload["natural_route"]["status"] == "blocked"
    assert payload["natural_route"]["blocker_reason"] == (
        "natural_route_max_depth_exceeded"
    )
    assert payload["natural_route"]["depth"] == DEFAULT_NATURAL_ROUTE_MAX_DEPTH + 1
    assert payload["inbox_items"][0]["target_participant_id"] == sender.participant_id
    assert payload["inbox_items"][0]["item_type"] == "natural_route_blocker"
    blocker_payload = payload["inbox_items"][0]["payload"]
    assert blocker_payload["blocks_dispatch"] is True
    assert blocker_payload["blocker_kind"] == "natural_route_max_depth_exceeded"
    assert blocker_payload["target_participant_id"] == target.participant_id
    assert blocker_payload["attempted_depth"] == DEFAULT_NATURAL_ROUTE_MAX_DEPTH + 1
    assert blocker_payload["max_depth"] == DEFAULT_NATURAL_ROUTE_MAX_DEPTH
    assert inbox_store.list_for_participant(
        conversation_id=conv.id,
        participant_id=target.participant_id,
    ) == []


def test_chat_mention_current_inbox_incomplete_handoff_creates_blocker(
    tmp_path: Path,
) -> None:
    chat, conv, sender, session = _registered_participant(tmp_path)
    execute = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    source = chat.add_message(conv.id, "Human", "human", "@architect hand off")
    inbox_store = ChatInboxStore(tmp_path / "chat.db")
    source_item = inbox_store.create_item(
        conversation_id=conv.id,
        target_participant_id=sender.participant_id,
        target_role=sender.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": source.content},
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "handoff-blocker-1",
                "target_address": "@execute",
                "content": "Please inspect the implementation risk.",
                "reply_to_inbox_item_id": source_item.id,
            },
        )
    )

    replied = inbox_store.get(source_item.id)
    assert replied.status == "read"
    assert replied.responded_message_id == payload["message"]["id"]
    assert payload["message"]["mentions"] == []
    assert payload["natural_route"]["status"] == "blocked"
    assert payload["natural_route"]["blocker_reason"] == "missing_handoff_fields"
    assert payload["handoff_assessment"]["missing_fields"] == [
        "what",
        "why",
        "tradeoffs",
        "open_questions",
        "next_action",
        "evidence_refs",
    ]
    assert payload["inbox_items"][0]["target_participant_id"] == sender.participant_id
    assert payload["inbox_items"][0]["item_type"] == "natural_handoff_blocker"
    assert payload["inbox_items"][0]["payload"]["blocks_dispatch"] is True
    assert payload["inbox_items"][0]["payload"]["target_participant_id"] == (
        execute.participant_id
    )
    assert inbox_store.list_for_participant(
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    ) == []


def test_chat_mention_resolves_participant_id_with_conversation_scope(
    tmp_path: Path,
) -> None:
    _chat, conv, sender, session = _registered_participant(tmp_path)
    other_chat = ChatStore(tmp_path / "chat.db")
    other_conv = other_chat.create_conversation("Other")
    other_target = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=other_conv.id,
        role="review",
        display_name="Review Other",
        cli_kind="codex",
        model="gpt-5.5",
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "cross-conv-id-1",
                "target_address": f"@participant:{other_target.participant_id}",
                "content": "please inspect",
            },
        )
    )

    assert payload["error"] == {
        "code": "unknown_target",
        "message": f"@participant:{other_target.participant_id}",
    }
    assert ChatInboxStore(tmp_path / "chat.db").list_by_conversation(conv.id) == []


def test_chat_mention_returns_structured_ambiguous_target_errors(
    tmp_path: Path,
) -> None:
    _chat, conv, sender, session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    for role in ("review-primary", "review-backup"):
        participants.add(
            conversation_id=conv.id,
            role=role,
            display_name="Review GOD",
            cli_kind="codex",
            model="gpt-5.5",
        )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": sender.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": "ambiguous-route-1",
                "target_address": "@Review GOD",
                "content": "please inspect",
            },
        )
    )

    assert payload["error"] == {
        "code": "ambiguous_target",
        "message": "@Review GOD",
    }
    assert ChatInboxStore(tmp_path / "chat.db").list_by_conversation(conv.id) == []


def test_chat_dispatch_returns_structured_argument_errors(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    payload = json.loads(_mcp_call(client, "chat_read_inbox", {}))

    assert payload["error"]["code"] == "invalid_arguments"


def test_mcp_collaboration_tools_support_veto_and_dispatch_gate(
    tmp_path: Path,
) -> None:
    chat, conv, architect, architect_session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    review = participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    review_session = GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role="review",
        agent_name="Review GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{review.participant_id}",
        session_inbox_id=f"inbox-{review.participant_id}",
        conversation_id=conv.id,
        participant_id=review.participant_id,
    )
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role="execute",
        agent_name="Execute GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{execute.participant_id}",
        session_inbox_id=f"inbox-{execute.participant_id}",
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )
    client = TestClient(create_app(tmp_path))

    created = json.loads(
        _mcp_call(
            client,
            "chat_create_collaboration_request",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "client_request_id": "collab-1",
                "goal": "Harden TUI discussion surface",
                "targets": ["review", "execute"],
                "callback_target": "architect",
                "question": "Review dispatch risks before execution.",
                "context_refs": ["message:intake"],
                "idempotency_key": "v14-mcp-collab",
                "timeout_s": 480,
            },
        )
    )
    replay = json.loads(
        _mcp_call(
            client,
            "chat_create_collaboration_request",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "client_request_id": "collab-1-replay",
                "goal": "Harden TUI discussion surface",
                "targets": ["review", "execute"],
                "callback_target": "architect",
                "question": "Review dispatch risks before execution.",
                "context_refs": [],
                "idempotency_key": "v14-mcp-collab",
                "timeout_s": 480,
            },
        )
    )

    run_id = created["run"]["run_id"]
    assert replay["run"]["run_id"] == run_id
    assert created["run"]["status"] == "running"
    assert created["run"]["targets"] == ["@review", "@execute"]

    response = json.loads(
        _mcp_call(
            client,
            "chat_record_collaboration_response",
            {
                "conversation_id": conv.id,
                "participant_id": review.participant_id,
                "god_session_id": review_session.god_session_id,
                "run_id": run_id,
                "content": "Block dispatch until blockers are visible in the TUI.",
                "status": "received",
            },
        )
    )
    assert response["run"]["status"] == "partial"
    assert response["run"]["responses"][0]["target"] == "@review"

    blocker = json.loads(
        _mcp_call(
            client,
            "chat_raise_collaboration_blocker",
            {
                "conversation_id": conv.id,
                "participant_id": review.participant_id,
                "god_session_id": review_session.god_session_id,
                "run_id": run_id,
                "severity": "veto",
                "reason": "Dispatch state is not visible to the operator.",
                "affected_ref": "tui:dispatch",
                "suggested_fix": "Expose dispatch and blocker state before dispatch.",
                "blocks_dispatch": True,
            },
        )
    )
    assert blocker["blocker"]["active"] is True
    assert blocker["blocker"]["blocks_dispatch"] is True

    blocked_gate = json.loads(
        _mcp_call(
            client,
            "chat_evaluate_dispatch_gate",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "run_id": run_id,
                "proposal_ref": "proposal:feature-plan",
                "artifact_ref": "artifact:lane-graph",
                "execute_confirmed": True,
                "policy_allows_real_provider": True,
            },
        )
    )
    assert blocked_gate["decision"] == "blocked_active_veto"

    resolved = json.loads(
        _mcp_call(
            client,
            "chat_resolve_collaboration_blocker",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "blocker_id": blocker["blocker"]["blocker_id"],
                "resolution_evidence": "inspector:/discussion-and-blockers-visible",
            },
        )
    )
    assert resolved["blocker"]["active"] is False

    allowed_gate = json.loads(
        _mcp_call(
            client,
            "chat_evaluate_dispatch_gate",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "run_id": run_id,
                "proposal_ref": "proposal:feature-plan",
                "artifact_ref": "artifact:lane-graph",
                "execute_confirmed": True,
                "policy_allows_real_provider": True,
            },
        )
    )
    assert allowed_gate["decision"] == "allowed"
    stored = ChatCollaborationStore(tmp_path / "chat.db").get_run(run_id)
    assert stored.responses[0].content.startswith("Block dispatch")
    assert stored.blockers[0].resolution_evidence == (
        "inspector:/discussion-and-blockers-visible"
    )


def test_mcp_collaboration_response_accepts_address_target(
    tmp_path: Path,
) -> None:
    _chat, conv, architect, architect_session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    execute_session = GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role="execute",
        agent_name="Execute GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{execute.participant_id}",
        session_inbox_id=f"inbox-{execute.participant_id}",
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )
    client = TestClient(create_app(tmp_path))

    created = json.loads(
        _mcp_call(
            client,
            "chat_create_collaboration_request",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "client_request_id": "collab-address-target",
                "goal": "Confirm executable scope.",
                "targets": ["@execute"],
                "callback_target": "@architect",
                "question": "Return an execute feasibility verdict.",
                "context_refs": ["message:intake"],
                "timeout_s": 480,
            },
        )
    )

    response = json.loads(
        _mcp_call(
            client,
            "chat_record_collaboration_response",
            {
                "conversation_id": conv.id,
                "participant_id": execute.participant_id,
                "god_session_id": execute_session.god_session_id,
                "run_id": created["run"]["run_id"],
                "content": json.dumps(
                    {
                        "type": "execute_feasibility_verdict",
                        "status": "executable",
                        "execution_performed": False,
                        "summary": "Executable as one lane.",
                        "evidence_refs": ["message:intake"],
                    }
                ),
                "status": "received",
            },
        )
    )

    assert response["run"]["status"] == "done"
    assert response["run"]["responses"][0]["target"] == "@execute"
    assert response["callback"]["inbox_items"][0]["item_type"] == (
        "collaboration_callback"
    )

    inbox = ChatInboxStore(tmp_path / "chat.db").list_for_participant(
        conversation_id=conv.id,
        participant_id=architect.participant_id,
    )
    callback_items = [
        item for item in inbox if item.item_type == "collaboration_callback"
    ]
    assert len(callback_items) == 1
    callback = callback_items[0]
    assert callback.target_address == "@architect"
    assert callback.payload["collaboration_run_id"] == created["run"]["run_id"]
    assert callback.payload["collaboration_status"] == "done"
    assert callback.payload["trigger_mode"] == "collaboration_done_callback"
    assert callback.payload["responses"][0]["target"] == "@execute"


def test_mcp_execute_collaboration_response_rejects_freeform_text(
    tmp_path: Path,
) -> None:
    _chat, conv, architect, architect_session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    execute_session = GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role="execute",
        agent_name="Execute GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{execute.participant_id}",
        session_inbox_id=f"inbox-{execute.participant_id}",
        conversation_id=conv.id,
        participant_id=execute.participant_id,
    )
    client = TestClient(create_app(tmp_path))

    created = json.loads(
        _mcp_call(
            client,
            "chat_create_collaboration_request",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": architect_session.god_session_id,
                "client_request_id": "execute-freeform-rejected",
                "goal": "Confirm executable scope.",
                "targets": ["execute"],
                "callback_target": "architect",
                "question": "Return an execute feasibility verdict.",
                "context_refs": ["message:intake"],
                "timeout_s": 480,
            },
        )
    )

    response = json.loads(
        _mcp_call(
            client,
            "chat_record_collaboration_response",
            {
                "conversation_id": conv.id,
                "participant_id": execute.participant_id,
                "god_session_id": execute_session.god_session_id,
                "run_id": created["run"]["run_id"],
                "content": "Executable as one lane.",
                "status": "received",
            },
        )
    )

    assert response["error"]["code"] == "execute_collaboration_response_invalid"
    stored = ChatCollaborationStore(tmp_path / "chat.db").get_run(
        created["run"]["run_id"]
    )
    assert stored.responses == []


def test_mcp_collaboration_tools_reject_spoofed_session_identity(
    tmp_path: Path,
) -> None:
    _chat, conv, _architect, architect_session = _registered_participant(tmp_path)
    review = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    client = TestClient(create_app(tmp_path))

    payload = json.loads(
        _mcp_call(
            client,
            "chat_create_collaboration_request",
            {
                "conversation_id": conv.id,
                "participant_id": review.participant_id,
                "god_session_id": architect_session.god_session_id,
                "client_request_id": "spoofed-collab-1",
                "goal": "Spoof collaboration identity",
                "targets": ["execute"],
                "callback_target": "review",
                "question": "This must not be accepted.",
                "timeout_s": 480,
            },
        )
    )

    assert payload["error"] == {
        "code": "session_participant_mismatch",
        "message": architect_session.god_session_id,
    }
    assert ChatCollaborationStore(tmp_path / "chat.db").list_runs(conv.id) == []
