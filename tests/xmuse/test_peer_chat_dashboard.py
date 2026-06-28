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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        }
    ]
    assert "recall body" not in json.dumps(supporting_context)
    assert payload["closure_evidence"]["total"] == 1
    assert payload["closure_evidence"]["items"][0]["proposal_id"] == proposal.id


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
