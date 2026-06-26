from __future__ import annotations

import json

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore


def test_lane_graph_proposal_auto_triggers_single_review_inbox_item(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Lane Graph Review Trigger")
    conversation_id = created["conversation"]["id"]
    architect_id = _participant_id_for_role(service, conversation_id, "architect")

    service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-review-trigger-lane-graph",
        summary="Add graph-owned review flow",
        lanes=[
            {
                "feature_id": "feature-review-trigger",
                "prompt": "Implement automatic review trigger after proposal creation.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
    )

    review_items = _review_inbox_items(tmp_path, conversation_id)

    assert len(review_items) == 1
    assert review_items[0].item_type == "review_trigger"
    assert review_items[0].target_role == "review"
    assert review_items[0].payload["reviewable_type"] == "lane_graph"


def test_blueprint_proposal_auto_triggers_single_review_inbox_item(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Blueprint Review Trigger")
    conversation_id = created["conversation"]["id"]
    architect_id = _participant_id_for_role(service, conversation_id, "architect")

    service.emit_blueprint_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-review-trigger-blueprint",
        title="Blueprint for review trigger protocol",
        body="Define when review should automatically enter the group chat.",
        acceptance_criteria=["Review enters only after a reviewable object exists."],
    )

    review_items = _review_inbox_items(tmp_path, conversation_id)

    assert len(review_items) == 1
    assert review_items[0].item_type == "review_trigger"
    assert review_items[0].target_role == "review"
    assert review_items[0].payload["reviewable_type"] == "mission_blueprint"


def test_non_reviewable_human_message_does_not_auto_trigger_review(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Message Only")
    conversation_id = created["conversation"]["id"]

    service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="Please think about this request.",
        client_request_id="req-non-reviewable-message",
    )

    review_items = _review_inbox_items(tmp_path, conversation_id)

    assert review_items == []


def test_review_trigger_replay_is_duplicate_safe(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Replay Review Trigger")
    conversation_id = created["conversation"]["id"]
    architect_id = _participant_id_for_role(service, conversation_id, "architect")

    first = service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-review-trigger-replay",
        summary="Replay-safe review trigger",
        lanes=[
            {
                "feature_id": "feature-replay-safe-review",
                "prompt": "Ensure review inbox creation is idempotent.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
    )
    second = service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-review-trigger-replay",
        summary="Replay-safe review trigger",
        lanes=[
            {
                "feature_id": "feature-replay-safe-review",
                "prompt": "Ensure review inbox creation is idempotent.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
    )

    review_items = _review_inbox_items(tmp_path, conversation_id)

    assert first["message"]["id"] == second["message"]["id"]
    assert len(review_items) == 1
    assert review_items[0].item_type == "review_trigger"


def test_approval_marks_related_review_trigger_read(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Approval Clears Review Trigger")
    conversation_id = created["conversation"]["id"]
    architect_id = _participant_id_for_role(service, conversation_id, "architect")

    proposal = service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-review-trigger-approval",
        summary="Review trigger cleared by approval",
        lanes=[
            {
                "feature_id": "feature-approval-clears-review",
                "prompt": "Clear obsolete review trigger on human approval.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
    )

    assert [item.status for item in _review_inbox_items(tmp_path, conversation_id)] == ["unread"]

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Review trigger cleared by approval",
        },
    )

    assert response.status_code == 200
    review_items = _review_inbox_items(tmp_path, conversation_id)
    assert [item.status for item in review_items] == ["read"]
    assert review_items[0].responded_message_id == proposal["message"]["id"]


def test_collaboration_proposal_approval_blocks_pending_review_trigger(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Pending Review Blocks Approval")
    conversation_id = created["conversation"]["id"]
    architect_id = _participant_id_for_role(service, conversation_id, "architect")
    collaboration = ChatCollaborationStore(tmp_path / "chat.db")
    run = collaboration.create_request(
        conversation_id=conversation_id,
        goal="Approve only after review trigger is handled",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm this lane can execute.",
        context_refs=[],
        idempotency_key="pending-review-approval",
        timeout_s=480,
    )
    collaboration.record_response(
        run.run_id,
        target="execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "execution_performed": False,
                "summary": "The lane has scoped work and enough evidence.",
                "evidence_refs": ["collaboration:pending-review-approval"],
            }
        ),
        response_status="received",
    )
    proposal = service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-pending-review-before-approval",
        summary="Approval must wait for proposal review",
        lanes=[
            {
                "feature_id": "feature-pending-review-before-approval",
                "prompt": "Do not approve before the review trigger is handled.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=[f"collaboration:{run.run_id}"],
    )

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "This approval must wait for proposal review",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_pending"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []
    review_items = _review_inbox_items(tmp_path, conversation_id)
    assert [item.status for item in review_items] == ["unread"]
    assert review_items[0].responded_message_id is None


def test_manual_review_mention_and_auto_review_trigger_do_not_conflict(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Manual And Auto Review")
    conversation_id = created["conversation"]["id"]
    architect_id = _participant_id_for_role(service, conversation_id, "architect")

    service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="@review please watch for the next structured object.",
        client_request_id="req-manual-review-mention",
    )
    service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=architect_id,
        client_request_id="req-auto-review-trigger-after-mention",
        summary="Review trigger after manual mention",
        lanes=[
            {
                "feature_id": "feature-manual-auto-review",
                "prompt": "Keep manual and automatic review trigger duplicate-safe.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
    )

    review_items = _review_inbox_items(tmp_path, conversation_id)

    assert sorted(item.item_type for item in review_items) == ["mention", "review_trigger"]


def _participant_id_for_role(
    service: PeerChatService,
    conversation_id: str,
    role: str,
) -> str:
    participants = service.list_participants(conversation_id=conversation_id)["participants"]
    for participant in participants:
        if participant["role"] == role:
            return participant["participant_id"]
    raise AssertionError(f"missing participant role: {role}")


def _review_inbox_items(tmp_path, conversation_id: str):
    return [
        item
        for item in ChatInboxStore(tmp_path / "chat.db").list_by_conversation(
            conversation_id,
            include_terminal=True,
        )
        if item.target_role == "review"
    ]
