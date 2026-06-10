from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from xmuse_core.structuring.area_conflict_index import serial_edges_for_touched_areas
from xmuse_core.structuring.models import LaneGraph, LaneNode


class LanePlannerV2Issue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    subject_id: str
    field: str
    severity: Literal["error"] = "error"
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("code", "message", "subject_id", "field")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)


class LanePlannerV2ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    issues: list[LanePlannerV2Issue] = Field(default_factory=list)

    def to_chat_payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": [issue.model_dump(mode="json") for issue in self.issues],
        }


class LanePlannerV2ValidationError(ValueError):
    def __init__(self, report: LanePlannerV2ValidationReport) -> None:
        self.report = report
        super().__init__("lane planner v2 validation failed")

    def to_chat_payload(self) -> dict[str, object]:
        return self.report.to_chat_payload()


class LanePlannerV2LaneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    title: str | None = None
    prompt: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    blueprint_refs: list[str] = Field(default_factory=list)
    expected_touched_areas: list[str] = Field(default_factory=list)
    gate_profile: str | None = None
    gate_profiles: list[str] = Field(default_factory=list)
    priority: int = 0
    task_type: str = "execute"
    capabilities: list[str] = Field(default_factory=lambda: ["code"])

    @field_validator("lane_id", "prompt")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "acceptance_criteria",
        "depends_on",
        "blueprint_refs",
        "expected_touched_areas",
        "gate_profiles",
        "capabilities",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


class LanePlannerV2Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str
    conversation_id: str
    resolution_id: str
    version: int
    available_blueprint_refs: list[str]
    lanes: list[LanePlannerV2LaneInput]
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("graph_id", "conversation_id", "resolution_id")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("version must be >= 1")
        return value

    @field_validator("available_blueprint_refs", "source_refs")
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]


def validate_lane_plan_v2(request: LanePlannerV2Input) -> LanePlannerV2ValidationReport:
    issues = [
        *_acceptance_criteria_issues(request),
        *_blueprint_ref_issues(request),
        *_unknown_dependency_issues(request),
    ]
    if not issues:
        graph_issue = _lane_graph_issue(request)
        if graph_issue is not None:
            issues.append(graph_issue)
    return LanePlannerV2ValidationReport(ok=not issues, issues=issues)


def build_lane_graph_v2(request: LanePlannerV2Input) -> LaneGraph:
    report = validate_lane_plan_v2(request)
    if not report.ok:
        raise LanePlannerV2ValidationError(report)
    return _lane_graph(request)


def _acceptance_criteria_issues(
    request: LanePlannerV2Input,
) -> list[LanePlannerV2Issue]:
    issues: list[LanePlannerV2Issue] = []
    for lane in request.lanes:
        if lane.acceptance_criteria:
            continue
        issues.append(
            LanePlannerV2Issue(
                code="missing_acceptance_criteria",
                message=f"lane {lane.lane_id} must declare at least one acceptance criterion",
                subject_id=lane.lane_id,
                field="acceptance_criteria",
                source_refs=request.source_refs,
            )
        )
    return issues


def _blueprint_ref_issues(request: LanePlannerV2Input) -> list[LanePlannerV2Issue]:
    available = set(request.available_blueprint_refs)
    issues: list[LanePlannerV2Issue] = []
    for lane in request.lanes:
        if not lane.blueprint_refs:
            issues.append(
                LanePlannerV2Issue(
                    code="missing_blueprint_ref",
                    message=f"lane {lane.lane_id} must reference at least one blueprint ref",
                    subject_id=lane.lane_id,
                    field="blueprint_refs",
                    source_refs=request.source_refs,
                )
            )
            continue
        for blueprint_ref in lane.blueprint_refs:
            if blueprint_ref in available:
                continue
            issues.append(
                LanePlannerV2Issue(
                    code="invalid_blueprint_ref",
                    message=(
                        f"lane {lane.lane_id} references unavailable blueprint ref "
                        f"{blueprint_ref}"
                    ),
                    subject_id=lane.lane_id,
                    field="blueprint_refs",
                    source_refs=request.source_refs,
                )
            )
    return issues


def _unknown_dependency_issues(request: LanePlannerV2Input) -> list[LanePlannerV2Issue]:
    lane_ids = {lane.lane_id for lane in request.lanes}
    issues: list[LanePlannerV2Issue] = []
    for lane in request.lanes:
        for dependency in lane.depends_on:
            if dependency in lane_ids:
                continue
            issues.append(
                LanePlannerV2Issue(
                    code="unknown_dependency",
                    message=f"lane {lane.lane_id} depends on unknown lane {dependency}",
                    subject_id=lane.lane_id,
                    field="depends_on",
                    source_refs=request.source_refs,
                )
            )
    return issues


def _lane_graph_issue(request: LanePlannerV2Input) -> LanePlannerV2Issue | None:
    try:
        _lane_graph(request)
    except (ValueError, ValidationError) as exc:
        return LanePlannerV2Issue(
            code="invalid_lane_graph",
            message=_error_message(exc),
            subject_id=request.graph_id,
            field="lanes",
            source_refs=request.source_refs,
        )
    return None


def _lane_graph(request: LanePlannerV2Input) -> LaneGraph:
    normalized_lanes = _with_gate_predecessors(_with_area_conflict_dependencies(request.lanes))
    return LaneGraph(
        id=request.graph_id,
        conversation_id=request.conversation_id,
        resolution_id=request.resolution_id,
        version=request.version,
        status="planned",
        source_refs=request.source_refs,
        lanes=[_lane_node(lane) for lane in normalized_lanes],
    )


def _with_area_conflict_dependencies(
    lanes: list[LanePlannerV2LaneInput],
) -> list[LanePlannerV2LaneInput]:
    dependencies_by_lane = {lane.lane_id: list(lane.depends_on) for lane in lanes}
    for source_id, target_id in serial_edges_for_touched_areas(lanes):
        dependencies = dependencies_by_lane[target_id]
        if source_id not in dependencies:
            dependencies.append(source_id)
    return [
        lane.model_copy(update={"depends_on": dependencies_by_lane[lane.lane_id]})
        for lane in lanes
    ]


def _with_gate_predecessors(
    lanes: list[LanePlannerV2LaneInput],
) -> list[LanePlannerV2LaneInput]:
    normalized: list[LanePlannerV2LaneInput] = []
    for lane in lanes:
        predecessor_ids = list(lane.depends_on)
        gate_lanes: list[LanePlannerV2LaneInput] = []
        for gate_type in _gate_predecessor_types(lane):
            gate_id = f"{lane.lane_id}-{gate_type}-gate"
            gate_lanes.append(
                LanePlannerV2LaneInput(
                    lane_id=gate_id,
                    title=f"{lane.title or lane.lane_id} {gate_type} gate",
                    prompt=f"{gate_type.title()} gate for {lane.lane_id}.",
                    task_type=gate_type,
                    capabilities=[gate_type],
                    depends_on=predecessor_ids,
                    acceptance_criteria=[
                        f"{gate_type.title()} gate passes for {lane.lane_id}."
                    ],
                    blueprint_refs=lane.blueprint_refs,
                    expected_touched_areas=[],
                )
            )
            predecessor_ids = [gate_id]
        normalized.extend(gate_lanes)
        normalized.append(lane.model_copy(update={"depends_on": predecessor_ids}))
    return normalized


def _gate_predecessor_types(lane: LanePlannerV2LaneInput) -> list[str]:
    profiles = [*(lane.gate_profiles or [])]
    if lane.gate_profile:
        profiles.append(lane.gate_profile)
    gate_types: list[str] = []
    for profile in profiles:
        if profile in {"check", "quality", "quality_gate"} and "check" not in gate_types:
            gate_types.append("check")
        if profile in {"review", "review_required"} and "review" not in gate_types:
            gate_types.append("review")
    return gate_types


def _lane_node(lane: LanePlannerV2LaneInput) -> LaneNode:
    return LaneNode(
        feature_id=lane.lane_id,
        title=lane.title,
        prompt=lane.prompt,
        task_type=lane.task_type,
        priority=lane.priority,
        capabilities=lane.capabilities,
        depends_on=lane.depends_on,
        gate_profile=lane.gate_profile,
        gate_profiles=lane.gate_profiles,
        blueprint_refs=lane.blueprint_refs,
        acceptance_criteria=lane.acceptance_criteria,
        expected_touched_areas=lane.expected_touched_areas,
    )


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if errors:
            message = errors[0].get("msg")
            if isinstance(message, str):
                return message.removeprefix("Value error, ")
    return str(exc)


def _require_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must be non-empty")
    return value
