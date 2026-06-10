"""Tests for GET /api/health endpoint."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.run_health import build_process_inventory

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "dashboard_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("xmuse_dashboard_api_health", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_app = _load_module().create_app


def test_health_returns_ok_and_version(tmp_path):
    client = TestClient(create_app(base_dir=tmp_path))
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["graph_authority"]["merge_state"] == "unknown"
    assert body["graph_authority"]["lineage_status"] == "unknown"


def test_run_health_returns_read_only_operational_model(tmp_path, monkeypatch):
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "live-worker",
                "status": "gated",
                "review_started_at": 9999999999.0,
            },
            {
                "feature_id": "terminal-retry-history",
                "status": "failed",
                "retry_count": 3,
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[111, 222], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/run-health")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["live"] == 1
    assert body["counts"]["terminal"] == 1
    assert body["groups"]["retrying"] == []
    assert body["scope"] == {
        "kind": "global",
        "conversation_id": None,
        "workspace_id": None,
    }
    assert body["processes"]["runner_count"] == 2
    assert body["processes"]["mcp_count"] == 0
    assert body["warnings"][0]["code"] == "duplicate_runner_processes"
    assert body["warnings"][1]["code"] == "missing_mcp_process"
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_run_health_exposes_review_rework_alignment_summary(tmp_path, monkeypatch):
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "semantic-rework",
                "status": "reworking",
                "retry_count": 1,
                "review_fallback_reason": "reproduced_finding",
            },
            {
                "feature_id": "old-terminal-retry",
                "status": "failed",
                "retry_count": 4,
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/run-health")

    assert response.status_code == 200
    body = response.json()
    alignment = body["review_rework_alignment"]
    assert alignment["counts_by_category"]["semantic_rework"] == 1
    assert alignment["counts_by_category"]["unknown"] == 1
    assert alignment["current_active_retry_or_rework"] == ["semantic-rework"]
    assert alignment["historical_terminal_retry_metadata"] == ["old-terminal-retry"]
    assert alignment["operator_attention_samples"][0]["lane_id"] == "semantic-rework"
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_dashboard_dead_letters_returns_read_only_coordinator_incidents(
    tmp_path,
    monkeypatch,
):
    incidents_path = tmp_path / "coordinator_incidents.jsonl"
    incidents_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "dead_letter",
                        "incident_id": "dl-older",
                        "source_event_ref": "event:evt_old",
                        "consumer": "dashboard",
                        "attempt_count": 3,
                        "last_error": "old schema mismatch",
                        "updated_at": "2026-06-02T00:01:00Z",
                    }
                ),
                json.dumps(
                    {
                        "kind": "degraded",
                        "incident_id": "deg-latest",
                        "source_event_ref": "event:evt_graph_set_ready",
                        "consumer": "read-model-materializer",
                        "attempt_count": 1,
                        "last_error": "graph set artifact temporarily missing",
                        "updated_at": "2026-06-02T00:02:00Z",
                    }
                ),
                json.dumps(
                    {
                        "kind": "dead_letter",
                        "incident_id": "dl-latest",
                        "source_event_ref": "event:evt_lane_updated",
                        "consumer": "dashboard",
                        "attempt_count": 5,
                        "last_error": "state guard mismatch",
                        "updated_at": "2026-06-02T00:03:00Z",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "feature_lanes.json").write_text(
        json.dumps({"lanes": []}),
        encoding="utf-8",
    )
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/dashboard/dead-letters")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "dashboard_dead_letters"
    assert body["read_only"] is True
    assert body["source_authority"] == "coordinator_incidents"
    assert body["degraded"] is True
    assert body["counts"] == {"dead_letter": 2, "degraded": 1, "lifecycle": 0}
    assert [item["incident_id"] for item in body["latest_dead_letters"]] == [
        "dl-latest",
        "dl-older",
    ]
    assert body["latest_degraded"][0]["incident_id"] == "deg-latest"
    assert json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8")) == {
        "lanes": []
    }
    assert incidents_path.read_text(encoding="utf-8").count("\n") == 2


def test_dashboard_read_model_status_reports_degraded_models_without_materializing(
    tmp_path,
):
    read_models = tmp_path / "read_models"
    read_models.mkdir()
    (read_models / "resolutions.json").write_text(
        json.dumps({"resolutions": [{"id": "res-ok"}]}),
        encoding="utf-8",
    )
    (read_models / "verdicts.json").write_text("{not valid json", encoding="utf-8")
    client = TestClient(create_app(base_dir=tmp_path))

    response = client.get("/api/dashboard/read-models/status")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "read_model_status"
    assert body["read_only"] is True
    assert body["source_authority"] == "read_models_directory"
    assert body["degraded"] is True
    models = {item["name"]: item for item in body["models"]}
    assert models["resolutions"]["status"] == "ok"
    assert models["resolutions"]["item_count"] == 1
    assert models["verdicts"]["status"] == "invalid_json"
    assert models["self_evolution_audit"]["status"] == "missing"
    assert sorted(body["degraded_models"]) == [
        "self_evolution_audit",
        "self_evolution_clarifications",
        "self_evolution_conversations",
        "verdicts",
    ]
    assert not (read_models / "self_evolution_audit.json").exists()


def test_run_health_supports_workspace_scoped_filter(tmp_path, monkeypatch):
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "alpha-live",
                "conversation_id": "conv-alpha",
                "status": "gated",
                "review_started_at": 9999999999.0,
            },
            {
                "feature_id": "alpha-terminal",
                "conversation_id": "conv-alpha",
                "status": "merged",
            },
            {
                "feature_id": "beta-noise",
                "conversation_id": "conv-beta",
                "status": "awaiting_final_action",
            },
            {
                "feature_id": "workspace-global",
                "status": "exec_failed",
                "failure_reason": "execution_infra_unavailable",
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[111], mcp_pids=[222]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/run-health", params={"workspace_id": "conv-alpha"})

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {
        "kind": "conversation",
        "conversation_id": "conv-alpha",
        "workspace_id": "conv-alpha",
    }
    assert body["counts"]["live"] == 1
    assert body["counts"]["terminal"] == 1
    assert body["counts"]["blocked"] == 0
    assert body["counts"]["infra_failed"] == 0
    assert body["groups"]["live"] == ["alpha-live"]
    assert body["groups"]["terminal"] == ["alpha-terminal"]
    assert body["groups"]["blocked"] == []
    assert body["groups"]["infra_failed"] == []
    assert body["processes"]["runner_count"] == 1
    assert body["processes"]["mcp_count"] == 1
    assert "beta-noise" not in json.dumps(body)
    assert "workspace-global" not in json.dumps(body)
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_peer_chat_run_health_drilldown_separates_scoped_lanes_from_global_process_health(
    tmp_path,
    monkeypatch,
):
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Mission Alpha")
    chat.create_proposal(
        conversation_id=conversation.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"Alpha lanes","lanes":[]}',
        references=[],
    )
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "alpha-live",
                "conversation_id": conversation.id,
                "status": "reviewed",
            },
            {
                "feature_id": "beta-noise",
                "conversation_id": "conv-beta",
                "status": "merged",
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[333], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get(
        f"/api/dashboard/peer-chat/conversations/{conversation.id}/run-health"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == conversation.id
    assert body["run_health"]["scope"] == {
        "kind": "conversation",
        "conversation_id": conversation.id,
        "workspace_id": conversation.id,
    }
    assert body["run_health"]["counts"]["live"] == 1
    assert body["run_health"]["counts"]["terminal"] == 0
    assert body["run_health"]["groups"]["live"] == ["alpha-live"]
    assert body["run_health"]["groups"]["terminal"] == []
    assert body["run_health"]["processes"]["runner_count"] == 1
    assert body["run_health"]["processes"]["mcp_count"] == 0
    assert "beta-noise" not in json.dumps(body)
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_run_health_workspace_filter_ignores_foreign_and_ambiguous_graph_scopes(
    tmp_path,
    monkeypatch,
):
    chat = ChatStore(tmp_path / "chat.db")
    alpha = chat.create_conversation("Mission Alpha")
    beta = chat.create_conversation("Mission Beta")
    graph_dir = tmp_path / "lane_graphs"
    graph_dir.mkdir()
    (graph_dir / "alpha-graph.json").write_text(
        json.dumps(
            {
                "id": "alpha-graph",
                "conversation_id": alpha.id,
                "version": 1,
                "lanes": [{"feature_id": "shared-lane"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (graph_dir / "beta-graph.json").write_text(
        json.dumps(
            {
                "id": "beta-graph",
                "conversation_id": beta.id,
                "version": 1,
                "lanes": [{"feature_id": "shared-lane"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "shared-lane",
                "graph_id": "alpha-graph",
                "status": "merged",
            },
            {
                "feature_id": "shared-lane",
                "graph_id": "beta-graph",
                "status": "exec_failed",
                "failure_reason": "execution_infra_unavailable",
            },
            {
                "feature_id": "shared-lane",
                "status": "gate_failed",
                "failure_reason": "execution_infra_unavailable",
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/run-health", params={"workspace_id": alpha.id})

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {
        "kind": "conversation",
        "conversation_id": alpha.id,
        "workspace_id": alpha.id,
    }
    assert body["counts"]["terminal"] == 1
    assert body["counts"]["infra_failed"] == 0
    assert body["groups"]["terminal"] == ["shared-lane"]
    assert body["groups"]["infra_failed"] == []
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_run_health_conversation_filter_ignores_workspace_id_collision(
    tmp_path,
    monkeypatch,
):
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "conversation-lane",
                "conversation_id": "conv-alpha",
                "status": "merged",
            },
            {
                "feature_id": "workspace-collision",
                "conversation_id": "conv-beta",
                "workspace_id": "conv-alpha",
                "status": "exec_failed",
                "failure_reason": "execution_infra_unavailable",
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/run-health", params={"conversation_id": "conv-alpha"})

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["terminal"] == 1
    assert body["counts"]["infra_failed"] == 0
    assert body["groups"]["terminal"] == ["conversation-lane"]
    assert "workspace-collision" not in json.dumps(body)
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_health_includes_read_only_run_health_peer_delivery_model(
    tmp_path,
    monkeypatch,
):
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "fallback-review",
                "status": "reviewed",
                "peer_delivery_mode": "one_shot_fallback",
                "peer_routing_mode": "preferred",
                "review_delivery_mode": "one_shot",
                "peer_degraded_reason": "peer_timeout",
            },
            {
                "feature_id": "required-peer-failed",
                "status": "gate_failed",
                "failure_reason": "review_peer_delivery_failed",
                "peer_delivery_mode": "required_peer_failed",
                "peer_routing_mode": "required",
                "review_peer_id": "peer-reviewer",
                "peer_request_id": "req-review",
                "persistent_review_degraded": True,
                "persistent_review_degraded_reason": "delivery_failed",
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    module = _load_module()
    monkeypatch.setattr(
        module,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )
    client = TestClient(module.create_app(base_dir=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    run_health = body["run_health"]
    assert run_health["groups"]["degraded_fallback"] == [
        "fallback-review",
        "required-peer-failed",
    ]
    assert run_health["peer_delivery"]["counts_by_delivery_mode"] == {
        "one_shot_fallback": 1,
        "required_peer_failed": 1,
    }
    assert run_health["peer_delivery"]["required_peer_failures"][0]["lane_id"] == (
        "required-peer-failed"
    )
    assert run_health["peer_delivery"]["persistent_review_degraded_reasons"] == {
        "delivery_failed": ["required-peer-failed"]
    }
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_lane_detail_exposes_lane_review_rework_alignment(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "approved-artifact",
                        "status": "reworking",
                        "review_summary": "Review decision: no blocking findings",
                        "review_fallback_reason": "unknown_review_text",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(base_dir=tmp_path))

    response = client.get("/api/lanes/approved-artifact")

    assert response.status_code == 200
    body = response.json()
    assert body["lane"]["review_rework_alignment"] == {
        "lane_id": "approved-artifact",
        "status": "reworking",
        "reason_category": "approved_review",
        "retry_count": 0,
        "review_retry_count": 0,
        "fallback_reason": "unknown_review_text",
        "primary_evidence_refs": ["lane.review_summary"],
    }
