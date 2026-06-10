from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.structuring.feature_plan_store import (
    FeaturePlanDeliberationAttempt,
    FeaturePlanDeliberationRecord,
    FeaturePlanStore,
    approve_feature_plan_proposal,
)
from xmuse_core.structuring.models import (
    ApprovedMissionBlueprint,
    FeaturePlanFeature,
    FeaturePlanProposal,
    FeaturePlanProposalApproval,
)
from xmuse_core.structuring.planning_contracts import (
    PlannerGodRequest,
    PlannerGodResponse,
    PlannerPreviousFeaturePlan,
    PlannerReworkContext,
    PlanningReviewPhase,
    PlanningReviewRequest,
    PlanningReviewResponse,
    PlanningReviewVerdict,
)


class PlannerProtocol(Protocol):
    async def request_plan(self, request: PlannerGodRequest) -> PlannerGodResponse: ...


class ReviewerProtocol(Protocol):
    async def request_review(self, request: PlanningReviewRequest) -> PlanningReviewResponse: ...


class FeaturePlanDeliberationResult(BaseModel):
    outcome: str
    rework_count: int
    feature_plan_id: str
    feature_plan_version: int | None = None
    ready_intent_ref: str | None = None


class FeaturePlanDeliberationService:
    def __init__(
        self,
        *,
        feature_plans_root: Path | str,
        card_emitter: ChatExecutionCardEmitter,
        event_bus: EventBus,
        planner: PlannerProtocol,
        reviewer: ReviewerProtocol,
        max_reworks: int = 2,
        now: Callable[[], str],
        planner_actor: str = "planner_god",
        reviewer_actor: str = "review_god",
    ) -> None:
        self._store = FeaturePlanStore(feature_plans_root)
        self._card_emitter = card_emitter
        self._event_bus = event_bus
        self._planner = planner
        self._reviewer = reviewer
        self._max_reworks = max_reworks
        self._now = now
        self._planner_actor = planner_actor
        self._reviewer_actor = reviewer_actor

    async def deliberate(
        self,
        *,
        planning_run_id: str,
        blueprint: ApprovedMissionBlueprint,
        feature_plan_id: str,
        artifact_refs: list[str],
    ) -> FeaturePlanDeliberationResult:
        record = self._load_or_create_record(
            planning_run_id=planning_run_id,
            blueprint=blueprint,
            feature_plan_id=feature_plan_id,
            artifact_refs=artifact_refs,
        )
        if record.status in {
            "approved",
            "rejected",
            "challenge_required",
            "manual_review_required",
        }:
            return self._result_from_record(record)

        while True:
            current_attempt = record.attempts[-1] if record.attempts else None
            if current_attempt is None:
                current_attempt = await self._propose_attempt(
                    record=record,
                    blueprint=blueprint,
                    artifact_refs=artifact_refs,
                    attempt_number=1,
                    rework_from=None,
                )
            elif current_attempt.review_response is None:
                pass
            elif (
                record.status == "reworking"
                and current_attempt.review_response.verdict
                == PlanningReviewVerdict.REQUEST_REWORK
            ):
                current_attempt = await self._propose_attempt(
                    record=record,
                    blueprint=blueprint,
                    artifact_refs=self._rework_artifact_refs(artifact_refs, current_attempt),
                    attempt_number=len(record.attempts) + 1,
                    rework_from=current_attempt,
                )

            if current_attempt.review_response is None:
                await self._publish_proposed_event_if_needed(
                    record=record,
                    blueprint=blueprint,
                    attempt=current_attempt,
                )
                await self._review_attempt(
                    record=record,
                    blueprint=blueprint,
                    attempt=current_attempt,
                )
            else:
                await self._publish_proposed_event_if_needed(
                    record=record,
                    blueprint=blueprint,
                    attempt=current_attempt,
                )
                await self._publish_reviewed_event_if_needed(
                    record=record,
                    blueprint=blueprint,
                    attempt=current_attempt,
                )

            if self._apply_review_verdict(record=record, attempt=current_attempt):
                continue
            return self._result_from_record(record)

    def _apply_review_verdict(
        self,
        *,
        record: FeaturePlanDeliberationRecord,
        attempt: FeaturePlanDeliberationAttempt,
    ) -> bool:
        if attempt.review_response is None:
            return True

        verdict = attempt.review_response.verdict
        if record.status in {
            "approved",
            "rejected",
            "challenge_required",
            "manual_review_required",
        }:
            return False

        if record.status == "reworking" and verdict == PlanningReviewVerdict.REQUEST_REWORK:
            return True

        if record.status != "feature_plan_review":
            return False

        if verdict == PlanningReviewVerdict.APPROVE:
            approved = approve_feature_plan_proposal(
                attempt.proposal,
                approval=FeaturePlanProposalApproval(
                    approved_by=[self._reviewer_actor],
                    approval_mode="autonomous_review",
                    approved_at=self._now(),
                ),
            )
            self._store.save(approved)
            self._emit_ready_intent_once(record=record, attempt=attempt)
            record.status = "approved"
            record.updated_at = self._now()
            self._store.save_deliberation(record)
            return False

        if verdict == PlanningReviewVerdict.REQUEST_REWORK:
            if record.rework_count + 1 > record.max_reworks:
                record.status = "rejected"
                record.failure_reason = "rework_limit_exceeded"
                record.updated_at = self._now()
                self._store.save_deliberation(record)
                return False
            record.rework_count += 1
            record.status = "reworking"
            record.updated_at = self._now()
            self._store.save_deliberation(record)
            return True

        if verdict == PlanningReviewVerdict.REJECT_AS_INVALID:
            record.status = "rejected"
            record.failure_reason = attempt.review_response.summary
            record.updated_at = self._now()
            self._store.save_deliberation(record)
            return False

        if verdict == PlanningReviewVerdict.CHALLENGE_REQUIRED:
            record.status = "challenge_required"
            record.failure_reason = attempt.review_response.summary
            record.updated_at = self._now()
            self._store.save_deliberation(record)
            return False

        record.status = "manual_review_required"
        record.failure_reason = attempt.review_response.summary
        record.updated_at = self._now()
        self._store.save_deliberation(record)
        return False

    def _load_or_create_record(
        self,
        *,
        planning_run_id: str,
        blueprint: ApprovedMissionBlueprint,
        feature_plan_id: str,
        artifact_refs: list[str],
    ) -> FeaturePlanDeliberationRecord:
        try:
            return self._store.load_deliberation(
                feature_plan_id,
                conversation_id=blueprint.conversation_id,
            )
        except KeyError:
            now = self._now()
            record = FeaturePlanDeliberationRecord(
                planning_run_id=planning_run_id,
                conversation_id=blueprint.conversation_id,
                feature_plan_id=feature_plan_id,
                source_blueprint_ref=blueprint.blueprint_ref,
                status="planning",
                max_reworks=self._max_reworks,
                rework_count=0,
                artifact_refs=list(dict.fromkeys(artifact_refs)),
                created_at=now,
                updated_at=now,
            )
            self._store.save_deliberation(record)
            return record

    async def _propose_attempt(
        self,
        *,
        record: FeaturePlanDeliberationRecord,
        blueprint: ApprovedMissionBlueprint,
        artifact_refs: list[str],
        attempt_number: int,
        rework_from: FeaturePlanDeliberationAttempt | None,
    ) -> FeaturePlanDeliberationAttempt:
        request = PlannerGodRequest(
            request_id=f"planner-request-{attempt_number}",
            correlation_id=f"feature-plan-correlation-{attempt_number}",
            conversation_id=blueprint.conversation_id,
            feature_plan_id=record.feature_plan_id,
            feature_plan_version=attempt_number,
            artifact_refs=artifact_refs,
            blueprint=blueprint,
            rework_context=self._build_rework_context(rework_from),
        )
        response = await self._planner.request_plan(request)
        self._validate_planner_response(response, request, blueprint)
        proposal = self._proposal_from_response(response, blueprint)
        self._store.save(proposal)
        attempt = FeaturePlanDeliberationAttempt(
            attempt_number=attempt_number,
            feature_plan_version=response.feature_plan_version,
            planner_request_id=request.request_id,
            planner_correlation_id=request.correlation_id,
            planner_response=response,
            proposal=proposal,
        )
        record.attempts.append(attempt)
        record.status = "feature_plan_review"
        record.updated_at = self._now()
        self._store.save_deliberation(record)
        await self._publish_proposed_event_if_needed(
            record=record,
            blueprint=blueprint,
            attempt=attempt,
        )
        return attempt

    async def _review_attempt(
        self,
        *,
        record: FeaturePlanDeliberationRecord,
        blueprint: ApprovedMissionBlueprint,
        attempt: FeaturePlanDeliberationAttempt,
    ) -> None:
        request = PlanningReviewRequest(
            request_id=f"review-request-{attempt.attempt_number}",
            correlation_id=f"feature-plan-review-correlation-{attempt.attempt_number}",
            conversation_id=blueprint.conversation_id,
            phase=PlanningReviewPhase.FEATURE_PLAN_REVIEW,
            artifact_id=record.feature_plan_id,
            artifact_version=attempt.feature_plan_version,
            artifact_refs=attempt.planner_response.artifact_refs,
            blueprint_refs=attempt.planner_response.blueprint_refs,
            feature_plan=attempt.planner_response,
        )
        response = await self._reviewer.request_review(request)
        self._validate_review_response(response, request)
        attempt.review_request_id = request.request_id
        attempt.review_correlation_id = request.correlation_id
        attempt.review_response = response
        record.updated_at = self._now()
        self._store.save_deliberation(record)
        await self._publish_reviewed_event_if_needed(
            record=record,
            blueprint=blueprint,
            attempt=attempt,
        )

    async def _publish_proposed_event_if_needed(
        self,
        *,
        record: FeaturePlanDeliberationRecord,
        blueprint: ApprovedMissionBlueprint,
        attempt: FeaturePlanDeliberationAttempt,
    ) -> None:
        if attempt.proposed_event_emitted:
            return
        response = attempt.planner_response
        await self._event_bus.publish(
            "feature_plan.proposed",
            {
                "planning_run_id": record.planning_run_id,
                "conversation_id": blueprint.conversation_id,
                "blueprint_ref": blueprint.blueprint_ref,
                "actor": self._planner_actor,
                "request_id": attempt.planner_request_id,
                "correlation_id": attempt.planner_correlation_id,
                "decision": "proposed",
                "evidence_refs": response.artifact_refs,
                "risk_level": "unknown",
                "feature_plan_id": response.feature_plan_id,
                "feature_plan_version": response.feature_plan_version,
            },
        )
        attempt.proposed_event_emitted = True
        record.audit_refs = self._append_unique(
            record.audit_refs,
            f"feature_plan.proposed:{attempt.attempt_number}",
        )
        record.updated_at = self._now()
        self._store.save_deliberation(record)

    async def _publish_reviewed_event_if_needed(
        self,
        *,
        record: FeaturePlanDeliberationRecord,
        blueprint: ApprovedMissionBlueprint,
        attempt: FeaturePlanDeliberationAttempt,
    ) -> None:
        if attempt.reviewed_event_emitted or attempt.review_response is None:
            return
        response = attempt.review_response
        await self._event_bus.publish(
            "feature_plan.reviewed",
            {
                "planning_run_id": record.planning_run_id,
                "conversation_id": blueprint.conversation_id,
                "blueprint_ref": blueprint.blueprint_ref,
                "actor": self._reviewer_actor,
                "request_id": str(attempt.review_request_id or ""),
                "correlation_id": str(attempt.review_correlation_id or ""),
                "decision": response.verdict.value,
                "evidence_refs": list(
                    dict.fromkeys(
                        attempt.planner_response.artifact_refs + response.artifact_refs
                    )
                ),
                "risk_level": "unknown",
                "feature_plan_id": response.artifact_id,
                "feature_plan_version": response.artifact_version,
            },
        )
        attempt.reviewed_event_emitted = True
        record.audit_refs = self._append_unique(
            record.audit_refs,
            f"feature_plan.reviewed:{attempt.attempt_number}",
        )
        record.updated_at = self._now()
        self._store.save_deliberation(record)

    def _emit_ready_intent_once(
        self,
        *,
        record: FeaturePlanDeliberationRecord,
        attempt: FeaturePlanDeliberationAttempt,
    ) -> None:
        if attempt.ready_intent_ref is not None:
            record.chat_card_refs = self._append_unique(
                record.chat_card_refs,
                attempt.ready_intent_ref,
            )
            return
        intent = self._card_emitter.emit_feature_plan_ready(
            conversation_id=record.conversation_id,
            planning_run_id=record.planning_run_id,
            feature_plan_id=record.feature_plan_id,
            feature_count=len(attempt.proposal.features),
            risk_level=None,
            created_at=self._now(),
            summary="Feature plan approved and ready for graph generation.",
        )
        attempt.ready_intent_ref = intent.intent_id
        record.chat_card_refs = self._append_unique(record.chat_card_refs, intent.intent_id)

    def _validate_planner_response(
        self,
        response: PlannerGodResponse,
        request: PlannerGodRequest,
        blueprint: ApprovedMissionBlueprint,
    ) -> None:
        if response.request_id != request.request_id:
            raise ValueError("request_id_mismatch")
        if response.correlation_id != request.correlation_id:
            raise ValueError("correlation_id_mismatch")
        if response.conversation_id != request.conversation_id:
            raise ValueError("conversation_id_mismatch")
        if response.feature_plan_id != request.feature_plan_id:
            raise ValueError("feature_plan_id_mismatch")
        if response.feature_plan_version != request.feature_plan_version:
            raise ValueError("feature_plan_version_mismatch")
        if response.source_blueprint_ref != blueprint.blueprint_ref:
            raise ValueError("source_blueprint_ref_mismatch")

    def _validate_review_response(
        self,
        response: PlanningReviewResponse,
        request: PlanningReviewRequest,
    ) -> None:
        if response.request_id != request.request_id:
            raise ValueError("request_id_mismatch")
        if response.correlation_id != request.correlation_id:
            raise ValueError("correlation_id_mismatch")
        if response.conversation_id != request.conversation_id:
            raise ValueError("conversation_id_mismatch")
        if response.phase != request.phase:
            raise ValueError("review_phase_mismatch")
        if response.artifact_id != request.artifact_id:
            raise ValueError("artifact_id_mismatch")
        if response.artifact_version != request.artifact_version:
            raise ValueError("artifact_version_mismatch")

    def _proposal_from_response(
        self,
        response: PlannerGodResponse,
        blueprint: ApprovedMissionBlueprint,
    ) -> FeaturePlanProposal:
        return FeaturePlanProposal(
            id=response.feature_plan_id,
            conversation_id=response.conversation_id,
            source_blueprint=blueprint,
            features=[
                FeaturePlanFeature(
                    feature_id=feature.feature_id,
                    title=feature.title,
                    goal=feature.goal,
                    acceptance_criteria=list(feature.acceptance_criteria),
                    dependencies=list(feature.dependencies),
                    graph_id=feature.graph_id,
                    blueprint_refs=list(feature.blueprint_refs),
                )
                for feature in response.features
            ],
        )

    def _build_rework_context(
        self,
        attempt: FeaturePlanDeliberationAttempt | None,
    ) -> PlannerReworkContext | None:
        if attempt is None or attempt.review_response is None:
            return None
        return PlannerReworkContext(
            previous_feature_plan=PlannerPreviousFeaturePlan(
                feature_plan_id=attempt.planner_response.feature_plan_id,
                feature_plan_version=attempt.planner_response.feature_plan_version,
                artifact_refs=list(attempt.planner_response.artifact_refs),
                blueprint_refs=list(attempt.planner_response.blueprint_refs),
                planning_rationale=attempt.planner_response.planning_rationale,
                features=[
                    feature.model_copy(deep=True)
                    for feature in attempt.planner_response.features
                ],
            ),
            review_summary=attempt.review_response.summary,
            expected_fix="Address the review findings and return a revised feature plan proposal.",
            review_findings=[finding.message for finding in attempt.review_response.findings],
            artifact_refs=list(
                dict.fromkeys(
                    attempt.planner_response.artifact_refs
                    + attempt.review_response.artifact_refs
                )
            ),
        )

    def _rework_artifact_refs(
        self,
        artifact_refs: list[str],
        attempt: FeaturePlanDeliberationAttempt,
    ) -> list[str]:
        if attempt.review_response is None:
            return artifact_refs
        return list(
            dict.fromkeys(
                artifact_refs
                + attempt.planner_response.artifact_refs
                + attempt.review_response.artifact_refs
            )
        )

    def _result_from_record(
        self,
        record: FeaturePlanDeliberationRecord,
    ) -> FeaturePlanDeliberationResult:
        ready_intent_ref = None
        if record.status == "approved" and record.attempts:
            ready_intent_ref = record.attempts[-1].ready_intent_ref
        return FeaturePlanDeliberationResult(
            outcome=record.status,
            rework_count=record.rework_count,
            feature_plan_id=record.feature_plan_id,
            feature_plan_version=(
                record.attempts[-1].feature_plan_version if record.attempts else None
            ),
            ready_intent_ref=ready_intent_ref,
        )

    def _append_unique(self, values: list[str], value: str) -> list[str]:
        if value in values:
            return values
        return [*values, value]
