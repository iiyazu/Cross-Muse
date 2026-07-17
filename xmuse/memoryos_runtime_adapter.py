"""Host-facing composition for independently bounded MemoryOS capabilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from xmuse.memoryos_http_client import MemoryOSAdapterError
from xmuse_core.chat.room_memory_ports import RoomMemoryRecallReceiptContextPort
from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_RECALL_TIMEOUT_S,
    RoomMemoryEvidence,
    RoomMemoryRecallInput,
    disabled_memory_evidence,
)


class MemoryRecallCapability(Protocol):
    @property
    def recall_timeout_s(self) -> float: ...

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
        included_items: Sequence[Mapping[str, Any]] = (),
    ) -> None: ...


class MemoryDeliveryCapability(Protocol):
    async def pump_once(self) -> bool: ...


class MemoryOSRoomMemoryRuntime:
    """Implement the stable Host protocol by delegation, without owning a Store."""

    def __init__(
        self,
        recall_runtime: MemoryRecallCapability,
        delivery_pump: MemoryDeliveryCapability,
    ) -> None:
        self._recall_runtime = recall_runtime
        self._delivery_pump = delivery_pump

    @property
    def recall_timeout_s(self) -> float:
        return self._recall_runtime.recall_timeout_s

    async def recall(self, request: RoomMemoryRecallInput) -> RoomMemoryEvidence:
        return await self._recall_runtime.recall(request)

    def record_recall_receipt(
        self,
        *,
        attempt_id: str,
        evidence: RoomMemoryEvidence,
    ) -> None:
        self._recall_runtime.record_recall_receipt(
            attempt_id=attempt_id,
            evidence=evidence,
        )

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
        included_items: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._recall_runtime.bind_context_receipt(
            attempt_id=attempt_id,
            evidence_sha256=evidence_sha256,
            context_payload_sha256=context_payload_sha256,
            included_items=included_items,
        )

    async def pump_once(self) -> bool:
        return await self._delivery_pump.pump_once()


class DisabledRoomMemoryRuntime:
    """Persist disabled receipts through only the receipt/context authority."""

    def __init__(self, receipt_store: RoomMemoryRecallReceiptContextPort) -> None:
        self._receipt_store = receipt_store

    @property
    def recall_timeout_s(self) -> float:
        return ROOM_MEMORY_RECALL_TIMEOUT_S

    async def recall(self, _request: RoomMemoryRecallInput) -> RoomMemoryEvidence:
        return disabled_memory_evidence()

    def record_recall_receipt(
        self,
        *,
        attempt_id: str,
        evidence: RoomMemoryEvidence,
    ) -> None:
        self._receipt_store.record_attempt_memory_receipt(
            attempt_id=attempt_id,
            status=evidence.status,
            schema_version=evidence.schema_version,
            latency_ms=evidence.latency_ms,
            items=[],
            evidence_sha256=evidence.evidence_sha256,
            now=datetime.now(UTC),
        )

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
        included_items: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        if not evidence_sha256.startswith("sha256:") or not context_payload_sha256.startswith(
            "sha256:"
        ):
            raise MemoryOSAdapterError("room_memory_context_digest_invalid")
        self._receipt_store.bind_attempt_memory_context(
            attempt_id=attempt_id,
            evidence_sha256=evidence_sha256,
            context_payload_sha256=context_payload_sha256,
            included_items=included_items,
            now=datetime.now(UTC),
        )

    async def pump_once(self) -> bool:
        return False


__all__ = [
    "DisabledRoomMemoryRuntime",
    "MemoryDeliveryCapability",
    "MemoryOSRoomMemoryRuntime",
    "MemoryRecallCapability",
]
