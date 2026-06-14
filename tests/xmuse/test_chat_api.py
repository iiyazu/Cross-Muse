import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.chat.god_room_speaker_response import GodRoomProviderSpeechResponseV1
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore
from xmuse_core.providers.god_identity_binding import (
    GodIdentityBindingStore,
    build_operator_selected_god_binding,
)
from xmuse_core.structuring.blueprint_execution.approval_events import (
    build_blueprint_approval_dedupe_key,
)
from xmuse_core.structuring.feature_plan_store import FeaturePlanStore
from xmuse_core.structuring.models import (
    ApprovedMissionBlueprint,
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    FeaturePlanProposal,
    FeaturePlanProposalApproval,
    FeaturePlanProposalStatus,
    LaneGraph,
    LaneNode,
)
from xmuse_core.structuring.planning_event_store import PlanningEventStore

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "chat_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("xmuse_chat_api", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


chat_api = _load_module()
create_app = chat_api.create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(base_dir=tmp_path))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_room_selected_god_binding(
    tmp_path: Path,
    *,
    room_id: str,
    participant: dict[str, object],
    selected_by: str = "operator",
) -> str:
    account, profile, binding = build_operator_selected_god_binding(
        room_id=room_id,
        participant_id=str(participant["participant_id"]),
        god_id=str(participant["god_id"]),
        account_ref="codex.god",
        cli_command="codex",
        model="gpt-5.4",
        selected_by=selected_by,
        selected_at="2026-06-14T00:00:00Z",
        role=str(participant.get("role") or "god"),
        capabilities=("peer_god", "review"),
    )
    GodIdentityBindingStore(tmp_path / "god_identity_bindings.json").upsert_selection(
        provider_account=account,
        god_profile=profile,
        room_binding=binding,
    )
    return binding.binding_ref


def _manual_god_cli_registration_payload() -> dict[str, object]:
    return {
        "cli_id": "custom.peer",
        "display_name": "Custom Peer",
        "command_family": "custom-cli",
        "provider_profile_ref": "custom.peer",
        "capabilities": ["peer_god"],
        "supports_persistent_sessions": True,
        "supports_mcp_writeback": True,
        "state_write_allowed": True,
        "proof_level": "real_provider_proof",
        "proof_refs": ["provider-run://custom.peer/live-smoke-1"],
    }


def _deliberation(
    conversation_id: str,
    *,
    msg_id: str,
    kind: str,
    payload: dict[str, object],
    target_ref: str,
    parent_id: str | None = None,
    objection_level: str = "none",
    agent_id: str = "god-architect",
) -> dict[str, object]:
    return {
        "msg_id": msg_id,
        "agent_id": agent_id,
        "lamport_ts": 1,
        "kind": kind,
        "parent_id": parent_id,
        "target_ref": target_ref,
        "mentions": [],
        "payload": payload,
        "objection_level": objection_level,
        "decision_scope": "blueprint.freeze",
        "conversation_id": conversation_id,
    }


def _seed_execution_card_drilldown_state(tmp_path: Path, conversation_id: str) -> None:
    source_blueprint = ApprovedMissionBlueprint(
        resolution_id="res-001",
        conversation_id=conversation_id,
        version=1,
        title="Blueprint Alpha",
        body="Turn the approved blueprint into execution cards.",
        acceptance_criteria=["Execution cards stay compact."],
        references=["docs/spec.md"],
        blueprint_ref="resolution:res-001:mission_blueprint:v1",
    )
    feature = FeaturePlanFeature(
        feature_id="feature-alpha",
        title="Feature Alpha",
        goal="Expose drilldown-ready read models.",
        acceptance_criteria=["Backend drilldowns resolve."],
        graph_id="graph-alpha",
        blueprint_refs=[source_blueprint.blueprint_ref],
    )
    FeaturePlanStore(tmp_path / "feature_plans").save(
        FeaturePlanProposal(
            id="feature-plan-001",
            conversation_id=conversation_id,
            source_blueprint=source_blueprint,
            features=[feature],
            status=FeaturePlanProposalStatus.APPROVED,
            approval=FeaturePlanProposalApproval(
                approved_by=["outer-god"],
                approval_mode="auto",
                approved_at="2026-05-31T12:00:00Z",
            ),
        )
    )
    graph_set = FeatureGraphSet(
        id="graph-set-001",
        feature_plan=FeaturePlan(
            id="feature-plan-001",
            conversation_id=conversation_id,
            resolution_id="res-001",
            version=1,
            features=[feature],
        ),
        graphs=[
            LaneGraph(
                id="graph-alpha",
                conversation_id=conversation_id,
                resolution_id="res-001",
                version=1,
                lanes=[
                    LaneNode(
                        feature_id="lane-001",
                        prompt="Keep takeover evidence compact.",
                        capabilities=["code", "test"],
                    )
                ],
            )
        ],
    )
    (tmp_path / "lane_graphs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "lane_graphs" / "graph-set-001.json").write_text(
        json.dumps(graph_set.model_dump(mode="json")),
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "read_models" / "planning_runs.json",
        {
            "planning_runs": [
                {
                    "planning_run_id": "plan-run-001",
                    "conversation_id": conversation_id,
                    "blueprint_ref": "resolution:res-001:mission_blueprint:v1",
                    "status": "running",
                    "feature_plan_id": "feature-plan-001",
                    "graph_set_id": "graph-set-001",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-001",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-alpha",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "feature-alpha",
                    "status": "exec_failed",
                    "prompt": "Keep takeover evidence compact.",
                    "acceptance_criteria": ["Takeover evidence is linkable."],
                    "blueprint_refs": ["resolution:res-001:mission_blueprint:v1"],
                    "review_summary": "Review flagged missing execution evidence.",
                    "review_decision": "rework",
                    "review_history": [
                        {
                            "decision": "rework",
                            "summary": "Prior review requested more evidence.",
                        }
                    ],
                    "retry_count": 2,
                    "review_retry_count": 1,
                    "failure_reason": "execution_infra_unavailable",
                    "branch": "lane-001-branch",
                    "worktree": "/tmp/lane-001",
                    "diff_ref": "logs/diffs/lane-001.patch",
                    "review_evidence_refs": ["logs/gates/lane-001/report.json"],
                }
            ]
        },
    )
    gate_dir = tmp_path / "logs" / "gates" / "lane-001"
    gate_dir.mkdir(parents=True, exist_ok=True)
    (gate_dir / "report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")


def test_chat_conversation_message_flow_uses_sqlite_store(tmp_path: Path) -> None:
    client = _client(tmp_path)

    create_response = client.post("/api/chat/conversations", json={"title": "xmuse MVP"})

    assert create_response.status_code == 201
    conversation = create_response.json()
    assert conversation["title"] == "xmuse MVP"
    assert (tmp_path / "chat.db").exists()

    message_response = client.post(
        f"/api/chat/conversations/{conversation['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Need the first chat-plane backend slice.",
        },
    )

    assert message_response.status_code == 201
    list_response = client.get(f"/api/chat/conversations/{conversation['id']}/messages")

    assert list_response.status_code == 200
    assert [item["content"] for item in list_response.json()["messages"]] == [
        "Need the first chat-plane backend slice."
    ]

    conversations_response = client.get("/api/chat/conversations")
    assert conversations_response.status_code == 200
    assert conversations_response.json()["conversations"][0]["id"] == conversation["id"]


def test_chat_api_operator_action_selects_god_cli_and_persists_selection(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Mission"}).json()

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "select_god_cli",
        },
        json={
            "action": "select_god_cli",
            "idempotency_key": "idem-chat-1",
            "payload": {
                "conversation_id": conversation["id"],
                "cli_id": "codex.god",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["payload"]["selection"]["durable_state_ref"] == (
        f"god_cli_selection:{conversation['id']}"
    )
    selection_response = client.get(
        f"/api/chat/operator/god-cli-selections/{conversation['id']}"
    )
    assert selection_response.status_code == 200
    selection = selection_response.json()["selection"]
    assert selection["cli_id"] == "codex.god"
    assert selection["selected_by"] == "operator-1"
    assert selection["audit_id"] == payload["audit_id"]


def test_chat_api_operator_action_selects_room_bound_god_identity(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Mission"}).json()
    room = client.post(f"/api/chat/conversations/{conversation['id']}/god-room").json()[
        "room"
    ]
    review = next(
        participant for participant in room["participants"]
        if participant["role"] == "review"
    )

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "select_god_cli",
        },
        json={
            "action": "select_god_cli",
            "idempotency_key": "idem-chat-room-binding-1",
            "payload": {
                "conversation_id": conversation["id"],
                "cli_id": "codex.god",
                "room_id": room["room_id"],
                "participant_id": review["participant_id"],
                "god_id": review["god_id"],
                "model": "gpt-5.4",
                "role": "review",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    binding = payload["payload"]["selection"]["room_selected_god_binding"]
    assert binding["durable_state_ref"].startswith(
        f"room_selected_god_binding:{room['room_id']}:{review['participant_id']}:"
    )
    resolution = binding["resolution"]
    assert resolution["status"] == "resolved"
    assert resolution["account_ref"] == "codex.god"
    assert resolution["god_id"] == review["god_id"]
    assert (tmp_path / "god_identity_bindings.json").exists()


def test_chat_api_operator_action_partial_room_binding_fails_without_side_effect(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Mission"}).json()

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "select_god_cli",
        },
        json={
            "action": "select_god_cli",
            "idempotency_key": "idem-chat-room-binding-partial",
            "payload": {
                "conversation_id": conversation["id"],
                "cli_id": "codex.god",
                "room_id": f"god-room:{conversation['id']}",
                "model": "gpt-5.4",
            },
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["status"] == "blocked"
    assert detail["proof_level"] == "manual_gap"
    assert detail["payload"]["missing_binding_fields"] == ["participant_id", "god_id"]
    assert not (tmp_path / "god_cli_selections.json").exists()
    assert not (tmp_path / "god_identity_bindings.json").exists()


def test_chat_api_god_room_persists_events_and_replays_turns(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room runtime"},
    ).json()
    conv_id = conversation["id"]

    room_response = client.post(f"/api/chat/conversations/{conv_id}/god-room")

    assert room_response.status_code == 201
    room = room_response.json()["room"]
    assert room["conversation_id"] == conv_id
    assert room["source_authority"] == "god_room_event_store"
    assert [participant["role"] for participant in room["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert [participant["god_id"] for participant in room["participants"]] == [
        "architect-god",
        "review-god",
        "execute-god",
    ]
    assert room["events"] == []
    assert room["replay"]["status"] == "ok"

    participants = {participant["role"]: participant for participant in room["participants"]}
    event = {
        "event_id": "evt-propose",
        "room_id": room["room_id"],
        "conversation_id": conv_id,
        "participant_id": participants["architect"]["participant_id"],
        "god_id": participants["architect"]["god_id"],
        "actor_kind": "god",
        "event_type": "speak",
        "timestamp_utc": "2026-06-13T10:00:00Z",
        "content": "I propose routing GOD room events through the Chat API.",
        "source_refs": [f"conversation:{conv_id}"],
        "cli_id": participants["architect"]["cli_id"],
        "provider_profile": "codex",
        "payload": {"body": "I propose routing GOD room events through the Chat API."},
    }

    append_response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json=event,
    )
    duplicate_response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json=event,
    )
    read_response = client.get(f"/api/chat/conversations/{conv_id}/god-room")
    snapshot_response = client.get(
        f"/api/chat/conversations/{conv_id}/god-room/snapshot"
    )

    assert append_response.status_code == 201
    assert append_response.json()["append_status"] == "created"
    assert append_response.json()["room"]["replay"]["decisions"][0] == {
        "event_id": "evt-propose",
        "next_participant_id": participants["review"]["participant_id"],
        "reason": "round_robin",
        "source_refs": ["god-room-event:evt-propose", f"conversation:{conv_id}"],
    }
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["append_status"] == "duplicate"
    assert read_response.status_code == 200
    assert [event["event_id"] for event in read_response.json()["room"]["events"]] == [
        "evt-propose"
    ]
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()["snapshot"]
    assert snapshot["schema_version"] == "xmuse.god_room_snapshot.v1"
    assert snapshot["source_authority"] == "god_room_event_store"
    assert snapshot["events"][0]["event_id"] == "evt-propose"


def test_chat_api_god_room_public_append_rejects_provider_proof_spoof(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room provider proof spoof"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-fake-provider-speak",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "This raw request body is pretending to be provider speech.",
            "source_refs": [
                f"conversation:{conv_id}",
                "provider_response_artifact:reports/provider-responses/fake.json",
            ],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {
                "body": "This raw request body is pretending to be provider speech.",
                "proof_level": "real_provider_proof",
                "provider_response_artifact_ref": (
                    "reports/provider-responses/fake.json"
                ),
                "binding_revision": "binding:spoof",
            },
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "god_room_event_public_append_provider_proof_forbidden"
    assert detail["proof_level"] == "manual_gap"
    assert detail["blocked_reason"] == "provider_backed_speak_requires_l4_l5_capture"
    assert detail["forbidden_refs"] == [
        "provider_response_artifact:reports/provider-responses/fake.json"
    ]
    assert detail["forbidden_payload_keys"] == [
        "binding_revision",
        "proof_level",
        "provider_response_artifact_ref",
    ]

    events = client.get(f"/api/chat/conversations/{conv_id}/god-room").json()["room"][
        "events"
    ]
    assert events == []


def test_chat_api_god_room_speaker_attempt_uses_selected_provider_bound_god(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room speaker attempt"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conv_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="audit-select-speaker",
        idempotency_key="select-speaker",
    )
    binding_ref = _seed_room_selected_god_binding(
        tmp_path,
        room_id=room["room_id"],
        participant=participants["review"],
    )
    session_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = session_registry.find_by_conversation_participant(
        conv_id,
        participants["review"]["participant_id"],
    )
    session_registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="provider-thread-review",
        provider_session_kind="provider_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    event = {
        "event_id": "evt-propose",
        "room_id": room["room_id"],
        "conversation_id": conv_id,
        "participant_id": participants["architect"]["participant_id"],
        "god_id": participants["architect"]["god_id"],
        "actor_kind": "god",
        "event_type": "speak",
        "timestamp_utc": "2026-06-13T10:00:00Z",
        "content": "I propose routing speaker attempts through selected GOD runtime.",
        "source_refs": [f"conversation:{conv_id}"],
        "cli_id": participants["architect"]["cli_id"],
        "provider_profile": "codex.god",
        "payload": {"body": "I propose routing speaker attempts."},
    }
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json=event,
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/speaker-attempt",
        json={"after_event_id": "evt-propose"},
    )

    assert response.status_code == 201
    payload = response.json()
    attempt = payload["speaker_attempt"]
    assert attempt["status"] == "ready_for_provider_attempt"
    assert attempt["proof_level"] == "contract_proof"
    assert attempt["selected_event_id"] == "evt-propose"
    assert attempt["target_participant_id"] == participants["review"]["participant_id"]
    assert attempt["target_god_id"] == participants["review"]["god_id"]
    assert attempt["account_ref"] == "codex.god"
    assert attempt["binding_revision"] == (
        f"binding:god-room:{conv_id}:{participants['review']['participant_id']}:1"
    )
    assert attempt["provider_profile_ref"] == "codex.god"
    assert attempt["provider_session_id"] == "provider-thread-review"
    assert binding_ref in attempt["source_refs"]
    assert payload["artifacts"]["speaker_attempt"].startswith(
        "reports/god_room_speaker_attempts/"
    )
    assert (
        len(
            client.get(f"/api/chat/conversations/{conv_id}/god-room")
            .json()["room"]["events"]
        )
        == 1
    )


def test_chat_api_god_room_speaker_attempt_reports_manual_gap_without_selection(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room speaker gap"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "I propose asking the review GOD to speak next.",
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {"body": "I propose asking the review GOD to speak next."},
        },
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/speaker-attempt",
        json={"after_event_id": "evt-propose"},
    )

    assert response.status_code == 201
    attempt = response.json()["speaker_attempt"]
    assert attempt["status"] == "manual_gap"
    assert attempt["proof_level"] == "manual_gap"
    assert attempt["target_participant_id"] == participants["review"]["participant_id"]
    assert attempt["blocked_reason"] == "room selected GOD binding unavailable"


def test_chat_api_god_room_speaker_response_appends_provider_speech(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room speaker response"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conv_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="audit-select-speaker-response",
        idempotency_key="select-speaker-response",
    )
    binding_ref = _seed_room_selected_god_binding(
        tmp_path,
        room_id=room["room_id"],
        participant=participants["review"],
    )
    session_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = session_registry.find_by_conversation_participant(
        conv_id,
        participants["review"]["participant_id"],
    )
    session_registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="provider-thread-review",
        provider_session_kind="provider_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "I propose asking the review GOD for a provider response.",
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {"body": "I propose asking the review GOD."},
        },
    )
    provider_response = {
        "response_id": "provider-response-1",
        "status": "completed",
        "proof_level": "real_provider_proof",
        "target_participant_id": participants["review"]["participant_id"],
        "provider_profile_ref": "codex.god",
        "provider_session_id": "provider-thread-review",
        "provider_session_kind": "provider_thread",
        "content": "I can review this path because my provider session responded.",
        "source_refs": ["provider-run:codex:provider-response-1"],
    }
    _write_json(
        tmp_path / "reports" / "provider-responses" / "provider-response-1.json",
        provider_response,
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/speaker-response",
        json={
            "after_event_id": "evt-propose",
            "event_id": "evt-review-provider-speak",
            "timestamp_utc": "2026-06-13T10:02:00Z",
            "provider_response_artifact": (
                "reports/provider-responses/provider-response-1.json"
            ),
            "provider_response": provider_response,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    capture = payload["speaker_response"]
    assert capture["status"] == "speak_event_appended"
    assert capture["proof_level"] == "real_provider_proof"
    assert capture["append_status"] == "created"
    assert capture["speak_event"]["event_id"] == "evt-review-provider-speak"
    assert capture["speak_event"]["participant_id"] == (
        participants["review"]["participant_id"]
    )
    assert capture["account_ref"] == "codex.god"
    assert capture["binding_revision"] is not None
    assert binding_ref in capture["source_refs"]
    assert payload["artifacts"]["speaker_response"].startswith(
        "reports/god_room_speaker_responses/"
    )
    read_response = client.get(f"/api/chat/conversations/{conv_id}/god-room")
    events = read_response.json()["room"]["events"]
    assert [event["event_id"] for event in events] == [
        "evt-propose",
        "evt-review-provider-speak",
    ]
    assert events[1]["causal_parent_id"] == "evt-propose"
    assert events[1]["payload"]["provider_response_id"] == "provider-response-1"
    assert events[1]["payload"]["account_ref"] == "codex.god"
    assert events[1]["payload"]["binding_revision"] == capture["binding_revision"]
    assert (
        events[1]["payload"]["provider_response_artifact_ref"]
        == "reports/provider-responses/provider-response-1.json"
    )


def test_chat_api_god_room_speaker_response_manual_gap_does_not_append_event(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room speaker response gap"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conv_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="audit-select-speaker-response-gap",
        idempotency_key="select-speaker-response-gap",
    )
    _seed_room_selected_god_binding(
        tmp_path,
        room_id=room["room_id"],
        participant=participants["review"],
    )
    session_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = session_registry.find_by_conversation_participant(
        conv_id,
        participants["review"]["participant_id"],
    )
    session_registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="provider-thread-review",
        provider_session_kind="provider_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "I propose asking the review GOD for a provider response.",
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {"body": "I propose asking the review GOD."},
        },
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/speaker-response",
        json={
            "after_event_id": "evt-propose",
            "event_id": "evt-review-provider-speak",
            "timestamp_utc": "2026-06-13T10:02:00Z",
            "provider_response": {
                "response_id": "provider-response-1",
                "status": "completed",
                "proof_level": "real_provider_proof",
                "target_participant_id": participants["review"]["participant_id"],
                "provider_profile_ref": "codex.god",
                "provider_session_id": "provider-thread-review",
                "provider_session_kind": "provider_thread",
                "content": "This response claims real proof but has no artifact authority.",
                "source_refs": ["provider-run:codex:provider-response-1"],
            },
        },
    )

    assert response.status_code == 201
    capture = response.json()["speaker_response"]
    assert capture["status"] == "manual_gap"
    assert capture["proof_level"] == "manual_gap"
    assert capture["blocked_reason"] == "provider response artifact missing"
    events = client.get(f"/api/chat/conversations/{conv_id}/god-room").json()["room"][
        "events"
    ]
    assert [event["event_id"] for event in events] == ["evt-propose"]


def test_chat_api_god_room_provider_invocation_writes_fail_closed_artifact(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room provider invocation gap"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conv_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="audit-select-provider-invocation-gap",
        idempotency_key="select-provider-invocation-gap",
    )
    account, profile, binding = build_operator_selected_god_binding(
        room_id=room["room_id"],
        participant_id=str(participants["review"]["participant_id"]),
        god_id=str(participants["review"]["god_id"]),
        account_ref="unsupported.god",
        cli_command="unsupported-cli",
        model="unsupported-model",
        selected_by="operator",
        selected_at="2026-06-14T00:00:00Z",
        role=str(participants["review"].get("role") or "god"),
        capabilities=("peer_god", "review"),
    )
    GodIdentityBindingStore(tmp_path / "god_identity_bindings.json").upsert_selection(
        provider_account=account,
        god_profile=profile,
        room_binding=binding,
    )
    session_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = session_registry.find_by_conversation_participant(
        conv_id,
        participants["review"]["participant_id"],
    )
    session_registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="provider-thread-review",
        provider_session_kind="provider_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "I propose asking the review GOD for a provider response.",
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {"body": "I propose asking the review GOD."},
        },
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/provider-invocation",
        json={
            "after_event_id": "evt-propose",
            "prompt": "Return structured GOD speech.",
            "timeout_seconds": 1,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    provider_response = payload["provider_response"]
    assert provider_response["schema_version"] == (
        "xmuse.god_room_provider_speech_response.v1"
    )
    assert provider_response["status"] == "blocked"
    assert provider_response["proof_level"] == "manual_gap"
    assert provider_response["blocked_reason"] == (
        "unsupported provider CLI for GOD room speech: unsupported-cli"
    )
    assert provider_response["binding_revision"] == binding.binding_revision
    assert provider_response["account_ref"] == "unsupported.god"
    artifact_ref = payload["artifacts"]["provider_response"]
    assert artifact_ref.startswith("reports/provider-responses/")
    assert (tmp_path / artifact_ref).exists()
    events = client.get(f"/api/chat/conversations/{conv_id}/god-room").json()["room"][
        "events"
    ]
    assert [event["event_id"] for event in events] == ["evt-propose"]


def test_chat_api_god_room_provider_invocation_capture_preserves_manual_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    execution_worktree = tmp_path / "trusted-worktree"
    execution_worktree.mkdir()

    def fake_contract_provider_invocation(**kwargs):
        attempt = kwargs["attempt"]
        assert attempt.status == "ready_for_provider_attempt"
        assert kwargs["workspace"] == execution_worktree
        return GodRoomProviderSpeechResponseV1(
            response_id="provider-response-contract-only",
            status="completed",
            proof_level="contract_proof",
            target_participant_id=attempt.target_participant_id,
            provider_profile_ref=attempt.provider_profile_ref,
            provider_session_id=attempt.provider_session_id,
            provider_session_kind=attempt.provider_session_kind,
            content="This completed provider artifact is still contract proof only.",
            source_refs=[
                "provider_invocation:contract-only",
                "provider_raw_output_sha256:contract",
            ],
            conversation_id=attempt.conversation_id,
            room_id=attempt.room_id,
            target_god_id=attempt.target_god_id,
            binding_revision=attempt.binding_revision,
            account_ref=attempt.account_ref,
            cli_command=attempt.cli_command,
            model=attempt.model,
            variant=attempt.variant,
            invocation_id="provider-invocation-contract-only",
            invocation_status="completed",
            prompt_refs=["prompt:contract-only"],
            output_refs=["provider_raw_output_sha256:contract"],
            raw_output_digest="contract",
            completed_at_utc="2026-06-13T10:01:00Z",
            started_at_utc="2026-06-13T10:00:59Z",
            duration_ms=1,
            exit_code=0,
        )

    monkeypatch.setattr(
        chat_api,
        "invoke_god_room_provider_speech",
        fake_contract_provider_invocation,
    )
    client = TestClient(
        create_app(base_dir=tmp_path, execution_worktree=execution_worktree)
    )
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room provider invocation capture gap"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conv_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="audit-select-provider-invocation-capture-gap",
        idempotency_key="select-provider-invocation-capture-gap",
    )
    _seed_room_selected_god_binding(
        tmp_path,
        room_id=room["room_id"],
        participant=participants["review"],
    )
    session_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = session_registry.find_by_conversation_participant(
        conv_id,
        participants["review"]["participant_id"],
    )
    session_registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="provider-thread-review",
        provider_session_kind="provider_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "I propose asking the review GOD for a provider response.",
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {"body": "I propose asking the review GOD."},
        },
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/provider-invocation-capture",
        json={
            "after_event_id": "evt-propose",
            "event_id": "evt-review-provider-speak",
            "timestamp_utc": "2026-06-13T10:02:00Z",
            "prompt": "Return structured GOD speech.",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    provider_response = payload["provider_response"]
    capture = payload["speaker_response"]
    assert provider_response["status"] == "completed"
    assert provider_response["proof_level"] == "contract_proof"
    assert capture["status"] == "manual_gap"
    assert capture["proof_level"] == "manual_gap"
    assert capture["blocked_reason"] == "provider response proof level is contract_proof"
    assert payload["artifacts"]["provider_response"].startswith(
        "reports/provider-responses/"
    )
    assert payload["artifacts"]["speaker_response"].startswith(
        "reports/god_room_speaker_responses/"
    )
    events = payload["room"]["events"]
    assert [event["event_id"] for event in events] == ["evt-propose"]


def test_chat_api_god_room_provider_invocation_capture_appends_server_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_provider_invocation(**kwargs):
        attempt = kwargs["attempt"]
        assert attempt.status == "ready_for_provider_attempt"
        assert attempt.account_ref == "codex.god"
        return GodRoomProviderSpeechResponseV1(
            response_id="provider-response-from-server-producer",
            status="completed",
            proof_level="real_provider_proof",
            target_participant_id=attempt.target_participant_id,
            provider_profile_ref=attempt.provider_profile_ref,
            provider_session_id="provider-thread-fresh-live",
            provider_session_kind=attempt.provider_session_kind,
            content="I can now be captured from the server-written L4 artifact.",
            source_refs=[
                "provider_invocation:server-produced",
                "provider_raw_output_sha256:test",
            ],
            conversation_id=attempt.conversation_id,
            room_id=attempt.room_id,
            target_god_id=attempt.target_god_id,
            binding_revision=attempt.binding_revision,
            account_ref=attempt.account_ref,
            cli_command=attempt.cli_command,
            model=attempt.model,
            variant=attempt.variant,
            invocation_id="provider-invocation-server-produced",
            invocation_status="completed",
            prompt_refs=["prompt:server-produced"],
            output_refs=["provider_raw_output_sha256:test"],
            raw_output_digest="test",
            completed_at_utc="2026-06-13T10:01:00Z",
            started_at_utc="2026-06-13T10:00:59Z",
            duration_ms=1,
            exit_code=0,
        )

    monkeypatch.setattr(
        chat_api,
        "invoke_god_room_provider_speech",
        fake_provider_invocation,
    )
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room provider invocation capture success"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conv_id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="audit-select-provider-invocation-capture",
        idempotency_key="select-provider-invocation-capture",
    )
    binding_ref = _seed_room_selected_god_binding(
        tmp_path,
        room_id=room["room_id"],
        participant=participants["review"],
    )
    session_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = session_registry.find_by_conversation_participant(
        conv_id,
        participants["review"]["participant_id"],
    )
    session_registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="provider-thread-review",
        provider_session_kind="provider_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "I propose asking the review GOD for a provider response.",
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex.god",
            "payload": {"body": "I propose asking the review GOD."},
        },
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/provider-invocation-capture",
        json={
            "after_event_id": "evt-propose",
            "event_id": "evt-review-provider-speak",
            "timestamp_utc": "2026-06-13T10:02:00Z",
            "prompt": "Return structured GOD speech.",
            "allow_live_provider_proof": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    provider_artifact_ref = payload["artifacts"]["provider_response"]
    capture = payload["speaker_response"]
    assert provider_artifact_ref.startswith("reports/provider-responses/")
    assert (tmp_path / provider_artifact_ref).exists()
    assert capture["status"] == "speak_event_appended"
    assert capture["proof_level"] == "real_provider_proof"
    assert capture["provider_session_id"] == "provider-thread-fresh-live"
    assert "provider_session:provider-thread-fresh-live" in capture["source_refs"]
    assert capture["provider_response_artifact_ref"] == provider_artifact_ref
    assert binding_ref in capture["source_refs"]
    events = payload["room"]["events"]
    assert [event["event_id"] for event in events] == [
        "evt-propose",
        "evt-review-provider-speak",
    ]
    assert events[1]["payload"]["provider_response_artifact_ref"] == provider_artifact_ref
    assert events[1]["payload"]["binding_revision"] == capture["binding_revision"]
    assert payload["room"]["replay"]["status"] == "ok"


def test_chat_api_god_room_rejects_unknown_target_without_writing(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room target guard"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    architect = next(
        participant for participant in room["participants"]
        if participant["role"] == "architect"
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/events",
        json={
            "event_id": "evt-question",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": architect["participant_id"],
            "god_id": architect["god_id"],
            "actor_kind": "god",
            "event_type": "question",
            "timestamp_utc": "2026-06-13T10:01:00Z",
            "content": "Can the missing GOD answer this?",
            "target_participant_ids": ["part-missing"],
            "source_refs": [f"conversation:{conv_id}"],
            "cli_id": architect["cli_id"],
            "provider_profile": "codex",
            "payload": {"body": "Can the missing GOD answer this?"},
        },
    )
    read_response = client.get(f"/api/chat/conversations/{conv_id}/god-room")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "god_room_membership_error"
    assert "target participant part-missing" in response.json()["detail"]["message"]
    assert read_response.status_code == 200
    assert read_response.json()["room"]["events"] == []


def test_chat_api_god_room_freeze_blueprint_persists_resolution_from_room_events(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room blueprint freeze"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}

    for event in [
        {
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "Build the GOD room runtime from durable events.",
            "source_refs": [f"conversation:{conv_id}", "message:evt-propose"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "goal": "Build the GOD room runtime from durable events.",
                "scope": ["GOD room runtime action", "Blueprint freeze artifact"],
                "acceptance_contracts": [
                    "Durable GOD room snapshot compiles to frozen blueprint."
                ],
                "assumptions": ["Provider responses may be unavailable in CI."],
                "rejected_alternatives": [
                    "Let the TUI mutate blueprint state directly."
                ],
            },
        },
        {
            "event_id": "evt-freeze",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["review"]["participant_id"],
            "god_id": participants["review"]["god_id"],
            "actor_kind": "god",
            "event_type": "freeze_requested",
            "timestamp_utc": "2026-06-13T10:03:00Z",
            "content": "Freeze this GOD room blueprint.",
            "source_refs": [f"conversation:{conv_id}", "message:evt-freeze"],
            "causal_parent_id": "evt-propose",
            "cli_id": participants["review"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "freeze_target_ref": "blueprint:bp-god-room:1",
                "goal": "Build the GOD room runtime from durable events.",
                "scope": ["GOD room runtime action", "Blueprint freeze artifact"],
                "constraints": ["Use durable GOD room snapshot authority."],
                "non_goals": ["Do not claim pr_merged."],
                "acceptance_contracts": [
                    "Durable GOD room snapshot compiles to frozen blueprint."
                ],
                "repo_areas": ["xmuse/chat_api.py", "src/xmuse_core/chat"],
            },
        },
    ]:
        assert client.post(
            f"/api/chat/conversations/{conv_id}/god-room/events",
            json=event,
        ).status_code in {200, 201}

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/freeze-blueprint",
        json={"blueprint_id": "bp-god-room", "revision": 1},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == "god_room_event_store"
    assert payload["artifact"]["version"] == "xmuse.god_room_blueprint_freeze.v1"
    assert payload["artifact"]["status"] == "frozen"
    assert payload["artifact"]["proof_level"] == "contract_proof"
    assert payload["artifact"]["decision_event_id"] == "evt-freeze"
    assert payload["blueprint"]["blueprint_id"] == "bp-god-room"
    assert payload["blueprint"]["status"] == "frozen"
    assert payload["blueprint"]["approved_by"] == [participants["review"]["god_id"]]
    assert payload["resolution"]["approval_mode"] == "god_room_blueprint_freeze"

    stored = ChatStore(tmp_path / "chat.db").get_resolution(payload["resolution"]["id"])
    assert stored.content["blueprint_v1"]["source_refs"] == payload["blueprint"]["source_refs"]
    assert stored.content["god_room_blueprint_freeze"]["decision_event_id"] == "evt-freeze"

    timeline = client.get(f"/api/chat/conversations/{conv_id}/messages").json()
    card = next(card for card in timeline["cards"] if card["card_type"] == "mission_blueprint")
    assert card["source_id"] == payload["resolution"]["id"]

    read_model = json.loads((tmp_path / "read_models" / "resolutions.json").read_text())
    assert read_model["resolutions"][-1]["resolution_id"] == payload["resolution"]["id"]


def test_chat_api_god_room_freeze_blueprint_blocks_unresolved_challenge(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room blocked freeze"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}

    for event in [
        {
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "Freeze a risky blueprint.",
            "source_refs": [f"conversation:{conv_id}", "message:evt-propose"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "goal": "Freeze a risky blueprint.",
                "scope": ["GOD room runtime action"],
                "acceptance_contracts": ["All challenges are resolved."],
            },
        },
        {
            "event_id": "evt-challenge",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["review"]["participant_id"],
            "god_id": participants["review"]["god_id"],
            "actor_kind": "god",
            "event_type": "challenge",
            "timestamp_utc": "2026-06-13T10:01:00Z",
            "content": "The freeze lacks evidence.",
            "target_participant_ids": [participants["architect"]["participant_id"]],
            "source_refs": [f"conversation:{conv_id}", "message:evt-challenge"],
            "causal_parent_id": "evt-propose",
            "cli_id": participants["review"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "conflict": "The freeze lacks evidence.",
                "resolved": False,
            },
        },
        {
            "event_id": "evt-freeze",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["execute"]["participant_id"],
            "god_id": participants["execute"]["god_id"],
            "actor_kind": "god",
            "event_type": "freeze_requested",
            "timestamp_utc": "2026-06-13T10:03:00Z",
            "content": "Freeze despite unresolved challenge.",
            "source_refs": [f"conversation:{conv_id}", "message:evt-freeze"],
            "causal_parent_id": "evt-propose",
            "cli_id": participants["execute"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "freeze_target_ref": "blueprint:bp-blocked:1",
                "goal": "Freeze a risky blueprint.",
                "scope": ["GOD room runtime action"],
                "acceptance_contracts": ["All challenges are resolved."],
            },
        },
    ]:
        assert client.post(
            f"/api/chat/conversations/{conv_id}/god-room/events",
            json=event,
        ).status_code in {200, 201}

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/freeze-blueprint",
        json={"blueprint_id": "bp-blocked", "revision": 1},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "god_room_blueprint_freeze_blocked"
    assert detail["artifact"]["status"] == "manual_gap"
    assert detail["artifact"]["blockers"] == ["unresolved challenge evt-challenge"]
    timeline = client.get(f"/api/chat/conversations/{conv_id}/messages").json()
    assert not any(card["card_type"] == "mission_blueprint" for card in timeline["cards"])


def test_chat_api_god_room_lane_dag_builds_from_freeze_resolution_without_projection_write(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "GOD room laneDAG"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    blueprint_ref = "blueprint:bp-god-room:1"

    for event in [
        {
            "event_id": "evt-propose",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "Build the laneDAG from frozen GOD room evidence.",
            "source_refs": [f"conversation:{conv_id}", "message:evt-propose"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "goal": "Build the laneDAG from frozen GOD room evidence.",
                "scope": ["GOD room laneDAG runtime action"],
                "acceptance_contracts": ["LaneDAG artifacts preserve runtime contracts."],
            },
        },
        {
            "event_id": "evt-freeze",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["review"]["participant_id"],
            "god_id": participants["review"]["god_id"],
            "actor_kind": "god",
            "event_type": "freeze_requested",
            "timestamp_utc": "2026-06-13T10:03:00Z",
            "content": "Freeze for laneDAG planning.",
            "source_refs": [f"conversation:{conv_id}", "message:evt-freeze"],
            "causal_parent_id": "evt-propose",
            "cli_id": participants["review"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "freeze_target_ref": blueprint_ref,
                "goal": "Build the laneDAG from frozen GOD room evidence.",
                "scope": ["GOD room laneDAG runtime action"],
                "acceptance_contracts": ["LaneDAG artifacts preserve runtime contracts."],
                "repo_areas": ["xmuse/chat_api.py", "src/xmuse_core/structuring"],
            },
        },
    ]:
        assert client.post(
            f"/api/chat/conversations/{conv_id}/god-room/events",
            json=event,
        ).status_code in {200, 201}
    freeze = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/freeze-blueprint",
        json={"blueprint_id": "bp-god-room", "revision": 1},
    ).json()

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag",
        json={
            "resolution_id": freeze["resolution"]["id"],
            "graph_id": "graph-bp-god-room",
            "graph_version": 1,
            "source_refs": ["god-room-freeze:evt-freeze"],
            "features": [
                {
                    "feature_id": "feature-runtime",
                    "title": "Runtime wiring",
                    "goal": "Wire GOD room freeze into laneDAG authority.",
                    "acceptance_criteria": ["Runtime contracts are persisted."],
                    "blueprint_refs": [blueprint_ref],
                    "memory_refs": [f"memory://conversation/{conv_id}/blueprint/bp-god-room"],
                }
            ],
            "lanes": [
                {
                    "lane_id": "lane-runtime-api",
                    "feature_id": "feature-runtime",
                    "title": "Expose laneDAG runtime API",
                    "prompt": "Build the laneDAG runtime action from the frozen blueprint.",
                    "acceptance_criteria": ["Focused tests cover laneDAG persistence."],
                    "blueprint_refs": [blueprint_ref],
                    "owner": "execute-god",
                    "inputs": [blueprint_ref],
                    "outputs": ["artifact://lane-runtime-api/lane-dag.json"],
                    "required_checks": ["focused-pytest", "ruff"],
                    "allowed_files": [
                        "xmuse/chat_api.py",
                        "src/xmuse_core/structuring/blueprint_execution",
                    ],
                    "rollback_constraints": ["preserve GOD room freeze resolution"],
                    "review_profile": "runtime-contract-review",
                    "budget": {
                        "max_attempts": 3,
                        "max_consecutive_same_failure": 2,
                        "max_runtime_seconds": 1800,
                        "retry_backoff_seconds": 30,
                        "source_refs": ["budget:lane-runtime-api"],
                    },
                }
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == "mission_blueprint_resolution"
    assert payload["resolution_id"] == freeze["resolution"]["id"]
    assert payload["lane_dag"]["blueprint_ref"] == blueprint_ref
    assert payload["lane_dag"]["blueprint_proof_level"] == "contract_proof"
    assert "god-room-event:evt-freeze" in payload["lane_dag"]["source_refs"]
    assert payload["lane_dag"]["lane_contracts"][0]["lane_id"] == "lane-runtime-api"
    assert payload["lane_dag"]["lane_contracts"][0]["owner"] == "execute-god"
    assert payload["lane_dag"]["lane_contracts"][0]["budget"]["max_runtime_seconds"] == 1800
    assert payload["artifacts"]["lane_graph"].endswith("graph-bp-god-room.json")
    assert payload["artifacts"]["lane_dag"].endswith("graph-bp-god-room.lane-dag.json")
    assert (tmp_path / payload["artifacts"]["lane_graph"]).exists()
    assert (tmp_path / payload["artifacts"]["lane_dag"]).exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_dag_rejects_non_god_room_freeze_resolution(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "Deliberation freeze only"},
    ).json()
    conv_id = conversation["id"]
    target_ref = "blueprint:bp-deliberation:1"
    for event in [
        _deliberation(
            conv_id,
            msg_id="msg-proposal",
            kind="proposal",
            target_ref=target_ref,
            payload={"summary": "Freeze through deliberation."},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-review",
            kind="challenge",
            target_ref=target_ref,
            parent_id="msg-proposal",
            objection_level="non_blocking",
            payload={"question": "Is this only a deliberation freeze?"},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-commit",
            kind="commit",
            target_ref=target_ref,
            agent_id="god-review",
            payload={"commitment": "ready_to_freeze"},
        ),
    ]:
        response = client.post(
            f"/api/chat/conversations/{conv_id}/deliberations",
            json=event,
        )
        assert response.status_code == 201
    freeze = client.post(
        f"/api/chat/conversations/{conv_id}/freeze-blueprint",
        json={
            "target_ref": target_ref,
            "blueprint": {
                "blueprint_id": "bp-deliberation",
                "revision": 1,
                "goal": "Freeze through deliberation.",
                "scope": ["Deliberation freeze"],
                "acceptance_contracts": ["Resolution exists."],
                "source_refs": ["message:msg-proposal"],
            },
        },
    )
    assert freeze.status_code == 201
    freeze_payload = freeze.json()

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag",
        json={
            "resolution_id": freeze_payload["resolution"]["id"],
            "graph_id": "graph-rejected",
            "features": [
                {
                    "feature_id": "feature-a",
                    "title": "Feature A",
                    "goal": "Should be rejected.",
                    "acceptance_criteria": ["No laneDAG is created."],
                    "blueprint_refs": [target_ref],
                }
            ],
            "lanes": [
                {
                    "lane_id": "lane-a",
                    "feature_id": "feature-a",
                    "title": "Lane A",
                    "prompt": "This should not run.",
                    "acceptance_criteria": ["No artifact is written."],
                    "blueprint_refs": [target_ref],
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "god_room_lane_dag_requires_god_room_freeze"
    assert not (tmp_path / "lane_graphs" / "graph-rejected.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_recovery_requires_refactor_from_lane_budget(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-recovery")

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": "graph-recovery",
            "lane_id": "lane-runtime-api",
            "failures": [
                {
                    "lane_id": "lane-runtime-api",
                    "attempt": 1,
                    "failure_class": "contract_boundary_leak",
                    "reason": "TUI attempted to mutate projection state.",
                    "source_refs": ["pytest:test_tui_authority"],
                },
                {
                    "lane_id": "lane-runtime-api",
                    "attempt": 2,
                    "failure_class": "contract_boundary_leak",
                    "reason": "Dashboard attempted to mutate projection state.",
                    "source_refs": ["pytest:test_dashboard_authority"],
                },
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == "lane_dag_artifact"
    assert payload["blueprint_proof_level"] == "contract_proof"
    assert "blueprint:bp-god-room:1" in payload["source_refs"]
    assert any(
        ref.startswith("god-room-event:evt-freeze")
        for ref in payload["source_refs"]
    )
    assert "budget:lane-runtime-api" in payload["source_refs"]
    assert payload["decision"]["decision"] == "refactor_required"
    assert payload["decision"]["retry_allowed"] is False
    assert payload["decision"]["failure_class"] == "contract_boundary_leak"
    assert payload["decision"]["refactor_required_reason"] == (
        "failure_class contract_boundary_leak repeated 2 times"
    )
    assert "budget:lane-runtime-api" in payload["decision"]["source_refs"]
    assert "pytest:test_tui_authority" in payload["decision"]["source_refs"]
    assert "pytest:test_dashboard_authority" in payload["decision"]["source_refs"]
    assert payload["artifacts"]["recovery"].endswith(
        "graph-recovery.lane-runtime-api.recovery.json"
    )
    recovery_artifact = tmp_path / payload["artifacts"]["recovery"]
    assert recovery_artifact.exists()
    artifact_payload = json.loads(recovery_artifact.read_text(encoding="utf-8"))
    assert artifact_payload["blueprint_proof_level"] == "contract_proof"
    assert artifact_payload["source_refs"] == payload["source_refs"]
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_recovery_records_manual_gap_without_failures(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-manual-gap")

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": "graph-manual-gap",
            "lane_id": "lane-runtime-api",
            "failures": [],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["decision"]["decision"] == "manual_gap"
    assert payload["decision"]["retry_allowed"] is False
    assert payload["decision"]["suspend_reason"] == "missing_failure_evidence"
    assert payload["artifacts"]["recovery"].endswith(
        "graph-manual-gap.lane-runtime-api.recovery.json"
    )
    assert (tmp_path / payload["artifacts"]["recovery"]).exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_review_intake_keeps_worker_output_candidate_only(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-review-intake")
    recovery = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": "graph-review-intake",
            "lane_id": "lane-runtime-api",
            "failures": [
                {
                    "lane_id": "lane-runtime-api",
                    "attempt": 1,
                    "failure_class": "missing_review_evidence",
                    "reason": "Worker result requires independent review.",
                    "source_refs": ["worker-candidate:run-1"],
                }
            ],
        },
    )
    assert recovery.status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-review-intake",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:run-1"],
            "execution_artifact_refs": ["artifacts/lane-runtime-api/result.json"],
            "reviewer_id": "review-god",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    intake = payload["review_intake"]
    assert payload["source_authority"] == "lane_dag_artifact+lane_recovery_artifact"
    assert intake["schema_version"] == "xmuse.god_room_lane_review_intake.v1"
    assert intake["proof_level"] == "contract_proof"
    assert intake["review_truth_status"] == "pending_independent_review"
    assert intake["candidate_truth_status"] == "candidate_only"
    assert intake["blueprint_proof_level"] == "contract_proof"
    assert intake["manual_gaps"] == []
    assert "worker_output_is_review_truth" in intake["forbidden_claims"]
    assert "end_to_end_execution_review_closure" in intake["forbidden_claims"]
    assert "review_worker_candidate_against_lane_contract" in intake[
        "required_review_checks"
    ]
    assert "verify_no_worker_self_report_as_truth" in intake["required_review_checks"]
    assert "worker-candidate:run-1" in intake["reviewer_input_refs"]
    assert "artifacts/lane-runtime-api/result.json" in intake["reviewer_input_refs"]
    assert intake["recovery_decision"]["decision"] == "retry"
    intake_artifact = tmp_path / payload["artifacts"]["review_intake"]
    assert intake_artifact.exists()
    artifact_payload = json.loads(intake_artifact.read_text(encoding="utf-8"))
    assert artifact_payload == intake
    assert not (tmp_path / "review_plane.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_review_intake_blocks_refactor_required_recovery(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-review-refactor-block")
    recovery = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": "graph-review-refactor-block",
            "lane_id": "lane-runtime-api",
            "failures": [
                {
                    "lane_id": "lane-runtime-api",
                    "attempt": 1,
                    "failure_class": "demo_grade_boundary",
                    "reason": "First failure shows demo-grade boundary.",
                    "source_refs": ["pytest:demo-boundary-1"],
                },
                {
                    "lane_id": "lane-runtime-api",
                    "attempt": 2,
                    "failure_class": "demo_grade_boundary",
                    "reason": "Second failure requires refactor.",
                    "source_refs": ["pytest:demo-boundary-2"],
                },
            ],
        },
    )
    assert recovery.status_code == 201
    assert recovery.json()["decision"]["decision"] == "refactor_required"

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-review-refactor-block",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:should-not-review"],
            "execution_artifact_refs": ["artifacts/lane-runtime-api/result.json"],
            "reviewer_id": "review-god",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "god_room_lane_review_blocked_by_recovery_decision"
    assert detail["source_authority"] == "lane_dag_artifact+lane_recovery_artifact"
    assert detail["recovery_decision"]["decision"] == "refactor_required"
    assert detail["recovery_decision"]["retry_allowed"] is False
    assert "lane_status_not_updated" in detail["manual_gaps"]
    assert "live_runner_recovery_enforcement_not_proven" in detail["manual_gaps"]
    assert "end_to_end_execution_review_closure" in detail["forbidden_claims"]
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_intake"
        / "graph-review-refactor-block.lane-runtime-api.review-intake.json"
    ).exists()
    assert not (tmp_path / "review_plane.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


@pytest.mark.parametrize(
    ("graph_id", "recovery_payload", "expected_decision"),
    [
        (
            "graph-review-manual-gap-block",
            {"failures": []},
            "manual_gap",
        ),
        (
            "graph-review-suspended-block",
            {
                "failures": [
                    {
                        "lane_id": "lane-runtime-api",
                        "attempt": 1,
                        "failure_class": "lint_failure",
                        "reason": "First attempt failed lint.",
                        "source_refs": ["pytest:suspend-1"],
                    },
                    {
                        "lane_id": "lane-runtime-api",
                        "attempt": 2,
                        "failure_class": "type_failure",
                        "reason": "Second attempt failed type checks.",
                        "source_refs": ["pytest:suspend-2"],
                    },
                    {
                        "lane_id": "lane-runtime-api",
                        "attempt": 3,
                        "failure_class": "runtime_failure",
                        "reason": "Third attempt failed runtime checks.",
                        "source_refs": ["pytest:suspend-3"],
                    },
                    {
                        "lane_id": "lane-runtime-api",
                        "attempt": 4,
                        "failure_class": "review_failure",
                        "reason": "Fourth attempt exhausted retry budget.",
                        "source_refs": ["pytest:suspend-4"],
                    },
                ],
            },
            "suspended",
        ),
    ],
)
def test_chat_api_god_room_lane_review_intake_blocks_non_retry_recovery(
    tmp_path: Path,
    graph_id: str,
    recovery_payload: dict[str, object],
    expected_decision: str,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id=graph_id)
    recovery = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": graph_id,
            "lane_id": "lane-runtime-api",
            **recovery_payload,
        },
    )
    assert recovery.status_code == 201
    assert recovery.json()["decision"]["decision"] == expected_decision
    assert recovery.json()["decision"]["retry_allowed"] is False

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": graph_id,
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:blocked"],
            "execution_artifact_refs": ["artifacts/lane-runtime-api/result.json"],
            "reviewer_id": "review-god",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "god_room_lane_review_blocked_by_recovery_decision"
    assert detail["recovery_decision"]["decision"] == expected_decision
    assert detail["recovery_decision"]["retry_allowed"] is False
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_intake"
        / f"{graph_id}.lane-runtime-api.review-intake.json"
    ).exists()
    assert not (tmp_path / "review_plane.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_review_intake_preserves_manual_gap_without_candidate(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-review-gap")

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-review-gap",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == "lane_dag_artifact"
    intake = payload["review_intake"]
    assert intake["source_authority"] == "lane_dag_artifact"
    assert intake["review_truth_status"] == "pending_independent_review"
    assert intake["candidate_truth_status"] == "candidate_only"
    assert intake["recovery_decision"] is None
    assert intake["manual_gaps"] == [
        "worker_candidate_evidence_missing",
        "lane_recovery_decision_missing",
    ]
    assert "worker_output_is_review_truth" in intake["forbidden_claims"]


def test_chat_api_god_room_lane_review_intake_rejects_unknown_lane(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-review-unknown")

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-review-unknown",
            "lane_id": "lane-missing",
            "worker_candidate_refs": ["worker-candidate:run-1"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "god_room_lane_review_unknown_lane"
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_intake"
        / "graph-review-unknown.lane-missing.review-intake.json"
    ).exists()


def test_chat_api_god_room_lane_review_verdict_requires_independent_evidence(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-review-verdict")
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-review-verdict",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:run-1"],
            "execution_artifact_refs": ["artifacts/lane-runtime-api/result.json"],
        },
    ).status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": "graph-review-verdict",
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": "merge",
            "summary": "Candidate output matches the lane contract.",
            "evidence_refs": [
                "worker-candidate:run-1",
                "artifacts/lane-runtime-api/result.json",
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    artifact = payload["review_verdict"]
    assert payload["source_authority"] == "god_room_lane_review_intake_artifact"
    assert artifact["schema_version"] == "xmuse.god_room_lane_review_verdict.v1"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["review_truth_status"] == "independent_review_artifact"
    assert artifact["server_truth_status"] == "not_server_truth"
    assert artifact["candidate_truth_status"] == "candidate_only"
    assert artifact["reviewer_id"] == "review-god"
    assert artifact["review_verdict"]["decision"] == "merge"
    assert artifact["review_verdict"]["summary"] == (
        "Candidate output matches the lane contract."
    )
    assert artifact["review_verdict"]["evidence_refs"][0].endswith(
        "graph-review-verdict.lane-runtime-api.review-intake.json"
    )
    assert "worker-candidate:run-1" in artifact["review_verdict"]["evidence_refs"]
    assert artifact["review_plane_sync_status"] == "review_plane_store_updated"
    assert artifact["review_plane_task_ref"].startswith("review_plane_task:")
    assert artifact["review_plane_verdict_ref"].startswith("review_plane_verdict:")
    assert "review_plane_store_not_updated" not in artifact["manual_gaps"]
    assert "patch_forward_lane_dag_not_linked" in artifact["manual_gaps"]
    assert "end_to_end_execution_review_closure" in artifact["forbidden_claims"]
    assert "ready_to_merge" in artifact["forbidden_claims"]
    verdict_artifact = tmp_path / payload["artifacts"]["review_verdict"]
    assert verdict_artifact.exists()
    assert json.loads(verdict_artifact.read_text(encoding="utf-8")) == artifact
    review_plane = json.loads((tmp_path / "review_plane.json").read_text())
    assert review_plane["review_tasks"][0]["lane_id"] == "lane-runtime-api"
    assert review_plane["review_tasks"][0]["status"] == "verdict_emitted"
    assert review_plane["review_verdicts"][0]["lane_id"] == "lane-runtime-api"
    assert review_plane["review_verdicts"][0]["decision"] == "merge"
    assert review_plane["review_verdicts"][0]["summary"] == (
        "Candidate output matches the lane contract."
    )
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_review_verdict_rejects_missing_intake(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-verdict-no-intake")

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": "graph-verdict-no-intake",
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": "merge",
            "summary": "No intake exists.",
            "evidence_refs": ["worker-candidate:run-1"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "god_room_lane_review_intake_not_found"
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_verdicts"
        / "graph-verdict-no-intake.lane-runtime-api.review-verdict.json"
    ).exists()


def test_chat_api_god_room_lane_review_verdict_rejects_uncited_evidence(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-verdict-uncited")
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-verdict-uncited",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:run-1"],
        },
    ).status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": "graph-verdict-uncited",
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": "merge",
            "summary": "Evidence does not cite intake inputs.",
            "evidence_refs": ["worker-candidate:other-run"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "god_room_lane_review_verdict_missing_intake_evidence"
    )


@pytest.mark.parametrize(
    ("decision", "expected_code"),
    [
        (
            "patch-forward",
            "god_room_lane_review_verdict_missing_patch_instructions",
        ),
        ("terminate", "god_room_lane_review_verdict_missing_terminate_reason"),
    ],
)
def test_chat_api_god_room_lane_review_verdict_requires_decision_details(
    tmp_path: Path,
    decision: str,
    expected_code: str,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id=f"graph-verdict-{decision}")
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": f"graph-verdict-{decision}",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:run-1"],
        },
    ).status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": f"graph-verdict-{decision}",
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": decision,
            "summary": "Decision is missing required follow-up detail.",
            "evidence_refs": ["worker-candidate:run-1"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == expected_code
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_verdicts"
        / f"graph-verdict-{decision}.lane-runtime-api.review-verdict.json"
    ).exists()


def test_chat_api_god_room_lane_patch_forward_appends_lanedag_lane(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-patch-forward")
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-patch-forward",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:patch-run-1"],
            "execution_artifact_refs": ["artifacts/lane-runtime-api/result.json"],
        },
    ).status_code == 201
    verdict = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": "graph-patch-forward",
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": "patch-forward",
            "summary": "Candidate needs a bounded patch lane.",
            "evidence_refs": [
                "worker-candidate:patch-run-1",
                "artifacts/lane-runtime-api/result.json",
            ],
            "patch_instructions": "Repair recovery evidence lineage.",
        },
    )
    assert verdict.status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/patch-forward",
        json={
            "graph_id": "graph-patch-forward",
            "lane_id": "lane-runtime-api",
            "patch_lane_id": "lane-runtime-api-patch-1",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == (
        "god_room_lane_review_verdict_artifact+lane_dag_artifact"
    )
    assert payload["patch_lane_id"] == "lane-runtime-api-patch-1"
    patch_forward = payload["patch_forward"]
    assert patch_forward["schema_version"] == "xmuse.god_room_lane_patch_forward.v1"
    assert patch_forward["proof_level"] == "contract_proof"
    assert patch_forward["blueprint_proof_level"] == "contract_proof"
    assert "patch_lane_not_executed" in patch_forward["manual_gaps"]
    assert "patch_lane_not_reviewed" in patch_forward["manual_gaps"]
    assert "release_evidence_not_linked" in patch_forward["manual_gaps"]
    assert "end_to_end_execution_review_closure" in patch_forward["forbidden_claims"]
    assert "ready_to_merge" in patch_forward["forbidden_claims"]
    assert "pr_merged" in patch_forward["forbidden_claims"]
    assert "github_review_truth" in patch_forward["forbidden_claims"]
    patch_lane = next(
        lane
        for lane in payload["lane_dag"]["lane_graph"]["lanes"]
        if lane["feature_id"] == "lane-runtime-api-patch-1"
    )
    assert patch_lane["task_type"] == "patch_forward"
    assert patch_lane["source_lane_id"] == "lane-runtime-api"
    assert patch_lane["prompt"] == "Repair recovery evidence lineage."
    patch_contract = patch_forward["patch_lane_contract"]
    assert patch_contract["lane_id"] == "lane-runtime-api-patch-1"
    assert any(
        ref.endswith("graph-patch-forward.lane-runtime-api.review-verdict.json")
        for ref in patch_contract["source_refs"]
    )
    assert "worker-candidate:patch-run-1" in patch_contract["source_refs"]
    assert patch_forward["patch_forward_link"]["failed_lane_id"] == "lane-runtime-api"
    assert patch_forward["patch_forward_link"]["patch_lane_id"] == (
        "lane-runtime-api-patch-1"
    )
    assert (tmp_path / payload["artifacts"]["lane_dag"]).exists()
    assert (tmp_path / payload["artifacts"]["patch_forward"]).exists()
    review_plane = json.loads((tmp_path / "review_plane.json").read_text())
    assert review_plane["review_verdicts"][0]["lane_id"] == "lane-runtime-api"
    assert review_plane["review_verdicts"][0]["decision"] == "patch-forward"
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_patch_forward_requires_patch_verdict(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-patch-reject")
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-patch-reject",
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:merge-run-1"],
        },
    ).status_code == 201
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": "graph-patch-reject",
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": "merge",
            "summary": "Candidate is accepted by independent review.",
            "evidence_refs": ["worker-candidate:merge-run-1"],
        },
    ).status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/patch-forward",
        json={
            "graph_id": "graph-patch-reject",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "god_room_lane_patch_forward_requires_patch_verdict"
    )
    assert not (
        tmp_path
        / "reports"
        / "god_room_patch_forward"
        / "graph-patch-reject.lane-runtime-api.patch-forward.json"
    ).exists()


def test_chat_api_god_room_lane_patch_forward_requires_verdict_artifact(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-patch-missing-verdict")

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/patch-forward",
        json={
            "graph_id": "graph-patch-missing-verdict",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "god_room_lane_review_verdict_not_found"
    assert not (
        tmp_path
        / "reports"
        / "god_room_patch_forward"
        / "graph-patch-missing-verdict.lane-runtime-api.patch-forward.json"
    ).exists()


def test_chat_api_god_room_lane_review_closure_links_reviewed_patch_lane(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_reviewed_patch_forward_lane(
        client,
        graph_id="graph-review-closure",
        patch_lane_id="lane-runtime-api-patch-reviewed",
        patch_decision="merge",
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-closure",
        json={
            "graph_id": "graph-review-closure",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == (
        "god_room_lane_patch_forward_artifact+patch_lane_review_verdict_artifact"
    )
    closure = payload["review_closure"]
    assert closure["schema_version"] == "xmuse.god_room_lane_review_closure.v1"
    assert closure["proof_level"] == "contract_proof"
    assert closure["review_truth_status"] == "independent_review_artifact"
    assert closure["execution_truth_status"] == "candidate_reviewed"
    assert closure["server_truth_status"] == "not_server_truth"
    assert closure["release_evidence_handoff_status"] == "candidate_input_ready"
    assert closure["failed_lane_id"] == "lane-runtime-api"
    assert closure["terminal_lane_id"] == "lane-runtime-api-patch-reviewed"
    assert closure["patch_lane_contract"]["lane_id"] == (
        "lane-runtime-api-patch-reviewed"
    )
    assert "worker-candidate:patch-reviewed" in closure["candidate_refs"]
    assert "artifacts/lane-runtime-api-patch-reviewed/result.json" in closure[
        "candidate_refs"
    ]
    assert "worker-candidate:patch-reviewed" in closure["cited_candidate_refs"]
    assert closure["terminal_review_verdict"]["decision"] == "merge"
    assert closure["review_plane_sync_status"] == "review_plane_store_updated"
    assert closure["review_plane_verdict_ref"].startswith("review_plane_verdict:")
    assert "review_plane_store_not_updated" not in closure["manual_gaps"]
    assert "lane_status_not_updated" in closure["manual_gaps"]
    assert "release_evidence_not_linked" in closure["manual_gaps"]
    assert "github_truth_not_checked" in closure["manual_gaps"]
    assert "worker_output_is_review_truth" in closure["forbidden_claims"]
    assert "end_to_end_execution_review_closure" in closure["forbidden_claims"]
    assert "ready_to_merge" in closure["forbidden_claims"]
    assert "pr_merged" in closure["forbidden_claims"]
    assert "github_review_truth" in closure["forbidden_claims"]
    assert (tmp_path / payload["artifacts"]["review_closure"]).exists()
    review_plane = json.loads((tmp_path / "review_plane.json").read_text())
    assert {
        row["lane_id"]: row["decision"] for row in review_plane["review_verdicts"]
    } == {
        "lane-runtime-api": "patch-forward",
        "lane-runtime-api-patch-reviewed": "merge",
    }
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_review_closure_requires_review_plane_verdict(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_reviewed_patch_forward_lane(
        client,
        graph_id="graph-review-closure-no-plane",
        patch_lane_id="lane-runtime-api-patch-no-plane",
        patch_decision="merge",
    )
    (tmp_path / "review_plane.json").unlink()

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-closure",
        json={
            "graph_id": "graph-review-closure-no-plane",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "god_room_lane_review_closure_missing_review_plane_verdict"
    )
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_closure"
        / "graph-review-closure-no-plane.lane-runtime-api.review-closure.json"
    ).exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_lane_review_closure_requires_patch_lane_verdict(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_patch_forward_lane(
        client,
        graph_id="graph-closure-missing-verdict",
        patch_lane_id="lane-runtime-api-patch-unreviewed",
    )
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": "graph-closure-missing-verdict",
            "lane_id": "lane-runtime-api-patch-unreviewed",
            "worker_candidate_refs": ["worker-candidate:patch-unreviewed"],
            "execution_artifact_refs": [
                "artifacts/lane-runtime-api-patch-unreviewed/result.json"
            ],
        },
    ).status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-closure",
        json={
            "graph_id": "graph-closure-missing-verdict",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == (
        "god_room_patch_lane_review_verdict_not_found"
    )
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_closure"
        / "graph-closure-missing-verdict.lane-runtime-api.review-closure.json"
    ).exists()


def test_chat_api_god_room_lane_review_closure_requires_patch_lane_merge_verdict(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_reviewed_patch_forward_lane(
        client,
        graph_id="graph-closure-rework-verdict",
        patch_lane_id="lane-runtime-api-patch-rework",
        patch_decision="rework",
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-closure",
        json={
            "graph_id": "graph-closure-rework-verdict",
            "lane_id": "lane-runtime-api",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "god_room_lane_review_closure_requires_merge_verdict"
    )
    assert not (
        tmp_path
        / "reports"
        / "god_room_review_closure"
        / "graph-closure-rework-verdict.lane-runtime-api.review-closure.json"
    ).exists()


def test_chat_api_god_room_lane_recovery_rejects_graph_path_escape(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-safe")
    escaped = tmp_path / "escaped.lane-dag.json"
    escaped.write_text(
        (tmp_path / "lane_graphs" / "graph-safe.lane-dag.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": "../escaped",
            "lane_id": "lane-runtime-api",
            "failures": [],
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "lane_graphs" / ".._escaped.lane-runtime-api.recovery.json").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_chat_api_god_room_memoryos_plan_builds_from_room_and_lane_artifacts(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conv_id = _create_god_room_lane_dag(client, graph_id="graph-memoryos")
    recovery = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/recovery",
        json={
            "graph_id": "graph-memoryos",
            "lane_id": "lane-runtime-api",
            "failures": [
                {
                    "lane_id": "lane-runtime-api",
                    "attempt": 1,
                    "failure_class": "memory_governance_gap",
                    "reason": "MemoryOS plan artifact was missing.",
                    "source_refs": ["pytest:memory-plan-gap"],
                }
            ],
        },
    )
    assert recovery.status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/memoryos-plan",
        json={
            "graph_id": "graph-memoryos",
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "context_budget": 1024,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_authority"] == "god_room_memoryos_plan_contract"
    plan = payload["memoryos_plan"]
    assert plan["schema_version"] == "xmuse.god_room_memoryos_plan.v1"
    assert plan["conversation_id"] == conv_id
    assert plan["graph_id"] == "graph-memoryos"
    assert plan["proof_level"] == "contract_proof"
    assert plan["live_trace"]["status"] == "manual_gap"
    assert plan["live_trace"]["blocked_reason"] == (
        "memoryos_lite_live_environment_missing"
    )
    assert plan["ingest_request_count"] == plan["plan_count"]
    assert any(
        item["event_kind"] == "blueprint_frozen"
        and item["target_namespace_uri"].endswith("/blueprint/bp-god-room")
        for item in plan["plans"]
    )
    assert any(
        item["event_kind"] == "lane_recovery_decision"
        and "pytest:memory-plan-gap" in item["source_refs"]
        for item in plan["plans"]
    )
    assert plan["context_plans"][0]["budget"] == 1024
    assert payload["artifacts"]["memoryos_plan"].endswith(
        "reports/god_room_memoryos/graph-memoryos.memoryos-plan.json"
    )
    assert (tmp_path / payload["artifacts"]["memoryos_plan"]).exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def _create_god_room_lane_dag(client: TestClient, *, graph_id: str) -> str:
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": f"GOD room recovery {graph_id}"},
    ).json()
    conv_id = conversation["id"]
    room = client.post(f"/api/chat/conversations/{conv_id}/god-room").json()["room"]
    participants = {participant["role"]: participant for participant in room["participants"]}
    blueprint_ref = "blueprint:bp-god-room:1"

    for event in [
        {
            "event_id": f"evt-propose-{graph_id}",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["architect"]["participant_id"],
            "god_id": participants["architect"]["god_id"],
            "actor_kind": "god",
            "event_type": "speak",
            "timestamp_utc": "2026-06-13T10:00:00Z",
            "content": "Build lane recovery from laneDAG budget.",
            "source_refs": [f"conversation:{conv_id}", f"message:evt-propose-{graph_id}"],
            "cli_id": participants["architect"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "goal": "Build lane recovery from laneDAG budget.",
                "scope": ["GOD room lane recovery runtime action"],
                "acceptance_contracts": ["Recovery decisions use lane runtime budgets."],
            },
        },
        {
            "event_id": f"evt-freeze-{graph_id}",
            "room_id": room["room_id"],
            "conversation_id": conv_id,
            "participant_id": participants["review"]["participant_id"],
            "god_id": participants["review"]["god_id"],
            "actor_kind": "god",
            "event_type": "freeze_requested",
            "timestamp_utc": "2026-06-13T10:03:00Z",
            "content": "Freeze for recovery planning.",
            "source_refs": [f"conversation:{conv_id}", f"message:evt-freeze-{graph_id}"],
            "causal_parent_id": f"evt-propose-{graph_id}",
            "cli_id": participants["review"]["cli_id"],
            "provider_profile": "codex",
            "payload": {
                "freeze_target_ref": blueprint_ref,
                "goal": "Build lane recovery from laneDAG budget.",
                "scope": ["GOD room lane recovery runtime action"],
                "acceptance_contracts": ["Recovery decisions use lane runtime budgets."],
            },
        },
    ]:
        response = client.post(
            f"/api/chat/conversations/{conv_id}/god-room/events",
            json=event,
        )
        assert response.status_code in {200, 201}
    freeze = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/freeze-blueprint",
        json={"blueprint_id": "bp-god-room", "revision": 1},
    )
    assert freeze.status_code == 201
    lane_dag = client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag",
        json={
            "resolution_id": freeze.json()["resolution"]["id"],
            "graph_id": graph_id,
            "source_refs": [f"god-room-freeze:evt-freeze-{graph_id}"],
            "features": [
                {
                    "feature_id": "feature-runtime",
                    "title": "Runtime recovery",
                    "goal": "Evaluate recovery from lane runtime budgets.",
                    "acceptance_criteria": ["Recovery artifacts are persisted."],
                    "blueprint_refs": [blueprint_ref],
                }
            ],
            "lanes": [
                {
                    "lane_id": "lane-runtime-api",
                    "feature_id": "feature-runtime",
                    "title": "Expose lane recovery runtime API",
                    "prompt": "Build the lane recovery runtime action.",
                    "acceptance_criteria": ["Focused tests cover recovery decisions."],
                    "blueprint_refs": [blueprint_ref],
                    "owner": "execute-god",
                    "inputs": [blueprint_ref],
                    "outputs": ["artifact://lane-runtime-api/recovery.json"],
                    "required_checks": ["focused-pytest", "ruff"],
                    "allowed_files": ["xmuse/chat_api.py"],
                    "rollback_constraints": ["preserve lane failure evidence"],
                    "review_profile": "runtime-recovery-review",
                    "budget": {
                        "max_attempts": 4,
                        "max_consecutive_same_failure": 2,
                        "max_runtime_seconds": 1800,
                        "retry_backoff_seconds": 30,
                        "source_refs": ["budget:lane-runtime-api"],
                    },
                }
            ],
        },
    )
    assert lane_dag.status_code == 201
    return conv_id


def _create_patch_forward_lane(
    client: TestClient,
    *,
    graph_id: str,
    patch_lane_id: str,
) -> str:
    conv_id = _create_god_room_lane_dag(client, graph_id=graph_id)
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": graph_id,
            "lane_id": "lane-runtime-api",
            "worker_candidate_refs": ["worker-candidate:root-patch"],
            "execution_artifact_refs": ["artifacts/lane-runtime-api/result.json"],
        },
    ).status_code == 201
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": graph_id,
            "lane_id": "lane-runtime-api",
            "reviewer_id": "review-god",
            "decision": "patch-forward",
            "summary": "Root lane needs a patch-forward lane.",
            "evidence_refs": [
                "worker-candidate:root-patch",
                "artifacts/lane-runtime-api/result.json",
            ],
            "patch_instructions": "Apply a bounded patch-forward repair.",
        },
    ).status_code == 201
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/patch-forward",
        json={
            "graph_id": graph_id,
            "lane_id": "lane-runtime-api",
            "patch_lane_id": patch_lane_id,
        },
    ).status_code == 201
    return conv_id


def _create_reviewed_patch_forward_lane(
    client: TestClient,
    *,
    graph_id: str,
    patch_lane_id: str,
    patch_decision: str,
) -> str:
    conv_id = _create_patch_forward_lane(
        client,
        graph_id=graph_id,
        patch_lane_id=patch_lane_id,
    )
    candidate_ref = "worker-candidate:patch-reviewed"
    execution_ref = f"artifacts/{patch_lane_id}/result.json"
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-intake",
        json={
            "graph_id": graph_id,
            "lane_id": patch_lane_id,
            "worker_candidate_refs": [candidate_ref],
            "execution_artifact_refs": [execution_ref],
        },
    ).status_code == 201
    assert client.post(
        f"/api/chat/conversations/{conv_id}/god-room/lane-dag/review-verdict",
        json={
            "graph_id": graph_id,
            "lane_id": patch_lane_id,
            "reviewer_id": "review-god",
            "decision": patch_decision,
            "summary": "Patch lane candidate was independently reviewed.",
            "evidence_refs": [candidate_ref, execution_ref],
        },
    ).status_code == 201
    return conv_id


def test_chat_api_operator_action_denies_missing_capability(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Mission"}).json()

    response = client.post(
        "/api/chat/operator/actions",
        headers={"X-XMuse-Operator-Id": "operator-1"},
        json={
            "action": "select_god_cli",
            "idempotency_key": "idem-chat-2",
            "payload": {
                "conversation_id": conversation["id"],
                "cli_id": "codex.god",
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "denied"
    selection_response = client.get(
        f"/api/chat/operator/god-cli-selections/{conversation['id']}"
    )
    assert selection_response.status_code == 404


def test_chat_api_operator_action_registers_manual_god_cli(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "register_god_cli",
        },
        json={
            "action": "register_god_cli",
            "idempotency_key": "idem-chat-register-1",
            "payload": _manual_god_cli_registration_payload(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fact_state"] == "god_cli_registered"
    assert payload["payload"]["durable_state_ref"] == (
        "god_cli_registration:custom.peer"
    )

    list_response = client.get("/api/chat/operator/god-cli-registrations")
    assert list_response.status_code == 200
    registrations = list_response.json()["registrations"]
    assert registrations[0]["registration"]["cli_id"] == "custom.peer"
    assert registrations[0]["registered_by"] == "operator-1"


def test_chat_api_operator_action_captures_release_evidence_pack(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    artifacts_dir = tmp_path / "work" / "release_readiness" / "artifacts"
    _write_json(
        artifacts_dir / "provider.json",
        {
            "schema_version": "xmuse.production_evidence.v1",
            "gate_id": "provider-soak",
            "kind": "real_provider",
            "configured": True,
            "required": True,
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "owner": "operator",
            "summary": "Provider soak was not supplied.",
        },
    )

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "release_gate",
        },
        json={
            "action": "capture_release_evidence_pack",
            "idempotency_key": "idem-release-api",
            "payload": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fact_state"] == "release_evidence_pack_captured"
    assert payload["payload"]["evidence_pack"]["decision"] == "blocked"
    assert (tmp_path / "work" / "release_readiness" / "evidence-pack.json").exists()


def test_chat_api_operator_action_exports_natural_release_evidence(
    tmp_path: Path,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation(
        "Natural export",
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "release_gate",
        },
        json={
            "action": "export_natural_deliberation_transcript",
            "idempotency_key": "idem-natural-export-api",
            "payload": {
                "conversation_id": conversation.id,
                "target_refs": ["blueprint:bp-1"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fact_state"] == "release_evidence_exported"
    exported = payload["payload"]["export"]
    assert exported["kind"] == "natural_deliberation"
    assert exported["gate"]["gate_id"] == "natural-god-deliberation"
    assert (
        tmp_path / "work" / "release_readiness" / "natural-transcript.json"
    ).exists()
    assert (
        tmp_path / "work" / "release_readiness" / "artifacts" / "natural-deliberation.json"
    ).exists()


def test_chat_api_operator_action_refreshes_live_gate_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def _fake_capture_live_gate_status(*, output_dir, env=None, command_runner=None):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        artifact = output / "live-memoryos-status.json"
        _write_json(
            artifact,
            {
                "schema_version": "xmuse.production_evidence.v1",
                "gate_id": "live-memoryos",
                "kind": "live_memoryos",
                "configured": False,
                "required": True,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "owner": "operator",
                "summary": "MemoryOS Lite live gate is required but not configured.",
            },
        )
        return {
            "schema_version": "xmuse.live_gate_status_capture.v1",
            "artifact_count": 1,
            "output_dir": str(output),
            "artifacts": [str(artifact)],
            "probes": {},
            "env_keys_present": [],
        }

    monkeypatch.setattr(
        "xmuse_core.platform.operator_actions.capture_live_gate_status",
        _fake_capture_live_gate_status,
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "release_gate",
        },
        json={
            "action": "refresh_live_gate_status",
            "idempotency_key": "idem-refresh-api",
            "payload": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fact_state"] == "live_gate_status_refreshed"
    assert payload["payload"]["live_gate_status"]["artifact_count"] == 1
    assert (
        tmp_path
        / "work"
        / "release_readiness"
        / "artifacts"
        / "live_gate_status"
        / "live-memoryos-status.json"
    ).exists()


def test_chat_api_operator_action_freezes_blueprint_with_capability(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Freeze"}).json()
    conv_id = conversation["id"]
    target_ref = "blueprint:bp-chat-1:1"
    for event in [
        _deliberation(
            conv_id,
            msg_id="msg-proposal",
            kind="proposal",
            target_ref=target_ref,
            payload={"summary": "Freeze through operator action."},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-review",
            kind="note",
            target_ref=target_ref,
            payload={"review": "no_objection"},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-commit",
            kind="commit",
            target_ref=target_ref,
            agent_id="god-review",
            payload={"commitment": "ready_to_freeze"},
        ),
    ]:
        response = client.post(f"/api/chat/conversations/{conv_id}/deliberations", json=event)
        assert response.status_code == 201

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "chat_freeze_blueprint",
        },
        json={
            "action": "freeze_blueprint",
            "idempotency_key": "idem-freeze-api-1",
            "payload": {
                "conversation_id": conv_id,
                "target_ref": target_ref,
                "blueprint": {
                    "blueprint_id": "bp-chat-1",
                    "revision": 1,
                    "goal": "Freeze through the operator action contract.",
                    "scope": ["Route freeze through operator action"],
                    "acceptance_contracts": ["A durable mission blueprint resolution exists"],
                    "source_refs": ["memory://conversation/conv-1/message/msg-proposal"],
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fact_state"] == "blueprint_frozen"
    assert payload["payload"]["freeze"]["decision"]["status"] == "allowed"
    resolution_id = payload["payload"]["freeze"]["resolution"]["id"]
    stored = ChatStore(tmp_path / "chat.db").get_resolution(resolution_id)
    assert stored.approval_mode == "deliberation_freeze"
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "work" / "operator_actions" / "operator-actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert audit_rows[-1]["action"] == "freeze_blueprint"
    assert audit_rows[-1]["status"] == "ok"


def test_chat_api_operator_action_denies_blueprint_freeze_without_capability(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Freeze"}).json()

    response = client.post(
        "/api/chat/operator/actions",
        headers={"X-XMuse-Operator-Id": "operator-1"},
        json={
            "action": "freeze_blueprint",
            "idempotency_key": "idem-freeze-api-2",
            "payload": {
                "conversation_id": conversation["id"],
                "target_ref": "blueprint:bp-chat-2:1",
                "blueprint": {
                    "blueprint_id": "bp-chat-2",
                    "goal": "Denied freeze.",
                    "scope": ["No unauthorized freeze"],
                    "acceptance_contracts": ["No resolution is created"],
                },
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "denied"
    assert not ChatStore(tmp_path / "chat.db").list_resolutions()


def test_chat_api_operator_action_retries_lane_with_workflow_capability(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "projection_revision": 1,
            "lanes": [
                {
                    "feature_id": "lane-1",
                    "status": "failed",
                    "retry_count": 0,
                    "conversation_id": "conv-user",
                }
            ],
        },
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Capabilities": "workflow_write",
        },
        json={
            "action": "retry_lane",
            "idempotency_key": "idem-lane-api-1",
            "payload": {
                "lane_id": "lane-1",
                "current_status": "failed",
                "reason": "retry via TUI operator action",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fact_state"] == "lane_retry_requested"
    assert payload["payload"]["lane"]["status"] == "reworking"
    updated = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert updated["lanes"][0]["status"] == "reworking"
    assert updated["lanes"][0]["last_mutation_audit"] == {
        "actor": "operator-1",
        "reason": "retry via TUI operator action",
        "request_id": "idem-lane-api-1",
        "tool": "retry_lane",
    }


def test_chat_api_operator_action_denies_lane_retry_without_workflow_capability(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "lane-1", "status": "failed", "retry_count": 0}]},
    )
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/operator/actions",
        headers={"X-XMuse-Operator-Id": "operator-1"},
        json={
            "action": "retry_lane",
            "idempotency_key": "idem-lane-api-2",
            "payload": {"lane_id": "lane-1", "current_status": "failed"},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["status"] == "denied"
    updated = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert updated["lanes"][0]["status"] == "failed"


def test_default_chat_participants_are_codex_only(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/chat/conversations", json={"title": "xmuse MVP"})

    assert response.status_code == 201
    participants = response.json()["participants"]
    assert {participant["role"] for participant in participants} == {
        "architect",
        "review",
        "execute",
    }
    assert {participant["provider_id"] for participant in participants} == {"codex"}
    assert {participant["role"]: participant["profile_id"] for participant in participants} == {
        "architect": "god",
        "review": "review",
        "execute": "worker",
    }
    assert {participant["cli_kind"] for participant in participants} == {"codex"}
    assert {participant["role"]: participant["model"] for participant in participants} == {
        "architect": "gpt-5.4",
        "review": "gpt-5.4",
        "execute": "gpt-5.4-mini",
    }


def test_chat_api_accepts_provider_profile_participant_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "xmuse MVP",
            "initial_participants": [
                {
                    "role": "review",
                    "provider_id": "codex",
                    "profile_id": "review",
                    "model": "gpt-5.5",
                }
            ],
        },
    )

    assert response.status_code == 201
    participants = response.json()["participants"]
    assert len(participants) == 1
    assert participants[0]["provider_id"] == "codex"
    assert participants[0]["profile_id"] == "review"
    assert participants[0]["cli_kind"] == "codex"


def test_chat_api_rejects_claude_participant(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "xmuse MVP",
            "initial_participants": [
                {
                    "role": "architect",
                    "cli_kind": "claude",
                    "model": "sonnet",
                }
            ],
        },
    )

    assert response.status_code == 422


def test_chat_api_rejects_claude_role_template(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/role-templates",
        json={
            "slug": "legacy-claude",
            "display_name": "Legacy Claude",
            "prompt": "No longer supported.",
            "cli_kind": "claude",
            "default_model": "sonnet",
        },
    )

    assert response.status_code == 422


def test_chat_api_role_template_exposes_provider_profile_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/role-templates",
        json={
            "slug": "custom-role",
            "display_name": "Custom Role",
            "prompt": "Act as a custom collaborator.",
            "provider_id": "codex",
            "profile_id": "default",
            "default_model": "gpt-5.5",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider_id"] == "codex"
    assert payload["profile_id"] == "default"
    assert payload["cli_kind"] == "codex"


def test_chat_proposal_approval_creates_resolution_snapshot(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "xmuse MVP"},
    ).json()

    proposal_response = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane-plan",
            "content": "Split into chat, planner, execution, dashboard lanes.",
            "references": [],
        },
    )

    assert proposal_response.status_code == 201
    proposal = proposal_response.json()

    approval_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "human",
            "goal_summary": "Build the MVP",
        },
    )

    assert approval_response.status_code == 200
    resolution = approval_response.json()
    assert resolution["version"] == 1
    assert resolution["status"] == "approved"

    fetch_response = client.get(f"/api/chat/resolutions/{resolution['id']}")

    assert fetch_response.status_code == 200
    assert fetch_response.json()["derived_from_proposal_ids"] == [proposal["id"]]


def test_approving_proposal_projects_dependency_ready_lanes_into_execution_queue(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "xmuse MVP"},
    ).json()
    proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane-plan",
            "content": "Split into chat and dashboard lanes.",
            "references": [],
        },
    ).json()

    approval_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "human",
            "goal_summary": "Build the MVP",
            "content": {
                "lanes": [
                    {
                        "feature_id": "chat-plane",
                        "prompt": "Build the chat plane.",
                        "priority": 90,
                        "capabilities": ["code"],
                        "depends_on": [],
                    },
                    {
                        "feature_id": "dashboard-split",
                        "prompt": "Build the dashboard surface.",
                        "priority": 60,
                        "capabilities": ["code", "test"],
                        "depends_on": ["chat-plane"],
                    },
                ]
            },
        },
    )

    assert approval_response.status_code == 200
    resolution = approval_response.json()
    lanes_path = tmp_path / "feature_lanes.json"
    assert lanes_path.exists()
    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert lanes
    assert lanes[0]["worktree"] == str(chat_api.REPO_ROOT)
    assert lanes[0]["worktree"] != str(tmp_path)
    graph_path = tmp_path / "lane_graphs" / f"{resolution['id']}-graph-v1.json"
    assert graph_path.exists()


def test_generic_mission_blueprint_approval_rejects_lane_resolution_content(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "xmuse blueprint"},
    ).json()
    proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": (
                '{"resolution_content":{"lanes":[{"feature_id":"hidden-lane",'
                '"prompt":"Do not project this as a blueprint approval.",'
                '"depends_on":[],"capabilities":["code"]}]}}'
            ),
            "references": [],
        },
    ).json()

    approval_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "human",
            "goal_summary": "Approve the blueprint",
        },
    )

    assert approval_response.status_code == 200
    resolution = approval_response.json()
    assert resolution["content"]["type"] == "mission_blueprint"
    assert resolution["content"]["blueprint_ref"] == (
        f"resolution:{resolution['id']}:mission_blueprint"
    )
    assert "lanes" not in resolution["content"]
    assert not (tmp_path / "feature_lanes.json").exists()
    assert not (tmp_path / "lane_graphs").exists()


def test_mission_blueprint_approval_strips_embedded_lane_payload(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "xmuse blueprint"},
    ).json()
    proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": (
                '{"type":"mission_blueprint","title":"Chat-first mission",'
                '"body":"Use chat before lane planning.",'
                '"acceptance_criteria":["Blueprint approval creates a stable ref."],'
                '"lanes":[{"feature_id":"hidden-lane","prompt":"Do not keep this."}]}'
            ),
            "references": [],
        },
    ).json()

    approval_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "human",
            "goal_summary": "Approve the blueprint",
        },
    )

    assert approval_response.status_code == 200
    resolution = approval_response.json()
    assert resolution["content"]["type"] == "mission_blueprint"
    assert resolution["content"]["title"] == "Chat-first mission"
    assert "lanes" not in resolution["content"]
    assert not (tmp_path / "feature_lanes.json").exists()
    assert not (tmp_path / "lane_graphs").exists()


def test_mission_blueprint_approval_enqueues_blueprint_approved_event_once(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "xmuse blueprint"},
    ).json()
    proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": (
                '{"type":"mission_blueprint","title":"Chat-first mission",'
                '"body":"Blueprint approval should only queue planning.",'
                '"acceptance_criteria":["Emit one blueprint.approved event."]}'
            ),
            "references": [],
        },
    ).json()

    approval_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve the blueprint",
        },
    )

    assert approval_response.status_code == 200
    resolution = approval_response.json()
    queue_path = tmp_path / "planning_events.sqlite3"
    assert queue_path.exists()

    with sqlite3.connect(queue_path) as conn:
        row = conn.execute(
            """
            select event_id, event_type, planning_run_id, dedupe_key
            from planning_events
            """
        ).fetchone()
        count = conn.execute("select count(*) from planning_events").fetchone()[0]

    assert row is not None
    event_id, event_type, planning_run_id, dedupe_key = row
    assert count == 1
    assert event_type == "blueprint.approved"
    assert planning_run_id is None
    assert dedupe_key == build_blueprint_approval_dedupe_key(
        conversation_id=conversation["id"],
        blueprint_artifact_id=resolution["content"]["blueprint_ref"],
        resolution_id=resolution["id"],
    )

    event = PlanningEventStore(queue_path).get(event_id)
    assert event.payload["resolution_id"] == resolution["id"]
    assert event.payload["human_trigger_enabled"] is False
    assert not (tmp_path / "feature_lanes.json").exists()
    assert not (tmp_path / "lane_graphs").exists()


def test_chat_threads_endpoint_projects_conversations_and_messages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "lane-alpha"}).json()
    client.post(
        f"/api/chat/conversations/{conversation['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Summarize the blocking gate evidence.",
        },
    )

    threads_response = client.get("/api/chat/threads")

    assert threads_response.status_code == 200
    thread = threads_response.json()["threads"][0]
    assert thread["id"] == conversation["id"]
    assert thread["featureId"] == "lane-alpha"
    assert thread["messages"][0]["role"] == "user"


def test_chat_threads_expose_isolated_workspace_overviews(tmp_path: Path) -> None:
    client = _client(tmp_path)
    alpha = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    beta = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    alpha_message = client.post(
        f"/api/chat/conversations/{alpha['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "@architect alpha needs a compact overview.",
        },
    ).json()
    beta_message = client.post(
        f"/api/chat/conversations/{beta['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "@review beta must stay separate.",
        },
    ).json()
    ChatInboxStore(tmp_path / "chat.db").claim_next(owner="alpha-worker")
    alpha_proposal = client.post(
        f"/api/chat/conversations/{alpha['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane_graph",
            "content": '{"summary":"Alpha work","lanes":[{"feature_id":"alpha-lane"}]}',
            "references": [alpha_message["id"]],
        },
    ).json()
    client.post(
        f"/api/chat/conversations/{beta['id']}/proposals",
        json={
            "author": "review-god",
            "proposal_type": "lane_graph",
            "content": '{"summary":"Beta work","lanes":[{"feature_id":"beta-lane"}]}',
            "references": [beta_message["id"]],
        },
    )
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-alpha",
                    "conversation_id": alpha["id"],
                    "participant_id": alpha["participants"][0]["participant_id"],
                    "role": "architect",
                    "status": "running",
                },
                {
                    "god_session_id": "god-beta",
                    "conversation_id": beta["id"],
                    "participant_id": beta["participants"][0]["participant_id"],
                    "role": "review",
                    "status": "running",
                },
            ]
        },
    )

    response = client.get("/api/chat/threads")

    assert response.status_code == 200
    threads = {thread["id"]: thread for thread in response.json()["threads"]}
    alpha_thread = threads[alpha["id"]]
    beta_thread = threads[beta["id"]]
    assert alpha_thread["href"] == f"/dashboard/peer-chat/conversations/{alpha['id']}"
    assert alpha_thread["dashboard_href"] == alpha_thread["href"]
    assert alpha_thread["api_href"] == f"/api/chat/conversations/{alpha['id']}/messages"
    assert alpha_thread["last_activity_at"] == alpha_thread["updatedAt"]
    assert alpha_thread["participants"]["total"] == 3
    assert {item["conversation_id"] for item in alpha_thread["participants"]["items"]} == {
        alpha["id"]
    }
    assert alpha_thread["inbox_counts"] == {"unread": 0, "claimed": 1}
    assert alpha_thread["linked_session_ids"] == ["god-alpha"]
    assert [session["god_session_id"] for session in alpha_thread["sessions"]] == ["god-alpha"]
    assert [message["id"] for message in alpha_thread["recent_messages"]] == [
        alpha_message["id"]
    ]
    assert [message["id"] for message in beta_thread["recent_messages"]] == [
        beta_message["id"]
    ]
    assert alpha_proposal["id"] in [
        card["source_id"] for card in alpha_thread["recent_cards"]
    ]
    assert all("lanes" not in card for card in alpha_thread["recent_cards"])
    assert "beta" not in json.dumps(alpha_thread)
    assert "alpha" not in json.dumps(beta_thread)


def test_chat_conversations_list_preserves_compact_card_compatibility_fields(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    alpha = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    beta = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    alpha_message = client.post(
        f"/api/chat/conversations/{alpha['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Keep the alpha workspace cards compact.",
        },
    ).json()
    client.post(
        f"/api/chat/conversations/{beta['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Beta must stay isolated.",
        },
    )
    alpha_proposal = client.post(
        f"/api/chat/conversations/{alpha['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane_graph",
            "content": '{"summary":"Alpha contract card","lanes":[{"feature_id":"alpha-lane"}]}',
            "references": [alpha_message["id"]],
        },
    ).json()
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "alpha-lane",
                    "conversation_id": alpha["id"],
                    "status": "pending",
                },
                {
                    "feature_id": "beta-lane",
                    "conversation_id": beta["id"],
                    "status": "merged",
                },
            ]
        },
    )

    response = client.get("/api/chat/conversations")

    assert response.status_code == 200
    conversations = {item["id"]: item for item in response.json()["conversations"]}
    alpha_row = conversations[alpha["id"]]
    assert alpha_row["href"] == f"/dashboard/peer-chat/conversations/{alpha['id']}"
    assert alpha_row["dashboard_href"] == alpha_row["href"]
    assert alpha_row["api_href"] == f"/api/chat/conversations/{alpha['id']}/messages"
    assert [message["id"] for message in alpha_row["recent_messages"]] == [alpha_message["id"]]
    assert alpha_row["card_counts"] == {
        "proposal": 1,
        "worklist_summary": 1,
        "health_summary": 1,
        "total": 3,
    }
    assert {card["source_id"] for card in alpha_row["recent_cards"]} == {
        alpha_proposal["id"],
        "run_health",
        "worklist",
    }
    assert all(card["conversation_id"] == alpha["id"] for card in alpha_row["recent_cards"])
    assert all(card["href"] and card["api_href"] for card in alpha_row["recent_cards"])
    assert "beta-lane" not in json.dumps(alpha_row)
    assert "mission-beta" not in json.dumps(alpha_row)


def test_thread_message_endpoint_records_human_checkpoint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "lane-beta"}).json()

    response = client.post(
        f"/api/chat/threads/{conversation['id']}/messages",
        json={"message": "Keep the next patch minimal."},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["thread_id"] == conversation["id"]
    assert payload["message"]["role"] == "user"
    assert payload["message"]["content"] == "Keep the next patch minimal."


def test_chat_messages_include_compact_drilldown_cards_without_large_embeds(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()
    first_id = first["id"]
    second_id = second["id"]

    client.post(
        f"/api/chat/conversations/{first_id}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Plan the chat frontdoor.",
        },
    )
    client.post(
        f"/api/chat/conversations/{second_id}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "This other conversation must stay isolated.",
        },
    )

    proposal = client.post(
        f"/api/chat/conversations/{first_id}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane_graph",
            "content": (
                '{"summary":"Build frontdoor cards",'
                '"lanes":[{"feature_id":"lane-a","prompt":"large prompt text",'
                '"depends_on":[],"capabilities":["code"]}],'
                '"evidence_bundle":{"logs":["very large log blob"]}}'
            ),
            "references": ["msg-source"],
        },
    ).json()
    blueprint = client.post(
        f"/api/chat/conversations/{first_id}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": (
                '{"type":"mission_blueprint","title":"Chat-first mission",'
                '"body":"Long blueprint body belongs behind a link.",'
                '"acceptance_criteria":["Compact cards link to details."]}'
            ),
            "references": ["doc:blueprint"],
        },
    ).json()
    approved = client.post(
        f"/api/chat/proposals/{blueprint['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve chat-first mission",
        },
    ).json()

    graph_id = "frontdoor-graph-v1"
    graph_dir = tmp_path / "lane_graphs"
    graph_dir.mkdir()
    _write_json(
        graph_dir / f"{graph_id}.json",
        {
            "id": graph_id,
            "conversation_id": first_id,
            "resolution_id": approved["id"],
            "version": 1,
            "status": "planned",
            "lanes": [
                {
                    "feature_id": "lane-a",
                    "prompt": "large lane prompt belongs behind a link",
                    "depends_on": [],
                    "capabilities": ["code"],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-a", "status": "pending"},
                {"feature_id": "other-lane", "status": "done"},
            ]
        },
    )

    response = client.get(f"/api/chat/conversations/{first_id}/messages")

    assert response.status_code == 200
    payload = response.json()
    assert [message["content"] for message in payload["messages"]] == [
        "Plan the chat frontdoor."
    ]
    assert [item["kind"] for item in payload["items"]] == [
        "message",
        "card",
        "card",
        "card",
        "card",
        "card",
    ]

    cards = payload["cards"]
    card_types = {card["card_type"] for card in cards}
    assert card_types == {
        "proposal",
        "mission_blueprint",
        "lane_graph",
        "health_summary",
        "worklist_summary",
    }
    proposal_card = next(card for card in cards if card["card_type"] == "proposal")
    assert proposal_card["source_id"] == proposal["id"]
    assert proposal_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first_id}#proposal-{proposal['id']}"
    )
    assert proposal_card["api_href"] == f"/api/chat/proposals/{proposal['id']}"
    assert proposal_card["summary"] == "Build frontdoor cards"
    assert proposal_card["counts"] == {"references": 1, "lanes": 1}
    assert "lanes" not in proposal_card
    assert "evidence_bundle" not in proposal_card

    blueprint_card = next(card for card in cards if card["card_type"] == "mission_blueprint")
    assert blueprint_card["source_id"] == approved["id"]
    assert blueprint_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first_id}#resolution-{approved['id']}"
    )
    assert blueprint_card["api_href"] == f"/api/chat/resolutions/{approved['id']}"
    assert blueprint_card["title"] == "Chat-first mission"
    assert blueprint_card["counts"] == {"acceptance_criteria": 1, "references": 1}
    assert "body" not in blueprint_card

    graph_card = next(card for card in cards if card["card_type"] == "lane_graph")
    assert graph_card["source_id"] == graph_id
    assert graph_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first_id}#lane-graph-{graph_id}"
    )
    assert graph_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{first_id}/lane-graphs/{graph_id}"
    )
    assert graph_card["counts"] == {"lanes": 1}
    assert "lanes" not in graph_card

    health_card = next(card for card in cards if card["card_type"] == "health_summary")
    assert health_card["source_id"] == "run_health"
    assert health_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first_id}#run-health"
    )
    assert health_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{first_id}/run-health"
    )
    assert health_card["counts"] == {
        "live": 0,
        "stale": 0,
        "retrying": 0,
        "blocked": 0,
        "infra_failed": 0,
        "terminal": 0,
        "degraded_fallback": 0,
        "required_peer_failures": 0,
        "takeover_context_needed": 0,
    }

    worklist_card = next(card for card in cards if card["card_type"] == "worklist_summary")
    assert worklist_card["counts"]["ready_lanes"] == 1
    assert worklist_card["counts"]["terminal_lanes"] == 0
    assert "prompt" not in json.dumps(worklist_card)

    other_response = client.get(f"/api/chat/conversations/{second_id}/messages")
    assert other_response.status_code == 200
    other_payload = other_response.json()
    assert [item["kind"] for item in other_payload["items"]] == ["message", "card"]
    assert [card["card_type"] for card in other_payload["cards"]] == ["worklist_summary"]
    assert other_payload["cards"][0]["counts"] == {
        "unread_inbox": 1,
        "claimed_inbox": 0,
        "ready_lanes": 0,
        "under_review_lanes": 0,
        "failed_lanes": 0,
        "terminal_lanes": 0,
    }
    assert "lane-a" not in json.dumps(other_payload)
    assert "frontdoor-graph-v1" not in json.dumps(other_payload)


def test_chat_messages_endpoint_exposes_conversation_scoped_compatibility_summary(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    first_message = client.post(
        f"/api/chat/conversations/{first['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Keep natural messages next to compact cards.",
        },
    ).json()
    client.post(
        f"/api/chat/conversations/{second['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Do not leak beta data.",
        },
    )
    first_proposal = client.post(
        f"/api/chat/conversations/{first['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane_graph",
            "content": (
                '{"summary":"Alpha compact drill-down","lanes":[{"feature_id":"alpha-lane"}]}'
            ),
            "references": [first_message["id"]],
        },
    ).json()
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "alpha-lane",
                    "conversation_id": first["id"],
                    "status": "pending",
                },
                {
                    "feature_id": "beta-lane",
                    "conversation_id": second["id"],
                    "status": "merged",
                },
            ]
        },
    )

    response = client.get(f"/api/chat/conversations/{first['id']}/messages")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == first["id"]
    assert payload["conversation_id"] == first["id"]
    assert payload["title"] == "mission-alpha"
    assert payload["href"] == f"/dashboard/peer-chat/conversations/{first['id']}"
    assert payload["dashboard_href"] == payload["href"]
    assert payload["api_href"] == f"/api/chat/conversations/{first['id']}/messages"
    assert payload["participants"]["total"] == 3
    assert payload["inbox_counts"] == {"unread": 1, "claimed": 0}
    assert [message["id"] for message in payload["recent_messages"]] == [first_message["id"]]
    assert payload["card_counts"] == {
        "proposal": 1,
        "worklist_summary": 1,
        "health_summary": 1,
        "total": 3,
    }
    assert {card["source_id"] for card in payload["recent_cards"]} == {
        first_proposal["id"],
        "run_health",
        "worklist",
    }
    assert payload["recent_cards"] == payload["cards"][-5:]
    assert all(card["conversation_id"] == first["id"] for card in payload["recent_cards"])
    assert all(card["href"] and card["api_href"] for card in payload["recent_cards"])
    assert [item["kind"] for item in payload["items"]] == [
        "message",
        "card",
        "card",
        "card",
    ]
    encoded = json.dumps(payload)
    assert "beta-lane" not in encoded
    assert "mission-beta" not in encoded


def test_chat_messages_include_compact_feature_graph_set_card(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    client.post(
        f"/api/chat/conversations/{first['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Show the feature graph-set without dumping graph JSON.",
        },
    )

    graph_dir = tmp_path / "lane_graphs"
    _write_json(
        graph_dir / "alpha-feature-graph-set.json",
        {
            "id": "alpha-feature-graph-set",
            "feature_plan": {
                "id": "plan-alpha",
                "conversation_id": first["id"],
                "resolution_id": "res-alpha",
                "version": 1,
                "features": [
                    {
                        "feature_id": "schema",
                        "title": "Schema",
                        "goal": "Add schema.",
                        "acceptance_criteria": ["Schema validates."],
                        "graph_id": "graph-schema",
                    },
                    {
                        "feature_id": "projection",
                        "title": "Projection",
                        "goal": "Project lanes.",
                        "acceptance_criteria": ["Projection is safe."],
                        "dependencies": ["schema"],
                        "graph_id": "graph-projection",
                    },
                ],
            },
            "graphs": [
                {
                    "id": "graph-schema",
                    "conversation_id": first["id"],
                    "resolution_id": "res-alpha",
                    "version": 1,
                    "lanes": [
                        {
                            "feature_id": "schema-root",
                            "prompt": "large prompt stays behind the drill-down",
                        }
                    ],
                },
                {
                    "id": "graph-projection",
                    "conversation_id": first["id"],
                    "resolution_id": "res-alpha",
                    "version": 1,
                    "lanes": [
                        {
                            "feature_id": "projection-root",
                            "prompt": "another large prompt",
                        }
                    ],
                },
            ],
        },
    )
    _write_json(
        graph_dir / "beta-feature-graph-set.json",
        {
            "id": "beta-feature-graph-set",
            "feature_plan": {
                "id": "plan-beta",
                "conversation_id": second["id"],
                "resolution_id": "res-beta",
                "version": 1,
                "features": [
                    {
                        "feature_id": "beta",
                        "title": "Beta",
                        "goal": "Other conversation.",
                        "acceptance_criteria": ["Stay isolated."],
                        "graph_id": "graph-beta",
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-beta",
                    "conversation_id": second["id"],
                    "resolution_id": "res-beta",
                    "version": 1,
                    "lanes": [{"feature_id": "beta-root", "prompt": "do not leak"}],
                }
            ],
        },
    )
    (graph_dir / "malformed-runtime-snapshot.json").write_text("{", encoding="utf-8")
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "schema-root", "graph_id": "graph-schema", "status": "merged"},
                {
                    "feature_id": "projection-root",
                    "graph_id": "graph-projection",
                    "status": "pending",
                },
            ]
        },
    )

    response = client.get(f"/api/chat/conversations/{first['id']}/messages")

    assert response.status_code == 200
    cards = response.json()["cards"]
    graph_set_card = next(
        card for card in cards if card["card_type"] == "feature_graph_set"
    )
    assert graph_set_card["source_id"] == "alpha-feature-graph-set"
    assert graph_set_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first['id']}"
        "#feature-graph-set-alpha-feature-graph-set"
    )
    assert graph_set_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{first['id']}"
        "/feature-graph-sets/alpha-feature-graph-set"
    )
    assert graph_set_card["counts"] == {
        "features": 2,
        "lane_graphs": 2,
        "projected_features": 2,
        "terminal_features": 1,
    }
    compact_payload = json.dumps(graph_set_card)
    assert "lanes" not in compact_payload
    assert "prompt" not in compact_payload
    assert "beta" not in compact_payload
    assert all(card["source_id"] != "beta-feature-graph-set" for card in cards)


def test_chat_messages_include_conversation_scoped_feature_plan_card(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    client.post(
        f"/api/chat/conversations/{first['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "Show the feature plan contract in the chat timeline.",
        },
    )

    graph_dir = tmp_path / "lane_graphs"
    _write_json(
        graph_dir / "alpha-feature-graph-set.json",
        {
            "id": "alpha-feature-graph-set",
            "feature_plan": {
                "id": "plan-alpha",
                "conversation_id": first["id"],
                "resolution_id": "res-alpha",
                "version": 2,
                "features": [
                    {
                        "feature_id": "schema",
                        "title": "Schema",
                        "goal": "Add schema.",
                        "acceptance_criteria": ["Schema validates."],
                        "graph_id": "graph-schema",
                    },
                    {
                        "feature_id": "projection",
                        "title": "Projection",
                        "goal": "Project lanes.",
                        "acceptance_criteria": ["Projection is safe."],
                        "dependencies": ["schema"],
                        "graph_id": "graph-projection",
                    },
                ],
            },
            "graphs": [
                {
                    "id": "graph-schema",
                    "conversation_id": first["id"],
                    "resolution_id": "res-alpha",
                    "version": 2,
                    "lanes": [{"feature_id": "schema-root", "prompt": "large prompt"}],
                },
                {
                    "id": "graph-projection",
                    "conversation_id": first["id"],
                    "resolution_id": "res-alpha",
                    "version": 2,
                    "lanes": [{"feature_id": "projection-root", "prompt": "other large prompt"}],
                },
            ],
        },
    )
    _write_json(
        graph_dir / "beta-feature-graph-set.json",
        {
            "id": "beta-feature-graph-set",
            "feature_plan": {
                "id": "plan-beta",
                "conversation_id": second["id"],
                "resolution_id": "res-beta",
                "version": 1,
                "features": [
                    {
                        "feature_id": "beta",
                        "title": "Beta",
                        "goal": "Other conversation.",
                        "acceptance_criteria": ["Stay isolated."],
                        "graph_id": "graph-beta",
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-beta",
                    "conversation_id": second["id"],
                    "resolution_id": "res-beta",
                    "version": 1,
                    "lanes": [{"feature_id": "beta-root", "prompt": "do not leak"}],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "feature_plan_id": "plan-alpha",
                    "feature_plan_feature_id": "schema",
                    "graph_id": "graph-schema",
                    "status": "merged",
                },
                {
                    "feature_id": "projection-root",
                    "feature_plan_id": "plan-alpha",
                    "feature_plan_feature_id": "projection",
                    "graph_id": "graph-projection",
                    "status": "pending",
                },
            ]
        },
    )

    response = client.get(f"/api/chat/conversations/{first['id']}/messages")

    assert response.status_code == 200
    cards = response.json()["cards"]
    feature_plan_card = next(card for card in cards if card["card_type"] == "feature_plan")
    assert feature_plan_card["source_id"] == "plan-alpha"
    assert feature_plan_card["href"] == (
        "/dashboard/feature-graph-sets/alpha-feature-graph-set#feature-plan"
    )
    assert feature_plan_card["api_href"] == "/api/feature-graph-sets/alpha-feature-graph-set"
    assert feature_plan_card["counts"] == {
        "features": 2,
        "projected_features": 2,
        "terminal_features": 1,
    }
    compact_payload = json.dumps(feature_plan_card)
    assert "acceptance_criteria" not in compact_payload
    assert "large prompt" not in compact_payload
    assert "beta" not in compact_payload


def test_chat_messages_enrich_execution_cards_with_compact_drilldown_refs(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post("/api/chat/conversations", json={"title": "Mission"}).json()
    _seed_execution_card_drilldown_state(tmp_path, conversation["id"])
    ChatExecutionCardEmitter(tmp_path).emit_run_takeover(
        conversation_id=conversation["id"],
        planning_run_id="plan-run-001",
        lane_id="lane-001",
        takeover_reason="review_god_takeover",
        created_at="2026-05-31T12:00:00Z",
        summary="Review GOD takeover started.",
    )

    response = client.get(f"/api/chat/conversations/{conversation['id']}/messages")

    assert response.status_code == 200
    card = next(
        card for card in response.json()["cards"] if card["card_type"] == "run_takeover"
    )
    refs = {ref["ref_type"]: ref for ref in card["metadata"]["drilldown_refs"]}
    assert {
        "planning_run",
        "feature_plan",
        "graph_set",
        "runner_evidence",
        "takeover_evidence",
    } <= set(refs)
    assert refs["planning_run"]["api_href"] == "/api/planning-runs/plan-run-001"
    assert refs["feature_plan"]["api_href"] == "/api/feature-plans/feature-plan-001"
    assert refs["graph_set"]["api_href"] == "/api/feature-graph-sets/graph-set-001"
    assert refs["runner_evidence"]["api_href"] == (
        "/api/feature-graph-sets/graph-set-001/runner-evidence"
    )
    assert refs["takeover_evidence"]["api_href"] == (
        f"/api/lanes/lane-001/takeover-context?conversation_id={conversation['id']}"
    )


def test_chat_messages_include_worklist_summary_card_for_actionable_state(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    first_message = client.post(
        f"/api/chat/conversations/{first['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "@architect alpha needs a worklist summary.",
        },
    ).json()
    client.post(
        f"/api/chat/conversations/{second['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "beta has no actionable state.",
        },
    )
    ChatInboxStore(tmp_path / "chat.db").claim_next(owner="alpha-worker")
    client.post(
        f"/api/chat/conversations/{first['id']}/messages",
        json={
            "author": "human",
            "role": "human",
            "content": "@review alpha also needs review.",
        },
    )

    _write_json(
        tmp_path / "lane_graphs" / "alpha-graph.json",
        {
            "id": "alpha-graph",
            "conversation_id": first["id"],
            "version": 1,
            "lanes": [{"feature_id": "alpha-from-graph"}],
        },
    )
    _write_json(
        tmp_path / "lane_graphs" / "beta-graph.json",
        {
            "id": "beta-graph",
            "conversation_id": second["id"],
            "version": 1,
            "lanes": [{"feature_id": "beta-from-graph"}],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "alpha-ready", "conversation_id": first["id"], "status": "pending"},
                {"feature_id": "alpha-review", "graph_id": "alpha-graph", "status": "gated"},
                {
                    "feature_id": "alpha-failed",
                    "conversation_id": first["id"],
                    "status": "exec_failed",
                },
                {"feature_id": "alpha-done", "conversation_id": first["id"], "status": "merged"},
                {
                    "feature_id": "workspace-global",
                    "status": "gate_failed",
                    "gate_report": {"logs": ["do not embed"]},
                    "prompt": "do not embed",
                    "evidence_bundle": {"large": True},
                },
            ]
        },
    )

    response = client.get(f"/api/chat/conversations/{first['id']}/messages")

    assert response.status_code == 200
    payload = response.json()
    assert [item["kind"] for item in payload["items"]].count("message") == 2
    assert first_message["id"] in [message["id"] for message in payload["messages"]]
    worklist_card = next(
        card for card in payload["cards"] if card["card_type"] == "worklist_summary"
    )
    assert worklist_card["href"] == f"/dashboard/peer-chat/conversations/{first['id']}#worklist"
    assert worklist_card["api_href"] == f"/api/chat/conversations/{first['id']}/messages"
    assert worklist_card["counts"] == {
        "unread_inbox": 1,
        "claimed_inbox": 1,
        "ready_lanes": 1,
        "under_review_lanes": 1,
        "failed_lanes": 1,
        "terminal_lanes": 2,
    }
    compact_payload = json.dumps(worklist_card)
    assert "prompt" not in compact_payload
    assert "gate_report" not in compact_payload
    assert "evidence_bundle" not in compact_payload

    second_response = client.get(f"/api/chat/conversations/{second['id']}/messages")

    assert second_response.status_code == 200
    second_worklist = next(
        card for card in second_response.json()["cards"]
        if card["card_type"] == "worklist_summary"
    )
    assert second_worklist["counts"] == {
        "unread_inbox": 1,
        "claimed_inbox": 0,
        "ready_lanes": 0,
        "under_review_lanes": 0,
        "failed_lanes": 0,
        "terminal_lanes": 0,
    }


def test_chat_health_card_uses_compact_operator_health_counts_for_scoped_lanes(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()

    client.post(
        f"/api/chat/conversations/{first['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane_graph",
            "content": '{"summary":"Alpha lanes","lanes":[]}',
            "references": [],
        },
    )
    client.post(
        f"/api/chat/conversations/{second['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "lane_graph",
            "content": '{"summary":"Beta lanes","lanes":[]}',
            "references": [],
        },
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "alpha-live",
                    "conversation_id": first["id"],
                    "status": "dispatched",
                },
                {
                    "feature_id": "alpha-stale",
                    "conversation_id": first["id"],
                    "status": "dispatched",
                    "dispatched_at": 1,
                },
                {
                    "feature_id": "alpha-retrying",
                    "conversation_id": first["id"],
                    "status": "pending",
                    "retry_count": 1,
                },
                {
                    "feature_id": "alpha-blocked",
                    "conversation_id": first["id"],
                    "status": "awaiting_final_action",
                },
                {
                    "feature_id": "alpha-infra",
                    "conversation_id": first["id"],
                    "status": "pending",
                    "failure_reason": "execution_infra_unavailable",
                },
                {
                    "feature_id": "alpha-terminal",
                    "conversation_id": first["id"],
                    "status": "merged",
                },
                {
                    "feature_id": "alpha-peer-fallback",
                    "conversation_id": first["id"],
                    "status": "reviewed",
                    "peer_delivery_mode": "one_shot_fallback",
                    "peer_degraded_reason": "receive_timeout",
                },
                {
                    "feature_id": "alpha-required-peer",
                    "conversation_id": first["id"],
                    "status": "gate_failed",
                    "failure_reason": "required_review_peer_unavailable",
                    "peer_delivery_mode": "required_peer_failed",
                    "peer_degraded_reason": "ensure_failed",
                },
                {
                    "feature_id": "alpha-takeover",
                    "conversation_id": first["id"],
                    "status": "reworking",
                    "retry_count": 1,
                    "review_fallback_reason": "reproduced_finding",
                },
                {
                    "feature_id": "beta-noise",
                    "conversation_id": second["id"],
                    "status": "merged",
                    "failure_reason": "execution_infra_unavailable",
                },
                {
                    "feature_id": "workspace-global",
                    "status": "gate_failed",
                },
            ]
        },
    )

    response = client.get(f"/api/chat/conversations/{first['id']}/messages")

    assert response.status_code == 200
    health_card = next(
        card for card in response.json()["cards"] if card["card_type"] == "health_summary"
    )
    assert health_card["counts"] == {
        "live": 3,
        "stale": 1,
        "retrying": 2,
        "blocked": 1,
        "infra_failed": 1,
        "terminal": 2,
        "degraded_fallback": 2,
        "required_peer_failures": 1,
        "takeover_context_needed": 4,
    }
    assert health_card["metadata"] == {
        "peer_delivery_modes": {
            "one_shot_fallback": 1,
            "required_peer_failed": 1,
        }
    }
    assert health_card["source_id"] == "run_health"
    assert health_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first['id']}#run-health"
    )
    assert health_card["api_href"] == (
        f"/api/dashboard/peer-chat/conversations/{first['id']}/run-health"
    )
    assert "total" not in health_card["counts"]
    assert "alpha-live" not in json.dumps(health_card)
    assert "alpha-peer-fallback" not in json.dumps(health_card)
    assert "alpha-required-peer" not in json.dumps(health_card)
    assert "alpha-takeover" not in json.dumps(health_card)
    assert "beta-noise" not in json.dumps(health_card)


def test_chat_api_health_reports_runtime_state_files(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "xmuse-chat-api",
        "chat_db": {
            "path": str(tmp_path / "chat.db"),
            "exists": True,
        },
        "role_templates": "ready",
    }


def test_chat_api_surfaces_peer_request_result_cards_scoped_by_conversation(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    first = client.post("/api/chat/conversations", json={"title": "mission-alpha"}).json()
    second = client.post("/api/chat/conversations", json={"title": "mission-beta"}).json()
    first_review = next(
        participant
        for participant in first["participants"]
        if participant["role"] == "review"
    )
    second_review = next(
        participant
        for participant in second["participants"]
        if participant["role"] == "review"
    )
    first_execute = next(
        participant
        for participant in first["participants"]
        if participant["role"] == "execute"
    )

    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-alpha-review",
                    "conversation_id": first["id"],
                    "participant_id": first_review["participant_id"],
                    "role": "review",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                    "feature_scope_id": "feature-alpha",
                    "status": "running",
                    "prompt_fingerprint": "sha256:do-not-embed",
                    "worktree": "/tmp/large/worktree/ref",
                },
                {
                    "god_session_id": "god-beta-review",
                    "conversation_id": second["id"],
                    "participant_id": second_review["participant_id"],
                    "role": "review",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                    "feature_scope_id": "feature-beta",
                    "status": "running",
                },
                {
                    "god_session_id": "god-alpha-execute",
                    "conversation_id": first["id"],
                    "participant_id": first_execute["participant_id"],
                    "role": "execute",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                    "feature_scope_id": "feature-alpha",
                    "status": "running",
                },
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
                    "graph_id": "graph-alpha",
                    "conversation_id": first["id"],
                    "status": "reviewed",
                    "review_peer_id": first_review["participant_id"],
                    "peer_request_id": "req-alpha-review",
                    "peer_delivery_mode": "configured_peer",
                    "peer_routing_mode": "preferred",
                    "updated_at": "2026-05-31T09:00:00Z",
                    "prompt": "large peer prompt belongs behind dashboard drill-down",
                    "review_result": {"raw": "large peer result belongs behind drill-down"},
                },
                {
                    "feature_id": "lane-beta",
                    "feature_plan_feature_id": "feature-beta",
                    "conversation_id": second["id"],
                    "status": "gate_failed",
                    "review_peer_id": second_review["participant_id"],
                    "peer_request_id": "req-beta-review",
                    "peer_delivery_mode": "required_peer_failed",
                    "peer_degraded_reason": "review_peer_role_mismatch",
                    "updated_at": "2026-05-31T09:05:00Z",
                },
                {
                    "feature_id": "lane-alpha-execute-in-flight",
                    "feature_plan_feature_id": "feature-alpha",
                    "conversation_id": first["id"],
                    "status": "dispatched",
                    "execute_peer_id": first_execute["participant_id"],
                    "execute_peer_request_id": "req-alpha-execute",
                    "execute_peer_delivery_mode": "configured_peer",
                    "execute_peer_routing_mode": "preferred",
                    "updated_at": "2026-05-31T09:10:00Z",
                },
            ]
        },
    )

    timeline_response = client.get(f"/api/chat/conversations/{first['id']}/messages")
    conversations_response = client.get("/api/chat/conversations")
    second_timeline_response = client.get(f"/api/chat/conversations/{second['id']}/messages")

    assert timeline_response.status_code == 200
    assert conversations_response.status_code == 200
    assert second_timeline_response.status_code == 200

    cards = timeline_response.json()["cards"]
    request_card = next(card for card in cards if card["card_type"] == "peer_request")
    result_card = next(card for card in cards if card["card_type"] == "peer_result")

    assert request_card["source_id"] == "req-alpha-review"
    assert request_card["status"] == "sent"
    assert request_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first['id']}#peer-request-req-alpha-review"
    )
    assert request_card["api_href"] == "/api/peer-requests/req-alpha-review"
    assert request_card["metadata"] == {
        "request_id": "req-alpha-review",
        "message_type": "review",
        "participant_id": first_review["participant_id"],
        "god_session_id": "god-alpha-review",
        "role": "review",
        "cli_kind": "codex",
        "runtime": "codex",
        "model": "gpt-5.5",
        "feature_scope_id": "feature-alpha",
        "lane_id": "lane-alpha",
        "feature_id": "feature-alpha",
        "graph_id": "graph-alpha",
    }
    assert request_card["counts"] == {"lane_refs": 1, "feature_refs": 1}

    assert result_card["source_id"] == "req-alpha-review"
    assert result_card["status"] == "completed"
    assert result_card["href"] == (
        f"/dashboard/peer-chat/conversations/{first['id']}#peer-result-req-alpha-review"
    )
    assert result_card["api_href"] == "/api/peer-requests/req-alpha-review/result"
    assert result_card["metadata"]["result_status"] == "ok"
    assert result_card["metadata"]["lane_id"] == "lane-alpha"
    assert any(
        card["card_type"] == "peer_request" and card["source_id"] == "req-alpha-execute"
        for card in cards
    )
    assert not any(
        card["card_type"] == "peer_result" and card["source_id"] == "req-alpha-execute"
        for card in cards
    )

    encoded = json.dumps(cards)
    assert "large peer prompt" not in encoded
    assert "large peer result" not in encoded
    assert "prompt_fingerprint" not in encoded
    assert "/tmp/large/worktree/ref" not in encoded
    assert "req-beta-review" not in encoded

    first_conversation = next(
        conversation
        for conversation in conversations_response.json()["conversations"]
        if conversation["id"] == first["id"]
    )
    assert first_conversation["card_counts"]["peer_request"] == 2
    assert first_conversation["card_counts"]["peer_result"] == 1
    assert "req-alpha-review" in json.dumps(first_conversation["recent_cards"])
    assert "req-beta-review" not in json.dumps(first_conversation)

    second_cards = second_timeline_response.json()["cards"]
    second_peer_source_ids = {
        card["source_id"]
        for card in second_cards
        if card["card_type"].startswith("peer_")
    }
    assert second_peer_source_ids == {
        "req-beta-review"
    }
    second_result = next(card for card in second_cards if card["card_type"] == "peer_result")
    assert second_result["status"] == "failed"
    assert second_result["metadata"]["reason"] == "review_peer_role_mismatch"


def test_chat_api_creates_forked_peer_participant_session_and_lineage_reads(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "fork-contracts"},
    ).json()
    source = conversation["participants"][0]
    source_session = GodSessionRegistry(
        tmp_path / "god_sessions.json"
    ).find_by_conversation_participant(
        conversation["id"],
        source["participant_id"],
    )
    baseline_lineage = client.get(
        f"/api/chat/conversations/{conversation['id']}/forks"
    ).json()["lineage"]

    create_response = client.post(
        f"/api/chat/conversations/{conversation['id']}/forks",
        json={
            "source_peer_id": source["participant_id"],
            "role": "review",
            "display_name": "Review Child",
            "model": "gpt-5.5",
            "prompt_delta": "Add evidence review rigor.",
            "inherited_refs": [" docs/spec.md ", "memory://conversation/bootstrap"],
            "model_policy": {"runtime": "codex", "review_model": "gpt-5.5"},
            "feature_scope_id": " feature-alpha ",
            "fork_reason": " specialize review ",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["participant"]["conversation_id"] == conversation["id"]
    assert created["participant"]["role"] == "review"
    assert created["participant"]["display_name"] == "Review Child"
    assert created["participant"]["provider_id"] == "codex"
    assert created["participant"]["profile_id"] == "review"
    assert created["session"]["conversation_id"] == conversation["id"]
    assert created["session"]["participant_id"] == created["participant"]["participant_id"]
    assert created["session"]["provider_id"] == "codex"
    assert created["session"]["profile_id"] == "review"
    assert created["session"]["feature_scope_id"] == "feature-alpha"
    assert created["lineage"]["source_peer_id"] == source["participant_id"]
    assert created["lineage"]["source_god_session_id"] == source_session.god_session_id
    assert created["lineage"]["new_peer_id"] == created["participant"]["participant_id"]
    assert created["lineage"]["new_god_session_id"] == created["session"]["god_session_id"]
    assert created["lineage"]["fork_reason"] == "specialize review"

    participants_response = client.get(
        f"/api/chat/conversations/{conversation['id']}/participants"
    )

    assert participants_response.status_code == 200
    participants_payload = participants_response.json()
    assert participants_payload["lineage"] == [*baseline_lineage, created["lineage"]]
    forked = next(
        participant
        for participant in participants_payload["participants"]
        if participant["participant_id"] == created["participant"]["participant_id"]
    )
    assert forked["session"]["god_session_id"] == created["session"]["god_session_id"]
    assert forked["session"]["provider_id"] == "codex"
    assert forked["session"]["profile_id"] == "review"
    assert forked["session"]["feature_scope_id"] == "feature-alpha"

    lineage_response = client.get(
        f"/api/chat/conversations/{conversation['id']}/forks"
    )

    assert lineage_response.status_code == 200
    assert lineage_response.json() == {
        "conversation_id": conversation["id"],
        "lineage": [*baseline_lineage, created["lineage"]],
    }


def test_chat_api_rejects_invalid_fork_contract_without_side_effects(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "fork-contracts"},
    ).json()
    source = conversation["participants"][0]
    baseline_sessions = GodSessionRegistry(tmp_path / "god_sessions.json").list()
    baseline_lineage = client.get(
        f"/api/chat/conversations/{conversation['id']}/forks"
    ).json()["lineage"]

    create_response = client.post(
        f"/api/chat/conversations/{conversation['id']}/forks",
        json={
            "source_peer_id": source["participant_id"],
            "role": "review",
            "display_name": "Broken Review Child",
            "model": "gpt-5.5",
            "prompt_delta": "Add evidence review rigor.",
            "inherited_refs": ["docs/spec.md"],
            "model_policy": {},
            "fork_reason": "specialize review",
        },
    )

    assert create_response.status_code == 400
    assert "model_policy must declare model_policy_runtime" in create_response.json()[
        "detail"
    ]

    participants_response = client.get(
        f"/api/chat/conversations/{conversation['id']}/participants"
    )

    assert participants_response.status_code == 200
    participants_payload = participants_response.json()
    assert len(participants_payload["participants"]) == 3
    assert participants_payload["lineage"] == baseline_lineage
    assert sum(
        participant["session"] is not None
        for participant in participants_payload["participants"]
    ) == 3
    assert GodSessionRegistry(tmp_path / "god_sessions.json").list() == baseline_sessions

    lineage_response = client.get(
        f"/api/chat/conversations/{conversation['id']}/forks"
    )

    assert lineage_response.status_code == 200
    assert lineage_response.json() == {
        "conversation_id": conversation["id"],
        "lineage": baseline_lineage,
    }


def test_chat_api_rejects_cross_conversation_fork_contamination_without_side_effects(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    alpha = client.post(
        "/api/chat/conversations",
        json={"title": "alpha-forks"},
    ).json()
    beta = client.post(
        "/api/chat/conversations",
        json={"title": "beta-forks"},
    ).json()
    alpha_source = alpha["participants"][0]
    beta_source = beta["participants"][0]
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    baseline_sessions = registry.list()
    alpha_baseline_lineage = client.get(
        f"/api/chat/conversations/{alpha['id']}/forks"
    ).json()["lineage"]
    beta_baseline_lineage = client.get(
        f"/api/chat/conversations/{beta['id']}/forks"
    ).json()["lineage"]

    foreign_peer_response = client.post(
        f"/api/chat/conversations/{alpha['id']}/forks",
        json={
            "source_peer_id": beta_source["participant_id"],
            "role": "review",
            "display_name": "Foreign Review Child",
            "model": "gpt-5.5",
            "prompt_delta": "Review alpha with beta context.",
            "inherited_refs": ["docs/spec.md"],
            "model_policy": {"runtime": "codex", "review_model": "gpt-5.5"},
            "feature_scope_id": "feature-alpha",
            "fork_reason": "attempt cross-workspace reuse",
        },
    )

    assert foreign_peer_response.status_code == 400
    assert foreign_peer_response.json()["detail"]["code"] == "unknown_source_peer"

    foreign_memory_ref_response = client.post(
        f"/api/chat/conversations/{alpha['id']}/forks",
        json={
            "source_peer_id": alpha_source["participant_id"],
            "role": "review",
            "display_name": "Foreign Memory Child",
            "model": "gpt-5.5",
            "prompt_delta": "Reuse another workspace memory.",
            "inherited_refs": [f"memory://conversation/{beta['id']}/bootstrap"],
            "model_policy": {"runtime": "codex", "review_model": "gpt-5.5"},
            "feature_scope_id": "feature-alpha",
            "fork_reason": "attempt foreign memory ref",
        },
    )

    assert foreign_memory_ref_response.status_code == 400
    assert "memory refs must stay within the conversation" in (
        foreign_memory_ref_response.json()["detail"]
    )

    alpha_participants = client.get(
        f"/api/chat/conversations/{alpha['id']}/participants"
    ).json()
    beta_participants = client.get(
        f"/api/chat/conversations/{beta['id']}/participants"
    ).json()
    alpha_forks = client.get(f"/api/chat/conversations/{alpha['id']}/forks").json()
    beta_forks = client.get(f"/api/chat/conversations/{beta['id']}/forks").json()

    assert len(alpha_participants["participants"]) == 3
    assert len(beta_participants["participants"]) == 3
    assert alpha_participants["lineage"] == alpha_baseline_lineage
    assert beta_participants["lineage"] == beta_baseline_lineage
    assert alpha_forks == {
        "conversation_id": alpha["id"],
        "lineage": alpha_baseline_lineage,
    }
    assert beta_forks == {
        "conversation_id": beta["id"],
        "lineage": beta_baseline_lineage,
    }
    assert registry.list() == baseline_sessions
