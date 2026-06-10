from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app as create_chat_app
from xmuse.mcp_server import create_app as create_mcp_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_scheduler import PeerChatScheduler
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore


class FakeGodLayer:
    def __init__(self, registry_path: Path) -> None:
        self._registry = GodSessionRegistry(registry_path)
        self.ensured = []
        self.sent = []

    async def ensure_conversation_session(self, **kwargs):
        self.ensured.append(kwargs)
        participant_id = kwargs["participant_id"]
        conversation_id = kwargs["conversation_id"]
        try:
            return self._registry.find_by_conversation_participant(
                conversation_id,
                participant_id,
            )
        except KeyError:
            return self._registry.create(
                role=kwargs["role"],
                agent_name=kwargs["agent"].name,
                runtime=kwargs["agent"].runtime.value,
                session_address=f"xmuse://{conversation_id}/{participant_id}",
                session_inbox_id=f"inbox-{participant_id}",
                conversation_id=conversation_id,
                participant_id=participant_id,
            )

    async def send_message(self, god_session_id, message_type, prompt, context, request_id=None):
        self.sent.append((god_session_id, message_type, prompt, context, request_id))

    async def receive_message(self, god_session_id):
        return type("Message", (), {"type": "result", "status": "success"})()


def _conv_with_architect(db: Path, title: str):
    chat = ChatStore(db)
    conv = chat.create_conversation(title)
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    return conv, participant


def test_two_conversations_with_same_role_get_separate_inbox_items(tmp_path):
    db = tmp_path / "chat.db"
    conv_a, arch_a = _conv_with_architect(db, "A")
    conv_b, arch_b = _conv_with_architect(db, "B")
    service = PeerChatService(db)

    result_a = service.post_human_message(
        conversation_id=conv_a.id,
        author="Human",
        content="@architect handle A",
        client_request_id="a-1",
    )
    result_b = service.post_human_message(
        conversation_id=conv_b.id,
        author="Human",
        content="@architect handle B",
        client_request_id="b-1",
    )

    assert result_a.inbox_items[0].target_participant_id == arch_a.participant_id
    assert result_b.inbox_items[0].target_participant_id == arch_b.participant_id
    assert result_a.inbox_items[0].conversation_id != result_b.inbox_items[0].conversation_id


def test_inbox_read_is_scoped_to_participant(tmp_path):
    db = tmp_path / "chat.db"
    conv, architect = _conv_with_architect(db, "A")
    service = PeerChatService(db)
    service.post_human_message(
        conversation_id=conv.id,
        author="Human",
        content="@architect handle A",
        client_request_id="a-1",
    )
    inbox = ChatInboxStore(db)

    assert (
        len(
            inbox.list_for_participant(
                conversation_id=conv.id,
                participant_id=architect.participant_id,
            )
        )
        == 1
    )
    assert (
        inbox.list_for_participant(
            conversation_id=conv.id,
            participant_id="part_other",
        )
        == []
    )


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
    return response.json()["result"]["structuredContent"]


@pytest.mark.asyncio
async def test_default_group_chat_flow_reaches_god_reply_proposal_and_keeps_roles_isolated(
    tmp_path: Path,
) -> None:
    chat_client = TestClient(create_chat_app(tmp_path))
    first = chat_client.post("/api/chat/conversations", json={"title": "Mission A"}).json()
    second = chat_client.post("/api/chat/conversations", json={"title": "Mission B"}).json()
    first_architect = next(
        participant for participant in first["participants"] if participant["role"] == "architect"
    )
    second_architect = next(
        participant for participant in second["participants"] if participant["role"] == "architect"
    )

    assert [participant["role"] for participant in first["participants"]] == [
        "architect",
        "review",
        "execute",
    ]

    human_message = chat_client.post(
        f"/api/chat/conversations/{first['id']}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "@architect draft a lane proposal from this chat",
            "client_request_id": "human-mention-1",
        },
    ).json()

    inbox = ChatInboxStore(tmp_path / "chat.db")
    durable_items = inbox.list_for_participant(
        conversation_id=first["id"],
        participant_id=first_architect["participant_id"],
    )
    assert human_message["mentions"] == ["@architect"]
    assert human_message["inbox_items"][0]["conversation_id"] == first["id"]
    assert [item.id for item in durable_items] == [human_message["inbox_items"][0]["id"]]
    assert (
        inbox.list_for_participant(
            conversation_id=second["id"],
            participant_id=second_architect["participant_id"],
        )
        == []
    )

    layer = FakeGodLayer(tmp_path / "god_sessions.json")
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-e2e",
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 0
    assert outcome.failed == 1
    assert layer.ensured[0]["conversation_id"] == first["id"]
    assert layer.ensured[0]["participant_id"] == first_architect["participant_id"]
    assert layer.ensured[0]["agent"].runtime is AgentRuntime.CODEX

    session_id = layer.sent[0][0]
    mcp_client = TestClient(create_mcp_app(tmp_path))
    read_payload = _mcp_call(
        mcp_client,
        "chat_read_inbox",
        {
            "conversation_id": first["id"],
            "participant_id": first_architect["participant_id"],
            "god_session_id": session_id,
        },
    )

    assert [item["id"] for item in read_payload["inbox_items"]] == [
        human_message["inbox_items"][0]["id"]
    ]

    reply_payload = _mcp_call(
        mcp_client,
        "chat_post_message",
        {
            "conversation_id": first["id"],
            "participant_id": first_architect["participant_id"],
            "god_session_id": session_id,
            "client_request_id": "architect-reply-1",
            "content": "I can draft the proposal from this chat.",
            "reply_to_inbox_item_id": human_message["inbox_items"][0]["id"],
        },
    )
    proposal_payload = _mcp_call(
        mcp_client,
        "chat_emit_proposal",
        {
            "conversation_id": first["id"],
            "participant_id": first_architect["participant_id"],
            "god_session_id": session_id,
            "client_request_id": "architect-proposal-1",
            "summary": "Add chat-first closure audit",
            "references": [human_message["id"], reply_payload["message"]["id"]],
            "lanes": [
                {
                    "feature_id": "lane-chat-first-closure-audit",
                    "prompt": "Audit the chat-first closure flow.",
                    "depends_on": [],
                    "capabilities": ["code"],
                    "feature_group": "peer-chat",
                }
            ],
        },
    )
    messages = ChatStore(tmp_path / "chat.db").list_messages(first["id"])
    approved = chat_client.post(
        f"/api/chat/proposals/{proposal_payload['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Add chat-first closure audit",
        },
    )

    assert approved.status_code == 200
    assert proposal_payload["message"]["envelope_type"] == "proposal"
    assert proposal_payload["message"]["envelope_json"]["proposal_id"] == (
        proposal_payload["proposal"]["id"]
    )
    assert messages[-1].envelope_type == "proposal"
    assert approved.json()["conversation_id"] == first["id"]
    assert approved.json()["content"]["lanes"][0]["feature_id"] == (
        "lane-chat-first-closure-audit"
    )

    timeline = chat_client.get(f"/api/chat/conversations/{first['id']}/messages")

    assert timeline.status_code == 200
    payload = timeline.json()
    assert [item["kind"] for item in payload["items"]] == [
        "message",
        "message",
        "card",
        "card",
        "card",
        "card",
    ]
    assert [message["content"] for message in payload["messages"]] == [
        "@architect draft a lane proposal from this chat",
        "I can draft the proposal from this chat.",
    ]
    proposal_card = next(card for card in payload["cards"] if card["card_type"] == "proposal")
    assert proposal_card["source_id"] == proposal_payload["proposal"]["id"]
    assert proposal_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first['id']}"
        f"#proposal-{proposal_payload['proposal']['id']}"
    )
    assert proposal_card["api_href"] == f"/api/chat/proposals/{proposal_payload['proposal']['id']}"
    assert proposal_card["counts"] == {"references": 2, "lanes": 1}
    assert "lanes" not in proposal_card
    worklist_card = next(
        card for card in payload["cards"] if card["card_type"] == "worklist_summary"
    )
    assert worklist_card["counts"]["ready_lanes"] == 1
    assert worklist_card["counts"]["unread_inbox"] == 0
    assert worklist_card["counts"]["claimed_inbox"] == 0
    assert worklist_card["href"] == f"/dashboard/peer-chat/conversations/{first['id']}#worklist"
    assert [item["kind"] for item in payload["items"][:2]] == ["message", "message"]
