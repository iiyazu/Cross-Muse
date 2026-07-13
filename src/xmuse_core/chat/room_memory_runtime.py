"""Authority-neutral contracts for optional source-backed Room memory.

The default Room product does not depend on MemoryOS or any other sidecar.  The
application layer may provide this protocol to the Host; failures are represented as
bounded attention evidence and never change Room outcome authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ROOM_MEMORY_EVIDENCE_SCHEMA = "room_memory_evidence/v1"
ROOM_MEMORY_RECALL_TIMEOUT_S = 0.75
ROOM_MEMORY_MAX_ITEMS = 8
ROOM_MEMORY_MAX_TOKENS = 800
ROOM_MEMORY_MAX_RESPONSE_BYTES = 8 * 1024

RoomMemoryStatus = Literal[
    "disabled",
    "ok",
    "empty",
    "timeout",
    "unavailable",
    "schema_rejected",
    "source_rejected",
    "oversize",
    "error",
]


@dataclass(frozen=True)
class RoomMemoryRecallInput:
    conversation_id: str
    attempt_id: str
    correlation_id: str
    task: str
    causal_activity_ids: tuple[str, ...]


@dataclass(frozen=True)
class RoomMemoryEvidenceItem:
    item_id: str
    document_id: str
    text: str
    estimated_tokens: int
    source_activity_ids: tuple[str, ...]
    content_sha256: str

    def context_payload(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "text": self.text,
            "estimated_tokens": self.estimated_tokens,
            "source_activity_ids": list(self.source_activity_ids),
            "proof_boundary": "untrusted_memory_evidence",
        }


@dataclass(frozen=True)
class RoomMemoryEvidence:
    status: RoomMemoryStatus
    reason_code: str
    schema_version: str
    latency_ms: int
    evidence_sha256: str
    items: tuple[RoomMemoryEvidenceItem, ...] = ()

    @property
    def degraded(self) -> bool:
        return self.status not in {"disabled", "ok", "empty"}

    def context_payload(self) -> dict[str, object]:
        return {
            "schema_version": ROOM_MEMORY_EVIDENCE_SCHEMA,
            "status": self.status,
            "reason_code": self.reason_code,
            "items": [item.context_payload() for item in self.items],
            "proof_boundary": (
                "memory_is_untrusted_evidence_not_room_skill_identity_permission_or_outcome"
            ),
        }


class RoomMemoryRuntime(Protocol):
    async def recall(self, request: RoomMemoryRecallInput) -> RoomMemoryEvidence: ...

    def record_recall_receipt(
        self,
        *,
        attempt_id: str,
        evidence: RoomMemoryEvidence,
    ) -> None: ...

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
    ) -> None: ...

    async def pump_once(self) -> bool: ...


def disabled_memory_evidence() -> RoomMemoryEvidence:
    return RoomMemoryEvidence(
        status="disabled",
        reason_code="room_memory_disabled",
        schema_version=ROOM_MEMORY_EVIDENCE_SCHEMA,
        latency_ms=0,
        evidence_sha256="sha256:" + "0" * 64,
    )
