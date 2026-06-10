from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _require_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _require_text_list(values: list[str], field_name: str) -> list[str]:
    cleaned = [_require_text(value, field_name) for value in values]
    if not cleaned:
        raise ValueError(f"{field_name} must contain at least one item")
    return cleaned


def _clean_text_list(values: list[str], field_name: str) -> list[str]:
    return [_require_text(value, field_name) for value in values]


def _safe_event_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "value"


def _require_ref(values: list[str], expected_ref: str, field_name: str) -> None:
    if expected_ref not in values:
        raise ValueError(f"{field_name} must include {expected_ref}")


def _validate_timestamp(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _require_timezone_timestamp(value: str, field_name: str) -> str:
    _parse_timezone_timestamp(value, field_name)
    return _require_text(value, field_name)


def _parse_timezone_timestamp(value: str, field_name: str) -> datetime:
    cleaned = _require_text(value, field_name)
    normalized = cleaned.replace("Z", "+00:00") if cleaned.endswith("Z") else cleaned
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone offset")
    return parsed


class FeatureReviewDecision(StrEnum):
    MERGE = "merge"
    REWORK = "rework"
    PATCH_FORWARD = "patch_forward"
    TAKEOVER = "takeover"
    BLOCKED = "blocked"


class ProviderSessionBindingStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    FAILED = "failed"
    RETIRED = "retired"


class FeatureGraphExecutionStatus(StrEnum):
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    REVIEWING = "reviewing"
    REWORKING = "reworking"
    MERGED = "merged"
    BLOCKED = "blocked"
    FAILED = "failed"


class FeatureGraphReviewCoordinatorAction(StrEnum):
    TRANSITION_STATUS = "transition_status"
    PATCH_FORWARD_GATE = "patch_forward_gate"
    TAKEOVER_REQUIRED = "takeover_required"


class FeatureGraphTakeoverTrigger(StrEnum):
    WORKER_UNRECOVERABLE = "worker_unrecoverable"
    REPEATED_FAILURE = "repeated_failure"
    CONTEXT_LOST = "context_lost"
    RISK_ESCALATED = "risk_escalated"


class ProviderSessionBindingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    god_session_id: str
    provider: str
    provider_session_id: str
    session_kind: str
    status: ProviderSessionBindingStatus = ProviderSessionBindingStatus.ACTIVE
    conversation_id: str | None = None
    feature_graph_id: str | None = None
    role: str
    cwd: str
    worktree: str | None = None
    model: str | None = None
    prompt_fingerprint: str | None = None
    created_at: str
    last_used_at: str | None = None
    last_verified_at: str | None = None
    failure_reason: str | None = None
    resume_command_template: str | None = None

    @field_validator(
        "binding_id",
        "god_session_id",
        "provider",
        "session_kind",
        "role",
        "cwd",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: str) -> str:
        return _require_timezone_timestamp(value, "created_at")

    @field_validator(
        "conversation_id",
        "feature_graph_id",
        "worktree",
        "model",
        "prompt_fingerprint",
        "failure_reason",
        "resume_command_template",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("last_used_at", "last_verified_at")
    @classmethod
    def _validate_optional_timestamps(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_timezone_timestamp(value, info.field_name)

    @field_validator("provider_session_id")
    @classmethod
    def _validate_explicit_provider_session_id(cls, value: str) -> str:
        cleaned = _require_text(value, "provider_session_id")
        normalized = cleaned.strip().lower()
        if normalized in {"last", "--last", "latest", "--latest"}:
            raise ValueError(
                "provider_session_id must be explicit; "
                "last-session aliases are forbidden"
            )
        return cleaned

    @model_validator(mode="after")
    def _validate_resume_contract(self) -> ProviderSessionBindingRecord:
        if self.resume_command_template is not None:
            normalized = self.resume_command_template.lower()
            if "--last" in normalized or " --latest" in normalized:
                raise ValueError(
                    "resume_command_template must not use --last "
                    "or latest-session aliases"
                )
        created_at = _parse_timezone_timestamp(self.created_at, "created_at")
        if self.last_used_at is not None:
            last_used_at = _parse_timezone_timestamp(self.last_used_at, "last_used_at")
            if last_used_at < created_at:
                raise ValueError("last_used_at must not be earlier than created_at")
        if self.last_verified_at is not None:
            last_verified_at = _parse_timezone_timestamp(
                self.last_verified_at,
                "last_verified_at",
            )
            if last_verified_at < created_at:
                raise ValueError("last_verified_at must not be earlier than created_at")
        if self.status in {ProviderSessionBindingStatus.FAILED, ProviderSessionBindingStatus.STALE}:
            _require_optional_text(self.failure_reason, "failure_reason")
        return self


class LaneGraphEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_graph_id: str
    lane_count: int = Field(ge=0)
    ready_lane_ids: list[str] = Field(default_factory=list)
    completed_lane_ids: list[str] = Field(default_factory=list)
    blocked_lane_ids: list[str] = Field(default_factory=list)

    @field_validator("feature_graph_id")
    @classmethod
    def _validate_feature_graph_id(cls, value: str) -> str:
        return _require_text(value, "feature_graph_id")

    @field_validator("ready_lane_ids", "completed_lane_ids", "blocked_lane_ids")
    @classmethod
    def _validate_lane_ids(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)


class CommandEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    status: str
    evidence_ref: str | None = None

    @field_validator("command", "status")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_ref")
    @classmethod
    def _validate_evidence_ref(cls, value: str | None) -> str | None:
        return _require_optional_text(value, "evidence_ref")


class FeatureVerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands_run: list[str] = Field(default_factory=list)
    test_results: list[CommandEvidence] = Field(default_factory=list)
    lint_results: list[CommandEvidence] = Field(default_factory=list)
    screenshots_or_logs: list[str] = Field(default_factory=list)
    known_failures: list[str] = Field(default_factory=list)

    @field_validator("commands_run")
    @classmethod
    def _validate_commands_run(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "commands_run")

    @field_validator("screenshots_or_logs", "known_failures")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)


class FeatureWorkerNotes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    implementation_summary: str
    decisions_made: list[str] = Field(default_factory=list)
    risks_or_open_questions: list[str] = Field(default_factory=list)
    skipped_items_with_reason: list[str] = Field(default_factory=list)

    @field_validator("implementation_summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _require_text(value, "implementation_summary")

    @field_validator("decisions_made", "risks_or_open_questions", "skipped_items_with_reason")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)


class FeatureEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    conversation_id: str
    planning_run_id: str
    feature_plan_id: str
    feature_plan_version: int = Field(ge=1)
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    worker_session_id: str
    provider_session_binding_ref: str
    blueprint_refs: list[str]
    feature_goal: str
    acceptance_criteria: list[str]
    lane_graph_summary: LaneGraphEvidenceSummary
    touched_files: list[str] = Field(default_factory=list)
    base_head_sha: str | None = None
    branch: str | None = None
    worktree: str | None = None
    diff_ref: str | None = None
    patch_ref: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    dependency_changes: list[str] = Field(default_factory=list)
    verification: FeatureVerificationEvidence
    worker_notes: FeatureWorkerNotes
    created_at: str

    @field_validator(
        "bundle_id",
        "conversation_id",
        "planning_run_id",
        "feature_plan_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "worker_session_id",
        "provider_session_binding_ref",
        "feature_goal",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("blueprint_refs", "acceptance_criteria")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @field_validator("touched_files", "changed_files", "dependency_changes")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)

    @field_validator("base_head_sha", "branch", "worktree", "diff_ref", "patch_ref")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @model_validator(mode="after")
    def _validate_graph_identity(self) -> FeatureEvidenceBundle:
        if self.lane_graph_summary.feature_graph_id != self.feature_graph_id:
            raise ValueError("lane_graph_summary feature_graph_id must match feature_graph_id")
        return self


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str | None = None
    severity: str = "blocking"
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("finding_id")
    @classmethod
    def _validate_finding_id(cls, value: str | None) -> str | None:
        return _require_optional_text(value, "finding_id")

    @field_validator("severity", "summary")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _clean_text_list(value, "evidence_refs")


class AcceptanceCoverageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    status: str
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("criterion", "status")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _clean_text_list(value, "evidence_refs")


class ReviewScopeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diff_scope: str
    touched_files: list[str] = Field(default_factory=list)
    unexpected_files: list[str] = Field(default_factory=list)
    public_contract_changed: bool = False
    new_dependency_added: bool = False

    @field_validator("diff_scope")
    @classmethod
    def _validate_diff_scope(cls, value: str) -> str:
        return _require_text(value, "diff_scope")

    @field_validator("touched_files", "unexpected_files")
    @classmethod
    def _validate_file_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)


class MergeGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acceptance_coverage_ref: str
    diff_scope_ref: str
    verification_ref: str
    merge_guard_ref: str

    @field_validator(
        "acceptance_coverage_ref",
        "diff_scope_ref",
        "verification_ref",
        "merge_guard_ref",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)


class PatchForwardGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk: str
    reason_not_rework: str
    allowed_file_refs: list[str]
    max_files_changed: int = Field(ge=1)
    max_lines_changed: int = Field(ge=1)
    focused_gates_to_rerun: list[str]
    disallow_new_dependencies: bool = True
    disallow_public_contract_changes: bool = True

    @field_validator("risk", "reason_not_rework")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("allowed_file_refs", "focused_gates_to_rerun")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_patch_forward_limits(self) -> PatchForwardGate:
        if self.risk != "low":
            raise ValueError("patch_forward requires low risk")
        if not self.disallow_new_dependencies:
            raise ValueError("patch_forward must disallow new dependencies")
        if not self.disallow_public_contract_changes:
            raise ValueError("patch_forward must disallow public contract changes")
        return self


class FeatureReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_id: str
    evidence_bundle_id: str
    decision: FeatureReviewDecision
    summary: str
    blocking_findings: list[ReviewFinding] = Field(default_factory=list)
    non_blocking_findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str]
    acceptance_coverage: list[AcceptanceCoverageItem]
    scope_assessment: ReviewScopeAssessment
    required_gates_before_merge: list[str] = Field(default_factory=list)
    merge_gate_evidence: MergeGateEvidence | None = None
    patch_forward_gate: PatchForwardGate | None = None
    reviewer_session_id: str
    takeover_reason: str | None = None
    takeover_triggers: list[FeatureGraphTakeoverTrigger] = Field(default_factory=list)
    blocked_missing_inputs: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    blocked_owner: str | None = None
    created_at: str | None = None

    @field_validator("verdict_id", "evidence_bundle_id", "summary", "reviewer_session_id")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_refs", "acceptance_coverage")
    @classmethod
    def _validate_required_lists(cls, value: list[Any], info: Any) -> list[Any]:
        if not value:
            raise ValueError(f"{info.field_name} must contain at least one item")
        return value

    @field_validator(
        "non_blocking_findings",
        "required_gates_before_merge",
        "blocked_missing_inputs",
    )
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)

    @field_validator("takeover_triggers")
    @classmethod
    def _validate_takeover_triggers(
        cls,
        value: list[FeatureGraphTakeoverTrigger],
    ) -> list[FeatureGraphTakeoverTrigger]:
        if len(set(value)) != len(value):
            raise ValueError("takeover_triggers must not contain duplicates")
        return value

    @field_validator("takeover_reason", "blocked_reason", "blocked_owner", "created_at")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _validate_timestamp(value, info.field_name)

    @model_validator(mode="after")
    def _validate_decision_gates(self) -> FeatureReviewVerdict:
        if self.decision is FeatureReviewDecision.MERGE:
            if self.blocking_findings:
                raise ValueError("merge verdicts must not include blocking findings")
            if self.merge_gate_evidence is None:
                raise ValueError("merge verdicts require merge_gate_evidence")
            if not self.required_gates_before_merge:
                raise ValueError("merge verdicts require required_gates_before_merge")
        if self.decision is FeatureReviewDecision.REWORK and not self.blocking_findings:
            raise ValueError("rework verdicts require blocking_findings")
        if self.decision is FeatureReviewDecision.PATCH_FORWARD:
            if self.patch_forward_gate is None:
                raise ValueError("patch_forward requires patch_forward_gate")
            if self.blocking_findings:
                raise ValueError("patch_forward must not include core blocking findings")
        if self.decision is FeatureReviewDecision.TAKEOVER:
            _require_optional_text(self.takeover_reason, "takeover_reason")
            if not self.takeover_triggers:
                raise ValueError("takeover verdicts require takeover_triggers")
        if self.decision is FeatureReviewDecision.BLOCKED:
            if not self.blocked_missing_inputs:
                raise ValueError("blocked verdicts require blocked_missing_inputs")
            _require_optional_text(self.blocked_reason, "blocked_reason")
            _require_optional_text(self.blocked_owner, "blocked_owner")
        return self


class ReworkPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rework_id: str
    source_verdict_id: str
    evidence_bundle_id: str
    target_worker_session_id: str | None = None
    target_provider_session_binding_ref: str | None = None
    blocking_findings: list[ReviewFinding]
    required_changes: list[str]
    forbidden_changes: list[str] = Field(default_factory=list)
    evidence_refs: list[str]
    files_or_areas_to_revisit: list[str]
    gates_to_rerun: list[str]
    max_remaining_attempts: int = Field(ge=0)
    return_requirements: list[str]
    created_at: str | None = None

    @field_validator("rework_id", "source_verdict_id", "evidence_bundle_id")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "target_worker_session_id",
        "target_provider_session_binding_ref",
        "created_at",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator(
        "blocking_findings",
        "required_changes",
        "evidence_refs",
        "files_or_areas_to_revisit",
        "gates_to_rerun",
        "return_requirements",
    )
    @classmethod
    def _validate_required_lists(cls, value: list[Any], info: Any) -> list[Any]:
        if not value:
            raise ValueError(f"{info.field_name} must contain at least one item")
        if all(isinstance(item, str) for item in value):
            return _require_text_list(value, info.field_name)
        return value

    @field_validator("forbidden_changes")
    @classmethod
    def _validate_forbidden_changes(cls, value: list[str]) -> list[str]:
        return _clean_text_list(value, "forbidden_changes")

    @model_validator(mode="after")
    def _validate_target_session(self) -> ReworkPacket:
        if (
            self.target_worker_session_id is None
            and self.target_provider_session_binding_ref is None
        ):
            raise ValueError(
                "rework packet requires target_worker_session_id or "
                "target_provider_session_binding_ref"
            )
        return self


class FeatureGraphPatchForwardPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    current_status: FeatureGraphExecutionStatus
    expected_status: FeatureGraphExecutionStatus
    reviewer_session_id: str
    rationale: str
    risk: str
    reason_not_rework: str
    allowed_file_refs: list[str]
    max_files_changed: int = Field(ge=1)
    max_lines_changed: int = Field(ge=1)
    focused_gates_to_rerun: list[str]
    disallow_new_dependencies: bool = True
    disallow_public_contract_changes: bool = True
    evidence_refs: list[str]
    created_at: str

    @field_validator(
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "reviewer_session_id",
        "rationale",
        "risk",
        "reason_not_rework",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("allowed_file_refs", "focused_gates_to_rerun", "evidence_refs")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_patch_forward_gate(self) -> FeatureGraphPatchForwardPlan:
        if self.current_status is not self.expected_status:
            raise ValueError("current_status must match expected_status")
        if self.expected_status is not FeatureGraphExecutionStatus.REVIEWING:
            raise ValueError("patch-forward plans require reviewing status")
        if self.risk != "low":
            raise ValueError("patch-forward plans require low risk")
        if not self.disallow_new_dependencies:
            raise ValueError("patch-forward plans must disallow new dependencies")
        if not self.disallow_public_contract_changes:
            raise ValueError("patch-forward plans must disallow public contract changes")
        return self


class FeatureGraphPatchForwardGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: str
    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    reviewer_session_id: str
    changed_file_refs: list[str]
    lines_changed: int = Field(ge=0)
    focused_gates_rerun: list[str]
    focused_gate_evidence_refs: list[str]
    patch_diff_ref: str
    verification_summary: str
    introduced_dependency_refs: list[str] = Field(default_factory=list)
    public_contract_change_refs: list[str] = Field(default_factory=list)
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
    created_at: str

    @field_validator(
        "result_id",
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "reviewer_session_id",
        "patch_diff_ref",
        "verification_summary",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "changed_file_refs",
        "focused_gates_rerun",
        "focused_gate_evidence_refs",
    )
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @field_validator(
        "introduced_dependency_refs",
        "public_contract_change_refs",
        "failure_reasons",
    )
    @classmethod
    def _validate_optional_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_gate_result(self) -> FeatureGraphPatchForwardGateResult:
        if self.passed and self.failure_reasons:
            raise ValueError("passed patch-forward gate results must not include failure_reasons")
        if not self.passed and not self.failure_reasons:
            raise ValueError("failed patch-forward gate results require failure_reasons")
        return self


class FeatureGraphPatchForwardMergeGuardHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    plan_id: str
    gate_result_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    reviewer_session_id: str
    patch_diff_ref: str
    focused_gate_evidence_refs: list[str]
    merge_guard_input_refs: list[str]
    required_merge_guard_checks: list[str]
    created_at: str

    @field_validator(
        "handoff_id",
        "plan_id",
        "gate_result_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "reviewer_session_id",
        "patch_diff_ref",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "focused_gate_evidence_refs",
        "merge_guard_input_refs",
        "required_merge_guard_checks",
    )
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)


class FeatureGraphPatchForwardMergeGuardDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    handoff_id: str
    gate_result_id: str
    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    merge_guard_ref: str
    merge_guard_evidence_refs: list[str]
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
    checked_at: str

    @field_validator(
        "decision_id",
        "handoff_id",
        "gate_result_id",
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "merge_guard_ref",
        "checked_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("merge_guard_evidence_refs")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @field_validator("failure_reasons")
    @classmethod
    def _validate_optional_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_decision(self) -> FeatureGraphPatchForwardMergeGuardDecision:
        if self.passed and self.failure_reasons:
            raise ValueError("passed patch-forward merge guard decisions must not fail")
        if not self.passed and not self.failure_reasons:
            raise ValueError("failed patch-forward merge guard decisions require reasons")
        return self


class FeatureGraphBlockedReviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    current_status: FeatureGraphExecutionStatus
    expected_status: FeatureGraphExecutionStatus
    target_status: FeatureGraphExecutionStatus
    reviewer_session_id: str
    rationale: str
    missing_inputs: list[str]
    blocked_reason: str
    blocked_owner: str
    evidence_refs: list[str]
    created_at: str

    @field_validator(
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "reviewer_session_id",
        "rationale",
        "blocked_reason",
        "blocked_owner",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("missing_inputs", "evidence_refs")
    @classmethod
    def _validate_required_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_blocked_review_plan(self) -> FeatureGraphBlockedReviewPlan:
        if self.current_status is not self.expected_status:
            raise ValueError("current_status must match expected_status")
        if self.expected_status is not FeatureGraphExecutionStatus.REVIEWING:
            raise ValueError("blocked review plans require reviewing status")
        if self.target_status is not FeatureGraphExecutionStatus.BLOCKED:
            raise ValueError("blocked review plans target blocked status")
        return self


class FeatureGraphTakeoverPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    current_status: FeatureGraphExecutionStatus
    expected_status: FeatureGraphExecutionStatus
    reviewer_session_id: str
    takeover_reason: str
    takeover_triggers: list[FeatureGraphTakeoverTrigger]
    failed_worker_session_id: str
    failed_provider_session_binding_ref: str
    evidence_refs: list[str]
    created_at: str

    @field_validator(
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "reviewer_session_id",
        "takeover_reason",
        "failed_worker_session_id",
        "failed_provider_session_binding_ref",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("takeover_triggers")
    @classmethod
    def _validate_takeover_triggers(
        cls,
        value: list[FeatureGraphTakeoverTrigger],
    ) -> list[FeatureGraphTakeoverTrigger]:
        if not value:
            raise ValueError("takeover_triggers must contain at least one item")
        if len(set(value)) != len(value):
            raise ValueError("takeover_triggers must not contain duplicates")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "evidence_refs")

    @model_validator(mode="after")
    def _validate_takeover_plan(self) -> FeatureGraphTakeoverPlan:
        if self.current_status is not self.expected_status:
            raise ValueError("current_status must match expected_status")
        if self.expected_status is not FeatureGraphExecutionStatus.REVIEWING:
            raise ValueError("takeover plans require reviewing status")
        return self


class FeatureGraphTakeoverDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    takeover_reason: str
    takeover_triggers: list[FeatureGraphTakeoverTrigger]
    approved: bool
    takeover_worker_session_id: str | None = None
    takeover_provider_session_binding_ref: str | None = None
    gate_refs: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    checked_at: str

    @field_validator(
        "decision_id",
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "takeover_reason",
        "checked_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "takeover_worker_session_id",
        "takeover_provider_session_binding_ref",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("takeover_triggers")
    @classmethod
    def _validate_takeover_triggers(
        cls,
        value: list[FeatureGraphTakeoverTrigger],
    ) -> list[FeatureGraphTakeoverTrigger]:
        if not value:
            raise ValueError("takeover_triggers must contain at least one item")
        if len(set(value)) != len(value):
            raise ValueError("takeover_triggers must not contain duplicates")
        return value

    @field_validator("gate_refs", "failure_reasons")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_decision(self) -> FeatureGraphTakeoverDecision:
        if self.approved:
            if self.takeover_worker_session_id is None:
                raise ValueError("approved takeover decisions require takeover_worker_session_id")
            if self.takeover_provider_session_binding_ref is None:
                raise ValueError(
                    "approved takeover decisions require "
                    "takeover_provider_session_binding_ref"
                )
            if not self.gate_refs:
                raise ValueError("approved takeover decisions require gate_refs")
            if self.failure_reasons:
                raise ValueError("approved takeover decisions must not include failure_reasons")
            return self
        if not self.failure_reasons:
            raise ValueError("rejected takeover decisions require failure_reasons")
        if self.takeover_worker_session_id is not None:
            raise ValueError(
                "rejected takeover decisions must not include takeover_worker_session_id"
            )
        if self.takeover_provider_session_binding_ref is not None:
            raise ValueError(
                "rejected takeover decisions must not include "
                "takeover_provider_session_binding_ref"
            )
        return self


class FeatureGraphTakeoverHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    decision_id: str
    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    takeover_worker_session_id: str
    takeover_provider_session_binding_ref: str
    takeover_reason: str
    takeover_triggers: list[FeatureGraphTakeoverTrigger]
    gate_refs: list[str]
    takeover_input_refs: list[str]
    required_takeover_checks: list[str]
    created_at: str

    @field_validator(
        "handoff_id",
        "decision_id",
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "takeover_worker_session_id",
        "takeover_provider_session_binding_ref",
        "takeover_reason",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("takeover_triggers")
    @classmethod
    def _validate_takeover_triggers(
        cls,
        value: list[FeatureGraphTakeoverTrigger],
    ) -> list[FeatureGraphTakeoverTrigger]:
        if not value:
            raise ValueError("takeover_triggers must contain at least one item")
        if len(set(value)) != len(value):
            raise ValueError("takeover_triggers must not contain duplicates")
        return value

    @field_validator("gate_refs", "takeover_input_refs", "required_takeover_checks")
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)


class FeatureGraphTakeoverOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_id: str
    handoff_id: str
    decision_id: str
    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    takeover_worker_session_id: str
    takeover_provider_session_binding_ref: str
    changed_file_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    output_summary: str
    completed: bool
    failure_reasons: list[str] = Field(default_factory=list)
    created_at: str

    @field_validator(
        "outcome_id",
        "handoff_id",
        "decision_id",
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "takeover_worker_session_id",
        "takeover_provider_session_binding_ref",
        "output_summary",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "changed_file_refs",
        "evidence_refs",
        "verification_refs",
        "failure_reasons",
    )
    @classmethod
    def _validate_text_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_outcome_shape(self) -> FeatureGraphTakeoverOutcome:
        if self.completed:
            if not self.evidence_refs:
                raise ValueError("completed takeover outcomes require evidence_refs")
            if not self.verification_refs:
                raise ValueError("completed takeover outcomes require verification_refs")
            if self.failure_reasons:
                raise ValueError("completed takeover outcomes must not include failure_reasons")
            return self
        if not self.failure_reasons:
            raise ValueError("failed takeover outcomes require failure_reasons")
        return self


class FeatureGraphTakeoverReviewHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_handoff_id: str
    outcome_id: str
    takeover_handoff_id: str
    decision_id: str
    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    takeover_worker_session_id: str
    takeover_provider_session_binding_ref: str
    changed_file_refs: list[str]
    evidence_refs: list[str]
    verification_refs: list[str]
    reviewer_input_refs: list[str]
    required_review_checks: list[str]
    created_at: str

    @field_validator(
        "review_handoff_id",
        "outcome_id",
        "takeover_handoff_id",
        "decision_id",
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "takeover_worker_session_id",
        "takeover_provider_session_binding_ref",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "changed_file_refs",
        "evidence_refs",
        "verification_refs",
        "reviewer_input_refs",
        "required_review_checks",
    )
    @classmethod
    def _validate_required_lists(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)


class ProviderSessionBindingDegradationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    reason: str
    evidence_refs: list[str]
    failure: str | None = None

    @field_validator("binding_id", "reason")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "evidence_refs")

    @field_validator("failure")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)


class FeatureGraphExecutionStatusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_id: str
    conversation_id: str
    planning_run_id: str | None = None
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_plan_id: str
    feature_plan_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    status: FeatureGraphExecutionStatus
    ready_lane_ids: list[str] = Field(default_factory=list)
    active_lane_ids: list[str] = Field(default_factory=list)
    active_worker_session_id: str | None = None
    active_provider_session_binding_ref: str | None = None
    completed_lane_ids: list[str] = Field(default_factory=list)
    blocked_lane_ids: list[str] = Field(default_factory=list)
    projection_lane_ids: list[str] = Field(default_factory=list)
    feature_lanes_projection_ref: str | None = None
    provider_session_binding_degradations: list[
        ProviderSessionBindingDegradationEvidence
    ] = Field(default_factory=list)
    updated_at: str

    @field_validator(
        "status_id",
        "conversation_id",
        "graph_set_id",
        "feature_plan_id",
        "feature_id",
        "feature_graph_id",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        field_name = "graph_set_id" if info.field_name == "graph_set_id" else info.field_name
        try:
            return _require_text(value, field_name)
        except ValueError as exc:
            if info.field_name == "graph_set_id":
                raise ValueError("feature graph status must identify graph_set_id") from exc
            raise

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: str) -> str:
        return _require_timezone_timestamp(value, "updated_at")

    @field_validator(
        "planning_run_id",
        "active_worker_session_id",
        "active_provider_session_binding_ref",
        "feature_lanes_projection_ref",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator(
        "ready_lane_ids",
        "active_lane_ids",
        "completed_lane_ids",
        "blocked_lane_ids",
        "projection_lane_ids",
    )
    @classmethod
    def _validate_lane_lists(cls, value: list[str], info: Any) -> list[str]:
        return _clean_text_list(value, info.field_name)


class FeatureGraphStatusEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_graph_id: str
    feature_id: str
    from_status: FeatureGraphExecutionStatus | None = None
    to_status: FeatureGraphExecutionStatus
    from_status_id: str | None = None
    status_id: str
    updated_at: str
    idempotency_key: str

    @field_validator(
        "event_id",
        "event_type",
        "graph_set_id",
        "feature_graph_id",
        "feature_id",
        "status_id",
        "idempotency_key",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: str) -> str:
        return _require_timezone_timestamp(value, "updated_at")

    @field_validator("from_status_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        if value not in {
            "feature_graph_status.initialized",
            "feature_graph_status.provider_session_binding_degraded",
            "feature_graph_status.transitioned",
        }:
            raise ValueError("event_type must be a feature graph status event")
        return value

    @model_validator(mode="after")
    def _validate_status_direction(self) -> FeatureGraphStatusEventRecord:
        if self.event_type == "feature_graph_status.initialized":
            if self.from_status is not None or self.from_status_id is not None:
                raise ValueError("initialized events must not have from_status")
            expected_event_id = (
                "fgse:initialized:"
                f"{self.graph_set_id}:{self.feature_graph_id}:{self.status_id}"
            )
            if self.event_id != expected_event_id:
                raise ValueError("initialized event_id must match status identity")
            expected_key = (
                "feature_graph_status.initialized:"
                f"{self.graph_set_id}:{self.feature_graph_id}:{self.status_id}"
            )
            if self.idempotency_key != expected_key:
                raise ValueError(
                    "initialized event idempotency_key must match status identity"
                )
        if self.event_type == "feature_graph_status.transitioned":
            if self.from_status is None or self.from_status_id is None:
                raise ValueError("transitioned events require from_status")
            expected_event_id = (
                "fgse:transition:"
                f"{self.graph_set_id}:{self.feature_graph_id}:"
                f"{self.from_status_id}:{self.status_id}"
            )
            if self.event_id != expected_event_id:
                raise ValueError("transitioned event_id must match status identity")
            expected_key = (
                "feature_graph_status.transitioned:"
                f"{self.graph_set_id}:{self.feature_graph_id}:"
                f"{self.from_status_id}:{self.status_id}"
            )
            if self.idempotency_key != expected_key:
                raise ValueError(
                    "transitioned event idempotency_key must match status identity"
                )
        if self.event_type == "feature_graph_status.provider_session_binding_degraded":
            if self.from_status is None or self.from_status_id is None:
                raise ValueError(
                    "provider session binding degraded events require from_status"
                )
            if self.from_status is not self.to_status:
                raise ValueError(
                    "provider session binding degraded events must preserve status"
                )
            expected_key_prefix = (
                "feature_graph_status.provider_session_binding_degraded:"
                f"{self.graph_set_id}:{self.feature_graph_id}:"
            )
            if not self.idempotency_key.startswith(expected_key_prefix):
                raise ValueError(
                    "provider session binding degraded idempotency_key must match "
                    "status identity"
                )
            key_tail = self.idempotency_key.removeprefix(expected_key_prefix)
            key_parts = key_tail.split(":")
            if len(key_parts) < 2:
                raise ValueError(
                    "provider session binding degraded idempotency_key must include "
                    "binding and reason"
                )
            binding_id = ":".join(key_parts[:-1])
            reason = key_parts[-1]
            safe_binding_id = _safe_event_part(binding_id)
            expected_event_id = (
                "fgse:provider-session-binding-degraded:"
                f"{self.graph_set_id}:{self.feature_graph_id}:"
                f"{self.from_status_id}:{safe_binding_id}:{reason}"
            )
            if self.event_id != expected_event_id:
                raise ValueError(
                    "provider session binding degraded event_id must match evidence"
                )
            if not binding_id or not reason:
                raise ValueError(
                    "provider session binding degraded idempotency_key must match "
                    "evidence"
                )
        return self


class FeatureGraphReviewStatusTransitionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    verdict_id: str
    evidence_bundle_id: str
    decision: FeatureReviewDecision
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    current_status: FeatureGraphExecutionStatus
    expected_status: FeatureGraphExecutionStatus
    target_status: FeatureGraphExecutionStatus | None = None
    coordinator_action: FeatureGraphReviewCoordinatorAction
    rationale: str
    evidence_refs: list[str]
    target_status_record: FeatureGraphExecutionStatusRecord | None = None
    updated_at: str

    @field_validator(
        "plan_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "rationale",
        "updated_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "evidence_refs")

    @model_validator(mode="after")
    def _validate_transition_shape(self) -> FeatureGraphReviewStatusTransitionPlan:
        if self.current_status is not self.expected_status:
            raise ValueError("current_status must match expected_status")
        if self.expected_status is not FeatureGraphExecutionStatus.REVIEWING:
            raise ValueError("review transition plans require reviewing status")
        if self.coordinator_action is FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS:
            target_status_by_decision = {
                FeatureReviewDecision.MERGE: FeatureGraphExecutionStatus.MERGED,
                FeatureReviewDecision.REWORK: FeatureGraphExecutionStatus.REWORKING,
                FeatureReviewDecision.BLOCKED: FeatureGraphExecutionStatus.BLOCKED,
            }
            expected_target_status = target_status_by_decision.get(self.decision)
            if expected_target_status is None:
                raise ValueError(
                    "transition_status action requires merge, rework, or blocked decision"
                )
            if self.target_status is not expected_target_status:
                raise ValueError("target_status must match review decision")
            if self.target_status is None or self.target_status_record is None:
                raise ValueError("transition plans require target_status_record")
            if self.target_status_record.status is not self.target_status:
                raise ValueError("target_status_record status must match target_status")
            if self.target_status_record.graph_set_id != self.graph_set_id:
                raise ValueError("target_status_record graph_set_id must match plan")
            if self.target_status_record.graph_set_version != self.graph_set_version:
                raise ValueError("target_status_record graph_set_version must match plan")
            if self.target_status_record.feature_id != self.feature_id:
                raise ValueError("target_status_record feature_id must match plan")
            if self.target_status_record.feature_graph_id != self.feature_graph_id:
                raise ValueError("target_status_record feature_graph_id must match plan")
            if self.target_status_record.updated_at != self.updated_at:
                raise ValueError("target_status_record updated_at must match plan")
        else:
            if self.target_status is not None or self.target_status_record is not None:
                raise ValueError("non-transition review actions must not carry target status")
        if (
            self.coordinator_action is FeatureGraphReviewCoordinatorAction.PATCH_FORWARD_GATE
            and self.decision is not FeatureReviewDecision.PATCH_FORWARD
        ):
            raise ValueError("patch_forward_gate action requires patch_forward decision")
        if (
            self.coordinator_action is FeatureGraphReviewCoordinatorAction.TAKEOVER_REQUIRED
            and self.decision is not FeatureReviewDecision.TAKEOVER
        ):
            raise ValueError("takeover_required action requires takeover decision")
        return self


class FeatureGraphTakeoverFollowupReviewApplicationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: str
    review_handoff_id: str
    verdict_id: str
    evidence_bundle_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    decision: FeatureReviewDecision
    coordinator_action: FeatureGraphReviewCoordinatorAction
    review_plan: FeatureGraphReviewStatusTransitionPlan
    applied_status: FeatureGraphExecutionStatusRecord | None = None
    rework_id: str | None = None
    patch_forward_plan_id: str | None = None
    blocked_review_plan_id: str | None = None
    takeover_plan_id: str | None = None
    input_refs: list[str]
    output_refs: list[str]
    applied_at: str
    idempotency_key: str

    @field_validator(
        "application_id",
        "review_handoff_id",
        "verdict_id",
        "evidence_bundle_id",
        "graph_set_id",
        "feature_id",
        "feature_graph_id",
        "applied_at",
        "idempotency_key",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator(
        "rework_id",
        "patch_forward_plan_id",
        "blocked_review_plan_id",
        "takeover_plan_id",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("input_refs", "output_refs")
    @classmethod
    def _validate_refs(cls, value: list[str], info: Any) -> list[str]:
        return _require_text_list(value, info.field_name)

    @model_validator(mode="after")
    def _validate_application_shape(
        self,
    ) -> FeatureGraphTakeoverFollowupReviewApplicationRecord:
        if self.review_plan.verdict_id != self.verdict_id:
            raise ValueError("review_plan verdict_id must match application")
        if self.review_plan.evidence_bundle_id != self.evidence_bundle_id:
            raise ValueError("review_plan evidence_bundle_id must match application")
        if self.review_plan.graph_set_id != self.graph_set_id:
            raise ValueError("review_plan graph_set_id must match application")
        if self.review_plan.graph_set_version != self.graph_set_version:
            raise ValueError("review_plan graph_set_version must match application")
        if self.review_plan.feature_id != self.feature_id:
            raise ValueError("review_plan feature_id must match application")
        if self.review_plan.feature_graph_id != self.feature_graph_id:
            raise ValueError("review_plan feature_graph_id must match application")
        if self.review_plan.decision is not self.decision:
            raise ValueError("review_plan decision must match application")
        if self.review_plan.coordinator_action is not self.coordinator_action:
            raise ValueError("review_plan coordinator_action must match application")
        if self.coordinator_action is FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS:
            if self.applied_status is None:
                raise ValueError("transition applications require applied_status")
            if self.review_plan.target_status_record is None:
                raise ValueError("transition applications require target_status_record")
            if self.applied_status.status_id != self.review_plan.target_status_record.status_id:
                raise ValueError("applied_status status_id must match review_plan")
        elif self.applied_status is not None:
            raise ValueError("non-transition applications must not carry applied_status")
        if self.decision is FeatureReviewDecision.REWORK and self.rework_id is None:
            raise ValueError("rework applications require rework_id")
        if (
            self.decision is not FeatureReviewDecision.REWORK
            and self.rework_id is not None
        ):
            raise ValueError("non-rework applications must not carry rework_id")
        if (
            self.decision is FeatureReviewDecision.PATCH_FORWARD
            and self.patch_forward_plan_id is None
        ):
            raise ValueError("patch_forward applications require patch_forward_plan_id")
        if (
            self.decision is not FeatureReviewDecision.PATCH_FORWARD
            and self.patch_forward_plan_id is not None
        ):
            raise ValueError(
                "non-patch_forward applications must not carry patch_forward_plan_id"
            )
        if (
            self.decision is FeatureReviewDecision.BLOCKED
            and self.blocked_review_plan_id is None
        ):
            raise ValueError("blocked applications require blocked_review_plan_id")
        if (
            self.decision is not FeatureReviewDecision.BLOCKED
            and self.blocked_review_plan_id is not None
        ):
            raise ValueError(
                "non-blocked applications must not carry blocked_review_plan_id"
            )
        if self.decision is FeatureReviewDecision.TAKEOVER and self.takeover_plan_id is None:
            raise ValueError("takeover applications require takeover_plan_id")
        if (
            self.decision is not FeatureReviewDecision.TAKEOVER
            and self.takeover_plan_id is not None
        ):
            raise ValueError("non-takeover applications must not carry takeover_plan_id")
        _require_ref(
            self.input_refs,
            f"feature_graph_takeover_review_handoff:{self.review_handoff_id}:v1",
            "input_refs",
        )
        _require_ref(
            self.input_refs,
            f"feature_review_verdict:{self.verdict_id}:v1",
            "input_refs",
        )
        _require_ref(
            self.input_refs,
            f"feature_evidence_bundle:{self.evidence_bundle_id}:v1",
            "input_refs",
        )
        _require_ref(
            self.output_refs,
            f"feature_graph_review_status_transition_plan:{self.review_plan.plan_id}:v1",
            "output_refs",
        )
        if self.applied_status is not None:
            _require_ref(
                self.output_refs,
                f"feature_graph_status:{self.applied_status.status_id}:v1",
                "output_refs",
            )
        if self.rework_id is not None:
            _require_ref(
                self.output_refs,
                f"feature_graph_rework_packet:{self.rework_id}:v1",
                "output_refs",
            )
        if self.patch_forward_plan_id is not None:
            _require_ref(
                self.output_refs,
                f"feature_graph_patch_forward_plan:{self.patch_forward_plan_id}:v1",
                "output_refs",
            )
        if self.blocked_review_plan_id is not None:
            _require_ref(
                self.output_refs,
                f"feature_graph_blocked_review_plan:{self.blocked_review_plan_id}:v1",
                "output_refs",
            )
        if self.takeover_plan_id is not None:
            _require_ref(
                self.output_refs,
                f"feature_graph_takeover_plan:{self.takeover_plan_id}:v1",
                "output_refs",
            )
        return self


class FeatureGraphWorkerClaimPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_plan_id: str
    feature_plan_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    current_status: FeatureGraphExecutionStatus
    expected_status: FeatureGraphExecutionStatus
    target_status: FeatureGraphExecutionStatus
    worker_session_id: str
    provider_session_binding_ref: str | None = None
    active_lane_ids: list[str]
    source_status_id: str
    updated_at: str

    @field_validator(
        "plan_id",
        "graph_set_id",
        "feature_plan_id",
        "feature_id",
        "feature_graph_id",
        "worker_session_id",
        "source_status_id",
        "updated_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("provider_session_binding_ref")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("active_lane_ids")
    @classmethod
    def _validate_active_lane_ids(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "active_lane_ids")

    @model_validator(mode="after")
    def _validate_worker_claim_shape(self) -> FeatureGraphWorkerClaimPlan:
        if self.current_status is not self.expected_status:
            raise ValueError("current_status must match expected_status")
        if self.expected_status is not FeatureGraphExecutionStatus.READY:
            raise ValueError("worker claim plans require ready status")
        if self.target_status is not FeatureGraphExecutionStatus.RUNNING:
            raise ValueError("worker claim plans target running status")
        return self


class FeatureGraphWorkerEvidenceSubmissionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    evidence_bundle_id: str
    evidence_bundle_ref: str
    graph_set_id: str
    graph_set_version: int = Field(ge=1)
    feature_plan_id: str
    feature_plan_version: int = Field(ge=1)
    feature_id: str
    feature_graph_id: str
    current_status: FeatureGraphExecutionStatus
    expected_status: FeatureGraphExecutionStatus
    target_status: FeatureGraphExecutionStatus
    worker_session_id: str
    provider_session_binding_ref: str
    source_status_id: str
    evidence_refs: list[str]
    target_status_record: FeatureGraphExecutionStatusRecord
    updated_at: str

    @field_validator(
        "plan_id",
        "evidence_bundle_id",
        "evidence_bundle_ref",
        "graph_set_id",
        "feature_plan_id",
        "feature_id",
        "feature_graph_id",
        "worker_session_id",
        "provider_session_binding_ref",
        "source_status_id",
        "updated_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[str]) -> list[str]:
        return _require_text_list(value, "evidence_refs")

    @model_validator(mode="after")
    def _validate_worker_evidence_submission_shape(
        self,
    ) -> FeatureGraphWorkerEvidenceSubmissionPlan:
        if self.current_status is not self.expected_status:
            raise ValueError("current_status must match expected_status")
        if self.expected_status is not FeatureGraphExecutionStatus.RUNNING:
            raise ValueError("worker evidence submission plans require running status")
        if self.target_status is not FeatureGraphExecutionStatus.REVIEWING:
            raise ValueError("worker evidence submission plans target reviewing status")
        if self.target_status_record.status is not FeatureGraphExecutionStatus.REVIEWING:
            raise ValueError("target_status_record status must be reviewing")
        if self.target_status_record.graph_set_id != self.graph_set_id:
            raise ValueError("target_status_record graph_set_id must match plan")
        if self.target_status_record.graph_set_version != self.graph_set_version:
            raise ValueError("target_status_record graph_set_version must match plan")
        if self.target_status_record.feature_plan_id != self.feature_plan_id:
            raise ValueError("target_status_record feature_plan_id must match plan")
        if self.target_status_record.feature_plan_version != self.feature_plan_version:
            raise ValueError("target_status_record feature_plan_version must match plan")
        if self.target_status_record.feature_id != self.feature_id:
            raise ValueError("target_status_record feature_id must match plan")
        if self.target_status_record.feature_graph_id != self.feature_graph_id:
            raise ValueError("target_status_record feature_graph_id must match plan")
        if self.target_status_record.active_worker_session_id != self.worker_session_id:
            raise ValueError("target_status_record active_worker_session_id must match plan")
        if (
            self.target_status_record.active_provider_session_binding_ref
            != self.provider_session_binding_ref
        ):
            raise ValueError(
                "target_status_record active_provider_session_binding_ref must match plan"
            )
        if self.target_status_record.updated_at != self.updated_at:
            raise ValueError("target_status_record updated_at must match plan")
        return self
