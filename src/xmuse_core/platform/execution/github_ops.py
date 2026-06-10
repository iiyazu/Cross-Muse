from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeatureDraftPRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: str
    feature_ids: list[str] = Field(default_factory=list)
    title: str
    base_branch: str
    head_branch: str
    blueprint_refs: list[str] = Field(default_factory=list)
    lane_refs: list[str] = Field(default_factory=list)
    depends_on_lanes: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]
    evidence_bundle_refs: list[str] = Field(default_factory=list)
    review_evidence_bundle: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    memory_impact: str = "none"
    new_artifacts: list[str] = Field(default_factory=list)
    provider_changes: list[str] = Field(default_factory=list)
    gate_profile: str = "default"
    rollback_plan: str = "Revert the feature branch or patch-forward from review evidence."
    privacy_impact: str = "none"
    parent_pr: int | str | None = None

    @field_validator("feature_id", "title", "base_branch", "head_branch")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "blueprint_refs",
        "feature_ids",
        "lane_refs",
        "depends_on_lanes",
        "acceptance_criteria",
        "evidence_bundle_refs",
        "review_evidence_bundle",
        "memory_refs",
        "new_artifacts",
        "provider_changes",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        cleaned = [_require_non_empty(value) for value in values]
        if not cleaned and values is not None:
            return cleaned
        return cleaned

    @field_validator("memory_impact", "gate_profile", "rollback_plan", "privacy_impact")
    @classmethod
    def _validate_policy_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def _validate_acceptance_criteria(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("acceptance_criteria must contain at least one item")
        return values


class DraftPRRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    number: int
    feature_id: str
    title: str
    base_branch: str
    head_branch: str
    body: str
    draft: bool = True


class CheckStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["success", "failure", "pending", "cancelled", "skipped"]

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value)


class MergeReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    merge_ready: bool
    reason: str
    failing_checks: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class WorkerOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["completed", "blocked", "failed"]
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)


class ReviewOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["approved", "changes_requested", "failed"]
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)


class FakeGitHubOps:
    """In-memory fake for feature-level Draft PR operations."""

    def __init__(self) -> None:
        self._records_by_feature: dict[str, DraftPRRecord] = {}
        self._next_number = 1

    def create_or_update_feature_draft_pr(
        self,
        request: FeatureDraftPRRequest,
    ) -> DraftPRRecord:
        existing = self._records_by_feature.get(request.feature_id)
        number = existing.number if existing is not None else self._next_number
        if existing is None:
            self._next_number += 1
        record = DraftPRRecord(
            number=number,
            feature_id=request.feature_id,
            title=request.title,
            base_branch=request.base_branch,
            head_branch=request.head_branch,
            body=render_feature_draft_pr_body(request),
            draft=True,
        )
        self._records_by_feature[request.feature_id] = record
        return record

    def get_feature_pr(self, feature_id: str) -> DraftPRRecord | None:
        return self._records_by_feature.get(feature_id)


def render_feature_draft_pr_body(request: FeatureDraftPRRequest) -> str:
    lines = [
        f"# {request.title}",
        "",
        f"Feature: `{request.feature_id}`",
        f"Base: `{request.base_branch}`",
        f"Head: `{request.head_branch}`",
    ]
    if request.parent_pr is not None:
        lines.append(f"Parent PR: #{request.parent_pr}")
    lines.append("")
    _append_section(lines, "Blueprint Refs", request.blueprint_refs)
    _append_section(lines, "Feature IDs", _feature_ids(request))
    _append_section(lines, "Lane IDs", request.lane_refs)
    _append_section(lines, "Depends On Lanes", request.depends_on_lanes)
    _append_section(lines, "Acceptance Criteria", request.acceptance_criteria, code=False)
    _append_section(lines, "Evidence Bundle", request.evidence_bundle_refs)
    _append_section(lines, "Review Evidence Bundle", request.review_evidence_bundle)
    _append_section(lines, "Memory Refs", request.memory_refs)
    _append_text_section(lines, "Memory Impact", request.memory_impact)
    _append_section(lines, "New Artifacts", request.new_artifacts)
    _append_section(lines, "Provider Changes", request.provider_changes, code=False)
    _append_text_section(lines, "Gate Profile", request.gate_profile)
    _append_text_section(lines, "Rollback Plan", request.rollback_plan)
    _append_text_section(lines, "Privacy Impact", request.privacy_impact)
    return "\n".join(lines).rstrip() + "\n"


def evaluate_merge_readiness(
    checks: list[CheckStatus],
    *,
    review_evidence_refs: list[str] | None = None,
    required_check_names: list[str] | None = None,
) -> MergeReadiness:
    failing = sorted(check.name for check in checks if check.status != "success")
    observed_checks = {check.name for check in checks}
    if required_check_names is not None:
        failing.extend(
            name for name in sorted(required_check_names) if name not in observed_checks
        )
        failing = sorted(set(failing))
    missing_evidence = [] if review_evidence_refs else ["review_evidence_bundle"]
    if failing:
        reason = "required checks not passing: " + ", ".join(failing)
        if missing_evidence:
            reason += "; missing review evidence"
        return MergeReadiness(
            merge_ready=False,
            reason=reason,
            failing_checks=failing,
            missing_evidence=missing_evidence,
        )
    if missing_evidence:
        return MergeReadiness(
            merge_ready=False,
            reason="missing review evidence",
            missing_evidence=missing_evidence,
        )
    return MergeReadiness(merge_ready=True, reason="required checks and review evidence present")


def apply_worker_outcome(lane: dict[str, object], outcome: WorkerOutcome) -> dict[str, object]:
    updated = dict(lane)
    if outcome.status == "completed":
        updated["status"] = "under_review"
    elif outcome.status == "blocked":
        updated["status"] = "blocked"
        updated["blocker_reason"] = "worker_blocked"
    else:
        updated["status"] = "blocked"
        updated["blocker_reason"] = "worker_failed"
    updated["worker_summary"] = outcome.summary
    updated["worker_evidence_refs"] = list(outcome.evidence_refs)
    return updated


def apply_review_outcome(lane: dict[str, object], outcome: ReviewOutcome) -> dict[str, object]:
    updated = dict(lane)
    if outcome.verdict == "approved":
        updated["status"] = "merge_ready"
    elif outcome.verdict == "changes_requested":
        updated["status"] = "patch_forward"
        updated["review_required_fix"] = outcome.summary
    else:
        updated["status"] = "blocked"
        updated["blocker_reason"] = "review_failed"
    updated["review_summary"] = outcome.summary
    updated["review_evidence_refs"] = list(outcome.evidence_refs)
    return updated


def _append_section(
    lines: list[str],
    title: str,
    values: list[str],
    *,
    code: bool = True,
) -> None:
    lines.extend([f"## {title}", ""])
    if values:
        lines.extend(f"- `{value}`" if code else f"- {value}" for value in values)
    else:
        lines.append("- None")
    lines.append("")


def _append_text_section(lines: list[str], title: str, value: str) -> None:
    lines.extend([f"## {title}", "", value, ""])


def _feature_ids(request: FeatureDraftPRRequest) -> list[str]:
    return _dedupe([request.feature_id, *request.feature_ids])


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
