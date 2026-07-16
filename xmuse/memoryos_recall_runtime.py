"""Recall, source proof, receipt, and advisory runtime for Room memory."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from xmuse.memoryos_evidence import (
    MEMORYOS_CONTEXT_SCHEMA,
    MemoryOSEvidenceDecoder,
    canonical_digest,
)
from xmuse.memoryos_http_client import MemoryOSAdapterError
from xmuse_core.chat.room_memory_ports import (
    RoomMemoryAdvisoryGovernancePort,
    RoomMemoryRecallReceiptContextPort,
    RoomMemoryRecallSourceRequestPort,
)
from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_EVIDENCE_SCHEMA,
    ROOM_MEMORY_MAX_TOKENS,
    RoomMemoryEvidence,
    RoomMemoryRecallInput,
)

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class MemoryOSRecallClient(Protocol):
    @property
    def profile(self) -> Literal["archive-only", "full-local"]: ...

    @property
    def recall_timeout_s(self) -> float: ...

    def build_context(
        self,
        *,
        session_id: str,
        task: str,
        retrieval_query: str | None,
        budget: int,
        timeout_s: float,
    ) -> Mapping[str, Any]: ...

    def list_advisories(self, *, session_id: str) -> list[Mapping[str, Any]]: ...


class MemoryOSRecallRuntime:
    """Produce bounded evidence while persisting only through narrow authorities."""

    def __init__(
        self,
        *,
        source_store: RoomMemoryRecallSourceRequestPort,
        receipt_store: RoomMemoryRecallReceiptContextPort,
        advisory_store: RoomMemoryAdvisoryGovernancePort,
        client: MemoryOSRecallClient,
        decoder: MemoryOSEvidenceDecoder | None = None,
    ) -> None:
        self._source_store = source_store
        self._receipt_store = receipt_store
        self._advisory_store = advisory_store
        self._client = client
        self._decoder = decoder or MemoryOSEvidenceDecoder(source_store)

    @property
    def recall_timeout_s(self) -> float:
        return float(self._client.recall_timeout_s)

    async def recall(self, request: RoomMemoryRecallInput) -> RoomMemoryEvidence:
        started = time.perf_counter()
        try:
            durable = self._source_store.build_recall_request(
                conversation_id=request.conversation_id,
                attempt_id=request.attempt_id,
                correlation_id=request.correlation_id,
                causal_activity_ids=request.causal_activity_ids,
            )
            session_id = _required_id(durable, "session_id", "room_memory_binding_unavailable")
            task = str(durable.get("task") or request.task)
            query = durable.get("retrieval_query")
            if query is not None and not isinstance(query, str):
                raise MemoryOSAdapterError("room_memory_request_invalid")
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.build_context,
                    session_id=session_id,
                    task=task,
                    retrieval_query=query,
                    budget=ROOM_MEMORY_MAX_TOKENS,
                    timeout_s=self.recall_timeout_s,
                ),
                timeout=self.recall_timeout_s,
            )
            if self._client.profile == "full-local":
                await self._record_advisories(
                    session_id=session_id,
                    conversation_id=request.conversation_id,
                    attempt_id=request.attempt_id,
                )
            return self._decoder.decode(
                payload,
                request=request,
                durable_request=durable,
                latency_ms=_latency_ms(started),
            )
        except TimeoutError:
            return _degraded("timeout", "room_memory_timeout", started)
        except MemoryOSAdapterError as exc:
            return _degraded(_status_for_error(exc.code), exc.code, started)
        except Exception as exc:
            code = str(getattr(exc, "code", "room_memory_unavailable"))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code):
                code = "room_memory_unavailable"
            return _degraded("unavailable", code, started)

    async def _record_advisories(
        self,
        *,
        session_id: str,
        conversation_id: str,
        attempt_id: str,
    ) -> None:
        try:
            advisories = await asyncio.to_thread(
                self._client.list_advisories,
                session_id=session_id,
            )
            if advisories:
                self._advisory_store.record_external_advisories(
                    conversation_id=conversation_id,
                    attempt_id=attempt_id,
                    advisories=advisories,
                    now=datetime.now(UTC),
                )
        except Exception as exc:
            reason_code = str(getattr(exc, "code", "memoryos_advisory_replay_failed"))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason_code):
                reason_code = "memoryos_advisory_replay_failed"
            try:
                self._advisory_store.record_external_advisory_failure(
                    conversation_id=conversation_id,
                    attempt_id=attempt_id,
                    reason_code=reason_code,
                    now=datetime.now(UTC),
                )
            except Exception:
                pass

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
            items=[
                {
                    "item_id": item.item_id,
                    "document_id": item.document_id,
                    "source_activity_ids": list(item.source_activity_ids),
                    "content_sha256": item.content_sha256,
                    "text": item.text,
                }
                for item in evidence.items
            ],
            evidence_sha256=evidence.evidence_sha256,
            now=datetime.now(UTC),
        )

    def bind_context_receipt(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
    ) -> None:
        if (
            _DIGEST_RE.fullmatch(evidence_sha256) is None
            or _DIGEST_RE.fullmatch(context_payload_sha256) is None
        ):
            raise MemoryOSAdapterError("room_memory_context_digest_invalid")
        self._receipt_store.bind_attempt_memory_context(
            attempt_id=attempt_id,
            evidence_sha256=evidence_sha256,
            context_payload_sha256=context_payload_sha256,
            now=datetime.now(UTC),
        )


def _required_id(payload: Mapping[str, Any], key: str, code: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value) > 512:
        raise MemoryOSAdapterError(code)
    return value


def _latency_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _degraded(status: str, code: str, started: float) -> RoomMemoryEvidence:
    digest = canonical_digest(
        {
            "schema_version": ROOM_MEMORY_EVIDENCE_SCHEMA,
            "status": status,
            "reason_code": code,
            "items": [],
        }
    )
    return RoomMemoryEvidence(
        status=status,  # type: ignore[arg-type]
        reason_code=code,
        schema_version=MEMORYOS_CONTEXT_SCHEMA,
        latency_ms=_latency_ms(started),
        evidence_sha256=digest,
    )


def _status_for_error(code: str) -> str:
    if code in {"memoryos_response_too_large", "room_memory_evidence_too_large"}:
        return "oversize"
    if code in {"room_memory_schema_rejected", "memoryos_response_invalid"}:
        return "schema_rejected"
    if code == "room_memory_source_rejected":
        return "source_rejected"
    return "unavailable"


__all__ = ["MemoryOSRecallClient", "MemoryOSRecallRuntime"]
