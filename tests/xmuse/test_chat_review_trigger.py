from __future__ import annotations

import json

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.review_trigger_verdicts import build_review_trigger_verdict_envelope
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
    assert "envelope.type=review_trigger_verdict" in review_items[0].payload["content"]


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
    content = review_items[0].payload["content"]
    assert "Collaboration authority:" in content
    assert f"collaboration:{run.run_id}: status=done" in content
    assert "type=execute_feasibility_verdict" in content
    assert "review_trigger_verdict" in content


def test_collaboration_proposal_approval_consumes_review_trigger_verdict(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        intake_message_id,
        proposal,
    ) = _dispatchable_proposal_with_review_trigger(tmp_path)
    review_item = _review_inbox_items(tmp_path, conversation_id)[0]

    reply = service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="review-dispatch-allowed",
        content="The collaboration evidence is present and the lane is bounded.",
        envelope=_review_verdict_envelope(
            review_item=review_item,
            proposal=proposal,
            decision="dispatch_allowed",
            summary="The collaboration evidence is present and the lane is bounded.",
        ),
        reply_to_inbox_item_id=review_item.id,
    )

    updated_item = ChatInboxStore(tmp_path / "chat.db").get(review_item.id)
    assert updated_item.status == "read"
    assert updated_item.responded_message_id == reply["message"]["id"]
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(
        intake_message_id
    )
    assert spine.status is AcceptanceSpineStatus.REVIEW_CLEARED
    assert spine.review_or_execute_verdict_ref == (
        f"review_trigger_verdict:{reply['message']['id']}"
    )

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Approve after review verdict",
        },
    )

    assert response.status_code == 200, response.text
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(
        intake_message_id
    )
    assert spine.status is AcceptanceSpineStatus.DISPATCHED
    assert spine.review_or_execute_verdict_ref == f"resolution:{response.json()['id']}"


def test_collaboration_proposal_approval_blocks_review_trigger_blocker(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        intake_message_id,
        proposal,
    ) = _dispatchable_proposal_with_review_trigger(tmp_path)
    review_item = _review_inbox_items(tmp_path, conversation_id)[0]

    reply = service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="review-blocks-dispatch",
        content="Blocking reason: missing concrete verification gate.",
        envelope=_review_verdict_envelope(
            review_item=review_item,
            proposal=proposal,
            decision="blocked",
            summary="Missing concrete verification gate.",
        ),
        reply_to_inbox_item_id=review_item.id,
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(
        intake_message_id
    )
    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.blocked_reason == "proposal_review_blocked"
    assert spine.review_or_execute_verdict_ref == (
        f"review_trigger_verdict:{reply['message']['id']}"
    )

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Blocked review cannot approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_blocked"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_collaboration_proposal_approval_rejects_stdout_only_review_verdict(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        intake_message_id,
        proposal,
    ) = _dispatchable_proposal_with_review_trigger(tmp_path)
    review_item = _review_inbox_items(tmp_path, conversation_id)[0]

    reply = service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="review-stdout-only-verdict",
        content=(
            "REVIEW_VERDICT: dispatch_allowed\n"
            "This is only message text/stdout and has no durable verdict envelope."
        ),
        reply_to_inbox_item_id=review_item.id,
    )

    updated_item = ChatInboxStore(tmp_path / "chat.db").get(review_item.id)
    assert updated_item.status == "read"
    assert updated_item.responded_message_id == reply["message"]["id"]
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(
        intake_message_id
    )
    assert spine.status is AcceptanceSpineStatus.REVIEW_PENDING
    assert spine.review_or_execute_verdict_ref is None

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Stdout-only review verdict must not approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_missing"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_collaboration_proposal_approval_rejects_mismatched_review_verdict(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        intake_message_id,
        proposal,
    ) = _dispatchable_proposal_with_review_trigger(tmp_path)
    review_item = _review_inbox_items(tmp_path, conversation_id)[0]
    envelope = _review_verdict_envelope(
        review_item=review_item,
        proposal=proposal,
        decision="dispatch_allowed",
        summary="Looks dispatchable but cites the wrong inbox item.",
    )
    envelope["review_trigger_inbox_id"] = "inbox-stale"

    service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="review-mismatched-verdict",
        content="Looks dispatchable.",
        envelope=envelope,
        reply_to_inbox_item_id=review_item.id,
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(
        intake_message_id
    )
    assert spine.status is AcceptanceSpineStatus.REVIEW_PENDING
    assert spine.review_or_execute_verdict_ref is None
    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Mismatched review verdict must not approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_missing"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_collaboration_proposal_approval_rejects_malformed_review_verdict(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        intake_message_id,
        proposal,
    ) = _dispatchable_proposal_with_review_trigger(tmp_path)
    review_item = _review_inbox_items(tmp_path, conversation_id)[0]
    envelope = _review_verdict_envelope(
        review_item=review_item,
        proposal=proposal,
        decision="dispatch_allowed",
        summary="Looks dispatchable but has no evidence refs.",
    )
    envelope["evidence_refs"] = []

    service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="review-malformed-verdict",
        content="Looks dispatchable.",
        envelope=envelope,
        reply_to_inbox_item_id=review_item.id,
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(
        intake_message_id
    )
    assert spine.status is AcceptanceSpineStatus.REVIEW_PENDING
    assert spine.review_or_execute_verdict_ref is None
    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Malformed review verdict must not approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_missing"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


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


def _review_verdict_envelope(
    *,
    review_item,
    proposal,
    decision: str,
    summary: str,
):
    return build_review_trigger_verdict_envelope(
        review_trigger_inbox_id=review_item.id,
        source_message_id=review_item.source_message_id,
        proposal_id=proposal["proposal"]["id"],
        decision=decision,
        summary=summary,
        evidence_refs=[
            f"inbox:{review_item.id}",
            f"proposal:{proposal['proposal']['id']}",
        ],
    )


def _dispatchable_proposal_with_review_trigger(tmp_path):
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Review Verdict Approval")
    conversation_id = created["conversation"]["id"]
    participants = {
        participant["role"]: participant["participant_id"]
        for participant in created["participants"]
    }
    sessions = {
        session["role"]: session["god_session_id"]
        for session in created["participant_sessions"]
    }
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="@architect propose the smallest dispatchable lane.",
        client_request_id="req-review-verdict-intake",
    )
    architect_inbox = [
        item
        for item in ChatInboxStore(tmp_path / "chat.db").list_by_conversation(
            conversation_id,
            include_terminal=True,
        )
        if item.target_role == "architect"
    ][0]
    collaboration = ChatCollaborationStore(tmp_path / "chat.db")
    run = collaboration.create_request(
        conversation_id=conversation_id,
        goal="Approve only after review verdict",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm this lane can execute.",
        context_refs=[],
        idempotency_key="review-verdict-approval",
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
                "evidence_refs": ["collaboration:review-verdict-approval"],
            }
        ),
        response_status="received",
    )
    proposal = service.emit_proposal(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["architect"],
        god_session_id=sessions["architect"],
        client_request_id="req-review-verdict-proposal",
        summary="Approval must consume a review trigger verdict",
        lanes=[
            {
                "feature_id": "feature-review-verdict-approval",
                "prompt": "Require review trigger verdict before approval.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=[f"intake_message:{intake.message.id}", f"collaboration:{run.run_id}"],
        reply_to_inbox_item_id=architect_inbox.id,
    )
    return (
        service,
        conversation_id,
        participants,
        sessions,
        intake.message.id,
        proposal,
    )
