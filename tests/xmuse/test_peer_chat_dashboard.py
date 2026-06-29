import json
import sqlite3
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.dashboard_api import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.structuring.models import ReviewDecision, ReviewTask, ReviewVerdict
from xmuse_core.structuring.verdict_store import VerdictStore


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _without_failure_classification(boundary: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in boundary.items()
        if key not in {"taxonomy", "proof_level", "classification"}
    }


def _create_final_action_projection_fixture(tmp_path: Path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Final action UX")
    message = chat.add_message(conv.id, "Human", "human", "@architect run sentinel")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Final action lane","lanes":[{"feature_id":"lane-final"}]}',
        references=[message.id],
    )
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(conversation_id=conv.id, intake_message_id=message.id)
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=message.id,
        proposal_id=proposal.id,
    )
    spine_store.attach_verdict_for_proposal(
        proposal_id=proposal.id,
        verdict_ref="resolution:res-final-action",
    )
    spine_store.attach_lane_execution_for_resolution(
        resolution_id="res-final-action",
        evidence_refs=["lane_graph:res-final-action-graph-v1"],
    )
    spine_store.attach_review_verdict_for_resolution(
        resolution_id="res-final-action",
        review_verdict_ref="review_plane.json#verdict=verdict-final-action",
    )
    hold = FinalActionGateStore(tmp_path / "final_actions.json").create_hold(
        lane_id="lane-final",
        verdict_id="verdict-final-action",
        action="merge",
        target_status="reviewed",
        summary="Review accepted; operator must verify GitHub gate before merge.",
    )
    spine = spine_store.attach_final_action_for_review_verdict(
        review_verdict_ref="review_plane.json#verdict=verdict-final-action",
        final_action_ref=f"final_actions.json#hold={hold.id}",
    )
    assert spine is not None
    return conv, hold, spine


def test_dashboard_lists_peer_chat_conversations_with_drilldown_links(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect design")
    ChatInboxStore(db).create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )
    ChatInboxStore(db).claim_next(owner="sched-test")
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-architect",
                    "conversation_id": conv.id,
                    "participant_id": participant.participant_id,
                    "role": participant.role,
                    "status": "running",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/api/dashboard/peer-chat/conversations")

    assert response.status_code == 200
    item = response.json()["conversations"][0]
    assert item["id"] == conv.id
    assert item["unread_count"] == 0
    assert item["claimed_count"] == 1
    assert item["href"] == f"/dashboard/peer-chat/conversations/{conv.id}"
    assert item["participants"]["items"][0]["participant_id"] == participant.participant_id
    assert item["recent_messages"][0]["id"] == message.id
    assert item["sessions"][0]["href"] == "/dashboard/peer-chat/sessions/god-architect"


def test_dashboard_conversation_list_uses_isolated_workspace_fields(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    alpha = chat.create_conversation("Mission Alpha")
    beta = chat.create_conversation("Mission Beta")
    alpha_participant = ParticipantStore(db).add(
        conversation_id=alpha.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    beta_participant = ParticipantStore(db).add(
        conversation_id=beta.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    alpha_message = chat.add_message(alpha.id, "Human", "human", "@architect alpha plan")
    beta_message = chat.add_message(beta.id, "Human", "human", "@review beta plan")
    alpha_proposal = chat.create_proposal(
        conversation_id=alpha.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Alpha lanes","lanes":[{"feature_id":"alpha-lane"}]}',
        references=[alpha_message.id],
    )
    chat.create_proposal(
        conversation_id=beta.id,
        author="Review GOD",
        proposal_type="lane_graph",
        content='{"summary":"Beta lanes","lanes":[{"feature_id":"beta-lane"}]}',
        references=[beta_message.id],
    )
    inbox = ChatInboxStore(db)
    inbox.create_item(
        conversation_id=alpha.id,
        target_participant_id=alpha_participant.participant_id,
        target_role=alpha_participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=alpha_message.id,
        item_type="mention",
        payload={"content": alpha_message.content},
    )
    inbox.create_item(
        conversation_id=beta.id,
        target_participant_id=beta_participant.participant_id,
        target_role=beta_participant.role,
        target_address="@review",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=beta_message.id,
        item_type="mention",
        payload={"content": beta_message.content},
    )
    inbox.claim_next(owner="alpha-worker")
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-alpha",
                    "conversation_id": alpha.id,
                    "participant_id": alpha_participant.participant_id,
                    "role": alpha_participant.role,
                    "status": "running",
                },
                {
                    "god_session_id": "god-beta",
                    "conversation_id": beta.id,
                    "participant_id": beta_participant.participant_id,
                    "role": beta_participant.role,
                    "status": "running",
                },
            ]
        },
    )

    response = TestClient(create_app(tmp_path)).get("/api/dashboard/peer-chat/conversations")

    assert response.status_code == 200
    conversations = {item["id"]: item for item in response.json()["conversations"]}
    alpha_row = conversations[alpha.id]
    beta_row = conversations[beta.id]
    assert alpha_row["href"] == f"/dashboard/peer-chat/conversations/{alpha.id}"
    assert alpha_row["dashboard_href"] == alpha_row["href"]
    assert alpha_row["api_href"] == f"/api/dashboard/peer-chat/conversations/{alpha.id}"
    assert alpha_row["last_activity_at"]
    assert alpha_row["participants"]["items"][0]["participant_id"] == (
        alpha_participant.participant_id
    )
    assert alpha_row["inbox_counts"] == {"unread": 0, "claimed": 1}
    assert alpha_row["unread_count"] == 0
    assert alpha_row["claimed_count"] == 1
    assert alpha_row["linked_session_ids"] == ["god-alpha"]
    assert [session["god_session_id"] for session in alpha_row["sessions"]] == ["god-alpha"]
    assert [message["id"] for message in alpha_row["recent_messages"]] == [alpha_message.id]
    assert [message["id"] for message in beta_row["recent_messages"]] == [beta_message.id]
    assert alpha_proposal.id in [card["source_id"] for card in alpha_row["recent_cards"]]
    assert all("lanes" not in card for card in alpha_row["recent_cards"])
    assert "beta" not in json.dumps(alpha_row).lower()
    assert "alpha" not in json.dumps(beta_row).lower()


def test_dashboard_returns_conversation_inbox_audit(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect design")
    item = ChatInboxStore(db).create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation"]["id"] == conv.id
    assert payload["inbox_items"][0]["id"] == item.id
    assert payload["inbox_items"][0]["target_participant_id"] == participant.participant_id
    assert payload["inbox_items"][0]["href"] == f"/dashboard/peer-chat/inbox/{item.id}"


def test_dashboard_peer_chat_conversation_includes_compact_cards(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    chat.add_message(conv.id, "Human", "human", "Keep chat compact.")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Compact cards","lanes":[{"feature_id":"lane-a"}]}',
        references=["msg-source"],
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}")

    assert response.status_code == 200
    payload = response.json()
    assert [message["content"] for message in payload["messages"]] == ["Keep chat compact."]
    assert payload["cards"][0]["card_type"] == "proposal"
    assert payload["cards"][0]["source_id"] == proposal.id
    assert payload["cards"][0]["href"] == (
        f"/dashboard/peer-chat/conversations/{conv.id}#proposal-{proposal.id}"
    )
    assert payload["cards"][0]["api_href"] == f"/api/chat/proposals/{proposal.id}"


def test_dashboard_peer_chat_ux_projection_is_frontend_read_model(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission UX")
    architect = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    execute = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect plan UX")
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(conversation_id=conv.id, intake_message_id=message.id)
    inbox_item = ChatInboxStore(db).create_item(
        conversation_id=conv.id,
        target_participant_id=architect.participant_id,
        target_role=architect.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"UX lanes","lanes":[{"feature_id":"ux-lane"}]}',
        references=[message.id, "artifact:ux-plan"],
    )
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=message.id,
        proposal_id=proposal.id,
    )
    collaboration = ChatCollaborationStore(db)
    run = collaboration.create_request(
        conversation_id=conv.id,
        goal="Review UX projection",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="Is the projection enough for frontend?",
        context_refs=["proposal:ux"],
        idempotency_key=None,
        timeout_s=60,
    )
    blocker = collaboration.raise_blocker(
        run.run_id,
        issuer="review",
        severity="blocker",
        reason="Need dispatch visibility",
        affected_ref="proposal:ux",
        suggested_fix="Expose dispatch next action",
        blocks_dispatch=True,
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id="resolution-ux",
        collaboration_run_id=run.run_id,
        artifact_ref="artifact:ux-lane-graph",
        gate_refs=["collaboration:frontend-gate", "review_trigger_verdict:frontend-review"],
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-architect",
                    "conversation_id": conv.id,
                    "participant_id": architect.participant_id,
                    "role": architect.role,
                    "status": "running",
                    "provider_id": "codex",
                }
            ]
        },
    )
    long_memory_refs = [f"memoryos:sidecar:{index}:{'x' * 260}" for index in range(25)]
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id=inbox_item.id,
        participant_id=architect.participant_id,
        target_role=architect.role,
        god_session_id="god-architect",
        provider_session_id="provider-thread-architect",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        message_created_at=inbox_item.created_at,
        inbox_claimed_at=inbox_item.claimed_at,
        delivery_started_at=10.0,
        provider_turn_started_at=10.1,
        first_delta_at=10.2,
        writeback_at=10.5,
        total_latency_ms=500,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
        supporting_context={
            "memoryos_sidecar": {
                "status": "degraded",
                "authority": "memoryos_sidecar",
                "proof_level": "degraded",
                "namespace_uri": f"memory://conversation/{conv.id}",
                "degraded_reason": "memoryos_timeout",
                "source_refs": long_memory_refs,
                "continuity_attempt_ref": (
                    f"memory://conversation/{conv.id}/context/memoryos-sidecar-attempt"
                ),
                "text": "recall body must not be projected as frontend truth",
            }
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "peer_chat_ux_projection/v1"
    assert payload["projection_only"] is True
    assert payload["write_capabilities"] == []
    assert payload["source_authority"] == [
        "chat.db:conversations",
        "chat.db:messages",
        "chat.db:participants",
        "chat.db:chat_inbox_items",
        "chat.db:proposals",
        "chat.db:chat_dispatch_queue",
        "chat.db:collaboration_runs",
        "chat.db:collaboration_blockers",
        "chat.db:acceptance_spines",
        "chat.db:peer_turn_latency_traces",
        "review_plane.json",
        "final_actions.json",
        "final_action_prs.json",
        "github_gate_evidence.json",
        "active_sessions.json",
        "god_sessions.json",
    ]
    assert payload["conversation"]["id"] == conv.id
    assert payload["links"]["inspector_api_href"].endswith(f"/{conv.id}/inspector")
    proposal_card = next(card for card in payload["cards"] if card["detail_kind"] == "proposal")
    assert proposal_card["detail_api_href"] == f"/api/chat/proposals/{proposal.id}"
    assert "artifact:ux-plan" in proposal_card["source_refs"]
    agent_by_role = {agent["role"]: agent for agent in payload["agent_cards"]}
    assert agent_by_role["architect"]["participant_id"] == architect.participant_id
    assert agent_by_role["architect"]["inbox_counts"]["unread"] == 1
    assert agent_by_role["architect"]["session"]["god_session_id"] == "god-architect"
    assert agent_by_role["execute"]["participant_id"] == execute.participant_id
    worklist_by_id = {item["id"]: item for item in payload["worklist"]}
    assert worklist_by_id[inbox_item.id]["next_action"] == "deliver_peer_turn"
    assert worklist_by_id[inbox_item.id]["detail_kind"] == "inbox_item"
    assert worklist_by_id[dispatch.entry_id]["next_action"] == "dispatch_execute_peer"
    expected_dispatch_refs = [
        f"chat_dispatch_queue:{dispatch.entry_id}",
        f"proposal:{proposal.id}",
        "collaboration:frontend-gate",
        "review_trigger_verdict:frontend-review",
        "resolution:resolution-ux",
        f"collaboration:{run.run_id}",
        "artifact:ux-lane-graph",
    ]
    assert worklist_by_id[dispatch.entry_id]["source_refs"] == expected_dispatch_refs
    dispatch_entry = next(
        entry
        for entry in payload["dispatch_queue"]["entries"]
        if entry["entry_id"] == dispatch.entry_id
    )
    assert dispatch_entry["source_refs"] == expected_dispatch_refs
    assert dispatch_entry["authority_boundary"] == {
        "producer": "chat.db:chat_dispatch_queue",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "dispatch_queue_authority_not_execution_proof",
    }
    assert dispatch_entry["sidecar_continuity"] == {
        "producer": "chat.db:chat_dispatch_queue",
        "consumer": "memoryos_sidecar",
        "condition": "explicit_memoryos_configuration",
        "proof_boundary": "sidecar_continuity_not_execution_truth",
        "projection_only": True,
        "handoff_state": "contract_available",
        "source_refs": expected_dispatch_refs,
    }
    assert worklist_by_id[blocker.blocker_id]["next_action"] == "resolve_blocker"
    assert worklist_by_id[blocker.blocker_id]["source_refs"] == ["proposal:ux"]
    supporting_context = payload["supporting_context"]
    assert supporting_context["projection_only"] is True
    assert supporting_context["source_authority"] == [
        "chat.db:peer_turn_latency_traces.supporting_context_json"
    ]
    assert supporting_context["memoryos_sidecar"]["status_summary"] == {"degraded": 1}
    assert supporting_context["memoryos_sidecar"]["latest"] == [
        {
            "trace_id": f"peer_latency_{inbox_item.id}",
            "inbox_item_id": inbox_item.id,
            "participant_id": architect.participant_id,
            "target_role": architect.role,
            "status": "degraded",
            "authority": "memoryos_sidecar",
            "proof_level": "degraded",
            "namespace_uri": f"memory://conversation/{conv.id}",
            "degraded_reason": "memoryos_timeout",
            "source_refs": [ref[:240] for ref in long_memory_refs[:20]],
            "continuity_refs": [],
            "continuity_attempt_ref": (
                f"memory://conversation/{conv.id}/context/memoryos-sidecar-attempt"
            ),
        }
    ]
    assert "recall body" not in json.dumps(supporting_context)
    assert payload["closure_evidence"]["total"] == 1
    assert payload["closure_evidence"]["items"][0]["proposal_id"] == proposal.id


def test_dashboard_peer_chat_ux_projection_exposes_pending_final_action_hold(
    tmp_path: Path,
) -> None:
    conv, hold, spine = _create_final_action_projection_fixture(tmp_path)

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    assert "final_actions.json" in payload["source_authority"]
    assert payload["final_action_holds"] == {
        "source_authority": ["final_actions.json", "chat.db:acceptance_spines"],
        "projection_only": True,
        "total": 1,
        "pending": 1,
        "items": [
            {
                "id": hold.id,
                "lane_id": "lane-final",
                "verdict_id": "verdict-final-action",
                "action": "merge",
                "target_status": "reviewed",
                "status": "pending",
                "summary": "Review accepted; operator must verify GitHub gate before merge.",
                "resolved_by": None,
                "github_gate_evidence_ref": None,
                "github_gate_gap_ref": None,
                "source_refs": [
                    f"final_actions.json#hold={hold.id}",
                    "review_plane.json#verdict=verdict-final-action",
                    f"chat.db:acceptance_spines#spine={spine.spine_id}",
                ],
                "authority_boundary": {
                    "producer": "final_actions.json",
                    "consumer": "frontend.peer_chat_ux_projection",
                    "condition": "read_only_projection",
                    "proof_boundary": "final_action_hold_not_github_or_merge_truth",
                },
            }
        ],
    }
    worklist_by_id = {item["id"]: item for item in payload["worklist"]}
    assert worklist_by_id[hold.id] == {
        "kind": "final_action_hold",
        "id": hold.id,
        "status": "pending",
        "target_role": "operator",
        "created_at": None,
        "updated_at": None,
        "next_action": "verify_github_gate_and_resolve_final_action",
        "detail_kind": "final_action_hold",
        "detail_api_href": f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector",
        "source_refs": [
            f"final_actions.json#hold={hold.id}",
            "review_plane.json#verdict=verdict-final-action",
            f"chat.db:acceptance_spines#spine={spine.spine_id}",
        ],
        "compact_detail": {
            "action": "merge",
            "lane_id": "lane-final",
            "target_status": "reviewed",
            "github_gate_evidence_ref": None,
            "github_gate_gap_ref": None,
        },
    }


def test_dashboard_peer_chat_ux_projection_exposes_review_verdict_state(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Review verdict UX")
    intake = chat.add_message(conv.id, "Human", "human", "@architect ship reviewed lane")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Reviewed lane","lanes":[{"feature_id":"lane-review"}]}',
        references=[intake.id],
    )
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(conversation_id=conv.id, intake_message_id=intake.id)
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=intake.id,
        proposal_id=proposal.id,
    )
    spine_store.attach_verdict_for_proposal(
        proposal_id=proposal.id,
        verdict_ref="resolution:res-review",
    )
    spine_store.attach_lane_execution_for_resolution(
        resolution_id="res-review",
        evidence_refs=["lane_graph:graph-review"],
    )
    spine = spine_store.attach_review_verdict_for_resolution(
        resolution_id="res-review",
        review_verdict_ref="review_plane.json#verdict=verdict-review",
    )

    task = ReviewTask(
        task_id="review-task-ux",
        lane_id="lane-review",
        graph_id="graph-review",
        resolution_id="res-review",
        lane_prompt="Review the frontend projection lane.",
        gate_report_ref="logs/gates/lane-review/report.json",
        created_at="2026-06-28T13:00:00Z",
    )
    verdict = ReviewVerdict(
        id="verdict-review",
        lane_id="lane-review",
        decision=ReviewDecision.MERGE,
        status="finalized",
        summary="Review accepted.",
        evidence_refs=["logs/gates/lane-review/report.json"],
        created_at="2026-06-28T13:01:00Z",
    )
    VerdictStore(tmp_path / "review_plane.json").save_task_and_verdict(task, verdict)

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    assert "review_plane.json" in payload["source_authority"]
    assert payload["review_state"] == {
        "source_authority": ["review_plane.json", "chat.db:acceptance_spines"],
        "projection_only": True,
        "total": 1,
        "decision_summary": {"merge": 1},
        "items": [
            {
                "id": "verdict-review",
                "lane_id": "lane-review",
                "decision": "merge",
                "verdict_status": "finalized",
                "summary": "Review accepted.",
                "task_id": "review-task-ux",
                "task_status": "verdict_emitted",
                "graph_id": "graph-review",
                "resolution_id": "res-review",
                "gate_report_ref": "logs/gates/lane-review/report.json",
                "evidence_refs": ["logs/gates/lane-review/report.json"],
                "patch_instructions": None,
                "terminate_reason": None,
                "created_at": "2026-06-28T13:01:00Z",
                "source_refs": [
                    "review_plane.json#verdict=verdict-review",
                    "review_plane.json#task=review-task-ux",
                    f"chat.db:acceptance_spines#spine={spine.spine_id}",
                ],
                "authority_boundary": {
                    "producer": "review_plane.json",
                    "consumer": "frontend.peer_chat_ux_projection",
                    "condition": "read_only_projection",
                    "proof_boundary": "review_verdict_authority_not_github_or_merge_truth",
                },
            }
        ],
    }


def test_dashboard_peer_chat_ux_projection_links_natural_chain_lane_state(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Natural chain projection")
    intake = chat.add_message(conv.id, "Human", "human", "@architect run sentinel")
    AcceptanceSpineStore(db).create_for_intake(
        conversation_id=conv.id,
        intake_message_id=intake.id,
    )
    task = ReviewTask(
        task_id="review-task-natural",
        lane_id="lane-natural",
        graph_id="graph-natural",
        resolution_id="res-natural",
        lane_prompt="Review natural-chain sentinel lane.",
        gate_report_ref="logs/gates/lane-natural/report.json",
        created_at="2026-06-28T18:00:00Z",
    )
    verdict = ReviewVerdict(
        id="verdict-natural",
        lane_id="lane-natural",
        decision=ReviewDecision.MERGE,
        status="finalized",
        summary="Review accepted natural-chain sentinel.",
        evidence_refs=["logs/gates/lane-natural/report.json"],
        created_at="2026-06-28T18:01:00Z",
    )
    VerdictStore(tmp_path / "review_plane.json").save_task_and_verdict(task, verdict)
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-natural",
                    "lane_id": "lane-natural",
                    "verdict_id": "verdict-natural",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "approved",
                    "summary": "GitHub gate accepted.",
                    "resolved_by": "platform-runner",
                    "github_gate_evidence_ref": (
                        "github_gate_evidence.json#evidence=accepted-natural"
                    ),
                }
            ]
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-natural",
                    "conversation_id": conv.id,
                    "status": "merged",
                    "review_verdict_id": "verdict-natural",
                    "final_action_hold_id": "final-natural",
                    "github_gate_evidence_ref": (
                        "github_gate_evidence.json#evidence=accepted-natural"
                    ),
                }
            ]
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_state"]["total"] == 1
    assert payload["review_state"]["projection_source"] == ["feature_lanes.json"]
    assert payload["review_state"]["items"][0]["source_refs"] == [
        "review_plane.json#verdict=verdict-natural",
        "review_plane.json#task=review-task-natural",
        "feature_lanes.json#lane=lane-natural",
    ]
    assert payload["final_action_holds"]["total"] == 0
    assert payload["final_action_state"] == {
        "source_authority": ["final_actions.json", "chat.db:acceptance_spines"],
        "projection_source": ["feature_lanes.json"],
        "projection_only": True,
        "total": 1,
        "status_summary": {"approved": 1},
        "items": [
            {
                "id": "final-natural",
                "lane_id": "lane-natural",
                "verdict_id": "verdict-natural",
                "action": "merge",
                "target_status": "reviewed",
                "status": "approved",
                "summary": "GitHub gate accepted.",
                "resolved_by": "platform-runner",
                "github_gate_evidence_ref": (
                    "github_gate_evidence.json#evidence=accepted-natural"
                ),
                "github_gate_gap_ref": None,
                "source_refs": [
                    "final_actions.json#hold=final-natural",
                    "review_plane.json#verdict=verdict-natural",
                    "feature_lanes.json#lane=lane-natural",
                ],
                "authority_boundary": {
                    "producer": "final_actions.json",
                    "consumer": "frontend.peer_chat_ux_projection",
                    "condition": "read_only_projection",
                    "proof_boundary": "final_action_hold_not_github_or_merge_truth",
                },
            }
        ],
    }


def test_dashboard_peer_chat_ux_projection_projects_final_action_pr_and_github_gate_from_lanes(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Natural final-action PR projection")
    chat.add_message(conv.id, "Human", "human", "@architect run final-action PR")
    task = ReviewTask(
        task_id="review-task-pr",
        lane_id="lane-pr",
        graph_id="graph-pr",
        resolution_id="res-pr",
        lane_prompt="Review natural final-action PR lane.",
        gate_report_ref="logs/gates/lane-pr/report.json",
        created_at="2026-06-29T04:00:00Z",
    )
    verdict = ReviewVerdict(
        id="verdict-pr",
        lane_id="lane-pr",
        decision=ReviewDecision.MERGE,
        status="finalized",
        summary="Review accepted PR lane.",
        evidence_refs=["logs/gates/lane-pr/report.json"],
        created_at="2026-06-29T04:01:00Z",
    )
    VerdictStore(tmp_path / "review_plane.json").save_task_and_verdict(task, verdict)
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-pr",
                    "lane_id": "lane-pr",
                    "verdict_id": "verdict-pr",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "approved",
                    "summary": "GitHub gate accepted for PR lane.",
                    "resolved_by": "platform-runner",
                    "github_gate_evidence_ref": "github_gate_evidence.json#evidence=gh-pr",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_prs.json",
        {
            "schema_version": "final_action_prs.v1",
            "items": [
                {
                    "id": "fapr-pr",
                    "final_action_id": "final-pr",
                    "lane_id": "lane-pr",
                    "status": "created",
                    "repo": "iiyazu/Cross-Muse",
                    "base_branch": "main",
                    "head_branch": "codex/lane-pr",
                    "commit_sha": "head-pr",
                    "pull_request_number": 301,
                    "pull_request_url": "https://github.com/iiyazu/Cross-Muse/pull/301",
                    "head_sha": "head-pr",
                    "draft": False,
                    "worktree": "/tmp/lane-pr",
                    "proof_boundary": "pull_request_created_not_merge_truth",
                    "created_at": "2026-06-29T04:02:00Z",
                }
            ],
        },
    )
    _write_json(
        tmp_path / "github_gate_evidence.json",
        {
            "schema_version": "github_gate_evidence.v1",
            "items": [
                {
                    "id": "gh-pr",
                    "final_action_id": "final-pr",
                    "repo": "iiyazu/Cross-Muse",
                    "pull_request_number": 301,
                    "required_checks": ["quality-gates"],
                    "can_accept": True,
                    "gap_reason": None,
                    "created_at": "2026-06-29T04:05:00Z",
                    "evidence": {
                        "repo": "iiyazu/Cross-Muse",
                        "pull_request_number": 301,
                        "required_checks": ["quality-gates"],
                        "proof_level": "server_side_merge_proof",
                        "head_sha": "head-pr",
                        "workflow_run_id": 28349550118,
                        "check_run_ids": [83979528377],
                        "check_run_names": ["quality-gates"],
                        "check_run_head_shas": ["head-pr"],
                        "merge_commit_sha": "merge-pr",
                        "merged_at": "2026-06-29T04:56:51Z",
                        "merge_event_id": "merge-event-pr",
                    },
                    "main_ci": {
                        "workflow_run_id": 28349587620,
                        "head_sha": "merge-pr",
                        "conclusion": "success",
                    },
                }
            ],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-pr",
                    "conversation_id": conv.id,
                    "status": "merged",
                    "review_verdict_id": "verdict-pr",
                    "final_action_hold_id": "final-pr",
                    "pull_request_ref": "final_action_prs.json#pr=fapr-pr",
                    "pull_request_number": 301,
                    "pull_request_url": "https://github.com/iiyazu/Cross-Muse/pull/301",
                    "pull_request_head_sha": "head-pr",
                    "github_gate_evidence_ref": "github_gate_evidence.json#evidence=gh-pr",
                }
            ]
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    assert "final_action_prs.json" in payload["source_authority"]
    assert payload["final_action_state"]["source_authority"] == [
        "final_actions.json",
        "chat.db:acceptance_spines",
        "final_action_prs.json",
        "github_gate_evidence.json",
    ]
    item = payload["final_action_state"]["items"][0]
    assert item["pull_request"] == {
        "id": "fapr-pr",
        "ref": "final_action_prs.json#pr=fapr-pr",
        "status": "created",
        "repo": "iiyazu/Cross-Muse",
        "base_branch": "main",
        "head_branch": "codex/lane-pr",
        "commit_sha": "head-pr",
        "pull_request_number": 301,
        "pull_request_url": "https://github.com/iiyazu/Cross-Muse/pull/301",
        "head_sha": "head-pr",
        "draft": False,
        "created_at": "2026-06-29T04:02:00Z",
        "proof_boundary": "pull_request_created_not_merge_truth",
        "authority_boundary": {
            "producer": "final_action_prs.json",
            "consumer": "frontend.peer_chat_ux_projection",
            "condition": "read_only_projection",
            "proof_boundary": "pull_request_record_not_ci_or_merge_truth",
        },
    }
    assert item["github_gate"]["ref"] == "github_gate_evidence.json#evidence=gh-pr"
    assert item["github_gate"]["status"] == "accepted"
    assert item["github_gate"]["details"]["pull_request"] == {
        "repo": "iiyazu/Cross-Muse",
        "number": 301,
        "head_sha": "head-pr",
    }
    assert item["github_gate"]["details"]["merge"] == {
        "merge_commit_sha": "merge-pr",
        "merged_at": "2026-06-29T04:56:51Z",
        "merge_event_id": "merge-event-pr",
    }
    assert item["github_gate"]["details"]["main_ci"] == {
        "workflow_run_id": 28349587620,
        "head_sha": "merge-pr",
        "conclusion": "success",
        "status": "success",
    }


def test_dashboard_peer_chat_ux_projection_includes_operator_evidence_summary(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Evidence summary projection")
    intake = chat.add_message(conv.id, "Human", "human", "@architect summarize closure")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Evidence lane","lanes":[{"feature_id":"lane-evidence"}]}',
        references=[intake.id],
    )
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(conversation_id=conv.id, intake_message_id=intake.id)
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=intake.id,
        proposal_id=proposal.id,
    )
    spine_store.attach_verdict_for_proposal(
        proposal_id=proposal.id,
        verdict_ref="resolution:res-evidence",
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id="res-evidence",
        collaboration_run_id="run-evidence",
        artifact_ref="lane_graph:res-evidence",
        gate_refs=["review_trigger_verdict:evidence-ready"],
    )
    assert ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conv.id,
        claimed_by="bridge-test",
    )
    ChatDispatchQueueStore(db).mark_dispatched(
        dispatch.entry_id,
        provider_run_ref="provider:execute:evidence",
        dispatch_evidence="mcp_writeback:evidence",
    )
    spine_store.attach_execution_evidence_for_dispatch(
        dispatch_item_id=dispatch.entry_id,
        evidence_refs=["logs/gates/lane-evidence/report.json"],
    )
    spine_store.attach_review_verdict_for_resolution(
        resolution_id="res-evidence",
        review_verdict_ref="review_plane.json#verdict=verdict-evidence",
    )
    hold = FinalActionGateStore(tmp_path / "final_actions.json").create_hold(
        lane_id="lane-evidence",
        verdict_id="verdict-evidence",
        action="merge",
        target_status="reviewed",
        summary="GitHub gate accepted.",
    )
    spine_store.attach_final_action_for_review_verdict(
        review_verdict_ref="review_plane.json#verdict=verdict-evidence",
        final_action_ref=f"final_actions.json#hold={hold.id}",
    )
    _write_json(
        tmp_path / "github_gate_evidence.json",
        {
            "schema_version": "github_gate_evidence.v1",
            "items": [
                {
                    "id": "accepted-evidence",
                    "final_action_id": hold.id,
                    "can_accept": True,
                    "evidence": {
                        "repo": "iiyazu/Cross-Muse",
                        "pull_request_number": 295,
                        "required_checks": ["quality-gates"],
                        "proof_level": "server_side_merge_proof",
                        "head_sha": "abc123",
                        "workflow_run_id": 28343033679,
                        "check_run_ids": [83961033533],
                        "check_run_names": ["quality-gates"],
                        "check_run_head_shas": ["abc123"],
                        "expected_source_app": "github-actions",
                        "branch_protection_snapshot": {
                            "required_status_checks": {
                                "strict": True,
                                "checks": [{"context": "quality-gates"}],
                            },
                            "required_pull_request_reviews": None,
                        },
                        "internal_review_artifact": "review_plane.json#verdict=verdict-evidence",
                        "internal_reviewer": "review-god",
                        "internal_reviewed_head_sha": "abc123",
                        "internal_review_verified": True,
                        "merge_commit_sha": "def456",
                        "merged_at": "2026-06-29T01:30:00Z",
                        "merge_event_id": "merge-event-evidence",
                    },
                    "main_ci": {
                        "workflow_run_id": 28343075740,
                        "head_sha": "def456",
                        "conclusion": "success",
                    },
                }
            ],
        },
    )
    FinalActionGateStore(tmp_path / "final_actions.json").resolve(
        hold.id,
        status="approved",
        resolved_by="platform-runner",
        github_gate_evidence_ref="github_gate_evidence.json#evidence=accepted-evidence",
    )
    task = ReviewTask(
        task_id="review-task-evidence",
        lane_id="lane-evidence",
        graph_id="graph-evidence",
        resolution_id="res-evidence",
        lane_prompt="Review evidence summary lane.",
        gate_report_ref="logs/gates/lane-evidence/report.json",
        created_at="2026-06-29T01:00:00Z",
    )
    verdict = ReviewVerdict(
        id="verdict-evidence",
        lane_id="lane-evidence",
        decision=ReviewDecision.MERGE,
        status="finalized",
        summary="Review accepted evidence summary lane.",
        evidence_refs=["logs/gates/lane-evidence/report.json"],
        created_at="2026-06-29T01:01:00Z",
    )
    VerdictStore(tmp_path / "review_plane.json").save_task_and_verdict(task, verdict)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-evidence",
                    "conversation_id": conv.id,
                    "status": "merged",
                    "review_verdict_id": "verdict-evidence",
                    "final_action_hold_id": hold.id,
                    "github_gate_evidence_ref": (
                        "github_gate_evidence.json#evidence=accepted-evidence"
                    ),
                }
            ]
        },
    )
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id="inbox-evidence",
        participant_id="architect-evidence",
        target_role="architect",
        god_session_id="god-evidence",
        provider_session_id="provider-thread-evidence",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        message_created_at="2026-06-29T01:00:00Z",
        inbox_claimed_at="2026-06-29T01:00:01Z",
        delivery_started_at=1.0,
        provider_turn_started_at=1.1,
        first_delta_at=1.2,
        writeback_at=1.5,
        total_latency_ms=500,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
        supporting_context={
            "memoryos_sidecar": {
                "status": "degraded",
                "proof_level": "degraded",
                "namespace_uri": f"memory://conversation/{conv.id}",
                "degraded_reason": "memoryos_unavailable",
                "continuity_attempt_ref": (
                    f"memory://conversation/{conv.id}/context/memoryos-sidecar-attempt"
                ),
            }
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    summary = payload["evidence_summary"]
    assert summary["schema_version"] == "natural_groupchat_evidence_summary/v1"
    assert summary["projection_only"] is True
    assert summary["conversation_id"] == conv.id
    assert summary["status"] == "complete"
    assert summary["active_blocker"] is None
    assert summary["counts"] == {
        "authority": 6,
        "execution_proof": 2,
        "github_server_truth": 1,
        "sidecar_continuity": 1,
        "read_projection": 1,
        "failure_boundary": 0,
    }
    assert summary["items"] == [
        {
            "kind": "conversation",
            "proof_class": "authority",
            "ref": f"chat.db:conversations#conversation={conv.id}",
            "status": "observed",
            "producer": "chat.db:conversations",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "conversation_exists",
            "proof_boundary": "conversation_authority_not_execution_or_github_truth",
        },
        {
            "kind": "proposal",
            "proof_class": "authority",
            "ref": f"proposal:{proposal.id}",
            "status": "accepted",
            "producer": "chat.db:proposals",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "proposal_linked_to_acceptance_spine",
            "proof_boundary": "proposal_authority_not_execution_or_github_truth",
        },
        {
            "kind": "review_verdict",
            "proof_class": "authority",
            "ref": "review_plane.json#verdict=verdict-evidence",
            "status": "finalized",
            "producer": "review_plane.json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "review_verdict_linked_to_acceptance_spine",
            "proof_boundary": "review_verdict_authority_not_github_or_merge_truth",
        },
        {
            "kind": "dispatch_queue_entry",
            "proof_class": "authority",
            "ref": f"chat_dispatch_queue:{dispatch.entry_id}",
            "status": "dispatched",
            "producer": "chat.db:chat_dispatch_queue",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "dispatch_entry_linked_to_acceptance_spine",
            "proof_boundary": "dispatch_queue_authority_not_execution_proof",
        },
        {
            "kind": "execution_proof",
            "proof_class": "execution_proof",
            "ref": "logs/gates/lane-evidence/report.json",
            "status": "observed",
            "producer": "review_plane.json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "review_verdict_evidence_ref",
            "proof_boundary": "execution_proof_not_review_github_or_merge_truth",
        },
        {
            "kind": "execution_proof",
            "proof_class": "execution_proof",
            "ref": "mcp_writeback:evidence",
            "status": "observed",
            "producer": "chat_dispatch_bridge",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "dispatch_entry_dispatch_evidence",
            "proof_boundary": "worker_writeback_not_authority_or_github_truth",
        },
        {
            "kind": "final_action",
            "proof_class": "authority",
            "ref": f"final_actions.json#hold={hold.id}",
            "status": "approved",
            "producer": "final_actions.json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "final_action_linked_to_acceptance_spine",
            "proof_boundary": "final_action_authority_not_github_or_merge_truth",
        },
        {
            "kind": "github_gate",
            "proof_class": "github_server_truth",
            "ref": "github_gate_evidence.json#evidence=accepted-evidence",
            "status": "accepted",
            "producer": "github_gate_evidence.json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "final_action_contains_github_gate_evidence_ref",
            "proof_boundary": "github_gate_evidence_not_main_ci_truth",
            "details": {
                "pull_request": {
                    "repo": "iiyazu/Cross-Muse",
                    "number": 295,
                    "head_sha": "abc123",
                },
                "exact_head_ci": {
                    "workflow_run_id": 28343033679,
                    "check_run_ids": [83961033533],
                    "check_run_names": ["quality-gates"],
                    "check_run_head_shas": ["abc123"],
                },
                "merge": {
                    "merge_commit_sha": "def456",
                    "merged_at": "2026-06-29T01:30:00Z",
                    "merge_event_id": "merge-event-evidence",
                },
                "main_ci": {
                    "workflow_run_id": 28343075740,
                    "head_sha": "def456",
                    "conclusion": "success",
                    "status": "success",
                },
            },
        },
        {
            "kind": "memoryos_sidecar",
            "proof_class": "sidecar_continuity",
            "ref": f"memory://conversation/{conv.id}/context/memoryos-sidecar-attempt",
            "status": "degraded",
            "producer": "chat.db:peer_turn_latency_traces.supporting_context_json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "memoryos_sidecar_projection_present",
            "proof_boundary": "sidecar_continuity_not_proposal_review_dispatch_or_github_truth",
        },
        {
            "kind": "frontend_projection",
            "proof_class": "read_projection",
            "ref": f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection",
            "status": "available",
            "producer": "frontend.peer_chat_ux_projection",
            "consumer": "operator",
            "condition": "read_only_projection_built_from_authority",
            "proof_boundary": "frontend_projection_not_truth_producer",
        },
        {
            "kind": "acceptance_spine",
            "proof_class": "authority",
            "ref": summary["items"][-1]["ref"],
            "status": "accepted",
            "producer": "chat.db:acceptance_spines",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "acceptance_spine_tracks_chain",
            "proof_boundary": "acceptance_spine_authority_not_github_or_merge_truth",
        },
    ]
    assert payload["operator_closure"] == {
        "schema_version": "operator_closure/v1",
        "projection_only": True,
        "status": "complete",
        "next_action": "observe_complete",
        "active_blocker": None,
        "proof_counts": summary["counts"],
        "worklist_next_actions": {"none": 1},
        "final_action_status_summary": {"approved": 1},
        "sidecar_status_summary": {"degraded": 1},
        "authority_boundary": {
            "producer": "frontend.peer_chat_ux_projection",
            "consumer": "operator",
            "condition": "read_only_operator_closure_projection",
            "proof_boundary": "operator_closure_not_truth_producer",
        },
    }


def test_dashboard_peer_chat_ux_projection_summarizes_multiple_sidecar_items(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Multiple sidecar evidence")
    namespace = f"memory://conversation/{conv.id}"
    traces = PeerTurnLatencyTraceStore(db)
    traces.record(
        conversation_id=conv.id,
        inbox_item_id="inbox-degraded",
        participant_id="execute-degraded",
        target_role="execute",
        message_created_at="2026-06-29T01:00:00Z",
        inbox_claimed_at="2026-06-29T01:00:01Z",
        delivery_started_at=1.0,
        provider_turn_started_at=1.1,
        first_delta_at=None,
        writeback_at=1.2,
        total_latency_ms=200,
        delivery_mode="memoryos_sidecar_dispatch_handoff",
        degraded_reason=None,
        supporting_context={
            "memoryos_sidecar": {
                "status": "degraded",
                "authority": "memoryos_sidecar",
                "proof_level": "degraded",
                "namespace_uri": namespace,
                "degraded_reason": "memoryos_unavailable",
                "continuity_attempt_ref": f"{namespace}/context/memoryos-sidecar-attempt",
            }
        },
    )
    traces.record(
        conversation_id=conv.id,
        inbox_item_id="inbox-recorded",
        participant_id="execute-recorded",
        target_role="execute",
        message_created_at="2026-06-29T01:01:00Z",
        inbox_claimed_at="2026-06-29T01:01:01Z",
        delivery_started_at=2.0,
        provider_turn_started_at=2.1,
        first_delta_at=None,
        writeback_at=2.2,
        total_latency_ms=200,
        delivery_mode="memoryos_sidecar_dispatch_handoff",
        degraded_reason=None,
        supporting_context={
            "memoryos_sidecar": {
                "status": "recorded",
                "authority": "memoryos_sidecar",
                "proof_level": "contract",
                "namespace_uri": namespace,
                "degraded_reason": None,
                "source_refs": ["chat_dispatch_queue:dispatch-recorded"],
                "continuity_refs": [f"{namespace}/messages/msg-recorded"],
            }
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    summary = payload["evidence_summary"]
    assert summary["counts"] == {
        "authority": 1,
        "execution_proof": 0,
        "github_server_truth": 0,
        "sidecar_continuity": 2,
        "read_projection": 1,
        "failure_boundary": 0,
    }
    sidecar_items = [
        item for item in summary["items"] if item["kind"] == "memoryos_sidecar"
    ]
    assert sidecar_items == [
        {
            "kind": "memoryos_sidecar",
            "proof_class": "sidecar_continuity",
            "ref": f"{namespace}/messages/msg-recorded",
            "status": "recorded",
            "producer": "chat.db:peer_turn_latency_traces.supporting_context_json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "memoryos_sidecar_projection_present",
            "proof_boundary": "sidecar_continuity_not_proposal_review_dispatch_or_github_truth",
        },
        {
            "kind": "memoryos_sidecar",
            "proof_class": "sidecar_continuity",
            "ref": f"{namespace}/context/memoryos-sidecar-attempt",
            "status": "degraded",
            "producer": "chat.db:peer_turn_latency_traces.supporting_context_json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "memoryos_sidecar_projection_present",
            "proof_boundary": "sidecar_continuity_not_proposal_review_dispatch_or_github_truth",
        },
    ]
    assert payload["operator_closure"]["sidecar_status_summary"] == {
        "recorded": 1,
        "degraded": 1,
    }


def test_dashboard_peer_chat_ux_projection_evidence_summary_keeps_multilane_refs(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Multi-lane evidence summary")
    spine_store = AcceptanceSpineStore(db)
    queue = ChatDispatchQueueStore(db)
    final_action_store = FinalActionGateStore(tmp_path / "final_actions.json")
    verdict_store = VerdictStore(tmp_path / "review_plane.json")
    github_items: list[dict[str, object]] = []
    final_action_resolutions: list[tuple[str, str]] = []
    expected: dict[str, dict[str, str]] = {}

    for lane_id, pr_number in (("lane-alpha", 298), ("lane-beta", 299)):
        intake = chat.add_message(conv.id, "Human", "human", f"@architect run {lane_id}")
        proposal = chat.create_proposal(
            conversation_id=conv.id,
            author="Architect GOD",
            proposal_type="lane_graph",
            content=json.dumps(
                {"summary": lane_id, "lanes": [{"feature_id": lane_id}]},
            ),
            references=[intake.id],
        )
        spine = spine_store.create_for_intake(
            conversation_id=conv.id,
            intake_message_id=intake.id,
        )
        spine_store.attach_proposal(
            conversation_id=conv.id,
            intake_message_id=intake.id,
            proposal_id=proposal.id,
        )
        resolution_id = f"res-{lane_id}"
        spine_store.attach_verdict_for_proposal(
            proposal_id=proposal.id,
            verdict_ref=f"resolution:{resolution_id}",
        )
        dispatch = queue.enqueue_agent_auto_dispatch(
            conversation_id=conv.id,
            proposal_id=proposal.id,
            resolution_id=resolution_id,
            collaboration_run_id=f"run-{lane_id}",
            artifact_ref=f"lane_graph:{lane_id}",
            gate_refs=[f"review_trigger_verdict:{lane_id}"],
        )
        assert queue.claim_next_auto_dispatch(
            conversation_id=conv.id,
            claimed_by="bridge-test",
        )
        queue.mark_dispatched(
            dispatch.entry_id,
            provider_run_ref=f"provider:execute:{lane_id}",
            dispatch_evidence=f"mcp_writeback:{lane_id}",
        )
        spine_store.attach_execution_evidence_for_dispatch(
            dispatch_item_id=dispatch.entry_id,
            evidence_refs=[f"logs/gates/{lane_id}/report.json"],
        )
        verdict_id = f"verdict-{lane_id}"
        spine_store.attach_review_verdict_for_resolution(
            resolution_id=resolution_id,
            review_verdict_ref=f"review_plane.json#verdict={verdict_id}",
        )
        hold = final_action_store.create_hold(
            lane_id=lane_id,
            verdict_id=verdict_id,
            action="merge",
            target_status="reviewed",
            summary=f"GitHub gate accepted for {lane_id}.",
        )
        spine_store.attach_final_action_for_review_verdict(
            review_verdict_ref=f"review_plane.json#verdict={verdict_id}",
            final_action_ref=f"final_actions.json#hold={hold.id}",
        )
        verdict_store.save_task_and_verdict(
            ReviewTask(
                task_id=f"review-task-{lane_id}",
                lane_id=lane_id,
                graph_id=f"graph-{lane_id}",
                resolution_id=resolution_id,
                lane_prompt=f"Review {lane_id}.",
                gate_report_ref=f"logs/gates/{lane_id}/report.json",
                created_at="2026-06-29T01:00:00Z",
            ),
            ReviewVerdict(
                id=verdict_id,
                lane_id=lane_id,
                decision=ReviewDecision.MERGE,
                status="finalized",
                summary=f"Review accepted {lane_id}.",
                evidence_refs=[f"logs/gates/{lane_id}/report.json"],
                created_at="2026-06-29T01:01:00Z",
            ),
        )
        evidence_id = f"accepted-{lane_id}"
        github_items.append(
            {
                "id": evidence_id,
                "final_action_id": hold.id,
                "can_accept": True,
                "evidence": {
                    "repo": "iiyazu/Cross-Muse",
                    "pull_request_number": pr_number,
                    "required_checks": ["quality-gates"],
                    "proof_level": "server_side_merge_proof",
                    "head_sha": f"head-{lane_id}",
                    "workflow_run_id": pr_number * 10,
                    "check_run_ids": [pr_number * 100],
                    "check_run_names": ["quality-gates"],
                    "check_run_head_shas": [f"head-{lane_id}"],
                    "merge_commit_sha": f"merge-{lane_id}",
                    "merged_at": "2026-06-29T01:30:00Z",
                    "merge_event_id": f"merge-event-{lane_id}",
                },
                "main_ci": {
                    "workflow_run_id": pr_number * 1000,
                    "head_sha": f"merge-{lane_id}",
                    "conclusion": "success",
                },
            }
        )
        final_action_resolutions.append(
            (hold.id, f"github_gate_evidence.json#evidence={evidence_id}")
        )
        expected[lane_id] = {
            "spine_ref": f"chat.db:acceptance_spines#spine={spine.spine_id}",
            "dispatch_ref": f"chat_dispatch_queue:{dispatch.entry_id}",
            "review_ref": f"review_plane.json#verdict={verdict_id}",
            "final_action_ref": f"final_actions.json#hold={hold.id}",
            "github_ref": f"github_gate_evidence.json#evidence={evidence_id}",
            "lane_ref": f"feature_lanes.json#lane={lane_id}",
        }

    _write_json(
        tmp_path / "github_gate_evidence.json",
        {"schema_version": "github_gate_evidence.v1", "items": github_items},
    )
    for hold_id, github_ref in final_action_resolutions:
        final_action_store.resolve(
            hold_id,
            status="approved",
            resolved_by="platform-runner",
            github_gate_evidence_ref=github_ref,
        )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": lane_id,
                    "conversation_id": conv.id,
                    "status": "merged",
                    "review_verdict_id": f"verdict-{lane_id}",
                    "final_action_hold_id": expected[lane_id]["final_action_ref"].removeprefix(
                        "final_actions.json#hold="
                    ),
                    "github_gate_evidence_ref": expected[lane_id]["github_ref"],
                }
                for lane_id in expected
            ]
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    items = response.json()["evidence_summary"]["items"]
    by_ref = {item["ref"]: item for item in items}
    for lane_id, refs in expected.items():
        for ref_key in ("dispatch_ref", "review_ref", "final_action_ref", "github_ref"):
            item = by_ref[refs[ref_key]]
            assert item.get("lane_id") == lane_id, (ref_key, item)
            assert refs["lane_ref"] in item["source_refs"]
            assert refs["spine_ref"] in item["source_refs"]


def test_dashboard_peer_chat_ux_projection_evidence_summary_uses_lane_projection_fallback(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Lane-derived evidence summary")
    intake = chat.add_message(conv.id, "Human", "human", "@architect run lane-derived")
    AcceptanceSpineStore(db).create_for_intake(
        conversation_id=conv.id,
        intake_message_id=intake.id,
    )
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content=json.dumps({"summary": "Lane-derived", "lanes": [{"feature_id": "lane-only"}]}),
        references=[intake.id],
    )
    resolution = chat.approve_proposal(
        proposal_id=proposal.id,
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Run lane-derived summary",
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id="collab-lane-only",
        artifact_ref="artifact:lane-only",
        gate_refs=["review_trigger_verdict:lane-only"],
    )
    assert ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conv.id,
        claimed_by="bridge-test",
    )
    ChatDispatchQueueStore(db).mark_dispatched(
        dispatch.entry_id,
        provider_run_ref="peer_ack:execute:lane-only",
        dispatch_evidence="mcp_writeback:lane-only",
    )
    verdict = ReviewVerdict(
        id="verdict-lane-only",
        lane_id="lane-only",
        decision=ReviewDecision.MERGE,
        status="finalized",
        summary="Review accepted lane-only.",
        evidence_refs=[
            "feature_lanes.json#lane=lane-only",
            "review_plane.json#task=review-task-lane-only",
        ],
        created_at="2026-06-29T05:00:00Z",
    )
    VerdictStore(tmp_path / "review_plane.json").save_task_and_verdict(
        ReviewTask(
            task_id="review-task-lane-only",
            lane_id="lane-only",
            graph_id="graph-lane-only",
            resolution_id=resolution.id,
            lane_prompt="Review lane-only.",
            gate_report_ref="logs/gates/lane-only/report.json",
            created_at="2026-06-29T04:59:00Z",
        ),
        verdict,
    )
    final_action_store = FinalActionGateStore(tmp_path / "final_actions.json")
    hold = final_action_store.create_hold(
        lane_id="lane-only",
        verdict_id=verdict.id,
        action="merge",
        target_status="reviewed",
        summary="GitHub gate accepted for lane-only.",
    )
    _write_json(
        tmp_path / "github_gate_evidence.json",
        {
            "schema_version": "github_gate_evidence.v1",
            "items": [
                {
                    "id": "accepted-lane-only",
                    "final_action_id": hold.id,
                    "repo": "iiyazu/Cross-Muse",
                    "pull_request_number": 304,
                    "required_checks": ["quality-gates"],
                    "can_accept": True,
                    "gap_reason": None,
                    "evidence": {
                        "repo": "iiyazu/Cross-Muse",
                        "pull_request_number": 304,
                        "required_checks": ["quality-gates"],
                        "proof_level": "server_side_merge_proof",
                        "head_sha": "head-lane-only",
                        "workflow_run_id": 3040,
                        "check_run_ids": [30401],
                        "check_run_names": ["quality-gates"],
                        "check_run_head_shas": ["head-lane-only"],
                        "merge_commit_sha": "merge-lane-only",
                        "merged_at": "2026-06-29T05:10:00Z",
                        "merge_event_id": "merge-event-lane-only",
                    },
                    "main_ci": {
                        "workflow_run_id": 304000,
                        "head_sha": "merge-lane-only",
                        "conclusion": "success",
                    },
                }
            ],
        },
    )
    final_action_store.resolve(
        hold.id,
        status="approved",
        resolved_by="platform-runner",
        github_gate_evidence_ref="github_gate_evidence.json#evidence=accepted-lane-only",
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-only",
                    "conversation_id": conv.id,
                    "status": "merged",
                    "review_verdict_id": verdict.id,
                    "final_action_hold_id": hold.id,
                    "github_gate_evidence_ref": (
                        "github_gate_evidence.json#evidence=accepted-lane-only"
                    ),
                }
            ]
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    summary = response.json()["evidence_summary"]
    assert summary["status"] == "complete"
    assert summary["active_blocker"] is None
    by_ref = {item["ref"]: item for item in summary["items"]}
    assert by_ref[f"proposal:{proposal.id}"]["condition"] == "proposal_present_for_conversation"
    assert by_ref[f"chat_dispatch_queue:{dispatch.entry_id}"]["condition"] == (
        "dispatch_entry_present_for_conversation"
    )
    assert by_ref[f"review_plane.json#verdict={verdict.id}"]["condition"] == (
        "review_verdict_projected_from_review_state"
    )
    assert by_ref[f"final_actions.json#hold={hold.id}"]["condition"] == (
        "final_action_projected_from_final_action_state"
    )
    assert by_ref["logs/gates/lane-only/report.json"]["producer"] == "review_plane.json"
    assert "feature_lanes.json#lane=lane-only" not in by_ref
    assert "review_plane.json#task=review-task-lane-only" not in by_ref
    assert by_ref["github_gate_evidence.json#evidence=accepted-lane-only"]["details"][
        "main_ci"
    ]["status"] == "success"


def test_dashboard_peer_chat_ux_projection_evidence_summary_reports_failure_boundary(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Evidence summary blocked")
    intake = chat.add_message(conv.id, "Human", "human", "@architect run blocked lane")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Blocked lane","lanes":[{"feature_id":"lane-blocked"}]}',
        references=[intake.id],
    )
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(conversation_id=conv.id, intake_message_id=intake.id)
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=intake.id,
        proposal_id=proposal.id,
    )
    spine_store.attach_verdict_for_proposal(
        proposal_id=proposal.id,
        verdict_ref="resolution:res-blocked",
    )
    queue = ChatDispatchQueueStore(db)
    dispatch = queue.enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id="res-blocked",
        collaboration_run_id="run-blocked",
        artifact_ref="lane_graph:res-blocked",
        gate_refs=["review_trigger_verdict:blocker-ready"],
    )
    queue.mark_failed(dispatch.entry_id, failure_reason="provider timeout")

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    summary = response.json()["evidence_summary"]
    assert summary["status"] == "blocked"
    assert summary["counts"]["failure_boundary"] == 2
    assert summary["active_blocker"] == summary["failure_boundaries"][0]
    assert [_without_failure_classification(item) for item in summary["failure_boundaries"]] == [
        {
            "kind": "dispatch_queue_entry",
            "proof_class": "failure_boundary",
            "ref": f"chat_dispatch_queue:{dispatch.entry_id}",
            "status": "failed",
            "producer": "chat.db:chat_dispatch_queue",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "provider timeout",
            "proof_boundary": "dispatch_failure_boundary",
            "next_recovery_action": "inspect_dispatch_failure_reason",
        },
        {
            "kind": "acceptance_spine",
            "proof_class": "failure_boundary",
            "ref": summary["failure_boundaries"][-1]["ref"],
            "status": "blocked",
            "producer": "chat.db:acceptance_spines",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "provider timeout",
            "proof_boundary": "acceptance_spine_blocker_boundary",
            "next_recovery_action": "resume_from_recorded_acceptance_spine_boundary",
        },
    ]
    assert summary["failure_boundaries"][0]["taxonomy"] == (
        "natural_groupchat_durable_failure_taxonomy/v1"
    )
    assert summary["failure_boundaries"][0]["proof_level"] == "durable xmuse authority gap"
    assert summary["failure_boundaries"][0]["classification"]["class_id"] == (
        "provider_turn_no_writeback_or_timeout"
    )
    assert summary["failure_boundaries"][0]["classification"]["failure_boundary"] == (
        "provider_writeback_boundary"
    )


def test_dashboard_peer_chat_ux_projection_evidence_summary_reports_active_collaboration_blocker(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Evidence summary active blocker")
    collaboration = ChatCollaborationStore(db)
    run = collaboration.create_request(
        conversation_id=conv.id,
        goal="Review blocked callback",
        initiator="architect",
        targets=["review"],
        callback_target="architect",
        question="Can this proposal dispatch?",
        context_refs=["proposal:blocker"],
        idempotency_key=None,
        timeout_s=60,
    )
    blocker = collaboration.raise_blocker(
        run.run_id,
        issuer="review",
        severity="blocker",
        reason="proposal callback missing",
        affected_ref="proposal:blocker",
        suggested_fix="Recreate callback proposal",
        blocks_dispatch=True,
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    summary = response.json()["evidence_summary"]
    assert summary["status"] == "blocked"
    assert summary["active_blocker"] == summary["failure_boundaries"][0]
    assert summary["active_blocker"]["kind"] == "collaboration_blocker"
    assert summary["active_blocker"]["ref"] == (
        f"chat.db:collaboration_blockers#blocker={blocker.blocker_id}"
    )
    assert summary["active_blocker"]["condition"] == "proposal callback missing"
    assert summary["active_blocker"]["classification"]["class_id"] == (
        "collaboration_callback_or_proposal_failure"
    )


def test_dashboard_peer_chat_ux_projection_rejects_stale_github_gate_ref(
    tmp_path: Path,
) -> None:
    conv, hold, spine = _create_final_action_projection_fixture(tmp_path)
    payload = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    payload["holds"][0]["status"] = "approved"
    payload["holds"][0]["resolved_by"] = "operator"
    payload["holds"][0]["github_gate_evidence_ref"] = (
        "github_gate_evidence.json#evidence=missing"
    )
    _write_json(tmp_path / "final_actions.json", payload)
    task = ReviewTask(
        task_id="review-task-final-action",
        lane_id="lane-final",
        graph_id="graph-final",
        resolution_id="res-final-action",
        lane_prompt="Review final action lane.",
        gate_report_ref="logs/gates/lane-final/report.json",
        created_at="2026-06-29T01:00:00Z",
    )
    verdict = ReviewVerdict(
        id="verdict-final-action",
        lane_id="lane-final",
        decision=ReviewDecision.MERGE,
        status="finalized",
        summary="Review accepted final action lane.",
        evidence_refs=["logs/gates/lane-final/report.json"],
        created_at="2026-06-29T01:01:00Z",
    )
    VerdictStore(tmp_path / "review_plane.json").save_task_and_verdict(task, verdict)

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    summary = response.json()["evidence_summary"]
    assert summary["status"] == "blocked"
    assert "github_gate" not in {item["kind"] for item in summary["items"]}
    assert [_without_failure_classification(item) for item in summary["failure_boundaries"]] == [
        {
            "kind": "github_gate",
            "proof_class": "failure_boundary",
            "ref": "github_gate_evidence.json#evidence=missing",
            "status": "blocked",
            "producer": "github_gate_evidence.json",
            "consumer": "natural_groupchat_evidence_summary",
            "condition": "github_gate_evidence_ref_missing_or_invalid",
            "proof_boundary": "github_gate_evidence_ref_boundary",
            "next_recovery_action": "capture_exact_head_github_gate_evidence",
        }
    ]
    assert summary["items"][-1] == {
        "kind": "acceptance_spine",
        "proof_class": "authority",
        "ref": f"chat.db:acceptance_spines#spine={spine.spine_id}",
        "status": "awaiting_final_action",
        "producer": "chat.db:acceptance_spines",
        "consumer": "natural_groupchat_evidence_summary",
        "condition": "acceptance_spine_tracks_chain",
        "proof_boundary": "acceptance_spine_authority_not_github_or_merge_truth",
    }


def test_dashboard_peer_chat_ux_projection_reports_missing_final_action_artifact(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Missing final action evidence")
    intake = chat.add_message(conv.id, "Human", "human", "@architect missing final action")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Missing final action lane"}',
        references=[intake.id],
    )
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(conversation_id=conv.id, intake_message_id=intake.id)
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=intake.id,
        proposal_id=proposal.id,
    )
    spine_store.attach_verdict_for_proposal(
        proposal_id=proposal.id,
        verdict_ref="resolution:res-missing-final",
    )
    spine_store.attach_review_verdict_for_resolution(
        resolution_id="res-missing-final",
        review_verdict_ref="review_plane.json#verdict=verdict-missing-final",
    )
    spine = spine_store.attach_final_action_for_review_verdict(
        review_verdict_ref="review_plane.json#verdict=verdict-missing-final",
        final_action_ref="final_actions.json#hold=missing-final",
    )
    assert spine is not None

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    summary = response.json()["evidence_summary"]
    assert summary["status"] == "blocked"
    assert "final_action" not in {item["kind"] for item in summary["items"]}
    expected_boundary = {
        "kind": "final_action",
        "proof_class": "failure_boundary",
        "ref": "final_actions.json#hold=missing-final",
        "status": "missing",
        "producer": "final_actions.json",
        "consumer": "natural_groupchat_evidence_summary",
        "condition": "final_action_ref_unresolved",
        "proof_boundary": "final_action_artifact_boundary",
        "next_recovery_action": "recreate_or_relink_final_action_hold",
    }
    assert expected_boundary in [
        _without_failure_classification(item) for item in summary["failure_boundaries"]
    ]


def test_dashboard_peer_chat_ux_projection_filters_non_pending_final_action_holds(
    tmp_path: Path,
) -> None:
    conv, hold, _spine = _create_final_action_projection_fixture(tmp_path)
    store = FinalActionGateStore(tmp_path / "final_actions.json")
    unlinked_hold = store.create_hold(
        lane_id="lane-unlinked",
        verdict_id="verdict-unlinked",
        action="merge",
        target_status="reviewed",
        summary="This hold is not linked by the conversation acceptance spine.",
    )
    store.resolve(
        hold.id,
        status="approved",
        resolved_by="operator",
        github_gate_gap_ref="github_gate_evidence.json#evidence=manual-gap",
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-bogus",
                    "status": "awaiting_final_action",
                    "final_action_hold_id": "final-bogus",
                }
            ]
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_action_holds"] == {
        "source_authority": ["final_actions.json", "chat.db:acceptance_spines"],
        "projection_only": True,
        "total": 0,
        "pending": 0,
        "items": [],
    }
    worklist_ids = {item["id"] for item in payload["worklist"]}
    assert hold.id not in worklist_ids
    assert unlinked_hold.id not in worklist_ids
    assert "final-bogus" not in worklist_ids


def test_dashboard_peer_chat_ux_projection_keeps_github_refs_out_of_hold_source_refs(
    tmp_path: Path,
) -> None:
    conv, hold, spine = _create_final_action_projection_fixture(tmp_path)
    payload = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    payload["holds"][0]["github_gate_evidence_ref"] = (
        "github_gate_evidence.json#evidence=accepted"
    )
    payload["holds"][0]["github_gate_gap_ref"] = "github_gate_evidence.json#evidence=gap"
    _write_json(tmp_path / "final_actions.json", payload)

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    projected = response.json()["final_action_holds"]["items"][0]
    assert projected["github_gate_evidence_ref"] == "github_gate_evidence.json#evidence=accepted"
    assert projected["github_gate_gap_ref"] == "github_gate_evidence.json#evidence=gap"
    assert projected["source_refs"] == [
        f"final_actions.json#hold={hold.id}",
        "review_plane.json#verdict=verdict-final-action",
        f"chat.db:acceptance_spines#spine={spine.spine_id}",
    ]
    worklist_item = next(item for item in response.json()["worklist"] if item["id"] == hold.id)
    assert worklist_item["source_refs"] == projected["source_refs"]
    assert worklist_item["compact_detail"]["github_gate_evidence_ref"] == (
        "github_gate_evidence.json#evidence=accepted"
    )
    assert worklist_item["compact_detail"]["github_gate_gap_ref"] == (
        "github_gate_evidence.json#evidence=gap"
    )


def test_dashboard_peer_chat_ux_projection_404s_for_missing_conversation(
    tmp_path: Path,
) -> None:
    response = TestClient(create_app(tmp_path)).get(
        "/api/dashboard/peer-chat/conversations/missing/ux-projection"
    )

    assert response.status_code == 404
    assert not (tmp_path / "chat.db").exists()


def test_dashboard_peer_chat_ux_projection_tolerates_old_trace_schema(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Old trace projection")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            create table peer_turn_latency_traces (
                id text primary key,
                conversation_id text not null references conversations(id),
                inbox_item_id text not null,
                god_session_id text,
                participant_id text,
                target_role text,
                provider_session_id text,
                provider_session_kind text,
                provider_binding_status text,
                provider_binding_failure_reason text,
                message_created_at text not null,
                inbox_claimed_at text,
                delivery_started_at real not null,
                provider_turn_started_at real not null,
                first_delta_at real,
                writeback_at real not null,
                total_latency_ms integer not null,
                delivery_mode text not null,
                degraded_reason text,
                stage_timings_json text not null default '{}'
            )
            """
        )
        conn.execute(
            """
            insert into peer_turn_latency_traces (
                id, conversation_id, inbox_item_id, message_created_at,
                delivery_started_at, provider_turn_started_at, writeback_at,
                total_latency_ms, delivery_mode, degraded_reason, stage_timings_json
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "peer_latency_old_projection",
                conv.id,
                "inbox-old-projection",
                "2026-06-28T00:00:00Z",
                1.0,
                1.1,
                2.0,
                1000,
                "mcp_writeback",
                None,
                "{}",
            ),
        )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    assert response.json()["supporting_context"] == {
        "projection_only": True,
        "source_authority": ["chat.db:peer_turn_latency_traces.supporting_context_json"],
        "memoryos_sidecar": {"status_summary": {}, "latest": []},
    }


def test_dashboard_peer_chat_ux_projection_accepts_singular_sidecar_continuity_ref(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Singular sidecar continuity")
    message = chat.add_message(conv.id, "Human", "human", "@architect continue")
    inbox = ChatInboxStore(db).create_item(
        conversation_id=conv.id,
        target_participant_id="part-architect",
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect continue"},
    )
    continuity_ref = f"memory://conversation/{conv.id}/context/memoryos-sidecar"
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id=inbox.id,
        participant_id="part-architect",
        target_role="architect",
        message_created_at=inbox.created_at,
        inbox_claimed_at=inbox.claimed_at,
        delivery_started_at=1.0,
        provider_turn_started_at=1.1,
        first_delta_at=None,
        writeback_at=2.0,
        total_latency_ms=1000,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
        supporting_context={
            "memoryos_sidecar": {
                "status": "attached",
                "authority": "memoryos_sidecar",
                "proof_level": "contract",
                "namespace_uri": f"memory://conversation/{conv.id}",
                "continuity_ref": continuity_ref,
            }
        },
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    [item] = response.json()["supporting_context"]["memoryos_sidecar"]["latest"]
    assert item["continuity_refs"] == [continuity_ref]


def test_dashboard_peer_chat_ux_projection_tolerates_dispatch_queue_without_gate_refs(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Old dispatch projection")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            create table chat_dispatch_queue (
                entry_id text primary key,
                conversation_id text not null,
                source text not null,
                target text not null,
                status text not null,
                auto_execute integer not null,
                proposal_id text,
                resolution_id text,
                collaboration_run_id text,
                artifact_ref text,
                dispatch_policy text not null,
                claimed_by text,
                claimed_at text,
                provider_run_ref text,
                dispatch_evidence text,
                failure_reason text,
                completed_at text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.execute(
            """
            insert into chat_dispatch_queue (
                entry_id, conversation_id, source, target, status, auto_execute,
                proposal_id, resolution_id, collaboration_run_id, artifact_ref,
                dispatch_policy, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dispatch:old",
                conv.id,
                "agent",
                "execute",
                "queued",
                1,
                "proposal-old",
                "resolution-old",
                None,
                "artifact:old-lane",
                "real_provider_allowed",
                "2026-06-28T00:00:00Z",
                "2026-06-28T00:00:00Z",
            ),
        )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    worklist_by_id = {item["id"]: item for item in payload["worklist"]}
    assert worklist_by_id["dispatch:old"]["source_refs"] == [
        "chat_dispatch_queue:dispatch:old",
        "proposal:proposal-old",
        "resolution:resolution-old",
        "artifact:old-lane",
    ]
    legacy_dispatch_entry = payload["dispatch_queue"]["entries"][0]
    expected_legacy_refs = [
        "chat_dispatch_queue:dispatch:old",
        "proposal:proposal-old",
        "resolution:resolution-old",
        "artifact:old-lane",
    ]
    assert legacy_dispatch_entry["source_refs"] == expected_legacy_refs
    assert legacy_dispatch_entry["authority_boundary"] == {
        "producer": "chat.db:chat_dispatch_queue",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "dispatch_queue_authority_not_execution_proof",
    }
    assert legacy_dispatch_entry["sidecar_continuity"] == {
        "producer": "chat.db:chat_dispatch_queue",
        "consumer": "memoryos_sidecar",
        "condition": "explicit_memoryos_configuration",
        "proof_boundary": "sidecar_continuity_not_execution_truth",
        "projection_only": True,
        "handoff_state": "contract_available",
        "source_refs": expected_legacy_refs,
    }


def test_dashboard_peer_chat_ux_projection_keeps_dispatch_evidence_out_of_source_refs(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conv = ChatStore(db).create_conversation("Dispatch evidence boundary")
    queue = ChatDispatchQueueStore(db)
    entry = queue.enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id="proposal-evidence-boundary",
        resolution_id="resolution-evidence-boundary",
        collaboration_run_id="collab-evidence-boundary",
        artifact_ref="artifact:lane_graph",
        gate_refs=["review_trigger_verdict:message-evidence-boundary"],
    )
    assert queue.claim_next_auto_dispatch(
        conversation_id=conv.id,
        claimed_by="bridge-test",
    )
    dispatched = queue.mark_dispatched(
        entry.entry_id,
        provider_run_ref="provider:execute:boundary",
        dispatch_evidence="mcp_writeback:dispatch-inbox",
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    payload = response.json()
    worklist_by_id = {item["id"]: item for item in payload["worklist"]}
    assert worklist_by_id[entry.entry_id]["source_refs"] == [
        f"chat_dispatch_queue:{entry.entry_id}",
        "proposal:proposal-evidence-boundary",
        "review_trigger_verdict:message-evidence-boundary",
        "resolution:resolution-evidence-boundary",
        "collaboration:collab-evidence-boundary",
        "artifact:lane_graph",
    ]
    assert dispatched.dispatch_evidence not in worklist_by_id[entry.entry_id]["source_refs"]
    dispatch_entry = payload["dispatch_queue"]["entries"][0]
    assert dispatch_entry["dispatch_evidence"] == "mcp_writeback:dispatch-inbox"
    assert dispatched.dispatch_evidence not in dispatch_entry["source_refs"]
    assert dispatch_entry["sidecar_continuity"]["source_refs"] == dispatch_entry["source_refs"]


def test_dashboard_peer_chat_ux_projection_does_not_mutate_authority_files(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Read-only UX")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect no writes")
    ChatInboxStore(db).create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )
    before_hash = sha256(db.read_bytes()).hexdigest()
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-read-only",
                    "conversation_id": conv.id,
                    "participant_id": participant.participant_id,
                    "role": participant.role,
                    "status": "running",
                }
            ]
        },
    )
    _write_json(tmp_path / "god_sessions.json", {"sessions": []})
    before_active_sessions = sha256((tmp_path / "active_sessions.json").read_bytes()).hexdigest()
    before_god_sessions = sha256((tmp_path / "god_sessions.json").read_bytes()).hexdigest()
    before_sidecars = {path.name for path in tmp_path.iterdir() if path.name.startswith("chat.db-")}

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/ux-projection"
    )

    assert response.status_code == 200
    assert response.json()["supporting_context"] == {
        "projection_only": True,
        "source_authority": ["chat.db:peer_turn_latency_traces.supporting_context_json"],
        "memoryos_sidecar": {"status_summary": {}, "latest": []},
    }
    assert sha256(db.read_bytes()).hexdigest() == before_hash
    assert sha256((tmp_path / "active_sessions.json").read_bytes()).hexdigest() == (
        before_active_sessions
    )
    assert sha256((tmp_path / "god_sessions.json").read_bytes()).hexdigest() == (
        before_god_sessions
    )
    after_sidecars = {path.name for path in tmp_path.iterdir() if path.name.startswith("chat.db-")}
    assert after_sidecars == before_sidecars


def test_dashboard_peer_chat_detail_filters_raw_proposal_envelopes(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    human = chat.add_message(conv.id, "Human", "human", "Keep details compact.")
    result = chat.create_proposal_message_and_log(
        conversation_id=conv.id,
        tool_name="chat.propose",
        caller_identity="architect-god",
        client_request_id="req-raw-proposal",
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Compact cards","lanes":[{"feature_id":"lane-a"}]}',
        references=[human.id],
        message_content="I drafted a lane graph.",
        envelope_json={
            "summary": "Compact cards",
            "lanes": [{"feature_id": "lane-a", "prompt": "large prompt"}],
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}")

    assert response.status_code == 200
    payload = response.json()
    assert [message["id"] for message in payload["messages"]] == [human.id]
    assert all(message.get("envelope_type") != "proposal" for message in payload["messages"])
    assert payload["cards"][0]["card_type"] == "proposal"
    assert payload["cards"][0]["source_id"] == result["proposal"]["id"]
    assert payload["cards"][0]["counts"]["lanes"] == 1
    assert "lanes" not in payload["cards"][0]
    assert [item["kind"] for item in payload["items"]] == ["message", "card"]


def test_dashboard_peer_session_detail_is_compact_and_linked(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-review",
                    "conversation_id": conv.id,
                    "participant_id": participant.participant_id,
                    "role": "review",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                    "status": "running",
                    "feature_scope_id": "feature-alpha",
                    "prompt_fingerprint": "sha256:keep-out-of-card",
                    "worktree": "/tmp/large/worktree/detail",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get("/api/dashboard/peer-chat/sessions/god-review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"] == {
        "god_session_id": "god-review",
        "conversation_id": conv.id,
        "participant_id": participant.participant_id,
        "role": "review",
        "runtime": "codex",
        "model": "gpt-5.5",
        "status": "running",
        "feature_scope_id": "feature-alpha",
        "href": "/dashboard/peer-chat/sessions/god-review",
        "api_href": "/api/dashboard/peer-chat/sessions/god-review",
    }
    assert payload["conversation"]["id"] == conv.id
    assert payload["participant"]["participant_id"] == participant.participant_id
    encoded = json.dumps(payload)
    assert "prompt_fingerprint" not in encoded
    assert "/tmp/large/worktree/detail" not in encoded


def test_dashboard_peer_request_and_result_drilldowns_follow_card_links(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-review",
                    "conversation_id": conv.id,
                    "participant_id": participant.participant_id,
                    "role": "review",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                    "status": "running",
                    "feature_scope_id": "feature-alpha",
                    "worktree": "/tmp/large/worktree/detail",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-alpha",
                    "feature_plan_feature_id": "feature-alpha",
                    "conversation_id": conv.id,
                    "graph_id": "graph-alpha",
                    "status": "reviewed",
                    "review_peer_id": participant.participant_id,
                    "peer_request_id": "req-alpha-review",
                    "peer_delivery_mode": "configured_peer",
                    "peer_routing_mode": "preferred",
                    "updated_at": "2026-05-31T09:00:00Z",
                    "prompt": "large peer prompt belongs outside compact drill-down",
                    "review_result": {
                        "raw": "large peer result belongs outside compact drill-down"
                    },
                },
                {
                    "feature_id": "lane-other",
                    "conversation_id": conv.id,
                    "status": "gate_failed",
                    "review_peer_id": participant.participant_id,
                    "peer_request_id": "req-other",
                    "peer_delivery_mode": "required_peer_failed",
                    "peer_degraded_reason": "noise",
                },
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    timeline = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}").json()
    request_card = next(
        card
        for card in timeline["cards"]
        if card["card_type"] == "peer_request" and card["source_id"] == "req-alpha-review"
    )
    result_card = next(
        card
        for card in timeline["cards"]
        if card["card_type"] == "peer_result" and card["source_id"] == "req-alpha-review"
    )

    request_response = client.get(request_card["api_href"])
    result_response = client.get(result_card["api_href"])

    assert request_response.status_code == 200
    request_payload = request_response.json()
    assert request_payload["request"] == {
        "request_id": "req-alpha-review",
        "message_type": "review",
        "status": "sent",
        "conversation_id": conv.id,
        "participant_id": participant.participant_id,
        "god_session_id": "god-review",
        "lane_id": "lane-alpha",
        "feature_id": "feature-alpha",
        "graph_id": "graph-alpha",
        "dashboard_href": (
            f"/dashboard/peer-chat/conversations/{conv.id}#peer-request-req-alpha-review"
        ),
        "api_href": "/api/peer-requests/req-alpha-review",
        "result_api_href": "/api/peer-requests/req-alpha-review/result",
        "session_api_href": "/api/dashboard/peer-chat/sessions/god-review",
    }
    assert request_payload["lane"] == {
        "feature_id": "lane-alpha",
        "status": "reviewed",
        "effective_status": "reviewed",
        "conversation_id": conv.id,
        "graph_id": "graph-alpha",
        "feature_ref": "feature-alpha",
    }
    assert request_payload["card"]["source_id"] == "req-alpha-review"
    assert request_payload["session"]["god_session_id"] == "god-review"

    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["result"] == {
        "request_id": "req-alpha-review",
        "message_type": "review",
        "status": "completed",
        "result_status": "ok",
        "reason": None,
        "conversation_id": conv.id,
        "participant_id": participant.participant_id,
        "god_session_id": "god-review",
        "lane_id": "lane-alpha",
        "feature_id": "feature-alpha",
        "graph_id": "graph-alpha",
        "request_api_href": "/api/peer-requests/req-alpha-review",
    }
    assert result_payload["card"]["source_id"] == "req-alpha-review"

    encoded = json.dumps({"request": request_payload, "result": result_payload})
    assert "large peer prompt" not in encoded
    assert "large peer result" not in encoded
    assert "/tmp/large/worktree/detail" not in encoded
    assert "req-other" not in encoded


def test_dashboard_gray_box_card_drilldowns_are_compact_and_conversation_scoped(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    other = chat.create_conversation("Other mission")
    chat.add_message(conv.id, "Human", "human", "Keep drill-down payloads compact.")

    graph_dir = tmp_path / "lane_graphs"
    graph_dir.mkdir()
    _write_json(
        graph_dir / "graph-alpha.json",
        {
            "id": "graph-alpha",
            "conversation_id": conv.id,
            "resolution_id": "res-alpha",
            "version": 1,
            "status": "planned",
            "lanes": [
                {
                    "feature_id": "lane-alpha",
                    "prompt": "large lane prompt belongs behind deeper raw APIs",
                }
            ],
        },
    )
    _write_json(
        graph_dir / "graph-set-alpha.json",
        {
            "id": "graph-set-alpha",
            "feature_plan": {
                "id": "plan-alpha",
                "conversation_id": conv.id,
                "resolution_id": "res-alpha",
                "version": 1,
                "features": [
                    {
                        "feature_id": "feature-alpha",
                        "title": "Feature Alpha",
                        "goal": "Keep cards compact.",
                        "acceptance_criteria": ["Compact drill-downs exist."],
                        "graph_id": "graph-alpha",
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-alpha",
                    "conversation_id": conv.id,
                    "resolution_id": "res-alpha",
                    "version": 1,
                    "lanes": [
                        {
                            "feature_id": "lane-alpha",
                            "prompt": "large graph-set prompt belongs behind deeper raw APIs",
                        }
                    ],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-alpha",
                    "conversation_id": conv.id,
                    "graph_id": "graph-alpha",
                    "status": "pending",
                    "prompt": "large runtime prompt should not be embedded",
                },
                {
                    "feature_id": "lane-other",
                    "conversation_id": other.id,
                    "status": "merged",
                    "prompt": "other conversation should stay isolated",
                },
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    timeline = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}")

    assert timeline.status_code == 200
    cards = timeline.json()["cards"]
    lane_graph_card = next(card for card in cards if card["card_type"] == "lane_graph")
    graph_set_card = next(card for card in cards if card["card_type"] == "feature_graph_set")
    health_card = next(card for card in cards if card["card_type"] == "health_summary")

    assert lane_graph_card["href"] == (
        f"/dashboard/peer-chat/conversations/{conv.id}#lane-graph-graph-alpha"
    )
    assert lane_graph_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{conv.id}/lane-graphs/graph-alpha"
    )
    assert graph_set_card["href"] == (
        f"/dashboard/peer-chat/conversations/{conv.id}#feature-graph-set-graph-set-alpha"
    )
    assert graph_set_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{conv.id}/feature-graph-sets/graph-set-alpha"
    )
    assert health_card["href"] == (f"/dashboard/peer-chat/conversations/{conv.id}#run-health")
    assert health_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{conv.id}/run-health"
    )

    lane_graph_payload = client.get(lane_graph_card["api_href"])
    graph_set_payload = client.get(graph_set_card["api_href"])
    health_payload = client.get(health_card["api_href"])

    assert lane_graph_payload.status_code == 200
    assert lane_graph_payload.json()["graph"] == {
        "id": "graph-alpha",
        "conversation_id": conv.id,
        "status": "planned",
        "resolution_id": "res-alpha",
        "version": 1,
        "lane_count": 1,
        "dashboard_href": "/dashboard/lane-graphs/graph-alpha",
        "raw_api_href": "/api/lane-graphs/graph-alpha",
    }
    assert graph_set_payload.status_code == 200
    assert graph_set_payload.json()["graph_set"] == {
        "id": "graph-set-alpha",
        "conversation_id": conv.id,
        "feature_plan_id": "plan-alpha",
        "resolution_id": "res-alpha",
        "version": 1,
        "feature_count": 1,
        "lane_graph_count": 1,
        "status": "planned",
        "dashboard_href": "/dashboard/feature-graph-sets/graph-set-alpha",
        "raw_api_href": "/api/feature-graph-sets/graph-set-alpha",
    }
    assert health_payload.status_code == 200
    assert health_payload.json()["conversation_id"] == conv.id
    assert health_payload.json()["card"]["source_id"] == "run_health"
    assert health_payload.json()["run_health"]["counts"]["terminal"] == 0
    assert health_payload.json()["run_health"]["groups"]["terminal"] == []

    encoded = json.dumps(
        {
            "cards": cards,
            "lane_graph": lane_graph_payload.json(),
            "graph_set": graph_set_payload.json(),
            "health": health_payload.json(),
        }
    )
    assert "large lane prompt" not in encoded
    assert "large graph-set prompt" not in encoded
    assert "large runtime prompt" not in encoded
    assert "other conversation" not in encoded


# ---------------------------------------------------------------------------
# Conversation inspector endpoint tests
# (GET /api/dashboard/peer-chat/conversations/{conversation_id}/inspector)
# ---------------------------------------------------------------------------


def test_conversation_inspector_returns_full_summary_with_participants_blueprint_and_graphs(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission Alpha")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    chat.add_message(conv.id, "Human", "human", "Build a dashboard")
    chat.add_message(conv.id, "Architect GOD", "architect", "Here is the plan")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="mission_blueprint",
        content='{"type":"mission_blueprint","title":"Dashboard","acceptance_criteria":["works"]}',
        references=[],
    )
    resolution = chat.approve_proposal(
        proposal_id=proposal.id,
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Build dashboard",
    )
    (tmp_path / "lane_graphs").mkdir(parents=True, exist_ok=True)
    _write_json(
        tmp_path / "lane_graphs" / "graph-set-alpha.json",
        {
            "id": "graph-set-alpha",
            "feature_plan": {
                "id": "plan-alpha",
                "conversation_id": conv.id,
                "version": 1,
                "features": [{"feature_id": "f1", "title": "Build UI"}],
            },
            "graphs": [
                {
                    "id": "graph-alpha",
                    "conversation_id": conv.id,
                    "version": 1,
                    "lanes": [{"feature_id": "lane-alpha"}],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-alpha",
                    "conversation_id": conv.id,
                    "graph_id": "graph-alpha",
                    "status": "pending",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()

    # conversation
    assert body["conversation"]["id"] == conv.id
    assert body["conversation"]["title"] == "Mission Alpha"

    # participants summary
    assert body["participants"]["total"] == 1
    assert body["participants"]["summary"]["architect"] == 1
    assert body["participants"]["items"][0]["participant_id"] == participant.participant_id

    # recent activity
    assert body["recent_activity"]["message_count"] == 2
    assert len(body["recent_activity"]["messages"]) == 2
    assert body["recent_activity"]["card_count"] >= 1

    # current blueprint (extracted from resolutions/cards)
    assert body["current_blueprint"] is not None
    assert body["current_blueprint"]["id"] == resolution.id
    assert body["current_blueprint"]["title"] == "Dashboard"

    # feature plan (extracted from graph-set cards)
    assert body["current_feature_plan"] is not None
    assert body["current_feature_plan"]["id"] == "plan-alpha"
    assert body["current_feature_plan"]["feature_count"] == 1

    # graph set
    assert body["current_graph_set"] is not None
    assert body["current_graph_set"]["id"] == "graph-set-alpha"


def test_conversation_inspector_includes_provider_summary_by_provider_and_cli_kind(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Provider Mix")
    participants = ParticipantStore(db)
    participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="opencode",
        model="gpt-5.5",
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector"
    )

    assert response.status_code == 200
    assert response.json()["participants"]["provider_summary"] == [
        {"provider_id": "codex", "cli_kind": "codex", "count": 2},
        {"provider_id": "opencode", "cli_kind": "opencode", "count": 1},
    ]


def test_conversation_inspector_includes_recent_peer_latency_trace(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Latency Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id="inbox-latency-1",
        participant_id=participant.participant_id,
        target_role="architect",
        god_session_id="god-inspector",
        provider_session_id="provider-inspector-thread",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        message_created_at="2026-06-04T01:00:00Z",
        inbox_claimed_at="2026-06-04T01:00:01Z",
        delivery_started_at=10.0,
        provider_turn_started_at=10.2,
        first_delta_at=10.9,
        writeback_at=11.4,
        total_latency_ms=1400,
        delivery_mode="stdout_fallback",
        degraded_reason="stdout_fallback",
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector"
    )

    assert response.status_code == 200
    traces = response.json()["peer_latency"]["recent_turns"]
    assert traces[0]["inbox_item_id"] == "inbox-latency-1"
    assert traces[0]["target_role"] == "architect"
    assert traces[0]["god_session_id"] == "god-inspector"
    assert traces[0]["provider_session_id"] == "provider-inspector-thread"
    assert traces[0]["provider_session_kind"] == "codex_app_server_thread"
    assert traces[0]["provider_binding_status"] == "active"
    assert traces[0]["delivery_mode"] == "stdout_fallback"
    assert traces[0]["degraded_reason"] == "stdout_fallback"
    assert traces[0]["total_latency_ms"] == 1400


def test_dashboard_peer_chat_runtime_timeline_projects_inspector_state(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    created = PeerChatService(db).create_conversation(
        title="Runtime Timeline",
        init_mode="proposal_then_approve",
    )
    conv_id = created["conversation"]["id"]
    collaboration = ChatCollaborationStore(db)
    run = collaboration.create_request(
        conversation_id=conv_id,
        goal="Ship runtime timeline",
        initiator="architect",
        targets=["review", "execute"],
        callback_target="architect",
        question="Can this dispatch safely?",
        context_refs=["proposal:runtime-cards"],
        idempotency_key="runtime-timeline",
        timeout_s=480,
    )
    collaboration.record_response(
        run.run_id,
        target="execute",
        content=(
            '{"type":"execute_feasibility_verdict","status":"executable",'
            '"execution_performed":false,"summary":"ready",'
            '"evidence_refs":["proposal:runtime-cards"]}'
        ),
        response_status="received",
    )
    blocker = collaboration.raise_blocker(
        run.run_id,
        issuer="review",
        severity="veto",
        reason="Dashboard timeline must show veto before dispatch.",
        affected_ref="dashboard:runtime-timeline",
        suggested_fix="Expose timeline event.",
        blocks_dispatch=True,
    )
    collaboration.evaluate_dispatch_gate(
        conversation_id=conv_id,
        run_id=run.run_id,
        proposal_ref="proposal:runtime-cards",
        artifact_ref="artifact:lane_graph",
        execute_confirmed=True,
        policy_allows_real_provider=True,
    )
    collaboration.resolve_blocker(
        blocker.blocker_id,
        resolved_by="review",
        resolution_evidence="timeline-card-added",
    )
    collaboration.evaluate_dispatch_gate(
        conversation_id=conv_id,
        run_id=run.run_id,
        proposal_ref="proposal:runtime-cards",
        artifact_ref="artifact:lane_graph",
        execute_confirmed=True,
        policy_allows_real_provider=True,
    )
    entry = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv_id,
        proposal_id="proposal-runtime-cards",
        resolution_id="resolution-runtime-cards",
        collaboration_run_id=run.run_id,
        artifact_ref="artifact:lane_graph",
    )
    claimed = ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conv_id,
        claimed_by="bridge-test",
    )
    assert claimed is not None
    ChatDispatchQueueStore(db).mark_dispatched(
        entry.entry_id,
        provider_run_ref="provider:execute:part-execute",
        dispatch_evidence="mcp_writeback:dispatch-inbox",
    )
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv_id,
        inbox_item_id="dispatch-inbox",
        participant_id="part-execute",
        target_role="execute",
        message_created_at="2026-06-05T01:00:00Z",
        inbox_claimed_at="2026-06-05T01:00:01Z",
        delivery_started_at=10.0,
        provider_turn_started_at=10.1,
        first_delta_at=10.2,
        writeback_at=11.5,
        total_latency_ms=1500,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv_id}/runtime-timeline"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == conv_id
    assert body["source_authority"] == "chat_inspector"
    event_types = [event["event_type"] for event in body["events"]]
    assert event_types == [
        "bootstrap",
        "collaboration_run",
        "blocker_resolved",
        "dispatch_gate",
        "dispatch_gate",
        "dispatch_queue",
        "provider_writeback",
    ]
    by_type = {event["event_type"]: event for event in body["events"]}
    assert by_type["bootstrap"]["summary"].startswith("proposal_ready")
    assert by_type["collaboration_run"]["summary"] == (
        f"{run.run_id} partial peer_consensus targets=review, execute responses=1 blockers=1"
    )
    assert by_type["blocker_resolved"]["status"] == "resolved"
    assert by_type["dispatch_queue"]["summary"] == (
        f"{entry.entry_id} dispatched agent target=execute auto provider:execute:part-execute"
    )
    assert by_type["provider_writeback"]["summary"] == (
        "mcp_writeback execute evidence=dispatch-inbox"
    )
    assert all(
        event["api_href"] == f"/api/dashboard/peer-chat/conversations/{conv_id}/runtime-timeline"
        for event in body["events"]
    )


def test_conversation_inspector_links_dashboard_runtime_timeline(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conv = ChatStore(db).create_conversation("Runtime Timeline Link")

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector"
    )

    assert response.status_code == 200
    runtime_refs = response.json()["runtime_timeline_refs"]
    assert runtime_refs == {
        "dashboard": {
            "href": f"/dashboard/peer-chat/conversations/{conv.id}#runtime-timeline",
            "label": "Runtime timeline",
        },
        "api": {
            "api_href": (f"/api/dashboard/peer-chat/conversations/{conv.id}/runtime-timeline"),
            "label": "Runtime timeline",
        },
    }


def test_conversation_inspector_exposes_separated_closure_evidence(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Closure Evidence")
    intake = chat.add_message(
        conv.id,
        "Human",
        "human",
        "Expose closure evidence for review, dispatch, and lane execution.",
    )
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content=json.dumps(
            {
                "summary": "Expose separated closure evidence",
                "lanes": [
                    {
                        "feature_id": "closure-evidence-read-model",
                        "prompt": "Expose separated closure evidence.",
                    }
                ],
            }
        ),
        references=[f"intake_message:{intake.id}"],
    )
    spine_store = AcceptanceSpineStore(db)
    spine_store.create_for_intake(
        conversation_id=conv.id,
        intake_message_id=intake.id,
    )
    spine_store.attach_proposal(
        conversation_id=conv.id,
        intake_message_id=intake.id,
        proposal_id=proposal.id,
    )
    spine_store.attach_review_trigger_for_proposal(
        proposal_id=proposal.id,
        review_trigger_inbox_id="inbox-review-trigger",
    )
    spine_store.attach_verdict_for_proposal(
        proposal_id=proposal.id,
        verdict_ref="resolution:res-closure-evidence",
    )
    dispatch_entry = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id="res-closure-evidence",
        collaboration_run_id="collab-closure-evidence",
        artifact_ref="artifact:lane_graph",
    )
    claimed = ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conv.id,
        claimed_by="bridge-test",
    )
    assert claimed is not None
    ChatDispatchQueueStore(db).mark_dispatched(
        dispatch_entry.entry_id,
        provider_run_ref="peer_ack:execute:part-execute",
        dispatch_evidence="mcp_writeback:inbox-dispatch-ack",
    )
    spine_store.attach_lane_execution_for_resolution(
        resolution_id="res-closure-evidence",
        evidence_refs=[
            "feature_lanes.json#lane=closure-evidence-read-model:status=executed",
            "lane_graph:graph-closure-evidence",
            "dispatch_attempt:attempt-closure-evidence",
        ],
    )
    spine_store.attach_review_verdict_for_resolution(
        resolution_id="res-closure-evidence",
        review_verdict_ref="review_plane.json#verdict=closure-evidence-reviewed",
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector"
    )

    assert response.status_code == 200
    closure = response.json()["closure_evidence"]
    assert closure["schema_version"] == "closure_evidence/v1"
    assert closure["source_authority"] == [
        "chat.db:acceptance_spines",
        "chat.db:chat_dispatch_queue",
    ]
    assert closure["status_summary"] == {"reviewed": 1}
    assert closure["proposal_review"] == {
        "total": 1,
        "refs": ["resolution:res-closure-evidence"],
    }
    assert closure["dispatch_ack"] == {
        "total": 2,
        "refs": [
            "peer_ack:execute:part-execute",
            "mcp_writeback:inbox-dispatch-ack",
        ],
    }
    assert closure["lane_execution"] == {
        "total": 3,
        "refs": [
            "feature_lanes.json#lane=closure-evidence-read-model:status=executed",
            "lane_graph:graph-closure-evidence",
            "dispatch_attempt:attempt-closure-evidence",
        ],
    }
    assert closure["independent_review"] == {
        "total": 1,
        "refs": ["review_plane.json#verdict=closure-evidence-reviewed"],
    }
    assert closure["items"][0]["dispatch_item_id"] == dispatch_entry.entry_id
    assert closure["items"][0]["review_trigger_inbox_id"] == "inbox-review-trigger"


def test_dashboard_runtime_timeline_prefers_latest_row_when_timestamps_tie(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conv = ChatStore(db).create_conversation("Runtime Timeline Tie")
    collaboration = ChatCollaborationStore(db)
    older = collaboration.create_request(
        conversation_id=conv.id,
        goal="Older discussion",
        initiator="architect",
        targets=["execute"],
        callback_target="architect",
        question="First?",
        context_refs=[],
        idempotency_key="runtime-tie-older",
        timeout_s=480,
    )
    newer = collaboration.create_request(
        conversation_id=conv.id,
        goal="Newer discussion",
        initiator="review",
        targets=["architect"],
        callback_target="review",
        question="Second?",
        context_refs=[],
        idempotency_key="runtime-tie-newer",
        timeout_s=480,
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update collaboration_runs set created_at = ?, updated_at = ?",
            ("2026-06-05T02:00:00Z", "2026-06-05T02:00:00Z"),
        )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/runtime-timeline"
    )

    assert response.status_code == 200
    discussion_events = [
        event for event in response.json()["events"] if event["event_type"] == "collaboration_run"
    ]
    assert discussion_events[0]["event_id"] == newer.run_id
    assert discussion_events[0]["event_id"] != older.run_id


def test_dashboard_runtime_timeline_ignores_unrelated_peer_latency_writeback(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conv = ChatStore(db).create_conversation("Runtime Timeline Writeback")
    entry = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id="proposal-runtime-cards",
        resolution_id="resolution-runtime-cards",
        collaboration_run_id="collab-runtime-cards",
        artifact_ref="artifact:lane_graph",
    )
    claimed = ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conv.id,
        claimed_by="bridge-test",
    )
    assert claimed is not None
    ChatDispatchQueueStore(db).mark_dispatched(
        entry.entry_id,
        provider_run_ref="provider:execute:part-execute",
        dispatch_evidence="mcp_writeback:dispatch-inbox",
    )
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id="ordinary-inbox",
        participant_id="part-architect",
        target_role="architect",
        message_created_at="2026-06-05T01:00:00Z",
        inbox_claimed_at="2026-06-05T01:00:01Z",
        delivery_started_at=10.0,
        provider_turn_started_at=10.1,
        first_delta_at=10.2,
        writeback_at=11.5,
        total_latency_ms=1500,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
    )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/runtime-timeline"
    )

    assert response.status_code == 200
    event_types = [event["event_type"] for event in response.json()["events"]]
    assert "dispatch_queue" in event_types
    assert "provider_writeback" not in event_types


def test_dashboard_runtime_timeline_prefers_newest_dispatch_queue_row_on_tie(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conv = ChatStore(db).create_conversation("Runtime Timeline Dispatch Tie")
    queue = ChatDispatchQueueStore(db)
    older = queue.enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id="proposal-older",
        resolution_id="resolution-older",
        collaboration_run_id="collab-older",
        artifact_ref="artifact:lane_graph",
    )
    newer = queue.enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id="proposal-newer",
        resolution_id="resolution-newer",
        collaboration_run_id="collab-newer",
        artifact_ref="artifact:lane_graph",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update chat_dispatch_queue set created_at = ?, updated_at = ?",
            ("2026-06-05T02:00:00Z", "2026-06-05T02:00:00Z"),
        )

    response = TestClient(create_app(tmp_path)).get(
        f"/api/dashboard/peer-chat/conversations/{conv.id}/runtime-timeline"
    )

    assert response.status_code == 200
    dispatch_events = [
        event for event in response.json()["events"] if event["event_type"] == "dispatch_queue"
    ]
    assert dispatch_events[0]["event_id"] == newer.entry_id
    assert dispatch_events[0]["event_id"] != older.entry_id


def test_conversation_inspector_stable_with_missing_data(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Empty Mission")

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()

    assert body["conversation"]["id"] == conv.id
    assert body["participants"]["total"] == 0
    assert body["participants"]["summary"] == {}
    assert body["participants"]["provider_summary"] == []
    assert body["recent_activity"]["message_count"] == 0
    assert body["recent_activity"]["card_count"] == 0
    assert body["current_blueprint"] is None
    assert body["current_feature_plan"] is None
    assert body["current_graph_set"] is None


def test_conversation_inspector_returns_404_for_unknown_conversation(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/dashboard/peer-chat/conversations/nonexistent/inspector")
    assert response.status_code == 404


def test_conversation_inspector_does_not_contain_write_semantics(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Read Only")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")
    assert response.status_code == 200
    body = response.json()

    encoded = json.dumps(body)
    assert "claim" not in encoded
    assert "approve" not in encoded
    assert "reject" not in encoded
    assert "rework" not in encoded
    assert "write" not in encoded


# ---------------------------------------------------------------------------
# Participant + inbox summary in inspector tests
# ---------------------------------------------------------------------------


def test_inspector_participant_inbox_summary_shows_counts_per_participant(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    arch = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    review = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="review",
        display_name="Review",
        cli_kind="codex",
        model="gpt-5.5",
    )
    msg = chat.add_message(conv.id, "Human", "human", "design this")
    inbox = ChatInboxStore(db)
    inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=arch.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=msg.id,
        item_type="mention",
        payload={"content": "design this"},
    )
    inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=review.participant_id,
        target_role="review",
        target_address="@review",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=msg.id,
        item_type="mention",
        payload={"content": "design this"},
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()
    inbox_by_participant = {
        entry["participant_id"]: entry for entry in body["participants"]["inbox_summary"]
    }
    arch_inbox = inbox_by_participant[arch.participant_id]
    assert arch_inbox["unread"] == 1
    assert arch_inbox["claimed"] == 0
    assert arch_inbox["failed"] == 0
    assert arch_inbox["read"] == 0

    review_inbox = inbox_by_participant[review.participant_id]
    assert review_inbox["unread"] == 1
    assert review_inbox["claimed"] == 0
    assert review_inbox["failed"] == 0


def test_inspector_inbox_summary_empty_when_no_inbox_items(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Empty")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()
    assert body["participants"]["inbox_summary"] == []


def test_inspector_inbox_summary_counts_only_non_terminal_items_for_unread_claimed(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    arch = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    msg = chat.add_message(conv.id, "Human", "human", "design this")
    inbox = ChatInboxStore(db)
    inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=arch.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=msg.id,
        item_type="mention",
        payload={"content": "design this"},
    )
    inbox.claim_next(owner="sched")
    # Manually create a failed item via the store
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into chat_inbox_items "
            "(id, conversation_id, target_participant_id, target_role, "
            "target_address, sender_participant_id, sender_address, "
            "source_message_id, item_type, payload_json, status, "
            "failure_reason, created_at, updated_at) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "inbox_failed",
                conv.id,
                arch.participant_id,
                "architect",
                "@architect",
                None,
                "@human",
                msg.id,
                "mention",
                '{"content": "failed task"}',
                "failed",
                "timeout",
                "2026-06-04T00:00:00Z",
                "2026-06-04T00:00:00Z",
            ),
        )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()
    arch_inbox = body["participants"]["inbox_summary"][0]
    assert arch_inbox["participant_id"] == arch.participant_id
    assert arch_inbox["unread"] == 0
    assert arch_inbox["claimed"] == 1
    assert arch_inbox["failed"] == 1
    assert arch_inbox["read"] == 0


# ---------------------------------------------------------------------------
# Session health in inspector tests
# ---------------------------------------------------------------------------


def test_inspector_session_health_shows_sessions_by_conversation(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-alpha",
                    "conversation_id": conv.id,
                    "participant_id": "part-1",
                    "role": "architect",
                    "status": "running",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                },
                {
                    "god_session_id": "god-beta",
                    "conversation_id": conv.id,
                    "participant_id": "part-2",
                    "role": "review",
                    "status": "running",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                },
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()
    sh = body["session_health"]
    assert sh["total"] == 2
    assert sh["by_status"]["running"] == 2
    assert len(sh["items"]) == 2
    session_ids = {s["god_session_id"] for s in sh["items"]}
    assert session_ids == {"god-alpha", "god-beta"}


def test_inspector_session_health_reads_durable_god_sessions(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = registry.create(
        role="architect",
        agent_name="architect-god",
        runtime="codex",
        session_address="@conv:architect",
        session_inbox_id="inbox-conv-architect",
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        model="gpt-5.5",
    )
    registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="thread-architect",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.update_prompt_contract(
        session.god_session_id,
        prompt_contract_version="xmuse-peer-chat-prompt-v2",
        prompt_layer_order=["xmuse_governance_l0", "member_identity"],
        prompt_layer_hashes={
            "xmuse_governance_l0": "sha256:governance",
            "member_identity": "sha256:identity",
        },
        prompt_artifact_fingerprint="sha256:prompt-artifact",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    sh = response.json()["session_health"]
    assert sh["total"] == 1
    assert sh["by_status"]["starting"] == 1
    assert sh["items"][0]["god_session_id"] == session.god_session_id
    assert sh["items"][0]["provider_session_id"] == "thread-architect"
    assert sh["items"][0]["prompt_contract_version"] == "xmuse-peer-chat-prompt-v2"
    assert sh["items"][0]["prompt_layer_order"] == [
        "xmuse_governance_l0",
        "member_identity",
    ]
    assert sh["items"][0]["prompt_artifact_fingerprint"] == "sha256:prompt-artifact"


def test_inspector_session_health_prefers_durable_status_for_same_session_id(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    participant = ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = registry.create(
        role="architect",
        agent_name="architect-god",
        runtime="codex",
        session_address="@conv:architect",
        session_inbox_id="inbox-conv-architect",
        conversation_id=conv.id,
        participant_id=participant.participant_id,
        model="gpt-5.5",
    )
    registry.promote_running(session.god_session_id)
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": session.god_session_id,
                    "conversation_id": conv.id,
                    "participant_id": participant.participant_id,
                    "role": "architect",
                    "status": "starting",
                    "pid": 12345,
                    "runtime": "codex",
                    "model": "gpt-5.5",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    sh = response.json()["session_health"]
    assert sh["total"] == 1
    assert sh["by_status"]["running"] == 1
    assert "starting" not in sh["by_status"]
    assert sh["items"][0]["status"] == "running"
    assert sh["items"][0]["pid"] == 12345


def test_inspector_session_health_empty_when_no_sessions(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Empty")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    sh = response.json()["session_health"]
    assert sh["total"] == 0
    assert sh["by_status"] == {}
    assert sh["items"] == []


def test_inspector_session_health_classifies_stopped_sessions(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-running",
                    "conversation_id": conv.id,
                    "role": "architect",
                    "status": "running",
                },
                {
                    "god_session_id": "god-stopped",
                    "conversation_id": conv.id,
                    "role": "review",
                    "status": "stopped",
                },
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    sh = response.json()["session_health"]
    assert sh["total"] == 2
    assert sh["by_status"]["running"] == 1
    assert sh["by_status"]["stopped"] == 1


# ---------------------------------------------------------------------------
# Graph + worklist in inspector tests
# ---------------------------------------------------------------------------


def test_inspector_graph_worklist_shows_authority_and_lane_summary(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    # Write lane graph for authority state
    (tmp_path / "lane_graphs").mkdir(parents=True, exist_ok=True)
    _write_json(
        tmp_path / "lane_graphs" / "graph-alpha.json",
        {
            "id": "graph-alpha",
            "conversation_id": conv.id,
            "version": 1,
            "status": "planned",
            "lanes": [{"feature_id": "lane-alpha"}],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-alpha", "conversation_id": conv.id, "status": "pending"},
                {"feature_id": "lane-beta", "conversation_id": conv.id, "status": "merged"},
            ]
        },
    )
    (tmp_path / "self_evolution").mkdir(parents=True, exist_ok=True)
    _write_json(
        tmp_path / "self_evolution" / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": "lin-1",
                    "source_run_id": "run-a",
                    "spawned_graph_id": "graph-alpha",
                    "blueprint_set_id": "bp-1",
                    "target_track_ids": [],
                    "evolution_proposal_id": "prop-1",
                    "guardrail_decision_id": "guard-1",
                    "created_at": "2026-06-04T00:00:00Z",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    body = response.json()
    gw = body["graph_worklist"]
    assert "authoritative_graph_id" in gw
    assert "lane_summary" in gw
    assert gw["total_lanes"] == 2
    assert isinstance(gw["lane_summary"], dict)


def test_inspector_graph_worklist_empty_when_no_lanes(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Empty")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    gw = response.json()["graph_worklist"]
    assert gw["total_lanes"] == 0
    assert gw["lane_summary"] == {}
    assert gw["authoritative_graph_id"] is None


# ---------------------------------------------------------------------------
# Artifact explorer in inspector tests
# ---------------------------------------------------------------------------


def test_inspector_artifacts_summarizes_available_artifacts(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    chat.add_message(conv.id, "Human", "human", "build it")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect",
        proposal_type="mission_blueprint",
        content='{"type":"mission_blueprint","title":"Build Dashboard"}',
        references=[],
    )
    chat.approve_proposal(
        proposal_id=proposal.id,
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Build dashboard",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    arts = response.json()["artifacts"]
    assert arts["total"] >= 1
    assert any(a["type"] == "mission_blueprint" for a in arts["items"])
    assert any(a.get("title") for a in arts["items"])


def test_inspector_artifacts_empty_when_no_proposals(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Empty")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    arts = response.json()["artifacts"]
    assert arts["total"] == 0
    assert arts["items"] == []


# ---------------------------------------------------------------------------
# Degradation/failure in inspector tests
# ---------------------------------------------------------------------------


def test_inspector_degradation_is_conversation_scoped(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv1 = chat.create_conversation("Conv1")
    conv2 = chat.create_conversation("Conv2")
    for cid in (conv1.id, conv2.id):
        ParticipantStore(db).add(
            conversation_id=cid,
            role="architect",
            display_name="Arch",
            cli_kind="codex",
            model="gpt-5.5",
        )
    # Error referencing a lane in conv2
    _write_json(
        tmp_path / "error_knowledge.json",
        {"entries": [{"id": "err-conv2", "lane_id": "lane-conv2", "pit": "conv2 only failure"}]},
    )
    # Lane in conv1 and lane in conv2
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-conv1", "conversation_id": conv1.id, "status": "failed"},
                {"feature_id": "lane-conv2", "conversation_id": conv2.id, "status": "failed"},
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    r1 = client.get(f"/api/dashboard/peer-chat/conversations/{conv1.id}/inspector")
    r2 = client.get(f"/api/dashboard/peer-chat/conversations/{conv2.id}/inspector")

    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()["degradation"]
    d2 = r2.json()["degradation"]

    # conv1 must NOT see conv2's error
    assert d1["error_count"] == 0
    assert d1["errors"] == []
    # conv2 must see its own error
    assert d2["error_count"] == 1
    assert d2["errors"][0]["id"] == "err-conv2"


def _add_conv_lane_and_errors(conv, tmp_path, errors, lane_id="lane-alpha"):
    """Helper to add a lane and matching error entries for conversation-scoped degradation."""
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": lane_id, "conversation_id": conv.id, "status": "failed"}]},
    )
    _write_json(
        tmp_path / "error_knowledge.json",
        {"entries": [{**e, "lane_id": lane_id} for e in errors]},
    )


def test_inspector_degradation_includes_error_details(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Errors")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Arch",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _add_conv_lane_and_errors(
        conv,
        tmp_path,
        [
            {"entry_id": "err-1", "message": "first error"},
            {"entry_id": "err-2", "message": "second error"},
        ],
    )

    client = TestClient(create_app(tmp_path))
    resp = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert resp.status_code == 200
    deg = resp.json()["degradation"]
    assert deg["error_count"] == 2
    assert len(deg["errors"]) == 2
    assert any("first error" in str(e) for e in deg["errors"])


def test_inspector_degradation_limits_error_details(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Many")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Arch",
        cli_kind="codex",
        model="gpt-5.5",
    )
    many_errors = [{"entry_id": f"err-{i}", "message": f"error {i}"} for i in range(100)]
    _add_conv_lane_and_errors(conv, tmp_path, many_errors)

    client = TestClient(create_app(tmp_path))
    resp = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert resp.status_code == 200
    deg = resp.json()["degradation"]
    assert deg["error_count"] == 100
    assert len(deg["errors"]) <= 5


def test_inspector_degradation_shows_dead_letters_and_errors(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Mission")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    _add_conv_lane_and_errors(
        conv,
        tmp_path,
        [{"entry_id": "err-1", "message": "test failure"}],
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    deg = response.json()["degradation"]
    assert deg["error_count"] == 1
    assert "dead_letter_count" in deg
    assert "read_model_degraded" in deg


def test_inspector_degradation_empty_when_no_errors(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Clean")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")

    assert response.status_code == 200
    deg = response.json()["degradation"]
    assert deg["error_count"] == 0
    assert deg["dead_letter_count"] == 0
    assert "read_model_degraded" in deg


# ---------------------------------------------------------------------------
# Cross-surface parity tests (dashboard inspector vs MCP inspector)
# ---------------------------------------------------------------------------


def test_inspector_cross_surface_parity_core_fields_match(
    tmp_path: Path,
) -> None:
    from xmuse.mcp_server import create_app as create_mcp_app

    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Parity")
    ParticipantStore(db).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.5",
    )
    chat.add_message(conv.id, "Human", "human", "build it")

    dash_client = TestClient(create_app(tmp_path))
    dash_resp = dash_client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")
    assert dash_resp.status_code == 200
    dash_body = dash_resp.json()

    mcp_client = TestClient(create_mcp_app(tmp_path))
    mcp_resp = mcp_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "chat_inspect_conversation",
                "arguments": {"conversation_id": conv.id},
            },
        },
    )
    assert mcp_resp.status_code == 200
    mcp_body = json.loads(mcp_resp.json()["result"]["content"][0]["text"])

    # Core fields: both surfaces must agree on conversation id
    assert dash_body["conversation"]["id"] == mcp_body["conversation"]["id"] == conv.id
    assert dash_body["conversation"]["title"] == mcp_body["conversation"]["title"] == "Parity"

    # Both must have the same sections
    for section in (
        "participants",
        "session_health",
        "graph_worklist",
        "artifacts",
        "degradation",
        "recent_activity",
    ):
        assert section in dash_body, f"dashboard missing {section}"
        assert section in mcp_body, f"MCP missing {section}"

    # Value-level parity: key fields must agree numerically
    d, m = dash_body, mcp_body
    assert d["participants"]["total"] == m["participants"]["total"]
    assert d["recent_activity"]["message_count"] == m["recent_activity"]["message_count"]
    assert d["session_health"]["total"] == m["session_health"]["total"]
    assert d["artifacts"]["total"] == m["artifacts"]["total"]
    assert d["degradation"]["error_count"] == m["degradation"]["error_count"]
    assert d["graph_worklist"]["total_lanes"] == m["graph_worklist"]["total_lanes"]
    assert d["graph_worklist"].get("authoritative_graph_id") == m["graph_worklist"].get(
        "authoritative_graph_id"
    )


def test_inspector_cross_surface_parity_empty_state(tmp_path: Path) -> None:
    from xmuse.mcp_server import create_app as create_mcp_app

    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Empty")

    dash_client = TestClient(create_app(tmp_path))
    dash_resp = dash_client.get(f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector")
    assert dash_resp.status_code == 200
    dash_body = dash_resp.json()

    mcp_client = TestClient(create_mcp_app(tmp_path))
    mcp_resp = mcp_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "chat_inspect_conversation",
                "arguments": {"conversation_id": conv.id},
            },
        },
    )
    mcp_body = json.loads(mcp_resp.json()["result"]["content"][0]["text"])

    # Empty states must agree — value-level for ALL numeric fields
    for section in (
        "recent_activity",
        "session_health",
        "graph_worklist",
        "artifacts",
        "degradation",
    ):
        assert section in dash_body and section in mcp_body
    d, m = dash_body, mcp_body
    assert d["recent_activity"]["message_count"] == m["recent_activity"]["message_count"] == 0
    assert d["artifacts"]["total"] == m["artifacts"]["total"] == 0
    assert d["session_health"]["total"] == m["session_health"]["total"] == 0
    assert d["graph_worklist"]["total_lanes"] == m["graph_worklist"]["total_lanes"] == 0
    assert d["degradation"]["error_count"] == m["degradation"]["error_count"] == 0
    assert d["graph_worklist"]["authoritative_graph_id"] is None
    assert m["graph_worklist"]["authoritative_graph_id"] is None


# ---------------------------------------------------------------------------


def test_dashboard_feature_graph_set_drilldown_rejects_other_conversation_scope(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    alpha = chat.create_conversation("Mission Alpha")
    beta = chat.create_conversation("Mission Beta")
    chat.add_message(
        alpha.id,
        "Human",
        "human",
        "Keep the alpha graph set scoped to this workspace.",
    )
    graph_dir = tmp_path / "lane_graphs"
    graph_dir.mkdir()
    _write_json(
        graph_dir / "graph-set-alpha.json",
        {
            "id": "graph-set-alpha",
            "feature_plan": {
                "id": "plan-alpha",
                "conversation_id": alpha.id,
                "resolution_id": "res-alpha",
                "version": 1,
                "features": [
                    {
                        "feature_id": "shared-feature",
                        "title": "Shared Feature",
                        "goal": "Stay in alpha only.",
                        "acceptance_criteria": ["No beta leakage."],
                        "graph_id": "graph-alpha",
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-alpha",
                    "conversation_id": alpha.id,
                    "resolution_id": "res-alpha",
                    "version": 1,
                    "lanes": [{"feature_id": "shared-feature"}],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "shared-feature",
                    "conversation_id": alpha.id,
                    "graph_id": "graph-alpha",
                    "status": "pending",
                }
            ]
        },
    )

    client = TestClient(create_app(tmp_path))
    alpha_timeline = client.get(f"/api/dashboard/peer-chat/conversations/{alpha.id}")
    beta_timeline = client.get(f"/api/dashboard/peer-chat/conversations/{beta.id}")
    alpha_detail = client.get(
        f"/api/dashboard/peer-chat/conversations/{alpha.id}/feature-graph-sets/graph-set-alpha"
    )
    beta_detail = client.get(
        f"/api/dashboard/peer-chat/conversations/{beta.id}/feature-graph-sets/graph-set-alpha"
    )

    assert alpha_timeline.status_code == 200
    assert any(
        card["card_type"] == "feature_graph_set" and card["source_id"] == "graph-set-alpha"
        for card in alpha_timeline.json()["cards"]
    )
    assert beta_timeline.status_code == 200
    assert all(card["source_id"] != "graph-set-alpha" for card in beta_timeline.json()["cards"])
    assert alpha_detail.status_code == 200
    assert alpha_detail.json()["graph_set"]["conversation_id"] == alpha.id
    assert beta_detail.status_code == 404
