import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from xmuse_core.agents.planning_god_adapters import PlannerGodAdapter, ReviewGodAdapter
from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.chat.models import ResolutionStatus, StructuredResolution
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.platform.mcp_tools import McpToolHandler
from xmuse_core.platform.projection.syncer import LaneProjectionSyncer
from xmuse_core.providers.models import TaskCapability
from xmuse_core.providers.policy import ProviderPolicyService
from xmuse_core.structuring.blueprint_execution.approval_events import (
    BlueprintApprovalEventProducer,
    build_blueprint_approval_dedupe_key,
)
from xmuse_core.structuring.blueprint_execution.automation_service import (
    BlueprintAutomationResult,
    BlueprintAutomationService,
)
from xmuse_core.structuring.blueprint_execution.feature_planning import (
    CodexPlanningAdapterFactory,
    FeaturePlanningResult,
    FeaturePlanningService,
)
from xmuse_core.structuring.feature_plan_store import (
    FeaturePlanStore,
    read_approved_mission_blueprint,
)
from xmuse_core.structuring.models import PlanningEvent, PlanningEventStatus, PlanningRunStatus
from xmuse_core.structuring.planning_contracts import (
    PlannerGodRequest,
    PlannerGodResponse,
    PlanningReviewFinding,
    PlanningReviewPhase,
    PlanningReviewRequest,
    PlanningReviewResponse,
)
from xmuse_core.structuring.planning_event_store import PlanningEventStore
from xmuse_core.structuring.planning_run_store import PlanningRunStore


def _approved_mission_blueprint_resolution(
    *,
    resolution_id: str = "res-1",
    blueprint_ref: str | None = None,
) -> StructuredResolution:
    resolved_blueprint_ref = blueprint_ref or f"resolution:{resolution_id}:mission_blueprint"
    return StructuredResolution(
        id=resolution_id,
        conversation_id="conv-1",
        version=1,
        status=ResolutionStatus.APPROVED,
        derived_from_proposal_ids=["proposal-1"],
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve the blueprint",
        content={
            "type": "mission_blueprint",
            "title": "Mission Alpha",
            "body": "Create an execution-ready plan.",
            "acceptance_criteria": ["Emit the durable approval event once."],
            "blueprint_ref": resolved_blueprint_ref,
        },
        created_at="2026-05-31T00:00:00Z",
    )


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def _approved_blueprint(*, conversation_id: str = "conv-1"):
    return read_approved_mission_blueprint(
        _approved_mission_blueprint_resolution().model_copy(
            update={"conversation_id": conversation_id}
        )
    )


def _planner_response(
    *,
    conversation_id: str = "conv-1",
    feature_plan_id: str,
    request_id: str = "planner-request-1",
    correlation_id: str = "feature-plan-correlation-1",
    feature_plan_version: int = 1,
) -> PlannerGodResponse:
    return PlannerGodResponse.model_validate(
        {
            "request_id": request_id,
            "correlation_id": correlation_id,
            "conversation_id": conversation_id,
            "feature_plan_id": feature_plan_id,
            "feature_plan_version": feature_plan_version,
            "source_blueprint_ref": "resolution:res-1:mission_blueprint",
            "artifact_refs": [
                "artifact:blueprint-card-1",
                "artifact:planner-proposal-1",
            ],
            "blueprint_refs": [
                "resolution:res-1:mission_blueprint",
            ],
            "planning_rationale": "Keep the plan medium-grained and replay-safe.",
            "features": [
                {
                    "feature_id": "B2",
                    "title": "Provider-routed planning",
                    "goal": "Route planner and reviewer through provider policy.",
                    "acceptance_criteria": [
                        "Planner and reviewer run through provider contracts.",
                    ],
                    "dependencies": [],
                    "graph_id": "graph-B2",
                    "blueprint_refs": [
                        "resolution:res-1:mission_blueprint",
                    ],
                    "artifact_refs": ["artifact:planner-proposal-1"],
                    "risk_notes": ["Touches provider selection."],
                    "planning_rationale": "This is the smallest planning slice.",
                    "dependency_rationale": "No prerequisite feature is required.",
                }
            ],
        }
    )


def _review_response(
    verdict: str,
    *,
    conversation_id: str = "conv-1",
    feature_plan_id: str,
    request_id: str = "review-request-1",
    correlation_id: str = "feature-plan-review-correlation-1",
    artifact_version: int = 1,
    summary: str = "Feature plan looks good.",
) -> PlanningReviewResponse:
    return PlanningReviewResponse(
        request_id=request_id,
        correlation_id=correlation_id,
        conversation_id=conversation_id,
        phase=PlanningReviewPhase.FEATURE_PLAN_REVIEW,
        artifact_id=feature_plan_id,
        artifact_version=artifact_version,
        verdict=verdict,
        summary=summary,
        artifact_refs=["artifact:review-1"],
        blueprint_refs=["resolution:res-1:mission_blueprint"],
        feature_ids=["B2"],
        lane_ids=[],
        dependency_rationale_notes=["No extra dependency in this focused test."],
        findings=[
            PlanningReviewFinding(
                code="acceptance_coverage",
                severity="low",
                message="Coverage is acceptable.",
                artifact_refs=["artifact:planner-proposal-1"],
                feature_ids=["B2"],
                lane_ids=[],
            )
        ],
    )


class FakePlannerAdapter:
    def __init__(self, responses: list[PlannerGodResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[PlannerGodRequest] = []

    async def request_plan(self, request: PlannerGodRequest) -> PlannerGodResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("planner request exceeded prepared responses")
        return self._responses.pop(0)


class FakeReviewAdapter:
    def __init__(self, responses: list[PlanningReviewResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[PlanningReviewRequest] = []

    async def request_review(self, request: PlanningReviewRequest) -> PlanningReviewResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("review request exceeded prepared responses")
        return self._responses.pop(0)


class FakePlanningAdapterFactory:
    def __init__(self, *, planner: FakePlannerAdapter, reviewer: FakeReviewAdapter) -> None:
        self._planner = planner
        self._reviewer = reviewer
        self.planner_decisions = []
        self.reviewer_decisions = []

    def build_planner(self, *, decision):
        self.planner_decisions.append(decision)
        return self._planner

    def build_reviewer(self, *, decision):
        self.reviewer_decisions.append(decision)
        return self._reviewer


class ShadowReplayState(TypedDict, total=False):
    automation_result: dict[str, Any]
    planning_result: dict[str, Any]


def _seed_blueprint_approval(
    base_dir: Path,
    *,
    planning_run_id: str = "planrun-shadow-1",
) -> None:
    queue_path = base_dir / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    approved_event = producer.enqueue_for_resolution(_approved_mission_blueprint_resolution())
    assert approved_event is not None
    PlanningEventStore(queue_path).attach_planning_run(
        approved_event.event_id,
        planning_run_id,
    )


def _build_feature_planning_service(
    base_dir: Path,
    *,
    planner: FakePlannerAdapter,
    reviewer: FakeReviewAdapter,
) -> FeaturePlanningService:
    return FeaturePlanningService(
        base_dir=base_dir,
        now=lambda: "2026-05-31T00:02:00Z",
        event_bus=EventBus(audit_log_path=base_dir / "audit_events.json"),
        blueprint_loader=lambda *, event, planning_run: _approved_blueprint(
            conversation_id=planning_run.conversation_id
        ),
        adapter_factory=FakePlanningAdapterFactory(planner=planner, reviewer=reviewer),
    )


def _serialize_automation_result(result: BlueprintAutomationResult) -> dict[str, Any]:
    return {
        "claimed_event_id": result.claimed_event_id,
        "planning_run_id": result.planning_run_id,
        "next_event_id": result.next_event_id,
        "audit_ref": result.audit_ref,
        "chat_card_ref": result.chat_card_ref,
    }


def _serialize_planning_result(result: FeaturePlanningResult) -> dict[str, Any]:
    return {
        "claimed_event_id": result.claimed_event_id,
        "planning_run_id": result.planning_run_id,
        "feature_plan_id": result.feature_plan_id,
        "feature_plan_version": result.feature_plan_version,
        "outcome": result.outcome,
        "ready_intent_ref": result.ready_intent_ref,
        "planner_provider_profile_ref": result.planner_provider_profile_ref,
        "reviewer_provider_profile_ref": result.reviewer_provider_profile_ref,
    }


def _planning_event_snapshot(path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            """
            select
                event_id,
                event_type,
                planning_run_id,
                conversation_id,
                blueprint_ref,
                dedupe_key,
                idempotency_key,
                status,
                payload_json
            from planning_events
            order by event_id
            """
        ).fetchall()
    return [
        {
            "event_id": row[0],
            "event_type": row[1],
            "planning_run_id": row[2],
            "conversation_id": row[3],
            "blueprint_ref": row[4],
            "dedupe_key": row[5],
            "idempotency_key": row[6],
            "status": row[7],
            "payload": json.loads(row[8]),
        }
        for row in rows
    ]


def _audit_log_snapshot(path: Path) -> list[dict[str, Any]]:
    events = json.loads(path.read_text(encoding="utf-8"))["events"]
    return [
        {
            "event_type": event["event_type"],
            "metadata": event["metadata"],
        }
        for event in events
    ]


def _execution_snapshot(
    base_dir: Path,
    *,
    planning_run_id: str = "planrun-shadow-1",
) -> dict[str, Any]:
    run = PlanningRunStore(base_dir / "planning_runs.sqlite3").get(planning_run_id)
    planning_run_snapshot = run.model_dump(mode="json")
    planning_run_snapshot["created_at"] = "<runtime-created-at>"
    feature_plan_id = f"{planning_run_id}-feature-plan"
    stored_plan = FeaturePlanStore(base_dir / "feature_plans").load(
        feature_plan_id,
        conversation_id="conv-1",
    )
    deliberation = FeaturePlanStore(base_dir / "feature_plans").load_deliberation(
        feature_plan_id,
        conversation_id="conv-1",
    )
    return {
        "planning_run": planning_run_snapshot,
        "planning_events": _planning_event_snapshot(base_dir / "planning_events.sqlite3"),
        "audit_events": _audit_log_snapshot(base_dir / "audit_events.json"),
        "chat_intents": [
            intent.model_dump(mode="json")
            for intent in ChatExecutionCardEmitter(base_dir).list_intents("conv-1")
        ],
        "feature_plan": stored_plan.model_dump(mode="json"),
        "deliberation": deliberation.model_dump(mode="json"),
    }


async def _run_native_blueprint_execution(
    base_dir: Path,
    *,
    planning_run_id: str = "planrun-shadow-1",
) -> dict[str, Any]:
    _seed_blueprint_approval(base_dir, planning_run_id=planning_run_id)
    automation_service = BlueprintAutomationService(
        base_dir=base_dir,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=base_dir / "audit_events.json"),
    )
    automation_result = automation_service.tick(worker_id="planner-automation-native")
    assert automation_result is not None

    feature_plan_id = f"{planning_run_id}-feature-plan"
    planner = FakePlannerAdapter([_planner_response(feature_plan_id=feature_plan_id)])
    reviewer = FakeReviewAdapter(
        [_review_response("approve", feature_plan_id=feature_plan_id)]
    )
    planning_service = _build_feature_planning_service(
        base_dir,
        planner=planner,
        reviewer=reviewer,
    )
    planning_result = await planning_service.tick(worker_id="feature-planner-native")
    assert planning_result is not None
    return {
        "automation_result": _serialize_automation_result(automation_result),
        "planning_result": _serialize_planning_result(planning_result),
        "planner_request_count": len(planner.requests),
        "review_request_count": len(reviewer.requests),
        "snapshot": _execution_snapshot(base_dir, planning_run_id=planning_run_id),
    }


async def _run_langgraph_shadow_replay(
    base_dir: Path,
    *,
    planning_run_id: str = "planrun-shadow-1",
) -> dict[str, Any]:
    _seed_blueprint_approval(base_dir, planning_run_id=planning_run_id)
    automation_service = BlueprintAutomationService(
        base_dir=base_dir,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=base_dir / "audit_events.json"),
    )

    feature_plan_id = f"{planning_run_id}-feature-plan"
    planner = FakePlannerAdapter([_planner_response(feature_plan_id=feature_plan_id)])
    reviewer = FakeReviewAdapter(
        [_review_response("approve", feature_plan_id=feature_plan_id)]
    )
    planning_service = _build_feature_planning_service(
        base_dir,
        planner=planner,
        reviewer=reviewer,
    )

    graph = StateGraph(ShadowReplayState)

    def automation_node(_: ShadowReplayState) -> ShadowReplayState:
        result = automation_service.tick(worker_id="planner-automation-langgraph")
        assert result is not None
        return {"automation_result": _serialize_automation_result(result)}

    async def planning_node(_: ShadowReplayState) -> ShadowReplayState:
        result = await planning_service.tick(worker_id="feature-planner-langgraph")
        assert result is not None
        return {"planning_result": _serialize_planning_result(result)}

    graph.add_node("automation", automation_node)
    graph.add_node("planning", planning_node)
    graph.add_edge(START, "automation")
    graph.add_edge("automation", "planning")
    graph.add_edge("planning", END)

    state = await graph.compile().ainvoke({})
    return {
        "automation_result": dict(state["automation_result"]),
        "planning_result": dict(state["planning_result"]),
        "planner_request_count": len(planner.requests),
        "review_request_count": len(reviewer.requests),
        "snapshot": _execution_snapshot(base_dir, planning_run_id=planning_run_id),
    }


def test_blueprint_approval_event_producer_enqueues_one_event_per_resolution(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    resolution = _approved_mission_blueprint_resolution()

    first = producer.enqueue_for_resolution(resolution)
    second = producer.enqueue_for_resolution(resolution)

    assert first is not None
    assert second == first
    assert first.event_type == "blueprint.approved"
    assert first.planning_run_id is None
    assert first.dedupe_key == build_blueprint_approval_dedupe_key(
        conversation_id=resolution.conversation_id,
        blueprint_artifact_id=f"resolution:{resolution.id}:mission_blueprint",
        resolution_id=resolution.id,
    )
    assert first.payload == {
        "resolution_id": resolution.id,
        "resolution_version": resolution.version,
        "blueprint_artifact_id": f"resolution:{resolution.id}:mission_blueprint",
        "goal_summary": resolution.goal_summary,
        "approved_by": ["human"],
        "approval_mode": "manual",
        "human_trigger_enabled": False,
    }

    with sqlite3.connect(queue_path) as conn:
        count = conn.execute("select count(*) from planning_events").fetchone()[0]

    assert count == 1


def test_blueprint_approval_event_producer_ignores_non_blueprint_resolutions(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    resolution = _approved_mission_blueprint_resolution(
        resolution_id="res-feature",
        blueprint_ref="resolution:res-feature:feature_plan",
    ).model_copy(
        update={
            "content": {
                "type": "feature_plan",
                "source_blueprint_ref": "resolution:res-1:mission_blueprint",
            }
        }
    )

    event = producer.enqueue_for_resolution(resolution)

    assert event is None
    with sqlite3.connect(queue_path) as conn:
        count = conn.execute("select count(*) from planning_events").fetchone()[0]

    assert count == 0


def test_blueprint_automation_service_claims_approval_and_persists_started_state(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
        human_trigger_enabled=True,
    )
    approved_event = producer.enqueue_for_resolution(_approved_mission_blueprint_resolution())
    assert approved_event is not None

    service = BlueprintAutomationService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
    )

    result = service.tick(worker_id="planner-automation")

    assert result is not None
    assert result.claimed_event_id == approved_event.event_id

    queue = PlanningEventStore(queue_path)
    acked = queue.get(approved_event.event_id)
    assert acked.status is PlanningEventStatus.ACKED
    assert acked.planning_run_id == result.planning_run_id

    started = queue.get(result.next_event_id)
    assert started == PlanningEvent(
        event_id=result.next_event_id,
        event_type="planning.started",
        planning_run_id=result.planning_run_id,
        conversation_id="conv-1",
        blueprint_ref="resolution:res-1:mission_blueprint",
        dedupe_key=approved_event.dedupe_key,
        idempotency_key=f"planning.started:{result.planning_run_id}",
        status=PlanningEventStatus.QUEUED,
        attempt=0,
        lease_owner=None,
        lease_expires_at=None,
        payload={
            **approved_event.payload,
            "source_event_id": approved_event.event_id,
        },
        created_at="2026-05-31T00:01:00Z",
        updated_at="2026-05-31T00:01:00Z",
        available_at=None,
        last_error_reason=None,
        lease_ttl_seconds=None,
        recovered_from_stale_lease=False,
    )

    run = PlanningRunStore(tmp_path / "planning_runs.sqlite3").get(result.planning_run_id)
    assert run.blueprint_version == 1
    assert run.status is PlanningRunStatus.PLANNING
    assert run.human_trigger_enabled is True
    assert run.audit_refs == [result.audit_ref]
    assert run.chat_card_refs == [result.chat_card_ref]

    intent = ChatExecutionCardEmitter(tmp_path).get_intent("conv-1", result.chat_card_ref)
    assert intent.card_type == "blueprint_execution_started"
    assert intent.planning_run_id == result.planning_run_id
    assert intent.payload == {
        "resolution_id": "res-1",
        "blueprint_ref": "resolution:res-1:mission_blueprint",
    }

    audit_log = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    assert [event["event_type"] for event in audit_log["events"]] == [
        "blueprint.execution.started"
    ]
    metadata = audit_log["events"][0]["metadata"]
    assert metadata["planning_run_id"] == result.planning_run_id
    assert metadata["source_event_ref"] == f"planning_events.sqlite3#{approved_event.event_id}"
    assert metadata["next_event_ref"] == f"planning_events.sqlite3#{result.next_event_id}"
    assert metadata["chat_card_ref"] == result.chat_card_ref


def test_blueprint_automation_service_replay_reuses_run_and_existing_artifacts(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    approved_event = producer.enqueue_for_resolution(_approved_mission_blueprint_resolution())
    assert approved_event is not None

    service = BlueprintAutomationService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
    )
    first = service.tick(worker_id="planner-automation")
    assert first is not None

    run_store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    run = run_store.get(first.planning_run_id)
    run_store.save(
        run.model_copy(
            update={
                "audit_refs": [],
                "chat_card_refs": [],
                "updated_at": "2026-05-31T00:01:30Z",
            }
        )
    )

    with sqlite3.connect(queue_path) as conn:
        conn.execute(
            """
            update planning_events
            set status = ?, updated_at = ?, lease_owner = null, lease_expires_at = null
            where event_id = ?
            """,
            (
                PlanningEventStatus.QUEUED.value,
                "2026-05-31T00:02:00Z",
                approved_event.event_id,
            ),
        )

    replay = service.tick(worker_id="planner-automation")

    assert replay is not None
    assert replay.planning_run_id == first.planning_run_id
    assert replay.next_event_id == first.next_event_id
    assert replay.audit_ref == first.audit_ref
    assert replay.chat_card_ref == first.chat_card_ref

    reloaded = run_store.get(first.planning_run_id)
    assert reloaded.audit_refs == [first.audit_ref]
    assert reloaded.chat_card_refs == [first.chat_card_ref]

    with sqlite3.connect(queue_path) as conn:
        rows = conn.execute(
            "select event_id, event_type, planning_run_id from planning_events order by event_id"
        ).fetchall()
    assert {row[1]: (row[0], row[2]) for row in rows} == {
        "blueprint.approved": (approved_event.event_id, first.planning_run_id),
        "planning.started": (first.next_event_id, first.planning_run_id),
    }

    intents = ChatExecutionCardEmitter(tmp_path).list_intents("conv-1")
    assert [intent.intent_id for intent in intents] == [first.chat_card_ref]

    audit_log = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    assert len(audit_log["events"]) == 1
    assert audit_log["events"][0]["event_type"] == "blueprint.execution.started"


@pytest.mark.asyncio
async def test_feature_planning_service_claims_planning_started_and_routes_through_provider_policy(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    approved_event = producer.enqueue_for_resolution(_approved_mission_blueprint_resolution())
    assert approved_event is not None

    automation_service = BlueprintAutomationService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
    )
    automation_result = automation_service.tick(worker_id="planner-automation")
    assert automation_result is not None

    feature_plan_id = f"{automation_result.planning_run_id}-feature-plan"
    planner = FakePlannerAdapter([_planner_response(feature_plan_id=feature_plan_id)])
    reviewer = FakeReviewAdapter(
        [_review_response("approve", feature_plan_id=feature_plan_id)]
    )
    adapter_factory = FakePlanningAdapterFactory(planner=planner, reviewer=reviewer)
    service = FeaturePlanningService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:02:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        blueprint_loader=lambda *, event, planning_run: _approved_blueprint(
            conversation_id=planning_run.conversation_id
        ),
        adapter_factory=adapter_factory,
    )

    result = await service.tick(worker_id="feature-planner")

    assert result is not None
    assert result.claimed_event_id == automation_result.next_event_id
    assert result.planning_run_id == automation_result.planning_run_id
    assert result.feature_plan_id == feature_plan_id
    assert result.feature_plan_version == 1
    assert result.outcome == "approved"
    assert result.planner_provider_profile_ref == "codex.god"
    assert result.reviewer_provider_profile_ref == "codex.review"

    assert len(planner.requests) == 1
    assert len(reviewer.requests) == 1
    assert adapter_factory.planner_decisions[0].task_type is TaskCapability.PLANNING
    assert adapter_factory.planner_decisions[0].provider_profile_ref == "codex.god"
    assert adapter_factory.reviewer_decisions[0].provider_profile_ref == "codex.review"

    run = PlanningRunStore(tmp_path / "planning_runs.sqlite3").get(result.planning_run_id)
    assert run.status is PlanningRunStatus.FEATURE_PLAN_REVIEW
    assert run.feature_plan_id == feature_plan_id
    assert run.feature_plan_version == 1
    assert run.graph_set_id is None
    assert run.graph_set_version is None
    assert not (tmp_path / "lane_graphs").exists()
    assert not (tmp_path / "feature_lanes.json").exists()

    planning_started = PlanningEventStore(queue_path).get(automation_result.next_event_id)
    assert planning_started.status is PlanningEventStatus.ACKED
    ready_event = PlanningEventStore(queue_path).get(
        f"pevt_{automation_result.planning_run_id}_feature_plan_ready"
    )
    assert ready_event.event_type == "feature_plan.ready"
    assert ready_event.status is PlanningEventStatus.QUEUED
    assert ready_event.idempotency_key == f"feature_plan.ready:{feature_plan_id}:1"
    assert ready_event.payload == {
        "source_event_id": automation_result.next_event_id,
        "planning_run_id": automation_result.planning_run_id,
        "feature_plan_id": feature_plan_id,
        "feature_plan_version": 1,
        "outcome": "approved",
        "artifact_refs": [
            f"planning_events.sqlite3#{automation_result.next_event_id}",
            f"feature_plans/{feature_plan_id}",
        ],
        "source_refs": [f"planning_events.sqlite3#{automation_result.next_event_id}"],
    }

    stored_plan = FeaturePlanStore(tmp_path / "feature_plans").load(
        feature_plan_id,
        conversation_id="conv-1",
    )
    assert stored_plan.status.value == "approved"
    deliberation = FeaturePlanStore(tmp_path / "feature_plans").load_deliberation(
        feature_plan_id,
        conversation_id="conv-1",
    )
    assert deliberation.status == "approved"

    intents = ChatExecutionCardEmitter(tmp_path).list_intents("conv-1")
    assert [intent.card_type for intent in intents] == [
        "blueprint_execution_started",
        "feature_plan_ready",
    ]


@pytest.mark.asyncio
async def test_feature_planning_service_replay_reuses_ready_event_without_graph_side_effects(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    approved_event = producer.enqueue_for_resolution(_approved_mission_blueprint_resolution())
    assert approved_event is not None
    automation_result = BlueprintAutomationService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
    ).tick(worker_id="planner-automation")
    assert automation_result is not None

    feature_plan_id = f"{automation_result.planning_run_id}-feature-plan"
    planner = FakePlannerAdapter([_planner_response(feature_plan_id=feature_plan_id)])
    reviewer = FakeReviewAdapter(
        [_review_response("approve", feature_plan_id=feature_plan_id)]
    )
    service = FeaturePlanningService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:02:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        blueprint_loader=lambda *, event, planning_run: _approved_blueprint(
            conversation_id=planning_run.conversation_id
        ),
        adapter_factory=FakePlanningAdapterFactory(planner=planner, reviewer=reviewer),
    )

    first = await service.tick(worker_id="feature-planner")
    assert first is not None

    with sqlite3.connect(queue_path) as conn:
        conn.execute(
            """
            update planning_events
            set status = ?, updated_at = ?, lease_owner = null, lease_expires_at = null
            where event_id = ?
            """,
            (
                PlanningEventStatus.QUEUED.value,
                "2026-05-31T00:03:00Z",
                automation_result.next_event_id,
            ),
        )

    second = await service.tick(worker_id="feature-planner")

    assert second is not None
    assert second.ready_intent_ref == first.ready_intent_ref
    assert len(planner.requests) == 1
    assert len(reviewer.requests) == 1

    with sqlite3.connect(queue_path) as conn:
        rows = conn.execute(
            "select event_type, count(*) from planning_events group by event_type"
        ).fetchall()
    assert dict(rows) == {
        "blueprint.approved": 1,
        "planning.started": 1,
        "feature_plan.ready": 1,
    }
    assert not (tmp_path / "lane_graphs").exists()
    assert not (tmp_path / "feature_lanes.json").exists()

    run = PlanningRunStore(tmp_path / "planning_runs.sqlite3").get(first.planning_run_id)
    assert len(run.audit_refs) == len(set(run.audit_refs))
    assert run.audit_refs[-2:] == [
        "feature_plan.proposed:1",
        "feature_plan.reviewed:1",
    ]
    audit_events = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    assert [event["event_type"] for event in audit_events["events"]] == [
        "blueprint.execution.started",
        "feature_plan.proposed",
        "feature_plan.reviewed",
    ]
    assert [
        intent.card_type
        for intent in ChatExecutionCardEmitter(tmp_path).list_intents("conv-1")
    ] == [
        "blueprint_execution_started",
        "feature_plan_ready",
    ]


@pytest.mark.asyncio
async def test_feature_planning_service_emits_planning_failed_with_reason_and_refs(
    tmp_path: Path,
) -> None:
    queue_path = tmp_path / "planning_events.sqlite3"
    producer = BlueprintApprovalEventProducer(
        PlanningEventStore(queue_path),
        now=lambda: "2026-05-31T00:00:00Z",
    )
    approved_event = producer.enqueue_for_resolution(_approved_mission_blueprint_resolution())
    assert approved_event is not None
    automation_result = BlueprintAutomationService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:01:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
    ).tick(worker_id="planner-automation")
    assert automation_result is not None

    feature_plan_id = f"{automation_result.planning_run_id}-feature-plan"
    service = FeaturePlanningService(
        base_dir=tmp_path,
        now=lambda: "2026-05-31T00:02:00Z",
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        blueprint_loader=lambda *, event, planning_run: _approved_blueprint(
            conversation_id=planning_run.conversation_id
        ),
        adapter_factory=FakePlanningAdapterFactory(
            planner=FakePlannerAdapter(
                [_planner_response(conversation_id="other-conv", feature_plan_id=feature_plan_id)]
            ),
            reviewer=FakeReviewAdapter([]),
        ),
    )

    result = await service.tick(worker_id="feature-planner")

    assert result is not None
    assert result.outcome == "failed"
    assert result.feature_plan_id == feature_plan_id
    assert result.feature_plan_version is None
    assert result.ready_intent_ref is None

    planning_started = PlanningEventStore(queue_path).get(automation_result.next_event_id)
    assert planning_started.status is PlanningEventStatus.ACKED
    failed_event = PlanningEventStore(queue_path).get(
        f"pevt_{automation_result.planning_run_id}_planning_failed"
    )
    assert failed_event.event_type == "planning.failed"
    assert failed_event.status is PlanningEventStatus.QUEUED
    assert failed_event.idempotency_key == (
        f"planning.failed:{automation_result.planning_run_id}:"
        f"{automation_result.next_event_id}"
    )
    assert failed_event.payload == {
        "source_event_id": automation_result.next_event_id,
        "planning_run_id": automation_result.planning_run_id,
        "feature_plan_id": feature_plan_id,
        "failure_reason": "conversation_id_mismatch",
        "artifact_refs": [f"planning_events.sqlite3#{automation_result.next_event_id}"],
        "source_refs": [f"planning_events.sqlite3#{automation_result.next_event_id}"],
    }
    run = PlanningRunStore(tmp_path / "planning_runs.sqlite3").get(result.planning_run_id)
    assert run.status is PlanningRunStatus.FAILED
    assert not (tmp_path / "lane_graphs").exists()
    assert not (tmp_path / "feature_lanes.json").exists()


def test_codex_planning_adapter_factory_uses_provider_policy_models_by_default(
    tmp_path: Path,
) -> None:
    policy = ProviderPolicyService()
    factory = CodexPlanningAdapterFactory(
        db_path=tmp_path / "chat.db",
        session_layer=object(),
        worktree=tmp_path,
    )

    planner = factory.build_planner(
        decision=policy.select_god(task_type=TaskCapability.PLANNING)
    )
    reviewer = factory.build_reviewer(decision=policy.select_review())

    assert isinstance(planner, PlannerGodAdapter)
    assert isinstance(reviewer, ReviewGodAdapter)


@pytest.mark.asyncio
async def test_langgraph_shadow_replay_matches_native_blueprint_execution_artifacts(
    tmp_path: Path,
) -> None:
    native = await _run_native_blueprint_execution(tmp_path / "native")
    shadow = await _run_langgraph_shadow_replay(tmp_path / "langgraph")

    assert shadow["automation_result"] == native["automation_result"]
    assert shadow["planning_result"] == native["planning_result"]
    assert shadow["planner_request_count"] == 1
    assert shadow["review_request_count"] == 1
    assert shadow["snapshot"] == native["snapshot"]


@pytest.mark.asyncio
async def test_langgraph_shadow_replay_never_calls_direct_lane_status_mutators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_write_calls: list[str] = []

    def _forbid_lane_status_write(*args: Any, **kwargs: Any) -> None:
        direct_write_calls.append("lane-status-write")
        raise AssertionError("LangGraph shadow replay must not write lane status directly")

    monkeypatch.setattr(LaneProjectionSyncer, "update_lane", _forbid_lane_status_write)
    monkeypatch.setattr(
        LaneProjectionSyncer,
        "metadata_update",
        _forbid_lane_status_write,
    )
    monkeypatch.setattr(
        McpToolHandler,
        "_tool_update_lane_status",
        _forbid_lane_status_write,
    )

    base_dir = tmp_path / "langgraph"
    shadow = await _run_langgraph_shadow_replay(base_dir)

    assert direct_write_calls == []
    assert "projected_lanes" not in shadow["snapshot"]
    assert not (base_dir / "feature_lanes.json").exists()
    assert sorted(
        event["event_type"] for event in shadow["snapshot"]["planning_events"]
    ) == [
        "blueprint.approved",
        "feature_plan.ready",
        "planning.started",
    ]
