from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xmuse_core.structuring.lane_planner_v2 import (
    LanePlannerV2Input,
    LanePlannerV2LaneInput,
    build_lane_graph_v2,
)
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
)
from xmuse_core.structuring.models import LaneGraph, LaneNode


class LaneDependencyType(StrEnum):
    HARD_DEP = "hard_dep"
    SOFT_DEP = "soft_dep"
    REVIEW_DEP = "review_dep"
    ARTIFACT_DEP = "artifact_dep"


class LaneExecutionStatus(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    APPROVED = "approved"
    FAILED = "failed"
    BLOCKED = "blocked"


TERMINAL_APPROVED_STATUSES = {LaneExecutionStatus.APPROVED}
TERMINAL_FAILED_STATUSES = {LaneExecutionStatus.FAILED, LaneExecutionStatus.BLOCKED}
BlueprintProofLevel = Literal["contract_proof", "opt_in_live_proof", "manual_gap"]


class BlueprintSourceEventLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    event_type: str
    participant_id: str
    god_id: str
    proof_level: BlueprintProofLevel
    source_authority: str
    provider_response_artifact_ref: str | None = None
    binding_revision: str | None = None
    account_ref: str | None = None
    cli_command: str | None = None
    model: str | None = None
    variant: str | None = None
    target_participant_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)

    @field_validator(
        "event_id",
        "event_type",
        "participant_id",
        "god_id",
        "source_authority",
    )
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "provider_response_artifact_ref",
        "binding_revision",
        "account_ref",
        "cli_command",
        "model",
        "variant",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("target_participant_ids", "source_refs", "forbidden_claims")
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class BlueprintFeatureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    title: str
    goal: str
    acceptance_criteria: list[str]
    blueprint_refs: list[str]
    depends_on_features: list[str] = Field(default_factory=list)
    expected_touched_areas: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)

    @field_validator(
        "feature_id",
        "title",
        "goal",
    )
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "acceptance_criteria",
        "blueprint_refs",
        "depends_on_features",
        "expected_touched_areas",
        "memory_refs",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class LaneRuntimeBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = 3
    max_consecutive_same_failure: int = 2
    max_runtime_seconds: int | None = None
    retry_backoff_seconds: int = 0
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("max_attempts", "max_consecutive_same_failure")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("value must be >= 1")
        return value

    @field_validator("max_runtime_seconds")
    @classmethod
    def _validate_optional_positive_int(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or value < 1:
            raise ValueError("max_runtime_seconds must be >= 1")
        return value

    @field_validator("retry_backoff_seconds")
    @classmethod
    def _validate_non_negative_int(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")
        return value

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class BlueprintLaneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    feature_id: str
    title: str
    prompt: str
    acceptance_criteria: list[str]
    blueprint_refs: list[str]
    dependency_edges: list[LaneDependencyEdge] = Field(default_factory=list)
    expected_touched_areas: list[str] = Field(default_factory=list)
    gate_profile: str | None = None
    gate_profiles: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    owner: str = "codex"
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    allowed_files: list[str] = Field(default_factory=list)
    rollback_constraints: list[str] = Field(default_factory=list)
    review_profile: str = "standard"
    budget: LaneRuntimeBudget = Field(default_factory=LaneRuntimeBudget)

    @field_validator("lane_id", "feature_id", "title", "prompt", "owner", "review_profile")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "acceptance_criteria",
        "blueprint_refs",
        "expected_touched_areas",
        "gate_profiles",
        "memory_refs",
        "inputs",
        "outputs",
        "required_checks",
        "allowed_files",
        "rollback_constraints",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]

    @field_validator("gate_profile")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class LaneDependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_lane_id: str
    target_lane_id: str
    edge_type: LaneDependencyType
    rationale: str
    source_refs: list[str] = Field(default_factory=list)
    dispatch_blocking: bool = True

    @field_validator("source_lane_id", "target_lane_id", "rationale")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class PatchForwardLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    failed_lane_id: str
    patch_lane_id: str
    verdict_ref: str
    evidence_refs: list[str] = Field(default_factory=list)


class LaneRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    feature_id: str
    owner: str
    inputs: list[str]
    outputs: list[str]
    dependency_refs: list[str] = Field(default_factory=list)
    required_checks: list[str]
    allowed_files: list[str]
    rollback_constraints: list[str]
    review_profile: str
    memory_refs: list[str] = Field(default_factory=list)
    budget: LaneRuntimeBudget = Field(default_factory=LaneRuntimeBudget)
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("lane_id", "feature_id", "owner", "review_profile")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "inputs",
        "outputs",
        "dependency_refs",
        "required_checks",
        "allowed_files",
        "rollback_constraints",
        "memory_refs",
        "source_refs",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class BlueprintLaneDagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str
    resolution_id: str
    graph_version: int = 1
    blueprint: MissionBlueprintV1
    blueprint_proof_level: BlueprintProofLevel = "contract_proof"
    source_event_lineage: list[BlueprintSourceEventLineage] = Field(
        default_factory=list
    )
    features: list[BlueprintFeatureSpec]
    lanes: list[BlueprintLaneSpec]
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("graph_id", "resolution_id")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("graph_version")
    @classmethod
    def _validate_graph_version(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("graph_version must be >= 1")
        return value

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class BlueprintLaneDagPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str
    blueprint_ref: str
    blueprint_proof_level: BlueprintProofLevel = "contract_proof"
    source_event_lineage: list[BlueprintSourceEventLineage] = Field(
        default_factory=list
    )
    feature_ids: list[str]
    lane_graph: LaneGraph
    dependency_edges: list[LaneDependencyEdge]
    lane_contracts: list[LaneRuntimeContract] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    patch_forward_links: list[PatchForwardLink] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class LaneRecoveryDecisionType(StrEnum):
    RETRY = "retry"
    SUSPENDED = "suspended"
    MANUAL_GAP = "manual_gap"
    REFACTOR_REQUIRED = "refactor_required"


class LaneFailureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    attempt: int
    failure_class: str
    reason: str
    source_refs: list[str]
    occurred_at_utc: str | None = None

    @field_validator("lane_id", "failure_class", "reason", "occurred_at_utc")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("attempt")
    @classmethod
    def _validate_attempt(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("attempt must be >= 1")
        return value

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, values: list[str]) -> list[str]:
        return _require_non_empty_list(values, "source_refs")


class LaneRecoveryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    decision: LaneRecoveryDecisionType
    retry_allowed: bool
    failure_class: str | None = None
    attempt: int | None = None
    suspend_reason: str | None = None
    refactor_required_reason: str | None = None
    next_action: str
    source_refs: list[str] = Field(default_factory=list)

    @field_validator(
        "lane_id",
        "failure_class",
        "suspend_reason",
        "refactor_required_reason",
        "next_action",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("attempt")
    @classmethod
    def _validate_optional_attempt(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or value < 1:
            raise ValueError("attempt must be >= 1")
        return value

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class LaneDispatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    ready: bool
    blockers: list[str] = Field(default_factory=list)


class BlueprintLaneDagService:
    def build_plan(self, request: BlueprintLaneDagRequest) -> BlueprintLaneDagPlan:
        _validate_blueprint_is_frozen(request.blueprint)
        _validate_feature_ids(request.features)
        _validate_lane_feature_refs(request.features, request.lanes)
        dependency_edges = _collect_dependency_edges(request)
        lane_graph = build_lane_graph_v2(
            LanePlannerV2Input(
                graph_id=request.graph_id,
                conversation_id=request.blueprint.conversation_id,
                resolution_id=request.resolution_id,
                version=request.graph_version,
                available_blueprint_refs=_available_blueprint_refs(request.blueprint),
                lanes=[
                    _lane_planner_input(lane, dependency_edges)
                    for lane in request.lanes
                ],
                source_refs=[
                    *request.source_refs,
                    *request.blueprint.source_refs,
                ],
            )
        )
        return BlueprintLaneDagPlan(
            blueprint_id=request.blueprint.blueprint_id,
            blueprint_ref=_blueprint_ref(request.blueprint),
            blueprint_proof_level=request.blueprint_proof_level,
            source_event_lineage=list(request.source_event_lineage),
            feature_ids=[feature.feature_id for feature in request.features],
            lane_graph=lane_graph,
            dependency_edges=dependency_edges,
            lane_contracts=_lane_runtime_contracts(request, dependency_edges),
            memory_refs=_collect_memory_refs(request),
            source_refs=_dedupe([*request.source_refs, *request.blueprint.source_refs]),
        )

    def evaluate_dispatch(
        self,
        plan: BlueprintLaneDagPlan,
        *,
        lane_statuses: dict[str, LaneExecutionStatus | str],
    ) -> list[LaneDispatchDecision]:
        normalized_statuses = {
            lane_id: _coerce_lane_status(status)
            for lane_id, status in lane_statuses.items()
        }
        decisions: list[LaneDispatchDecision] = []
        for lane in plan.lane_graph.lanes:
            blockers = _dispatch_blockers(
                lane,
                dependency_edges=plan.dependency_edges,
                lane_statuses=normalized_statuses,
            )
            decisions.append(
                LaneDispatchDecision(
                    lane_id=lane.feature_id,
                    ready=not blockers,
                    blockers=blockers,
                )
            )
        return decisions

    def append_patch_forward_lane(
        self,
        plan: BlueprintLaneDagPlan,
        *,
        failed_lane_id: str,
        patch_lane_id: str,
        prompt: str,
        acceptance_criteria: list[str],
        verdict_ref: str,
        evidence_refs: list[str],
    ) -> BlueprintLaneDagPlan:
        failed_lane = _find_lane(plan.lane_graph, failed_lane_id)
        if _find_lane_or_none(plan.lane_graph, patch_lane_id) is not None:
            raise ValueError(f"patch lane already exists: {patch_lane_id}")
        patch_lane = LaneNode(
            feature_id=patch_lane_id,
            title=f"Patch forward for {failed_lane_id}",
            prompt=_require_non_empty(prompt),
            task_type="patch_forward",
            priority=failed_lane.priority,
            capabilities=list(failed_lane.capabilities),
            depends_on=[],
            gate_profile=failed_lane.gate_profile,
            gate_profiles=list(failed_lane.gate_profiles),
            source_lane_id=failed_lane_id,
            feature_group=failed_lane.feature_group,
            blueprint_refs=list(failed_lane.blueprint_refs),
            acceptance_criteria=[_require_non_empty(item) for item in acceptance_criteria],
            expected_touched_areas=list(failed_lane.expected_touched_areas),
        )
        edge = LaneDependencyEdge(
            source_lane_id=failed_lane_id,
            target_lane_id=patch_lane_id,
            edge_type=LaneDependencyType.ARTIFACT_DEP,
            rationale="patch-forward lane inherits evidence from failed lane",
            source_refs=evidence_refs,
            dispatch_blocking=False,
        )
        link = PatchForwardLink(
            failed_lane_id=failed_lane_id,
            patch_lane_id=patch_lane_id,
            verdict_ref=_require_non_empty(verdict_ref),
            evidence_refs=[_require_non_empty(item) for item in evidence_refs],
        )
        return plan.model_copy(
            update={
                "lane_graph": plan.lane_graph.model_copy(
                    update={"lanes": [*plan.lane_graph.lanes, patch_lane]}
                ),
                "dependency_edges": [*plan.dependency_edges, edge],
                "lane_contracts": [
                    *plan.lane_contracts,
                    _patch_forward_runtime_contract(
                        plan,
                        failed_lane_id=failed_lane_id,
                        patch_lane_id=patch_lane_id,
                        evidence_refs=evidence_refs,
                    ),
                ],
                "patch_forward_links": [*plan.patch_forward_links, link],
            }
        )


def evaluate_lane_recovery(
    *,
    lane_id: str,
    budget: LaneRuntimeBudget,
    failures: list[LaneFailureEvidence],
    runtime_seconds: int | None = None,
) -> LaneRecoveryDecision:
    lane_id = _require_non_empty(lane_id)
    lane_failures = [failure for failure in failures if failure.lane_id == lane_id]
    if not lane_failures:
        return LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.MANUAL_GAP,
            retry_allowed=False,
            suspend_reason="missing_failure_evidence",
            next_action="record lane failure evidence before retrying",
            source_refs=list(budget.source_refs),
        )
    latest_failure = max(lane_failures, key=lambda failure: failure.attempt)
    source_refs = _dedupe(
        [
            *budget.source_refs,
            *[
                source_ref
                for failure in lane_failures
                for source_ref in failure.source_refs
            ],
        ]
    )
    repeated_class, repeated_count = Counter(
        failure.failure_class for failure in lane_failures
    ).most_common(1)[0]
    if repeated_count >= budget.max_consecutive_same_failure:
        return LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.REFACTOR_REQUIRED,
            retry_allowed=False,
            failure_class=repeated_class,
            attempt=latest_failure.attempt,
            refactor_required_reason=(
                f"failure_class {repeated_class} repeated {repeated_count} times"
            ),
            next_action="refactor or replace the failing lane boundary before retrying",
            source_refs=source_refs,
        )
    if latest_failure.attempt >= budget.max_attempts:
        return LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.SUSPENDED,
            retry_allowed=False,
            failure_class=latest_failure.failure_class,
            attempt=latest_failure.attempt,
            suspend_reason="retry_budget_exhausted",
            next_action="suspend lane and request operator review",
            source_refs=source_refs,
        )
    if (
        runtime_seconds is not None
        and budget.max_runtime_seconds is not None
        and runtime_seconds >= budget.max_runtime_seconds
    ):
        return LaneRecoveryDecision(
            lane_id=lane_id,
            decision=LaneRecoveryDecisionType.SUSPENDED,
            retry_allowed=False,
            failure_class=latest_failure.failure_class,
            attempt=latest_failure.attempt,
            suspend_reason="runtime_budget_exhausted",
            next_action="suspend lane and request operator review",
            source_refs=source_refs,
        )
    return LaneRecoveryDecision(
        lane_id=lane_id,
        decision=LaneRecoveryDecisionType.RETRY,
        retry_allowed=True,
        failure_class=latest_failure.failure_class,
        attempt=latest_failure.attempt,
        next_action="retry lane within declared budget",
        source_refs=source_refs,
    )


def _validate_blueprint_is_frozen(blueprint: MissionBlueprintV1) -> None:
    if blueprint.status not in {
        MissionBlueprintStatus.FROZEN,
        MissionBlueprintStatus.APPROVED,
    }:
        raise ValueError("blueprint must be frozen or approved before laneDAG planning")


def _validate_feature_ids(features: list[BlueprintFeatureSpec]) -> None:
    if not features:
        raise ValueError("features must contain at least one feature")
    seen: set[str] = set()
    for feature in features:
        if feature.feature_id in seen:
            raise ValueError(f"duplicate feature_id: {feature.feature_id}")
        seen.add(feature.feature_id)


def _validate_lane_feature_refs(
    features: list[BlueprintFeatureSpec],
    lanes: list[BlueprintLaneSpec],
) -> None:
    feature_ids = {feature.feature_id for feature in features}
    if not lanes:
        raise ValueError("lanes must contain at least one lane")
    for lane in lanes:
        if lane.feature_id not in feature_ids:
            raise ValueError(f"lane {lane.lane_id} references unknown feature {lane.feature_id}")


def _collect_dependency_edges(request: BlueprintLaneDagRequest) -> list[LaneDependencyEdge]:
    edges: list[LaneDependencyEdge] = []
    lane_ids = {lane.lane_id for lane in request.lanes}
    first_lane_by_feature = _first_lane_by_feature(request.lanes)
    for feature in request.features:
        target_lane_id = first_lane_by_feature.get(feature.feature_id)
        if target_lane_id is None:
            continue
        for dependency_feature_id in feature.depends_on_features:
            source_lane_id = first_lane_by_feature.get(dependency_feature_id)
            if source_lane_id is None:
                raise ValueError(
                    f"feature {feature.feature_id} depends on unknown feature "
                    f"{dependency_feature_id}"
                )
            edges.append(
                LaneDependencyEdge(
                    source_lane_id=source_lane_id,
                    target_lane_id=target_lane_id,
                    edge_type=LaneDependencyType.HARD_DEP,
                    rationale=f"feature {feature.feature_id} depends on {dependency_feature_id}",
                    source_refs=feature.blueprint_refs,
                )
            )
    for lane in request.lanes:
        for edge in lane.dependency_edges:
            if edge.source_lane_id not in lane_ids:
                raise ValueError(
                    f"lane {lane.lane_id} depends on unknown lane {edge.source_lane_id}"
                )
            if edge.target_lane_id != lane.lane_id:
                raise ValueError(
                    f"dependency edge target {edge.target_lane_id} does not match "
                    f"lane {lane.lane_id}"
                )
            edges.append(edge)
    return edges


def _first_lane_by_feature(lanes: list[BlueprintLaneSpec]) -> dict[str, str]:
    first: dict[str, str] = {}
    for lane in lanes:
        first.setdefault(lane.feature_id, lane.lane_id)
    return first


def _lane_planner_input(
    lane: BlueprintLaneSpec,
    dependency_edges: list[LaneDependencyEdge],
) -> LanePlannerV2LaneInput:
    depends_on = _dedupe(
        [
            edge.source_lane_id
            for edge in dependency_edges
            if edge.target_lane_id == lane.lane_id and edge.dispatch_blocking
        ]
    )
    return LanePlannerV2LaneInput(
        lane_id=lane.lane_id,
        title=lane.title,
        prompt=lane.prompt,
        acceptance_criteria=lane.acceptance_criteria,
        depends_on=depends_on,
        blueprint_refs=lane.blueprint_refs,
        expected_touched_areas=lane.expected_touched_areas,
        gate_profile=lane.gate_profile,
        gate_profiles=lane.gate_profiles,
    )


def _dispatch_blockers(
    lane: LaneNode,
    *,
    dependency_edges: list[LaneDependencyEdge],
    lane_statuses: dict[str, LaneExecutionStatus],
) -> list[str]:
    blockers: list[str] = []
    if lane_statuses.get(lane.feature_id) in TERMINAL_APPROVED_STATUSES:
        return blockers
    for edge in dependency_edges:
        if edge.target_lane_id != lane.feature_id or not edge.dispatch_blocking:
            continue
        source_status = lane_statuses.get(edge.source_lane_id, LaneExecutionStatus.PLANNED)
        if source_status in TERMINAL_APPROVED_STATUSES:
            continue
        if source_status in TERMINAL_FAILED_STATUSES:
            blockers.append(f"{edge.source_lane_id} is {source_status.value}")
        else:
            blockers.append(f"{edge.source_lane_id} is not approved")
    return blockers


def _coerce_lane_status(status: LaneExecutionStatus | str) -> LaneExecutionStatus:
    if isinstance(status, LaneExecutionStatus):
        return status
    return LaneExecutionStatus(status)


def _collect_memory_refs(request: BlueprintLaneDagRequest) -> list[str]:
    refs: list[str] = []
    for feature in request.features:
        refs.extend(feature.memory_refs)
    for lane in request.lanes:
        refs.extend(lane.memory_refs)
    return _dedupe(refs)


def _lane_runtime_contracts(
    request: BlueprintLaneDagRequest,
    dependency_edges: list[LaneDependencyEdge],
) -> list[LaneRuntimeContract]:
    features_by_id = {feature.feature_id: feature for feature in request.features}
    return [
        LaneRuntimeContract(
            lane_id=lane.lane_id,
            feature_id=lane.feature_id,
            owner=lane.owner,
            inputs=lane.inputs or lane.blueprint_refs,
            outputs=lane.outputs or lane.acceptance_criteria,
            dependency_refs=_dependency_refs_for_lane(lane, dependency_edges),
            required_checks=_required_checks(lane),
            allowed_files=lane.allowed_files or lane.expected_touched_areas,
            rollback_constraints=lane.rollback_constraints,
            review_profile=lane.review_profile,
            memory_refs=_memory_refs_for_lane(lane, features_by_id),
            budget=lane.budget,
            source_refs=_dedupe([*request.source_refs, *lane.blueprint_refs]),
        )
        for lane in request.lanes
    ]


def _patch_forward_runtime_contract(
    plan: BlueprintLaneDagPlan,
    *,
    failed_lane_id: str,
    patch_lane_id: str,
    evidence_refs: list[str],
) -> LaneRuntimeContract:
    failed_contract = _find_lane_contract_or_none(plan, failed_lane_id)
    if failed_contract is None:
        return LaneRuntimeContract(
            lane_id=patch_lane_id,
            feature_id=patch_lane_id,
            owner="codex",
            inputs=[f"lane:{failed_lane_id}", *evidence_refs],
            outputs=[f"artifact://{patch_lane_id}/patch-forward-evidence.json"],
            dependency_refs=[f"lane:{failed_lane_id}"],
            required_checks=["focused-pytest"],
            allowed_files=[],
            rollback_constraints=["preserve failed lane evidence"],
            review_profile="patch-forward-review",
            source_refs=evidence_refs,
        )
    return failed_contract.model_copy(
        update={
            "lane_id": patch_lane_id,
            "inputs": _dedupe(
                [*failed_contract.inputs, f"lane:{failed_lane_id}", *evidence_refs]
            ),
            "outputs": [f"artifact://{patch_lane_id}/patch-forward-evidence.json"],
            "dependency_refs": _dedupe(
                [*failed_contract.dependency_refs, f"lane:{failed_lane_id}"]
            ),
            "rollback_constraints": _dedupe(
                [
                    *failed_contract.rollback_constraints,
                    "preserve failed lane evidence",
                ]
            ),
            "source_refs": _dedupe([*failed_contract.source_refs, *evidence_refs]),
        }
    )


def _find_lane_contract_or_none(
    plan: BlueprintLaneDagPlan,
    lane_id: str,
) -> LaneRuntimeContract | None:
    for contract in plan.lane_contracts:
        if contract.lane_id == lane_id:
            return contract
    return None


def _dependency_refs_for_lane(
    lane: BlueprintLaneSpec,
    dependency_edges: list[LaneDependencyEdge],
) -> list[str]:
    return _dedupe(
        [
            f"lane:{edge.source_lane_id}"
            for edge in dependency_edges
            if edge.target_lane_id == lane.lane_id
        ]
    )


def _required_checks(lane: BlueprintLaneSpec) -> list[str]:
    if lane.required_checks:
        return lane.required_checks
    checks: list[str] = []
    if lane.gate_profile:
        checks.append(lane.gate_profile)
    checks.extend(lane.gate_profiles)
    return _dedupe(checks or ["focused-pytest"])


def _memory_refs_for_lane(
    lane: BlueprintLaneSpec,
    features_by_id: dict[str, BlueprintFeatureSpec],
) -> list[str]:
    feature = features_by_id.get(lane.feature_id)
    feature_memory_refs = feature.memory_refs if feature is not None else []
    return _dedupe([*feature_memory_refs, *lane.memory_refs])


def _available_blueprint_refs(blueprint: MissionBlueprintV1) -> list[str]:
    return _dedupe([_blueprint_ref(blueprint), *blueprint.source_refs])


def _blueprint_ref(blueprint: MissionBlueprintV1) -> str:
    return f"blueprint:{blueprint.blueprint_id}:{blueprint.revision}"


def _find_lane(graph: LaneGraph, lane_id: str) -> LaneNode:
    lane = _find_lane_or_none(graph, lane_id)
    if lane is None:
        raise ValueError(f"unknown lane: {lane_id}")
    return lane


def _find_lane_or_none(graph: LaneGraph, lane_id: str) -> LaneNode | None:
    for lane in graph.lanes:
        if lane.feature_id == lane_id:
            return lane
    return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _require_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must be non-empty")
    return value


def _require_non_empty_list(values: list[str], field_name: str) -> list[str]:
    cleaned = [_require_non_empty(value) for value in values]
    if not cleaned:
        raise ValueError(f"{field_name} must contain at least one item")
    return cleaned
