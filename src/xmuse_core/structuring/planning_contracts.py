from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xmuse_core.structuring.models import (
    ApprovedMissionBlueprint,
    GraphSetDecompositionReviewPacket,
)


def _require_text(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_text_list(
    values: list[str],
    field_name: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    cleaned = [_require_text(str(value), field_name) for value in values]
    if not allow_empty and not cleaned:
        raise ValueError(f"{field_name} must contain at least one item")
    return cleaned


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_lane_dependencies(lanes: list[ArchitectLaneProposal]) -> None:
    lane_ids = [lane.lane_id for lane in lanes]
    duplicate_lane_ids = _find_duplicates(lane_ids)
    if duplicate_lane_ids:
        raise ValueError("duplicate lane_id: " + ", ".join(duplicate_lane_ids))

    local_lane_ids = [lane.local_lane_id for lane in lanes]
    duplicate_local_lane_ids = _find_duplicates(local_lane_ids)
    if duplicate_local_lane_ids:
        raise ValueError(
            "duplicate local_lane_id: " + ", ".join(duplicate_local_lane_ids)
        )

    known_lane_ids = set(lane_ids)
    missing_dependencies = sorted(
        {
            dependency
            for lane in lanes
            for dependency in lane.dependencies
            if dependency not in known_lane_ids
        }
    )
    if missing_dependencies:
        raise ValueError(
            "unknown lane dependency: " + ", ".join(missing_dependencies)
        )

    adjacency: dict[str, list[str]] = {lane_id: [] for lane_id in lane_ids}
    for lane in lanes:
        if lane.lane_id in lane.dependencies:
            raise ValueError(f"lane {lane.lane_id} must not depend on itself")
        for dependency in lane.dependencies:
            adjacency[dependency].append(lane.lane_id)
    for dependents in adjacency.values():
        dependents.sort()

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    stack_positions: dict[str, int] = {}

    def visit(lane_id: str) -> None:
        visiting.add(lane_id)
        stack_positions[lane_id] = len(stack)
        stack.append(lane_id)

        for dependent_id in adjacency[lane_id]:
            if dependent_id in visited:
                continue
            if dependent_id in visiting:
                cycle = stack[stack_positions[dependent_id] :] + [dependent_id]
                raise ValueError("dependency cycle detected: " + " -> ".join(cycle))
            visit(dependent_id)

        visiting.remove(lane_id)
        visited.add(lane_id)
        stack.pop()
        stack_positions.pop(lane_id, None)

    for lane_id in sorted(known_lane_ids):
        if lane_id not in visited:
            visit(lane_id)


class PlannerFeatureProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    title: str
    goal: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    graph_id: str
    blueprint_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    planning_rationale: str
    dependency_rationale: str

    @field_validator(
        "feature_id",
        "title",
        "goal",
        "graph_id",
        "planning_rationale",
        "dependency_rationale",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("acceptance_criteria")
    @classmethod
    def _validate_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "acceptance_criteria")

    @field_validator("dependencies", "blueprint_refs", "artifact_refs", "risk_notes")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(
            value,
            info.field_name,
            allow_empty=info.field_name in {"dependencies", "artifact_refs", "risk_notes"},
        )

    @model_validator(mode="after")
    def _reject_self_dependency(self) -> PlannerFeatureProposal:
        if self.feature_id in self.dependencies:
            raise ValueError("dependencies must not include the feature_id itself")
        return self


class PlannerPreviousFeaturePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_plan_id: str
    feature_plan_version: int
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    planning_rationale: str
    features: list[PlannerFeatureProposal] = Field(default_factory=list)

    @field_validator(
        "feature_plan_id",
        "planning_rationale",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("feature_plan_version")
    @classmethod
    def _validate_feature_plan_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("feature_plan_version must be >= 1")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def _validate_artifact_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "artifact_refs", allow_empty=True)

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "blueprint_refs")

    @model_validator(mode="after")
    def _validate_features(self) -> PlannerPreviousFeaturePlan:
        if not self.features:
            raise ValueError("features must contain at least one item")
        return self


class PlannerReworkContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_feature_plan: PlannerPreviousFeaturePlan
    review_summary: str
    expected_fix: str
    review_findings: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)

    @field_validator("review_summary", "expected_fix")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("review_findings", "artifact_refs")
    @classmethod
    def _validate_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)


class PlannerGodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    conversation_id: str
    feature_plan_id: str
    feature_plan_version: int
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint: ApprovedMissionBlueprint
    rework_context: PlannerReworkContext | None = None

    @field_validator("request_id", "correlation_id", "conversation_id", "feature_plan_id")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("artifact_refs")
    @classmethod
    def _validate_artifact_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "artifact_refs", allow_empty=True)

    @field_validator("feature_plan_version")
    @classmethod
    def _validate_feature_plan_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("feature_plan_version must be >= 1")
        return value

    @model_validator(mode="after")
    def _validate_conversation(self) -> PlannerGodRequest:
        if self.conversation_id != self.blueprint.conversation_id:
            raise ValueError("conversation_id must match blueprint conversation_id")
        return self


class PlannerGodResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    conversation_id: str
    feature_plan_id: str
    feature_plan_version: int
    source_blueprint_ref: str
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    planning_rationale: str
    features: list[PlannerFeatureProposal] = Field(default_factory=list)

    @field_validator(
        "request_id",
        "correlation_id",
        "conversation_id",
        "feature_plan_id",
        "source_blueprint_ref",
        "planning_rationale",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("feature_plan_version")
    @classmethod
    def _validate_feature_plan_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("feature_plan_version must be >= 1")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def _validate_artifact_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "artifact_refs", allow_empty=True)

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "blueprint_refs")

    @model_validator(mode="after")
    def _validate_features(self) -> PlannerGodResponse:
        if not self.features:
            raise ValueError("features must contain at least one item")
        if self.source_blueprint_ref not in self.blueprint_refs:
            raise ValueError("blueprint_refs must include source_blueprint_ref")
        return self


class ArchitectLaneProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    local_lane_id: str
    feature_id: str
    title: str
    prompt: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    expected_touched_areas: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    feature_refs: list[str] = Field(default_factory=list)
    dependency_rationale: str

    @field_validator(
        "lane_id",
        "local_lane_id",
        "feature_id",
        "title",
        "prompt",
        "dependency_rationale",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("acceptance_criteria", "capabilities", "blueprint_refs", "feature_refs")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @field_validator("dependencies", "expected_touched_areas", "artifact_refs")
    @classmethod
    def _validate_optional_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)


class ArchitectFeatureGraphProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    graph_id: str
    title: str
    goal: str
    dependencies: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    lanes: list[ArchitectLaneProposal] = Field(default_factory=list)

    @field_validator("feature_id", "graph_id", "title", "goal")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("dependencies", "artifact_refs")
    @classmethod
    def _validate_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)

    @model_validator(mode="after")
    def _validate_lanes(self) -> ArchitectFeatureGraphProposal:
        if not self.lanes:
            raise ValueError("lanes must contain at least one item")
        for lane in self.lanes:
            if lane.feature_id != self.feature_id:
                raise ValueError("lane feature_id must match parent feature_id")
        _validate_lane_dependencies(self.lanes)
        return self


class ArchitectSelfCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    dependency_shape: str
    lane_size: str
    risk_level: str
    readiness_warnings: list[str] = Field(default_factory=list)

    @field_validator("summary", "dependency_shape", "lane_size", "risk_level")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("readiness_warnings")
    @classmethod
    def _validate_warnings(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "readiness_warnings", allow_empty=True)


class ArchitectGodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    conversation_id: str
    feature_plan_id: str
    feature_plan_version: int
    graph_set_id: str
    graph_set_version: int
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    features: list[PlannerFeatureProposal] = Field(default_factory=list)

    @field_validator(
        "request_id",
        "correlation_id",
        "conversation_id",
        "feature_plan_id",
        "graph_set_id",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("feature_plan_version", "graph_set_version")
    @classmethod
    def _validate_versions(cls, value: int, info: Any) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be >= 1")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def _validate_artifact_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "artifact_refs", allow_empty=True)

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "blueprint_refs")

    @model_validator(mode="after")
    def _validate_features(self) -> ArchitectGodRequest:
        if not self.features:
            raise ValueError("features must contain at least one item")
        return self


class ArchitectGodResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    conversation_id: str
    feature_plan_id: str
    feature_plan_version: int
    graph_set_id: str
    graph_set_version: int
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    feature_graphs: list[ArchitectFeatureGraphProposal] = Field(default_factory=list)
    decomposition_review: GraphSetDecompositionReviewPacket
    architect_self_check: ArchitectSelfCheck

    @field_validator(
        "request_id",
        "correlation_id",
        "conversation_id",
        "feature_plan_id",
        "graph_set_id",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("feature_plan_version", "graph_set_version")
    @classmethod
    def _validate_versions(cls, value: int, info: Any) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be >= 1")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def _validate_artifact_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "artifact_refs", allow_empty=True)

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "blueprint_refs")

    @model_validator(mode="after")
    def _validate_feature_graphs(self) -> ArchitectGodResponse:
        if not self.feature_graphs:
            raise ValueError("feature_graphs must contain at least one item")
        feature_ids = [graph.feature_id for graph in self.feature_graphs]
        graph_ids = [graph.graph_id for graph in self.feature_graphs]
        duplicate_feature_ids = _find_duplicates(feature_ids)
        if duplicate_feature_ids:
            raise ValueError(
                "duplicate feature_graph feature_id: "
                + ", ".join(duplicate_feature_ids)
            )
        duplicate_graph_ids = _find_duplicates(graph_ids)
        if duplicate_graph_ids:
            raise ValueError(
                "duplicate feature_graph graph_id: " + ", ".join(duplicate_graph_ids)
            )
        if self.decomposition_review.feature_packet.feature_ids != feature_ids:
            raise ValueError(
                "decomposition_review feature_packet.feature_ids must match feature_graphs"
            )
        lane_packet_graph_ids = [
            packet.graph_id for packet in self.decomposition_review.lane_packets
        ]
        if lane_packet_graph_ids != graph_ids:
            raise ValueError(
                "decomposition_review lane_packets must match feature_graph graph ids"
            )
        lane_packet_feature_ids = [
            packet.source_feature_id for packet in self.decomposition_review.lane_packets
        ]
        if lane_packet_feature_ids != feature_ids:
            raise ValueError(
                "decomposition_review lane_packets must align with feature_graphs"
            )
        lane_packets_by_graph_id = {
            packet.graph_id: packet for packet in self.decomposition_review.lane_packets
        }
        for graph in self.feature_graphs:
            packet = lane_packets_by_graph_id[graph.graph_id]
            if packet.lane_ids != [lane.lane_id for lane in graph.lanes]:
                raise ValueError(
                    "decomposition_review lane packet lane_ids must match graph lanes"
                )
        return self


class PlanningReviewPhase(StrEnum):
    FEATURE_PLAN_REVIEW = "feature_plan_review"
    GRAPH_SET_REVIEW = "graph_set_review"


class PlanningReviewVerdict(StrEnum):
    APPROVE = "approve"
    REQUEST_REWORK = "request_rework"
    REJECT_AS_INVALID = "reject_as_invalid"
    CHALLENGE_REQUIRED = "challenge_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class PlanningReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    conversation_id: str
    phase: PlanningReviewPhase
    artifact_id: str
    artifact_version: int
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    feature_plan: PlannerGodResponse | None = None
    graph_set: ArchitectGodResponse | None = None

    @field_validator("request_id", "correlation_id", "conversation_id", "artifact_id")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("artifact_version")
    @classmethod
    def _validate_artifact_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("artifact_version must be >= 1")
        return value

    @field_validator("artifact_refs")
    @classmethod
    def _validate_artifact_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "artifact_refs", allow_empty=True)

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "blueprint_refs")

    @model_validator(mode="after")
    def _validate_phase_payload(self) -> PlanningReviewRequest:
        if self.phase == PlanningReviewPhase.FEATURE_PLAN_REVIEW:
            if self.feature_plan is None or self.graph_set is not None:
                raise ValueError(
                    "feature_plan_review requires feature_plan and forbids graph_set"
                )
            if self.artifact_id != self.feature_plan.feature_plan_id:
                raise ValueError("artifact_id must match feature_plan.feature_plan_id")
            if self.artifact_version != self.feature_plan.feature_plan_version:
                raise ValueError(
                    "artifact_version must match feature_plan.feature_plan_version"
                )
        else:
            if self.graph_set is None or self.feature_plan is not None:
                raise ValueError(
                    "graph_set_review requires graph_set and forbids feature_plan"
                )
            if self.artifact_id != self.graph_set.graph_set_id:
                raise ValueError("artifact_id must match graph_set.graph_set_id")
            if self.artifact_version != self.graph_set.graph_set_version:
                raise ValueError(
                    "artifact_version must match graph_set.graph_set_version"
                )
        return self


class PlanningReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str
    artifact_refs: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    lane_ids: list[str] = Field(default_factory=list)

    @field_validator("code", "severity", "message")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("artifact_refs", "feature_ids", "lane_ids")
    @classmethod
    def _validate_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)


class PlanningReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    conversation_id: str
    phase: PlanningReviewPhase
    artifact_id: str
    artifact_version: int
    verdict: PlanningReviewVerdict
    summary: str
    artifact_refs: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    feature_ids: list[str] = Field(default_factory=list)
    lane_ids: list[str] = Field(default_factory=list)
    dependency_rationale_notes: list[str] = Field(default_factory=list)
    architect_self_check: ArchitectSelfCheck | None = None
    findings: list[PlanningReviewFinding] = Field(default_factory=list)

    @field_validator(
        "request_id",
        "correlation_id",
        "conversation_id",
        "artifact_id",
        "summary",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("artifact_version")
    @classmethod
    def _validate_artifact_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError("artifact_version must be >= 1")
        return value

    @field_validator("artifact_refs", "feature_ids", "lane_ids", "dependency_rationale_notes")
    @classmethod
    def _validate_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name, allow_empty=True)

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "blueprint_refs")

    @model_validator(mode="after")
    def _validate_phase_specific_rules(self) -> PlanningReviewResponse:
        if (
            self.phase == PlanningReviewPhase.FEATURE_PLAN_REVIEW
            and self.verdict == PlanningReviewVerdict.MANUAL_REVIEW_REQUIRED
        ):
            raise ValueError("manual_review_required is only valid for graph_set_review")
        if self.phase == PlanningReviewPhase.GRAPH_SET_REVIEW:
            if self.architect_self_check is None:
                raise ValueError("graph_set_review responses require architect_self_check")
        elif self.architect_self_check is not None:
            raise ValueError("feature_plan_review responses must not include architect_self_check")
        return self


__all__ = [
    "ArchitectFeatureGraphProposal",
    "ArchitectGodRequest",
    "ArchitectGodResponse",
    "ArchitectLaneProposal",
    "ArchitectSelfCheck",
    "PlannerFeatureProposal",
    "PlannerGodRequest",
    "PlannerGodResponse",
    "PlannerPreviousFeaturePlan",
    "PlannerReworkContext",
    "PlanningReviewFinding",
    "PlanningReviewPhase",
    "PlanningReviewRequest",
    "PlanningReviewResponse",
    "PlanningReviewVerdict",
]
