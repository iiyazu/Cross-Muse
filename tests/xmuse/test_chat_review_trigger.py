from __future__ import annotations

import json

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.groupchat_worklist import (
    GroupchatWorklistScheduler,
    GroupchatWorklistStore,
)
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.review_trigger_verdicts import build_review_trigger_verdict_envelope
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.a2a_writeback_reconciler import A2AProviderWritebackReconciler
from xmuse_core.providers.adapters.base import ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, ProviderProfileId


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
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
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
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
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

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
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
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
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

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
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

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
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


def test_groupchat_proposal_approval_requires_review_and_critic_clearance(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        proposal,
        review_item,
    ) = _groupchat_sourced_proposal_with_review_trigger(tmp_path)

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Groupchat decision needs review and critic clearance.",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_pending"

    service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="groupchat-review-dispatch-allowed",
        content="Review clears the bounded groupchat decision.",
        envelope=_review_verdict_envelope(
            review_item=review_item,
            proposal=proposal,
            decision="dispatch_allowed",
            summary="Review clears the bounded groupchat decision.",
        ),
        reply_to_inbox_item_id=review_item.id,
    )

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Groupchat decision still needs critic clearance.",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_critic_missing"

    service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["critic"],
        god_session_id=sessions["critic"],
        client_request_id="groupchat-critic-clearance",
        content="Critic clearance: no blocking objection remains.",
        envelope=_groupchat_critic_verdict_envelope(
            proposal=proposal,
            decision="clearance",
            summary="No blocking objection remains.",
        ),
    )

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Groupchat decision has review and critic clearance.",
        },
    )

    assert response.status_code == 200, response.text


def test_groupchat_proposal_approval_blocks_critic_objection(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    (
        service,
        conversation_id,
        participants,
        sessions,
        proposal,
        review_item,
    ) = _groupchat_sourced_proposal_with_review_trigger(tmp_path)
    service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="groupchat-review-before-critic-block",
        content="Review clears dispatch shape; critic still owns objection gate.",
        envelope=_review_verdict_envelope(
            review_item=review_item,
            proposal=proposal,
            decision="dispatch_allowed",
            summary="Review clears dispatch shape; critic still owns objection gate.",
        ),
        reply_to_inbox_item_id=review_item.id,
    )
    service.post_god_message(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["critic"],
        god_session_id=sessions["critic"],
        client_request_id="groupchat-critic-blocks",
        content="Blocking objection: the proposal lacks a durable rollback boundary.",
        envelope=_groupchat_critic_verdict_envelope(
            proposal=proposal,
            decision="blocked",
            summary="The proposal lacks a durable rollback boundary.",
        ),
    )

    response = client.post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Blocked critic objection cannot approve.",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_critic_blocked"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_a2a_review_trigger_verdict_only_proposal_approval_enqueues_dispatch(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))
    (
        conversation_id,
        intake_message_id,
        proposal_id,
        verdict_message_id,
    ) = _a2a_proposal_with_review_trigger_without_collaboration(
        tmp_path,
        write_verdict=True,
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    assert spine.status is AcceptanceSpineStatus.REVIEW_CLEARED
    assert spine.review_or_execute_verdict_ref == f"review_trigger_verdict:{verdict_message_id}"

    response = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Approve after durable review-trigger verdict.",
        },
    )

    assert response.status_code == 200, response.text
    entries = ChatDispatchQueueStore(tmp_path / "chat.db").list_entries(conversation_id)
    assert len(entries) == 1
    assert entries[0].proposal_id == proposal_id
    assert entries[0].resolution_id == response.json()["id"]
    assert entries[0].collaboration_run_id is None
    assert entries[0].artifact_ref == "artifact:lane_graph"
    assert entries[0].gate_refs == [f"review_trigger_verdict:{verdict_message_id}"]
    assert response.json()["next_authority_boundary"] == {
        "required_authority": "chat.db/dispatch_queue",
        "required_action": "run_dispatch_bridge",
        "dispatch_queue_entry_available": True,
        "dispatch_queue_entry_id": entries[0].entry_id,
        "dispatch_policy": "real_provider_allowed",
        "source_refs": [
            f"proposal:{proposal_id}",
            f"review_trigger_verdict:{verdict_message_id}",
            f"resolution:{response.json()['id']}",
            f"chat_dispatch_queue:{entries[0].entry_id}",
        ],
    }
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    assert spine.status is AcceptanceSpineStatus.DISPATCHED


def test_a2a_review_trigger_pending_proposal_approval_without_collaboration_is_blocked(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))
    (
        conversation_id,
        _intake_message_id,
        proposal_id,
        _verdict_message_id,
    ) = _a2a_proposal_with_review_trigger_without_collaboration(
        tmp_path,
        write_verdict=False,
    )

    response = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
            "goal_summary": "Try approval before review verdict.",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "proposal_review_pending"
    assert ChatDispatchQueueStore(tmp_path / "chat.db").list_entries(conversation_id) == []


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


def _groupchat_critic_verdict_envelope(
    *,
    proposal,
    decision: str,
    summary: str,
):
    return {
        "schema_version": 1,
        "type": "groupchat_critic_verdict",
        "proposal_id": proposal["proposal"]["id"],
        "decision": decision,
        "summary": summary,
        "evidence_refs": [f"proposal:{proposal['proposal']['id']}"],
    }


def _groupchat_sourced_proposal_with_review_trigger(tmp_path):
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(
        title="Groupchat Critic Gate",
        preset_id="architect-review-critic",
    )
    conversation_id = created["conversation"]["id"]
    participants = {
        participant["role"]: participant["participant_id"]
        for participant in created["participants"]
    }
    sessions = {
        session["role"]: session["god_session_id"] for session in created["participant_sessions"]
    }
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="Discuss a groupchat decision and propose the next lane.",
        client_request_id="groupchat-critic-gate-intake",
    )
    worklist = GroupchatWorklistStore(tmp_path / "chat.db")
    chain = worklist.create_chain(
        conversation_id=conversation_id,
        root_message_id=intake.message.id,
    )
    route = worklist.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=intake.message.id,
        target_participant_id=participants["architect"],
        route_kind="router",
        depth=0,
    )
    linked = GroupchatWorklistScheduler(
        db_path=tmp_path / "chat.db",
        scheduler_id="groupchat-a2-test",
    ).claim_and_link_one(chain_id=chain.chain_id)
    assert linked is not None
    assert linked.inbox_item_id is not None
    proposal = service.emit_proposal(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["architect"],
        god_session_id=sessions["architect"],
        client_request_id="groupchat-critic-gate-proposal",
        summary="Groupchat proposal needs review and critic gates",
        lanes=[
            {
                "feature_id": "groupchat-a2-critic-gate",
                "prompt": "Require review verdict and critic clearance before approval.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=[f"intake_message:{intake.message.id}"],
        reply_to_inbox_item_id=linked.inbox_item_id,
    )
    assert f"groupchat_chain:{chain.chain_id}" in proposal["proposal"]["references"]
    assert f"groupchat_worklist:{route.item_id}" in proposal["proposal"]["references"]
    review_items = _review_inbox_items(tmp_path, conversation_id)
    assert len(review_items) == 1
    return (
        service,
        conversation_id,
        participants,
        sessions,
        proposal,
        review_items[0],
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
        session["role"]: session["god_session_id"] for session in created["participant_sessions"]
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


def _a2a_proposal_with_review_trigger_without_collaboration(
    tmp_path,
    *,
    write_verdict: bool,
):
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("A2A review-trigger dispatch")
    participants = ParticipantStore(db_path)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="A2A Architect",
        cli_kind="a2a",
        model="a2a-remote",
    )
    review = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="A2A Review",
        cli_kind="a2a",
        model="a2a-remote",
    )
    intake = chat.add_message(
        conversation.id,
        "Human",
        "human",
        "@architect propose the smallest reviewed lane.",
    )
    AcceptanceSpineStore(db_path).create_for_intake(
        conversation_id=conversation.id,
        intake_message_id=intake.id,
    )
    source_inbox = ChatInboxStore(db_path).create_item(
        conversation_id=conversation.id,
        target_participant_id=architect.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=intake.id,
        item_type="mention",
        payload={"content": intake.content},
    )
    result = A2AProviderWritebackReconciler(db_path).record_provider_result(
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        reply_to_inbox_item_id=source_inbox.id,
        provider_result=_a2a_proposal_result(),
    )
    proposal_id = result["proposal_writeback"]["proposal_id"]
    review_item = next(
        item
        for item in ChatInboxStore(db_path).list_by_conversation(
            conversation.id,
            include_terminal=True,
        )
        if item.item_type == "review_trigger"
    )
    verdict_message_id = None
    if write_verdict:
        verdict = A2AProviderWritebackReconciler(db_path).record_provider_result(
            conversation_id=conversation.id,
            participant_id=review.participant_id,
            reply_to_inbox_item_id=review_item.id,
            provider_result=_a2a_review_verdict_result(
                review_item=review_item,
                proposal_id=proposal_id,
            ),
        )
        verdict_message_id = verdict["message"]["id"]
    return (
        conversation.id,
        intake.id,
        proposal_id,
        verdict_message_id,
    )


def _a2a_proposal_result() -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id="req-a2a-review-only-proposal",
        provider_id=ProviderId.A2A,
        profile_id=ProviderProfileId.REMOTE,
        status=WorkerResultStatus.COMPLETED,
        evidence_refs=[
            "a2a_task:req-a2a-review-only-proposal",
            "a2a_context:review-only",
        ],
        diagnostic_payload={
            "a2a_task_id": "req-a2a-review-only-proposal",
            "a2a_context_id": "review-only",
            "a2a_state": "TASK_STATE_COMPLETED",
            "a2a_disposition": "completed",
            "a2a_terminal": True,
            "a2a_content": "A2A architect returned a structured proposal.",
            "a2a_artifacts": [{"artifact_id": "artifact-a2a-review-only", "text": "proposal"}],
            "a2a_history": [],
            "a2a_metadata": {
                "xmuse_proposal": {
                    "schema_version": 1,
                    "proposal_type": "lane_graph",
                    "summary": "A2A review-only dispatch candidate",
                    "content": {
                        "summary": "A2A review-only dispatch candidate",
                        "lanes": [
                            {
                                "feature_id": "feature-a2a-review-only-dispatch",
                                "prompt": (
                                    "Allow dispatch after A2A review-trigger verdict and approval."
                                ),
                                "depends_on": [],
                                "capabilities": ["code"],
                                "gate_profiles": ["xmuse-core"],
                            }
                        ],
                    },
                    "references": ["artifact:a2a-review-only-proposal"],
                }
            },
            "a2a_source_refs": [
                "a2a_task:req-a2a-review-only-proposal",
                "a2a_context:review-only",
            ],
            "a2a_sdk_task": {
                "id": "req-a2a-review-only-proposal",
                "status": {"state": "TASK_STATE_COMPLETED"},
            },
            "a2a_jsonrpc_id": "req-a2a-review-only-proposal",
        },
    )


def _a2a_review_verdict_result(*, review_item, proposal_id: str) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id="req-a2a-review-only-verdict",
        provider_id=ProviderId.A2A,
        profile_id=ProviderProfileId.REMOTE,
        status=WorkerResultStatus.COMPLETED,
        evidence_refs=[
            "a2a_task:req-a2a-review-only-verdict",
            "a2a_context:review-only",
        ],
        diagnostic_payload={
            "a2a_task_id": "req-a2a-review-only-verdict",
            "a2a_context_id": "review-only",
            "a2a_state": "TASK_STATE_COMPLETED",
            "a2a_disposition": "completed",
            "a2a_terminal": True,
            "a2a_content": "A2A review verdict: dispatch allowed.",
            "a2a_artifacts": [],
            "a2a_history": [],
            "a2a_metadata": {
                "xmuse_review_trigger_verdict": build_review_trigger_verdict_envelope(
                    review_trigger_inbox_id=review_item.id,
                    source_message_id=review_item.source_message_id,
                    proposal_id=proposal_id,
                    decision="dispatch_allowed",
                    summary="A2A review-trigger verdict allows dispatch.",
                    evidence_refs=[
                        f"inbox:{review_item.id}",
                        f"proposal:{proposal_id}",
                        "a2a_task:req-a2a-review-only-verdict",
                    ],
                )
            },
            "a2a_source_refs": [
                "a2a_task:req-a2a-review-only-verdict",
                "a2a_context:review-only",
            ],
            "a2a_sdk_task": {
                "id": "req-a2a-review-only-verdict",
                "status": {"state": "TASK_STATE_COMPLETED"},
            },
            "a2a_jsonrpc_id": "req-a2a-review-only-verdict",
        },
    )
