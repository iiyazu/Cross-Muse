from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

ClosureConditionStatus = Literal["true", "false", "unknown"]
ClosureSeverity = Literal["ok", "manual_gap", "blocked"]

CLOSURE_OBJECT_EVALUATOR_VERSION = "xmuse.closure_controller.v1"

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
PATCH_FORWARD_LINEAGE_PRESENT = "PatchForwardLineagePresent"
RELEASE_HANDOFF_EVALUATED = "ReleaseHandoffEvaluated"
REQUIRED_FORBIDDEN_CLAIMS_PRESENT = "RequiredForbiddenClaimsPresent"
SERVER_TRUTH_PENDING = "ServerTruthPending"
CLOSURE_CONTROLLER_FRESH = "ClosureControllerFresh"

REQUIRED_FORBIDDEN_CLAIMS = (
    "live_memoryos",
    "github_review_truth",
    "ready_to_merge",
    "pr_merged",
    "worker_output_is_review_truth",
)

CONDITION_ORDER = (
    CLOSURE_CONTROLLER_FRESH,
    RECOVERY_ARTIFACT_PRESENT,
    RECOVERY_ALLOWS_PROGRESS,
    VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    INDEPENDENT_REVIEW_VERDICT_PRESENT,
    PATCH_FORWARD_LINEAGE_PRESENT,
    RELEASE_HANDOFF_EVALUATED,
    REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
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
    generation: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer,
            "chain": list(self.chain),
            "source_refs": list(self.source_refs),
            "target_refs": list(self.target_refs),
            "owner_refs": list(self.owner_refs),
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClosureMetadata:
        return cls(
            name=_required_text(payload, "name"),
            layer=_required_text(payload, "layer"),
            chain=string_list(payload.get("chain")) or DEFAULT_CLOSURE_CHAIN,
            source_refs=string_list(payload.get("source_refs")),
            target_refs=string_list(payload.get("target_refs")),
            owner_refs=string_list(payload.get("owner_refs")),
            generation=_non_negative_int(payload.get("generation"), default=1),
        )


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClosureSpec:
        return cls(
            desired_conditions=string_list(payload.get("desired_conditions"))
            or CONDITION_ORDER,
            proof_level=_text(payload.get("proof_level")) or "contract_proof",
            required_forbidden_claims=string_list(
                payload.get("required_forbidden_claims")
            )
            or REQUIRED_FORBIDDEN_CLAIMS,
        )


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
    observed_generation: int | None = None

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
            "observed_generation": self.observed_generation,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClosureCondition:
        return cls(
            type=_required_text(payload, "type"),
            status=_condition_status(payload.get("status")),
            severity=_severity(payload.get("severity")),
            reason=_required_text(payload, "reason"),
            proof_level=_text(payload.get("proof_level")) or "contract_proof",
            source_refs=string_list(payload.get("source_refs")),
            target_refs=string_list(payload.get("target_refs")),
            observed_ref=_text(payload.get("observed_ref")),
            observed_generation=_optional_non_negative_int(
                payload.get("observed_generation")
            ),
        )


@dataclass(frozen=True)
class ClosureStatus:
    phase: str
    proof_level: str = "contract_proof"
    conditions: tuple[ClosureCondition, ...] = ()
    observed_refs: tuple[str, ...] = ()
    observed_generation: int = 1
    evaluator_version: str = CLOSURE_OBJECT_EVALUATOR_VERSION
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
            "observed_generation": self.observed_generation,
            "evaluator_version": self.evaluator_version,
            "manual_gaps": list(self.manual_gaps),
            "forbidden_claims": list(self.forbidden_claims),
            "blocked_reasons": list(self.blocked_reasons),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClosureStatus:
        return cls(
            phase=_required_text(payload, "phase"),
            proof_level=_text(payload.get("proof_level")) or "contract_proof",
            conditions=tuple(
                ClosureCondition.from_dict(condition)
                for condition in mapping_list(payload.get("conditions"))
            ),
            observed_refs=string_list(payload.get("observed_refs")),
            observed_generation=_non_negative_int(
                payload.get("observed_generation"),
                default=1,
            ),
            evaluator_version=_text(payload.get("evaluator_version"))
            or CLOSURE_OBJECT_EVALUATOR_VERSION,
            manual_gaps=string_list(payload.get("manual_gaps")),
            forbidden_claims=string_list(payload.get("forbidden_claims"))
            or REQUIRED_FORBIDDEN_CLAIMS,
            blocked_reasons=string_list(payload.get("blocked_reasons")),
        )


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClosureObject:
        if _text(payload.get("apiVersion")) != "xmuse.io/v1":
            raise ValueError("ClosureObject apiVersion must be xmuse.io/v1")
        if _text(payload.get("kind")) != "ClosureObject":
            raise ValueError("ClosureObject kind must be ClosureObject")
        metadata = payload.get("metadata")
        spec = payload.get("spec")
        status = payload.get("status")
        if not isinstance(metadata, Mapping):
            raise ValueError("ClosureObject metadata must be an object")
        if not isinstance(spec, Mapping):
            raise ValueError("ClosureObject spec must be an object")
        if not isinstance(status, Mapping):
            raise ValueError("ClosureObject status must be an object")
        return cls(
            metadata=ClosureMetadata.from_dict(metadata),
            spec=ClosureSpec.from_dict(spec),
            status=ClosureStatus.from_dict(status),
        )


@dataclass(frozen=True)
class ClosureObjectL10Admission:
    gate_ready: bool
    summary: str
    phase: str
    source_refs: tuple[str, ...]
    source_ref_count: int
    target_refs: tuple[str, ...]
    target_ref_count: int
    owner_refs: tuple[str, ...]
    owner_ref_count: int
    forbidden_claim_count: int
    issues: tuple[str, ...] = ()


def evaluate_closure_object_l10_admission(
    closure: ClosureObject,
) -> ClosureObjectL10Admission:
    """Evaluate whether a ClosureObject can seed L10 provenance hints."""

    issues: list[str] = []
    missing_spec_conditions = [
        condition_type
        for condition_type in CONDITION_ORDER
        if condition_type not in closure.spec.desired_conditions
    ]
    if missing_spec_conditions:
        issues.append(
            "ClosureObject spec missing required desired conditions: "
            + ", ".join(missing_spec_conditions)
        )
    missing_status_conditions = [
        condition_type
        for condition_type in CONDITION_ORDER
        if closure.status.condition(condition_type) is None
    ]
    if missing_status_conditions:
        issues.append(
            "ClosureObject status missing desired conditions: "
            + ", ".join(missing_status_conditions)
        )
    if closure.status.evaluator_version != CLOSURE_OBJECT_EVALUATOR_VERSION:
        issues.append("ClosureObject evaluator_version is stale")
    if closure.status.observed_generation != closure.metadata.generation:
        issues.append(
            "ClosureObject observed_generation does not match metadata generation"
        )
    if closure.status.phase == "blocked":
        issues.append("ClosureObject phase is blocked")
    fresh = closure.status.condition(CLOSURE_CONTROLLER_FRESH)
    if fresh is None or fresh.status != "true" or fresh.severity != "ok":
        issues.append("ClosureObject controller freshness is not ok")
    forbidden = closure.status.condition(REQUIRED_FORBIDDEN_CLAIMS_PRESENT)
    if forbidden is None or forbidden.status != "true" or forbidden.severity != "ok":
        issues.append("ClosureObject required forbidden claims are not preserved")
    server = closure.status.condition(SERVER_TRUTH_PENDING)
    if server is None or server.status != "true" or server.severity != "ok":
        issues.append("ClosureObject server-truth boundary is not pending")
    missing_claims = [
        claim
        for claim in REQUIRED_FORBIDDEN_CLAIMS
        if claim not in closure.status.forbidden_claims
    ]
    if missing_claims:
        issues.append(
            "ClosureObject missing forbidden claims: " + ", ".join(missing_claims)
        )
    source_refs = dedupe_text(
        [
            *closure.metadata.source_refs,
            *closure.status.observed_refs,
        ]
    )
    if not source_refs:
        issues.append("ClosureObject source refs are missing")
    if not closure.metadata.target_refs:
        issues.append("ClosureObject target refs are missing")
    if not closure.metadata.owner_refs:
        issues.append("ClosureObject owner refs are missing")
    if issues:
        return ClosureObjectL10Admission(
            gate_ready=False,
            summary="; ".join(issues),
            phase=closure.status.phase,
            source_refs=(),
            source_ref_count=0,
            target_refs=(),
            target_ref_count=0,
            owner_refs=(),
            owner_ref_count=0,
            forbidden_claim_count=len(closure.status.forbidden_claims),
            issues=tuple(issues),
        )
    return ClosureObjectL10Admission(
        gate_ready=True,
        summary="ClosureObject can seed MemoryOS source refs.",
        phase=closure.status.phase,
        source_refs=source_refs,
        source_ref_count=len(source_refs),
        target_refs=closure.metadata.target_refs,
        target_ref_count=len(closure.metadata.target_refs),
        owner_refs=closure.metadata.owner_refs,
        owner_ref_count=len(closure.metadata.owner_refs),
        forbidden_claim_count=len(closure.status.forbidden_claims),
    )


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


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _text(payload.get(key))
    if value is None:
        raise ValueError(f"ClosureObject {key} must be a non-empty string")
    return value


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _condition_status(value: object) -> ClosureConditionStatus:
    if value in {"true", "false", "unknown"}:
        return value  # type: ignore[return-value]
    raise ValueError("ClosureCondition status must be true, false, or unknown")


def _severity(value: object) -> ClosureSeverity:
    if value in {"ok", "manual_gap", "blocked"}:
        return value  # type: ignore[return-value]
    raise ValueError("ClosureCondition severity must be ok, manual_gap, or blocked")


def _non_negative_int(value: object, *, default: int) -> int:
    parsed = _optional_non_negative_int(value)
    return default if parsed is None else parsed


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("ClosureObject generation fields must be non-negative integers")
    return value
