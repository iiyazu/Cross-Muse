from __future__ import annotations

from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore


def test_lane_graph_review_trigger_includes_readable_proposal_content(tmp_path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Proposal review")
    participants = ParticipantStore(tmp_path / "chat.db")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    review = participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )

    result = PeerChatService(tmp_path / "chat.db").emit_proposal_without_session_for_test(
        conversation_id=conv.id,
        participant_id=architect.participant_id,
        client_request_id="proposal-review-content",
        summary="Add peer chat",
        lanes=[
            {
                "feature_id": "lane-peer-chat",
                "prompt": "Implement peer chat",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=["memory://conversation/conv/messages/msg_1"],
        resolution_content=None,
    )

    review_triggers = [
        item
        for item in ChatInboxStore(tmp_path / "chat.db").list_by_conversation(conv.id)
        if item.item_type == "review_trigger"
    ]

    assert len(review_triggers) == 1
    trigger = review_triggers[0]
    assert trigger.target_participant_id == review.participant_id
    assert trigger.source_message_id == result["message"]["id"]
    assert trigger.payload["reviewable_type"] == "lane_graph"
    assert trigger.payload["source_message_id"] == result["message"]["id"]
    assert "Add peer chat" in trigger.payload["content"]
    assert "lane-peer-chat" in trigger.payload["content"]
    assert "memory://conversation/conv/messages/msg_1" in trigger.payload["content"]
