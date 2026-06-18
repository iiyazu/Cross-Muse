from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardMergeGuardDecision,
    FeatureGraphPatchForwardMergeGuardHandoff,
    FeatureGraphPatchForwardPlan,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphReviewStatusTransitionPlan,
    FeatureGraphStatusEventRecord,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverFollowupReviewApplicationRecord,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureGraphTakeoverTrigger,
    FeatureGraphWorkerClaimPlan,
    FeatureGraphWorkerEvidenceSubmissionPlan,
    FeatureReviewDecision,
    FeatureReviewVerdict,
    ProviderSessionBindingDegradationEvidence,
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
    ReworkPacket,
)
from xmuse_core.structuring.graph_validation import (
    duplicate_edge_labels as _duplicate_edge_labels,
)
from xmuse_core.structuring.graph_validation import (
    duplicates as _duplicates,
)
from xmuse_core.structuring.graph_validation import (
    validate_acyclic_dependencies as _validate_acyclic_dependencies,
)
from xmuse_core.structuring.graph_validation import (
    validate_dependency_edges as _validate_dependency_edges,
)
from xmuse_core.structuring.graph_validation import (
    validate_lane_collection as _validate_lane_collection,
)
from xmuse_core.structuring.planning_event_models import (
    PlanningEvent,
    PlanningEventStatus,
)
from xmuse_core.structuring.review_models import (
    ReviewDecision,
    ReviewTask,
    ReviewTaskStatus,
    ReviewVerdict,
    RunTerminalAggregation,
    RunTerminalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.structuring.takeover_models import (
    ReviewGodTakeoverAction,
    ReviewGodTakeoverContextContract,
    ReviewGodTakeoverDecision,
    ReviewGodTakeoverEvidence,
    TakeoverAttemptContext,
    TakeoverEvidenceContext,
    TakeoverFeaturePlanContext,
    TakeoverGraphSetContext,
    TakeoverLaneContext,
    TakeoverLeaseContext,
    TakeoverMaxAttemptContext,
    TakeoverProjectionContext,
)

__all__ = [
    "FeatureEvidenceBundle",
    "FeatureGraphBlockedReviewPlan",
    "FeatureGraphExecutionStatus",
    "FeatureGraphExecutionStatusRecord",
    "FeatureGraphPatchForwardGateResult",
    "FeatureGraphPatchForwardMergeGuardDecision",
    "FeatureGraphPatchForwardMergeGuardHandoff",
    "FeatureGraphPatchForwardPlan",
    "FeatureGraphReviewCoordinatorAction",
    "FeatureGraphReviewStatusTransitionPlan",
    "FeatureGraphStatusEventRecord",
    "FeatureGraphTakeoverDecision",
    "FeatureGraphTakeoverFollowupReviewApplicationRecord",
    "FeatureGraphTakeoverHandoff",
    "FeatureGraphTakeoverOutcome",
    "FeatureGraphTakeoverPlan",
    "FeatureGraphTakeoverReviewHandoff",
    "FeatureGraphTakeoverTrigger",
    "FeatureGraphWorkerClaimPlan",
    "FeatureGraphWorkerEvidenceSubmissionPlan",
    "FeatureReviewDecision",
    "FeatureReviewVerdict",
    "ProviderSessionBindingDegradationEvidence",
    "ProviderSessionBindingRecord",
    "ProviderSessionBindingStatus",
    "ReworkPacket",
    "ReviewDecision",
    "ReviewGodTakeoverAction",
    "ReviewGodTakeoverContextContract",
    "ReviewGodTakeoverDecision",
    "ReviewGodTakeoverEvidence",
    "ReviewTask",
    "ReviewTaskStatus",
    "ReviewVerdict",
    "RunTerminalAggregation",
    "RunTerminalStatus",
    "PlanningEvent",
    "PlanningEventStatus",
    "StructuredEvidenceBundle",
    "TakeoverAttemptContext",
    "TakeoverEvidenceContext",
    "TakeoverFeaturePlanContext",
    "TakeoverGraphSetContext",
    "TakeoverLaneContext",
    "TakeoverLeaseContext",
    "TakeoverMaxAttemptContext",
    "TakeoverProjectionContext",
]


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_non_empty_list(values: list[str], field_name: str) -> list[str]:
    cleaned = [_require_non_empty(value, field_name) for value in values]
    if not cleaned:
        raise ValueError(f"{field_name} must contain at least one item")
    return cleaned


def _require_non_negative_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return value


class LaneNode(BaseModel):
    feature_id: str
    title: str | None = None
    prompt: str
    task_type: str = "execute"
    priority: int = 0
    capabilities: list[str] = Field(default_factory=lambda: ["code"])
    depends_on: list[str] = Field(default_factory=list)
    gate_profile: str | None = None
    gate_profiles: list[str] = Field(default_factory=list)
    source_lane_id: str | None = None
    feature_group: str | None = None
    review_runtime: str | None = None
    final_action: str | None = None
    proof_boundary: str | None = None
    blueprint_refs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_touched_areas: list[str] = Field(default_factory=list)


class LaneGraph(BaseModel):
    id: str
    conversation_id: str
    resolution_id: str
    version: int
    status: str = "planned"
    source_refs: list[str] = Field(default_factory=list)
    lanes: list[LaneNode] = Field(default_factory=list)

    @field_validator("id", "conversation_id", "resolution_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "source_refs") for item in value]

    @model_validator(mode="after")
    def _validate_lanes(self) -> LaneGraph:
        _validate_lane_collection(self.lanes)
        return self


class FeaturePlanFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    title: str
    goal: str
    acceptance_criteria: list[str]
    dependencies: list[str] = Field(default_factory=list)
    graph_id: str
    expected_touched_areas: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)

    @field_validator("feature_id", "title", "goal", "graph_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("acceptance_criteria")
    @classmethod
    def _validate_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return _require_non_empty_list(value, "acceptance_criteria")

    @field_validator("dependencies")
    @classmethod
    def _validate_dependencies(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "dependencies") for item in value]

    @field_validator("expected_touched_areas")
    @classmethod
    def _validate_expected_touched_areas(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "expected_touched_areas") for item in value]

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "blueprint_refs") for item in value]

    @model_validator(mode="after")
    def _reject_self_dependency(self) -> FeaturePlanFeature:
        if self.feature_id in self.dependencies:
            raise ValueError("dependencies must not include the feature_id itself")
        return self


class DependencyEdgeRationale(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_id: str
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("source_id", "target_id", "rationale")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "evidence_refs") for item in value]

    @model_validator(mode="after")
    def _reject_self_edge(self) -> DependencyEdgeRationale:
        if self.source_id == self.target_id:
            raise ValueError("dependency edge must not point to itself")
        return self


class DecompositionReviewHeuristics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    over_serialized_min_node_count: int = 4
    over_serialized_min_critical_path_ratio: float = 0.8
    over_serialized_max_parallel_width: int = 2
    broad_lane_min_prompt_words: int = 25
    broad_lane_min_acceptance_criteria: int = 4
    tiny_lane_max_prompt_words: int = 8
    tiny_lane_max_acceptance_criteria: int = 1

    @field_validator(
        "over_serialized_min_node_count",
        "over_serialized_max_parallel_width",
        "broad_lane_min_prompt_words",
        "broad_lane_min_acceptance_criteria",
        "tiny_lane_max_prompt_words",
        "tiny_lane_max_acceptance_criteria",
    )
    @classmethod
    def _validate_non_negative_int(cls, value: int, info: Any) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be >= 0")
        return value

    @field_validator("over_serialized_min_critical_path_ratio")
    @classmethod
    def _validate_ratio(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("over_serialized_min_critical_path_ratio must be between 0 and 1")
        return value


class DecompositionReviewWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str = "warning"
    message: str
    subject_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("code", "severity", "message")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("subject_ids")
    @classmethod
    def _validate_subject_ids(cls, value: list[str]) -> list[str]:
        return _require_non_empty_list(value, "subject_ids")


def _validate_review_packet_edge_ids(
    edges: list[DependencyEdgeRationale],
    *,
    known_ids: set[str],
    label: str,
) -> None:
    duplicate_edges = _duplicate_edge_labels(
        [(edge.source_id, edge.target_id) for edge in edges]
    )
    if duplicate_edges:
        raise ValueError(f"duplicate {label}: {', '.join(duplicate_edges)}")

    unknown_ids = sorted(
        {
            node_id
            for edge in edges
            for node_id in (edge.source_id, edge.target_id)
            if node_id not in known_ids
        }
    )
    if unknown_ids:
        raise ValueError(
            f"{label} reference unknown node ids: " + ", ".join(unknown_ids)
        )


class FeatureDecompositionReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    source_blueprint_ref: str
    feature_ids: list[str] = Field(default_factory=list)
    dependency_edges: list[DependencyEdgeRationale] = Field(default_factory=list)
    review_warnings: list[DecompositionReviewWarning] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)

    @field_validator("packet_id", "source_blueprint_ref")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("feature_ids")
    @classmethod
    def _validate_feature_ids(cls, value: list[str]) -> list[str]:
        return _require_non_empty_list(value, "feature_ids")

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "blueprint_refs") for item in value]

    @model_validator(mode="after")
    def _validate_edges(self) -> FeatureDecompositionReviewPacket:
        feature_ids = _require_non_empty_list(self.feature_ids, "feature_ids")
        if self.source_blueprint_ref not in self.blueprint_refs:
            raise ValueError(
                "blueprint_refs must include the source_blueprint_ref"
            )
        _validate_review_packet_edge_ids(
            self.dependency_edges,
            known_ids=set(feature_ids),
            label="feature dependency_edges",
        )
        return self


class LaneDecompositionReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    graph_id: str
    source_feature_id: str
    lane_ids: list[str] = Field(default_factory=list)
    dependency_edges: list[DependencyEdgeRationale] = Field(default_factory=list)
    review_warnings: list[DecompositionReviewWarning] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)

    @field_validator("packet_id", "graph_id", "source_feature_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("lane_ids")
    @classmethod
    def _validate_lane_ids(cls, value: list[str]) -> list[str]:
        return _require_non_empty_list(value, "lane_ids")

    @field_validator("blueprint_refs")
    @classmethod
    def _validate_blueprint_refs(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "blueprint_refs") for item in value]

    @model_validator(mode="after")
    def _validate_edges(self) -> LaneDecompositionReviewPacket:
        _validate_review_packet_edge_ids(
            self.dependency_edges,
            known_ids=set(_require_non_empty_list(self.lane_ids, "lane_ids")),
            label="lane dependency_edges",
        )
        return self


class GraphSetDecompositionReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    source_blueprint_ref: str
    supporting_refs: list[str] = Field(default_factory=list)
    feature_packet: FeatureDecompositionReviewPacket
    lane_packets: list[LaneDecompositionReviewPacket] = Field(default_factory=list)

    @field_validator("packet_id", "source_blueprint_ref")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("supporting_refs")
    @classmethod
    def _validate_supporting_refs(cls, value: list[str]) -> list[str]:
        refs = [_require_non_empty(item, "supporting_refs") for item in value]
        deduped: list[str] = []
        for ref in refs:
            if ref not in deduped:
                deduped.append(ref)
        return deduped

    @model_validator(mode="after")
    def _validate_relationships(self) -> GraphSetDecompositionReviewPacket:
        if not self.supporting_refs:
            raise ValueError("supporting_refs must contain at least one item")
        if self.source_blueprint_ref not in self.supporting_refs:
            raise ValueError("supporting_refs must include the source_blueprint_ref")
        if self.feature_packet.source_blueprint_ref != self.source_blueprint_ref:
            raise ValueError(
                "feature_packet source_blueprint_ref must match graph-set packet source"
            )
        graph_ids = [packet.graph_id for packet in self.lane_packets]
        duplicate_graph_ids = _duplicates(graph_ids)
        if duplicate_graph_ids:
            raise ValueError(
                "duplicate lane packet graph id: " + ", ".join(duplicate_graph_ids)
            )
        source_feature_ids = [packet.source_feature_id for packet in self.lane_packets]
        duplicate_feature_ids = _duplicates(source_feature_ids)
        if duplicate_feature_ids:
            raise ValueError(
                "duplicate lane packet source_feature_id: "
                + ", ".join(duplicate_feature_ids)
            )
        return self


class FeatureDecompositionCandidatePacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    conversation_id: str
    source_blueprint_ref: str
    features: list[FeaturePlanFeature] = Field(default_factory=list)
    dependency_edges: list[DependencyEdgeRationale] = Field(default_factory=list)
    review_heuristics: DecompositionReviewHeuristics = Field(
        default_factory=DecompositionReviewHeuristics
    )
    review_warnings: list[DecompositionReviewWarning] = Field(default_factory=list)

    @field_validator("packet_id", "conversation_id", "source_blueprint_ref")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_candidate_dag(self) -> FeatureDecompositionCandidatePacket:
        if not self.features:
            raise ValueError("features must contain at least one item")

        _validate_feature_collection(self.features)
        known_ids = {feature.feature_id for feature in self.features}
        expected_edges = {
            (dependency, feature.feature_id)
            for feature in self.features
            for dependency in feature.dependencies
        }
        _validate_dependency_edges(
            self.dependency_edges,
            known_ids=known_ids,
            expected_edges=expected_edges,
        )
        _validate_acyclic_dependencies(
            known_ids=known_ids,
            expected_edges=expected_edges,
        )
        from xmuse_core.structuring.decomposition_review import (
            review_feature_decomposition,
        )

        self.review_warnings = review_feature_decomposition(
            self.features,
            heuristics=self.review_heuristics,
        )
        return self


class LaneDecompositionCandidatePacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    conversation_id: str
    source_feature_id: str
    graph_id: str
    lanes: list[LaneNode] = Field(default_factory=list)
    dependency_edges: list[DependencyEdgeRationale] = Field(default_factory=list)
    review_heuristics: DecompositionReviewHeuristics = Field(
        default_factory=DecompositionReviewHeuristics
    )
    review_warnings: list[DecompositionReviewWarning] = Field(default_factory=list)

    @field_validator("packet_id", "conversation_id", "source_feature_id", "graph_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_candidate_dag(self) -> LaneDecompositionCandidatePacket:
        if not self.lanes:
            raise ValueError("lanes must contain at least one item")

        _validate_lane_collection(self.lanes)
        known_ids = {lane.feature_id for lane in self.lanes}
        expected_edges = {
            (dependency, lane.feature_id)
            for lane in self.lanes
            for dependency in lane.depends_on
        }
        _validate_dependency_edges(
            self.dependency_edges,
            known_ids=known_ids,
            expected_edges=expected_edges,
        )
        _validate_acyclic_dependencies(
            known_ids=known_ids,
            expected_edges=expected_edges,
        )
        from xmuse_core.structuring.decomposition_review import review_lane_decomposition

        self.review_warnings = review_lane_decomposition(
            self.lanes,
            heuristics=self.review_heuristics,
        )
        return self


def _validate_feature_collection(features: list[FeaturePlanFeature]) -> None:
    feature_ids = [feature.feature_id for feature in features]
    duplicate_ids = _duplicates(feature_ids)
    if duplicate_ids:
        raise ValueError(f"duplicate feature_id: {', '.join(duplicate_ids)}")

    known_ids = set(feature_ids)
    missing_dependencies = sorted(
        {
            dependency
            for feature in features
            for dependency in feature.dependencies
            if dependency not in known_ids
        }
    )
    if missing_dependencies:
        missing = ", ".join(missing_dependencies)
        raise ValueError(f"dependencies reference unknown feature_id: {missing}")

    graph_ids = [feature.graph_id for feature in features]
    duplicate_graph_ids = _duplicates(graph_ids)
    if duplicate_graph_ids:
        raise ValueError(f"duplicate graph id: {', '.join(duplicate_graph_ids)}")

    _validate_acyclic_dependencies(
        known_ids=known_ids,
        expected_edges={
            (dependency, feature.feature_id)
            for feature in features
            for dependency in feature.dependencies
        },
    )


class ApprovedMissionBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_id: str
    conversation_id: str
    version: int
    title: str
    body: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    blueprint_ref: str
    proposal_blueprint_ref: str | None = None
    revision_of: str | None = None

    @field_validator(
        "resolution_id",
        "conversation_id",
        "title",
        "body",
        "blueprint_ref",
        "proposal_blueprint_ref",
        "revision_of",
    )
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)

    @field_validator("acceptance_criteria", "references")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return [_require_non_empty(item, info.field_name) for item in value]

    @property
    def available_refs(self) -> list[str]:
        refs: list[str] = []
        for value in (
            self.blueprint_ref,
            self.proposal_blueprint_ref,
            self.revision_of,
            *self.references,
        ):
            if value and value not in refs:
                refs.append(value)
        return refs


class FeaturePlanProposalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class FeaturePlanProposalApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: list[str]
    approval_mode: str
    approved_at: str

    @field_validator("approved_by")
    @classmethod
    def _validate_approved_by(cls, value: list[str]) -> list[str]:
        return _require_non_empty_list(value, "approved_by")

    @field_validator("approval_mode", "approved_at")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)


class FeaturePlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    source_blueprint: ApprovedMissionBlueprint
    features: list[FeaturePlanFeature] = Field(default_factory=list)
    status: FeaturePlanProposalStatus = FeaturePlanProposalStatus.PROPOSED
    approval: FeaturePlanProposalApproval | None = None

    @field_validator("id", "conversation_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_features(self) -> FeaturePlanProposal:
        if self.conversation_id != self.source_blueprint.conversation_id:
            raise ValueError("proposal conversation_id must match source blueprint")
        if not self.features:
            raise ValueError("features must contain at least one item")

        _validate_feature_collection(self.features)

        allowed_refs = set(self.source_blueprint.available_refs)
        for feature in self.features:
            if not feature.blueprint_refs:
                raise ValueError(
                    f"missing blueprint refs for feature {feature.feature_id}"
                )
            unknown_refs = sorted(set(feature.blueprint_refs) - allowed_refs)
            if unknown_refs:
                raise ValueError(
                    f"unknown blueprint refs for feature {feature.feature_id}: "
                    f"{', '.join(unknown_refs)}"
                )
        if self.status == FeaturePlanProposalStatus.APPROVED and self.approval is None:
            raise ValueError("approved feature plan proposals require approval metadata")
        if self.status != FeaturePlanProposalStatus.APPROVED and self.approval is not None:
            raise ValueError("feature plan approval metadata requires approved status")
        return self

    def to_feature_plan(
        self,
        *,
        resolution_id: str,
        version: int,
        plan_id: str | None = None,
    ) -> FeaturePlan:
        if self.status != FeaturePlanProposalStatus.APPROVED or self.approval is None:
            raise ValueError("approved feature plan proposals require approval metadata")
        return FeaturePlan(
            id=plan_id or self.id,
            conversation_id=self.conversation_id,
            resolution_id=resolution_id,
            version=version,
            features=[feature.model_copy(deep=True) for feature in self.features],
        )


class FeaturePlan(BaseModel):
    id: str
    conversation_id: str
    resolution_id: str
    version: int
    features: list[FeaturePlanFeature] = Field(default_factory=list)

    @field_validator("id", "conversation_id", "resolution_id")
    @classmethod
    def _validate_required_text(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _validate_feature_references(self) -> FeaturePlan:
        _validate_feature_collection(self.features)
        return self


class FeatureGraphSet(BaseModel):
    id: str
    version: int | None = None
    source_refs: list[str] = Field(default_factory=list)
    feature_plan: FeaturePlan
    graphs: list[LaneGraph] = Field(default_factory=list)
    decomposition_review: GraphSetDecompositionReviewPacket | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_non_empty(value, "id")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return _require_non_negative_int(value, "version")

    @field_validator("source_refs")
    @classmethod
    def _validate_source_refs(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, "source_refs") for item in value]

    @model_validator(mode="after")
    def _validate_graphs(self) -> FeatureGraphSet:
        if self.version is None:
            self.version = self.feature_plan.version
        if not self.source_refs:
            self.source_refs = _default_feature_plan_source_refs(self.feature_plan)

        graph_ids = [graph.id for graph in self.graphs]
        duplicate_graph_ids = _duplicates(graph_ids)
        if duplicate_graph_ids:
            raise ValueError(f"duplicate graph id: {', '.join(duplicate_graph_ids)}")

        expected_graph_ids = {feature.graph_id for feature in self.feature_plan.features}
        actual_graph_ids = set(graph_ids)
        missing = sorted(expected_graph_ids - actual_graph_ids)
        extra = sorted(actual_graph_ids - expected_graph_ids)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if extra:
                details.append(f"extra: {', '.join(extra)}")
            raise ValueError(f"graph id mismatch ({'; '.join(details)})")

        for graph in self.graphs:
            if graph.conversation_id != self.feature_plan.conversation_id:
                raise ValueError("graph conversation_id must match feature plan")
            if graph.resolution_id != self.feature_plan.resolution_id:
                raise ValueError("graph resolution_id must match feature plan")
            if graph.version != self.feature_plan.version:
                raise ValueError("graph version must match feature plan")
            if not graph.source_refs:
                graph.source_refs = list(self.source_refs)
        if self.decomposition_review is not None:
            feature_ids = [feature.feature_id for feature in self.feature_plan.features]
            if self.decomposition_review.feature_packet.feature_ids != feature_ids:
                raise ValueError(
                    "decomposition_review feature_packet.feature_ids must match feature plan"
                )
            graph_ids = [graph.id for graph in self.graphs]
            lane_packet_graph_ids = [
                packet.graph_id for packet in self.decomposition_review.lane_packets
            ]
            if lane_packet_graph_ids != graph_ids:
                raise ValueError(
                    "decomposition_review lane_packets must match graph set graph ids"
                )
            lane_packet_feature_ids = [
                packet.source_feature_id
                for packet in self.decomposition_review.lane_packets
            ]
            if lane_packet_feature_ids != feature_ids:
                raise ValueError(
                    "decomposition_review lane_packets must align with feature plan order"
                )
            lane_packet_by_graph_id = {
                packet.graph_id: packet for packet in self.decomposition_review.lane_packets
            }
            for graph in self.graphs:
                packet = lane_packet_by_graph_id[graph.id]
                graph_lane_ids = [lane.feature_id for lane in graph.lanes]
                if packet.lane_ids != graph_lane_ids:
                    raise ValueError(
                        "decomposition_review lane packet lane_ids must match graph lanes"
                    )
        return self


def _default_feature_plan_source_refs(feature_plan: FeaturePlan) -> list[str]:
    refs = [f"feature_plan:{feature_plan.id}:v{feature_plan.version}"]
    for feature in feature_plan.features:
        for ref in feature.blueprint_refs:
            if ref not in refs:
                refs.append(ref)
    return refs


class PlanningRunStatus(StrEnum):
    PLANNING = "planning"
    FEATURE_PLAN_REVIEW = "feature_plan_review"
    ARCHITECTING = "architecting"
    GRAPH_REVIEW = "graph_review"
    INJECTING = "injecting"
    RUNNING = "running"
    REWORKING = "reworking"
    WAITING_MANUAL_REVIEW = "waiting_manual_review"
    CHALLENGE_REVIEW = "challenge_review"
    TERMINAL = "terminal"
    FAILED = "failed"


class PlanningRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planning_run_id: str
    conversation_id: str
    blueprint_ref: str
    blueprint_version: int
    dedupe_key: str
    rerun_sequence: int = 0
    rerun_of: str | None = None
    status: PlanningRunStatus = PlanningRunStatus.PLANNING
    feature_plan_id: str | None = None
    feature_plan_version: int | None = None
    graph_set_id: str | None = None
    graph_set_version: int | None = None
    risk_level: str = "unknown"
    trigger_owner: str = "GOD"
    human_trigger_enabled: bool = False
    manual_review_mode: bool = False
    review_policy: str = "risk_adaptive"
    queue_backend: str = "sqlite"
    external_mq: str = "disabled"
    created_by: str = "god"
    audit_refs: list[str] = Field(default_factory=list)
    chat_card_refs: list[str] = Field(default_factory=list)
    retry_count: int = 0
    created_at: str
    updated_at: str

    @field_validator(
        "planning_run_id",
        "conversation_id",
        "blueprint_ref",
        "dedupe_key",
        "rerun_of",
        "feature_plan_id",
        "graph_set_id",
        "risk_level",
        "trigger_owner",
        "review_policy",
        "queue_backend",
        "external_mq",
        "created_by",
        "created_at",
        "updated_at",
    )
    @classmethod
    def _validate_text_fields(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)

    @field_validator("audit_refs", "chat_card_refs")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return [_require_non_empty(item, info.field_name) for item in value]

    @field_validator(
        "blueprint_version",
        "feature_plan_version",
        "graph_set_version",
        "rerun_sequence",
        "retry_count",
    )
    @classmethod
    def _validate_non_negative_ints(cls, value: int | None, info: Any) -> int | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError(f"{info.field_name} must be >= 0")
        return value

    @model_validator(mode="after")
    def _validate_rerun_and_artifact_lineage(self) -> PlanningRun:
        if self.rerun_sequence == 0 and self.rerun_of is not None:
            raise ValueError("rerun_of must be null when rerun_sequence is 0")
        if self.rerun_sequence > 0 and self.rerun_of is None:
            raise ValueError("rerun_of is required when rerun_sequence is greater than 0")
        if (self.feature_plan_id is None) != (self.feature_plan_version is None):
            raise ValueError(
                "feature_plan_id and feature_plan_version must both be set or both be null"
            )
        if (self.graph_set_id is None) != (self.graph_set_version is None):
            raise ValueError(
                "graph_set_id and graph_set_version must both be set or both be null"
            )
        return self


class ClarificationStatus(StrEnum):
    """Lifecycle status for a ClarificationObject.

    ``open``
        The clarification is blocking run progress; no executable lane can
        advance until this is resolved.
    ``resolved``
        The clarification has been answered and the block is lifted.
    ``cancelled``
        The clarification was withdrawn without a resolution (e.g. the lane
        was terminated before an answer arrived).
    """

    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ClarificationObject(BaseModel):
    """A blocked-for-input record for a lane that cannot proceed without
    external information or clarification.

    This is the authoritative object for the ``blocked_for_input`` terminal
    state in the run-level aggregation contract.  A run is ``blocked_for_input``
    when at least one ``ClarificationObject`` with status ``open`` exists for
    any lane in the run and no executable lane can advance.

    Minimum fields match the blueprint-anchored self-evolution spec,
    "Run Terminal Aggregation → blocked_for_input" section.
    """

    clarification_id: str
    lane_id: str
    graph_id: str | None = None
    resolution_id: str | None = None
    # Human-readable description of what information is needed.
    question: str
    # Optional structured context for the blocking gap.
    context: dict[str, Any] = Field(default_factory=dict)
    status: ClarificationStatus = ClarificationStatus.OPEN
    # Set when the clarification is resolved.
    answer: str | None = None
    resolved_by: str | None = None
    created_at: str
    updated_at: str | None = None
