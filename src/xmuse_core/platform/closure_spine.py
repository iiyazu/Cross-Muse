from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ClosureConditionStatus = Literal["true", "false"]
ClosureSeverity = Literal["ok", "manual_gap", "blocked"]

CONTRACT_PROOF = "contract_proof"
NOT_SERVER_TRUTH = "not_server_truth"
CANDIDATE_EVIDENCE_ONLY = "candidate_evidence_only"
INDEPENDENT_REVIEW_ARTIFACT = "independent_review_artifact"

CHAIN = ("Recovery", "ExecutionCandidate", "ReviewClosure", "ReleaseHandoff")

CLOSURE_CONTROLLER_FRESH = "ClosureControllerFresh"
RECOVERY_READY = "RecoveryReady"
EXECUTION_CANDIDATE_READY = "ExecutionCandidateReady"
INDEPENDENT_REVIEW_READY = "IndependentReviewReady"
RELEASE_HANDOFF_READY = "ReleaseHandoffReady"
REQUIRED_FORBIDDEN_CLAIMS_PRESENT = "RequiredForbiddenClaimsPresent"
SERVER_TRUTH_PENDING = "ServerTruthPending"

CONDITION_ORDER = (
    CLOSURE_CONTROLLER_FRESH,
    RECOVERY_READY,
    EXECUTION_CANDIDATE_READY,
    INDEPENDENT_REVIEW_READY,
    RELEASE_HANDOFF_READY,
    REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
    SERVER_TRUTH_PENDING,
)

REQUIRED_FORBIDDEN_CLAIMS = (
    "github_review_truth",
    "ready_to_merge",
    "pr_merged",
    "live_memoryos",
    "worker_output_is_review_truth",
    "local_tests_are_review_truth",
    "server_side_truth",
    "full_l8_l10_closure",
    "full_l1_l11_closure",
    "overnight_readiness",
    "natural_peer_god_groupchat",
)

SCHEMA_BY_STAGE = {
    "recovery": "xmuse.minimal_recovery_artifact.v1",
    "candidate": "xmuse.minimal_execution_candidate.v1",
    "review": "xmuse.minimal_review_verdict.v1",
    "handoff": "xmuse.minimal_release_handoff.v1",
}


@dataclass(frozen=True)
class ClosureCondition:
    type: str
    status: ClosureConditionStatus
    severity: ClosureSeverity
    reason: str
    observed_generation: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "status": self.status,
            "severity": self.severity,
            "reason": self.reason,
            "proof_level": CONTRACT_PROOF,
            "observed_generation": self.observed_generation,
        }


@dataclass(frozen=True)
class ClosureSpine:
    graph_id: str
    lane_id: str
    generation: int
    observed_generation: int
    conditions: tuple[ClosureCondition, ...]
    source_refs: tuple[str, ...]
    owner_refs: tuple[str, ...]
    forbidden_claims: tuple[str, ...]

    @property
    def phase(self) -> str:
        if any(condition.severity == "blocked" for condition in self.conditions):
            return "blocked"
        if all(condition.status == "true" for condition in self.conditions):
            return "release_handoff_contract_ready"
        return "manual_gap"

    @property
    def manual_gaps(self) -> tuple[str, ...]:
        return tuple(
            condition.reason
            for condition in self.conditions
            if condition.severity == "manual_gap"
        )

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        return tuple(
            condition.reason
            for condition in self.conditions
            if condition.severity == "blocked"
        )

    def condition(self, condition_type: str) -> ClosureCondition | None:
        return next(
            (condition for condition in self.conditions if condition.type == condition_type),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": "xmuse.io/v1",
            "kind": "MinimalClosureSpine",
            "spec": {
                "chain": list(CHAIN),
                "proof_level": CONTRACT_PROOF,
                "required_forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
            },
            "status": {
                "phase": self.phase,
                "graph_id": self.graph_id,
                "lane_id": self.lane_id,
                "generation": self.generation,
                "observed_generation": self.observed_generation,
                "conditions": [condition.to_dict() for condition in self.conditions],
                "source_refs": list(self.source_refs),
                "target_refs": [f"graph:{self.graph_id}", f"lane:{self.lane_id}"],
                "owner_refs": list(self.owner_refs),
                "manual_gaps": list(self.manual_gaps),
                "forbidden_claims": list(self.forbidden_claims),
                "blocked_reasons": list(self.blocked_reasons),
            },
        }


@dataclass(frozen=True)
class ClosureSpineAdmission:
    ready: bool
    status: str
    summary: str
    source_refs: tuple[str, ...] = ()
    owner_refs: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()


def evaluate_minimal_closure_spine(
    *,
    graph_id: str,
    lane_id: str,
    recovery: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    review: Mapping[str, Any] | None,
    handoff: Mapping[str, Any] | None,
    generation: int = 1,
    observed_generation: int | None = None,
) -> ClosureSpine:
    observed = generation if observed_generation is None else observed_generation
    conditions = tuple(
        _with_generation(condition, observed)
        for condition in (
            _fresh(generation),
            _recovery_ready(recovery, graph_id, lane_id),
            _candidate_ready(candidate, recovery, graph_id, lane_id),
            _review_ready(review, candidate, graph_id, lane_id),
            _handoff_ready(handoff, candidate, review, graph_id, lane_id),
            _forbidden_claims_present(recovery, candidate, review, handoff),
            _server_truth_pending(recovery, candidate, review, handoff),
        )
    )
    return ClosureSpine(
        graph_id=graph_id,
        lane_id=lane_id,
        generation=generation,
        observed_generation=observed,
        conditions=conditions,
        source_refs=_source_refs(recovery, candidate, review, handoff),
        owner_refs=_owner_refs(recovery, candidate, review, handoff),
        forbidden_claims=dedupe_text(
            [
                *REQUIRED_FORBIDDEN_CLAIMS,
                *_claims(recovery),
                *_claims(candidate),
                *_claims(review),
                *_claims(handoff),
            ]
        ),
    )


def admit_closure_spine(spine: ClosureSpine) -> ClosureSpineAdmission:
    issues: list[str] = []
    missing = [name for name in CONDITION_ORDER if spine.condition(name) is None]
    if missing:
        issues.append("missing closure conditions: " + ", ".join(missing))
    failed = [
        f"{condition.type}: {condition.reason}"
        for condition in spine.conditions
        if condition.type in CONDITION_ORDER
        and (condition.status != "true" or condition.severity != "ok")
    ]
    if failed:
        issues.append("closure conditions are not admitted: " + "; ".join(failed))
    stale = [
        condition.type
        for condition in spine.conditions
        if condition.observed_generation != spine.observed_generation
    ]
    if stale:
        issues.append(
            "closure conditions have stale observed_generation: " + ", ".join(stale)
        )
    if spine.observed_generation != spine.generation:
        issues.append("closure observed_generation does not match generation")
    missing_claims = [
        claim for claim in REQUIRED_FORBIDDEN_CLAIMS if claim not in spine.forbidden_claims
    ]
    if missing_claims:
        issues.append("closure missing forbidden claims: " + ", ".join(missing_claims))
    if spine.blocked_reasons:
        issues.extend(spine.blocked_reasons)
    if not spine.source_refs:
        issues.append("closure source refs are missing")
    if not spine.owner_refs:
        issues.append("closure owner refs are missing")
    if issues:
        return ClosureSpineAdmission(
            ready=False,
            status="blocked" if spine.blocked_reasons else "manual_gap",
            summary="; ".join(dedupe_text(issues)),
            issues=dedupe_text(issues),
        )
    return ClosureSpineAdmission(
        ready=True,
        status="ready",
        summary="minimal closure spine admitted as contract proof",
        source_refs=spine.source_refs,
        owner_refs=spine.owner_refs,
    )


def closure_condition_by_type(
    spine: ClosureSpine,
    condition_type: str,
) -> ClosureCondition | None:
    return spine.condition(condition_type)


def _fresh(generation: int) -> ClosureCondition:
    if generation < 1:
        return _blocked(CLOSURE_CONTROLLER_FRESH, "closure generation must be positive")
    return _ok(CLOSURE_CONTROLLER_FRESH, f"closure generation {generation} is fresh")


def _recovery_ready(
    recovery: Mapping[str, Any] | None,
    graph_id: str,
    lane_id: str,
) -> ClosureCondition:
    issues = _artifact_issues(recovery, "recovery", graph_id, lane_id)
    if recovery is not None and recovery.get("allows_progress") is not True:
        issues.append("recovery does not allow progress")
    return _condition_from_issues(RECOVERY_READY, "recovery allows progress", issues)


def _candidate_ready(
    candidate: Mapping[str, Any] | None,
    recovery: Mapping[str, Any] | None,
    graph_id: str,
    lane_id: str,
) -> ClosureCondition:
    issues = _artifact_issues(candidate, "candidate", graph_id, lane_id)
    if _ref(candidate) is not None and _text(_field(candidate, "recovery_ref")) != _ref(
        recovery
    ):
        issues.append("candidate is not tied to recovery")
    if _text(_field(candidate, "worker_output_truth_status")) != CANDIDATE_EVIDENCE_ONLY:
        issues.append("worker output is not candidate evidence only")
    if _text(_field(candidate, "local_tests_truth_status")) != CANDIDATE_EVIDENCE_ONLY:
        issues.append("local tests are not candidate evidence only")
    return _condition_from_issues(
        EXECUTION_CANDIDATE_READY,
        "execution candidate is candidate evidence only",
        issues,
    )


def _review_ready(
    review: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    graph_id: str,
    lane_id: str,
) -> ClosureCondition:
    issues = _artifact_issues(review, "review", graph_id, lane_id)
    if _ref(candidate) not in string_list(_field(review, "cited_candidate_refs")):
        issues.append("review does not cite candidate")
    if _text(_field(review, "reviewer_ref")) is None:
        issues.append("reviewer_ref is missing")
    if _text(_field(review, "review_truth_status")) != INDEPENDENT_REVIEW_ARTIFACT:
        issues.append("review is not independent_review_artifact")
    return _condition_from_issues(
        INDEPENDENT_REVIEW_READY,
        "independent review cites candidate",
        issues,
    )


def _handoff_ready(
    handoff: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    review: Mapping[str, Any] | None,
    graph_id: str,
    lane_id: str,
) -> ClosureCondition:
    issues = _artifact_issues(handoff, "handoff", graph_id, lane_id)
    if _ref(candidate) not in string_list(_field(handoff, "cited_candidate_refs")):
        issues.append("handoff does not cite candidate")
    if _ref(review) not in string_list(_field(handoff, "review_verdict_refs")):
        issues.append("handoff does not cite review")
    if _text(_field(handoff, "handoff_status")) != "evaluated":
        issues.append("handoff status is not evaluated")
    server_issue = _server_truth_issue(handoff, "handoff")
    if server_issue:
        return _blocked(RELEASE_HANDOFF_READY, server_issue)
    return _condition_from_issues(
        RELEASE_HANDOFF_READY,
        "release handoff cites candidate and review",
        issues,
    )


def _forbidden_claims_present(
    *artifacts: Mapping[str, Any] | None,
) -> ClosureCondition:
    missing = [
        f"{_ref(artifact) or 'artifact'} missing {claim}"
        for artifact in artifacts
        if artifact is not None
        for claim in REQUIRED_FORBIDDEN_CLAIMS
        if claim not in _claims(artifact)
    ]
    return _condition_from_issues(
        REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
        "required forbidden claims are preserved",
        missing,
    )


def _server_truth_pending(*artifacts: Mapping[str, Any] | None) -> ClosureCondition:
    issues = [
        issue
        for artifact in artifacts
        if (issue := _server_truth_issue(artifact, "artifact")) is not None
    ]
    if issues:
        return _blocked(SERVER_TRUTH_PENDING, "; ".join(issues))
    return _ok(SERVER_TRUTH_PENDING, "server truth remains pending")


def _artifact_issues(
    artifact: Mapping[str, Any] | None,
    stage: str,
    graph_id: str,
    lane_id: str,
) -> list[str]:
    if artifact is None:
        return [f"{stage} is missing"]
    issues: list[str] = []
    if _text(artifact.get("schema_version")) != SCHEMA_BY_STAGE[stage]:
        issues.append(f"{stage} schema_version is unsupported")
    if _ref(artifact) is None:
        issues.append(f"{stage} artifact_ref is missing")
    if _text(artifact.get("graph_id")) != graph_id:
        issues.append(f"{stage} graph_id does not match")
    if _text(artifact.get("lane_id")) != lane_id:
        issues.append(f"{stage} lane_id does not match")
    if _text(artifact.get("proof_level")) != CONTRACT_PROOF:
        issues.append(f"{stage} proof_level is not contract_proof")
    if not string_list(artifact.get("owner_refs")):
        issues.append(f"{stage} owner_refs are missing")
    if (server_issue := _server_truth_issue(artifact, stage)) is not None:
        issues.append(server_issue)
    return issues


def _condition_from_issues(
    condition_type: str,
    ok_reason: str,
    issues: Sequence[str],
) -> ClosureCondition:
    if issues:
        return _gap(condition_type, issues[0])
    return _ok(condition_type, ok_reason)


def _ok(condition_type: str, reason: str) -> ClosureCondition:
    return ClosureCondition(condition_type, "true", "ok", reason, 0)


def _gap(condition_type: str, reason: str) -> ClosureCondition:
    return ClosureCondition(condition_type, "false", "manual_gap", reason, 0)


def _blocked(condition_type: str, reason: str) -> ClosureCondition:
    return ClosureCondition(condition_type, "false", "blocked", reason, 0)


def _with_generation(
    condition: ClosureCondition,
    generation: int,
) -> ClosureCondition:
    return ClosureCondition(
        condition.type,
        condition.status,
        condition.severity,
        condition.reason,
        generation,
    )


def _source_refs(*artifacts: Mapping[str, Any] | None) -> tuple[str, ...]:
    return dedupe_text(
        value
        for artifact in artifacts
        if artifact is not None
        for value in (
            _ref(artifact),
            *string_list(artifact.get("worker_output_refs")),
            *string_list(artifact.get("local_test_refs")),
        )
    )


def _owner_refs(*artifacts: Mapping[str, Any] | None) -> tuple[str, ...]:
    return dedupe_text(
        ref
        for artifact in artifacts
        if artifact is not None
        for ref in string_list(artifact.get("owner_refs"))
    )


def _claims(artifact: Mapping[str, Any] | None) -> tuple[str, ...]:
    if artifact is None:
        return ()
    return string_list(artifact.get("forbidden_claims"))


def _server_truth_issue(
    artifact: Mapping[str, Any] | None,
    label: str,
) -> str | None:
    if artifact is None:
        return None
    status = _text(artifact.get("server_truth_status"))
    if status not in {None, NOT_SERVER_TRUTH}:
        return f"{label} overclaims server truth: {status}"
    return None


def _ref(artifact: Mapping[str, Any] | None) -> str | None:
    if artifact is None:
        return None
    return _text(artifact.get("artifact_ref"))


def _field(artifact: Mapping[str, Any] | None, key: str) -> object:
    if artifact is None:
        return None
    return artifact.get(key)


def string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return dedupe_text(value)


def dedupe_text(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        clean = value.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return tuple(result)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
