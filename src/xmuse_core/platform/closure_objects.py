from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ClosureConditionStatus = Literal["true", "false", "unknown"]
ClosureSeverity = Literal["ok", "manual_gap", "blocked"]

CHAIN_LANE_RECOVERY = "LaneRecovery"
CHAIN_EXECUTION_CANDIDATE = "ExecutionCandidate"
CHAIN_REVIEW_CLOSURE = "ReviewClosure"
CHAIN_RELEASE_HANDOFF = "ReleaseHandoff"

DEFAULT_CLOSURE_CHAIN = (
    CHAIN_LANE_RECOVERY,
    CHAIN_EXECUTION_CANDIDATE,
    CHAIN_REVIEW_CLOSURE,
    CHAIN_RELEASE_HANDOFF,
)

RECOVERY_ARTIFACT_PRESENT = "RecoveryArtifactPresent"
RECOVERY_ALLOWS_PROGRESS = "RecoveryAllowsProgress"
VALIDATED_EXECUTION_CANDIDATE_PRESENT = "ValidatedExecutionCandidatePresent"
INDEPENDENT_REVIEW_VERDICT_PRESENT = "IndependentReviewVerdictPresent"
RELEASE_HANDOFF_EVALUATED = "ReleaseHandoffEvaluated"
SERVER_TRUTH_PENDING = "ServerTruthPending"

REQUIRED_FORBIDDEN_CLAIMS = (
    "live_memoryos",
    "github_review_truth",
    "ready_to_merge",
    "pr_merged",
    "worker_output_is_review_truth",
)

CONDITION_ORDER = (
    RECOVERY_ARTIFACT_PRESENT,
    RECOVERY_ALLOWS_PROGRESS,
    VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    INDEPENDENT_REVIEW_VERDICT_PRESENT,
    RELEASE_HANDOFF_EVALUATED,
    SERVER_TRUTH_PENDING,
)


@dataclass(frozen=True)
class ClosureMetadata:
    name: str
    layer: str
    chain: tuple[str, ...] = DEFAULT_CLOSURE_CHAIN
    source_refs: tuple[str, ...] = ()
    target_refs: tuple[str, ...] = ()
    owner_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "chain": list(self.chain),
            "source_refs": list(self.source_refs),
            "target_refs": list(self.target_refs),
            "owner_refs": list(self.owner_refs),
        }


@dataclass(frozen=True)
class ClosureSpec:
    desired_conditions: tuple[str, ...] = CONDITION_ORDER
    proof_level: str = "contract_proof"
    required_forbidden_claims: tuple[str, ...] = REQUIRED_FORBIDDEN_CLAIMS

    def to_dict(self) -> dict[str, Any]:
        return {
            "desired_conditions": list(self.desired_conditions),
            "proof_level": self.proof_level,
            "required_forbidden_claims": list(self.required_forbidden_claims),
        }


@dataclass(frozen=True)
class ClosureCondition:
    type: str
    status: ClosureConditionStatus
    severity: ClosureSeverity
    reason: str
    proof_level: str = "contract_proof"
    source_refs: tuple[str, ...] = ()
    target_refs: tuple[str, ...] = ()
    observed_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "status": self.status,
            "severity": self.severity,
            "reason": self.reason,
            "proof_level": self.proof_level,
            "source_refs": list(self.source_refs),
            "target_refs": list(self.target_refs),
            "observed_ref": self.observed_ref,
        }


@dataclass(frozen=True)
class ClosureStatus:
    phase: str
    proof_level: str = "contract_proof"
    conditions: tuple[ClosureCondition, ...] = ()
    observed_refs: tuple[str, ...] = ()
    manual_gaps: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = REQUIRED_FORBIDDEN_CLAIMS
    blocked_reasons: tuple[str, ...] = ()

    def condition(self, condition_type: str) -> ClosureCondition | None:
        return next(
            (condition for condition in self.conditions if condition.type == condition_type),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "proof_level": self.proof_level,
            "conditions": [condition.to_dict() for condition in self.conditions],
            "observed_refs": list(self.observed_refs),
            "manual_gaps": list(self.manual_gaps),
            "forbidden_claims": list(self.forbidden_claims),
            "blocked_reasons": list(self.blocked_reasons),
        }


@dataclass(frozen=True)
class ClosureObject:
    metadata: ClosureMetadata
    spec: ClosureSpec
    status: ClosureStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": "xmuse.io/v1",
            "kind": "ClosureObject",
            "metadata": self.metadata.to_dict(),
            "spec": self.spec.to_dict(),
            "status": self.status.to_dict(),
        }


@dataclass(frozen=True)
class ClosureObservedState:
    recovery_artifact: Mapping[str, Any] | None = None
    recovery_artifact_ref: str | None = None
    execution_candidates: tuple[Mapping[str, Any], ...] = ()
    execution_candidate_refs: tuple[str, ...] = ()
    review_closure: Mapping[str, Any] | None = None
    review_closure_ref: str | None = None
    release_handoff: Mapping[str, Any] | None = None
    release_handoff_ref: str | None = None


def closure_condition_by_type(
    closure: ClosureObject,
    condition_type: str,
) -> ClosureCondition | None:
    return closure.status.condition(condition_type)


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


def mapping_list(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return dedupe_text(value)
