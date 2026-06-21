from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.review_plane import ReviewPlaneController
from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict


def test_human_intake_creates_durable_acceptance_spine(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="Acceptance Spine Intake")
    conversation_id = created["conversation"]["id"]

    result = service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content="Please turn this demand into an auditable closure path.",
        client_request_id="goalrun-intake",
    )

    spines = AcceptanceSpineStore(db).list_by_conversation(conversation_id)
    assert len(spines) == 1
    assert spines[0].conversation_id == conversation_id
    assert spines[0].intake_message_id == result.message.id
    assert spines[0].status is AcceptanceSpineStatus.INTAKE
    assert spines[0].proposal_id is None


def test_acceptance_spine_tracks_proposal_resolution_and_dispatch_refs(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="Acceptance Spine Flow")
    conversation_id = created["conversation"]["id"]

    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content="Create the smallest real execution proposal.",
        client_request_id="goalrun-flow-intake",
    )
    proposal = ChatStore(db).create_proposal(
        conversation_id=conversation_id,
        author="architect",
        proposal_type="lane_graph",
        content='{"summary":"small proposal","lanes":[]}',
        references=[f"intake_message:{intake.message.id}"],
    )
    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.PROPOSED
    assert spine.proposal_id == proposal.id

    resolution = ChatStore(db).approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve smallest proposal.",
        content={"type": "lane_graph", "lanes": []},
    )
    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.REVIEW_CLEARED
    assert spine.review_or_execute_verdict_ref == f"resolution:{resolution.id}"

    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id=None,
        artifact_ref="artifact:lane_graph",
    )
    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.DISPATCHED
    assert spine.dispatch_item_id == dispatch.entry_id

    claimed = ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="dispatch-test",
    )
    assert claimed is not None
    ChatDispatchQueueStore(db).mark_dispatched(
        dispatch.entry_id,
        provider_run_ref="provider:run:1",
        dispatch_evidence="mcp_writeback:dispatch-inbox",
    )

    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.DISPATCHED
    assert spine.execution_evidence_refs == [
        "provider:run:1",
        "mcp_writeback:dispatch-inbox",
    ]


def test_chat_api_reads_acceptance_spine_status(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "Acceptance Spine API"},
    )
    conversation_id = conversation.json()["id"]
    posted = client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={
            "author": "Human operator",
            "role": "human",
            "content": "Expose the durable goal run status.",
            "client_request_id": "goalrun-api-intake",
        },
    )

    response = client.get(f"/api/chat/conversations/{conversation_id}/acceptance-spines")

    assert posted.status_code == 201
    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == conversation_id
    assert payload["source_authority"] == "chat_store"
    assert payload["items"][0]["intake_message_id"] == posted.json()["id"]
    assert payload["items"][0]["status"] == "intake"


def test_acceptance_spine_tracks_review_verdict_final_action_and_github_gap(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="Acceptance Spine Review")
    conversation_id = created["conversation"]["id"]
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content="Review and hold final action for this demand.",
        client_request_id="goalrun-review-intake",
    )
    proposal = ChatStore(db).create_proposal(
        conversation_id=conversation_id,
        author="architect",
        proposal_type="lane_graph",
        content='{"summary":"review proposal","lanes":[]}',
        references=[f"intake_message:{intake.message.id}"],
    )
    resolution = ChatStore(db).approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve review proposal.",
        content={"type": "lane_graph", "lanes": []},
    )
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-spine-review",
                        "status": "gated",
                        "prompt": "Run review.",
                        "graph_id": "graph-spine-review",
                        "resolution_id": resolution.id,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    controller = ReviewPlaneController(
        lanes_path=lanes_path,
        store_path=tmp_path / "review_plane.json",
        final_actions_path=tmp_path / "final_actions.json",
        require_final_action_approval=True,
    )
    task = controller.open_review_task("lane-spine-review")

    controller.ingest_verdict(
        task.task_id,
        ReviewVerdict(
            id="verdict-spine-review",
            lane_id="lane-spine-review",
            decision=ReviewDecision.MERGE,
            summary="No findings.",
            evidence_refs=["review:evidence"],
        ),
    )

    hold = FinalActionGateStore(tmp_path / "final_actions.json").list_actions()[0]
    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.review_verdict_ref == "review_plane.json#verdict=verdict-spine-review"
    assert spine.final_action_ref == f"final_actions.json#hold={hold.id}"
    assert spine.manual_gaps == ["github_gate_unverified"]
    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.blocked_reason == "final_action_pending"
