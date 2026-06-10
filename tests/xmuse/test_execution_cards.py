from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.dashboard_api import create_app
from xmuse_core.chat.execution_cards import (
    ChatExecutionCardEmitter,
    build_execution_card_envelope,
)
from xmuse_core.chat.store import ChatStore
from xmuse_core.self_evolution.models import (
    RunTerminalAggregation,
    RunTerminalStatus,
)
from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore, FeaturePlanStore
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
    PlanningRun,
    PlanningRunStatus,
)
from xmuse_core.structuring.planning_run_store import PlanningRunStore
from xmuse_core.structuring.projection import project_feature_graph_set_ready_lanes


def _conversation(tmp_path: Path) -> str:
    return ChatStore(tmp_path / "chat.db").create_conversation("Execution cards").id


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _feature_graph_set(
    *,
    conversation_id: str,
    graph_set_id: str = "graph-set-001",
    feature_plan_id: str = "feature-plan-001",
) -> FeatureGraphSet:
    plan = FeaturePlan(
        id=feature_plan_id,
        conversation_id=conversation_id,
        resolution_id="res-001",
        version=3,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add durable planning run schemas.",
                acceptance_criteria=["Schema lands cleanly."],
                graph_id="graph-schema",
            ),
            FeaturePlanFeature(
                feature_id="cards",
                title="Cards",
                goal="Materialize progress and terminal cards.",
                acceptance_criteria=["Compact cards are emitted."],
                dependencies=["schema"],
                graph_id="graph-cards",
            ),
        ],
    )
    return FeatureGraphSet(
        id=graph_set_id,
        feature_plan=plan,
        graphs=[
            LaneGraph(
                id="graph-schema",
                conversation_id=conversation_id,
                resolution_id="res-001",
                version=3,
                lanes=[LaneNode(feature_id="schema-root", prompt="Ship schema changes.")],
            ),
            LaneGraph(
                id="graph-cards",
                conversation_id=conversation_id,
                resolution_id="res-001",
                version=3,
                lanes=[LaneNode(feature_id="cards-root", prompt="Emit chat cards.")],
            ),
        ],
    )


def _planning_run(
    conversation_id: str,
    *,
    status: str,
    graph_set_id: str = "graph-set-001",
) -> dict[str, str]:
    return {
        "planning_run_id": "plan-run-001",
        "conversation_id": conversation_id,
        "graph_set_id": graph_set_id,
        "status": status,
        "updated_at": "2026-05-31T12:05:00Z",
    }


def _seed_feature_plan_proposal(
    tmp_path: Path,
    *,
    conversation_id: str,
    feature_plan_id: str = "feature-plan-001",
) -> FeaturePlanFeature:
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
            id=feature_plan_id,
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
    return feature


def _write_graph_set(
    tmp_path: Path,
    *,
    conversation_id: str,
    feature: FeaturePlanFeature,
    feature_plan_id: str = "feature-plan-001",
    graph_set_id: str = "graph-set-001",
) -> None:
    graph_set = FeatureGraphSet(
        id=graph_set_id,
        feature_plan=FeaturePlan(
            id=feature_plan_id,
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
    lane_graphs_dir = tmp_path / "lane_graphs"
    lane_graphs_dir.mkdir(parents=True, exist_ok=True)
    (lane_graphs_dir / f"{graph_set_id}.json").write_text(
        json.dumps(graph_set.model_dump(mode="json")),
        encoding="utf-8",
    )


def _write_planning_run(
    tmp_path: Path,
    *,
    conversation_id: str,
    feature_plan_id: str = "feature-plan-001",
    graph_set_id: str | None = None,
) -> None:
    read_models_dir = tmp_path / "read_models"
    read_models_dir.mkdir(parents=True, exist_ok=True)
    (read_models_dir / "planning_runs.json").write_text(
        json.dumps(
            {
                "planning_runs": [
                    {
                        "planning_run_id": "plan-run-001",
                        "conversation_id": conversation_id,
                        "blueprint_ref": "resolution:res-001:mission_blueprint:v1",
                        "status": "running",
                        "feature_plan_id": feature_plan_id,
                        "graph_set_id": graph_set_id,
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_execution_card_intents_support_all_c6_card_kinds(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    emitter = ChatExecutionCardEmitter(tmp_path)
    planning_run_id = "plan-run-001"
    created_at = "2026-05-31T12:00:00Z"

    intents = [
        emitter.emit_blueprint_execution_started(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            resolution_id="res-001",
            blueprint_ref="docs/spec.md",
            created_at=created_at,
            summary="Blueprint execution started.",
        ),
        emitter.emit_feature_plan_ready(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            feature_plan_id="feature-plan-001",
            feature_count=3,
            risk_level="medium",
            created_at=created_at,
            summary="Feature plan ready.",
        ),
        emitter.emit_lane_graph_ready(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            graph_set_id="graph-set-001",
            lane_graph_count=3,
            lane_count=9,
            risk_level="high",
            created_at=created_at,
            summary="Lane graph set ready.",
        ),
        emitter.emit_run_progress(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            graph_set_id="graph-set-001",
            counts={
                "ready_lanes": 1,
                "active_lanes": 2,
                "blocked_lanes": 0,
                "failed_lanes": 0,
                "terminal_lanes": 4,
            },
            fallback_used=True,
            created_at=created_at,
            summary="Run progress updated.",
        ),
        emitter.emit_run_takeover(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            lane_id="lane-001",
            takeover_reason="review_god_takeover",
            created_at=created_at,
            summary="Review GOD takeover started.",
        ),
        emitter.emit_run_terminal(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            terminal_status="merged",
            counts={
                "merged_lanes": 9,
                "failed_lanes": 0,
            },
            created_at=created_at,
            summary="Run merged cleanly.",
        ),
    ]

    assert [intent.card_type for intent in intents] == [
        "blueprint_execution_started",
        "feature_plan_ready",
        "lane_graph_ready",
        "run_progress",
        "run_takeover",
        "run_terminal",
    ]
    for intent in intents:
        assert intent.conversation_id == conversation_id
        assert intent.planning_run_id == planning_run_id
        assert intent.href.endswith(f"#execution-card-{intent.intent_id}")
        assert intent.api_href.endswith(
            f"/api/dashboard/peer-chat/conversations/{conversation_id}/execution-cards/{intent.intent_id}"
        )
        assert intent.drilldown_refs


def test_execution_card_envelope_materializes_compact_chat_card_shape(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    emitter = ChatExecutionCardEmitter(tmp_path)
    intent = emitter.emit_run_progress(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        graph_set_id="graph-set-001",
        counts={
            "ready_lanes": 1,
            "active_lanes": 2,
            "blocked_lanes": 1,
            "failed_lanes": 0,
            "terminal_lanes": 4,
        },
        fallback_used=True,
        created_at="2026-05-31T12:00:00Z",
        summary="Run progress updated.",
    )

    envelope = build_execution_card_envelope(intent)
    card = envelope["cards"][0]

    assert envelope["type"] == "message"
    assert card["card_type"] == "run_progress"
    assert card["status"] == "active"
    assert card["counts"] == {
        "ready_lanes": 1,
        "active_lanes": 2,
        "blocked_lanes": 1,
        "failed_lanes": 0,
        "terminal_lanes": 4,
    }
    assert card["metadata"]["planning_run_id"] == "plan-run-001"
    assert card["metadata"]["payload"] == {
        "graph_set_id": "graph-set-001",
        "fallback_used": True,
    }
    assert "prompt" not in str(card)
    assert "raw" not in str(card)


def test_execution_card_materialization_is_replay_safe(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    emitter = ChatExecutionCardEmitter(tmp_path)

    first = emitter.emit_run_terminal(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        terminal_status="merged",
        counts={"merged_lanes": 9, "failed_lanes": 0},
        created_at="2026-05-31T12:00:00Z",
        summary="Run merged cleanly.",
    )
    second = emitter.emit_run_terminal(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        terminal_status="merged",
        counts={"merged_lanes": 9, "failed_lanes": 0},
        created_at="2026-05-31T12:00:00Z",
        summary="Run merged cleanly.",
    )

    cards = emitter.list_cards(conversation_id)

    assert first.intent_id == second.intent_id
    assert len(cards) == 1
    assert cards[0].card_type == "run_terminal"
    assert cards[0].source_id == first.intent_id


def test_execution_card_dashboard_detail_exposes_drilldown_refs(tmp_path: Path) -> None:
    conversation_id = _conversation(tmp_path)
    _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
    _write_planning_run(tmp_path, conversation_id=conversation_id)
    emitter = ChatExecutionCardEmitter(tmp_path)
    intent = emitter.emit_feature_plan_ready(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        feature_plan_id="feature-plan-001",
        feature_count=3,
        risk_level="medium",
        created_at="2026-05-31T12:00:00Z",
        summary="Feature plan ready.",
    )

    client = TestClient(create_app(tmp_path))
    timeline = client.get(f"/api/dashboard/peer-chat/conversations/{conversation_id}")
    detail = client.get(intent.api_href)

    assert timeline.status_code == 200
    assert any(
        card["card_type"] == "feature_plan_ready"
        and card["source_id"] == intent.intent_id
        for card in timeline.json()["cards"]
    )

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["card"]["source_id"] == intent.intent_id
    assert payload["intent"]["card_type"] == "feature_plan_ready"
    assert payload["intent"]["risk_level"] == "medium"
    assert payload["intent"]["payload"] == {"feature_plan_id": "feature-plan-001"}
    refs = {ref["ref_type"]: ref for ref in payload["refs"]}
    assert refs == {
        "planning_run": {
            "label": "Planning run",
            "href": "/dashboard/planning-runs/plan-run-001",
            "api_href": "/api/planning-runs/plan-run-001",
            "ref_id": "plan-run-001",
            "ref_type": "planning_run",
        },
        "feature_plan": {
            "label": "Feature plan",
            "href": "/dashboard/feature-plans/feature-plan-001",
            "api_href": "/api/feature-plans/feature-plan-001",
            "ref_id": "feature-plan-001",
            "ref_type": "feature_plan",
        },
    }
    planning_run = client.get(refs["planning_run"]["api_href"])
    feature_plan = client.get(refs["feature_plan"]["api_href"])
    assert planning_run.status_code == 200
    assert planning_run.json()["planning_run"]["planning_run_id"] == "plan-run-001"
    assert feature_plan.status_code == 200
    assert feature_plan.json()["feature_plan"]["id"] == "feature-plan-001"
    assert feature_plan.json()["summary"]["counts"] == {
        "features": 1,
        "graphs": 0,
        "dependency_edges": 0,
    }


def test_planning_run_drilldown_reads_durable_planning_run_store(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
    PlanningRunStore(tmp_path / "planning_runs.sqlite3").save(
        PlanningRun(
            planning_run_id="plan-run-001",
            conversation_id=conversation_id,
            blueprint_ref="resolution:res-001:mission_blueprint:v1",
            blueprint_version=1,
            dedupe_key=f"{conversation_id}:resolution:res-001:1",
            status=PlanningRunStatus.RUNNING,
            feature_plan_id="feature-plan-001",
            feature_plan_version=1,
            created_at="2026-05-31T12:00:00Z",
            updated_at="2026-05-31T12:05:00Z",
        )
    )
    intent = ChatExecutionCardEmitter(tmp_path).emit_feature_plan_ready(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        feature_plan_id="feature-plan-001",
        feature_count=1,
        risk_level="medium",
        created_at="2026-05-31T12:00:00Z",
        summary="Feature plan ready.",
    )

    client = TestClient(create_app(tmp_path))
    detail = client.get(intent.api_href)

    assert detail.status_code == 200
    refs = {ref["ref_type"]: ref for ref in detail.json()["refs"]}
    planning_run = client.get(refs["planning_run"]["api_href"])
    assert planning_run.status_code == 200
    assert planning_run.json()["planning_run"]["planning_run_id"] == "plan-run-001"
    assert planning_run.json()["planning_run"]["feature_plan_id"] == "feature-plan-001"


def test_planning_run_drilldown_falls_back_to_json_when_sqlite_is_invalid(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
    (tmp_path / "planning_runs.sqlite3").write_text("not sqlite", encoding="utf-8")
    _write_planning_run(tmp_path, conversation_id=conversation_id)
    intent = ChatExecutionCardEmitter(tmp_path).emit_feature_plan_ready(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        feature_plan_id="feature-plan-001",
        feature_count=1,
        risk_level="medium",
        created_at="2026-05-31T12:00:00Z",
        summary="Feature plan ready.",
    )

    client = TestClient(create_app(tmp_path))
    detail = client.get(intent.api_href)

    assert detail.status_code == 200
    refs = {ref["ref_type"]: ref for ref in detail.json()["refs"]}
    planning_run = client.get(refs["planning_run"]["api_href"])
    assert planning_run.status_code == 200
    assert planning_run.json()["planning_run"]["planning_run_id"] == "plan-run-001"


def test_planning_run_drilldown_does_not_initialize_sqlite_on_read_fallback(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
    with sqlite3.connect(tmp_path / "planning_runs.sqlite3") as conn:
        conn.execute("create table unrelated(id text primary key)")
    _write_planning_run(tmp_path, conversation_id=conversation_id)
    intent = ChatExecutionCardEmitter(tmp_path).emit_feature_plan_ready(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        feature_plan_id="feature-plan-001",
        feature_count=1,
        risk_level="medium",
        created_at="2026-05-31T12:00:00Z",
        summary="Feature plan ready.",
    )

    client = TestClient(create_app(tmp_path))
    response = client.get(intent.api_href)

    assert response.status_code == 200
    with sqlite3.connect(tmp_path / "planning_runs.sqlite3") as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
    assert "planning_runs" not in tables


def test_planning_run_drilldown_falls_back_when_sqlite_schema_is_empty(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
    PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    _write_planning_run(tmp_path, conversation_id=conversation_id)
    intent = ChatExecutionCardEmitter(tmp_path).emit_feature_plan_ready(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        feature_plan_id="feature-plan-001",
        feature_count=1,
        risk_level="medium",
        created_at="2026-05-31T12:00:00Z",
        summary="Feature plan ready.",
    )

    client = TestClient(create_app(tmp_path))
    detail = client.get(intent.api_href)

    assert detail.status_code == 200
    refs = {ref["ref_type"]: ref for ref in detail.json()["refs"]}
    planning_run = client.get(refs["planning_run"]["api_href"])
    assert planning_run.status_code == 200
    assert planning_run.json()["planning_run"]["planning_run_id"] == "plan-run-001"


def test_execution_card_dashboard_detail_exposes_graph_and_evidence_drilldowns(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    feature = _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
    _write_graph_set(tmp_path, conversation_id=conversation_id, feature=feature)
    _write_planning_run(
        tmp_path,
        conversation_id=conversation_id,
        graph_set_id="graph-set-001",
    )
    (tmp_path / "feature_lanes.json").write_text(
        json.dumps(
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
            indent=2,
        ),
        encoding="utf-8",
    )
    gate_dir = tmp_path / "logs" / "gates" / "lane-001"
    gate_dir.mkdir(parents=True)
    (gate_dir / "report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")

    emitter = ChatExecutionCardEmitter(tmp_path)
    intent = emitter.emit_run_takeover(
        conversation_id=conversation_id,
        planning_run_id="plan-run-001",
        lane_id="lane-001",
        takeover_reason="review_god_takeover",
        created_at="2026-05-31T12:00:00Z",
        summary="Review GOD takeover started.",
    )

    client = TestClient(create_app(tmp_path))
    detail = client.get(intent.api_href)

    assert detail.status_code == 200
    refs = {ref["ref_type"]: ref for ref in detail.json()["refs"]}
    assert {
        "planning_run",
        "feature_plan",
        "graph_set",
        "runner_evidence",
        "takeover_evidence",
    } <= set(refs)

    planning_run = client.get(refs["planning_run"]["api_href"])
    feature_plan = client.get(refs["feature_plan"]["api_href"])
    graph_set = client.get(refs["graph_set"]["api_href"])
    runner_evidence = client.get(refs["runner_evidence"]["api_href"])
    takeover_evidence = client.get(refs["takeover_evidence"]["api_href"])

    assert planning_run.status_code == 200
    assert planning_run.json()["planning_run"]["graph_set_id"] == "graph-set-001"
    assert feature_plan.status_code == 200
    assert feature_plan.json()["feature_plan"]["id"] == "feature-plan-001"
    assert graph_set.status_code == 200
    assert graph_set.json()["graph_set"]["id"] == "graph-set-001"
    assert runner_evidence.status_code == 200
    assert runner_evidence.json()["graph_set_id"] == "graph-set-001"
    assert runner_evidence.json()["lanes"] == [
        {
            "lane_id": "lane-001",
            "lane_context_ref": "logs/lane_context/lane-001/latest.json",
            "primary_evidence_refs": ["lane.failure_reason"],
            "review_evidence_refs": ["logs/gates/lane-001/report.json"],
            "gate_refs": [{"ref": "logs/gates/lane-001/report.json"}],
            "worker_refs": [{"ref": "logs/diffs/lane-001.patch"}],
        }
    ]
    assert takeover_evidence.status_code == 200
    assert takeover_evidence.json()["lane_id"] == "lane-001"
    assert takeover_evidence.json()["needs_takeover"] is True


def test_takeover_context_drilldown_does_not_create_projection_lock(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-001",
                        "conversation_id": conversation_id,
                        "status": "exec_failed",
                        "failure_reason": "execution_infra_unavailable",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    response = TestClient(create_app(tmp_path)).get("/api/lanes/lane-001/takeover-context")

    assert response.status_code == 200
    assert response.json()["lane_id"] == "lane-001"
    assert not (tmp_path / "feature_lanes.json.lock").exists()


def test_execution_drilldowns_keep_lane_and_graph_fallbacks_conversation_scoped(
    tmp_path: Path,
) -> None:
    current_conversation_id = _conversation(tmp_path)
    other_conversation_id = ChatStore(tmp_path / "chat.db").create_conversation("Other").id
    current_feature = _seed_feature_plan_proposal(
        tmp_path,
        conversation_id=current_conversation_id,
        feature_plan_id="feature-plan-current",
    )
    other_feature = _seed_feature_plan_proposal(
        tmp_path,
        conversation_id=other_conversation_id,
        feature_plan_id="feature-plan-other",
    )
    _write_graph_set(
        tmp_path,
        conversation_id=other_conversation_id,
        feature=other_feature,
        feature_plan_id="feature-plan-other",
        graph_set_id="aaa-other-graph-set",
    )
    _write_graph_set(
        tmp_path,
        conversation_id=current_conversation_id,
        feature=current_feature,
        feature_plan_id="feature-plan-current",
        graph_set_id="zzz-current-graph-set",
    )
    _write_planning_run(
        tmp_path,
        conversation_id=current_conversation_id,
        feature_plan_id="feature-plan-current",
        graph_set_id=None,
    )
    (tmp_path / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-001",
                        "conversation_id": other_conversation_id,
                        "graph_id": "graph-alpha",
                        "feature_plan_id": "feature-plan-other",
                        "status": "failed",
                    },
                    {
                        "feature_id": "lane-001",
                        "conversation_id": current_conversation_id,
                        "graph_id": "graph-alpha",
                        "feature_plan_id": "feature-plan-current",
                        "status": "failed",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    intent = ChatExecutionCardEmitter(tmp_path).emit_run_takeover(
        conversation_id=current_conversation_id,
        planning_run_id="plan-run-001",
        lane_id="lane-001",
        takeover_reason="review_god_takeover",
        created_at="2026-05-31T12:00:00Z",
        summary="Review GOD takeover started.",
    )

    detail = TestClient(create_app(tmp_path)).get(intent.api_href)

    assert detail.status_code == 200
    refs = {ref["ref_type"]: ref for ref in detail.json()["refs"]}
    assert refs["feature_plan"]["api_href"] == "/api/feature-plans/feature-plan-current"
    assert refs["graph_set"]["api_href"] == "/api/feature-graph-sets/zzz-current-graph-set"
    takeover = TestClient(create_app(tmp_path)).get(refs["takeover_evidence"]["api_href"])
    assert takeover.status_code == 200
    assert takeover.json()["bundle"]["lane_metadata"]["conversation_id"] == current_conversation_id
    assert takeover.json()["bundle"]["lane_metadata"]["feature_plan_id"] == "feature-plan-current"


def test_graph_set_runner_evidence_matches_projected_feature_graph_lanes(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    feature = _seed_feature_plan_proposal(tmp_path, conversation_id=conversation_id)
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
    lane_graphs_dir = tmp_path / "lane_graphs"
    lane_graphs_dir.mkdir(parents=True, exist_ok=True)
    (lane_graphs_dir / "graph-set-001.json").write_text(
        json.dumps(graph_set.model_dump(mode="json")),
        encoding="utf-8",
    )
    _write_planning_run(
        tmp_path,
        conversation_id=conversation_id,
        graph_set_id="graph-set-001",
    )

    lanes_path = tmp_path / "feature_lanes.json"
    projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids=set(),
    )
    assert len(projected) == 1

    projected_lane = dict(projected[0])
    projected_lane["status"] = "exec_failed"
    projected_lane["failure_reason"] = "execution_infra_unavailable"
    projected_lane["diff_ref"] = "logs/diffs/lane-001.patch"
    projected_lane["review_evidence_refs"] = ["logs/gates/manual-review.json"]
    lanes_path.write_text(
        json.dumps({"lanes": [projected_lane]}, indent=2) + "\n",
        encoding="utf-8",
    )

    safe_lane_id = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in projected_lane["feature_id"]
    )
    gate_dir = tmp_path / "logs" / "gates" / safe_lane_id
    gate_dir.mkdir(parents=True)
    (gate_dir / "report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")

    client = TestClient(create_app(tmp_path))
    response = client.get("/api/feature-graph-sets/graph-set-001/runner-evidence")

    assert response.status_code == 200
    assert response.json()["graph_set_id"] == "graph-set-001"
    assert response.json()["lanes"] == [
        {
            "lane_id": "lane-001",
            "lane_context_ref": f"logs/lane_context/{safe_lane_id}/latest.json",
            "primary_evidence_refs": ["lane.failure_reason"],
            "review_evidence_refs": ["logs/gates/manual-review.json"],
            "gate_refs": [{"ref": f"logs/gates/{safe_lane_id}/report.json"}],
            "worker_refs": [{"ref": "logs/diffs/lane-001.patch"}],
        }
    ]


def test_materialize_planning_run_cards_derives_progress_counts_from_graph_set_and_run_health(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    FeatureGraphSetStore(tmp_path / "lane_graphs").save(
        _feature_graph_set(conversation_id=conversation_id)
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "lane_id": "schema-root",
                    "lane_local_id": "schema-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-schema",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "schema",
                    "status": "merged",
                },
                {
                    "feature_id": "cards-root",
                    "lane_id": "cards-root",
                    "lane_local_id": "cards-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-cards",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "cards",
                    "status": "dispatched",
                    "worker_pid": 4242,
                    "dispatched_at": 995.0,
                },
            ]
        },
    )

    intents = ChatExecutionCardEmitter(tmp_path).materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="running"),
        live_pids={4242},
        runner_pids=[101],
        mcp_pids=[202],
        now=1000.0,
    )

    progress = next(intent for intent in intents if intent.card_type == "run_progress")

    assert progress.status == "active"
    assert progress.counts == {
        "features": 2,
        "lane_graphs": 2,
        "planned_features": 0,
        "ready_features": 0,
        "active_features": 1,
        "terminal_features": 1,
        "blocked_features": 0,
        "unsafe_features": 0,
        "total_lanes": 2,
        "active_lanes": 1,
        "stale_lanes": 0,
        "blocked_lanes": 0,
        "failed_lanes": 0,
        "terminal_lanes": 1,
        "retrying_lanes": 0,
        "takeover_lanes": 0,
        "degraded_lanes": 0,
    }
    assert progress.payload == {
        "graph_set_id": "graph-set-001",
        "graph_set_version": 3,
        "feature_plan_id": "feature-plan-001",
        "planning_status": "running",
        "stale": False,
        "degraded": False,
        "fallback_used": False,
        "warning_codes": [],
    }


def test_materialize_planning_run_cards_emits_terminal_success_and_failure_cards(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    FeatureGraphSetStore(tmp_path / "lane_graphs").save(
        _feature_graph_set(conversation_id=conversation_id)
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "lane_id": "schema-root",
                    "lane_local_id": "schema-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-schema",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "schema",
                    "status": "merged",
                },
                {
                    "feature_id": "cards-root",
                    "lane_id": "cards-root",
                    "lane_local_id": "cards-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-cards",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "cards",
                    "status": "merged",
                },
            ]
        },
    )
    emitter = ChatExecutionCardEmitter(tmp_path)

    merged_cards = emitter.materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="terminal"),
        terminal_aggregation={
            "aggregation_id": "agg-merged",
            "graph_id": "graph-set-001",
            "status": "merged",
            "reason": "all graph lineage lanes merged",
            "lane_counts": {"terminal": 2},
            "lane_statuses": [
                {"feature_id": "schema-root", "normalized_status": "merged", "terminal": True},
                {"feature_id": "cards-root", "normalized_status": "merged", "terminal": True},
            ],
            "open_lineages": [],
            "blocked_objects": [],
            "final_action_holds": [],
        },
        runner_pids=[101],
        mcp_pids=[202],
    )
    terminated_cards = emitter.materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="failed"),
        terminal_aggregation={
            "aggregation_id": "agg-terminated",
            "graph_id": "graph-set-001",
            "status": "terminated",
            "reason": "at least one graph lineage terminalized without merge",
            "lane_counts": {"terminal": 2},
            "lane_statuses": [
                {"feature_id": "schema-root", "normalized_status": "merged", "terminal": True},
                {"feature_id": "cards-root", "normalized_status": "exec_failed", "terminal": True},
            ],
            "open_lineages": [],
            "blocked_objects": [],
            "final_action_holds": [],
        },
        runner_pids=[101],
        mcp_pids=[202],
    )

    merged_terminal = next(
        intent for intent in merged_cards if intent.card_type == "run_terminal"
    )
    terminated_terminal = next(
        intent for intent in terminated_cards if intent.card_type == "run_terminal"
    )

    assert merged_terminal.status == "merged"
    assert merged_terminal.counts["merged_lanes"] == 2
    assert merged_terminal.counts["failed_lanes"] == 0
    assert merged_terminal.payload["terminal_reason"] == "all graph lineage lanes merged"

    assert terminated_terminal.status == "terminated"
    assert terminated_terminal.counts["merged_lanes"] == 1
    assert terminated_terminal.counts["failed_lanes"] == 1
    assert (
        terminated_terminal.payload["terminal_reason"]
        == "at least one graph lineage terminalized without merge"
    )


def test_materialize_planning_run_cards_accepts_run_terminal_aggregation_models(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    FeatureGraphSetStore(tmp_path / "lane_graphs").save(
        _feature_graph_set(conversation_id=conversation_id)
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "lane_id": "schema-root",
                    "lane_local_id": "schema-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-schema",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "schema",
                    "status": "merged",
                },
                {
                    "feature_id": "cards-root",
                    "lane_id": "cards-root",
                    "lane_local_id": "cards-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-cards",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "cards",
                    "status": "exec_failed",
                },
            ]
        },
    )

    intents = ChatExecutionCardEmitter(tmp_path).materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="failed"),
        terminal_aggregation=RunTerminalAggregation(
            aggregation_id="agg-terminated",
            run_id="graph-set-001",
            resolution_id="res-001",
            graph_id="graph-set-001",
            status=RunTerminalStatus.TERMINATED,
            terminal=True,
            reason="at least one graph lineage terminalized without merge",
            lane_counts={"terminal": 2},
            lane_statuses=[
                {
                    "feature_id": "schema-root",
                    "normalized_status": "merged",
                    "terminal": True,
                },
                {
                    "feature_id": "cards-root",
                    "normalized_status": "exec_failed",
                    "terminal": True,
                },
            ],
            open_lineages=[],
            blocked_objects=[],
            final_action_holds=[],
            created_at="2026-05-31T12:05:00Z",
        ),
        runner_pids=[101],
        mcp_pids=[202],
    )

    terminal = next(intent for intent in intents if intent.card_type == "run_terminal")

    assert terminal.status == "terminated"
    assert terminal.counts["merged_lanes"] == 1
    assert terminal.counts["failed_lanes"] == 1
    assert (
        terminal.payload["terminal_reason"]
        == "at least one graph lineage terminalized without merge"
    )


def test_materialize_planning_run_cards_marks_stale_and_degraded_progress(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    FeatureGraphSetStore(tmp_path / "lane_graphs").save(
        _feature_graph_set(conversation_id=conversation_id)
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "lane_id": "schema-root",
                    "lane_local_id": "schema-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-schema",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "schema",
                    "status": "dispatched",
                    "dispatched_at": 0.0,
                },
                {
                    "feature_id": "cards-root",
                    "lane_id": "cards-root",
                    "lane_local_id": "cards-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-cards",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "cards",
                    "status": "reviewed",
                    "peer_delivery_mode": "auto_persistent_fallback",
                },
            ]
        },
    )

    intents = ChatExecutionCardEmitter(tmp_path).materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="running"),
        live_pids=set(),
        runner_pids=[],
        mcp_pids=[],
        now=2000.0,
    )

    progress = next(intent for intent in intents if intent.card_type == "run_progress")

    assert progress.status == "degraded"
    assert progress.fallback_used is True
    assert progress.counts["stale_lanes"] == 1
    assert progress.counts["degraded_lanes"] == 1
    assert progress.payload["stale"] is True
    assert progress.payload["degraded"] is True
    assert progress.payload["fallback_used"] is True
    assert progress.payload["warning_codes"] == [
        "missing_runner_process",
        "missing_mcp_process",
    ]


def test_materialize_planning_run_cards_replays_without_duplicate_intents(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    FeatureGraphSetStore(tmp_path / "lane_graphs").save(
        _feature_graph_set(conversation_id=conversation_id)
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "lane_id": "schema-root",
                    "lane_local_id": "schema-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-schema",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "schema",
                    "status": "merged",
                },
                {
                    "feature_id": "cards-root",
                    "lane_id": "cards-root",
                    "lane_local_id": "cards-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-cards",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "cards",
                    "status": "merged",
                },
            ]
        },
    )
    emitter = ChatExecutionCardEmitter(tmp_path)

    first = emitter.materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="terminal"),
        terminal_aggregation={
            "aggregation_id": "agg-merged",
            "graph_id": "graph-set-001",
            "status": "merged",
            "reason": "all graph lineage lanes merged",
            "lane_counts": {"terminal": 2},
            "lane_statuses": [
                {"feature_id": "schema-root", "normalized_status": "merged", "terminal": True},
                {"feature_id": "cards-root", "normalized_status": "merged", "terminal": True},
            ],
            "open_lineages": [],
            "blocked_objects": [],
            "final_action_holds": [],
        },
        runner_pids=[101],
        mcp_pids=[202],
    )
    second = emitter.materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="terminal"),
        terminal_aggregation={
            "aggregation_id": "agg-merged",
            "graph_id": "graph-set-001",
            "status": "merged",
            "reason": "all graph lineage lanes merged",
            "lane_counts": {"terminal": 2},
            "lane_statuses": [
                {"feature_id": "schema-root", "normalized_status": "merged", "terminal": True},
                {"feature_id": "cards-root", "normalized_status": "merged", "terminal": True},
            ],
            "open_lineages": [],
            "blocked_objects": [],
            "final_action_holds": [],
        },
        runner_pids=[101],
        mcp_pids=[202],
    )

    assert [intent.intent_id for intent in first] == [intent.intent_id for intent in second]
    assert len(emitter.list_cards(conversation_id)) == 2
    assert len(
        [
            card
            for card in emitter.list_cards(conversation_id)
            if card.card_type == "run_terminal"
        ]
    ) == 1


def test_materialize_terminal_card_replay_uses_stable_terminal_identity(
    tmp_path: Path,
) -> None:
    conversation_id = _conversation(tmp_path)
    FeatureGraphSetStore(tmp_path / "lane_graphs").save(
        _feature_graph_set(conversation_id=conversation_id)
    )
    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": "schema-root",
                    "lane_id": "schema-root",
                    "lane_local_id": "schema-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-schema",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "schema",
                    "status": "merged",
                },
                {
                    "feature_id": "cards-root",
                    "lane_id": "cards-root",
                    "lane_local_id": "cards-root",
                    "conversation_id": conversation_id,
                    "graph_id": "graph-cards",
                    "feature_plan_id": "feature-plan-001",
                    "feature_plan_feature_id": "cards",
                    "status": "merged",
                },
            ]
        },
    )
    terminal_aggregation = {
        "aggregation_id": "agg-merged",
        "graph_id": "graph-set-001",
        "status": "merged",
        "reason": "all graph lineage lanes merged",
        "lane_counts": {"terminal": 2},
        "lane_statuses": [
            {
                "feature_id": "schema-root",
                "normalized_status": "merged",
                "terminal": True,
            },
            {
                "feature_id": "cards-root",
                "normalized_status": "merged",
                "terminal": True,
            },
        ],
        "open_lineages": [],
        "blocked_objects": [],
        "final_action_holds": [],
    }
    emitter = ChatExecutionCardEmitter(tmp_path)

    first = emitter.materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="terminal"),
        terminal_aggregation=terminal_aggregation,
        runner_pids=[101],
        mcp_pids=[202],
    )
    replayed_terminal_aggregation = {
        **terminal_aggregation,
        "aggregation_id": "agg-merged-recomputed",
    }
    second = emitter.materialize_planning_run_cards(
        planning_run=_planning_run(conversation_id, status="terminal"),
        terminal_aggregation=replayed_terminal_aggregation,
        runner_pids=[],
        mcp_pids=[],
    )

    first_terminal = next(intent for intent in first if intent.card_type == "run_terminal")
    second_terminal = next(intent for intent in second if intent.card_type == "run_terminal")

    assert first_terminal.intent_id == second_terminal.intent_id
    assert len(
        [
            card
            for card in emitter.list_cards(conversation_id)
            if card.card_type == "run_terminal"
        ]
    ) == 1
