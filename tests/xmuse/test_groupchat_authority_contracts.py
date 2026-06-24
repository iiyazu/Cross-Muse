from pathlib import Path

import pytest

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import ChatStreamStore


def test_stream_text_never_closes_inbox(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    conversation = service.create_conversation(title="Stream authority")
    result = service.post_human_message(
        conversation_id=conversation["conversation"]["id"],
        author="human",
        content="Please turn this into a plan.",
        client_request_id="authority-stream-intake",
    )
    inbox_item = result.inbox_items[0]
    stream_store = ChatStreamStore(db)

    stream = stream_store.start_or_reset(
        conversation_id=inbox_item.conversation_id,
        author="Architect GOD",
        role="assistant",
        request_id="authority-stream",
        source_inbox_item_id=inbox_item.id,
    )
    stream_store.append_delta(stream.id, "I can help with that.")
    stream_store.finish(stream.id, status="done")

    reloaded = ChatInboxStore(db).get(inbox_item.id)
    assert reloaded.status == "unread"
    assert reloaded.responded_message_id is None


def test_chat_note_does_not_create_goalrun_or_peer_inbox(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    conversation = service.create_conversation(title="Chat note authority")
    conversation_id = conversation["conversation"]["id"]

    result = service.post_human_message(
        conversation_id=conversation_id,
        author="human",
        content="Document `@architect` literally in the example.",
        client_request_id="authority-chat-note",
    )

    assert result.message.envelope_json["intake_kind"] == "chat_note"
    assert result.inbox_items == []
    assert ChatInboxStore(db).list_by_conversation(conversation_id) == []
    assert AcceptanceSpineStore(db).list_by_conversation(conversation_id) == []


def test_direct_handoff_routes_peer_inbox_without_goalrun(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    conversation = service.create_conversation(title="Direct handoff authority")
    conversation_id = conversation["conversation"]["id"]

    result = service.post_human_message(
        conversation_id=conversation_id,
        author="human",
        content="@review please inspect this proposal.",
        client_request_id="authority-direct-handoff",
    )

    assert result.message.envelope_json["intake_kind"] == "direct_handoff"
    assert [item.target_role for item in result.inbox_items] == ["review"]
    assert [item.item_type for item in result.inbox_items] == ["mention"]
    assert ChatInboxStore(db).list_by_conversation(conversation_id) == result.inbox_items
    assert AcceptanceSpineStore(db).list_by_conversation(conversation_id) == []


def test_stdout_reply_cannot_mark_dispatch_dispatched(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    queue = ChatDispatchQueueStore(db)
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id="conv-authority",
        proposal_id="proposal-authority",
        resolution_id="resolution-authority",
        collaboration_run_id=None,
        artifact_ref="artifact:lane_graph",
    )
    claimed = queue.claim_next_auto_dispatch(
        conversation_id="conv-authority",
        claimed_by="dispatch-authority-test",
    )

    assert claimed is not None
    with pytest.raises(ValueError, match="mcp_writeback"):
        queue.mark_dispatched(
            entry.entry_id,
            provider_run_ref="stdout:provider-claimed-success",
            dispatch_evidence="stdout:plain-text-ack",
        )

    reloaded = queue.get(entry.entry_id)
    assert reloaded.status == "processing"
    assert reloaded.provider_run_ref is None
    assert reloaded.dispatch_evidence is None


def test_manual_gap_and_arbitrary_github_ref_cannot_render_spine_accepted(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    conversation = service.create_conversation(title="GitHub authority")
    conversation_id = conversation["conversation"]["id"]
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="human",
        content="Make this closure path auditable.",
        client_request_id="authority-github-intake",
    )
    proposal = ChatStore(db).create_proposal(
        conversation_id=conversation_id,
        author="architect",
        proposal_type="lane_graph",
        content='{"summary":"authority proposal","lanes":[]}',
        references=[f"intake_message:{intake.message.id}"],
    )
    resolution = ChatStore(db).approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve authority proposal.",
        content={"type": "lane_graph", "lanes": []},
    )
    spine_store = AcceptanceSpineStore(db)
    review_ref = "review_plane.json#verdict=authority-verdict"
    final_action_ref = "final_actions.json#hold=authority-hold"
    spine_store.attach_review_verdict_for_resolution(
        resolution_id=resolution.id,
        review_verdict_ref=review_ref,
    )
    spine_store.attach_final_action_for_review_verdict(
        review_verdict_ref=review_ref,
        final_action_ref=final_action_ref,
        manual_gaps=["github_gate_unverified"],
    )

    resolved = spine_store.resolve_final_action(
        final_action_ref=final_action_ref,
        status="approved",
        github_gate_evidence_ref="github:pr:42#checks=local-copy",
    )

    assert resolved is not None
    assert resolved.status is AcceptanceSpineStatus.BLOCKED
    assert resolved.github_gate_evidence_ref is None
    assert resolved.manual_gaps == ["github_gate_unverified"]
    assert resolved.blocked_reason == "github_gate_unverified"
