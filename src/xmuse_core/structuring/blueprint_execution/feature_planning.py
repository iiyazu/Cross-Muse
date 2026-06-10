from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from xmuse_core.agents.planning_god_adapters import PlannerGodAdapter, ReviewGodAdapter
from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.chat.models import StructuredResolution
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.providers.models import ProviderId, TaskCapability
from xmuse_core.providers.policy import ProviderPolicyDecision, ProviderPolicyService
from xmuse_core.structuring.feature_plan_deliberation import (
    FeaturePlanDeliberationService,
    PlannerProtocol,
    ReviewerProtocol,
)
from xmuse_core.structuring.feature_plan_store import (
    FeaturePlanStore,
    read_approved_mission_blueprint,
)
from xmuse_core.structuring.models import ApprovedMissionBlueprint, PlanningEvent, PlanningRunStatus
from xmuse_core.structuring.planning_event_store import PlanningEventStore
from xmuse_core.structuring.planning_run_store import PlanningRunStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _event_ref(event_id: str) -> str:
    return f"planning_events.sqlite3#{event_id}"


def _feature_plan_ref(feature_plan_id: str) -> str:
    return f"feature_plans/{feature_plan_id}"


class BlueprintLoader(Protocol):
    def __call__(
        self,
        *,
        event: PlanningEvent,
        planning_run: Any,
    ) -> ApprovedMissionBlueprint | StructuredResolution: ...


class PlanningAdapterFactory(Protocol):
    def build_planner(self, *, decision: ProviderPolicyDecision) -> PlannerProtocol: ...

    def build_reviewer(self, *, decision: ProviderPolicyDecision) -> ReviewerProtocol: ...


@dataclass(frozen=True)
class FeaturePlanningResult:
    claimed_event_id: str
    planning_run_id: str
    feature_plan_id: str
    feature_plan_version: int | None
    outcome: str
    ready_intent_ref: str | None
    planner_provider_profile_ref: str
    reviewer_provider_profile_ref: str


class CodexPlanningAdapterFactory:
    def __init__(
        self,
        *,
        db_path: Path | str,
        session_layer: Any,
        worktree: Path | str,
        planner_participant_id: str = "planner_god",
        reviewer_participant_id: str = "review_god",
        timeout_s: float = 180.0,
    ) -> None:
        self._db_path = Path(db_path)
        self._session_layer = session_layer
        self._worktree = Path(worktree)
        self._planner_participant_id = planner_participant_id
        self._reviewer_participant_id = reviewer_participant_id
        self._timeout_s = timeout_s

    def build_planner(self, *, decision: ProviderPolicyDecision) -> PlannerProtocol:
        self._require_codex_profile(decision, task_type=TaskCapability.PLANNING)
        return PlannerGodAdapter(
            db_path=self._db_path,
            session_layer=self._session_layer,
            participant_id=self._planner_participant_id,
            model=decision.selected_model,
            worktree=self._worktree,
            timeout_s=self._timeout_s,
        )

    def build_reviewer(self, *, decision: ProviderPolicyDecision) -> ReviewerProtocol:
        self._require_codex_profile(decision, task_type=TaskCapability.REVIEW)
        return ReviewGodAdapter(
            db_path=self._db_path,
            session_layer=self._session_layer,
            participant_id=self._reviewer_participant_id,
            model=decision.selected_model,
            worktree=self._worktree,
            timeout_s=self._timeout_s,
        )

    def _require_codex_profile(
        self,
        decision: ProviderPolicyDecision,
        *,
        task_type: TaskCapability,
    ) -> None:
        if decision.provider_id is not ProviderId.CODEX:
            raise ValueError(
                "planning adapters currently require a codex provider profile"
            )
        if decision.task_type is not task_type:
            raise ValueError(
                f"provider policy task mismatch: expected {task_type.value}, "
                f"got {decision.task_type.value}"
            )


class FeaturePlanningService:
    def __init__(
        self,
        *,
        base_dir: Path | str,
        blueprint_loader: BlueprintLoader,
        policy_service: ProviderPolicyService | None = None,
        adapter_factory: PlanningAdapterFactory | None = None,
        event_store: PlanningEventStore | None = None,
        run_store: PlanningRunStore | None = None,
        card_emitter: ChatExecutionCardEmitter | None = None,
        event_bus: EventBus | None = None,
        feature_plans_root: Path | str | None = None,
        graph_sets_root: Path | str | None = None,
        lanes_path: Path | str | None = None,
        now: Callable[[], str] = _utc_now_iso,
        lease_ttl_seconds: int = 60,
        planner_actor: str = "planner_god",
        reviewer_actor: str = "review_god",
        db_path: Path | str | None = None,
        session_layer: Any | None = None,
        worktree: Path | str | None = None,
    ) -> None:
        del graph_sets_root, lanes_path
        self._base_dir = Path(base_dir)
        self._blueprint_loader = blueprint_loader
        self._policy_service = policy_service or ProviderPolicyService()
        self._event_store = event_store or PlanningEventStore(
            self._base_dir / "planning_events.sqlite3"
        )
        self._run_store = run_store or PlanningRunStore(self._base_dir / "planning_runs.sqlite3")
        self._card_emitter = card_emitter or ChatExecutionCardEmitter(self._base_dir)
        self._event_bus = event_bus or EventBus(
            audit_log_path=self._base_dir / "audit_events.json"
        )
        self._feature_plans_root = (
            Path(feature_plans_root)
            if feature_plans_root is not None
            else self._base_dir / "feature_plans"
        )
        self._feature_plan_store = FeaturePlanStore(self._feature_plans_root)
        self._now = now
        self._lease_ttl_seconds = lease_ttl_seconds
        self._planner_actor = planner_actor
        self._reviewer_actor = reviewer_actor
        self._adapter_factory = adapter_factory or self._build_default_adapter_factory(
            db_path=db_path,
            session_layer=session_layer,
            worktree=worktree,
        )

    async def tick(self, *, worker_id: str) -> FeaturePlanningResult | None:
        claimed = self._event_store.claim_next(
            worker_id=worker_id,
            lease_ttl=self._lease_ttl_seconds,
            event_type="planning.started",
        )
        if claimed is None:
            return None
        return await self._process_claimed_event(claimed)

    async def _process_claimed_event(
        self,
        event: PlanningEvent,
    ) -> FeaturePlanningResult:
        try:
            planning_run_id = _require_text(event.planning_run_id, "planning_run_id")
            planning_run = self._run_store.get(planning_run_id)
            blueprint = self._load_blueprint(event=event, planning_run=planning_run)
            feature_plan_id = planning_run.feature_plan_id or self._feature_plan_id_for(
                planning_run_id
            )

            planner_decision = self._policy_service.select_god(
                task_type=TaskCapability.PLANNING
            )
            reviewer_decision = self._policy_service.select_review()
            planner = self._adapter_factory.build_planner(decision=planner_decision)
            reviewer = self._adapter_factory.build_reviewer(decision=reviewer_decision)

            deliberation = FeaturePlanDeliberationService(
                feature_plans_root=self._feature_plans_root,
                card_emitter=self._card_emitter,
                event_bus=self._event_bus,
                planner=planner,
                reviewer=reviewer,
                now=self._now,
                planner_actor=self._planner_actor,
                reviewer_actor=self._reviewer_actor,
            )
            result = await deliberation.deliberate(
                planning_run_id=planning_run_id,
                blueprint=blueprint,
                feature_plan_id=feature_plan_id,
                artifact_refs=[_event_ref(event.event_id)],
            )
        except Exception as exc:
            return self._process_failed_event(event, exc)

        record = self._feature_plan_store.load_deliberation(
            feature_plan_id,
            conversation_id=planning_run.conversation_id,
        )
        if result.outcome == "approved" and result.feature_plan_version is not None:
            self._enqueue_feature_plan_ready(
                event=event,
                planning_run_id=planning_run_id,
                feature_plan_id=result.feature_plan_id,
                feature_plan_version=result.feature_plan_version,
            )
        elif result.outcome != "approved":
            self._enqueue_planning_failed(
                event=event,
                planning_run_id=planning_run_id,
                feature_plan_id=result.feature_plan_id,
                failure_reason=result.outcome,
            )
        updated_run = planning_run.model_copy(
            update={
                "status": self._status_for_outcome(result.outcome),
                "feature_plan_id": result.feature_plan_id,
                "feature_plan_version": result.feature_plan_version,
                "graph_set_id": None,
                "graph_set_version": None,
                "audit_refs": self._append_unique(
                    planning_run.audit_refs,
                    record.audit_refs,
                ),
                "chat_card_refs": self._append_unique(
                    planning_run.chat_card_refs,
                    record.chat_card_refs,
                ),
                "updated_at": self._now(),
            }
        )
        self._run_store.save(updated_run)
        self._event_store.ack(event.event_id)
        return FeaturePlanningResult(
            claimed_event_id=event.event_id,
            planning_run_id=planning_run_id,
            feature_plan_id=result.feature_plan_id,
            feature_plan_version=result.feature_plan_version,
            outcome=result.outcome,
            ready_intent_ref=result.ready_intent_ref,
            planner_provider_profile_ref=planner_decision.provider_profile_ref,
            reviewer_provider_profile_ref=reviewer_decision.provider_profile_ref,
        )

    def _process_failed_event(
        self,
        event: PlanningEvent,
        exc: Exception,
    ) -> FeaturePlanningResult:
        planning_run_id = _require_text(event.planning_run_id, "planning_run_id")
        planning_run = self._run_store.get(planning_run_id)
        feature_plan_id = planning_run.feature_plan_id or self._feature_plan_id_for(
            planning_run_id
        )
        failure_reason = str(exc) or exc.__class__.__name__
        self._enqueue_planning_failed(
            event=event,
            planning_run_id=planning_run_id,
            feature_plan_id=feature_plan_id,
            failure_reason=failure_reason,
        )
        self._run_store.save(
            planning_run.model_copy(
                update={
                    "status": PlanningRunStatus.FAILED,
                    "graph_set_id": None,
                    "graph_set_version": None,
                    "updated_at": self._now(),
                }
            )
        )
        self._event_store.ack(event.event_id)
        return FeaturePlanningResult(
            claimed_event_id=event.event_id,
            planning_run_id=planning_run_id,
            feature_plan_id=feature_plan_id,
            feature_plan_version=None,
            outcome="failed",
            ready_intent_ref=None,
            planner_provider_profile_ref="unavailable",
            reviewer_provider_profile_ref="unavailable",
        )

    def _enqueue_feature_plan_ready(
        self,
        *,
        event: PlanningEvent,
        planning_run_id: str,
        feature_plan_id: str,
        feature_plan_version: int,
    ) -> PlanningEvent:
        timestamp = self._now()
        return self._event_store.enqueue(
            PlanningEvent(
                event_id=f"pevt_{planning_run_id}_feature_plan_ready",
                event_type="feature_plan.ready",
                planning_run_id=planning_run_id,
                conversation_id=event.conversation_id,
                blueprint_ref=event.blueprint_ref,
                dedupe_key=event.dedupe_key,
                idempotency_key=f"feature_plan.ready:{feature_plan_id}:{feature_plan_version}",
                payload={
                    "source_event_id": event.event_id,
                    "planning_run_id": planning_run_id,
                    "feature_plan_id": feature_plan_id,
                    "feature_plan_version": feature_plan_version,
                    "outcome": "approved",
                    "artifact_refs": [
                        _event_ref(event.event_id),
                        _feature_plan_ref(feature_plan_id),
                    ],
                    "source_refs": [_event_ref(event.event_id)],
                },
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

    def _enqueue_planning_failed(
        self,
        *,
        event: PlanningEvent,
        planning_run_id: str,
        feature_plan_id: str,
        failure_reason: str,
    ) -> PlanningEvent:
        timestamp = self._now()
        return self._event_store.enqueue(
            PlanningEvent(
                event_id=f"pevt_{planning_run_id}_planning_failed",
                event_type="planning.failed",
                planning_run_id=planning_run_id,
                conversation_id=event.conversation_id,
                blueprint_ref=event.blueprint_ref,
                dedupe_key=event.dedupe_key,
                idempotency_key=f"planning.failed:{planning_run_id}:{event.event_id}",
                payload={
                    "source_event_id": event.event_id,
                    "planning_run_id": planning_run_id,
                    "feature_plan_id": feature_plan_id,
                    "failure_reason": failure_reason,
                    "artifact_refs": [_event_ref(event.event_id)],
                    "source_refs": [_event_ref(event.event_id)],
                },
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

    def _build_default_adapter_factory(
        self,
        *,
        db_path: Path | str | None,
        session_layer: Any | None,
        worktree: Path | str | None,
    ) -> PlanningAdapterFactory:
        if session_layer is None:
            raise ValueError(
                "session_layer is required when adapter_factory is not provided"
            )
        return CodexPlanningAdapterFactory(
            db_path=db_path or self._base_dir / "chat.db",
            session_layer=session_layer,
            worktree=worktree or self._base_dir,
        )

    def _load_blueprint(
        self,
        *,
        event: PlanningEvent,
        planning_run: Any,
    ) -> ApprovedMissionBlueprint:
        loaded = self._blueprint_loader(event=event, planning_run=planning_run)
        if isinstance(loaded, StructuredResolution):
            return read_approved_mission_blueprint(loaded)
        return loaded

    def _feature_plan_id_for(self, planning_run_id: str) -> str:
        return f"{planning_run_id}-feature-plan"

    def _status_for_outcome(self, outcome: str) -> PlanningRunStatus:
        if outcome == "approved":
            return PlanningRunStatus.FEATURE_PLAN_REVIEW
        if outcome == "challenge_required":
            return PlanningRunStatus.CHALLENGE_REVIEW
        if outcome == "manual_review_required":
            return PlanningRunStatus.WAITING_MANUAL_REVIEW
        if outcome == "rejected":
            return PlanningRunStatus.FAILED
        return PlanningRunStatus.REWORKING

    def _append_unique(
        self,
        existing: list[str],
        values: list[str],
    ) -> list[str]:
        merged = list(existing)
        for value in values:
            if value not in merged:
                merged.append(value)
        return merged


__all__ = [
    "BlueprintLoader",
    "CodexPlanningAdapterFactory",
    "FeaturePlanningResult",
    "FeaturePlanningService",
    "PlanningAdapterFactory",
]
