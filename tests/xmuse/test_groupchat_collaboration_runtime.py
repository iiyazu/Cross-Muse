from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.collaboration_contracts import (
    CollaborationStatus,
    DispatchGateDecision,
)
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_bridge import ChatDispatchBridge
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.chat.store import ChatStore


def _conversation(tmp_path: Path) -> str:
    chat = ChatStore(tmp_path / "chat.db")
    return chat.create_conversation("V14 runtime").id


def test_collaboration_request_is_bounded_durable_and_idempotent(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")

    request = store.create_request(
        conversation_id=conversation_id,
        goal="Improve the TUI runtime surface",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Check feasibility and risks.",
        context_refs=["message:1", "proposal:1"],
        idempotency_key="v14-first-pass",
        timeout_s=480,
    )
    same_request = store.create_request(
        conversation_id=conversation_id,
        goal="Improve the TUI runtime surface",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Check feasibility and risks.",
        context_refs=[],
        idempotency_key="v14-first-pass",
        timeout_s=480,
    )

    assert request.run_id == same_request.run_id
    assert request.orchestration_mode == "peer_consensus"
    assert request.status is CollaborationStatus.RUNNING
    assert request.targets == ["review", "execute"]
    assert request.max_depth == 1

    reloaded = ChatCollaborationStore(tmp_path / "chat.db").get_run(request.run_id)
    assert reloaded.run_id == request.run_id
    assert reloaded.context_refs == ["message:1", "proposal:1"]


def test_collaboration_rejects_unbounded_targets_and_active_target_cascade(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")

    with pytest.raises(ValueError, match="1-3 targets"):
        store.create_request(
            conversation_id=conversation_id,
            goal="Too broad",
            initiator="architect",
            targets=["review", "execute", "security", "ux"],
            callback_target="architect",
            question="Everyone weigh in.",
            context_refs=[],
            idempotency_key="too-many",
            timeout_s=480,
        )

    store.create_request(
        conversation_id=conversation_id,
        goal="First request",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="Review this.",
        context_refs=[],
        idempotency_key="outer",
        timeout_s=480,
    )

    with pytest.raises(ValueError, match="anti-cascade"):
        store.create_request(
            conversation_id=conversation_id,
            goal="Nested request",
            initiator="review",
            targets=["execute"],
            callback_target="review",
            question="Can you also check execution?",
            context_refs=[],
            idempotency_key="nested",
            timeout_s=480,
        )


def test_collaboration_aggregates_responses_and_times_out_missing_targets(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Aggregate review",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Respond with blocker and feasibility.",
        context_refs=[],
        idempotency_key="aggregate",
        timeout_s=480,
    )

    partial = store.record_response(
        run.run_id,
        target="review",
        content="Review blocks dispatch until controls are visible.",
        response_status="received",
    )
    assert partial.status is CollaborationStatus.PARTIAL
    assert [response.target for response in partial.responses] == ["review"]

    timed_out = store.mark_timeout(run.run_id)
    assert timed_out.status is CollaborationStatus.TIMEOUT
    by_target = {response.target: response.status for response in timed_out.responses}
    assert by_target == {"review": "received", "execute": "timeout"}

    late = store.record_response(
        run.run_id,
        target="execute",
        content="Late response should not reopen a timeout.",
        response_status="received",
    )
    assert late.status is CollaborationStatus.TIMEOUT
    assert {response.target: response.status for response in late.responses} == by_target


def test_active_review_veto_blocks_dispatch_until_resolved(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Dispatch gate",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Can this dispatch?",
        context_refs=[],
        idempotency_key="dispatch-gate",
        timeout_s=480,
    )

    blocker = store.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="TUI does not expose blocker state yet.",
        affected_ref="tui:blockers",
        suggested_fix="Add blocker read surface before dispatch.",
        blocks_dispatch=True,
    )
    blocked = store.evaluate_dispatch_gate(
        conversation_id=conversation_id,
        run_id=run.run_id,
        proposal_ref="proposal:lane-graph",
        artifact_ref="artifact:lane-graph",
        execute_confirmed=True,
        policy_allows_real_provider=True,
    )

    assert blocker.active is True
    assert blocked is DispatchGateDecision.BLOCKED_ACTIVE_VETO

    store.resolve_blocker(
        blocker.blocker_id,
        resolved_by="architect",
        resolution_evidence="read-surface:blockers-visible",
    )
    allowed = store.evaluate_dispatch_gate(
        conversation_id=conversation_id,
        run_id=run.run_id,
        proposal_ref="proposal:lane-graph",
        artifact_ref="artifact:lane-graph",
        execute_confirmed=True,
        policy_allows_real_provider=True,
    )
    assert allowed is DispatchGateDecision.ALLOWED


def test_dispatch_gate_decisions_are_durable_and_visible_in_inspector(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Trace dispatch gate",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Can this dispatch?",
        context_refs=[],
        idempotency_key="dispatch-gate-trace",
        timeout_s=480,
    )

    decision = store.evaluate_dispatch_gate(
        conversation_id=conversation_id,
        run_id=run.run_id,
        proposal_ref="proposal:lane-graph",
        artifact_ref="artifact:lane-graph",
        execute_confirmed=False,
        policy_allows_real_provider=True,
    )

    assert decision is DispatchGateDecision.BLOCKED_EXECUTE_NOT_CONFIRMED
    reloaded_events = ChatCollaborationStore(tmp_path / "chat.db").list_dispatch_gate_events(
        conversation_id
    )
    assert len(reloaded_events) == 1
    assert reloaded_events[0].run_id == run.run_id
    assert reloaded_events[0].decision is DispatchGateDecision.BLOCKED_EXECUTE_NOT_CONFIRMED
    assert reloaded_events[0].proposal_ref == "proposal:lane-graph"
    assert reloaded_events[0].artifact_ref == "artifact:lane-graph"
    assert reloaded_events[0].execute_confirmed is False

    payload = build_conversation_inspector_payload(conversation_id, tmp_path)

    assert payload["collaboration"]["dispatch_gates"] == [
        reloaded_events[0].model_dump(mode="json")
    ]


def test_conversation_inspector_exposes_collaboration_and_blocker_read_surface(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Read surface",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="Review the read surface.",
        context_refs=[],
        idempotency_key="read-surface",
        timeout_s=480,
    )
    blocker = store.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Missing discussion run cards.",
        affected_ref="dashboard:overview",
        suggested_fix="Expose collaboration summary in inspector.",
        blocks_dispatch=True,
    )

    payload = build_conversation_inspector_payload(conversation_id, tmp_path)

    assert payload["collaboration"]["active_runs"] == 1
    assert payload["collaboration"]["runs"][0]["run_id"] == run.run_id
    assert payload["collaboration"]["runs"][0]["status"] == "running"
    assert payload["blockers"]["active"] == 1
    assert payload["blockers"]["items"][0]["blocker_id"] == blocker.blocker_id
    assert payload["blockers"]["items"][0]["blocks_dispatch"] is True


def test_chat_api_inspector_exposes_collaboration_read_surface(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="API read surface",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="Review API surface.",
        context_refs=[],
        idempotency_key="api-read-surface",
        timeout_s=480,
    )
    blocker = store.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Dispatch gate needs API visibility.",
        affected_ref="api:inspector",
        suggested_fix="Expose blockers through inspector.",
        blocks_dispatch=True,
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/chat/conversations/{conversation_id}/inspector"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["collaboration"]["runs"][0]["run_id"] == run.run_id
    assert payload["blockers"]["items"][0]["blocker_id"] == blocker.blocker_id


def test_chat_api_collaboration_control_surface_enforces_dispatch_gate(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    client = TestClient(create_app(tmp_path))

    created = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/requests",
        json={
            "goal": "API-controlled V14 run",
            "initiator": "architect",
            "targets": ["review", "execute"],
            "callback_target": "architect",
            "question": "Check whether this can dispatch.",
            "context_refs": ["message:intake"],
            "idempotency_key": "api-collaboration",
            "timeout_s": 480,
        },
    )

    assert created.status_code == 201
    run_id = created.json()["run"]["run_id"]
    assert created.json()["run"]["orchestration_mode"] == "peer_consensus"

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/responses",
        json={
            "target": "execute",
            "content": "Executable once review clears the TUI blocker.",
            "status": "received",
        },
    )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "partial"

    blocker_response = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/blockers",
        json={
            "issuer": "review",
            "severity": "veto",
            "reason": "Operator cannot see dispatch state.",
            "affected_ref": "dashboard:overview",
            "suggested_fix": "Expose dispatch gate status before real provider execution.",
            "blocks_dispatch": True,
        },
    )
    assert blocker_response.status_code == 201
    blocker_id = blocker_response.json()["blocker"]["blocker_id"]

    blocked_gate = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/dispatch-gate",
        json={
            "proposal_ref": "proposal:mission-blueprint",
            "artifact_ref": "artifact:feature-plan",
            "execute_confirmed": True,
            "policy_allows_real_provider": True,
        },
    )
    assert blocked_gate.status_code == 200
    assert blocked_gate.json()["decision"] == "blocked_active_veto"

    resolved = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/blockers/{blocker_id}/resolve",
        json={
            "resolved_by": "architect",
            "resolution_evidence": "dashboard:dispatch-state-visible",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["blocker"]["active"] is False

    allowed_gate = client.post(
        f"/api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/dispatch-gate",
        json={
            "proposal_ref": "proposal:mission-blueprint",
            "artifact_ref": "artifact:feature-plan",
            "execute_confirmed": True,
            "policy_allows_real_provider": True,
        },
    )
    assert allowed_gate.status_code == 200
    assert allowed_gate.json()["decision"] == "allowed"


def test_proposal_approval_references_collaboration_gate_and_blocks_active_veto(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Gate proposal approval",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Can this proposal dispatch?",
        context_refs=[],
        idempotency_key="proposal-gate",
        timeout_s=480,
    )
    blocker = store.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Execution controls are not visible yet.",
        affected_ref="dispatch:proposal-approval",
        suggested_fix="Expose controls before approving dispatchable artifact.",
        blocks_dispatch=True,
    )
    client = TestClient(create_app(tmp_path))

    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Dispatchable TUI work",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-tui",
                            "prompt": "Update TUI dispatch visibility.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                    "resolution_content": {
                        "type": "lane_graph",
                        "summary": "Dispatchable TUI work",
                        "lanes": [
                            {
                                "feature_id": "lane-v14-tui",
                                "prompt": "Update TUI dispatch visibility.",
                                "depends_on": [],
                                "capabilities": ["code"],
                            }
                        ],
                    },
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201
    proposal_id = proposal.json()["id"]

    blocked = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Attempt dispatch while review veto is active",
        },
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "dispatch_gate_blocked"
    assert blocked.json()["detail"]["message"] == "blocked_active_veto"

    store.resolve_blocker(
        blocker.blocker_id,
        resolved_by="architect",
        resolution_evidence="tui:dispatch-visibility-added",
    )
    store.record_response(
        run.run_id,
        target="execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "summary": "Executable after blocker visibility was added.",
                "evidence_refs": ["tui:dispatch-visibility-added"],
            }
        ),
        response_status="received",
    )
    store.record_response(
        run.run_id,
        target="review",
        content="Review veto resolved; dispatch gate can now use fresh proposal authority.",
        response_status="received",
    )
    stale = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Old proposal remains stale after review veto is resolved",
        },
    )
    assert stale.status_code == 400
    assert stale.json()["detail"]["message"] == "blocked_stale_collaboration_proposal"

    fresh_proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Dispatchable TUI work after collaboration done",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-tui",
                            "prompt": "Update TUI dispatch visibility.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert fresh_proposal.status_code == 201
    allowed = client.post(
        f"/api/chat/proposals/{fresh_proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Dispatch after review veto is resolved",
        },
    )
    assert allowed.status_code == 200


def test_blocked_collaboration_gate_leaves_no_approval_side_effects(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Gate side effects",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="Can this dispatch?",
        context_refs=[],
        idempotency_key="proposal-gate-side-effects",
        timeout_s=480,
    )
    store.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Review veto must stop approval side effects.",
        affected_ref="proposal:approval",
        suggested_fix="Resolve review veto before approving.",
        blocks_dispatch=True,
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Blocked dispatchable work",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-blocked",
                            "prompt": "This must not dispatch while veto is active.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Blocked approval must not write side effects",
        },
    )

    assert blocked.status_code == 400
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []
    assert ChatDispatchQueueStore(tmp_path / "chat.db").list_entries(conversation_id) == []
    assert not (tmp_path / "read_models" / "resolutions.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_proposal_approval_rejects_foreign_collaboration_run_ref(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    foreign_conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    foreign_run = store.create_request(
        conversation_id=foreign_conversation_id,
        goal="Foreign gate",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="This belongs to another conversation.",
        context_refs=[],
        idempotency_key="foreign-proposal-gate",
        timeout_s=480,
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Wrong collaboration ref",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-foreign-ref",
                            "prompt": "This must not borrow another conversation gate.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{foreign_run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Foreign collaboration gate must not approve",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "dispatch_gate_blocked"
    assert blocked.json()["detail"]["message"] == "blocked_unknown_run"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_proposal_approval_requires_execute_collaboration_confirmation(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Require execute confirmation",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Review and confirm whether the artifact is executable.",
        context_refs=[],
        idempotency_key="execute-confirmation-gate",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="review",
        content="No veto from review.",
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Needs execute confirmation",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-needs-execute",
                            "prompt": "Do not dispatch before execute confirms feasibility.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute has not confirmed feasibility yet",
        },
    )
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "dispatch_gate_blocked"
    assert blocked.json()["detail"]["message"] == "blocked_execute_not_confirmed"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []

    store.record_response(
        run.run_id,
        target="execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "summary": "Lane graph has clear scope and required evidence.",
                "evidence_refs": ["proposal:lane-v14-needs-execute"],
            }
        ),
        response_status="received",
    )
    stale = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute confirmed feasibility on stale proposal",
        },
    )
    assert stale.status_code == 400
    assert stale.json()["detail"]["message"] == "blocked_stale_collaboration_proposal"

    fresh_proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Needs execute confirmation after collaboration done",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-needs-execute",
                            "prompt": "Dispatch after execute confirms feasibility.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert fresh_proposal.status_code == 201
    allowed = client.post(
        f"/api/chat/proposals/{fresh_proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute confirmed feasibility",
        },
    )
    assert allowed.status_code == 200


def test_proposal_approval_rejects_proposal_created_before_collaboration_done(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Reject stale proposal authority",
        initiator="architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Confirm execution feasibility before proposal authority.",
        context_refs=["message:intake"],
        idempotency_key="stale-collaboration-proposal",
        timeout_s=480,
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Created before collaboration completes",
                    "lanes": [
                        {
                            "feature_id": "stale-collaboration-proposal",
                            "prompt": "This proposal must not become authority.",
                            "depends_on": [],
                            "capabilities": ["test"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    store.record_response(
        run.run_id,
        target="@execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "verdict": "dispatchable",
                "command": "uv run pytest tests/xmuse/test_package_boundaries.py -q",
                "proof_boundary": "local runtime contract proof only",
                "notes": "Execution is feasible after the proposal was created.",
            }
        ),
        response_status="received",
    )
    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Stale proposal must not dispatch",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "dispatch_gate_blocked"
    assert blocked.json()["detail"]["message"] == "blocked_stale_collaboration_proposal"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_proposal_approval_accepts_dispatchable_execute_verdict(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Accept provider-style dispatchability verdict",
        initiator="architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Confirm whether the artifact is dispatchable.",
        context_refs=["message:intake"],
        idempotency_key="execute-dispatchable-confirmation-gate",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="@execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "dispatchable": True,
                "scope": "dispatchability judgment only for later lane execution worktree work",
                "later_execution_command": (
                    "uv run pytest tests/xmuse/test_package_boundaries.py -q"
                ),
                "proof_boundary": "local runtime contract proof only",
                "notes": [
                    "No tests run during peer chat.",
                    "No files edited during peer chat.",
                ],
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Provider-style execute confirmation",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-dispatchable-execute",
                            "prompt": "Run one bounded command later.",
                            "depends_on": [],
                            "capabilities": ["test"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    allowed = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute confirmed provider-style dispatchability",
        },
    )

    assert allowed.status_code == 200


def test_proposal_approval_accepts_response_type_dispatchable_verdict(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Accept natural provider dispatchability verdict",
        initiator="architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Confirm whether the artifact is dispatchable.",
        context_refs=["message:intake"],
        idempotency_key="execute-response-type-dispatchable-gate",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="@execute",
        content=json.dumps(
            {
                "response_type": "execute_feasibility_verdict",
                "verdict": "dispatchable",
                "scope": "later lane execution worktree only",
                "command": "uv run pytest tests/xmuse/test_package_boundaries.py -q",
                "proof_boundary": "local runtime contract proof only",
                "peer_chat_actions_taken": [
                    "did_not_run_tests",
                    "did_not_edit_files",
                    "did_not_treat_peer_chat_worktree_as_lane_worktree",
                ],
                "notes": "This is a dispatchability judgment for later execution only.",
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Natural provider execute confirmation",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-response-type-execute",
                            "prompt": "Run one bounded command later.",
                            "depends_on": [],
                            "capabilities": ["test"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    allowed = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute confirmed natural dispatchability",
        },
    )

    assert allowed.status_code == 200


def test_proposal_approval_accepts_provider_expanded_dispatchable_verdict(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Accept provider-expanded dispatchability verdict",
        initiator="architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Confirm whether the artifact is dispatchable.",
        context_refs=["message:intake"],
        idempotency_key="execute-expanded-dispatchable-gate",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="@execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "verdict": (
                    "dispatchable_for_later_lane_execution_worktree_pending_human_approval"
                ),
                "command": "uv run pytest tests/xmuse/test_package_boundaries.py -q",
                "proof_boundary": "local runtime proof only",
                "execution_performed": False,
                "summary": "Provider confirms dispatchability for a later lane worktree.",
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Expanded provider execute confirmation",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-expanded-execute",
                            "prompt": "Run one bounded command later.",
                            "depends_on": [],
                            "capabilities": ["test"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    allowed = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute confirmed expanded provider dispatchability",
        },
    )

    assert allowed.status_code == 200


def test_proposal_approval_accepts_execute_address_target_confirmation(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Require execute confirmation with address target",
        initiator="architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Confirm whether the artifact is executable.",
        context_refs=["message:intake"],
        idempotency_key="execute-address-confirmation-gate",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="@execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "summary": "Lane graph has clear scope and required evidence.",
                "evidence_refs": ["message:intake", "proposal:lane-v14-address-execute"],
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Address execute confirmation",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-address-execute",
                            "prompt": "Dispatch after address execute confirms feasibility.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    allowed = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Address execute confirmed feasibility",
        },
    )

    assert allowed.status_code == 200


def test_lane_graph_approval_preserves_review_runtime_in_projection(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Preserve review runtime",
                    "lanes": [
                        {
                            "feature_id": "lane-review-runtime-opencode",
                            "prompt": "Preserve OpenCode review routing.",
                            "depends_on": [],
                            "capabilities": ["code"],
                            "review_runtime": "opencode",
                        }
                    ],
                }
            ),
            "references": [],
        },
    )
    assert proposal.status_code == 201

    approved = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "manual",
            "goal_summary": "Approve review runtime projection",
        },
    )

    assert approved.status_code == 200
    graph_id = f"{approved.json()['id']}-graph-v{approved.json()['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    assert graph["lanes"][0]["review_runtime"] == "opencode"
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    assert lanes[0]["feature_id"] == "lane-review-runtime-opencode"
    assert lanes[0]["review_runtime"] == "opencode"


def test_lane_graph_approval_carries_execution_evidence_contract(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "type": "lane_graph",
                    "summary": "Loop evidence continuation",
                    "lanes": [
                        {
                            "feature_id": "lane-loop8-evidence",
                            "prompt": (
                                "Document the bounded proposal proof; do not "
                                "execute or approve in this loop."
                            ),
                            "depends_on": [],
                            "capabilities": ["docs"],
                            "review_runtime": "grok",
                        }
                    ],
                }
            ),
            "references": ["message:review-ready", "runtime_artifact:loop6-summary"],
        },
    )
    assert proposal.status_code == 201

    approved = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "manual",
            "goal_summary": "Continue approved proposal into execution evidence",
        },
    )

    assert approved.status_code == 200
    resolution = approved.json()
    proposal_ref = f"proposal:{proposal.json()['id']}"
    graph_id = f"{resolution['id']}-graph-v{resolution['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    lane_prompt = graph["lanes"][0]["prompt"]
    assert "Approved proposal execution contract" in lane_prompt
    assert f"resolution_id: {resolution['id']}" in lane_prompt
    assert proposal_ref in lane_prompt
    assert "message:review-ready" in lane_prompt
    assert f"xmuse_runtime_root: {tmp_path}" in lane_prompt
    assert "Original proposal lane prompt:" in lane_prompt
    assert "do not execute or approve in this loop" in lane_prompt

    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    projected = lanes[0]
    prompt_ref = projected["prompt_ref"]
    prompt_artifact = (tmp_path / prompt_ref).read_text(encoding="utf-8")
    assert "Approved proposal execution contract" in prompt_artifact
    assert proposal_ref in prompt_artifact
    assert projected["prompt_summary"].startswith("Approved proposal execution contract")


def test_proposal_approval_rejects_freeform_execute_confirmation(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Reject freeform execute confirmation",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm feasibility with typed evidence.",
        context_refs=[],
        idempotency_key="freeform-execute-confirmation",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="execute",
        content="Executable: I can do this.",
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Freeform execute response is not enough",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-freeform-execute",
                            "prompt": "Do not dispatch on freeform execute response.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Freeform execute confirmation must not dispatch",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "dispatch_gate_blocked"
    assert blocked.json()["detail"]["message"] == "blocked_execute_not_confirmed"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_proposal_approval_rejects_blocked_execute_verdict(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Reject blocked execute verdict",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm feasibility with typed evidence.",
        context_refs=[],
        idempotency_key="blocked-execute-verdict",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "blocked",
                "summary": "Cannot execute until review veto is resolved.",
                "evidence_refs": ["blocker:review-veto"],
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Blocked execute verdict is not enough",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-blocked-execute",
                            "prompt": "Do not dispatch on blocked execute verdict.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Blocked execute verdict must not dispatch",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["message"] == "blocked_execute_not_confirmed"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_proposal_approval_rejects_negative_expanded_execute_verdict(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Reject negative provider-expanded execute verdict",
        initiator="architect",
        targets=["@execute"],
        callback_target="@architect",
        question="Confirm feasibility with typed evidence.",
        context_refs=[],
        idempotency_key="negative-expanded-execute-verdict",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="@execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "verdict": "not_dispatchable_until_review_veto_resolved",
                "command": "uv run pytest tests/xmuse/test_package_boundaries.py -q",
                "proof_boundary": "local runtime proof only",
                "summary": "Provider says dispatch is still blocked.",
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Negative expanded verdict is not enough",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-negative-expanded",
                            "prompt": "Do not dispatch on negative expanded verdict.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Negative expanded verdict must not dispatch",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["message"] == "blocked_execute_not_confirmed"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_proposal_approval_rejects_execute_verdict_without_evidence(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Reject execute verdict without evidence",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm feasibility with typed evidence.",
        context_refs=[],
        idempotency_key="execute-verdict-without-evidence",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "summary": "Looks executable.",
                "evidence_refs": [],
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Evidence is required",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-no-execute-evidence",
                            "prompt": "Do not dispatch without execute evidence.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute verdict evidence is required",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["message"] == "blocked_execute_not_confirmed"
    assert ChatStore(tmp_path / "chat.db").list_resolutions(conversation_id) == []


def test_proposal_approval_enqueues_agent_auto_dispatch_entry_after_gate(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    collaboration = ChatCollaborationStore(tmp_path / "chat.db")
    run = collaboration.create_request(
        conversation_id=conversation_id,
        goal="Queue approved dispatch",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Can this dispatch through the unified queue?",
        context_refs=[],
        idempotency_key="proposal-gate-dispatch-queue",
        timeout_s=480,
    )
    collaboration.record_response(
        run.run_id,
        target="review",
        content="No veto.",
        response_status="received",
    )
    collaboration.record_response(
        run.run_id,
        target="execute",
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "summary": "Queue-backed TUI work is executable.",
                "evidence_refs": ["proposal:lane-v14-dispatch-queue"],
            }
        ),
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Queue-backed TUI work",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-dispatch-queue",
                            "prompt": "Surface dispatch queue state in the TUI.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    approved = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Queue approved dispatch work",
        },
    )

    assert approved.status_code == 200
    resolution_id = approved.json()["id"]
    entries = ChatDispatchQueueStore(tmp_path / "chat.db").list_entries(conversation_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == "agent"
    assert entry.auto_execute is True
    assert entry.status == "queued"
    assert entry.proposal_id == proposal.json()["id"]
    assert entry.resolution_id == resolution_id
    assert entry.collaboration_run_id == run.run_id
    assert entry.artifact_ref == "artifact:lane_graph"
    assert entry.dispatch_policy == "real_provider_allowed"
    assert entry.target == "execute"

    inspector = build_conversation_inspector_payload(conversation_id, tmp_path)
    assert inspector["dispatch_queue"]["entries"][0]["entry_id"] == entry.entry_id
    assert inspector["dispatch_queue"]["queued"] == 1


def test_proposal_approval_without_collaboration_ref_does_not_enqueue_dispatch_entry(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Ungated structured work",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-no-collaboration-ref",
                            "prompt": "This approval has no collaboration dispatch gate.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [],
        },
    )
    assert proposal.status_code == 201

    approved = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Legacy approval without collaboration ref",
        },
    )

    assert approved.status_code == 200
    assert ChatDispatchQueueStore(tmp_path / "chat.db").list_entries(conversation_id) == []


def test_dispatch_queue_lifecycle_is_durable_and_visible_in_inspector(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    queue = ChatDispatchQueueStore(tmp_path / "chat.db")
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-v14",
        resolution_id="resolution-v14",
        collaboration_run_id="collab-v14",
        artifact_ref="artifact:lane_graph",
    )

    claimed = queue.claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="dispatch-bridge",
    )

    assert claimed is not None
    assert claimed.entry_id == entry.entry_id
    assert claimed.status == "processing"
    assert claimed.claimed_by == "dispatch-bridge"
    assert claimed.claimed_at is not None

    reloaded_processing = ChatDispatchQueueStore(tmp_path / "chat.db").get(entry.entry_id)
    assert reloaded_processing.status == "processing"
    assert reloaded_processing.claimed_by == "dispatch-bridge"

    dispatched = ChatDispatchQueueStore(tmp_path / "chat.db").mark_dispatched(
        entry.entry_id,
        provider_run_ref="provider:codex:session-1",
        dispatch_evidence="mcp_writeback:trace-1",
    )
    assert dispatched.status == "dispatched"
    assert dispatched.provider_run_ref == "provider:codex:session-1"
    assert dispatched.dispatch_evidence == "mcp_writeback:trace-1"
    assert dispatched.completed_at is not None

    failed_entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-v14-failed",
        resolution_id="resolution-v14-failed",
        collaboration_run_id="collab-v14-failed",
        artifact_ref="artifact:lane_graph",
    )
    queue.claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="dispatch-bridge",
    )
    failed = queue.mark_failed(
        failed_entry.entry_id,
        failure_reason="provider dispatch rejected",
    )
    assert failed.status == "failed"
    assert failed.failure_reason == "provider dispatch rejected"
    assert failed.completed_at is not None

    inspector = build_conversation_inspector_payload(conversation_id, tmp_path)
    assert inspector["dispatch_queue"]["dispatched"] == 1
    assert inspector["dispatch_queue"]["failed"] == 1
    by_id = {
        item["entry_id"]: item
        for item in inspector["dispatch_queue"]["entries"]
    }
    assert by_id[entry.entry_id]["provider_run_ref"] == "provider:codex:session-1"
    assert by_id[failed_entry.entry_id]["failure_reason"] == "provider dispatch rejected"


def test_chat_api_dispatch_bridge_claims_and_records_dispatch_lifecycle(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    queue = ChatDispatchQueueStore(tmp_path / "chat.db")
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-api",
        resolution_id="resolution-api",
        collaboration_run_id="collab-api",
        artifact_ref="artifact:lane_graph",
    )
    client = TestClient(create_app(tmp_path))

    claimed = client.post(
        f"/api/chat/conversations/{conversation_id}/dispatch/claim",
        json={"claimed_by": "dispatch-bridge"},
    )

    assert claimed.status_code == 200
    assert claimed.json()["entry"]["entry_id"] == entry.entry_id
    assert claimed.json()["entry"]["status"] == "processing"
    assert claimed.json()["entry"]["claimed_by"] == "dispatch-bridge"

    dispatched = client.post(
        f"/api/chat/dispatch/{entry.entry_id}/dispatched",
        json={
            "provider_run_ref": "provider:codex:session-api",
            "dispatch_evidence": "mcp_writeback:trace-api",
        },
    )

    assert dispatched.status_code == 200
    assert dispatched.json()["entry"]["status"] == "dispatched"
    assert dispatched.json()["entry"]["provider_run_ref"] == "provider:codex:session-api"
    assert dispatched.json()["entry"]["dispatch_evidence"] == "mcp_writeback:trace-api"


def test_chat_api_dispatch_bridge_records_failure(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    queue = ChatDispatchQueueStore(tmp_path / "chat.db")
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-api-fail",
        resolution_id="resolution-api-fail",
        collaboration_run_id="collab-api-fail",
        artifact_ref="artifact:lane_graph",
    )
    client = TestClient(create_app(tmp_path))

    failed = client.post(
        f"/api/chat/dispatch/{entry.entry_id}/failed",
        json={"failure_reason": "provider transport unavailable"},
    )

    assert failed.status_code == 200
    assert failed.json()["entry"]["status"] == "failed"
    assert failed.json()["entry"]["failure_reason"] == "provider transport unavailable"


def test_chat_api_dispatch_bridge_rejects_blank_claim_identity(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-api-blank",
        resolution_id="resolution-api-blank",
        collaboration_run_id="collab-api-blank",
        artifact_ref="artifact:lane_graph",
    )
    client = TestClient(create_app(tmp_path))

    rejected = client.post(
        f"/api/chat/conversations/{conversation_id}/dispatch/claim",
        json={"claimed_by": "   "},
    )

    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_dispatch_bridge_records_lane_worker_handoff_without_peer_nudge(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-real-provider",
        resolution_id="resolution-real-provider",
        collaboration_run_id="collab-real-provider",
        artifact_ref="artifact:lane_graph",
    )
    lane_worktree = tmp_path / "lane-worktree"
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-real-provider",
                        "resolution_id": "resolution-real-provider",
                        "worktree": str(lane_worktree),
                        "status": "awaiting_final_action",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=object(),
        worktree=tmp_path,
        lanes_path=lanes_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.claimed == 1
    assert outcome.dispatched == 1
    assert outcome.failed == 0
    reloaded = ChatDispatchQueueStore(tmp_path / "chat.db").get(entry.entry_id)
    assert reloaded.status == "dispatched"
    assert reloaded.provider_run_ref == "lane_worker:lane-real-provider"
    assert reloaded.dispatch_evidence.startswith("dispatch_handoff:")
    assert ":feature_lanes:lane-real-provider:awaiting_final_action" in (
        reloaded.dispatch_evidence
    )
    messages = ChatStore(tmp_path / "chat.db").list_messages(conversation_id)
    handoff = [msg for msg in messages if msg.envelope_type == "dispatch_handoff"]
    assert len(handoff) == 1
    envelope = handoff[0].envelope_json or {}
    assert envelope["dispatch_queue_entry_id"] == entry.entry_id
    assert envelope["lane_worker_authority"] == "feature_lanes"
    assert envelope["lane_id"] == "lane-real-provider"
    assert envelope["lane_status"] == "awaiting_final_action"
    assert envelope["execution_worktree"] == str(lane_worktree)
    assert "LANE_WORKER_HANDOFF" in handoff[0].content
    assert f"- Execution worktree: {lane_worktree}" in handoff[0].content
    assert "This message is not peer-chat execution truth." in handoff[0].content
    assert "DISPATCH_COMPLETED" not in handoff[0].content
    inspector = build_conversation_inspector_payload(conversation_id, tmp_path)
    assert inspector["dispatch_queue"]["dispatched"] == 1


@pytest.mark.asyncio
async def test_dispatch_bridge_handoff_includes_approved_artifact_context(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    chat = ChatStore(tmp_path / "chat.db")
    proposal = chat.create_proposal(
        conversation_id,
        author="architect",
        proposal_type="lane_graph",
        content=json.dumps(
            {
                "summary": "Production TUI closure",
                "lanes": [
                    {
                        "feature_id": "tui-command-dashboard",
                        "prompt": (
                            "Improve xmuse TUI slash commands and dashboard "
                            "read surfaces for production operator use."
                        ),
                        "depends_on": [],
                        "capabilities": ["code"],
                    }
                ],
            }
        ),
        references=["collaboration:run-dispatch-context"],
    )
    resolution = chat.approve_proposal(
        proposal.id,
        approved_by=["architect", "review", "execute"],
        approval_mode="auto",
        goal_summary="Approved production TUI closure work.",
        content={
            "summary": "Production TUI closure",
            "lanes": [
                {
                    "feature_id": "tui-command-dashboard",
                    "prompt": (
                        "Improve xmuse TUI slash commands and dashboard "
                        "read surfaces for production operator use."
                    ),
                    "depends_on": [],
                    "capabilities": ["code"],
                }
            ],
        },
    )
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id="run-dispatch-context",
        artifact_ref="artifact:lane_graph",
    )
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "tui-command-dashboard",
                        "resolution_id": resolution.id,
                        "worktree": str(tmp_path / "lane-worktree"),
                        "status": "pending",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=object(),
        worktree=tmp_path,
        lanes_path=lanes_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.dispatched == 1
    handoff = next(
        msg
        for msg in ChatStore(tmp_path / "chat.db").list_messages(conversation_id)
        if msg.envelope_type == "dispatch_handoff"
    )
    assert "Production TUI closure" in handoff.content
    assert "Improve xmuse TUI slash commands" in handoff.content
    assert "Approved production TUI closure work" in handoff.content
    envelope = handoff.envelope_json or {}
    assert envelope["proposal"]["id"] == proposal.id
    assert envelope["resolution"]["id"] == resolution.id
    assert envelope["resolution"]["content"]["summary"] == "Production TUI closure"
    assert envelope["dispatch_queue_entry_id"] == entry.entry_id


@pytest.mark.asyncio
async def test_dispatch_bridge_does_not_consume_older_unread_chat(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    chat = ChatStore(tmp_path / "chat.db")
    older_message = chat.add_message(
        conversation_id,
        author="human",
        role="human",
        content="@execute older ordinary chat",
    )
    from xmuse_core.chat.inbox_store import ChatInboxStore

    older_item = ChatInboxStore(tmp_path / "chat.db").create_item(
        conversation_id=conversation_id,
        target_participant_id="execute-participant",
        target_role="execute",
        target_address="@execute",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=older_message.id,
        item_type="mention",
        payload={"content": "@execute older ordinary chat", "mention": "@execute"},
    )
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-specific-dispatch",
        resolution_id="resolution-specific-dispatch",
        collaboration_run_id="collab-specific-dispatch",
        artifact_ref="artifact:lane_graph",
    )
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-specific-dispatch",
                        "resolution_id": "resolution-specific-dispatch",
                        "worktree": str(tmp_path / "lane-worktree"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=object(),
        worktree=tmp_path,
        lanes_path=lanes_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.dispatched == 1
    assert ChatInboxStore(tmp_path / "chat.db").get(older_item.id).status == "unread"
    messages = ChatStore(tmp_path / "chat.db").list_messages(conversation_id)
    handoff = [msg for msg in messages if msg.envelope_type == "dispatch_handoff"]
    assert len(handoff) == 1
    assert (handoff[0].envelope_json or {})["dispatch_queue_entry_id"] == entry.entry_id


@pytest.mark.asyncio
async def test_dispatch_bridge_fails_entry_without_lane_worker_projection(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-missing-lane",
        resolution_id="resolution-missing-lane",
        collaboration_run_id="collab-missing-lane",
        artifact_ref="artifact:lane_graph",
    )
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=object(),
        worktree=tmp_path,
        lanes_path=tmp_path / "feature_lanes.json",
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.claimed == 1
    assert outcome.dispatched == 0
    assert outcome.failed == 1
    reloaded = ChatDispatchQueueStore(tmp_path / "chat.db").get(entry.entry_id)
    assert reloaded.status == "failed"
    assert reloaded.failure_reason == "lane_worker_projection_missing"
    messages = ChatStore(tmp_path / "chat.db").list_messages(conversation_id)
    assert [msg for msg in messages if msg.envelope_type == "dispatch_handoff"] == []


def test_dispatch_queue_reclaims_stale_processing_entry(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    queue = ChatDispatchQueueStore(tmp_path / "chat.db")
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-stale",
        resolution_id="resolution-stale",
        collaboration_run_id="collab-stale",
        artifact_ref="artifact:lane_graph",
    )
    first_claim = queue.claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="dead-dispatch-worker",
    )
    assert first_claim is not None
    assert first_claim.entry_id == entry.entry_id

    reclaimed = queue.claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="replacement-dispatch-worker",
        claim_ttl_s=0,
    )

    assert reclaimed is not None
    assert reclaimed.entry_id == entry.entry_id
    assert reclaimed.status == "processing"
    assert reclaimed.claimed_by == "replacement-dispatch-worker"


def test_proposal_approval_rejects_blank_execute_confirmation(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Reject blank execute confirmation",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm feasibility with evidence.",
        context_refs=[],
        idempotency_key="blank-execute-confirmation",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="execute",
        content="   ",
        response_status="received",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Blank execute response is not enough",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-blank-execute",
                            "prompt": "Do not dispatch on blank execute response.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [f"collaboration:{run.run_id}"],
        },
    )
    assert proposal.status_code == 201

    blocked = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Blank execute confirmation must not dispatch",
        },
    )

    assert blocked.status_code == 400
    assert blocked.json()["detail"]["message"] == "blocked_execute_not_confirmed"
