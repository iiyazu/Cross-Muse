import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse_core.providers.models import (
    ProviderId,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)
from xmuse_core.providers.selection_record import (
    ProviderSelectionRecord,
    ProviderSelectionRecordStore,
)

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "dashboard_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("xmuse_dashboard_api", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dashboard_api = _load_module()
create_app = dashboard_api.create_app


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(base_dir=tmp_path))


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "xmuse@example.test")
    _git(path, "config", "user.name", "xmuse test")


def _runtime_inventory() -> dict[str, object]:
    return {
        "runner_pids": [101],
        "mcp_pids": [201],
        "services": [
            {"service": "runner", "pids": [101]},
            {"service": "mcp", "pids": [201]},
        ],
        "counts_by_service": {
            "runner": 1,
            "mcp": 1,
        },
        "warnings": [],
        "evidence": {"hard": [], "degraded": []},
    }


def test_list_lanes_returns_status_for_every_lane(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "done-lane", "status": "done", "prompt": "ship it"},
                {"feature_id": "new-lane", "prompt": "build it"},
            ]
        },
    )

    response = _client(tmp_path).get("/api/lanes")

    assert response.status_code == 200
    lanes = response.json()["lanes"]
    assert lanes[0]["feature_id"] == "done-lane"
    assert lanes[0]["status"] == "done"
    assert lanes[0]["effective_status"] == "merged"
    assert lanes[0]["prompt"] == "ship it"
    assert lanes[1]["feature_id"] == "new-lane"
    assert lanes[1]["status"] == "pending"
    assert lanes[1]["effective_status"] == "ready"
    assert lanes[1]["prompt"] == "build it"


def test_tui_worklist_envelope_returns_compact_contract_and_runtime_refs(
    tmp_path,
    monkeypatch,
):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "projection_revision": 7,
            "lanes": [
                {
                    "feature_id": "lane-conv-a",
                    "lane_local_id": "T1-01-envelope-tests",
                    "plan_feature_id": "T1",
                    "feature_label": "Envelope Tests",
                    "status": "pending",
                    "priority": 3,
                    "lane_depends_on_ids": ["lane-root-a"],
                    "provider_profile_ref": "codex.worker",
                    "prompt_summary": "Stabilize the Textual worklist envelope.",
                    "conversation_id": "conv-a",
                    "workspace_id": "workspace-a",
                    "prompt": "raw prompt should stay out of the envelope",
                    "worker_command": ["codex", "exec"],
                },
                {
                    "feature_id": "lane-conv-b",
                    "lane_local_id": "T1-02-something-else",
                    "plan_feature_id": "T1",
                    "feature_label": "Other Lane",
                    "status": "merged",
                    "priority": 1,
                    "lane_depends_on_ids": [],
                    "provider_profile_ref": "opencode.deepseek_flash_worker",
                    "prompt_summary": "Other lane should be filtered out.",
                    "conversation_id": "conv-b",
                    "workspace_id": "workspace-b",
                },
            ],
        },
    )
    ProviderSelectionRecordStore.from_xmuse_root(tmp_path).append(
        ProviderSelectionRecord(
            lane_id="lane-conv-a",
            selected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Fallback to codex when OpenCode is unavailable.",
            peer_type="worker",
            fallback_cause="unavailable",
            health_failure_kind="unavailable",
            source_authority="provider_policy",
        )
    )
    monkeypatch.setattr(
        dashboard_api,
        "discover_xmuse_runtime_processes",
        lambda **_kwargs: _runtime_inventory(),
    )

    response = _client(tmp_path).get("/api/tui/worklist-envelope?conversation_id=conv-a")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "schema_version",
        "read_model_version",
        "source_authority",
        "projection_revision",
        "generated_at",
        "items",
        "run_health",
        "degraded",
        "stale",
        "provider_selection_refs",
        "degradation",
        "runtime_backend",
        "fallback_reason",
        "fallback",
        "graph_lineage",
        "debug_drilldown_refs",
        "debug_refs",
    }
    assert body["schema_version"] == "1"
    assert body["read_model_version"] == "1"
    assert body["source_authority"] == "feature_lanes_projection"
    assert body["projection_revision"] == 7
    assert body["generated_at"].endswith("Z")
    assert body["degraded"] is True
    assert body["stale"] is False
    assert body["provider_selection_refs"] == {
        "inventory": {
            "api_href": "/api/tui/provider-inventory",
            "label": "Provider inventory",
        },
        "records": {
            "api_href": "/api/tui/provider-selection-records",
            "label": "Provider selection records",
        },
    }
    assert body["degradation"] == {
        "degraded": True,
        "stale": False,
        "warning_codes": [],
        "reasons": ["provider fallback lanes present"],
    }
    assert body["runtime_backend"] == {
        "configured": "ray",
        "source_authority": "runtime_backend_config",
    }
    assert body["fallback_reason"] == "provider fallback lanes present"
    assert body["fallback"] == {
        "active": True,
        "count": 1,
        "lane_ids": ["lane-conv-a"],
        "reason": "provider fallback lanes present",
    }
    assert body["graph_lineage"] == {
        "degraded": False,
        "authoritative_graph_id": None,
        "checked_graph_ids": [],
        "mismatched_graph_ids": [],
        "missing_projection_lane_ids": [],
        "unexpected_projection_lane_ids": [],
        "warning_codes": [],
    }
    assert body["debug_drilldown_refs"] == body["debug_refs"]
    assert body["debug_refs"] == {
        "self": {
            "api_href": "/api/tui/worklist-envelope?conversation_id=conv-a",
            "label": "Worklist envelope",
        },
        "run_health": {
            "api_href": "/api/run-health?conversation_id=conv-a",
            "label": "Run health",
        },
        "lanes": {
            "api_href": "/api/lanes",
            "label": "Projected lanes",
        },
    }
    assert body["run_health"]["scope"] == {
        "kind": "conversation",
        "conversation_id": "conv-a",
        "workspace_id": "conv-a",
    }
    assert len(body["items"]) == 1
    assert body["items"][0] == {
        "lane_id": "lane-conv-a",
        "lane_local_id": "T1-01-envelope-tests",
        "plan_feature_id": "T1",
        "feature_label": "Envelope Tests",
        "effective_status": "ready",
        "ready": True,
        "blocked": False,
        "rework": False,
        "scoped_dependency_ids": ["lane-root-a"],
        "priority": 3,
        "provider_selection_ref": {
            "api_href": "/api/tui/provider-selection-records?lane_id=lane-conv-a",
            "label": "Provider selection",
        },
        "debug_refs": {
            "lane": {
                "api_href": "/api/lanes/lane-conv-a",
                "label": "Lane detail",
            },
            "takeover": {
                "api_href": "/api/lanes/lane-conv-a/takeover-context?conversation_id=conv-a",
                "label": "Takeover context",
            },
        },
        "prompt_summary": "Stabilize the Textual worklist envelope.",
    }


def test_tui_worklist_envelope_filters_by_workspace_server_side(
    tmp_path,
    monkeypatch,
):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "projection_revision": 3,
            "lanes": [
                {
                    "feature_id": "lane-workspace-a",
                    "lane_local_id": "T1-01",
                    "plan_feature_id": "T1",
                    "feature_label": "Workspace A",
                    "status": "gated",
                    "priority": 1,
                    "lane_depends_on_ids": [],
                    "workspace_id": "workspace-a",
                    "prompt_summary": "Only workspace A should remain.",
                },
                {
                    "feature_id": "lane-workspace-b",
                    "lane_local_id": "T1-02",
                    "plan_feature_id": "T1",
                    "feature_label": "Workspace B",
                    "status": "pending",
                    "priority": 2,
                    "lane_depends_on_ids": [],
                    "workspace_id": "workspace-b",
                    "prompt_summary": "Workspace B should be filtered out.",
                },
            ],
        },
    )
    monkeypatch.setattr(
        dashboard_api,
        "discover_xmuse_runtime_processes",
        lambda **_kwargs: _runtime_inventory(),
    )

    response = _client(tmp_path).get("/api/tui/worklist-envelope?workspace_id=workspace-a")

    assert response.status_code == 200
    body = response.json()
    assert [item["lane_id"] for item in body["items"]] == ["lane-workspace-a"]
    assert body["items"][0]["debug_refs"]["takeover"]["api_href"] == (
        "/api/lanes/lane-workspace-a/takeover-context?workspace_id=workspace-a"
    )
    assert body["run_health"]["scope"] == {
        "kind": "conversation",
        "conversation_id": "workspace-a",
        "workspace_id": "workspace-a",
    }
    assert body["debug_refs"]["self"]["api_href"] == (
        "/api/tui/worklist-envelope?workspace_id=workspace-a"
    )
    run_health = _client(tmp_path).get(body["debug_refs"]["run_health"]["api_href"])
    assert run_health.status_code == 200
    assert run_health.json() == body["run_health"]
    takeover = _client(tmp_path).get(body["items"][0]["debug_refs"]["takeover"]["api_href"])
    assert takeover.status_code == 200
    assert takeover.json()["lane_id"] == "lane-workspace-a"


def test_tui_worklist_envelope_filters_conversation_without_workspace_collision(
    tmp_path,
    monkeypatch,
):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-conv-a",
                    "lane_local_id": "T1-01",
                    "plan_feature_id": "T1",
                    "feature_label": "Conversation A",
                    "status": "pending",
                    "priority": 1,
                    "lane_depends_on_ids": [],
                    "conversation_id": "conv-a",
                    "workspace_id": "workspace-z",
                    "prompt_summary": "This lane belongs to conversation A.",
                },
                {
                    "feature_id": "lane-collision",
                    "lane_local_id": "T1-02",
                    "plan_feature_id": "T1",
                    "feature_label": "Collision",
                    "status": "pending",
                    "priority": 2,
                    "lane_depends_on_ids": [],
                    "conversation_id": "conv-b",
                    "workspace_id": "conv-a",
                    "prompt_summary": "This lane only collides by workspace id.",
                },
            ],
        },
    )
    monkeypatch.setattr(
        dashboard_api,
        "discover_xmuse_runtime_processes",
        lambda **_kwargs: _runtime_inventory(),
    )

    response = _client(tmp_path).get("/api/tui/worklist-envelope?conversation_id=conv-a")

    assert response.status_code == 200
    body = response.json()
    assert [item["lane_id"] for item in body["items"]] == ["lane-conv-a"]


def test_tui_worklist_envelope_degrades_when_projection_and_graph_lineage_disagree(
    tmp_path,
    monkeypatch,
):
    graph_id = "graph-envelope"
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "projection_revision": 9,
            "lanes": [
                {
                    "feature_id": "lane-projected",
                    "lane_local_id": "T1-02",
                    "plan_feature_id": "T1",
                    "feature_label": "Projected Lane",
                    "status": "pending",
                    "priority": 1,
                    "lane_depends_on_ids": [],
                    "conversation_id": "conv-envelope",
                    "graph_id": graph_id,
                    "prompt_summary": "Projected lane in scope.",
                }
            ],
        },
    )
    _write_lane_graph(
        tmp_path,
        graph_id,
        [
            {"feature_id": "lane-projected", "prompt": "projected lane"},
            {"feature_id": "lane-missing", "prompt": "missing lane"},
        ],
    )
    _write_lineage(
        tmp_path,
        [
            {
                **_LINEAGE_RECORDS[0],
                "spawned_conversation_id": "conv-envelope",
                "spawned_graph_id": graph_id,
            }
        ],
    )
    monkeypatch.setattr(
        dashboard_api,
        "discover_xmuse_runtime_processes",
        lambda **_kwargs: _runtime_inventory(),
    )

    response = _client(tmp_path).get("/api/tui/worklist-envelope?conversation_id=conv-envelope")

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["graph_lineage"] == {
        "degraded": True,
        "authoritative_graph_id": graph_id,
        "checked_graph_ids": [graph_id],
        "mismatched_graph_ids": [graph_id],
        "missing_projection_lane_ids": ["lane-missing"],
        "unexpected_projection_lane_ids": [],
        "warning_codes": ["graph_lineage_projection_mismatch"],
    }
    assert body["degradation"]["warning_codes"] == [
        "graph_lineage_projection_mismatch",
    ]
    assert body["degradation"]["reasons"] == [
        "projection lanes do not match graph lineage",
    ]


def test_lane_detail_includes_execution_logs(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "api-lane", "status": "running", "prompt": "test"}]},
    )
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "api-lane-round-1.log").write_text("started\nfinished\n", encoding="utf-8")
    (logs_dir / "other-lane.log").write_text("ignore me\n", encoding="utf-8")

    response = _client(tmp_path).get("/api/lanes/api-lane")

    assert response.status_code == 200
    body = response.json()
    assert body["lane"]["feature_id"] == "api-lane"
    assert body["execution_log"] == "started\nfinished\n"
    assert body["logs"] == [
        {
            "path": "logs/api-lane-round-1.log",
            "content": "started\nfinished\n",
        }
    ]


def test_lane_detail_includes_round_logs_that_mention_lane(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "api-lane", "status": "running", "prompt": "test"}]},
    )
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "round-1.log").write_text("api-lane: gate passed\n", encoding="utf-8")
    (logs_dir / "round-2.log").write_text("other-lane: gate passed\n", encoding="utf-8")

    response = _client(tmp_path).get("/api/lanes/api-lane")

    assert response.status_code == 200
    assert response.json()["logs"] == [
        {
            "path": "logs/round-1.log",
            "content": "api-lane: gate passed\n",
        }
    ]


def test_create_lane_appends_pending_execute_lane(tmp_path):
    _write_json(tmp_path / "feature_lanes.json", {"lanes": []})

    response = _client(tmp_path).post(
        "/api/lanes",
        json={
            "feature_id": "human-request",
            "prompt": "Add a dashboard",
            "capabilities": ["code", "test"],
            "failure_error": "large stderr should not be projected",
            "worker_command": ["codex", "exec"],
            "provider_health": {"diagnostic_summary": "secret"},
            "stdout": "raw stdout",
        },
    )

    assert response.status_code == 201
    response_body = response.json()
    assert response_body["feature_id"] == "human-request"
    assert response_body["command_hash"].startswith("sha256:")
    assert response_body["prompt"] == "Add a dashboard"
    assert "worker_command" not in response_body
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["projection_revision"] == 1
    assert data["lanes"] == [
        {
            "feature_id": "human-request",
            "task_type": "execute",
            "prompt_summary": "Add a dashboard",
            "prompt_ref": "logs/lane_prompts/human-request.md",
            "status": "pending",
            "capabilities": ["code", "test"],
            "command_hash": response_body["command_hash"],
        }
    ]
    assert (tmp_path / "logs" / "lane_prompts" / "human-request.md").read_text(
        encoding="utf-8"
    ) == "Add a dashboard"


def test_create_lane_rejects_duplicate_feature_id(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "same", "prompt": "already queued"}]},
    )

    response = _client(tmp_path).post(
        "/api/lanes",
        json={"feature_id": "same", "prompt": "duplicate"},
    )

    assert response.status_code == 409


def test_approve_completed_lane_marks_approval(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "ready", "status": "done", "prompt": "ready"}]},
    )

    response = _client(tmp_path).post("/api/lanes/ready/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "approved"
    assert body["approved_at"]
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["projection_revision"] == 1
    assert data["lanes"][0]["approval_status"] == "approved"


def test_approve_rejects_lane_that_is_not_completed(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "pending-lane", "status": "pending", "prompt": "wait"}]},
    )

    response = _client(tmp_path).post("/api/lanes/pending-lane/approve")

    assert response.status_code == 409


def test_reject_can_trigger_rework(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "needs-fix", "status": "done", "prompt": "almost"}]},
    )

    response = _client(tmp_path).post(
        "/api/lanes/needs-fix/reject",
        json={"reason": "Missing tests", "rework": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "rejected"
    assert body["status"] == "pending"
    assert body["rework_requested"] is True
    assert body["rejection_reason"] == "Missing tests"
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["projection_revision"] == 1
    assert data["lanes"][0]["status"] == "pending"


def test_sessions_and_errors_tolerate_missing_files(tmp_path):
    client = _client(tmp_path)

    assert client.get("/api/sessions").json() == {"sessions": []}
    assert client.get("/api/errors").json() == {"errors": []}


def test_sessions_and_errors_read_supported_file_shapes(tmp_path):
    _write_json(
        tmp_path / "active_sessions.json",
        {"sessions": [{"feature_id": "running", "pid": 123, "state": "running"}]},
    )
    _write_json(
        tmp_path / "error_knowledge.json",
        {"entries": [{"entry_id": "err-1", "pit": "pytest failed"}]},
    )
    client = _client(tmp_path)

    assert client.get("/api/sessions").json() == {
        "sessions": [{"feature_id": "running", "pid": 123, "state": "running"}]
    }
    assert client.get("/api/errors").json() == {
        "errors": [{"entry_id": "err-1", "pit": "pytest failed"}]
    }


def test_sessions_support_mcp_dict_shape(tmp_path):
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": {
                "running": {"session_id": "sess-1", "pid": 123, "status": "running"}
            }
        },
    )

    response = _client(tmp_path).get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "feature_id": "running",
                "session_id": "sess-1",
                "pid": 123,
                "status": "running",
            }
        ]
    }


def test_sessions_support_god_session_registry_shape(tmp_path):
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {
                    "god_session_id": "god-1",
                    "role": "executor",
                    "session_address": "xmuse://sessions/god-1",
                    "session_inbox_id": "inbox-1",
                    "status": "running",
                    "pid": 456,
                }
            ]
        },
    )

    response = _client(tmp_path).get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "god_session_id": "god-1",
                "role": "executor",
                "session_address": "xmuse://sessions/god-1",
                "session_inbox_id": "inbox-1",
                "status": "running",
                "pid": 456,
            }
        ]
    }


def test_metrics_use_normalized_lane_states(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "ready-lane", "status": "pending", "duration_seconds": 10},
                {"feature_id": "requeued-lane", "status": "reworking", "duration_seconds": 30},
                {"feature_id": "done-lane", "status": "merged"},
                {"feature_id": "terminated-lane", "status": "failed"},
                {"feature_id": "gate-failed-lane", "status": "gate_failed"},
                {"feature_id": "exec-failed-lane", "status": "exec_failed"},
            ]
        },
    )

    response = _client(tmp_path).get("/api/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "total": 6,
        "done": 1,
        "ready": 1,
        "requeued": 1,
        "failed": 3,
        "pending": 2,
        "avg_time_seconds": 20.0,
    }


def test_approve_accepts_merged_lane(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "ready", "status": "merged", "prompt": "ready"}]},
    )

    response = _client(tmp_path).post("/api/lanes/ready/approve")

    assert response.status_code == 200
    assert response.json()["approval_status"] == "approved"


def test_approve_awaiting_final_action_merge_without_github_proof_stays_blocked(
    tmp_path,
):
    _write_json(
        tmp_path / "feature_lanes.json",
        {"lanes": [{"feature_id": "ready", "status": "awaiting_final_action", "prompt": "ready"}]},
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-1",
                    "lane_id": "ready",
                    "verdict_id": "verdict-1",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/ready/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["blocker_reason"] == "github_gate_unverified"
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "blocked"
    assert data["lanes"][0]["blocker_reason"] == "github_gate_unverified"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "blocked"
    assert holds["holds"][0]["github_gate_gap_ref"] == "github_gate_unverified"


def test_approve_awaiting_final_action_merge_applies_import_to_target_worktree(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "tracked.txt").write_text("base\n", encoding="utf-8")
    _init_git_repo(worktree)
    _git(worktree, "add", "tracked.txt")
    _git(worktree, "commit", "-m", "base")
    artifact = worktree / "runtime_artifacts" / "loop7r.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7R\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    _init_git_repo(target_worktree)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "import-ready",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": ["runtime_artifacts/loop7r.txt"],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-import",
                    "lane_id": "import-ready",
                    "verdict_id": "verdict-import",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-import",
                    "lane_id": "import-ready",
                    "hold_id": "final-import",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "explicit target worktree selected for local import proof",
                    "created_at": "2026-06-21T00:00:00Z",
                    "forbidden_claims": ["github_server_merge"],
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/import-ready/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["blocker_reason"] == "github_gate_unverified"
    assert (target_worktree / "runtime_artifacts" / "loop7r.txt").read_text(
        encoding="utf-8"
    ) == "LOOP7R\n"
    imports = json.loads((tmp_path / "final_action_imports.json").read_text(encoding="utf-8"))
    assert imports["imports"][0]["status"] == "applied"
    assert imports["imports"][0]["hold_id"] == "final-import"
    assert imports["imports"][0]["target_worktree"] == str(target_worktree)
    assert imports["imports"][0]["import_decision"]["id"] == "decision-import"
    assert "github_server_merge" in imports["imports"][0]["forbidden_claims"]
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "blocked"
    assert holds["holds"][0]["github_gate_gap_ref"] == "github_gate_unverified"


def test_approve_awaiting_final_action_merge_requires_import_decision_for_target(
    tmp_path,
):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "tracked.txt").write_text("base\n", encoding="utf-8")
    _init_git_repo(worktree)
    _git(worktree, "add", "tracked.txt")
    _git(worktree, "commit", "-m", "base")
    artifact = worktree / "runtime_artifacts" / "loop7r-missing-decision.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7R\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "import-without-decision",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": ["runtime_artifacts/loop7r-missing-decision.txt"],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-no-decision",
                    "lane_id": "import-without-decision",
                    "verdict_id": "verdict-no-decision",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/import-without-decision/approve")

    assert response.status_code == 409
    assert "final_action_import_decision_missing" in response.json()["detail"]
    assert not (target_worktree / "runtime_artifacts" / "loop7r-missing-decision.txt").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_rejects_dirty_target_conflict(
    tmp_path,
):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "tracked.txt").write_text("base\n", encoding="utf-8")
    _init_git_repo(worktree)
    _git(worktree, "add", "tracked.txt")
    _git(worktree, "commit", "-m", "base")
    artifact = worktree / "runtime_artifacts" / "loop7r-conflict.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7R_SOURCE\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    (target_worktree / "runtime_artifacts").mkdir()
    target_artifact = target_worktree / "runtime_artifacts" / "loop7r-conflict.txt"
    target_artifact.write_text("LOOP7R_TARGET_BASE\n", encoding="utf-8")
    _init_git_repo(target_worktree)
    _git(target_worktree, "add", "runtime_artifacts/loop7r-conflict.txt")
    _git(target_worktree, "commit", "-m", "target base")
    target_artifact.write_text("LOOP7R_TARGET_DIRTY\n", encoding="utf-8")

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "dirty-target-conflict",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": ["runtime_artifacts/loop7r-conflict.txt"],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-dirty-target",
                    "lane_id": "dirty-target-conflict",
                    "verdict_id": "verdict-dirty-target",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-dirty-target",
                    "lane_id": "dirty-target-conflict",
                    "hold_id": "final-dirty-target",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "audit source-root style import conflict before apply",
                    "created_at": "2026-06-21T00:00:00Z",
                    "forbidden_claims": ["github_server_merge"],
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/dirty-target-conflict/approve")

    assert response.status_code == 409
    assert "final_action_import_target_dirty_conflict" in response.json()["detail"]
    assert "runtime_artifacts/loop7r-conflict.txt" in response.json()["detail"]
    assert target_artifact.read_text(encoding="utf-8") == "LOOP7R_TARGET_DIRTY\n"
    assert not (tmp_path / "final_action_imports.json").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_rejects_non_git_target(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    artifact = worktree / "runtime_artifacts" / "loop7r-non-git.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7R_SOURCE\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    target_artifact = target_worktree / "runtime_artifacts" / "loop7r-non-git.txt"

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "non-git-target",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": ["runtime_artifacts/loop7r-non-git.txt"],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-non-git-target",
                    "lane_id": "non-git-target",
                    "verdict_id": "verdict-non-git-target",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-non-git-target",
                    "lane_id": "non-git-target",
                    "hold_id": "final-non-git-target",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "target must be a git worktree before local import",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/non-git-target/approve")

    assert response.status_code == 409
    assert "final_action_import_target_not_git_worktree" in response.json()["detail"]
    assert not target_artifact.exists()
    assert not (tmp_path / "final_action_imports.json").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_preflights_all_sources_before_copy(
    tmp_path,
):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    first_artifact = worktree / "runtime_artifacts" / "loop7r-first.txt"
    first_artifact.parent.mkdir()
    first_artifact.write_text("FIRST\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    _init_git_repo(target_worktree)
    first_target = target_worktree / "runtime_artifacts" / "loop7r-first.txt"

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "partial-copy-risk",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": [
                        "runtime_artifacts/loop7r-first.txt",
                        "runtime_artifacts/loop7r-missing.txt",
                    ],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-partial-copy-risk",
                    "lane_id": "partial-copy-risk",
                    "verdict_id": "verdict-partial-copy-risk",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-partial-copy-risk",
                    "lane_id": "partial-copy-risk",
                    "hold_id": "final-partial-copy-risk",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "preflight all changed files before copying",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/partial-copy-risk/approve")

    assert response.status_code == 409
    assert "final_action_import_source_file_missing" in response.json()["detail"]
    assert "runtime_artifacts/loop7r-missing.txt" in response.json()["detail"]
    assert not first_target.exists()
    assert not (tmp_path / "final_action_imports.json").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_requires_decision_bound_to_hold(
    tmp_path,
):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    artifact = worktree / "runtime_artifacts" / "loop7r-unbound-decision.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7R\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    _init_git_repo(target_worktree)

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "unbound-decision",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": ["runtime_artifacts/loop7r-unbound-decision.txt"],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-unbound-decision",
                    "lane_id": "unbound-decision",
                    "verdict_id": "verdict-unbound-decision",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-unbound",
                    "lane_id": "unbound-decision",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "old broad approval must not satisfy a new hold",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/unbound-decision/approve")

    assert response.status_code == 409
    assert "final_action_import_decision_missing" in response.json()["detail"]
    assert not (target_worktree / "runtime_artifacts" / "loop7r-unbound-decision.txt").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_rejects_empty_changed_files(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    _init_git_repo(target_worktree)

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "empty-import",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": [],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-empty-import",
                    "lane_id": "empty-import",
                    "verdict_id": "verdict-empty-import",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-empty-import",
                    "lane_id": "empty-import",
                    "hold_id": "final-empty-import",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "empty imports are not durable local import proof",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/empty-import/approve")

    assert response.status_code == 409
    assert "final_action_import_changed_files_empty" in response.json()["detail"]
    assert not (tmp_path / "final_action_imports.json").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_rejects_git_subdirectory_target(
    tmp_path,
):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    artifact = worktree / "runtime_artifacts" / "loop7r-subdir.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7R_SOURCE\n", encoding="utf-8")

    target_repo = tmp_path / "target-repo"
    target_repo.mkdir()
    _init_git_repo(target_repo)
    target_worktree = target_repo / "nested"
    target_worktree.mkdir()
    target_artifact = target_worktree / "runtime_artifacts" / "loop7r-subdir.txt"
    target_artifact.parent.mkdir()
    target_artifact.write_text("LOOP7R_TARGET_DIRTY\n", encoding="utf-8")

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "subdir-target",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": ["runtime_artifacts/loop7r-subdir.txt"],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-subdir-target",
                    "lane_id": "subdir-target",
                    "verdict_id": "verdict-subdir-target",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-subdir-target",
                    "lane_id": "subdir-target",
                    "hold_id": "final-subdir-target",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "target must be the git worktree root",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/subdir-target/approve")

    assert response.status_code == 409
    assert "final_action_import_target_not_git_worktree_root" in response.json()["detail"]
    assert target_artifact.read_text(encoding="utf-8") == "LOOP7R_TARGET_DIRTY\n"
    assert not (tmp_path / "final_action_imports.json").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_approve_awaiting_final_action_merge_preflights_target_path_types(
    tmp_path,
):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    first_artifact = worktree / "runtime_artifacts" / "loop7r-target-first.txt"
    second_artifact = worktree / "runtime_artifacts" / "loop7r-target-second.txt"
    first_artifact.parent.mkdir()
    first_artifact.write_text("FIRST\n", encoding="utf-8")
    second_artifact.write_text("SECOND\n", encoding="utf-8")

    target_worktree = tmp_path / "target"
    target_worktree.mkdir()
    _init_git_repo(target_worktree)
    first_target = target_worktree / "runtime_artifacts" / "loop7r-target-first.txt"
    second_target = target_worktree / "runtime_artifacts" / "loop7r-target-second.txt"
    second_target.mkdir(parents=True)

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "target-path-type",
                    "status": "awaiting_final_action",
                    "prompt": "ready",
                    "worktree": str(worktree),
                    "final_action_import_target": str(target_worktree),
                    "changed_files": [
                        "runtime_artifacts/loop7r-target-first.txt",
                        "runtime_artifacts/loop7r-target-second.txt",
                    ],
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_actions.json",
        {
            "holds": [
                {
                    "id": "final-target-path-type",
                    "lane_id": "target-path-type",
                    "verdict_id": "verdict-target-path-type",
                    "action": "merge",
                    "target_status": "reviewed",
                    "status": "pending",
                    "summary": "merge now",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "final_action_import_decisions.json",
        {
            "decisions": [
                {
                    "id": "decision-target-path-type",
                    "lane_id": "target-path-type",
                    "hold_id": "final-target-path-type",
                    "decision": "apply_to_target_worktree",
                    "status": "approved",
                    "source_worktree": str(worktree),
                    "target_worktree": str(target_worktree),
                    "decided_by": "main-goal-agent",
                    "reason": "preflight target path types before copying",
                }
            ]
        },
    )

    response = _client(tmp_path).post("/api/lanes/target-path-type/approve")

    assert response.status_code == 409
    assert "final_action_import_target_path_not_file" in response.json()["detail"]
    assert "runtime_artifacts/loop7r-target-second.txt" in response.json()["detail"]
    assert not first_target.exists()
    assert second_target.is_dir()
    assert not (second_target / "loop7r-target-second.txt").exists()
    assert not (tmp_path / "final_action_imports.json").exists()
    data = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert data["lanes"][0]["status"] == "awaiting_final_action"
    holds = json.loads((tmp_path / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"


def test_metrics_treats_merged_lane_as_completed(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "a", "status": "merged", "duration_seconds": 10},
                {"feature_id": "b", "status": "failed", "duration_seconds": 30},
                {"feature_id": "c", "status": "running"},
            ]
        },
    )

    response = _client(tmp_path).get("/api/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "total": 3,
        "done": 1,
        "ready": 0,
        "requeued": 0,
        "failed": 1,
        "pending": 1,
        "avg_time_seconds": 20.0,
    }


def test_cors_allows_localhost_frontend(tmp_path):
    response = _client(tmp_path).options(
        "/api/lanes",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_default_port_is_dashboard_port():
    assert dashboard_api.DEFAULT_PORT == 8200


# ---------------------------------------------------------------------------
# Audit-event endpoint tests
# ---------------------------------------------------------------------------

_AUDIT_EVENTS = [
    {
        "event_id": "evt-1",
        "event_type": "lane.created",
        "timestamp": "2026-05-01T10:00:00Z",
        "metadata": {"feature_id": "feat-a"},
    },
    {
        "event_id": "evt-2",
        "event_type": "lane.completed",
        "timestamp": "2026-05-02T12:00:00Z",
        "metadata": {"feature_id": "feat-a", "duration_seconds": 120},
    },
    {
        "event_id": "evt-3",
        "event_type": "lane.created",
        "timestamp": "2026-05-03T08:00:00Z",
        "metadata": {"feature_id": "feat-b"},
    },
    {
        "event_id": "evt-4",
        "event_type": "gate.passed",
        "timestamp": "2026-05-04T09:30:00Z",
        "metadata": {"gate": "review"},
    },
    {
        "event_id": "evt-5",
        "event_type": "lane.failed",
        "timestamp": "2026-05-05T11:00:00Z",
        "metadata": {"feature_id": "feat-c"},
    },
]


def _write_audit_events(tmp_path: Path, events: list) -> None:
    _write_json(tmp_path / "audit_events.json", {"events": events})


def test_audit_events_returns_all_events_when_no_filters(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get("/api/dashboard/audit-events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["events"]) == 5
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["pages"] == 1


def test_audit_events_returns_empty_when_no_file(tmp_path):
    response = _client(tmp_path).get("/api/dashboard/audit-events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["events"] == []


def test_audit_events_filter_by_event_type(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"event_type": "lane.created"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(e["event_type"] == "lane.created" for e in body["events"])
    assert {e["event_id"] for e in body["events"]} == {"evt-1", "evt-3"}


def test_audit_events_filter_by_since(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"since": "2026-05-03T00:00:00Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {e["event_id"] for e in body["events"]} == {"evt-3", "evt-4", "evt-5"}


def test_audit_events_filter_by_until(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"until": "2026-05-02T23:59:59Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {e["event_id"] for e in body["events"]} == {"evt-1", "evt-2"}


def test_audit_events_filter_by_date_range(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events",
        params={"since": "2026-05-02T00:00:00Z", "until": "2026-05-04T23:59:59Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {e["event_id"] for e in body["events"]} == {"evt-2", "evt-3", "evt-4"}


def test_audit_events_filter_by_type_and_date_range(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events",
        params={
            "event_type": "lane.created",
            "since": "2026-05-02T00:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["event_id"] == "evt-3"


def test_audit_events_pagination(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"page": 1, "page_size": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["events"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["pages"] == 3


def test_audit_events_pagination_last_page(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"page": 3, "page_size": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    assert body["page"] == 3


def test_audit_events_pagination_beyond_last_page_returns_empty(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"page": 99, "page_size": 10}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["events"] == []
    assert body["total"] == 5


def test_audit_events_invalid_page_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"page": 0}
    )

    assert response.status_code == 422


def test_audit_events_invalid_since_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"since": "not-a-date"}
    )

    assert response.status_code == 422


def test_audit_events_invalid_until_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"until": "bad-ts"}
    )

    assert response.status_code == 422


def test_audit_events_events_include_timestamps_types_and_metadata(tmp_path):
    _write_audit_events(tmp_path, _AUDIT_EVENTS[:1])

    response = _client(tmp_path).get("/api/dashboard/audit-events")

    assert response.status_code == 200
    event = response.json()["events"][0]
    assert "event_id" in event
    assert "event_type" in event
    assert "timestamp" in event
    assert "metadata" in event


def test_audit_events_page_size_capped_at_500(tmp_path):
    events = [
        {
            "event_id": f"evt-{i}",
            "event_type": "test.event",
            "timestamp": f"2026-05-01T{i:02d}:00:00Z",
            "metadata": {},
        }
        for i in range(600)
    ]
    _write_audit_events(tmp_path, events)

    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"page_size": 9999}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 500
    assert body["page_size"] == 500


def test_audit_events_events_without_timestamp_excluded_when_range_filter_active(tmp_path):
    events = [
        {"event_id": "no-ts", "event_type": "lane.created", "metadata": {}},
        {
            "event_id": "has-ts",
            "event_type": "lane.created",
            "timestamp": "2026-05-01T10:00:00Z",
            "metadata": {},
        },
    ]
    _write_audit_events(tmp_path, events)

    # With a date range filter, the event without a timestamp should be excluded
    response = _client(tmp_path).get(
        "/api/dashboard/audit-events", params={"since": "2026-01-01T00:00:00Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["event_id"] == "has-ts"


def test_audit_events_events_without_timestamp_included_when_no_range_filter(tmp_path):
    events = [
        {"event_id": "no-ts", "event_type": "lane.created", "metadata": {}},
        {
            "event_id": "has-ts",
            "event_type": "lane.created",
            "timestamp": "2026-05-01T10:00:00Z",
            "metadata": {},
        },
    ]
    _write_audit_events(tmp_path, events)

    # Without a date range filter, all events are returned
    response = _client(tmp_path).get("/api/dashboard/audit-events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# State-history endpoint tests
# ---------------------------------------------------------------------------

_STATE_SNAPSHOTS = [
    {
        "snapshot_id": "snap-1",
        "lane_id": "feat-a",
        "state_key": "pending",
        "timestamp": "2026-05-01T10:00:00Z",
        "metadata": {"triggered_by": "human"},
    },
    {
        "snapshot_id": "snap-2",
        "lane_id": "feat-a",
        "state_key": "dispatched",
        "timestamp": "2026-05-02T08:00:00Z",
        "metadata": {"agent": "codex"},
    },
    {
        "snapshot_id": "snap-3",
        "lane_id": "feat-b",
        "state_key": "pending",
        "timestamp": "2026-05-03T09:00:00Z",
        "metadata": {},
    },
    {
        "snapshot_id": "snap-4",
        "lane_id": "feat-b",
        "state_key": "executed",
        "timestamp": "2026-05-04T11:00:00Z",
        "metadata": {"exit_code": 0},
    },
    {
        "snapshot_id": "snap-5",
        "lane_id": "feat-a",
        "state_key": "merged",
        "timestamp": "2026-05-05T14:00:00Z",
        "metadata": {},
    },
]


def _write_state_history(tmp_path: Path, snapshots: list) -> None:
    _write_json(tmp_path / "state_history.json", {"snapshots": snapshots})


def test_state_history_returns_all_snapshots_when_no_filters(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get("/api/dashboard/state-history")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["snapshots"]) == 5
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["pages"] == 1


def test_state_history_returns_empty_when_no_file(tmp_path):
    response = _client(tmp_path).get("/api/dashboard/state-history")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["snapshots"] == []


def test_state_history_filter_by_lane_id(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"lane_id": "feat-a"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert all(s["lane_id"] == "feat-a" for s in body["snapshots"])
    assert {s["snapshot_id"] for s in body["snapshots"]} == {"snap-1", "snap-2", "snap-5"}


def test_state_history_filter_by_state_key(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"state_key": "pending"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(s["state_key"] == "pending" for s in body["snapshots"])
    assert {s["snapshot_id"] for s in body["snapshots"]} == {"snap-1", "snap-3"}


def test_state_history_filter_by_lane_id_and_state_key(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history",
        params={"lane_id": "feat-a", "state_key": "dispatched"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["snapshots"][0]["snapshot_id"] == "snap-2"


def test_state_history_filter_by_since(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"since": "2026-05-03T00:00:00Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {s["snapshot_id"] for s in body["snapshots"]} == {"snap-3", "snap-4", "snap-5"}


def test_state_history_filter_by_until(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"until": "2026-05-02T23:59:59Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {s["snapshot_id"] for s in body["snapshots"]} == {"snap-1", "snap-2"}


def test_state_history_filter_by_date_range(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history",
        params={"since": "2026-05-02T00:00:00Z", "until": "2026-05-04T23:59:59Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {s["snapshot_id"] for s in body["snapshots"]} == {"snap-2", "snap-3", "snap-4"}


def test_state_history_filter_by_lane_and_date_range(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history",
        params={"lane_id": "feat-a", "since": "2026-05-02T00:00:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {s["snapshot_id"] for s in body["snapshots"]} == {"snap-2", "snap-5"}


def test_state_history_pagination(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"page": 1, "page_size": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["snapshots"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["pages"] == 3


def test_state_history_pagination_last_page(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"page": 3, "page_size": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["snapshots"]) == 1
    assert body["page"] == 3


def test_state_history_pagination_beyond_last_page_returns_empty(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"page": 99, "page_size": 10}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["snapshots"] == []
    assert body["total"] == 5


def test_state_history_invalid_page_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"page": 0}
    )

    assert response.status_code == 422


def test_state_history_invalid_since_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"since": "not-a-date"}
    )

    assert response.status_code == 422


def test_state_history_invalid_until_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"until": "bad-ts"}
    )

    assert response.status_code == 422


def test_state_history_snapshots_include_required_fields(tmp_path):
    _write_state_history(tmp_path, _STATE_SNAPSHOTS[:1])

    response = _client(tmp_path).get("/api/dashboard/state-history")

    assert response.status_code == 200
    snapshot = response.json()["snapshots"][0]
    assert "snapshot_id" in snapshot
    assert "lane_id" in snapshot
    assert "state_key" in snapshot
    assert "timestamp" in snapshot
    assert "metadata" in snapshot


def test_state_history_page_size_capped_at_500(tmp_path):
    snapshots = [
        {
            "snapshot_id": f"snap-{i}",
            "lane_id": "feat-x",
            "state_key": "pending",
            "timestamp": f"2026-05-01T{i % 24:02d}:00:00Z",
            "metadata": {},
        }
        for i in range(600)
    ]
    _write_state_history(tmp_path, snapshots)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"page_size": 9999}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["snapshots"]) == 500
    assert body["page_size"] == 500


def test_state_history_snapshots_without_timestamp_excluded_when_range_filter_active(tmp_path):
    snapshots = [
        {"snapshot_id": "no-ts", "lane_id": "feat-a", "state_key": "pending", "metadata": {}},
        {
            "snapshot_id": "has-ts",
            "lane_id": "feat-a",
            "state_key": "dispatched",
            "timestamp": "2026-05-01T10:00:00Z",
            "metadata": {},
        },
    ]
    _write_state_history(tmp_path, snapshots)

    response = _client(tmp_path).get(
        "/api/dashboard/state-history", params={"since": "2026-01-01T00:00:00Z"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["snapshots"][0]["snapshot_id"] == "has-ts"


def test_state_history_snapshots_without_timestamp_included_when_no_range_filter(tmp_path):
    snapshots = [
        {"snapshot_id": "no-ts", "lane_id": "feat-a", "state_key": "pending", "metadata": {}},
        {
            "snapshot_id": "has-ts",
            "lane_id": "feat-a",
            "state_key": "dispatched",
            "timestamp": "2026-05-01T10:00:00Z",
            "metadata": {},
        },
    ]
    _write_state_history(tmp_path, snapshots)

    response = _client(tmp_path).get("/api/dashboard/state-history")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2


# ---------------------------------------------------------------------------
def test_dashboard_lists_resolutions_and_verdicts_from_read_models(tmp_path):
    _write_json(
        tmp_path / "read_models" / "resolutions.json",
        {"resolutions": [{"resolution_id": "res-1", "status": "approved"}]},
    )
    _write_json(
        tmp_path / "read_models" / "verdicts.json",
        {"verdicts": [{"verdict_id": "verdict-1", "decision": "merge"}]},
    )

    client = _client(tmp_path)
    resolutions = client.get("/api/resolutions")
    verdicts = client.get("/api/verdicts")

    assert resolutions.status_code == 200
    assert resolutions.json()["resolutions"][0]["resolution_id"] == "res-1"
    assert verdicts.status_code == 200
    assert verdicts.json()["verdicts"][0]["decision"] == "merge"


# ---------------------------------------------------------------------------
# Execution lineage endpoint tests  (GET /api/dashboard/lineage)
# ---------------------------------------------------------------------------

_LINEAGE_RECORDS = [
    {
        "lineage_id": "lin-1",
        "source_run_id": "run-a",
        "source_resolution_id": "res-a",
        "evidence_bundle_id": "evbundle_e432ba4eae4b4941bc88f28dcf633e0c",
        "evolution_proposal_id": "prop-1",
        "review_decision_id": "rev-1",
        "guardrail_decision_id": "guard-1",
        "spawned_conversation_id": "conv-1",
        "spawned_proposal_id": "prop-2",
        "spawned_resolution_id": "res-b",
        "spawned_graph_id": "graph-b",
        "blueprint_set_id": "bp-1",
        "target_track_ids": ["dashboard-auditability"],
        "terminal_aggregation_ref": "agg-1",
        "created_at": "2026-05-01T10:00:00Z",
    },
    {
        "lineage_id": "lin-2",
        "source_run_id": "run-b",
        "source_resolution_id": "res-b",
        "evidence_bundle_id": "evbundle_e432ba4eae4b4941bc88f28dcf633e0c",
        "evolution_proposal_id": "prop-3",
        "review_decision_id": "rev-2",
        "guardrail_decision_id": "guard-2",
        "spawned_conversation_id": "conv-2",
        "spawned_proposal_id": "prop-4",
        "spawned_resolution_id": "res-c",
        "spawned_graph_id": "graph-c",
        "blueprint_set_id": "bp-1",
        "target_track_ids": ["execution-autonomy"],
        "terminal_aggregation_ref": "agg-2",
        "created_at": "2026-05-02T10:00:00Z",
    },
    {
        "lineage_id": "lin-3",
        "source_run_id": "run-c",
        "source_resolution_id": "res-c",
        "evidence_bundle_id": "evbundle_e432ba4eae4b4941bc88f28dcf633e0c",
        "evolution_proposal_id": "prop-5",
        "review_decision_id": "rev-3",
        "guardrail_decision_id": "guard-3",
        "spawned_conversation_id": "conv-3",
        "spawned_proposal_id": "prop-6",
        "spawned_resolution_id": "res-d",
        "spawned_graph_id": "graph-d",
        "blueprint_set_id": "bp-2",
        "target_track_ids": ["review-verdict-formalization"],
        "terminal_aggregation_ref": "agg-3",
        "created_at": "2026-05-03T10:00:00Z",
    },
]


def _write_lineage(tmp_path: Path, records: list) -> None:
    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)
    (se_dir / "lineage.json").write_text(
        json.dumps({"lineage": records}, indent=2), encoding="utf-8"
    )


def test_lineage_returns_empty_graph_when_no_file(tmp_path):
    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["merge_points"] == []
    assert body["total_nodes"] == 0
    assert body["total_edges"] == 0


def test_lineage_returns_full_graph(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    body = response.json()
    # 3 source runs + 3 spawned graphs = 6 unique nodes
    assert body["total_nodes"] == 6
    assert body["total_edges"] == 3
    assert body["merge_points"] == []


def test_lineage_edges_contain_required_fields(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])

    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    edge = response.json()["edges"][0]
    assert edge["lineage_id"] == "lin-1"
    assert edge["source_node"] == "run-a"
    assert edge["target_node"] == "graph-b"
    assert edge["blueprint_set_id"] == "bp-1"
    assert edge["target_track_ids"] == ["dashboard-auditability"]
    assert edge["evolution_proposal_id"] == "prop-1"
    assert edge["guardrail_decision_id"] == "guard-1"
    assert edge["created_at"] == "2026-05-01T10:00:00Z"


def test_lineage_nodes_contain_required_fields(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])

    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    nodes = {n["node_id"]: n for n in response.json()["nodes"]}
    assert "run-a" in nodes
    assert nodes["run-a"]["node_type"] == "run"
    assert nodes["run-a"]["is_merge_point"] is False
    assert "graph-b" in nodes
    assert nodes["graph-b"]["node_type"] == "graph"
    assert nodes["graph-b"]["is_merge_point"] is False


def test_lineage_detects_merge_points(tmp_path):
    # Two source runs both spawn the same graph — that graph is a merge point
    records = [
        {
            "lineage_id": "lin-m1",
            "source_run_id": "run-x",
            "spawned_graph_id": "graph-merged",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-x",
            "guardrail_decision_id": "guard-x",
            "created_at": "2026-05-01T10:00:00Z",
        },
        {
            "lineage_id": "lin-m2",
            "source_run_id": "run-y",
            "spawned_graph_id": "graph-merged",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-y",
            "guardrail_decision_id": "guard-y",
            "created_at": "2026-05-02T10:00:00Z",
        },
    ]
    _write_lineage(tmp_path, records)

    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    body = response.json()
    assert body["merge_points"] == ["graph-merged"]
    nodes = {n["node_id"]: n for n in body["nodes"]}
    assert nodes["graph-merged"]["is_merge_point"] is True


def test_lineage_traversal_from_node(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    # run-a -> graph-b; run-b -> graph-c; run-c -> graph-d
    # Starting from run-a should only return run-a and graph-b
    response = _client(tmp_path).get(
        "/api/dashboard/lineage", params={"from_node": "run-a"}
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert node_ids == {"run-a", "graph-b"}
    assert body["total_edges"] == 1
    assert body["edges"][0]["lineage_id"] == "lin-1"


def test_lineage_traversal_run_id_alias(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    response = _client(tmp_path).get(
        "/api/dashboard/lineage", params={"run_id": "run-b"}
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert node_ids == {"run-b", "graph-c"}


def test_lineage_traversal_from_node_not_found_returns_empty(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    response = _client(tmp_path).get(
        "/api/dashboard/lineage", params={"from_node": "nonexistent-run"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"] == []
    assert body["edges"] == []


def test_lineage_traversal_depth_limits_reachable_nodes(tmp_path):
    # Chain: run-start -> graph-mid -> graph-end
    # (graph-mid acts as both a spawned graph and a source run for the next hop)
    chain_records = [
        {
            "lineage_id": "chain-1",
            "source_run_id": "run-start",
            "spawned_graph_id": "graph-mid",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-c1",
            "guardrail_decision_id": "guard-c1",
            "created_at": "2026-05-01T10:00:00Z",
        },
        {
            "lineage_id": "chain-2",
            "source_run_id": "graph-mid",
            "spawned_graph_id": "graph-end",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-c2",
            "guardrail_decision_id": "guard-c2",
            "created_at": "2026-05-02T10:00:00Z",
        },
    ]
    _write_lineage(tmp_path, chain_records)

    # depth=1 from run-start: only run-start and graph-mid
    response = _client(tmp_path).get(
        "/api/dashboard/lineage", params={"from_node": "run-start", "depth": 1}
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert node_ids == {"run-start", "graph-mid"}
    assert body["total_edges"] == 1


def test_lineage_traversal_depth_2_reaches_full_chain(tmp_path):
    chain_records = [
        {
            "lineage_id": "chain-1",
            "source_run_id": "run-start",
            "spawned_graph_id": "graph-mid",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-c1",
            "guardrail_decision_id": "guard-c1",
            "created_at": "2026-05-01T10:00:00Z",
        },
        {
            "lineage_id": "chain-2",
            "source_run_id": "graph-mid",
            "spawned_graph_id": "graph-end",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-c2",
            "guardrail_decision_id": "guard-c2",
            "created_at": "2026-05-02T10:00:00Z",
        },
    ]
    _write_lineage(tmp_path, chain_records)

    response = _client(tmp_path).get(
        "/api/dashboard/lineage", params={"from_node": "run-start", "depth": 2}
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert node_ids == {"run-start", "graph-mid", "graph-end"}
    assert body["total_edges"] == 2


def test_lineage_invalid_depth_returns_422(tmp_path):
    response = _client(tmp_path).get(
        "/api/dashboard/lineage", params={"from_node": "run-a", "depth": 0}
    )

    assert response.status_code == 422


def test_lineage_from_node_takes_precedence_over_run_id(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    # from_node=run-a should win over run_id=run-b
    response = _client(tmp_path).get(
        "/api/dashboard/lineage",
        params={"from_node": "run-a", "run_id": "run-b"},
    )

    assert response.status_code == 200
    node_ids = {n["node_id"] for n in response.json()["nodes"]}
    assert "run-a" in node_ids
    assert "run-b" not in node_ids


def test_lineage_records_with_missing_ids_are_skipped(tmp_path):
    records = [
        # valid record
        {
            "lineage_id": "lin-ok",
            "source_run_id": "run-ok",
            "spawned_graph_id": "graph-ok",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "evolution_proposal_id": "prop-ok",
            "guardrail_decision_id": "guard-ok",
            "created_at": "2026-05-01T10:00:00Z",
        },
        # missing source_run_id
        {
            "lineage_id": "lin-bad",
            "spawned_graph_id": "graph-bad",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "created_at": "2026-05-01T10:00:00Z",
        },
        # missing spawned_graph_id
        {
            "lineage_id": "lin-bad2",
            "source_run_id": "run-bad",
            "blueprint_set_id": "bp-1",
            "target_track_ids": [],
            "created_at": "2026-05-01T10:00:00Z",
        },
    ]
    _write_lineage(tmp_path, records)

    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    body = response.json()
    assert body["total_edges"] == 1
    assert body["edges"][0]["lineage_id"] == "lin-ok"


def test_lineage_graph_node_spawned_at_and_track_ids(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])

    response = _client(tmp_path).get("/api/dashboard/lineage")

    assert response.status_code == 200
    nodes = {n["node_id"]: n for n in response.json()["nodes"]}
    graph_node = nodes["graph-b"]
    assert graph_node["spawned_at"] == "2026-05-01T10:00:00Z"
    assert graph_node["target_track_ids"] == ["dashboard-auditability"]
    assert graph_node["blueprint_set_id"] == "bp-1"


# ---------------------------------------------------------------------------
# Health endpoint tests  (GET /api/health)
# ---------------------------------------------------------------------------


def _write_aggregations(tmp_path: Path, aggregations: list) -> None:
    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)
    _write_json(se_dir / "run_aggregations.json", {"aggregations": aggregations})


def _write_lane_graph(tmp_path: Path, graph_id: str, lanes: list[dict]) -> None:
    _write_json(
        tmp_path / "lane_graphs" / f"{graph_id}.json",
        {
            "id": graph_id,
            "conversation_id": f"conv-{graph_id}",
            "resolution_id": f"res-{graph_id}",
            "version": 1,
            "lanes": lanes,
        },
    )


def _write_feature_graph_set(
    tmp_path: Path,
    *,
    root_name: str = "graph_sets",
    graph_set_id: str = "graph-set-alpha",
) -> None:
    _write_json(
        tmp_path / root_name / f"{graph_set_id}.json",
        {
            "id": graph_set_id,
            "version": 1,
            "source_refs": ["feature_plan:plan-alpha"],
            "feature_plan": {
                "id": "plan-alpha",
                "conversation_id": "conv-alpha",
                "resolution_id": "res-alpha",
                "version": 1,
                "features": [
                    {
                        "feature_id": "F1",
                        "title": "Dashboard drilldown",
                        "goal": "Expose graph-set status to dashboard readers.",
                        "acceptance_criteria": ["graph-set is inspectable"],
                        "dependencies": [],
                        "graph_id": "graph-alpha",
                        "expected_touched_areas": ["xmuse/dashboard_api.py"],
                        "blueprint_refs": ["blueprint:alpha"],
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-alpha",
                    "conversation_id": "conv-alpha",
                    "resolution_id": "res-alpha",
                    "version": 1,
                    "status": "planned",
                    "source_refs": ["feature:F1"],
                    "lanes": [
                        {
                            "feature_id": "lane-alpha",
                            "title": "Inspect graph set",
                            "prompt": "Verify graph-set dashboard drilldown.",
                            "task_type": "execute",
                            "priority": 1,
                            "capabilities": ["code"],
                            "depends_on": [],
                            "blueprint_refs": ["blueprint:alpha"],
                            "acceptance_criteria": ["runner evidence is visible"],
                            "expected_touched_areas": ["tests/xmuse/test_dashboard_api.py"],
                        }
                    ],
                }
            ],
        },
    )


def test_health_returns_ok_with_no_data(tmp_path):
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["graph_authority"]["authoritative_graph_id"] is None
    assert body["graph_authority"]["merge_state"] == "unknown"
    assert body["graph_authority"]["lineage_terminated"] is False
    assert body["graph_authority"]["open_lineage_count"] == 0
    assert body["graph_authority"]["latest_run_id"] is None
    assert body["graph_authority"]["latest_lineage_id"] is None
    assert body["active_session_count"] == 0
    assert body["error_count"] == 0


def test_feature_graph_sets_read_fake_graph_set_artifacts(tmp_path):
    _write_feature_graph_set(tmp_path, root_name="graph_sets")

    list_response = _client(tmp_path).get("/api/feature-graph-sets")
    detail_response = _client(tmp_path).get("/api/feature-graph-sets/graph-set-alpha")

    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["total"] == 1
    assert list_body["graph_sets"][0]["id"] == "graph-set-alpha"
    assert list_body["graph_sets"][0]["feature_plan_id"] == "plan-alpha"
    assert list_body["graph_sets"][0]["counts"] == {
        "features": 1,
        "lane_graphs": 1,
    }
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["graph_set"]["id"] == "graph-set-alpha"
    assert detail_body["summary"] == list_body["graph_sets"][0]


def test_feature_graph_set_runner_evidence_uses_fake_graph_set_artifact(tmp_path):
    _write_feature_graph_set(tmp_path, root_name="graph_sets")
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-alpha",
                    "lane_local_id": "lane-alpha",
                    "conversation_id": "conv-alpha",
                    "graph_id": "graph-alpha",
                    "status": "gate_failed",
                    "failure_reason": "execution_infra_unavailable",
                    "review_evidence_refs": ["review:alpha"],
                    "diff_ref": "diff:alpha",
                }
            ]
        },
    )

    response = _client(tmp_path).get(
        "/api/feature-graph-sets/graph-set-alpha/runner-evidence"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "graph_set_runner_evidence"
    assert body["read_only"] is True
    assert body["graph_set_id"] == "graph-set-alpha"
    assert body["lane_count"] == 1
    assert body["lanes"][0]["lane_id"] == "lane-alpha"
    assert body["lanes"][0]["primary_evidence_refs"] == ["lane.failure_reason"]
    assert body["lanes"][0]["review_evidence_refs"] == ["review:alpha"]
    assert body["lanes"][0]["gate_refs"] == []
    assert {"ref": "diff:alpha"} in body["lanes"][0]["worker_refs"]


def test_health_reports_authoritative_graph_from_latest_lineage(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    # lin-3 is the most recent (2026-05-03); its spawned_graph_id is graph-d
    assert body["graph_authority"]["authoritative_graph_id"] == "graph-d"
    assert body["graph_authority"]["latest_run_id"] == "run-c"
    assert body["graph_authority"]["latest_lineage_id"] == "lin-3"


def test_health_merge_state_running_when_no_aggregation(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])
    # No aggregations written — graph is still running

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["merge_state"] == "running"
    assert body["graph_authority"]["lineage_terminated"] is False
    assert body["status"] == "ok"


def test_health_separates_source_lineage_status_from_spawned_graph_state(tmp_path):
    _write_lineage(
        tmp_path,
        [
            {
                **_LINEAGE_RECORDS[0],
                "source_run_id": "source-graph",
                "spawned_graph_id": "next-graph",
                "terminal_aggregation_ref": "source-agg",
            }
        ],
    )
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "source-agg",
                "run_id": "source-graph",
                "resolution_id": "source-res",
                "graph_id": "source-graph",
                "status": "terminated",
                "terminal": True,
                "reason": "lineage terminalized without merge",
                "created_at": "2026-05-01T12:00:00Z",
            },
            {
                "aggregation_id": "next-agg",
                "run_id": "next-graph",
                "resolution_id": "next-res",
                "graph_id": "next-graph",
                "status": "running",
                "terminal": False,
                "reason": "follow-up graph still running",
                "created_at": "2026-05-01T13:00:00Z",
            },
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["graph_authority"]["authoritative_graph_id"] == "next-graph"
    assert body["graph_authority"]["merge_state"] == "running"
    assert body["graph_authority"]["lineage_status"] == "terminated"
    assert body["graph_authority"]["lineage_terminated"] is True
    assert body["graph_authority"]["source_aggregation"]["aggregation_id"] == "source-agg"
    assert body["graph_authority"]["graph_aggregation"]["aggregation_id"] == "next-agg"


def test_health_merge_state_merged_when_aggregation_is_merged(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-1",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "merged",
                "terminal": True,
                "reason": "all lanes merged",
                "created_at": "2026-05-01T12:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["merge_state"] == "merged"
    assert body["graph_authority"]["lineage_terminated"] is True
    assert body["status"] == "ok"


def test_health_status_degraded_when_merge_state_is_terminated(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-1",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "terminated",
                "terminal": True,
                "reason": "hard failure",
                "created_at": "2026-05-01T12:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["merge_state"] == "terminated"
    assert body["graph_authority"]["lineage_terminated"] is True
    assert body["status"] == "degraded"


def test_health_uses_latest_graph_aggregation_when_graph_has_multiple_rows(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-old",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "terminated",
                "terminal": True,
                "reason": "old failed state",
                "created_at": "2026-05-01T12:00:00Z",
            },
            {
                "aggregation_id": "agg-new",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "merged",
                "terminal": True,
                "reason": "new merged state",
                "created_at": "2026-05-01T13:00:00Z",
            },
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["merge_state"] == "merged"
    assert body["graph_authority"]["graph_aggregation"]["aggregation_id"] == "agg-new"
    assert body["status"] == "ok"


def test_health_status_degraded_when_merge_state_is_blocked_for_input(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-1",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "blocked_for_input",
                "terminal": True,
                "reason": "missing clarification",
                "created_at": "2026-05-01T12:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["merge_state"] == "blocked_for_input"
    assert body["status"] == "degraded"


def test_health_keeps_awaiting_final_action_merge_lane_running(tmp_path):
    graph_id = "graph-final-action"
    _write_lineage(tmp_path, [{**_LINEAGE_RECORDS[0], "spawned_graph_id": graph_id}])
    _write_lane_graph(
        tmp_path,
        graph_id,
        [{"feature_id": "lane-awaiting", "prompt": "approve merge"}],
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-awaiting",
                    "status": "awaiting_final_action",
                    "graph_id": graph_id,
                    "review_decision": "merge",
                    "review_verdict_id": "verdict-merge-1",
                    "final_action": "merge",
                    "review_summary": "ready to merge after human approval",
                }
            ]
        },
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    graph_authority = body["graph_authority"]
    assert body["status"] == "ok"
    assert graph_authority["merge_state"] == "running"
    assert graph_authority["graph_terminal"] is False
    assert graph_authority["graph_lineage_status"] == "awaiting_final_action"
    assert graph_authority["graph_reason"] == "one or more lanes are awaiting final-action approval"
    assert graph_authority["open_lane_lineages"] == ["lane-awaiting"]
    assert graph_authority["merged_lineages"] == []
    assert graph_authority["final_action_holds"] == [
        {
            "lane_id": "lane-awaiting",
            "action": "merge",
            "verdict_id": "verdict-merge-1",
            "summary": "ready to merge after human approval",
        }
    ]


def test_health_status_degraded_when_errors_present(tmp_path):
    _write_json(
        tmp_path / "error_knowledge.json",
        {"entries": [{"entry_id": "err-1", "pit": "test failed"}]},
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["error_count"] == 1


def test_health_open_lineage_count_reflects_unterminated_graphs(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS)
    # Only graph-b has a terminal aggregation; graph-c and graph-d are open
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-1",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "merged",
                "terminal": True,
                "reason": "done",
                "created_at": "2026-05-01T12:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["open_lineage_count"] == 2


def test_health_open_lineage_count_zero_when_all_terminated(tmp_path):
    _write_lineage(tmp_path, _LINEAGE_RECORDS[:1])
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-1",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "graph-b",
                "status": "merged",
                "terminal": True,
                "reason": "done",
                "created_at": "2026-05-01T12:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json()["graph_authority"]["open_lineage_count"] == 0


def test_health_includes_lane_summary(tmp_path):
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "a", "status": "merged"},
                {"feature_id": "b", "status": "pending"},
                {"feature_id": "c", "status": "failed"},
            ]
        },
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert "lane_summary" in body
    assert isinstance(body["lane_summary"], dict)


def test_health_includes_active_session_count(tmp_path):
    _write_json(
        tmp_path / "active_sessions.json",
        {
            "sessions": [
                {"feature_id": "a", "pid": 1},
                {"feature_id": "b", "pid": 2},
            ]
        },
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert response.json()["active_session_count"] == 2


def test_health_latest_lineage_is_most_recent_by_created_at(tmp_path):
    # Write records out of chronological order to verify sorting
    records = [
        {**_LINEAGE_RECORDS[2], "created_at": "2026-05-03T10:00:00Z"},  # lin-3 latest
        {**_LINEAGE_RECORDS[0], "created_at": "2026-05-01T10:00:00Z"},  # lin-1 oldest
        {**_LINEAGE_RECORDS[1], "created_at": "2026-05-02T10:00:00Z"},  # lin-2 middle
    ]
    _write_lineage(tmp_path, records)

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["latest_lineage_id"] == "lin-3"
    assert body["graph_authority"]["authoritative_graph_id"] == "graph-d"


def test_health_status_degraded_when_source_lineage_was_terminated(tmp_path):
    _write_lineage(
        tmp_path,
        [
            {
                **_LINEAGE_RECORDS[0],
                "terminal_aggregation_ref": "agg-source",
            }
        ],
    )
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-source",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "run-a",
                "status": "terminated",
                "terminal": True,
                "reason": "review=rework",
                "created_at": "2026-05-01T12:00:00Z",
            },
            {
                "aggregation_id": "agg-graph",
                "run_id": "graph-b",
                "resolution_id": "res-b",
                "graph_id": "graph-b",
                "status": "merged",
                "terminal": True,
                "reason": "follow-up graph merged",
                "created_at": "2026-05-01T13:00:00Z",
            },
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["graph_authority"]["merge_state"] == "merged"
    assert body["graph_authority"]["lineage_status"] == "terminated"
    assert body["status"] == "degraded"


def test_health_derives_graph_state_from_lane_graph_when_aggregation_is_stale(tmp_path):
    graph_id = "graph-stale"
    _write_lineage(
        tmp_path,
        [
            {
                **_LINEAGE_RECORDS[0],
                "spawned_graph_id": graph_id,
                "terminal_aggregation_ref": "agg-source",
            }
        ],
    )
    _write_lane_graph(
        tmp_path,
        graph_id,
        [{"feature_id": "lane-unmerged", "prompt": "needs merge"}],
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-unmerged",
                    "status": "failed",
                    "graph_id": graph_id,
                    "review_decision": "rework",
                }
            ]
        },
    )
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-source",
                "run_id": "run-a",
                "resolution_id": "res-a",
                "graph_id": "run-a",
                "status": "merged",
                "terminal": True,
                "reason": "source merged",
                "created_at": "2026-05-01T12:00:00Z",
            },
            {
                "aggregation_id": "agg-stale",
                "run_id": graph_id,
                "resolution_id": f"res-{graph_id}",
                "graph_id": graph_id,
                "status": "merged",
                "terminal": True,
                "reason": "stale row",
                "created_at": "2026-05-01T13:00:00Z",
            },
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    graph_authority = body["graph_authority"]
    assert body["status"] == "degraded"
    assert graph_authority["graph_state_source"] == "lane_graph"
    assert graph_authority["merge_state"] == "running"
    assert graph_authority["graph_terminal"] is False
    assert graph_authority["graph_lineage_status"] == "incomplete_termination"
    assert graph_authority["unmerged_terminal_lineages"] == ["lane-unmerged"]
    assert graph_authority["graph_aggregation"]["aggregation_id"] == "agg-stale"


def test_health_reports_terminate_review_decision_as_terminal_graph(tmp_path):
    graph_id = "graph-review-terminated"
    _write_lineage(tmp_path, [{**_LINEAGE_RECORDS[0], "spawned_graph_id": graph_id}])
    _write_lane_graph(
        tmp_path,
        graph_id,
        [{"feature_id": "lane-terminated", "prompt": "stop this lane"}],
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-terminated",
                    "status": "failed",
                    "graph_id": graph_id,
                    "review_decision": "terminate",
                }
            ]
        },
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    graph_authority = body["graph_authority"]
    assert body["status"] == "degraded"
    assert graph_authority["graph_state_source"] == "lane_graph"
    assert graph_authority["merge_state"] == "terminated"
    assert graph_authority["graph_terminal"] is True
    assert graph_authority["graph_lineage_status"] == "terminated"
    assert graph_authority["open_lineage_count"] == 0
    assert graph_authority["failed_lineages"] == ["lane-terminated"]
    assert graph_authority["unmerged_terminal_lineages"] == []


def test_health_reports_merged_graph_from_current_lane_state_without_aggregation(tmp_path):
    graph_id = "graph-current-merged"
    _write_lineage(tmp_path, [{**_LINEAGE_RECORDS[0], "spawned_graph_id": graph_id}])
    _write_lane_graph(
        tmp_path,
        graph_id,
        [{"feature_id": "lane-merged", "prompt": "done"}],
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-merged", "status": "merged", "graph_id": graph_id}
            ]
        },
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    graph_authority = response.json()["graph_authority"]
    assert graph_authority["graph_state_source"] == "lane_graph"
    assert graph_authority["merge_state"] == "merged"
    assert graph_authority["graph_lineage_status"] == "merged"
    assert graph_authority["graph_terminal"] is True
    assert graph_authority["open_lineage_count"] == 0


def test_health_includes_patch_forward_descendant_in_graph_lineage_state(tmp_path):
    graph_id = "graph-patch-forward-open"
    _write_lineage(tmp_path, [{**_LINEAGE_RECORDS[0], "spawned_graph_id": graph_id}])
    _write_lane_graph(
        tmp_path,
        graph_id,
        [{"feature_id": "lane-original", "prompt": "original"}],
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-original", "status": "failed", "graph_id": graph_id},
                {
                    "feature_id": "lane-patch",
                    "status": "pending",
                    "graph_id": graph_id,
                    "source_lane_id": "lane-original",
                },
            ]
        },
    )
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-stale-terminal",
                "run_id": graph_id,
                "resolution_id": f"res-{graph_id}",
                "graph_id": graph_id,
                "status": "terminated",
                "terminal": True,
                "reason": "stale failure",
                "created_at": "2026-05-01T12:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 200
    graph_authority = response.json()["graph_authority"]
    assert graph_authority["merge_state"] == "running"
    assert graph_authority["graph_lineage_status"] == "open"
    assert graph_authority["open_lane_lineages"] == ["lane-patch"]
    assert graph_authority["open_lineage_count"] == 1


# ---------------------------------------------------------------------------
# Self-evolution audit endpoint tests  (GET /api/self-evolution/audit)
# ---------------------------------------------------------------------------


def _write_se_store(tmp_path: Path, collection: str, key: str, records: list) -> None:
    """Write records into the self_evolution store directory."""
    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)
    _write_json(se_dir / f"{collection}.json", {key: records})


_SE_LINEAGE = {
    "lineage_id": "lin-se-1",
    "source_run_id": "run-se-1",
    "source_resolution_id": "res-se-0",
    "evidence_bundle_id": "evbundle_8b1e193a9751458d8d62032cfb55a17c",
    "evolution_proposal_id": "prop-se-1",
    "review_decision_id": "rev-se-1",
    "guardrail_decision_id": "guard-se-1",
    "spawned_conversation_id": "conv-se-1",
    "spawned_proposal_id": "prop-se-2",
    "spawned_resolution_id": "res-se-1",
    "spawned_graph_id": "graph-se-1",
    "blueprint_set_id": "bp-se-1",
    "target_track_ids": ["dashboard_auditability"],
    "terminal_aggregation_ref": "agg-se-1",
    "created_at": "2026-05-28T10:00:00Z",
}

_SE_PROPOSAL = {
    "proposal_id": "prop-se-1",
    "source_run_id": "run-se-1",
    "blueprint_set_id": "bp-se-1",
    "target_track_ids": ["dashboard_auditability"],
    "status": "landed",
    "draft_version": 1,
    "author_session_id": "sess-se-1",
    "scope_summary": "Add generated_at and guardrail join to audit writer",
    "why_now": "Contract gap identified in evidence bundle",
    "evidence_bundle_id": "evbundle_8b1e193a9751458d8d62032cfb55a17c",
    "candidate_graph": {
        "lanes": [
            {
                "feature_id": "audit-writer-generated-at",
                "feature_group": "dashboard_auditability/audit_writer",
                "prompt": "Add generated_at field",
            },
            {
                "feature_id": "audit-writer-guardrail-join",
                "feature_group": "dashboard_auditability/audit_writer",
                "prompt": "Join guardrail decision",
            },
            {
                "feature_id": "audit-writer-spawned-resolution",
                "feature_group": "dashboard_auditability/conversations",
                "prompt": "Add spawned_resolution_id to conversations",
            },
        ]
    },
    "review_status": "approve",
    "spawned_conversation_id": "conv-se-1",
    "spawned_resolution_id": "res-se-1",
    "created_at": "2026-05-28T10:00:00Z",
}

_SE_AGGREGATION = {
    "aggregation_id": "agg-se-1",
    "run_id": "run-se-1",
    "resolution_id": "res-se-0",
    "graph_id": "graph-se-0",
    "status": "merged",
    "terminal": True,
    "reason": "all lanes merged",
    "lane_counts": {"merged": 3},
    "lane_statuses": [],
    "open_lineages": [],
    "blocked_objects": [{"lane_id": "blocked-lane", "missing_input": "spec"}],
    "final_action_holds": [{"lane_id": "hold-lane", "action": "merge"}],
    "verdict_lineage": [],
    "created_at": "2026-05-28T09:00:00Z",
}

_SE_CONVERSATION = {
    "conversation_id": "conv-se-1",
    "proposal_id": "prop-se-1",
    "source_run_id": "run-se-1",
    "created_by": "system",
    "created_at": "2026-05-28T10:00:00Z",
}

_SE_GUARDRAIL = {
    "decision_id": "guard-se-1",
    "proposal_id": "prop-se-1",
    "action": "continue",
    "rationale": "Budget within limits; no duplicate signal detected.",
    "source_run_id": "run-se-1",
    "reason_codes": ["budget_ok", "dedup_clear"],
    "budget_window_id": "bw-se-1",
    "dedup_key": None,
    "terminal_aggregation_ref": "agg-se-1",
    "checks": {"budget": True, "dedup": True},
    "created_at": "2026-05-28T10:00:00Z",
}


def _write_full_se_store(tmp_path: Path) -> None:
    _write_se_store(tmp_path, "lineage", "lineage", [_SE_LINEAGE])
    _write_se_store(tmp_path, "proposals", "proposals", [_SE_PROPOSAL])
    _write_se_store(tmp_path, "run_aggregations", "aggregations", [_SE_AGGREGATION])
    _write_se_store(tmp_path, "conversations", "conversations", [_SE_CONVERSATION])
    _write_se_store(tmp_path, "guardrail_decisions", "guardrail_decisions", [_SE_GUARDRAIL])


def test_self_evolution_audit_returns_schema_version_and_generated_at(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1"
    assert "generated_at" in body
    # generated_at must be a non-empty ISO-8601 string
    assert isinstance(body["generated_at"], str)
    assert body["generated_at"].endswith("Z")


def test_self_evolution_audit_entry_has_spawned_resolution_id(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["spawned_resolution_id"] == "res-se-1"


def test_self_evolution_audit_entry_proposal_nested_object(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    proposal = entry["proposal"]
    assert proposal["proposal_id"] == "prop-se-1"
    assert proposal["scope_summary"] == "Add generated_at and guardrail join to audit writer"
    assert proposal["status"] == "landed"
    assert proposal["review_status"] == "approve"
    assert proposal["target_track_ids"] == ["dashboard_auditability"]


def test_self_evolution_audit_entry_proposal_candidate_lane_count(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    proposal = response.json()["entries"][0]["proposal"]
    assert proposal["candidate_lane_count"] == 3


def test_self_evolution_audit_entry_proposal_feature_groups(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    proposal = response.json()["entries"][0]["proposal"]
    # Two distinct feature_group values, sorted
    assert proposal["feature_groups"] == [
        "dashboard_auditability/audit_writer",
        "dashboard_auditability/conversations",
    ]


def test_self_evolution_audit_entry_aggregation_nested_object(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    aggregation = response.json()["entries"][0]["aggregation"]
    assert aggregation["aggregation_id"] == "agg-se-1"
    assert aggregation["status"] == "merged"
    assert aggregation["terminal"] is True
    assert aggregation["lane_counts"] == {"merged": 3}


def test_self_evolution_audit_entry_aggregation_blocked_object_count(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    aggregation = response.json()["entries"][0]["aggregation"]
    # _SE_AGGREGATION has 1 blocked_object
    assert aggregation["blocked_object_count"] == 1


def test_self_evolution_audit_entry_aggregation_final_action_hold_count(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    aggregation = response.json()["entries"][0]["aggregation"]
    # _SE_AGGREGATION has 1 final_action_hold
    assert aggregation["final_action_hold_count"] == 1


def test_self_evolution_audit_entry_guardrail_decision_joined(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert "guardrail_decision" in entry
    gd = entry["guardrail_decision"]
    assert gd["decision_id"] == "guard-se-1"
    assert gd["action"] == "continue"
    assert gd["rationale"] == "Budget within limits; no duplicate signal detected."
    assert gd["reason_codes"] == ["budget_ok", "dedup_clear"]


def test_self_evolution_audit_entry_no_guardrail_when_missing(tmp_path):
    # Write store without guardrail decisions
    _write_se_store(tmp_path, "lineage", "lineage", [_SE_LINEAGE])
    _write_se_store(tmp_path, "proposals", "proposals", [_SE_PROPOSAL])

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert "guardrail_decision" not in entry


def test_self_evolution_audit_entry_conversation_nested_object(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert "conversation" in entry
    conv = entry["conversation"]
    assert conv["conversation_id"] == "conv-se-1"
    assert conv["created_by"] == "system"
    assert conv["created_at"] == "2026-05-28T10:00:00Z"


def test_self_evolution_audit_entry_unknown_proposal_fallback(tmp_path):
    # Lineage references a proposal that doesn't exist in the store
    _write_se_store(tmp_path, "lineage", "lineage", [_SE_LINEAGE])
    # No proposals written

    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    proposal = entry["proposal"]
    assert proposal["proposal_id"] == "prop-se-1"
    assert proposal["status"] == "unknown"
    assert proposal["candidate_lane_count"] == 0
    assert proposal["feature_groups"] == []


def test_self_evolution_audit_empty_store_returns_empty_entries(tmp_path):
    response = _client(tmp_path).get("/api/self-evolution/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1"
    assert "generated_at" in body
    assert body["entries"] == []


# ---------------------------------------------------------------------------
# Self-evolution conversations endpoint tests
# (GET /api/self-evolution/conversations)
# ---------------------------------------------------------------------------


def test_self_evolution_conversations_includes_spawned_resolution_id(tmp_path):
    _write_full_se_store(tmp_path)

    response = _client(tmp_path).get("/api/self-evolution/conversations")

    assert response.status_code == 200
    conversations = response.json()["conversations"]
    assert len(conversations) == 1
    conv = conversations[0]
    # spawned_resolution_id comes from the joined proposal
    assert conv["spawned_resolution_id"] == "res-se-1"


def test_self_evolution_conversations_spawned_resolution_id_null_when_no_proposal(tmp_path):
    # Conversation with no matching proposal
    _write_se_store(tmp_path, "conversations", "conversations", [_SE_CONVERSATION])
    # No proposals

    response = _client(tmp_path).get("/api/self-evolution/conversations")

    assert response.status_code == 200
    conv = response.json()["conversations"][0]
    assert conv["spawned_resolution_id"] is None


def test_self_evolution_conversations_spawned_resolution_id_null_when_proposal_not_landed(
    tmp_path,
):
    proposal_not_landed = {**_SE_PROPOSAL, "spawned_resolution_id": None, "status": "approved"}
    _write_se_store(tmp_path, "conversations", "conversations", [_SE_CONVERSATION])
    _write_se_store(tmp_path, "proposals", "proposals", [proposal_not_landed])

    response = _client(tmp_path).get("/api/self-evolution/conversations")

    assert response.status_code == 200
    conv = response.json()["conversations"][0]
    assert conv["spawned_resolution_id"] is None


# ---------------------------------------------------------------------------
# Lane-graphs endpoints  (GET /api/lane-graphs, GET /api/lane-graphs/{graph_id})
# Lane: self-evolution-dashboard_auditability-res_9b183490337e4f90b3082bbad2738c42-graph-v1
# Evidence bundle: evbundle_8b1e193a9751458d8d62032cfb55a17c
# ---------------------------------------------------------------------------

_GRAPH_A = {
    "id": "graph-a",
    "conversation_id": "conv-a",
    "resolution_id": "res-a",
    "version": 1,
    "status": "planned",
    "lanes": [
        {
            "feature_id": "lane-a1",
            "prompt": "Build feature A",
            "task_type": "execute",
            "priority": 0,
            "capabilities": ["code"],
            "depends_on": [],
        }
    ],
}

_GRAPH_B = {
    "id": "graph-b",
    "conversation_id": "conv-b",
    "resolution_id": "res-b",
    "version": 2,
    "status": "planned",
    "lanes": [
        {
            "feature_id": "lane-b1",
            "prompt": "Build feature B",
            "task_type": "execute",
            "priority": 0,
            "capabilities": ["code"],
            "depends_on": [],
        },
        {
            "feature_id": "lane-b2",
            "prompt": "Test feature B",
            "task_type": "execute",
            "priority": 0,
            "capabilities": ["test"],
            "depends_on": ["lane-b1"],
        },
    ],
}


def _write_lane_graphs(tmp_path: Path, *graphs: dict) -> None:
    graphs_dir = tmp_path / "lane_graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    for graph in graphs:
        _write_json(graphs_dir / f"{graph['id']}.json", graph)


def test_lane_graphs_returns_empty_when_no_directory(tmp_path):
    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    body = response.json()
    assert body["graphs"] == []
    assert body["total"] == 0


def test_lane_graphs_returns_empty_when_directory_is_empty(tmp_path):
    (tmp_path / "lane_graphs").mkdir()

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    body = response.json()
    assert body["graphs"] == []
    assert body["total"] == 0


def test_lane_graphs_returns_all_graphs(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A, _GRAPH_B)

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    graph_ids = {g["id"] for g in body["graphs"]}
    assert graph_ids == {"graph-a", "graph-b"}


def test_lane_graphs_each_entry_includes_derived_state(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-a1", "status": "merged", "graph_id": "graph-a"}
            ]
        },
    )

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    graph = response.json()["graphs"][0]
    assert "derived_state" in graph
    ds = graph["derived_state"]
    assert ds["status"] == "merged"
    assert ds["terminal"] is True


def test_lane_graphs_derived_state_running_when_lane_not_terminal(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-a1", "status": "dispatched", "graph_id": "graph-a"}
            ]
        },
    )

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    ds = response.json()["graphs"][0]["derived_state"]
    assert ds["status"] == "running"
    assert ds["terminal"] is False


def test_lane_graphs_derived_state_empty_when_no_lanes_file(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    # No feature_lanes.json

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    graph = response.json()["graphs"][0]
    assert "derived_state" in graph


def test_lane_graphs_includes_lane_definitions(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_B)

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    graph = response.json()["graphs"][0]
    assert graph["id"] == "graph-b"
    assert len(graph["lanes"]) == 2
    lane_ids = {lane["feature_id"] for lane in graph["lanes"]}
    assert lane_ids == {"lane-b1", "lane-b2"}


def test_lane_graph_detail_returns_404_for_unknown_graph(tmp_path):
    response = _client(tmp_path).get("/api/lane-graphs/nonexistent-graph")

    assert response.status_code == 404


def test_lane_graph_detail_returns_graph_with_derived_state(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {"feature_id": "lane-a1", "status": "merged", "graph_id": "graph-a"}
            ]
        },
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    body = response.json()
    assert "graph" in body
    assert body["graph"]["id"] == "graph-a"
    assert body["graph"]["conversation_id"] == "conv-a"
    assert body["graph"]["resolution_id"] == "res-a"
    assert "derived_state" in body["graph"]
    assert body["graph"]["derived_state"]["status"] == "merged"


def test_lane_graph_detail_includes_lineage_when_present(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_lineage(
        tmp_path,
        [
            {
                "lineage_id": "lin-for-a",
                "source_run_id": "run-prev",
                "source_resolution_id": "res-prev",
                "evidence_bundle_id": "evbundle_8b1e193a9751458d8d62032cfb55a17c",
                "evolution_proposal_id": "prop-for-a",
                "review_decision_id": "rev-for-a",
                "guardrail_decision_id": "guard-for-a",
                "spawned_conversation_id": "conv-for-a",
                "spawned_proposal_id": "prop-for-a2",
                "spawned_resolution_id": "res-for-a",
                "spawned_graph_id": "graph-a",
                "blueprint_set_id": "bp-1",
                "target_track_ids": ["dashboard_auditability"],
                "created_at": "2026-05-28T10:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    body = response.json()
    assert body["lineage"] is not None
    assert body["lineage"]["lineage_id"] == "lin-for-a"
    assert body["lineage"]["source_run_id"] == "run-prev"
    assert body["lineage"]["target_track_ids"] == ["dashboard_auditability"]


def test_lane_graph_detail_lineage_null_when_no_matching_record(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    # Lineage records exist but none reference graph-a
    _write_lineage(tmp_path, _LINEAGE_RECORDS)

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    assert response.json()["lineage"] is None


def test_lane_graph_detail_lineage_null_when_no_lineage_file(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    assert response.json()["lineage"] is None


def test_lane_graph_detail_includes_aggregation_when_present(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-for-a",
                "run_id": "graph-a",
                "resolution_id": "res-a",
                "graph_id": "graph-a",
                "status": "merged",
                "terminal": True,
                "reason": "all lanes merged",
                "created_at": "2026-05-28T10:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    body = response.json()
    assert body["aggregation"] is not None
    assert body["aggregation"]["aggregation_id"] == "agg-for-a"
    assert body["aggregation"]["status"] == "merged"
    assert body["aggregation"]["terminal"] is True


def test_lane_graph_detail_aggregation_null_when_no_matching_record(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    # Aggregations exist but none reference graph-a
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-other",
                "run_id": "other-graph",
                "resolution_id": "res-other",
                "graph_id": "other-graph",
                "status": "running",
                "terminal": False,
                "reason": "still running",
                "created_at": "2026-05-28T10:00:00Z",
            }
        ],
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    assert response.json()["aggregation"] is None


def test_lane_graph_detail_aggregation_null_when_no_aggregation_file(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    assert response.json()["aggregation"] is None


def test_lane_graph_detail_uses_latest_aggregation_when_multiple_exist(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_aggregations(
        tmp_path,
        [
            {
                "aggregation_id": "agg-old",
                "run_id": "graph-a",
                "resolution_id": "res-a",
                "graph_id": "graph-a",
                "status": "running",
                "terminal": False,
                "reason": "old state",
                "created_at": "2026-05-28T09:00:00Z",
            },
            {
                "aggregation_id": "agg-new",
                "run_id": "graph-a",
                "resolution_id": "res-a",
                "graph_id": "graph-a",
                "status": "merged",
                "terminal": True,
                "reason": "all lanes merged",
                "created_at": "2026-05-28T10:00:00Z",
            },
        ],
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    assert response.json()["aggregation"]["aggregation_id"] == "agg-new"


def test_lane_graph_detail_uses_latest_lineage_when_multiple_reference_same_graph(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_lineage(
        tmp_path,
        [
            {
                "lineage_id": "lin-old",
                "source_run_id": "run-old",
                "source_resolution_id": "res-old",
                "evidence_bundle_id": "evbundle_8b1e193a9751458d8d62032cfb55a17c",
                "evolution_proposal_id": "prop-old",
                "review_decision_id": "rev-old",
                "guardrail_decision_id": "guard-old",
                "spawned_conversation_id": "conv-old",
                "spawned_proposal_id": "prop-old2",
                "spawned_resolution_id": "res-old2",
                "spawned_graph_id": "graph-a",
                "blueprint_set_id": "bp-1",
                "target_track_ids": ["dashboard_auditability"],
                "created_at": "2026-05-27T10:00:00Z",
            },
            {
                "lineage_id": "lin-new",
                "source_run_id": "run-new",
                "source_resolution_id": "res-new",
                "evidence_bundle_id": "evbundle_8b1e193a9751458d8d62032cfb55a17c",
                "evolution_proposal_id": "prop-new",
                "review_decision_id": "rev-new",
                "guardrail_decision_id": "guard-new",
                "spawned_conversation_id": "conv-new",
                "spawned_proposal_id": "prop-new2",
                "spawned_resolution_id": "res-new2",
                "spawned_graph_id": "graph-a",
                "blueprint_set_id": "bp-1",
                "target_track_ids": ["dashboard_auditability"],
                "created_at": "2026-05-28T10:00:00Z",
            },
        ],
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    assert response.json()["lineage"]["lineage_id"] == "lin-new"


def test_lane_graphs_list_sorted_newest_first_by_id(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A, _GRAPH_B)

    response = _client(tmp_path).get("/api/lane-graphs")

    assert response.status_code == 200
    ids = [g["id"] for g in response.json()["graphs"]]
    # graph-b > graph-a lexicographically
    assert ids == ["graph-b", "graph-a"]


def test_lane_graph_detail_blocked_for_input_reflected_in_derived_state(tmp_path):
    _write_lane_graphs(tmp_path, _GRAPH_A)
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "lane-a1",
                    "status": "blocked_for_input",
                    "graph_id": "graph-a",
                    "clarification_request": {
                        "missing_input": "need API spec",
                        "owner": "human",
                        "resume_path": "provide spec and reproject",
                    },
                }
            ]
        },
    )

    response = _client(tmp_path).get("/api/lane-graphs/graph-a")

    assert response.status_code == 200
    ds = response.json()["graph"]["derived_state"]
    assert ds["status"] == "blocked_for_input"
    assert ds["terminal"] is True
    assert len(ds["blocked_objects"]) == 1
    assert ds["blocked_objects"][0]["lane_id"] == "lane-a1"
