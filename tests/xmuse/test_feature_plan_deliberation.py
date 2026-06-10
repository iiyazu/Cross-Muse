from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.structuring.feature_plan_deliberation import (
    FeaturePlanDeliberationService,
)
from xmuse_core.structuring.feature_plan_store import (
    FeaturePlanDeliberationAttempt,
    FeaturePlanDeliberationRecord,
    FeaturePlanStore,
)
from xmuse_core.structuring.models import ApprovedMissionBlueprint, FeaturePlanProposalStatus
from xmuse_core.structuring.planning_contracts import (
    PlannerGodRequest,
    PlannerGodResponse,
    PlanningReviewFinding,
    PlanningReviewPhase,
    PlanningReviewRequest,
    PlanningReviewResponse,
)


def _approved_blueprint(*, conversation_id: str = "conv-1") -> ApprovedMissionBlueprint:
    return ApprovedMissionBlueprint(
        resolution_id="res-blueprint-1",
        conversation_id=conversation_id,
        version=1,
        title="Autonomous blueprint execution MVP",
        body="Turn approved mission blueprints into feature plans and graph sets.",
        acceptance_criteria=[
            "Planner returns a medium-grained feature plan proposal.",
            "Review handles bounded rework.",
        ],
        references=[
            "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
            "xmuse/work/c_class_autonomous_blueprint_execution_graph_preview.md",
        ],
        blueprint_ref="resolution:res-blueprint-1:mission_blueprint",
    )


def _planner_response(
    *,
    conversation_id: str = "conv-1",
    request_id: str | None = None,
    correlation_id: str | None = None,
    feature_plan_version: int = 1,
    artifact_suffix: str = "1",
    title: str = "Planner contracts",
) -> PlannerGodResponse:
    return PlannerGodResponse.model_validate(
        {
            "request_id": request_id or f"planner-request-{feature_plan_version}",
            "correlation_id": correlation_id
            or f"feature-plan-correlation-{feature_plan_version}",
            "conversation_id": conversation_id,
            "feature_plan_id": "feature-plan-1",
            "feature_plan_version": feature_plan_version,
            "source_blueprint_ref": "resolution:res-blueprint-1:mission_blueprint",
            "artifact_refs": [
                "artifact:blueprint-card-1",
                f"artifact:planner-proposal-{artifact_suffix}",
            ],
            "blueprint_refs": [
                "resolution:res-blueprint-1:mission_blueprint",
                "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
            ],
            "planning_rationale": "Keep the feature plan medium-grained and replay-safe.",
            "features": [
                {
                    "feature_id": "C3",
                    "title": title,
                    "goal": "Define bounded planner and review contracts.",
                    "acceptance_criteria": [
                        "Planner outputs validate.",
                        "Review can request bounded rework.",
                    ],
                    "dependencies": [],
                    "graph_id": "graph-C3",
                    "blueprint_refs": [
                        "resolution:res-blueprint-1:mission_blueprint",
                        "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
                    ],
                    "artifact_refs": [f"artifact:planner-proposal-{artifact_suffix}"],
                    "risk_notes": ["Touches planning persistence."],
                    "planning_rationale": "This feature defines the planning protocol.",
                    "dependency_rationale": (
                        "No prerequisite feature is required in this focused test."
                    ),
                }
            ],
        }
    )


def _review_response(
    verdict: str,
    *,
    conversation_id: str = "conv-1",
    request_id: str = "review-request-1",
    correlation_id: str = "feature-plan-review-correlation-1",
    summary: str = "Feature plan looks good.",
    artifact_suffix: str = "1",
    findings: list[PlanningReviewFinding] | None = None,
) -> PlanningReviewResponse:
    return PlanningReviewResponse(
        request_id=request_id,
        correlation_id=correlation_id,
        conversation_id=conversation_id,
        phase=PlanningReviewPhase.FEATURE_PLAN_REVIEW,
        artifact_id="feature-plan-1",
        artifact_version=1 if artifact_suffix == "1" else 2,
        verdict=verdict,
        summary=summary,
        artifact_refs=[f"artifact:review-{artifact_suffix}"],
        blueprint_refs=[
            "resolution:res-blueprint-1:mission_blueprint",
            "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
        ],
        feature_ids=["C3"],
        lane_ids=[],
        dependency_rationale_notes=["No cross-feature dependency in this focused test."],
        findings=findings or [],
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


@pytest.mark.asyncio
async def test_feature_plan_deliberation_approves_and_persists_ready_intent(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter([_planner_response()])
    reviewer = FakeReviewAdapter([_review_response("approve")])
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    result = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=_approved_blueprint(),
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    assert result.outcome == "approved"
    assert result.rework_count == 0
    assert result.ready_intent_ref is not None

    stored = FeaturePlanStore(tmp_path / "feature_plans").load(
        "feature-plan-1",
        conversation_id="conv-1",
    )
    assert stored.status == FeaturePlanProposalStatus.APPROVED
    assert stored.approval is not None
    assert stored.features[0].title == "Planner contracts"

    record = FeaturePlanStore(tmp_path / "feature_plans").load_deliberation(
        "feature-plan-1",
        conversation_id="conv-1",
    )
    assert record.status == "approved"
    assert record.rework_count == 0
    assert len(record.attempts) == 1
    assert record.attempts[0].ready_intent_ref == result.ready_intent_ref

    events = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    assert [event["event_type"] for event in events["events"]] == [
        "feature_plan.proposed",
        "feature_plan.reviewed",
    ]
    proposed_metadata = events["events"][0]["metadata"]
    assert proposed_metadata["planning_run_id"] == "planrun-1"
    assert proposed_metadata["request_id"] == "planner-request-1"
    assert proposed_metadata["evidence_refs"] == [
        "artifact:blueprint-card-1",
        "artifact:planner-proposal-1",
    ]

    intents = ChatExecutionCardEmitter(tmp_path).list_intents("conv-1")
    assert len(intents) == 1
    assert intents[0].card_type == "feature_plan_ready"
    assert intents[0].payload == {"feature_plan_id": "feature-plan-1"}


@pytest.mark.asyncio
async def test_feature_plan_deliberation_does_not_emit_ready_card_for_rejected_plan(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter([_planner_response()])
    reviewer = FakeReviewAdapter(
        [
            _review_response(
                "reject_as_invalid",
                summary="Feature plan does not match the approved blueprint.",
            )
        ]
    )
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    result = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=_approved_blueprint(),
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    assert result.outcome == "rejected"
    assert result.ready_intent_ref is None
    assert ChatExecutionCardEmitter(tmp_path).list_intents("conv-1") == []


@pytest.mark.asyncio
async def test_feature_plan_deliberation_reworks_once_then_approves(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter(
        [
            _planner_response(feature_plan_version=1, artifact_suffix="1", title="Draft split"),
            _planner_response(feature_plan_version=2, artifact_suffix="2", title="Reworked split"),
        ]
    )
    reviewer = FakeReviewAdapter(
        [
            _review_response(
                "request_rework",
                summary="Needs a narrower medium-grained feature split.",
                artifact_suffix="1",
                findings=[
                    PlanningReviewFinding(
                        code="feature_scope_too_broad",
                        severity="medium",
                        message=(
                            "Split the plan into one execution feature instead "
                            "of two broad themes."
                        ),
                        artifact_refs=["artifact:planner-proposal-1"],
                        feature_ids=["C3"],
                        lane_ids=[],
                    )
                ],
            ),
            _review_response(
                "approve",
                request_id="review-request-2",
                correlation_id="feature-plan-review-correlation-2",
                summary="Reworked feature plan is acceptable.",
                artifact_suffix="2",
            ),
        ]
    )
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        max_reworks=2,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    result = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=_approved_blueprint(),
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    assert result.outcome == "approved"
    assert result.rework_count == 1
    assert len(planner.requests) == 2
    assert len(reviewer.requests) == 2

    second_request = planner.requests[1]
    assert second_request.feature_plan_version == 2
    assert second_request.rework_context is not None
    assert second_request.rework_context.previous_feature_plan.feature_plan_version == 1
    assert second_request.rework_context.review_summary == (
        "Needs a narrower medium-grained feature split."
    )
    assert second_request.rework_context.expected_fix == (
        "Address the review findings and return a revised feature plan proposal."
    )
    assert second_request.artifact_refs == [
        "artifact:blueprint-card-1",
        "artifact:planner-proposal-1",
        "artifact:review-1",
    ]

    record = FeaturePlanStore(tmp_path / "feature_plans").load_deliberation(
        "feature-plan-1",
        conversation_id="conv-1",
    )
    assert record.rework_count == 1
    assert record.status == "approved"
    assert [attempt.proposal.features[0].title for attempt in record.attempts] == [
        "Draft split",
        "Reworked split",
    ]
    assert record.attempts[0].ready_intent_ref is None
    assert record.attempts[1].ready_intent_ref == result.ready_intent_ref
    intents = ChatExecutionCardEmitter(tmp_path).list_intents("conv-1")
    assert len(intents) == 1
    assert intents[0].intent_id == result.ready_intent_ref


@pytest.mark.asyncio
async def test_feature_plan_deliberation_allows_configured_single_rework_attempt(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter(
        [
            _planner_response(feature_plan_version=1, artifact_suffix="1", title="Draft split"),
            _planner_response(feature_plan_version=2, artifact_suffix="2", title="Reworked split"),
        ]
    )
    reviewer = FakeReviewAdapter(
        [
            _review_response("request_rework", artifact_suffix="1"),
            _review_response(
                "approve",
                request_id="review-request-2",
                correlation_id="feature-plan-review-correlation-2",
                artifact_suffix="2",
            ),
        ]
    )
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        max_reworks=1,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    result = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=_approved_blueprint(),
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    assert result.outcome == "approved"
    assert result.rework_count == 1
    assert len(planner.requests) == 2
    assert len(reviewer.requests) == 2


@pytest.mark.asyncio
async def test_feature_plan_deliberation_replay_processes_persisted_review_verdict(
    tmp_path: Path,
) -> None:
    blueprint = _approved_blueprint()
    response = _planner_response()
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=FakePlannerAdapter([]),
        reviewer=FakeReviewAdapter([]),
        now=lambda: "2026-05-31T12:00:00Z",
    )
    proposal = service._proposal_from_response(response, blueprint)
    store = FeaturePlanStore(tmp_path / "feature_plans")
    store.save(proposal)
    store.save_deliberation(
        FeaturePlanDeliberationRecord(
            planning_run_id="planrun-1",
            conversation_id="conv-1",
            feature_plan_id="feature-plan-1",
            source_blueprint_ref=blueprint.blueprint_ref,
            status="feature_plan_review",
            max_reworks=2,
            rework_count=0,
            artifact_refs=["artifact:blueprint-card-1"],
            audit_refs=[
                "feature_plan.proposed:1",
                "feature_plan.reviewed:1",
            ],
            attempts=[
                FeaturePlanDeliberationAttempt(
                    attempt_number=1,
                    feature_plan_version=1,
                    planner_request_id="planner-request-1",
                    planner_correlation_id="feature-plan-correlation-1",
                    planner_response=response,
                    proposal=proposal,
                    proposed_event_emitted=True,
                    review_request_id="review-request-1",
                    review_correlation_id="feature-plan-review-correlation-1",
                    review_response=_review_response("approve"),
                    reviewed_event_emitted=True,
                )
            ],
            created_at="2026-05-31T12:00:00Z",
            updated_at="2026-05-31T12:00:00Z",
        )
    )

    result = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=blueprint,
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    assert result.outcome == "approved"
    assert result.ready_intent_ref is not None
    stored = store.load("feature-plan-1", conversation_id="conv-1")
    assert stored.status == FeaturePlanProposalStatus.APPROVED


@pytest.mark.asyncio
async def test_feature_plan_deliberation_replay_publishes_missing_attempt_events(
    tmp_path: Path,
) -> None:
    blueprint = _approved_blueprint()
    response = _planner_response()
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=FakePlannerAdapter([]),
        reviewer=FakeReviewAdapter([]),
        now=lambda: "2026-05-31T12:00:00Z",
    )
    proposal = service._proposal_from_response(response, blueprint)
    store = FeaturePlanStore(tmp_path / "feature_plans")
    store.save(proposal)
    store.save_deliberation(
        FeaturePlanDeliberationRecord(
            planning_run_id="planrun-1",
            conversation_id="conv-1",
            feature_plan_id="feature-plan-1",
            source_blueprint_ref=blueprint.blueprint_ref,
            status="feature_plan_review",
            max_reworks=2,
            rework_count=0,
            artifact_refs=["artifact:blueprint-card-1"],
            attempts=[
                FeaturePlanDeliberationAttempt(
                    attempt_number=1,
                    feature_plan_version=1,
                    planner_request_id="planner-request-1",
                    planner_correlation_id="feature-plan-correlation-1",
                    planner_response=response,
                    proposal=proposal,
                    proposed_event_emitted=False,
                    review_request_id="review-request-1",
                    review_correlation_id="feature-plan-review-correlation-1",
                    review_response=_review_response("approve"),
                    reviewed_event_emitted=False,
                )
            ],
            created_at="2026-05-31T12:00:00Z",
            updated_at="2026-05-31T12:00:00Z",
        )
    )

    await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=blueprint,
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    events = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    assert [event["event_type"] for event in events["events"]] == [
        "feature_plan.proposed",
        "feature_plan.reviewed",
    ]
    record = store.load_deliberation("feature-plan-1", conversation_id="conv-1")
    assert record.attempts[0].proposed_event_emitted is True
    assert record.attempts[0].reviewed_event_emitted is True


@pytest.mark.asyncio
async def test_feature_plan_deliberation_rejects_service_level_planner_identity_mismatch(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter([_planner_response(conversation_id="other-conv")])
    reviewer = FakeReviewAdapter([])
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    with pytest.raises(ValueError, match="conversation_id_mismatch"):
        await service.deliberate(
            planning_run_id="planrun-1",
            blueprint=_approved_blueprint(),
            feature_plan_id="feature-plan-1",
            artifact_refs=["artifact:blueprint-card-1"],
        )


@pytest.mark.asyncio
async def test_feature_plan_deliberation_rejects_service_level_review_identity_mismatch(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter([_planner_response()])
    reviewer = FakeReviewAdapter([_review_response("approve", request_id="wrong-request")])
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    with pytest.raises(ValueError, match="request_id_mismatch"):
        await service.deliberate(
            planning_run_id="planrun-1",
            blueprint=_approved_blueprint(),
            feature_plan_id="feature-plan-1",
            artifact_refs=["artifact:blueprint-card-1"],
        )


@pytest.mark.asyncio
async def test_feature_plan_deliberation_reuses_existing_ready_intent_on_replay(
    tmp_path: Path,
) -> None:
    planner = FakePlannerAdapter([_planner_response()])
    reviewer = FakeReviewAdapter([_review_response("approve")])
    service = FeaturePlanDeliberationService(
        feature_plans_root=tmp_path / "feature_plans",
        card_emitter=ChatExecutionCardEmitter(tmp_path),
        event_bus=EventBus(audit_log_path=tmp_path / "audit_events.json"),
        planner=planner,
        reviewer=reviewer,
        now=lambda: "2026-05-31T12:00:00Z",
    )

    first = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=_approved_blueprint(),
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )
    second = await service.deliberate(
        planning_run_id="planrun-1",
        blueprint=_approved_blueprint(),
        feature_plan_id="feature-plan-1",
        artifact_refs=["artifact:blueprint-card-1"],
    )

    assert first.ready_intent_ref == second.ready_intent_ref
    assert len(planner.requests) == 1
    assert len(reviewer.requests) == 1

    intents = ChatExecutionCardEmitter(tmp_path).list_intents("conv-1")
    assert len(intents) == 1
    assert intents[0].intent_id == first.ready_intent_ref

    events = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    assert [event["event_type"] for event in events["events"]] == [
        "feature_plan.proposed",
        "feature_plan.reviewed",
    ]
