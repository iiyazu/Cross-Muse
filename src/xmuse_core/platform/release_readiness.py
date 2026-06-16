from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Literal

ProofLevel = Literal[
    "contract_proof",
    "fake_runtime_proof",
    "live_service_proof",
    "server_side_enforcement_proof",
    "server_side_merge_proof",
    "real_provider_proof",
    "internal_review_proof",
    "manual_gap",
]
GateStatus = Literal["ok", "blocked", "manual_gap", "not_evaluated"]
ReadinessDecision = Literal["ready", "blocked", "not_evaluated"]


class ReleaseGateKind(StrEnum):
    LOCAL_VALIDATION = "local_validation"
    INTERNAL_REVIEW = "internal_review"
    LIVE_MEMORYOS = "live_memoryos"
    GITHUB_SERVER_TRUTH = "github_server_truth"
    GITHUB_MERGE_TRUTH = "github_merge_truth"
    REAL_PROVIDER = "real_provider"
    NATURAL_DELIBERATION = "natural_deliberation"


@dataclass(frozen=True)
class ReleaseGateEvidence:
    gate_id: str
    kind: ReleaseGateKind
    configured: bool
    required: bool
    status: GateStatus
    proof_level: ProofLevel
    owner: str
    summary: str
    attempted_command: str | None = None
    next_action: str | None = None
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    target_refs: tuple[str, ...] = field(default_factory=tuple)
    owner_refs: tuple[str, ...] = field(default_factory=tuple)
    forbidden_claims: tuple[str, ...] = field(default_factory=tuple)
    artifacts: tuple[str, ...] = field(default_factory=tuple)

    def model_dump(self) -> dict[str, object]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True)
class ReleaseReadinessResult:
    decision: ReadinessDecision
    blockers: list[dict[str, object]]
    proof_level_summary: dict[str, int]
    gates: list[dict[str, object]]

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


def evaluate_release_readiness(
    gates: list[ReleaseGateEvidence],
) -> ReleaseReadinessResult:
    blockers: list[dict[str, object]] = []
    proof_level_summary: dict[str, int] = {}
    for gate in gates:
        proof_level_summary[gate.proof_level] = (
            proof_level_summary.get(gate.proof_level, 0) + 1
        )
        blocker_reason = _gate_blocker_reason(gate)
        if blocker_reason is not None:
            blockers.append(
                {
                    "gate_id": gate.gate_id,
                    "kind": gate.kind.value,
                    "reason": blocker_reason,
                    "owner": gate.owner,
                    "attempted_command": gate.attempted_command,
                    "next_action": gate.next_action,
                }
            )
    if blockers:
        decision: ReadinessDecision = "blocked"
    elif gates:
        decision = "ready"
    else:
        decision = "not_evaluated"
    return ReleaseReadinessResult(
        decision=decision,
        blockers=blockers,
        proof_level_summary=proof_level_summary,
        gates=[gate.model_dump() for gate in gates],
    )


def _gate_blocker_reason(gate: ReleaseGateEvidence) -> str | None:
    if not gate.required:
        return None
    if not gate.configured:
        return f"{gate.gate_id} is required but not configured"
    if gate.status != "ok":
        return f"{gate.gate_id} status is {gate.status}: {gate.summary}"
    required_proof = _required_proof_level(gate.kind)
    if required_proof is None:
        return None
    if gate.proof_level != required_proof:
        return f"{gate.kind.value} requires {required_proof}, got {gate.proof_level}"
    return None


def _required_proof_level(kind: ReleaseGateKind) -> ProofLevel | None:
    if kind is ReleaseGateKind.LOCAL_VALIDATION:
        return "contract_proof"
    if kind is ReleaseGateKind.INTERNAL_REVIEW:
        return "internal_review_proof"
    if kind is ReleaseGateKind.LIVE_MEMORYOS:
        return "live_service_proof"
    if kind is ReleaseGateKind.GITHUB_SERVER_TRUTH:
        return "server_side_enforcement_proof"
    if kind is ReleaseGateKind.GITHUB_MERGE_TRUTH:
        return "server_side_merge_proof"
    if kind is ReleaseGateKind.REAL_PROVIDER:
        return "real_provider_proof"
    if kind is ReleaseGateKind.NATURAL_DELIBERATION:
        return "real_provider_proof"
    return None
