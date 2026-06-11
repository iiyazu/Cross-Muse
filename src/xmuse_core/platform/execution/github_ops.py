from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from fnmatch import fnmatchcase
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class GitHubServerSideTruthEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repo: str
    pull_request_number: int
    required_checks: list[str] = Field(default_factory=list)
    proof_level: Literal["manual_gap", "contract_proof", "server_side_merge_proof"] = (
        "manual_gap"
    )
    workflow_run_id: int | None = None
    check_suite_id: int | None = None
    check_run_ids: list[int] = Field(default_factory=list)
    expected_source_app: str | None = None
    branch_protection_snapshot: dict[str, Any] | None = None
    ruleset_snapshot: dict[str, Any] | None = None
    review_event_id: int | str | None = None
    reviewer_login: str | None = None
    code_owner_review_verified: bool = False
    merge_commit_sha: str | None = None
    merged_at: str | None = None
    merge_event_id: int | str | None = None
    gap_reason: str | None = None

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("pull_request_number")
    @classmethod
    def _validate_pull_request_number(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("pull_request_number must be positive")
        return value

    @field_validator("required_checks")
    @classmethod
    def _validate_required_checks(cls, values: list[str]) -> list[str]:
        return [_require_non_empty(value) for value in values]

    @field_validator(
        "expected_source_app",
        "reviewer_login",
        "merge_commit_sha",
        "merged_at",
        "gap_reason",
    )
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @model_validator(mode="after")
    def _validate_server_side_merge_proof(self) -> GitHubServerSideTruthEvidence:
        if self.proof_level != "server_side_merge_proof":
            return self
        missing = []
        if not self.has_status_check_truth:
            missing.append("workflow_run_id/check_suite_id/check_run_ids/expected_source_app")
        if not self.has_server_enforcement_truth:
            missing.append("branch_protection_snapshot_or_ruleset_snapshot")
        if not self.has_review_truth:
            missing.append("review_event_id/reviewer_login/code_owner_review_verified")
        if not self.has_merge_truth:
            missing.append("merge_commit_sha/merged_at/merge_event_id")
        if missing:
            raise ValueError(
                "server_side_merge_proof missing required server-side fields: "
                + ", ".join(missing)
            )
        return self

    @property
    def has_status_check_truth(self) -> bool:
        return (
            self.workflow_run_id is not None
            and (self.check_suite_id is not None or bool(self.check_run_ids))
            and self.expected_source_app is not None
            and len(self.check_run_ids) >= len(self.required_checks)
        )

    @property
    def has_server_enforcement_truth(self) -> bool:
        return self.branch_protection_snapshot is not None or self.ruleset_snapshot is not None

    @property
    def has_review_truth(self) -> bool:
        return (
            self.review_event_id is not None
            and self.reviewer_login is not None
            and self.code_owner_review_verified
        )

    @property
    def has_merge_truth(self) -> bool:
        return (
            self.merge_commit_sha is not None
            and self.merged_at is not None
            and self.merge_event_id is not None
        )


class GitHubServerSideTruthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_run_id: int | None = None
    check_suite_id: int | None = None
    check_run_ids: list[int] = Field(default_factory=list)
    expected_source_app: str | None = None
    branch_protection_snapshot: dict[str, Any] | None = None
    ruleset_snapshot: dict[str, Any] | None = None
    review_event_id: int | str | None = None
    reviewer_login: str | None = None
    code_owner_review_verified: bool = False
    merge_commit_sha: str | None = None
    merged_at: str | None = None
    merge_event_id: int | str | None = None


class ReadOnlyGitHubServerSideTruthClient(Protocol):
    def fetch_server_side_truth_snapshot(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthSnapshot | None: ...


class ReadOnlyGitHubServerSideTruthCollector:
    def __init__(self, *, client: ReadOnlyGitHubServerSideTruthClient) -> None:
        self._client = client

    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence:
        snapshot = self._client.fetch_server_side_truth_snapshot(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
        )
        if snapshot is None:
            return build_github_server_side_truth_gap(
                repo=repo,
                pull_request_number=pull_request_number,
                required_checks=required_checks,
                reason="read-only GitHub server-side truth snapshot unavailable",
            )
        return build_github_server_side_truth_from_snapshot(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
            snapshot=snapshot,
        )


class GitHubCliServerSideTruthClient:
    def __init__(
        self,
        *,
        base_branch: str = "main",
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        gh_binary: str = "gh",
    ) -> None:
        self._base_branch = _require_non_empty(base_branch)
        self._runner = runner or _run_gh_api
        self._gh_binary = _require_non_empty(gh_binary)

    def fetch_server_side_truth_snapshot(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthSnapshot | None:
        repo = _require_non_empty(repo)
        pr_payload = self._gh_api(f"repos/{repo}/pulls/{pull_request_number}")
        if pr_payload is None:
            return None
        head_sha = _nested_str(pr_payload, "head", "sha")
        if head_sha is None:
            return None
        reviews_payload = self._gh_api(f"repos/{repo}/pulls/{pull_request_number}/reviews")
        protection_payload = self._gh_api(
            f"repos/{repo}/branches/{self._base_branch}/protection"
        )
        rulesets_payload = None
        if protection_payload is None:
            rulesets_payload = self._gh_api(f"repos/{repo}/rulesets")
        ruleset_snapshot = (
            {"rulesets": rulesets_payload} if isinstance(rulesets_payload, list) else None
        )
        checks_payload = self._gh_api(f"repos/{repo}/commits/{head_sha}/check-runs")
        if (
            reviews_payload is None
            or (protection_payload is None and ruleset_snapshot is None)
            or checks_payload is None
            or not isinstance(reviews_payload, list)
        ):
            return None
        check_run_ids, expected_source_app = _successful_required_check_runs(
            checks_payload,
            required_checks=required_checks,
        )
        review_event_id, reviewer_login = _approved_review_identity(reviews_payload)
        return GitHubServerSideTruthSnapshot(
            workflow_run_id=check_run_ids[0] if check_run_ids else None,
            check_run_ids=check_run_ids,
            expected_source_app=expected_source_app,
            branch_protection_snapshot=protection_payload,
            ruleset_snapshot=ruleset_snapshot,
            review_event_id=review_event_id,
            reviewer_login=reviewer_login,
            code_owner_review_verified=(
                _requires_code_owner_review(protection_payload)
                or _rulesets_require_code_owner_review(
                    ruleset_snapshot,
                    base_branch=self._base_branch,
                )
            )
            and review_event_id is not None,
            merge_commit_sha=_optional_str(pr_payload.get("merge_commit_sha")),
            merged_at=_optional_str(pr_payload.get("merged_at")),
            merge_event_id=_optional_str(pr_payload.get("node_id"))
            if pr_payload.get("merged") is True
            else None,
        )

    def _gh_api(self, endpoint: str) -> Any | None:
        result = self._runner([self._gh_binary, "api", endpoint])
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None


class FakeGitHubServerSideTruthCollector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_run_id: int | None = None
    check_suite_id: int | None = None
    check_run_ids: list[int] = Field(default_factory=list)
    expected_source_app: str | None = "fake-github"
    branch_protection_snapshot: dict[str, Any] | None = None
    ruleset_snapshot: dict[str, Any] | None = None
    review_event_id: int | str | None = None
    reviewer_login: str | None = None
    code_owner_review_verified: bool = False
    merge_commit_sha: str | None = None
    merged_at: str | None = None
    merge_event_id: int | str | None = None

    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence:
        return GitHubServerSideTruthEvidence(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
            proof_level="contract_proof",
            workflow_run_id=self.workflow_run_id,
            check_suite_id=self.check_suite_id,
            check_run_ids=list(self.check_run_ids),
            expected_source_app=self.expected_source_app,
            branch_protection_snapshot=self.branch_protection_snapshot,
            ruleset_snapshot=self.ruleset_snapshot,
            review_event_id=self.review_event_id,
            reviewer_login=self.reviewer_login,
            code_owner_review_verified=self.code_owner_review_verified,
        )


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


def build_github_server_side_truth_gap(
    *,
    repo: str,
    pull_request_number: int,
    required_checks: list[str],
    reason: str,
) -> GitHubServerSideTruthEvidence:
    return GitHubServerSideTruthEvidence(
        repo=repo,
        pull_request_number=pull_request_number,
        required_checks=required_checks,
        proof_level="manual_gap",
        gap_reason=reason,
    )


def build_github_server_side_truth_from_snapshot(
    *,
    repo: str,
    pull_request_number: int,
    required_checks: list[str],
    snapshot: GitHubServerSideTruthSnapshot,
) -> GitHubServerSideTruthEvidence:
    candidate = GitHubServerSideTruthEvidence.model_construct(
        repo=repo,
        pull_request_number=pull_request_number,
        required_checks=required_checks,
        proof_level="server_side_merge_proof",
        workflow_run_id=snapshot.workflow_run_id,
        check_suite_id=snapshot.check_suite_id,
        check_run_ids=list(snapshot.check_run_ids),
        expected_source_app=snapshot.expected_source_app,
        branch_protection_snapshot=snapshot.branch_protection_snapshot,
        ruleset_snapshot=snapshot.ruleset_snapshot,
        review_event_id=snapshot.review_event_id,
        reviewer_login=snapshot.reviewer_login,
        code_owner_review_verified=snapshot.code_owner_review_verified,
        merge_commit_sha=snapshot.merge_commit_sha,
        merged_at=snapshot.merged_at,
        merge_event_id=snapshot.merge_event_id,
        gap_reason=None,
    )
    if can_emit_pr_merged(candidate):
        return GitHubServerSideTruthEvidence(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
            proof_level="server_side_merge_proof",
            workflow_run_id=snapshot.workflow_run_id,
            check_suite_id=snapshot.check_suite_id,
            check_run_ids=list(snapshot.check_run_ids),
            expected_source_app=snapshot.expected_source_app,
            branch_protection_snapshot=snapshot.branch_protection_snapshot,
            ruleset_snapshot=snapshot.ruleset_snapshot,
            review_event_id=snapshot.review_event_id,
            reviewer_login=snapshot.reviewer_login,
            code_owner_review_verified=snapshot.code_owner_review_verified,
            merge_commit_sha=snapshot.merge_commit_sha,
            merged_at=snapshot.merged_at,
            merge_event_id=snapshot.merge_event_id,
        )
    return GitHubServerSideTruthEvidence(
        repo=repo,
        pull_request_number=pull_request_number,
        required_checks=required_checks,
        proof_level="manual_gap",
        workflow_run_id=snapshot.workflow_run_id,
        check_suite_id=snapshot.check_suite_id,
        check_run_ids=list(snapshot.check_run_ids),
        expected_source_app=snapshot.expected_source_app,
        branch_protection_snapshot=snapshot.branch_protection_snapshot,
        ruleset_snapshot=snapshot.ruleset_snapshot,
        review_event_id=snapshot.review_event_id,
        reviewer_login=snapshot.reviewer_login,
        code_owner_review_verified=snapshot.code_owner_review_verified,
        merge_commit_sha=snapshot.merge_commit_sha,
        merged_at=snapshot.merged_at,
        merge_event_id=snapshot.merge_event_id,
        gap_reason=_github_server_side_truth_gap_reason(candidate),
    )


def can_emit_pr_merged(evidence: GitHubServerSideTruthEvidence) -> bool:
    return (
        evidence.proof_level == "server_side_merge_proof"
        and evidence.has_status_check_truth
        and evidence.has_server_enforcement_truth
        and evidence.has_review_truth
        and evidence.has_merge_truth
    )


def _github_server_side_truth_gap_reason(evidence: GitHubServerSideTruthEvidence) -> str:
    missing = []
    if not evidence.has_status_check_truth:
        missing.append("status_check_truth")
    if not evidence.has_server_enforcement_truth:
        missing.append("server_enforcement_truth")
    if not evidence.has_review_truth:
        missing.append("review_truth")
    if not evidence.has_merge_truth:
        missing.append("merge_truth")
    return "missing server-side truth: " + ", ".join(missing)


def _run_gh_api(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _successful_required_check_runs(
    payload: Any,
    *,
    required_checks: list[str],
) -> tuple[list[int], str | None]:
    if not isinstance(payload, dict):
        return [], None
    check_runs = payload.get("check_runs")
    if not isinstance(check_runs, list):
        return [], None
    required = set(required_checks)
    ids: list[int] = []
    source_apps: list[str] = []
    for item in check_runs:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name not in required or item.get("conclusion") != "success":
            continue
        check_run_id = item.get("id")
        if isinstance(check_run_id, int):
            ids.append(check_run_id)
        app_slug = _nested_str(item, "app", "slug")
        if app_slug is not None:
            source_apps.append(app_slug)
    if {str(name) for name in required} and len(ids) < len(required):
        return ids, source_apps[0] if source_apps else None
    return ids, source_apps[0] if source_apps else None


def _approved_review_identity(payload: list[Any]) -> tuple[int | str | None, str | None]:
    for item in reversed(payload):
        if not isinstance(item, dict) or item.get("state") != "APPROVED":
            continue
        reviewer = item.get("user")
        reviewer_login = (
            _optional_str(reviewer.get("login")) if isinstance(reviewer, dict) else None
        )
        review_id = item.get("id")
        if isinstance(review_id, int | str) and reviewer_login is not None:
            return review_id, reviewer_login
    return None, None


def _requires_code_owner_review(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    review_policy = payload.get("required_pull_request_reviews")
    if not isinstance(review_policy, dict):
        return False
    return review_policy.get("require_code_owner_reviews") is True


def _rulesets_require_code_owner_review(payload: Any, *, base_branch: str) -> bool:
    if not isinstance(payload, dict):
        return False
    rulesets = payload.get("rulesets")
    if not isinstance(rulesets, list):
        return False
    for ruleset in rulesets:
        if not isinstance(ruleset, dict):
            continue
        if ruleset.get("enforcement") != "active":
            continue
        if ruleset.get("target") != "branch":
            continue
        if not _ruleset_applies_to_branch(ruleset, base_branch=base_branch):
            continue
        rules = ruleset.get("rules")
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict) or rule.get("type") != "pull_request":
                continue
            parameters = rule.get("parameters")
            if (
                isinstance(parameters, dict)
                and parameters.get("require_code_owner_review") is True
            ):
                return True
    return False


def _ruleset_applies_to_branch(ruleset: dict[str, Any], *, base_branch: str) -> bool:
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, dict):
        return False
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        return False
    include = ref_name.get("include")
    if not isinstance(include, list):
        return False
    exclude = ref_name.get("exclude", [])
    if not isinstance(exclude, list):
        return False
    branch_refs = (base_branch, f"refs/heads/{base_branch}")
    if _any_ref_pattern_matches(exclude, branch_refs=branch_refs):
        return False
    return _any_ref_pattern_matches(include, branch_refs=branch_refs)


def _any_ref_pattern_matches(patterns: list[Any], *, branch_refs: tuple[str, str]) -> bool:
    return any(
        isinstance(pattern, str)
        and any(fnmatchcase(branch_ref, pattern) for branch_ref in branch_refs)
        for pattern in patterns
    )


def _nested_str(payload: dict[str, Any], *path: str) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _optional_str(current)


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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
