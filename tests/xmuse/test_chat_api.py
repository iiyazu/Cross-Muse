import importlib.util
import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.chat.inbox_store import ChatInboxStore
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
