from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.collaboration_contracts import (
    CollaborationStatus,
    DispatchGateDecision,
)
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_bridge import ChatDispatchBridge
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_scheduler import PeerChatScheduler
from xmuse_core.chat.peer_service import PeerChatError, PeerChatService
from xmuse_core.chat.review_trigger_verdicts import build_review_trigger_verdict_envelope
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.integrations.a2a_provider_client import A2AProviderTaskRequest
from xmuse_core.integrations.a2a_sdk_boundary import NormalizedA2ATaskResult
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.structuring.graph_store import LaneGraphStore


class _DispatchBridgeGodLayer:
    def __init__(
        self,
        db_path: Path,
        *,
        write_back: bool = True,
        completion_content: str = (
            "DISPATCH_ACKNOWLEDGED\nDispatch entry acknowledged."
        ),
    ) -> None:
        self.db_path = db_path
        self.write_back = write_back
        self.completion_content = completion_content
        self.sent: list[tuple[str, str, str, str, str | None]] = []

    async def ensure_conversation_session(self, **kwargs):
        participant_id = str(kwargs["participant_id"])
        return type("Record", (), {"god_session_id": f"god-{participant_id}"})()

    async def send_message(
        self,
        god_session_id,
        message_type,
        prompt,
        context,
        request_id=None,
    ):
        self.sent.append((god_session_id, message_type, prompt, context, request_id))

    async def receive_message(self, god_session_id):
        if not self.write_back:
            return type("Message", (), {"type": "result", "status": "success"})()
        context = json.loads(self.sent[-1][3])
        inbox_item = context["inbox_item"]
        participant_id = context["participant_id"]
        message = ChatStore(self.db_path).add_message(
            inbox_item["conversation_id"],
            author=participant_id,
            role="assistant",
            content=self.completion_content,
            envelope_type="dispatch_result",
            envelope_json={
                "type": "dispatch_result",
                "source_inbox_item_id": inbox_item["id"],
            },
        )
        from xmuse_core.chat.inbox_store import ChatInboxStore

        ChatInboxStore(self.db_path).mark_read(
            inbox_item["id"],
            responded_message_id=message.id,
        )
        PeerTurnLatencyTraceStore(self.db_path).record_mcp_tool_stage(
            conversation_id=inbox_item["conversation_id"],
            inbox_item_id=inbox_item["id"],
            tool_name="chat_post_message",
            called_at=1.0,
        )
        return type(
            "Message",
            (),
            {
                "type": "result",
                "status": "success",
                "artifacts": {
                    "latency_stages": {
                        "codex_app_server_turn_start": {"at": 1.0},
                        "chat_post_message": {"at": 1.1},
                    }
                },
            },
        )()


class _A2AGroupchatRuntimeClient:
    def __init__(self) -> None:
        self.task_types: list[str] = []

    async def invoke_task(
        self,
        request: A2AProviderTaskRequest,
    ) -> NormalizedA2ATaskResult:
        task_type = str(request.metadata.get("xmuse_task_type") or "")
        self.task_types.append(task_type)
        runtime_context = request.metadata.get("xmuse_runtime_context")
        runtime_context = runtime_context if isinstance(runtime_context, dict) else {}
        metadata: dict[str, object] = {}
        content = ""
        if task_type == "review":
            review_trigger_inbox_id = str(runtime_context.get("inbox_item_id") or "")
            source_message_id = str(runtime_context.get("source_message_id") or "")
            proposal_id = _line_value(request.content, "Proposal id:")
            metadata["xmuse_review_trigger_verdict"] = {
                "type": "review_trigger_verdict",
                "review_trigger_inbox_id": review_trigger_inbox_id,
                "source_message_id": source_message_id,
                "proposal_id": proposal_id,
                "decision": "dispatch_allowed",
                "summary": "A2A review linked the durable proposal and trigger ids.",
                "evidence_refs": [
                    f"inbox:{review_trigger_inbox_id}",
                    f"proposal:{proposal_id}",
                    f"a2a_task:{request.task_id}",
                ],
                "authority": "chat.db/inbox/review_trigger_verdict",
                "a2a_is_authority": False,
            }
            content = "A2A review verdict: dispatch allowed."
        elif task_type == "bounded_code_writing":
            dispatch_entry_id = _line_value(request.content, "- Dispatch entry:")
            content = f"DISPATCH_ACKNOWLEDGED {dispatch_entry_id} via A2A execute peer."
        else:
            metadata["xmuse_proposal"] = {
                "proposal_type": "lane_graph",
                "summary": "A2A dispatchable lane_graph proposal",
                "content": {
                    "summary": "Prove the A2A dispatch handoff reaches execute ack.",
                    "lanes": [
                        {
                            "feature_id": "a2a-dispatch-ack-runtime-probe",
                            "prompt": (
                                "Acknowledge dispatch without claiming code execution."
                            ),
                            "depends_on": [],
                            "capabilities": ["code", "test"],
                        }
                    ],
                },
                "references": ["artifact:a2a-dispatchable-proposal"],
            }
            content = "Remote A2A architect returned a dispatchable lane_graph proposal."
        return NormalizedA2ATaskResult(
            task_id=request.task_id,
            context_id=request.context_id,
            state="TASK_STATE_COMPLETED",
            disposition="completed",
            terminal=True,
            content=content,
            metadata=metadata,
            source_refs=(
                f"a2a_task:{request.task_id}",
                f"a2a_context:{request.context_id}",
            ),
            jsonrpc_id=request.task_id,
        )


def _line_value(text: str, prefix: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip()
    return ""


def _conversation(tmp_path: Path) -> str:
    chat = ChatStore(tmp_path / "chat.db")
    return chat.create_conversation("V14 runtime").id


def _execute_participant(tmp_path: Path, conversation_id: str):
    return ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )


def _conversation_participants_by_role(tmp_path: Path, conversation_id: str):
    return {
        participant.role: participant
        for participant in ParticipantStore(tmp_path / "chat.db").list_by_conversation(
            conversation_id
        )
    }


def _conversation_sessions_by_role(tmp_path: Path, conversation_id: str) -> dict[str, str]:
    return {
        session.role: session.god_session_id
        for session in GodSessionRegistry(tmp_path / "god_sessions.json").list()
        if session.conversation_id == conversation_id
    }


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


@pytest.mark.asyncio
async def test_groupchat_proposal_approval_dispatch_and_review_closure_authority_path(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    service = PeerChatService(db)
    created = service.create_conversation(title="Proposal dispatch bridge")
    conversation_id = created["conversation"]["id"]
    participants = _conversation_participants_by_role(tmp_path, conversation_id)
    sessions = _conversation_sessions_by_role(tmp_path, conversation_id)

    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content=(
            "@architect propose the smallest auditable authority bridge from "
            "groupchat decision to dispatch."
        ),
        client_request_id="bridge-intake",
    )
    run_payload = service.create_collaboration_request(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["architect"].participant_id,
        god_session_id=sessions["architect"],
        client_request_id="bridge-collaboration",
        goal="Bridge approved groupchat proposal into dispatch authority.",
        targets=["review", "execute"],
        callback_target="architect",
        question="Can this bounded lane graph safely enter dispatch?",
        context_refs=[f"intake_message:{intake.message.id}"],
        idempotency_key="bridge-collaboration",
        timeout_s=480,
    )
    run_id = run_payload["run"]["run_id"]
    service.record_collaboration_response(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["review"].participant_id,
        god_session_id=sessions["review"],
        run_id=run_id,
        content="Review verdict: no dispatch veto for this bounded bridge.",
    )
    service.record_collaboration_response(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["execute"].participant_id,
        god_session_id=sessions["execute"],
        run_id=run_id,
        content=json.dumps(
            {
                "type": "execute_feasibility_verdict",
                "status": "executable",
                "execution_performed": False,
                "summary": "The bridge is bounded and can be dispatched.",
                "evidence_refs": [f"collaboration:{run_id}"],
            }
        ),
    )
    proposal = service.emit_proposal(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["architect"].participant_id,
        god_session_id=sessions["architect"],
        client_request_id="bridge-proposal",
        summary="Bridge groupchat proposal approval into dispatch authority",
        lanes=[
            {
                "feature_id": "bridge-proposal-dispatch-authority",
                "prompt": (
                    "Connect an approved groupchat lane_graph proposal to the "
                    "existing dispatch authority path."
                ),
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=[f"intake_message:{intake.message.id}", f"collaboration:{run_id}"],
    )
    review_trigger = next(
        item
        for item in ChatInboxStore(db).list_by_conversation(conversation_id)
        if item.target_participant_id == participants["review"].participant_id
        and item.item_type == "review_trigger"
        and item.payload.get("source_message_id") == proposal["message"]["id"]
    )
    service.post_god_message(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["review"].participant_id,
        god_session_id=sessions["review"],
        client_request_id="bridge-proposal-review-gate",
        content="No veto; proposal may proceed to explicit approval.",
        envelope=build_review_trigger_verdict_envelope(
            review_trigger_inbox_id=review_trigger.id,
            source_message_id=review_trigger.source_message_id,
            proposal_id=proposal["proposal"]["id"],
            decision="dispatch_allowed",
            summary="No veto; proposal may proceed to explicit approval.",
            evidence_refs=[
                f"inbox:{review_trigger.id}",
                f"collaboration:{run_id}",
            ],
        ),
        reply_to_inbox_item_id=review_trigger.id,
    )

    approved = TestClient(create_app(tmp_path)).post(
        f"/api/chat/proposals/{proposal['proposal']['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve the dispatch authority bridge.",
        },
    )

    assert approved.status_code == 200, approved.json()
    resolution_id = approved.json()["id"]
    graph = LaneGraphStore(tmp_path / "lane_graphs").get(f"{resolution_id}-graph-v1")
    assert graph.lanes[0].feature_id == "bridge-proposal-dispatch-authority"
    queued_entry = ChatDispatchQueueStore(db).list_entries(conversation_id)[0]
    assert queued_entry.status == "queued"
    assert queued_entry.proposal_id == proposal["proposal"]["id"]
    assert queued_entry.resolution_id == resolution_id
    assert queued_entry.collaboration_run_id == run_id

    bridge = ChatDispatchBridge(
        db_path=db,
        god_layer=_DispatchBridgeGodLayer(db),
        worktree=tmp_path,
        bridge_id="bridge-authority-test",
        response_wait_s=0.1,
    )
    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.dispatched == 1
    dispatched_entry = ChatDispatchQueueStore(db).get(queued_entry.entry_id)
    assert dispatched_entry.status == "dispatched"
    assert dispatched_entry.provider_run_ref == (
        f"peer_ack:execute:{participants['execute'].participant_id}"
    )
    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.DISPATCHED
    assert spine.dispatch_item_id == queued_entry.entry_id
    assert dispatched_entry.dispatch_evidence in spine.execution_evidence_refs

    review = service.post_god_message(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["review"].participant_id,
        god_session_id=sessions["review"],
        client_request_id="bridge-review-closure",
        content=(
            "Review verdict: acceptable, no veto for the dispatch authority bridge."
        ),
        envelope={
            "type": "review_closure",
            "resolution_id": resolution_id,
            "decision": "merge",
            "dispatch_queue_entry_id": queued_entry.entry_id,
        },
    )

    reviewed_spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert reviewed_spine.status is AcceptanceSpineStatus.REVIEWED
    assert reviewed_spine.review_verdict_ref == (
        f"chat:message:{review['message']['id']}"
    )


def test_review_closure_requires_review_participant_and_resolution_ref(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    service = PeerChatService(db)
    created = service.create_conversation(title="Review closure authority")
    conversation_id = created["conversation"]["id"]
    participants = _conversation_participants_by_role(tmp_path, conversation_id)
    sessions = _conversation_sessions_by_role(tmp_path, conversation_id)

    with pytest.raises(PeerChatError, match="invalid_review_closure"):
        service.post_god_message(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participants["review"].participant_id,
            god_session_id=sessions["review"],
            client_request_id="missing-resolution",
            content="Review verdict: missing target resolution.",
            envelope={"type": "review_closure", "decision": "merge"},
        )

    with pytest.raises(PeerChatError, match="review_closure_authority_forbidden"):
        service.post_god_message(
            registry_path=registry_path,
            conversation_id=conversation_id,
            participant_id=participants["execute"].participant_id,
            god_session_id=sessions["execute"],
            client_request_id="wrong-role",
            content="Review verdict: wrong role.",
            envelope={"type": "review_closure", "resolution_id": "res_missing"},
        )


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


def test_collaboration_active_target_cascade_matches_address_targets(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")

    store.create_request(
        conversation_id=conversation_id,
        goal="First request",
        initiator="architect",
        targets=["@review"],
        callback_target="@architect",
        question="Review this.",
        context_refs=[],
        idempotency_key="outer-address",
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
            idempotency_key="nested-address",
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
                "execution_performed": False,
                "summary": "Executable after blocker visibility was added.",
                "evidence_refs": ["tui:dispatch-visibility-added"],
            }
        ),
        response_status="received",
    )
    allowed = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
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
                "execution_performed": False,
                "summary": "Lane graph has clear scope and required evidence.",
                "evidence_refs": ["proposal:lane-v14-needs-execute"],
            }
        ),
        response_status="received",
    )
    allowed = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["architect"],
            "approval_mode": "auto",
            "goal_summary": "Execute confirmed feasibility",
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
                "execution_performed": False,
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


def test_lane_graph_approval_uses_opencode_review_peer_for_final_hold_runtime(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="review",
        display_name="Review GOD",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Use the registered review peer",
                    "lanes": [
                        {
                            "feature_id": "lane-review-runtime-from-peer",
                            "prompt": "Review through the registered OpenCode peer.",
                            "depends_on": [],
                            "capabilities": ["code"],
                            "review_runtime": "human_final_hold",
                            "final_action": "no-auto-merge",
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
            "goal_summary": "Approve review peer runtime projection",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["content"]["lanes"][0]["review_runtime"] == "opencode"
    graph_id = f"{approved.json()['id']}-graph-v{approved.json()['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    assert graph["lanes"][0]["feature_id"] == "lane-review-runtime-from-peer"
    assert graph["lanes"][0]["review_runtime"] == "opencode"
    assert graph["lanes"][0]["final_action"] == "no-auto-merge"
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    assert lanes[0]["feature_id"] == "lane-review-runtime-from-peer"
    assert lanes[0]["review_runtime"] == "opencode"


def test_lane_graph_approval_uses_opencode_review_peer_display_name_runtime(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="review",
        display_name="review-god",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Use the named review peer",
                    "lanes": [
                        {
                            "feature_id": "lane-review-runtime-display-name",
                            "prompt": "Review through review-god.",
                            "depends_on": [],
                            "capabilities": ["code"],
                            "review_runtime": "review-god",
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
            "goal_summary": "Approve review peer display name projection",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["content"]["lanes"][0]["review_runtime"] == "opencode"
    graph_id = f"{approved.json()['id']}-graph-v{approved.json()['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    assert graph["lanes"][0]["feature_id"] == "lane-review-runtime-display-name"
    assert graph["lanes"][0]["review_runtime"] == "opencode"
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    assert lanes[0]["feature_id"] == "lane-review-runtime-display-name"
    assert lanes[0]["review_runtime"] == "opencode"


def test_lane_graph_approval_canonicalizes_opencode_review_runtime_case(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="review",
        display_name="review-god",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Use canonical OpenCode runtime",
                    "lanes": [
                        {
                            "feature_id": "lane-review-runtime-opencode-case",
                            "prompt": "Review through OpenCode.",
                            "depends_on": [],
                            "capabilities": ["code"],
                            "review_runtime": "OpenCode",
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
            "goal_summary": "Approve canonical OpenCode runtime projection",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["content"]["lanes"][0]["review_runtime"] == "opencode"
    graph_id = f"{approved.json()['id']}-graph-v{approved.json()['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    assert graph["lanes"][0]["feature_id"] == "lane-review-runtime-opencode-case"
    assert graph["lanes"][0]["review_runtime"] == "opencode"
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    assert lanes[0]["feature_id"] == "lane-review-runtime-opencode-case"
    assert lanes[0]["review_runtime"] == "opencode"


def test_lane_graph_approval_uses_a2a_review_peer_for_final_hold_runtime(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="review",
        display_name="Remote A2A Review GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    client = TestClient(create_app(tmp_path))
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Use the registered A2A review peer",
                    "lanes": [
                        {
                            "feature_id": "lane-review-runtime-from-a2a-peer",
                            "prompt": "Review through the remote A2A peer.",
                            "depends_on": [],
                            "capabilities": ["code"],
                            "review_runtime": "human_final_hold",
                            "final_action": "no-auto-merge",
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
            "goal_summary": "Approve A2A review peer runtime projection",
        },
    )

    assert approved.status_code == 200
    assert approved.json()["content"]["lanes"][0]["review_runtime"] == "a2a"
    graph_id = f"{approved.json()['id']}-graph-v{approved.json()['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    assert graph["lanes"][0]["feature_id"] == "lane-review-runtime-from-a2a-peer"
    assert graph["lanes"][0]["review_runtime"] == "a2a"
    assert graph["lanes"][0]["final_action"] == "no-auto-merge"
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    assert lanes[0]["feature_id"] == "lane-review-runtime-from-a2a-peer"
    assert lanes[0]["review_runtime"] == "a2a"


def test_lane_graph_approval_metadata_preserves_proposal_lane_authority(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    client = TestClient(create_app(tmp_path))
    lane_prompt = (
        "Post-PR56 latest-main local runtime fullchain stability proof. "
        "Call query_knowledge, run package-boundary pytest, make no edits, "
        "then update lane status with bounded evidence."
    )
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect",
            "proposal_type": "lane_graph",
            "content": json.dumps(
                {
                    "summary": "Preserve accepted lane graph",
                    "lanes": [
                        {
                            "feature_id": "loop25r-main-package-boundary-final-hold",
                            "prompt": lane_prompt,
                            "depends_on": [],
                            "capabilities": ["python", "pytest", "xmuse_mcp"],
                            "review_runtime": "opencode",
                            "final_action": "no-auto-merge",
                            "proof_boundary": "local_runtime_proof",
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
            "approved_by": ["human-operator"],
            "approval_mode": "manual",
            "goal_summary": "Approve with supplemental proof metadata",
            "content": {
                "final_action": "no-auto-merge",
                "proof_boundary": "local_runtime_proof",
                "forbidden_claims": ["github_review_truth", "full_l1_l11_closure"],
            },
        },
    )

    assert approved.status_code == 200
    resolution = approved.json()
    assert resolution["content"]["type"] == "lane_graph"
    assert resolution["content"]["forbidden_claims"] == [
        "github_review_truth",
        "full_l1_l11_closure",
    ]
    assert resolution["content"]["lanes"][0]["feature_id"] == (
        "loop25r-main-package-boundary-final-hold"
    )

    graph_id = f"{resolution['id']}-graph-v{resolution['version']}"
    graph = json.loads((tmp_path / "lane_graphs" / f"{graph_id}.json").read_text())
    assert graph["lanes"][0]["feature_id"] == "loop25r-main-package-boundary-final-hold"
    assert graph["lanes"][0]["prompt"] == lane_prompt
    assert graph["lanes"][0]["capabilities"] == ["python", "pytest", "xmuse_mcp"]
    assert graph["lanes"][0]["review_runtime"] == "opencode"
    assert graph["lanes"][0]["final_action"] == "no-auto-merge"
    assert graph["lanes"][0]["proof_boundary"] == "local_runtime_proof"

    lanes = json.loads((tmp_path / "feature_lanes.json").read_text())["lanes"]
    assert lanes[0]["feature_id"] == "loop25r-main-package-boundary-final-hold"
    assert lanes[0]["capabilities"] == ["python", "pytest", "xmuse_mcp"]
    assert lanes[0]["review_runtime"] == "opencode"
    assert lanes[0]["final_action"] == "no-auto-merge"
    assert lanes[0]["proof_boundary"] == "local_runtime_proof"
    assert (tmp_path / lanes[0]["prompt_ref"]).read_text(encoding="utf-8") == lane_prompt


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


def test_proposal_approval_accepts_embedded_provider_execute_verdict(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    store = ChatCollaborationStore(tmp_path / "chat.db")
    run = store.create_request(
        conversation_id=conversation_id,
        goal="Accept embedded execute confirmation",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="Confirm feasibility with typed evidence.",
        context_refs=[],
        idempotency_key="embedded-execute-confirmation",
        timeout_s=480,
    )
    store.record_response(
        run.run_id,
        target="execute",
        content=(
            "Execution feasibility verdict:\n\n"
            "```json\n"
            + json.dumps(
                {
                    "type": "execute_feasibility_verdict",
                    "status": "executable",
                    "execution_performed": False,
                    "summary": "The lane is bounded and has a focused verification gate.",
                    "evidence_refs": ["message:intake", "proposal:embedded-execute"],
                }
            )
            + "\n```"
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
                    "summary": "Embedded execute response is enough",
                    "lanes": [
                        {
                            "feature_id": "lane-v14-embedded-execute",
                            "prompt": "Dispatch after embedded typed execute response.",
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
            "goal_summary": "Embedded execute confirmation can dispatch",
        },
    )

    assert approved.status_code == 200
    entries = ChatDispatchQueueStore(tmp_path / "chat.db").list_entries(conversation_id)
    assert len(entries) == 1
    assert entries[0].collaboration_run_id == run.run_id


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
                "execution_performed": False,
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
                "execution_performed": False,
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
                "execution_performed": False,
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
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))[
        "lanes"
    ]
    assert lanes[0]["feature_id"] == "lane-v14-dispatch-queue"
    assert lanes[0]["feature_scope_id"] == f"lane_graph:{resolution_id}-graph-v1"

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
async def test_a2a_groupchat_review_approval_dispatch_reaches_execute_ack(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    conversation_id = _conversation(tmp_path)
    participants = ParticipantStore(db_path)
    participants.add(
        conversation_id=conversation_id,
        role="architect",
        display_name="Remote A2A Architect",
        cli_kind="a2a",
        model="a2a-remote",
    )
    participants.add(
        conversation_id=conversation_id,
        role="review",
        display_name="Remote A2A Review",
        cli_kind="a2a",
        model="a2a-remote",
    )
    execute = participants.add(
        conversation_id=conversation_id,
        role="execute",
        display_name="Remote A2A Execute",
        cli_kind="a2a",
        model="a2a-remote",
    )
    intake = PeerChatService(db_path).post_human_message(
        conversation_id=conversation_id,
        author="operator",
        content=(
            "@architect Propose the smallest dispatchable A2A lane and keep "
            "chat.db gates explicit."
        ),
        client_request_id="runtime-human-a2a-dispatch-001",
    )
    a2a_client = _A2AGroupchatRuntimeClient()
    provider_service = RunnerProviderService(
        a2a_provider_endpoint_url="http://a2a-runtime.test/tasks/send",
        a2a_task_client=a2a_client,
    )
    scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=object(),
        worktree=tmp_path,
        scheduler_id="a2a-runtime-probe",
        response_wait_s=0.1,
        provider_service=provider_service,
    )

    proposal_outcome = await scheduler.tick_once()
    review_outcome = await scheduler.tick_once()

    assert proposal_outcome.happy_path == 1
    assert review_outcome.happy_path == 1
    proposal = ChatStore(db_path).list_proposals(conversation_id)[0]
    spine = AcceptanceSpineStore(db_path).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.REVIEW_CLEARED
    assert spine.proposal_id == proposal.id
    approval = TestClient(create_app(tmp_path)).post(
        f"/api/chat/proposals/{proposal.id}/approve",
        json={
            "approved_by": ["operator"],
            "approval_mode": "runtime_probe_manual_approval_no_auto_merge",
            "goal_summary": "Approve A2A runtime probe after durable review verdict.",
        },
    )
    assert approval.status_code == 200, approval.text
    queued = ChatDispatchQueueStore(db_path).list_entries(conversation_id)
    assert len(queued) == 1
    assert queued[0].status == "queued"
    bridge = ChatDispatchBridge(
        db_path=db_path,
        god_layer=object(),
        worktree=tmp_path,
        bridge_id="a2a-dispatch-bridge",
        response_wait_s=0.1,
        provider_service=provider_service,
    )

    dispatch_outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert dispatch_outcome.claimed == 1
    assert dispatch_outcome.dispatched == 1
    assert dispatch_outcome.failed == 0
    dispatched = ChatDispatchQueueStore(db_path).get(queued[0].entry_id)
    assert dispatched.status == "dispatched"
    assert dispatched.provider_run_ref == f"peer_ack:execute:{execute.participant_id}"
    assert dispatched.dispatch_evidence.startswith("mcp_writeback:")
    spine = AcceptanceSpineStore(db_path).get_by_intake_message(intake.message.id)
    assert spine.status is AcceptanceSpineStatus.DISPATCHED
    assert spine.dispatch_item_id == queued[0].entry_id
    assert spine.execution_evidence_refs == [
        f"peer_ack:execute:{execute.participant_id}",
        dispatched.dispatch_evidence,
    ]
    assert a2a_client.task_types == [
        "bounded_deliberation",
        "review",
        "bounded_code_writing",
    ]
    dispatch_messages = [
        message
        for message in ChatStore(db_path).list_messages(conversation_id)
        if message.envelope_type == "a2a_provider_result"
        and "DISPATCH_ACKNOWLEDGED" in message.content
    ]
    assert len(dispatch_messages) == 1


@pytest.mark.asyncio
async def test_dispatch_bridge_acknowledges_gated_entry_through_execute_peer(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    execute = _execute_participant(tmp_path, conversation_id)
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-real-provider",
        resolution_id="resolution-real-provider",
        collaboration_run_id="collab-real-provider",
        artifact_ref="artifact:lane_graph",
    )
    god_layer = _DispatchBridgeGodLayer(tmp_path / "chat.db")
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=god_layer,
        worktree=tmp_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.claimed == 1
    assert outcome.dispatched == 1
    assert outcome.failed == 0
    assert god_layer.sent
    god_session_id, message_type, prompt, context_json, request_id = god_layer.sent[0]
    context = json.loads(context_json)
    assert god_session_id == f"god-{execute.participant_id}"
    assert message_type == "peer_chat_nudge"
    assert request_id == context["inbox_item"]["id"]
    assert "reply_to_inbox_item_id=xmuse_context.inbox_item.id" in prompt
    assert context["inbox_item"]["item_type"] == "dispatch"
    assert context["inbox_item"]["payload"]["dispatch_queue_entry_id"] == entry.entry_id
    reloaded = ChatDispatchQueueStore(tmp_path / "chat.db").get(entry.entry_id)
    assert reloaded.status == "dispatched"
    assert reloaded.provider_run_ref == f"peer_ack:execute:{execute.participant_id}"
    assert reloaded.dispatch_evidence.startswith("mcp_writeback:")
    inspector = build_conversation_inspector_payload(conversation_id, tmp_path)
    assert inspector["dispatch_queue"]["dispatched"] == 1


@pytest.mark.asyncio
async def test_dispatch_bridge_prompt_includes_approved_artifact_context(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _execute_participant(tmp_path, conversation_id)
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
    god_layer = _DispatchBridgeGodLayer(tmp_path / "chat.db")
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=god_layer,
        worktree=tmp_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.dispatched == 1
    _, _, prompt, context_json, _ = god_layer.sent[0]
    context = json.loads(context_json)
    assert "chat-plane handoff notice" in prompt
    assert "must not claim execution" in prompt
    assert "Do not edit files, run tests" in prompt
    assert "do not claim that MCP writeback tools are unavailable" in prompt
    assert "must call the MCP tool chat_post_message exactly once" in prompt
    assert "plain text acknowledgement is not a durable dispatch acknowledgement" in prompt
    assert "still call chat_post_message" in prompt
    assert "DISPATCH_ACKNOWLEDGED" in prompt
    assert "DISPATCH_ACK_FAILED" in prompt
    assert "DISPATCH_COMPLETED" not in prompt
    assert "Production TUI closure" in prompt
    assert "Improve xmuse TUI slash commands" in prompt
    assert "Approved production TUI closure work" in prompt
    assert context["inbox_item"]["payload"]["proposal"]["id"] == proposal.id
    assert context["inbox_item"]["payload"]["resolution"]["id"] == resolution.id
    assert context["inbox_item"]["payload"]["resolution"]["content"]["summary"] == (
        "Production TUI closure"
    )
    assert context["inbox_item"]["payload"]["dispatch_queue_entry_id"] == entry.entry_id


@pytest.mark.asyncio
async def test_dispatch_bridge_dispatches_its_item_not_older_unread_chat(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    execute = _execute_participant(tmp_path, conversation_id)
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
        target_participant_id=execute.participant_id,
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
    god_layer = _DispatchBridgeGodLayer(tmp_path / "chat.db")
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=god_layer,
        worktree=tmp_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.dispatched == 1
    sent_context = json.loads(god_layer.sent[0][3])
    assert sent_context["inbox_item"]["id"] != older_item.id
    assert sent_context["inbox_item"]["item_type"] == "dispatch"
    assert sent_context["inbox_item"]["payload"]["dispatch_queue_entry_id"] == entry.entry_id
    assert ChatInboxStore(tmp_path / "chat.db").get(older_item.id).status == "unread"


@pytest.mark.asyncio
async def test_dispatch_bridge_rejects_progress_only_writeback(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _execute_participant(tmp_path, conversation_id)
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-progress-only",
        resolution_id="resolution-progress-only",
        collaboration_run_id="collab-progress-only",
        artifact_ref="artifact:lane_graph",
    )
    god_layer = _DispatchBridgeGodLayer(
        tmp_path / "chat.db",
        completion_content=(
            "I have claimed the task and will update after implementation."
        ),
    )
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=god_layer,
        worktree=tmp_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.claimed == 1
    assert outcome.dispatched == 0
    assert outcome.failed == 1
    reloaded = ChatDispatchQueueStore(tmp_path / "chat.db").get(entry.entry_id)
    assert reloaded.status == "failed"
    assert reloaded.failure_reason == "dispatch_ack_marker_missing"


@pytest.mark.asyncio
async def test_dispatch_bridge_fails_entry_without_mcp_writeback(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _execute_participant(tmp_path, conversation_id)
    entry = ChatDispatchQueueStore(tmp_path / "chat.db").enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id="proposal-no-writeback",
        resolution_id="resolution-no-writeback",
        collaboration_run_id="collab-no-writeback",
        artifact_ref="artifact:lane_graph",
    )
    bridge = ChatDispatchBridge(
        db_path=tmp_path / "chat.db",
        god_layer=_DispatchBridgeGodLayer(tmp_path / "chat.db", write_back=False),
        worktree=tmp_path,
        bridge_id="dispatch-bridge-test",
        response_wait_s=0.1,
    )

    outcome = await bridge.tick_once(conversation_id=conversation_id)

    assert outcome.claimed == 1
    assert outcome.dispatched == 0
    assert outcome.failed == 1
    reloaded = ChatDispatchQueueStore(tmp_path / "chat.db").get(entry.entry_id)
    assert reloaded.status == "failed"
    assert reloaded.failure_reason == "peer_no_inbox_side_effect"


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
