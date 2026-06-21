import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

import xmuse_core.platform.mcp_tools as mcp_tools_module
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.platform.lane_context import build_lane_context_bundle
from xmuse_core.platform.lane_takeover import build_lane_takeover_bundle
from xmuse_core.platform.mcp_tools import McpToolHandler
from xmuse_core.platform.read_contracts import (
    READ_CONTRACT_TOOL_SCHEMAS,
    build_blueprint_contract,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.platform.takeover_actions import record_takeover_started
from xmuse_core.structuring.feature_plan_store import (
    FeaturePlanStore,
    read_approved_mission_blueprint,
)
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    FeaturePlanProposal,
    FeaturePlanProposalApproval,
    FeaturePlanProposalStatus,
    LaneGraph,
    LaneNode,
    ReviewDecision,
    ReviewTask,
    ReviewTaskStatus,
    ReviewVerdict,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def setup(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix bug",
            "worktree": str(tmp_path / "wt"),
            "graph_id": "graph-alpha",
            "review_task_id": "task-1",
            "review_verdict_id": "verdict-1",
        },
    ]}))
    wt = tmp_path / "wt"
    wt.mkdir()
    gates_dir = tmp_path / "logs" / "gates" / "lane-1"
    gates_dir.mkdir(parents=True)
    (gates_dir / "report.json").write_text(json.dumps({
        "passed": True, "feature_id": "lane-1", "profile_ids": ["linter-only"],
    }))
    ek_path = tmp_path / "error_knowledge.json"
    ek_path.write_text(json.dumps({"entries": [
        {"id": "ek-1", "pit": "mypy arg-type", "root_cause": "wrong type",
         "scope": "type errors"},
    ]}))
    review_task = ReviewTask(
        task_id="task-1",
        lane_id="lane-1",
        graph_id="graph-alpha",
        lane_prompt="fix bug",
        gate_report_ref="logs/gates/lane-1/report.json",
        status=ReviewTaskStatus.VERDICT_EMITTED,
        verdict_id="verdict-1",
        created_at="2026-05-31T10:00:00Z",
        updated_at="2026-05-31T10:05:00Z",
    )
    review_verdict = ReviewVerdict(
        id="verdict-1",
        lane_id="lane-1",
        decision=ReviewDecision.MERGE,
        summary="Looks good.",
        evidence_refs=["logs/gates/lane-1/report.json"],
        task_id="task-1",
        created_at="2026-05-31T10:05:00Z",
    )
    (tmp_path / "review_plane.json").write_text(
        json.dumps(
            {
                "review_tasks": [review_task.model_dump(mode="json")],
                "review_verdicts": [review_verdict.model_dump(mode="json")],
            }
        )
    )
    graph_set = FeatureGraphSet(
        id="graph-set-1",
        feature_plan=FeaturePlan(
            id="plan-1",
            conversation_id="conv-1",
            resolution_id="res-1",
            version=1,
            features=[
                FeaturePlanFeature(
                    feature_id="feature-alpha",
                    title="Alpha",
                    goal="Ship the lane contract scaffold.",
                    acceptance_criteria=["Read-only graph-set summaries are available."],
                    graph_id="graph-alpha",
                )
            ],
        ),
        graphs=[
            LaneGraph(
                id="graph-alpha",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=1,
                lanes=[
                    LaneNode(
                        feature_id="lane-1",
                        prompt="fix bug",
                        capabilities=["code", "test"],
                        feature_group="b5/contracts",
                    )
                ],
            )
        ],
    )
    lane_graphs_dir = tmp_path / "lane_graphs"
    lane_graphs_dir.mkdir()
    (lane_graphs_dir / "graph-set-1.json").write_text(
        json.dumps(graph_set.model_dump(mode="json")),
    )
    sm = LaneStateMachine(lanes_path)
    status_changes = []
    handler = McpToolHandler(
        state_machine=sm,
        xmuse_root=tmp_path,
        on_status_change=lambda lid, s: status_changes.append((lid, s)),
    )
    return handler, sm, tmp_path, status_changes


def test_get_lane(setup):
    handler, _, _, _ = setup
    result = handler.call("get_lane", {"lane_id": "lane-1"})
    assert result["feature_id"] == "lane-1"
    assert result["status"] == "gated"


def test_get_gate_report(setup):
    handler, _, _, _ = setup
    result = handler.call("get_gate_report", {"lane_id": "lane-1"})
    assert result["passed"] is True


def test_get_diff_reports_untracked_worker_outputs(tmp_path: Path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(worktree, "init")
    _git(worktree, "config", "user.email", "xmuse@example.test")
    _git(worktree, "config", "user.name", "xmuse test")
    _git(worktree, "add", "tracked.txt")
    _git(worktree, "commit", "-m", "base")

    artifact = worktree / "runtime_artifacts" / "loop7k.txt"
    artifact.parent.mkdir()
    artifact.write_text("LOOP7K\n", encoding="utf-8")

    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-untracked",
                        "status": "reviewed",
                        "prompt": "review artifact",
                        "worktree": str(worktree),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    handler = McpToolHandler(
        state_machine=LaneStateMachine(lanes_path),
        xmuse_root=tmp_path,
    )

    result = handler.call("get_diff", {"lane_id": "lane-untracked"})

    assert result["returncode"] == 0
    assert result["untracked_files"] == ["runtime_artifacts/loop7k.txt"]
    assert "runtime_artifacts/loop7k.txt" in result["status_short"]
    assert result["has_untracked"] is True


def test_query_knowledge(setup):
    handler, _, _, _ = setup
    result = handler.call("query_knowledge", {"query": "mypy type", "top_k": 3})
    assert len(result["matches"]) == 1
    assert result["matches"][0]["entry"]["id"] == "ek-1"


def test_read_lane_contract_returns_read_only_scaffold(setup):
    handler, _, _, _ = setup

    result = handler.call("read_lane_contract", {"lane_id": "lane-1"})

    assert result["kind"] == "lane_contract"
    assert result["read_only"] is True
    assert result["lane"]["feature_id"] == "lane-1"
    assert result["refs"]["gate_report"] == {
        "tool": "get_gate_report",
        "arguments": {"lane_id": "lane-1"},
    }
    assert result["refs"]["review"] == {
        "tool": "read_review_contract",
        "arguments": {"lane_id": "lane-1"},
    }
    assert result["refs"]["graph_set"] == {
        "tool": "read_graph_set_contract",
        "arguments": {"graph_set_id": "graph-set-1"},
    }
    assert result["refs"]["graph_set_summary"] == {
        "tool": "read_graph_set_summary",
        "arguments": {"graph_set_id": "graph-set-1"},
    }


def _seed_blueprint_feature_plan_contracts(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix bug",
            "graph_id": "graph-alpha",
        },
    ]}))
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Alpha mission")
    proposal = chat.create_proposal(
        conversation_id=conversation.id,
        author="architect",
        proposal_type="mission_blueprint",
        content=json.dumps(
            {
                "type": "mission_blueprint",
                "title": "Alpha blueprint",
                "body": "Ship the B5 read-only peer contracts.",
                "acceptance_criteria": ["Peers can read blueprint and plan state."],
                "references": ["doc:alpha-blueprint"],
            }
        ),
        references=["doc:alpha-blueprint"],
    )
    resolution = chat.approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve alpha blueprint",
    )
    blueprint = read_approved_mission_blueprint(resolution)
    feature = FeaturePlanFeature(
        feature_id="feature-alpha",
        title="Alpha",
        goal="Ship the lane contract scaffold.",
        acceptance_criteria=["Read-only graph-set summaries are available."],
        graph_id="graph-alpha",
        blueprint_refs=[blueprint.blueprint_ref],
    )
    FeaturePlanStore(tmp_path / "feature_plans").save(
        FeaturePlanProposal(
            id="plan-1",
            conversation_id=conversation.id,
            source_blueprint=blueprint,
            features=[feature],
            status=FeaturePlanProposalStatus.APPROVED,
            approval=FeaturePlanProposalApproval(
                approved_by=["human"],
                approval_mode="manual",
                approved_at=resolution.created_at,
            ),
        )
    )
    graph_set = FeatureGraphSet(
        id="graph-set-1",
        feature_plan=FeaturePlan(
            id="plan-1",
            conversation_id=conversation.id,
            resolution_id=resolution.id,
            version=1,
            features=[feature],
        ),
        graphs=[
            LaneGraph(
                id="graph-alpha",
                conversation_id=conversation.id,
                resolution_id=resolution.id,
                version=1,
                lanes=[LaneNode(feature_id="lane-1", prompt="fix bug")],
            )
        ],
    )
    lane_graphs_dir = tmp_path / "lane_graphs"
    lane_graphs_dir.mkdir()
    (lane_graphs_dir / "graph-set-1.json").write_text(
        json.dumps(graph_set.model_dump(mode="json")),
    )
    handler = McpToolHandler(
        state_machine=LaneStateMachine(lanes_path),
        xmuse_root=tmp_path,
    )
    return handler, {"blueprint_ref": blueprint.blueprint_ref, "resolution_id": resolution.id}


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_writer_lease(
    lanes_path,
    *,
    lease_id: str = "lease-guard-current",
    runner_id: str = "runner-guard",
):
    lease_path = lanes_path.with_name(f"{lanes_path.name}.writer_lease.json")
    lease_path.write_text(
        json.dumps(
            {
                "runner_id": runner_id,
                "lease_id": lease_id,
                "heartbeat_at": 1_717_171_717.0,
                "expires_at": 4_102_444_800.0,
            }
        )
    )
    return lease_id


def _takeover_guard(*, sm: LaneStateMachine, xmuse_root, lane_id: str, lease_id: str) -> dict:
    lane = sm.get_lane(lane_id)
    all_lanes = sm.get_lanes()
    lane_context = build_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    takeover_bundle = build_lane_takeover_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    return {
        "lane_status": str(lane["status"]),
        "projection_revision": sm.current_projection_revision(),
        "lease_id": lease_id,
        "lane_context_hash": _stable_hash(lane_context["context_contract"]),
        "evidence_bundle_hash": _stable_hash(asdict(takeover_bundle)),
    }


def test_read_review_contract_returns_latest_review_records(setup):
    handler, _, _, _ = setup

    result = handler.call("read_review_contract", {"lane_id": "lane-1"})

    assert result["kind"] == "review_contract"
    assert result["read_only"] is True
    assert result["lane_id"] == "lane-1"
    assert result["counts"] == {"tasks": 1, "verdicts": 1}
    assert result["latest_task"]["task_id"] == "task-1"
    assert result["latest_verdict"]["id"] == "verdict-1"
    assert result["latest_verdict"]["decision"] == "merge"


def test_read_review_contract_does_not_create_store_when_absent(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [{"feature_id": "lane-1", "status": "gated"}]}))
    handler = McpToolHandler(
        state_machine=LaneStateMachine(lanes_path),
        xmuse_root=tmp_path / "missing-xmuse-root",
    )

    result = handler.call("read_review_contract", {"lane_id": "lane-1"})

    assert result["counts"] == {"tasks": 0, "verdicts": 0}
    assert result["latest_task"] is None
    assert result["latest_verdict"] is None
    assert not (tmp_path / "missing-xmuse-root").exists()


def test_read_review_contract_does_not_create_lock_file_for_existing_store(setup):
    handler, _, tmp_path, _ = setup
    lock_path = tmp_path / "review_plane.json.lock"
    assert not lock_path.exists()

    result = handler.call("read_review_contract", {"lane_id": "lane-1"})

    assert result["counts"] == {"tasks": 1, "verdicts": 1}
    assert not lock_path.exists()


def test_read_health_contract_returns_read_only_health_model(setup):
    handler, _, _, _ = setup

    result = handler.call("read_health_contract", {})

    assert result["kind"] == "health_contract"
    assert result["read_only"] is True
    assert result["run_health"]["counts"]["terminal"] == 0
    assert result["run_health"]["processes"]["runner_count"] == 0
    assert result["run_health"]["processes"]["mcp_count"] == 0


def test_read_blueprint_contract_returns_approved_blueprint_and_feature_plan_refs(tmp_path):
    handler, meta = _seed_blueprint_feature_plan_contracts(tmp_path)

    result = handler.call(
        "read_blueprint_contract",
        {"blueprint_ref": meta["blueprint_ref"]},
    )

    assert result["kind"] == "blueprint_contract"
    assert result["read_only"] is True
    assert result["blueprint"]["title"] == "Alpha blueprint"
    assert result["blueprint"]["body"] == "Ship the B5 read-only peer contracts."
    assert result["counts"] == {
        "acceptance_criteria": 1,
        "references": 1,
        "related_feature_plans": 1,
    }
    assert result["refs"]["feature_plans"] == [
        {
            "tool": "read_feature_plan_contract",
            "arguments": {"feature_plan_id": "plan-1"},
        }
    ]


def test_read_blueprint_contract_omits_unapproved_or_unbacked_feature_plans(tmp_path):
    handler, meta = _seed_blueprint_feature_plan_contracts(tmp_path)
    stored = FeaturePlanStore(tmp_path / "feature_plans").get("plan-1")
    FeaturePlanStore(tmp_path / "feature_plans").save(
        FeaturePlanProposal(
            id="draft-plan",
            conversation_id=stored.conversation_id,
            source_blueprint=stored.source_blueprint,
            features=[
                FeaturePlanFeature(
                    feature_id="draft-feature",
                    title="Draft",
                    goal="This proposal is not approved yet.",
                    acceptance_criteria=["It should not be advertised."],
                    graph_id="graph-draft",
                    blueprint_refs=[stored.source_blueprint.blueprint_ref],
                )
            ],
        )
    )
    FeaturePlanStore(tmp_path / "feature_plans").save(
        stored.model_copy(update={"id": "approved-without-graph"}, deep=True)
    )

    result = handler.call(
        "read_blueprint_contract",
        {"blueprint_ref": meta["blueprint_ref"]},
    )

    assert result["refs"]["feature_plans"] == [
        {
            "tool": "read_feature_plan_contract",
            "arguments": {"feature_plan_id": "plan-1"},
        }
    ]


def test_read_feature_plan_contract_returns_authoritative_plan_and_refs(tmp_path):
    handler, _ = _seed_blueprint_feature_plan_contracts(tmp_path)

    result = handler.call("read_feature_plan_contract", {"feature_plan_id": "plan-1"})

    assert result["kind"] == "feature_plan_contract"
    assert result["read_only"] is True
    assert result["feature_plan"]["id"] == "plan-1"
    assert result["source_blueprint"]["title"] == "Alpha blueprint"
    assert result["summary"]["counts"] == {
        "features": 1,
        "graphs": 1,
        "dependency_edges": 0,
    }
    assert result["refs"]["blueprint"] == {
        "tool": "read_blueprint_contract",
        "arguments": {"blueprint_ref": result["source_blueprint"]["blueprint_ref"]},
    }
    assert result["refs"]["graph_set"] == {
        "tool": "read_graph_set_contract",
        "arguments": {"graph_set_id": "graph-set-1"},
    }
    assert result["refs"]["graph_set_summary"] == {
        "tool": "read_graph_set_summary",
        "arguments": {"graph_set_id": "graph-set-1"},
    }


def test_read_feature_plan_contract_rejects_direct_unapproved_plan_access(tmp_path):
    handler, _ = _seed_blueprint_feature_plan_contracts(tmp_path)
    stored = FeaturePlanStore(tmp_path / "feature_plans").get("plan-1")
    draft_feature = FeaturePlanFeature(
        feature_id="draft-feature",
        title="Draft",
        goal="Draft graph sets are not approved contracts.",
        acceptance_criteria=["Drafts are hidden."],
        graph_id="graph-draft",
        blueprint_refs=[stored.source_blueprint.blueprint_ref],
    )
    FeaturePlanStore(tmp_path / "feature_plans").save(
        FeaturePlanProposal(
            id="draft-plan",
            conversation_id=stored.conversation_id,
            source_blueprint=stored.source_blueprint,
            features=[draft_feature],
        )
    )
    draft_graph_set = FeatureGraphSet(
        id="draft-graph-set",
        feature_plan=FeaturePlan(
            id="draft-plan",
            conversation_id=stored.conversation_id,
            resolution_id=stored.source_blueprint.resolution_id,
            version=1,
            features=[draft_feature],
        ),
        graphs=[
            LaneGraph(
                id="graph-draft",
                conversation_id=stored.conversation_id,
                resolution_id=stored.source_blueprint.resolution_id,
                version=1,
                lanes=[LaneNode(feature_id="draft-lane", prompt="Draft lane.")],
            )
        ],
    )
    (tmp_path / "lane_graphs" / "draft-graph-set.json").write_text(
        json.dumps(draft_graph_set.model_dump(mode="json")),
    )

    result = handler.call("read_feature_plan_contract", {"feature_plan_id": "draft-plan"})
    graph_set = handler.call("read_graph_set_contract", {"graph_set_id": "draft-graph-set"})
    summary = handler.call("read_graph_set_summary", {"graph_set_id": "draft-graph-set"})

    assert "error" in result
    assert "approved feature plan" in result["error"]
    assert "error" in graph_set
    assert "approved feature plan" in graph_set["error"]
    assert "error" in summary
    assert "approved feature plan" in summary["error"]


def test_graph_set_reads_resolve_refs_from_legacy_root_when_lane_graphs_exists(tmp_path):
    handler, _ = _seed_blueprint_feature_plan_contracts(tmp_path)
    (tmp_path / "graph_sets").mkdir()
    (tmp_path / "lane_graphs" / "graph-set-1.json").replace(
        tmp_path / "graph_sets" / "graph-set-1.json"
    )
    (tmp_path / "lane_graphs" / "placeholder.json").write_text("{}")

    feature_plan = handler.call("read_feature_plan_contract", {"feature_plan_id": "plan-1"})
    summary = handler.call("read_graph_set_summary", {"graph_set_id": "graph-set-1"})

    assert feature_plan["refs"]["graph_set_summary"] == {
        "tool": "read_graph_set_summary",
        "arguments": {"graph_set_id": "graph-set-1"},
    }
    assert summary["kind"] == "graph_set_summary"
    assert summary["graph_set_id"] == "graph-set-1"


def test_read_blueprint_contract_schema_requires_lookup_argument() -> None:
    schema = next(
        item for item in READ_CONTRACT_TOOL_SCHEMAS
        if item["name"] == "read_blueprint_contract"
    )

    input_schema = schema["inputSchema"]
    assert input_schema["type"] == "object"
    assert "anyOf" not in input_schema
    assert "oneOf" not in input_schema
    assert "allOf" not in input_schema
    assert {"blueprint_ref", "resolution_id"} == set(input_schema["properties"])

    with pytest.raises(ValueError, match="blueprint_ref or resolution_id is required"):
        build_blueprint_contract(xmuse_root=Path("/tmp/unused"))


def test_read_graph_set_contract_returns_summary_scaffold(setup):
    handler, _, _, _ = setup

    result = handler.call("read_graph_set_contract", {"graph_set_id": "graph-set-1"})

    assert result["kind"] == "graph_set_contract"
    assert result["read_only"] is True
    assert result["graph_set"]["id"] == "graph-set-1"
    assert result["summary"]["counts"]["active"] == 1
    assert result["summary"]["graph_statuses"] == {"feature-alpha": "in_progress"}


def test_read_graph_set_summary_returns_compact_progress_model(tmp_path):
    handler, meta = _seed_blueprint_feature_plan_contracts(tmp_path)

    result = handler.call("read_graph_set_summary", {"graph_set_id": "graph-set-1"})

    assert result["kind"] == "graph_set_summary"
    assert result["read_only"] is True
    assert result["graph_set_id"] == "graph-set-1"
    assert result["summary"]["counts"] == {
        "features": 1,
        "graphs": 1,
        "planned": 0,
        "ready": 0,
        "active": 1,
        "terminal": 0,
        "blocked": 0,
        "unsafe": 0,
    }
    assert result["summary"]["features"] == [
        {
            "feature_id": "feature-alpha",
            "title": "Alpha",
            "graph_id": "graph-alpha",
            "dependencies": [],
            "status": "in_progress",
            "blueprint_refs": [meta["blueprint_ref"]],
        }
    ]
    assert result["refs"]["feature_plan"] == {
        "tool": "read_feature_plan_contract",
        "arguments": {"feature_plan_id": "plan-1"},
    }


def test_read_evidence_refs_returns_auditable_lane_refs(setup):
    handler, _, _, _ = setup

    result = handler.call("read_evidence_refs", {"lane_id": "lane-1"})

    assert result["kind"] == "evidence_refs"
    assert result["read_only"] is True
    assert result["lane_id"] == "lane-1"
    assert result["review_evidence_refs"] == ["logs/gates/lane-1/report.json"]
    assert result["gate_refs"][0]["ref"] == "logs/gates/lane-1/report.json"
    assert result["lane_context_ref"] == "logs/lane_context/lane-1/latest.json"


def test_read_review_verdict_returns_latest_structured_verdict(setup):
    handler, _, _, _ = setup

    result = handler.call("read_review_verdict", {"lane_id": "lane-1"})

    assert result["kind"] == "review_verdict"
    assert result["read_only"] is True
    assert result["lane_id"] == "lane-1"
    assert result["verdict_id"] == "verdict-1"
    assert result["task_id"] == "task-1"
    assert result["latest_verdict"]["decision"] == "merge"
    assert result["latest_verdict"]["evidence_refs"] == [
        "logs/gates/lane-1/report.json"
    ]


def test_read_takeover_context_returns_bounded_bundle_for_lane(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-takeover",
                        "status": "exec_failed",
                        "prompt": "Fix takeover context.",
                        "acceptance_criteria": ["Keep evidence refs auditable."],
                        "blueprint_refs": ["docs/spec.md"],
                        "graph_id": "graph-f4",
                        "conversation_id": "conv-1",
                        "feature_plan_id": "plan-1",
                        "feature_plan_feature_id": "feature-takeover",
                        "review_summary": "Review found missing dependency status.",
                        "review_decision": "rework",
                        "review_history": [
                            {
                                "decision": "rework",
                                "summary": "Prior review flagged missing dependency evidence.",
                            }
                        ],
                        "retry_count": 2,
                        "review_retry_count": 1,
                        "failure_reason": "execution_infra_unavailable",
                        "branch": "lane-takeover-branch",
                        "worktree": "/tmp/lane-takeover",
                        "diff_ref": "logs/diffs/lane-takeover.patch",
                    }
                ]
            }
        )
    )
    gate_dir = tmp_path / "logs" / "gates" / "lane-takeover"
    gate_dir.mkdir(parents=True)
    (gate_dir / "report.json").write_text(json.dumps({"passed": False}))
    sm = LaneStateMachine(lanes_path)
    handler = McpToolHandler(state_machine=sm, xmuse_root=tmp_path)

    result = handler.call("read_takeover_context", {"lane_id": "lane-takeover"})

    assert result["kind"] == "takeover_context"
    assert result["read_only"] is True
    assert result["lane_id"] == "lane-takeover"
    assert result["needs_takeover"] is True
    assert result["takeover_reason"] == "execution_infra_failure"
    assert result["bundle"]["lane_metadata"]["status"] == "exec_failed"
    assert result["bundle"]["worker_diff_refs"] == ["logs/diffs/lane-takeover.patch"]
    assert result["bundle"]["run_health_summary"]["counts"]["takeover_context_needed"] == 1
    assert result["supported_actions"] == [
        "repair_and_merge",
        "requeue_with_context",
        "abandon_lane",
        "self_correction_then_abandon",
        "escalate_to_human_or_outer_god",
    ]
    assert result["bundle"]["gate_report_refs"][0]["ref"] == (
        "logs/gates/lane-takeover/report.json"
    )
    assert "Fix takeover context." in result["prompt_context"]


def test_apply_takeover_decision_routes_repair_and_merge_action(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lane = {
        "feature_id": "lane-takeover",
        "status": "failed",
        "prompt": "Fix takeover action routing.",
        "conversation_id": "conv-1",
        "planning_run_id": "plan-1",
        "graph_id": "graph-1",
        "graph_set_id": "graph-set-1",
        "feature_plan_id": "feature-plan-1",
        "blueprint_refs": ["docs/spec.md"],
        "failure_reason": "merge_failed",
        "gate_passed": False,
        "takeover_attempt_id": "takeover-attempt-1",
        "lease_owner": "review-god/session-1",
        "lease_expires_at": "2026-05-31T20:30:00Z",
        "evidence_bundle_id": "evbundle_123",
        "takeover_attempt_cap": 3,
        "max_attempts_by_reason": {"merge_failed": 3},
        "takeover_cooldown_seconds": 0,
        "terminal_escalation_policy": "escalate_to_human_or_outer_god",
    }
    lanes_path.write_text(json.dumps({"lanes": [lane]}))
    (tmp_path / "logs" / "takeover" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "takeover" / "lane-takeover" / "context.json").write_text(
        json.dumps({"lane_id": "lane-takeover"})
    )
    (tmp_path / "logs" / "diffs").mkdir(parents=True)
    (tmp_path / "logs" / "diffs" / "lane-takeover.patch").write_text("diff --git\n")
    (tmp_path / "logs" / "gates" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "gates" / "lane-takeover" / "report.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "passed": True, "blocking_passed": True})
    )
    (tmp_path / "xmuse" / "reviews" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "xmuse" / "reviews" / "lane-takeover" / "verdict.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "decision": "merge"})
    )
    sm = LaneStateMachine(lanes_path, history_path=tmp_path / "state_history.json")
    lease_id = _write_writer_lease(lanes_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-1",
        "reason": "repair via routed takeover tool",
        "request_id": "req-takeover-routed",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T20:00:00Z",
    )
    handler = McpToolHandler(state_machine=sm, xmuse_root=tmp_path)

    result = handler.call(
        "apply_takeover_decision",
        {
            "audit": audit,
            "guard": _takeover_guard(
                sm=sm,
                xmuse_root=tmp_path,
                lane_id="lane-takeover",
                lease_id=lease_id,
            ),
            "created_at": "2026-05-31T20:00:01Z",
            "decision": {
                "lane_id": "lane-takeover",
                "action": "repair_and_merge",
                "summary": "Repair passed verification and review.",
                "evidence": {
                    "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
                    "change_ref": "logs/diffs/lane-takeover.patch",
                    "verification_ref": "logs/gates/lane-takeover/report.json",
                    "review_verdict_ref": "xmuse/reviews/lane-takeover/verdict.json",
                    "audit_event_ref": started["audit_event_ref"],
                    "chat_card_ref": started["chat_card_ref"],
                },
            },
        },
    )

    assert result["decision_id"].startswith("takeover-")
    updated = sm.get_lane("lane-takeover")
    assert updated["status"] == "merged"
    assert updated["gate_passed"] is True
    assert updated["takeover_action"] == "repair_and_merge"
    assert updated["takeover_resolved_card_ref"] == result["chat_card_ref"]


@pytest.mark.parametrize(
    "missing_field",
    [
        "lane_status",
        "projection_revision",
        "lease_id",
        "lane_context_hash",
        "evidence_bundle_hash",
    ],
)
def test_apply_takeover_decision_requires_complete_takeover_guard(
    tmp_path,
    missing_field: str,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lane = {
        "feature_id": "lane-takeover",
        "status": "failed",
        "prompt": "Fix takeover action routing.",
        "conversation_id": "conv-1",
        "planning_run_id": "plan-1",
        "graph_id": "graph-1",
        "blueprint_refs": ["docs/spec.md"],
        "failure_reason": "merge_failed",
        "gate_passed": False,
    }
    lanes_path.write_text(json.dumps({"lanes": [lane]}))
    (tmp_path / "logs" / "takeover" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "takeover" / "lane-takeover" / "context.json").write_text(
        json.dumps({"lane_id": "lane-takeover"})
    )
    (tmp_path / "logs" / "diffs").mkdir(parents=True)
    (tmp_path / "logs" / "diffs" / "lane-takeover.patch").write_text("diff --git\n")
    (tmp_path / "logs" / "gates" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "gates" / "lane-takeover" / "report.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "passed": True, "blocking_passed": True})
    )
    (tmp_path / "xmuse" / "reviews" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "xmuse" / "reviews" / "lane-takeover" / "verdict.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "decision": "merge"})
    )
    sm = LaneStateMachine(lanes_path, history_path=tmp_path / "state_history.json")
    lease_id = _write_writer_lease(lanes_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-guard-missing",
        "reason": "guard must be complete",
        "request_id": "req-takeover-guard-missing",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T20:00:00Z",
    )
    handler = McpToolHandler(state_machine=sm, xmuse_root=tmp_path)
    guard = _takeover_guard(
        sm=sm,
        xmuse_root=tmp_path,
        lane_id="lane-takeover",
        lease_id=lease_id,
    )
    guard.pop(missing_field)

    result = handler.call(
        "apply_takeover_decision",
        {
            "audit": audit,
            "guard": guard,
            "created_at": "2026-05-31T20:00:01Z",
            "decision": {
                "lane_id": "lane-takeover",
                "action": "repair_and_merge",
                "summary": "Repair passed verification and review.",
                "evidence": {
                    "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
                    "change_ref": "logs/diffs/lane-takeover.patch",
                    "verification_ref": "logs/gates/lane-takeover/report.json",
                    "review_verdict_ref": "xmuse/reviews/lane-takeover/verdict.json",
                    "audit_event_ref": started["audit_event_ref"],
                    "chat_card_ref": started["chat_card_ref"],
                },
            },
        },
    )

    assert "error" in result
    assert missing_field in result["error"]
    assert sm.get_lane("lane-takeover")["status"] == "failed"


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("lane_status", "exec_failed"),
        ("projection_revision", 99),
        ("lease_id", "lease-other"),
        ("lane_context_hash", "bad-context-hash"),
        ("evidence_bundle_hash", "bad-evidence-hash"),
    ],
)
def test_apply_takeover_decision_rejects_stale_takeover_guard(
    tmp_path,
    field_name: str,
    bad_value,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lane = {
        "feature_id": "lane-takeover",
        "status": "failed",
        "prompt": "Fix takeover action routing.",
        "conversation_id": "conv-1",
        "planning_run_id": "plan-1",
        "graph_id": "graph-1",
        "blueprint_refs": ["docs/spec.md"],
        "failure_reason": "merge_failed",
        "gate_passed": False,
    }
    lanes_path.write_text(json.dumps({"lanes": [lane]}))
    (tmp_path / "logs" / "takeover" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "takeover" / "lane-takeover" / "context.json").write_text(
        json.dumps({"lane_id": "lane-takeover"})
    )
    (tmp_path / "logs" / "diffs").mkdir(parents=True)
    (tmp_path / "logs" / "diffs" / "lane-takeover.patch").write_text("diff --git\n")
    (tmp_path / "logs" / "gates" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "gates" / "lane-takeover" / "report.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "passed": True, "blocking_passed": True})
    )
    (tmp_path / "xmuse" / "reviews" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "xmuse" / "reviews" / "lane-takeover" / "verdict.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "decision": "merge"})
    )
    sm = LaneStateMachine(lanes_path, history_path=tmp_path / "state_history.json")
    lease_id = _write_writer_lease(lanes_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-guard-mismatch",
        "reason": "guard must reject stale context",
        "request_id": "req-takeover-guard-mismatch",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T20:00:00Z",
    )
    handler = McpToolHandler(state_machine=sm, xmuse_root=tmp_path)
    guard = _takeover_guard(
        sm=sm,
        xmuse_root=tmp_path,
        lane_id="lane-takeover",
        lease_id=lease_id,
    )
    guard[field_name] = bad_value

    result = handler.call(
        "apply_takeover_decision",
        {
            "audit": audit,
            "guard": guard,
            "created_at": "2026-05-31T20:00:01Z",
            "decision": {
                "lane_id": "lane-takeover",
                "action": "repair_and_merge",
                "summary": "Repair passed verification and review.",
                "evidence": {
                    "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
                    "change_ref": "logs/diffs/lane-takeover.patch",
                    "verification_ref": "logs/gates/lane-takeover/report.json",
                    "review_verdict_ref": "xmuse/reviews/lane-takeover/verdict.json",
                    "audit_event_ref": started["audit_event_ref"],
                    "chat_card_ref": started["chat_card_ref"],
                },
            },
        },
    )

    assert "error" in result
    assert field_name in result["error"]
    assert "mismatch" in result["error"]
    assert sm.get_lane("lane-takeover")["status"] == "failed"


def test_apply_takeover_decision_rejects_post_validation_state_change(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lane = {
        "feature_id": "lane-takeover",
        "status": "failed",
        "prompt": "Fix takeover action routing.",
        "conversation_id": "conv-1",
        "planning_run_id": "plan-1",
        "graph_id": "graph-1",
        "blueprint_refs": ["docs/spec.md"],
        "failure_reason": "merge_failed",
        "gate_passed": False,
    }
    lanes_path.write_text(json.dumps({"lanes": [lane]}))
    (tmp_path / "logs" / "takeover" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "takeover" / "lane-takeover" / "context.json").write_text(
        json.dumps({"lane_id": "lane-takeover"})
    )
    (tmp_path / "logs" / "diffs").mkdir(parents=True)
    (tmp_path / "logs" / "diffs" / "lane-takeover.patch").write_text("diff --git\n")
    (tmp_path / "logs" / "gates" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "logs" / "gates" / "lane-takeover" / "report.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "passed": True, "blocking_passed": True})
    )
    (tmp_path / "xmuse" / "reviews" / "lane-takeover").mkdir(parents=True)
    (tmp_path / "xmuse" / "reviews" / "lane-takeover" / "verdict.json").write_text(
        json.dumps({"lane_id": "lane-takeover", "decision": "merge"})
    )
    sm = LaneStateMachine(lanes_path, history_path=tmp_path / "state_history.json")
    lease_id = _write_writer_lease(lanes_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-guard-race",
        "reason": "guard must be enforced at the write boundary",
        "request_id": "req-takeover-guard-race",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T20:00:00Z",
    )
    handler = McpToolHandler(state_machine=sm, xmuse_root=tmp_path)
    guard = _takeover_guard(
        sm=sm,
        xmuse_root=tmp_path,
        lane_id="lane-takeover",
        lease_id=lease_id,
    )
    real_apply_takeover_decision = mcp_tools_module.apply_takeover_decision

    def mutate_after_validation(**kwargs):
        _write_writer_lease(lanes_path, lease_id="lease-rotated-after-validation")
        sm.update_metadata(
            "lane-takeover",
            {"post_validation_marker": "changed-after-initial-guard-check"},
        )
        return real_apply_takeover_decision(**kwargs)

    monkeypatch.setattr(
        mcp_tools_module,
        "apply_takeover_decision",
        mutate_after_validation,
    )

    result = handler.call(
        "apply_takeover_decision",
        {
            "audit": audit,
            "guard": guard,
            "created_at": "2026-05-31T20:00:01Z",
            "decision": {
                "lane_id": "lane-takeover",
                "action": "repair_and_merge",
                "summary": "Repair passed verification and review.",
                "evidence": {
                    "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
                    "change_ref": "logs/diffs/lane-takeover.patch",
                    "verification_ref": "logs/gates/lane-takeover/report.json",
                    "review_verdict_ref": "xmuse/reviews/lane-takeover/verdict.json",
                    "audit_event_ref": started["audit_event_ref"],
                    "chat_card_ref": started["chat_card_ref"],
                },
            },
        },
    )

    assert "error" in result
    assert "guard." in result["error"]
    assert "mismatch" in result["error"]
    updated = sm.get_lane("lane-takeover")
    assert updated["status"] == "failed"
    assert updated["post_validation_marker"] == "changed-after-initial-guard-check"
    assert "takeover_decision_id" not in updated
    assert "takeover_resolved_event_ref" not in updated
    assert "takeover_resolved_card_ref" not in updated

    audit_events = json.loads(
        (tmp_path / "audit_events.json").read_text(encoding="utf-8")
    )["events"]
    assert [event["event_type"] for event in audit_events] == ["run.takeover_started"]

    intents = json.loads(
        (tmp_path / "read_models" / "execution_card_intents.json").read_text(
            encoding="utf-8"
        )
    )["intents"]
    assert len(intents) == 1
    assert intents[0]["payload"]["event_type"] == "run.takeover_started"


def test_read_run_health_returns_read_only_operational_snapshot(setup):
    handler, _, _, _ = setup

    result = handler.call("read_run_health", {})

    assert result["kind"] == "run_health"
    assert result["read_only"] is True
    assert result["run_health"]["counts"]["terminal"] == 0
    assert result["run_health"]["processes"]["runner_count"] == 0
    assert result["run_health"]["processes"]["mcp_count"] == 0


def test_update_lane_status_valid(setup):
    handler, sm, _, status_changes = setup
    result = handler.call("update_lane_status", {
        "lane_id": "lane-1",
        "status": "reviewed",
        "audit": {
            "actor": "review_god",
            "reason": "accept review verdict",
            "request_id": "req-review-1",
        },
        "guard": {"current_status": "gated"},
    })
    assert result["status"] == "reviewed"
    lane = sm.get_lane("lane-1")
    assert lane["status"] == "reviewed"
    assert lane["last_mutation_audit"]["actor"] == "review_god"
    assert lane["last_mutation_audit"]["reason"] == "accept review verdict"
    assert lane["last_mutation_audit"]["request_id"] == "req-review-1"
    assert lane["last_mutation_audit"]["tool"] == "update_lane_status"
    assert status_changes == [("lane-1", "reviewed")]


def test_update_lane_status_accepts_bounded_execution_evidence_metadata(tmp_path: Path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-exec",
            "status": "dispatched",
            "prompt": "validate package boundaries",
            "worktree": str(tmp_path / "wt"),
        },
    ]}))
    sm = LaneStateMachine(lanes_path)
    handler = McpToolHandler(state_machine=sm, xmuse_root=tmp_path)

    result = handler.call("update_lane_status", {
        "lane_id": "lane-exec",
        "status": "executed",
        "audit": {
            "actor": "codex-child-worker",
            "reason": "package boundary validation passed",
            "request_id": "req-exec-1",
        },
        "guard": {"current_status": "dispatched"},
        "metadata": {
            "tests_run": ["uv run pytest tests/xmuse/test_package_boundaries.py -q"],
            "changed_files": [],
            "evidence_refs": ["runtime_artifacts/package-boundary-proof.txt"],
        },
    })

    assert result["status"] == "executed"
    lane = sm.get_lane("lane-exec")
    assert lane["tests_run"] == ["uv run pytest tests/xmuse/test_package_boundaries.py -q"]
    assert lane["changed_files"] == []
    assert lane["evidence_refs"] == ["runtime_artifacts/package-boundary-proof.txt"]
    assert lane["last_mutation_audit"]["tool"] == "update_lane_status"


def test_update_lane_status_requires_audit_and_guard(setup):
    handler, sm, _, status_changes = setup
    result = handler.call("update_lane_status", {
        "lane_id": "lane-1",
        "status": "reviewed",
    })
    assert "error" in result
    assert "audit" in result["error"]
    assert sm.get_lane("lane-1")["status"] == "gated"
    assert status_changes == []


def test_rejected_status_normalizes_rework_context_for_retry_prompt(setup):
    handler, sm, _, status_changes = setup

    result = handler.call(
        "update_lane_status",
        {
            "lane_id": "lane-1",
            "status": "rejected",
            "audit": {
                "actor": "review_god",
                "reason": "request rework",
                "request_id": "req-review-2",
            },
            "guard": {"current_status": "gated"},
            "metadata": {"rework_context": "Fix missing lineage assertion."},
        },
    )

    assert result["status"] == "rejected"
    lane = sm.get_lane("lane-1")
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "Fix missing lineage assertion."
    assert lane["review_history"][-1]["decision"] == "rework"
    assert lane["review_history"][-1]["summary"] == "Fix missing lineage assertion."
    assert lane["review_history"][-1]["fallback"] == "mcp"
    assert status_changes == [("lane-1", "rejected")]


def test_rejected_status_overrides_conflicting_review_decision(setup):
    handler, sm, _, _ = setup

    result = handler.call(
        "update_lane_status",
        {
            "lane_id": "lane-1",
            "status": "rejected",
            "audit": {
                "actor": "review_god",
                "reason": "normalize review rework",
                "request_id": "req-review-3",
            },
            "guard": {"current_status": "gated"},
            "metadata": {
                "review_decision": "merge",
                "review_summary": "Incorrect merge summary.",
                "rework_context": "Actual rework instructions.",
            },
        },
    )

    assert result["status"] == "rejected"
    lane = sm.get_lane("lane-1")
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "Actual rework instructions."
    assert lane["review_history"][-1]["decision"] == "rework"


def test_rejected_status_accepts_missing_or_invalid_metadata(setup):
    handler, sm, tmp_path, _ = setup

    result = handler.call(
        "update_lane_status",
        {
            "lane_id": "lane-1",
            "status": "rejected",
            "audit": {
                "actor": "review_god",
                "reason": "request rework",
                "request_id": "req-review-4",
            },
            "guard": {"current_status": "gated"},
        },
    )

    assert result["status"] == "rejected"
    lane = sm.get_lane("lane-1")
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "review requested rework"

    lanes_path = tmp_path / "feature_lanes_invalid_metadata.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-invalid-metadata",
            "status": "gated",
            "prompt": "fix bug",
            "worktree": str(tmp_path / "wt"),
        },
    ]}))
    sm2 = LaneStateMachine(lanes_path)
    handler2 = McpToolHandler(state_machine=sm2, xmuse_root=tmp_path)

    result = handler2.call(
        "update_lane_status",
        {
            "lane_id": "lane-invalid-metadata",
            "status": "rejected",
            "audit": {
                "actor": "review_god",
                "reason": "request rework",
                "request_id": "req-review-5",
            },
            "guard": {"current_status": "gated"},
            "metadata": "not-a-dict",
        },
    )

    assert result["status"] == "rejected"
    lane = sm2.get_lane("lane-invalid-metadata")
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "review requested rework"


def test_update_lane_status_invalid(setup):
    handler, _, _, _ = setup
    result = handler.call("update_lane_status", {
        "lane_id": "lane-1",
        "status": "merged",
        "audit": {
            "actor": "review_god",
            "reason": "attempt invalid merge",
            "request_id": "req-review-6",
        },
        "guard": {"current_status": "gated"},
    })
    assert "error" in result


def test_update_lane_status_returns_validation_error(setup):
    handler, sm, _, status_changes = setup
    result = handler.call("update_lane_status", {
        "lane_id": "lane-1",
        "status": "gate_failed",
        "audit": {
            "actor": "review_god",
            "reason": "report gate failure",
            "request_id": "req-review-7",
        },
        "guard": {"current_status": "gated"},
    })

    assert "error" in result
    assert "failure_reason" in result["error"]
    assert sm.get_lane("lane-1")["status"] == "gated"
    assert status_changes == []


def test_update_lane_status_rejects_unsafe_projection_metadata(setup):
    handler, sm, _, status_changes = setup
    result = handler.call(
        "update_lane_status",
        {
            "lane_id": "lane-1",
            "status": "rejected",
            "audit": {
                "actor": "review_god",
                "reason": "reject unsafe projection write",
                "request_id": "req-review-8",
            },
            "guard": {"current_status": "gated"},
            "metadata": {
                "rework_context": "Fix the guard.",
                "worker_command": ["codex", "exec"],
                "provider_health": {"diagnostic_summary": "secret"},
            },
        },
    )

    assert "error" in result
    assert "provider_health" in result["error"]
    assert "worker_command" in result["error"]
    assert sm.get_lane("lane-1")["status"] == "gated"
    assert status_changes == []


def test_update_lane_status_accepts_bounded_scalar_status_metadata(setup):
    handler, sm, _, status_changes = setup
    result = handler.call(
        "update_lane_status",
        {
            "lane_id": "lane-1",
            "status": "reviewed",
            "audit": {
                "actor": "review_god",
                "reason": "record bounded status metadata",
                "request_id": "req-review-9",
            },
            "guard": {"current_status": "gated"},
            "metadata": {
                "review_runtime": "opencode",
                "final_action": "no-auto-merge",
                "proof_boundary": "local_runtime_proof",
            },
        },
    )

    assert result["status"] == "reviewed"
    lane = sm.get_lane("lane-1")
    assert lane["review_runtime"] == "opencode"
    assert lane["final_action"] == "no-auto-merge"
    assert lane["proof_boundary"] == "local_runtime_proof"
    assert status_changes == [("lane-1", "reviewed")]


def test_unknown_tool(setup):
    handler, _, _, _ = setup
    result = handler.call("nonexistent_tool", {})
    assert "error" in result
