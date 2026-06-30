from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.execution.github_ops import (
    GitHubMainCiEvidence,
    GitHubServerSideTruthEvidence,
)
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
    assert spine.execution_evidence_refs == []

    AcceptanceSpineStore(db).attach_lane_execution_for_resolution(
        resolution_id=resolution.id,
        evidence_refs=[
            "feature_lanes.json#lane=lane-spine-flow:status=executed",
            "lane_graph:graph-spine-flow",
        ],
    )

    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.EXECUTED
    assert spine.execution_evidence_refs == [
        "feature_lanes.json#lane=lane-spine-flow:status=executed",
        "lane_graph:graph-spine-flow",
    ]

    AcceptanceSpineStore(db).attach_review_verdict_for_resolution(
        resolution_id=resolution.id,
        review_verdict_ref="review_plane.json#verdict=verdict-spine-flow",
    )
    AcceptanceSpineStore(db).attach_lane_execution_for_resolution(
        resolution_id=resolution.id,
        evidence_refs=["provider_session_binding:binding-spine-flow"],
    )

    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.REVIEWED
    assert "provider_session_binding:binding-spine-flow" in spine.execution_evidence_refs


def test_dispatch_queue_preserves_gate_refs_when_legacy_enqueue_retries(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("Dispatch gate refs")
    queue = ChatDispatchQueueStore(db)

    initial = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation.id,
        proposal_id="proposal-gated",
        resolution_id="resolution-gated",
        collaboration_run_id="run-gated",
        artifact_ref="artifact:lane_graph",
        gate_refs=["collaboration:run-gated", "review_trigger_verdict:message-gated"],
    )
    retried = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation.id,
        proposal_id="proposal-gated",
        resolution_id="resolution-gated",
        collaboration_run_id="run-gated",
        artifact_ref="artifact:lane_graph",
    )

    assert retried.entry_id == initial.entry_id
    assert retried.gate_refs == [
        "collaboration:run-gated",
        "review_trigger_verdict:message-gated",
    ]


def test_acceptance_spine_filters_dispatch_ack_refs_from_execution_evidence(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="Execution evidence boundary")
    conversation_id = created["conversation"]["id"]
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content="Keep dispatch acknowledgement evidence out of execution proof.",
        client_request_id="goalrun-execution-evidence-boundary",
    )
    proposal = ChatStore(db).create_proposal(
        conversation_id=conversation_id,
        author="architect",
        proposal_type="lane_graph",
        content='{"summary":"small proposal","lanes":[]}',
        references=[f"intake_message:{intake.message.id}"],
    )
    resolution = ChatStore(db).approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve execution evidence boundary.",
        content={"type": "lane_graph", "lanes": []},
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id=None,
        artifact_ref="artifact:lane_graph",
    )

    spine = AcceptanceSpineStore(db).attach_execution_evidence_for_dispatch(
        dispatch_item_id=dispatch.entry_id,
        evidence_refs=[
            "provider:run:dispatch-ack",
            "peer_ack:execute:participant-1",
            "mcp_writeback:dispatch-inbox",
            "chat_dispatch_queue#entry=dispatch-1",
            "feature_lanes.json#lane=lane-boundary:status=executed",
            "provider_session_binding:binding-boundary",
        ],
    )

    assert spine is not None
    assert spine.execution_evidence_refs == [
        "feature_lanes.json#lane=lane-boundary:status=executed",
        "provider_session_binding:binding-boundary",
    ]

    spine = AcceptanceSpineStore(db).attach_lane_execution_for_resolution(
        resolution_id=resolution.id,
        evidence_refs=[
            "mcp_writeback:dispatch-inbox",
            "peer_ack:execute:participant-1",
            "feature_lanes.json#lane=lane-resolution:status=executed",
            "lane_graph:graph-resolution",
        ],
    )

    assert spine is not None
    assert spine.execution_evidence_refs == [
        "feature_lanes.json#lane=lane-boundary:status=executed",
        "provider_session_binding:binding-boundary",
        "feature_lanes.json#lane=lane-resolution:status=executed",
        "lane_graph:graph-resolution",
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
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    assert spine.review_verdict_ref == "review_plane.json#verdict=verdict-spine-review"
    assert spine.final_action_ref == f"final_actions.json#hold={hold.id}"
    assert spine.manual_gaps == ["github_gate_unverified"]
    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.blocked_reason == "final_action_pending"


def test_final_action_approval_without_github_evidence_keeps_spine_blocked(
    tmp_path: Path,
) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    final_action = FinalActionGateStore(tmp_path / "final_actions.json").resolve(
        hold.id,
        status="approved",
        resolved_by="human",
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    assert final_action.status == "blocked"
    assert final_action.github_gate_evidence_ref is None
    assert final_action.github_gate_gap_ref == "github_gate_unverified"
    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.github_gate_evidence_ref is None
    assert spine.manual_gaps == ["github_gate_unverified"]
    assert spine.blocked_reason == "github_gate_unverified"
    writebacks = [
        message
        for message in ChatStore(tmp_path / "chat.db").list_messages(spine.conversation_id)
        if message.envelope_type == "final_action_result"
    ]
    assert len(writebacks) == 1
    writeback = writebacks[0]
    assert "github_gate_unverified" in writeback.content
    assert writeback.envelope_json["type"] == "final_action_result"
    assert writeback.envelope_json["final_action_id"] == hold.id
    assert writeback.envelope_json["status"] == "blocked"
    assert writeback.envelope_json["github_gate_evidence_ref"] is None
    assert writeback.envelope_json["github_gate_gap_ref"] == "github_gate_unverified"
    assert writeback.envelope_json["acceptance_spine_ref"] == (
        f"chat.db:acceptance_spines#spine={spine.spine_id}"
    )
    assert writeback.envelope_json["source_refs"] == [
        f"final_actions.json#hold={hold.id}",
        f"chat.db:acceptance_spines#spine={spine.spine_id}",
        f"message:{intake_message_id}",
        f"proposal:{spine.proposal_id}",
        spine.review_or_execute_verdict_ref,
        "review_plane.json#verdict=verdict-spine-review",
        "github_gate_unverified",
    ]
    assert writeback.envelope_json["proof_boundary"] == (
        "final_action_writeback_not_github_or_merge_truth"
    )


def test_final_action_approval_with_direct_github_evidence_ref_stays_blocked(
    tmp_path: Path,
) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    FinalActionGateStore(tmp_path / "final_actions.json").resolve(
        hold.id,
        status="approved",
        resolved_by="human",
        github_gate_evidence_ref="github:pr:42#checks=abc123",
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    final_action = FinalActionGateStore(tmp_path / "final_actions.json").get(hold.id)
    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.github_gate_evidence_ref is None
    assert spine.manual_gaps == ["github_gate_unverified"]
    assert spine.blocked_reason == "github_gate_unverified"
    assert final_action.github_gate_evidence_ref is None
    assert final_action.github_gate_gap_ref == "github:pr:42#checks=abc123"


def test_final_action_terminate_approval_does_not_require_github_gate(
    tmp_path: Path,
) -> None:
    store = FinalActionGateStore(tmp_path / "final_actions.json")
    hold = store.create_hold(
        lane_id="lane-terminal",
        verdict_id="verdict-terminal",
        action="terminate",
        target_status="failed",
        summary="Terminate unrecoverable lane.",
    )

    final_action = store.resolve(
        hold.id,
        status="approved",
        resolved_by="human",
    )

    assert final_action.status == "approved"
    assert final_action.github_gate_evidence_ref is None
    assert final_action.github_gate_gap_ref is None


def test_acceptance_spine_direct_final_action_ref_without_producer_record_stays_blocked(
    tmp_path: Path,
) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    AcceptanceSpineStore(tmp_path / "chat.db").resolve_final_action(
        final_action_ref=f"final_actions.json#hold={hold.id}",
        status="approved",
        github_gate_evidence_ref="github:pr:42#checks=abc123",
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.github_gate_evidence_ref is None
    assert spine.manual_gaps == ["github_gate_unverified"]
    assert spine.blocked_reason == "github_gate_unverified"


def test_final_action_approval_with_server_gate_producer_accepts_spine(
    tmp_path: Path,
) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    FinalActionGateStore(tmp_path / "final_actions.json").resolve_with_github_gate_evidence(
        hold.id,
        status="approved",
        resolved_by="human",
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=["quality-gates", "contract-smoke-gates"],
        collector=_StaticGithubTruthCollector(_complete_server_truth()),
        main_ci_collector=_StaticMainCiTruthCollector(_complete_main_ci_truth()),
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    final_action = FinalActionGateStore(tmp_path / "final_actions.json").get(hold.id)
    gate_payload = json.loads((tmp_path / "github_gate_evidence.json").read_text(encoding="utf-8"))

    assert spine.status is AcceptanceSpineStatus.ACCEPTED
    assert spine.github_gate_evidence_ref == final_action.github_gate_evidence_ref
    assert spine.github_gate_evidence_ref is not None
    assert spine.manual_gaps == []
    assert gate_payload["items"][0]["can_accept"] is True
    assert gate_payload["items"][0]["evidence"]["proof_level"] == "server_side_merge_proof"

    api_payload = (
        TestClient(create_app(tmp_path))
        .get(f"/api/chat/conversations/{spine.conversation_id}/acceptance-spines")
        .json()
    )
    api_item = api_payload["items"][0]
    assert api_payload["source_authority"] == "chat_store"
    assert api_item["final_action_ref"] == f"final_actions.json#hold={hold.id}"
    assert api_item["github_gate_evidence_ref"] == final_action.github_gate_evidence_ref
    assert api_item["manual_gaps"] == []

    writebacks = [
        message
        for message in ChatStore(tmp_path / "chat.db").list_messages(spine.conversation_id)
        if message.envelope_type == "final_action_result"
    ]
    assert len(writebacks) == 1
    writeback = writebacks[0]
    assert writeback.envelope_json["github_gate_evidence_ref"] == (
        final_action.github_gate_evidence_ref
    )
    assert writeback.envelope_json["github_gate"]["status"] == "accepted"
    assert writeback.envelope_json["github_gate"]["proof_level"] == (
        "server_side_merge_proof"
    )
    assert writeback.envelope_json["github_gate"]["repo"] == "iiyazu/Cross-Muse"
    assert writeback.envelope_json["github_gate"]["pull_request_number"] == 42
    assert writeback.envelope_json["github_gate"]["head_sha"] == "head123"
    assert writeback.envelope_json["github_gate"]["workflow_run_id"] == 111
    assert writeback.envelope_json["github_gate"]["check_suite_id"] == 222
    assert writeback.envelope_json["github_gate"]["required_checks"] == [
        "quality-gates",
        "contract-smoke-gates",
    ]
    assert writeback.envelope_json["github_gate"]["check_runs"] == [
        {"id": 111, "name": "quality-gates", "head_sha": "head123"},
        {"id": 112, "name": "contract-smoke-gates", "head_sha": "head123"},
    ]
    assert writeback.envelope_json["github_gate"]["merge"] == {
        "merge_commit_sha": "abc123",
        "merged_at": "2026-06-10T15:00:00Z",
        "merge_event_id": "merge-event-1",
    }
    assert writeback.envelope_json["github_gate"]["main_ci"] == {
        "workflow_run_id": 333,
        "workflow_name": "xmuse CI",
        "head_sha": "abc123",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "url": "https://github.com/iiyazu/Cross-Muse/actions/runs/333",
    }
    assert writeback.envelope_json["acceptance_spine_ref"] == (
        f"chat.db:acceptance_spines#spine={spine.spine_id}"
    )
    assert writeback.envelope_json["source_refs"] == [
        f"final_actions.json#hold={hold.id}",
        f"chat.db:acceptance_spines#spine={spine.spine_id}",
        f"message:{intake_message_id}",
        f"proposal:{spine.proposal_id}",
        spine.review_or_execute_verdict_ref,
        "review_plane.json#verdict=verdict-spine-review",
        final_action.github_gate_evidence_ref,
    ]


def test_final_action_writeback_preserves_spine_execution_lineage_refs(
    tmp_path: Path,
) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)
    db = tmp_path / "chat.db"
    spine_store = AcceptanceSpineStore(db)
    spine = spine_store.get_by_intake_message(intake_message_id)
    assert spine.proposal_id is not None
    assert spine.review_or_execute_verdict_ref is not None
    resolution_id = spine.review_or_execute_verdict_ref.removeprefix("resolution:")
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=spine.conversation_id,
        proposal_id=spine.proposal_id,
        resolution_id=resolution_id,
        collaboration_run_id=None,
        artifact_ref="artifact:final-action-lineage",
        gate_refs=["review:accepted"],
    )
    spine_store.attach_lane_execution_for_resolution(
        resolution_id=resolution_id,
        evidence_refs=[
            "feature_lanes.json#lane=lane-spine-review:status=executed",
            "lane_graph:graph-spine-review",
        ],
    )

    FinalActionGateStore(tmp_path / "final_actions.json").resolve_with_github_gate_evidence(
        hold.id,
        status="approved",
        resolved_by="human",
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=["quality-gates", "contract-smoke-gates"],
        collector=_StaticGithubTruthCollector(_complete_server_truth()),
        main_ci_collector=_StaticMainCiTruthCollector(_complete_main_ci_truth()),
    )

    final_action = FinalActionGateStore(tmp_path / "final_actions.json").get(hold.id)
    accepted_spine = spine_store.get_by_intake_message(intake_message_id)
    writeback = [
        message
        for message in ChatStore(db).list_messages(accepted_spine.conversation_id)
        if message.envelope_type == "final_action_result"
    ][0]
    assert writeback.envelope_json["source_refs"] == [
        f"final_actions.json#hold={hold.id}",
        f"chat.db:acceptance_spines#spine={accepted_spine.spine_id}",
        f"message:{intake_message_id}",
        f"proposal:{accepted_spine.proposal_id}",
        accepted_spine.review_or_execute_verdict_ref,
        f"chat_dispatch_queue:{dispatch.entry_id}",
        "feature_lanes.json#lane=lane-spine-review:status=executed",
        "lane_graph:graph-spine-review",
        "review_plane.json#verdict=verdict-spine-review",
        final_action.github_gate_evidence_ref,
    ]


def test_final_action_approval_with_server_gate_gap_keeps_spine_blocked(
    tmp_path: Path,
) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    FinalActionGateStore(tmp_path / "final_actions.json").resolve_with_github_gate_evidence(
        hold.id,
        status="approved",
        resolved_by="human",
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=["quality-gates"],
        collector=_StaticGithubTruthCollector(_manual_gap_truth()),
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    final_action = FinalActionGateStore(tmp_path / "final_actions.json").get(hold.id)
    gate_payload = json.loads((tmp_path / "github_gate_evidence.json").read_text(encoding="utf-8"))

    assert spine.status is AcceptanceSpineStatus.BLOCKED
    assert spine.github_gate_evidence_ref is None
    assert spine.manual_gaps == ["github_gate_unverified"]
    assert final_action.status == "blocked"
    assert final_action.github_gate_evidence_ref is None
    assert final_action.github_gate_gap_ref is not None
    assert gate_payload["items"][0]["can_accept"] is False
    assert gate_payload["items"][0]["gap_reason"] == "missing server-side truth"


def test_final_action_rejection_fails_spine(tmp_path: Path) -> None:
    intake_message_id, hold = _create_spine_with_pending_final_action(tmp_path)

    FinalActionGateStore(tmp_path / "final_actions.json").resolve(
        hold.id,
        status="rejected",
        resolved_by="human",
    )

    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(intake_message_id)
    assert spine.status is AcceptanceSpineStatus.FAILED
    assert spine.blocked_reason == "final_action_rejected"


def _create_spine_with_pending_final_action(tmp_path: Path):
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
    return intake.message.id, hold


class _StaticGithubTruthCollector:
    def __init__(self, evidence: GitHubServerSideTruthEvidence) -> None:
        self._evidence = evidence

    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence:
        assert repo == self._evidence.repo
        assert pull_request_number == self._evidence.pull_request_number
        assert required_checks == self._evidence.required_checks
        return self._evidence


class _StaticMainCiTruthCollector:
    def __init__(self, evidence: GitHubMainCiEvidence) -> None:
        self._evidence = evidence

    def collect_main_ci(
        self,
        *,
        repo: str,
        merge_commit_sha: str,
    ) -> GitHubMainCiEvidence:
        assert repo == "iiyazu/Cross-Muse"
        assert merge_commit_sha == "abc123"
        return self._evidence


def _complete_server_truth() -> GitHubServerSideTruthEvidence:
    return GitHubServerSideTruthEvidence(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=["quality-gates", "contract-smoke-gates"],
        proof_level="server_side_merge_proof",
        head_sha="head123",
        workflow_run_id=111,
        check_suite_id=222,
        check_run_ids=[111, 112],
        check_run_names=["quality-gates", "contract-smoke-gates"],
        check_run_head_shas=["head123", "head123"],
        expected_source_app="github-actions",
        branch_protection_snapshot={
            "required_status_checks": {
                "checks": [{"context": "quality-gates"}, {"context": "contract-smoke-gates"}]
            }
        },
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )


def _complete_main_ci_truth() -> GitHubMainCiEvidence:
    return GitHubMainCiEvidence(
        workflow_run_id=333,
        workflow_name="xmuse CI",
        head_sha="abc123",
        head_branch="main",
        status="completed",
        conclusion="success",
        url="https://github.com/iiyazu/Cross-Muse/actions/runs/333",
        created_at="2026-06-10T15:01:00Z",
        updated_at="2026-06-10T15:02:00Z",
    )


def _manual_gap_truth() -> GitHubServerSideTruthEvidence:
    return GitHubServerSideTruthEvidence(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=["quality-gates"],
        proof_level="manual_gap",
        gap_reason="missing server-side truth",
    )
