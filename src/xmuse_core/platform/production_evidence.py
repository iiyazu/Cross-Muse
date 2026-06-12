from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from xmuse_core.platform.release_readiness import ProofLevel

PRODUCTION_EVIDENCE_SCHEMA_VERSION = "xmuse.production_evidence.v1"

ProductionEvidenceStatus = Literal[
    "pending",
    "running",
    "ok",
    "blocked",
    "manual_gap",
    "retry",
    "not_evaluated",
]


@dataclass(frozen=True)
class ProductionEvidenceEnvelope:
    stage_id: str
    action: str
    status: ProductionEvidenceStatus
    proof_level: ProofLevel
    source_authority: str
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    target_refs: tuple[str, ...] = field(default_factory=tuple)
    commands: tuple[str, ...] = field(default_factory=tuple)
    test_results: tuple[str, ...] = field(default_factory=tuple)
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    blocked_reason: str | None = None
    owner: str = "codex"
    next_action: str | None = None
    run_id: str | None = None
    summary: str | None = None
    gate_id: str | None = None
    kind: str | None = None
    configured: bool | None = None
    required: bool | None = None
    generated_at: str = field(default_factory=lambda: _utc_now())

    def model_dump(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": PRODUCTION_EVIDENCE_SCHEMA_VERSION,
            "stage_id": self.stage_id,
            "action": self.action,
            "status": self.status,
            "proof_level": self.proof_level,
            "source_authority": self.source_authority,
            "source_refs": list(self.source_refs),
            "target_refs": list(self.target_refs),
            "commands": list(self.commands),
            "test_results": list(self.test_results),
            "artifacts": list(self.artifacts),
            "blocked_reason": self.blocked_reason,
            "owner": self.owner,
            "next_action": self.next_action,
            "generated_at": self.generated_at,
        }
        _add_optional(payload, "run_id", self.run_id)
        _add_optional(payload, "summary", self.summary)
        _add_optional(payload, "gate_id", self.gate_id)
        _add_optional(payload, "kind", self.kind)
        _add_optional(payload, "configured", self.configured)
        _add_optional(payload, "required", self.required)
        return payload


def _add_optional(payload: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        payload[key] = value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
