"""Decode and re-prove untrusted MemoryOS evidence against ``chat.db``."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from xmuse.memoryos_http_client import MemoryOSAdapterError
from xmuse_core.chat.room_memory_ports import RoomMemoryRecallSourceRequestPort
from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_EVIDENCE_SCHEMA,
    ROOM_MEMORY_MAX_ITEMS,
    ROOM_MEMORY_MAX_RESPONSE_BYTES,
    ROOM_MEMORY_MAX_TOKENS,
    RoomMemoryEvidence,
    RoomMemoryEvidenceItem,
    RoomMemoryRecallInput,
)

MEMORYOS_CONTEXT_SCHEMA = "memoryos_source_evidence/v1"
MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA = "memoryos_source_evidence/v2"
MEMORYOS_DOCUMENT_PREFIX = "xmuse-room-activity-"
_MEMORYOS_CONTEXT_SEMANTIC_MAX_BYTES = 64 * 1024
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_EVIDENCE_KEYS = {
    "schema",
    "items",
    "omitted_count",
    "estimated_tokens",
    "truncated",
    "diagnostics_digest",
}
_SOURCE_EVIDENCE_ITEM_KEYS = {
    "item_id",
    "archive_id",
    "document_id",
    "source_refs",
    "text",
    "estimated_tokens",
    "content_sha256",
    "score",
    "rank",
    "truncated",
}
_SOURCE_EVIDENCE_V2_ITEM_KEYS = {
    "item_id",
    "layer",
    "document_id",
    "text",
    "estimated_tokens",
    "source_refs",
    "content_sha256",
    "derived",
    "source_complete",
    "score",
    "rank",
    "truncated",
}


@dataclass(frozen=True)
class _SourceEvidenceItemWire:
    item_id: str
    archive_id: str | None
    document_id: str | None
    text: str
    estimated_tokens: int
    source_ids: tuple[str, ...]
    content_sha256: str
    rank: int
    source_type: Literal["document", "message"] = "document"
    source_session_id: str | None = None
    layer: Literal["recall", "page", "core", "archival"] = "archival"
    derived: bool = False


class MemoryOSEvidenceDecoder:
    """Validate wire bytes and resolve every admitted source through one narrow port."""

    def __init__(self, source_store: RoomMemoryRecallSourceRequestPort) -> None:
        self._source_store = source_store

    def decode(
        self,
        payload: Mapping[str, Any],
        *,
        request: RoomMemoryRecallInput,
        durable_request: Mapping[str, Any],
        latency_ms: int,
    ) -> RoomMemoryEvidence:
        try:
            semantic_bytes = json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift") from exc
        if len(semantic_bytes) > _MEMORYOS_CONTEXT_SEMANTIC_MAX_BYTES:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        response_schema = payload.get("schema")
        if response_schema not in {MEMORYOS_CONTEXT_SCHEMA, MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA}:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        if response_schema == MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA:
            if set(payload) != _SOURCE_EVIDENCE_KEYS:
                raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        elif not _SOURCE_EVIDENCE_KEYS <= set(payload):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        raw_items = payload.get("items")
        omitted_count = payload.get("omitted_count")
        estimated_tokens = payload.get("estimated_tokens")
        truncated = payload.get("truncated")
        diagnostics_digest = payload.get("diagnostics_digest")
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > ROOM_MEMORY_MAX_ITEMS
            or isinstance(omitted_count, bool)
            or not isinstance(omitted_count, int)
            or omitted_count < 0
            or isinstance(estimated_tokens, bool)
            or not isinstance(estimated_tokens, int)
            or not 0 <= estimated_tokens <= ROOM_MEMORY_MAX_TOKENS
            or not isinstance(truncated, bool)
            or not isinstance(diagnostics_digest, str)
            or _DIGEST_RE.fullmatch(diagnostics_digest) is None
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        digest_payload = {
            key: payload[key] for key in _SOURCE_EVIDENCE_KEYS - {"diagnostics_digest"}
        }
        if canonical_digest(digest_payload) != diagnostics_digest:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        excluded = {
            str(value)
            for value in durable_request.get("excluded_activity_ids", [])
            if isinstance(value, str)
        }
        excluded.update(request.causal_activity_ids)
        excluded_documents = {
            str(value)
            for value in durable_request.get("excluded_document_ids", [])
            if isinstance(value, str)
        }
        raw_archive_ids = durable_request.get("archive_ids")
        if not isinstance(raw_archive_ids, list) or not raw_archive_ids:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        archive_ids = {
            required_source_id({"archive_id": value}, "archive_id") for value in raw_archive_ids
        }
        if len(archive_ids) != len(raw_archive_ids):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        expected_session_id = durable_request.get("session_id")
        if not isinstance(expected_session_id, str) or not expected_session_id:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        wire_items = [
            source_evidence_item_wire(
                raw,
                v2=response_schema == MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA,
                expected_session_id=expected_session_id,
            )
            for raw in raw_items
            if isinstance(raw, Mapping)
        ]
        if len(wire_items) != len(raw_items):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        if (
            any(
                item.archive_id is not None and item.archive_id not in archive_ids
                for item in wire_items
            )
            or len({item.rank for item in wire_items}) != len(wire_items)
            or sum(item.estimated_tokens for item in wire_items) != estimated_tokens
            or sum(len(item.text.encode("utf-8")) for item in wire_items) > 32 * 1024
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")

        items: list[RoomMemoryEvidenceItem] = []
        rejected_item = False
        for wire in wire_items:
            try:
                item = self._reprove_item(
                    wire,
                    conversation_id=request.conversation_id,
                    correlation_id=request.correlation_id,
                    excluded_activity_ids=excluded,
                    excluded_document_ids=excluded_documents,
                )
            except MemoryOSAdapterError as exc:
                if exc.code != "room_memory_source_rejected":
                    raise
                rejected_item = True
                continue
            if item is None:
                continue
            if memory_context_size([*items, item]) > ROOM_MEMORY_MAX_RESPONSE_BYTES:
                if not items:
                    raise MemoryOSAdapterError("room_memory_evidence_too_large")
                break
            items.append(item)
        if not items and rejected_item:
            raise MemoryOSAdapterError("room_memory_source_rejected")
        status: Literal["ok", "empty"] = "ok" if items else "empty"
        reason = "room_memory_recalled" if items else "room_memory_no_evidence"
        evidence_digest = canonical_digest(
            {
                "schema_version": ROOM_MEMORY_EVIDENCE_SCHEMA,
                "status": status,
                "items": [
                    {
                        **item.context_payload(),
                        "document_id": item.document_id,
                        "content_sha256": item.content_sha256,
                    }
                    for item in items
                ],
            }
        )
        return RoomMemoryEvidence(
            status=status,
            reason_code=reason,
            schema_version=str(response_schema),
            latency_ms=latency_ms,
            evidence_sha256=evidence_digest,
            items=tuple(items),
        )

    def _reprove_item(
        self,
        wire: _SourceEvidenceItemWire,
        *,
        conversation_id: str,
        correlation_id: str,
        excluded_activity_ids: set[str],
        excluded_document_ids: set[str],
    ) -> RoomMemoryEvidenceItem | None:
        if wire.document_id in excluded_document_ids:
            return None
        try:
            if wire.source_type == "message":
                if wire.source_session_id is None:
                    raise MemoryOSAdapterError("room_memory_source_rejected")
                authority = self._source_store.resolve_recall_message_source(
                    conversation_id=conversation_id,
                    session_id=wire.source_session_id,
                    source_message_ids=wire.source_ids,
                    content_sha256=wire.content_sha256,
                    item_text=wire.text,
                    derived=wire.derived,
                )
            else:
                if wire.document_id is None:
                    raise MemoryOSAdapterError("room_memory_source_rejected")
                if any(activity_id in excluded_activity_ids for activity_id in wire.source_ids):
                    return None
                authority = self._source_store.resolve_recall_source(
                    conversation_id=conversation_id,
                    document_id=wire.document_id,
                    source_activity_ids=tuple(sorted(wire.source_ids)),
                    content_sha256=wire.content_sha256,
                    item_text=wire.text,
                )
        except Exception as exc:
            if isinstance(exc, MemoryOSAdapterError):
                raise
            raise MemoryOSAdapterError("room_memory_source_rejected") from exc
        activities = authority.get("source_activities")
        if not isinstance(activities, list) or not activities:
            raise MemoryOSAdapterError("room_memory_source_rejected")
        resolved_activity_ids: list[str] = []
        for source in activities:
            if not isinstance(source, Mapping):
                raise MemoryOSAdapterError("room_memory_source_rejected")
            source_id = source.get("activity_id")
            if not isinstance(source_id, str) or not source_id:
                raise MemoryOSAdapterError("room_memory_source_rejected")
            resolved_activity_ids.append(source_id)
            if (
                source.get("conversation_id") == conversation_id
                and source.get("correlation_id") == correlation_id
            ):
                return None
            if source_id in excluded_activity_ids:
                return None
        document_id = authority.get("document_id") or wire.document_id
        if (
            not isinstance(document_id, str)
            or not document_id
            or len(document_id.encode("utf-8")) > 512
        ):
            raise MemoryOSAdapterError("room_memory_source_rejected")
        return RoomMemoryEvidenceItem(
            item_id=wire.item_id,
            document_id=document_id,
            text=wire.text,
            estimated_tokens=wire.estimated_tokens,
            source_activity_ids=tuple(sorted(resolved_activity_ids)),
            content_sha256=wire.content_sha256,
            layer=wire.layer,
            derived=wire.derived,
        )


def source_evidence_item_wire(
    raw: Mapping[str, Any],
    *,
    v2: bool = False,
    expected_session_id: str | None = None,
) -> _SourceEvidenceItemWire:
    if v2:
        return _source_evidence_v2_item_wire(raw, expected_session_id=expected_session_id)
    if not _SOURCE_EVIDENCE_ITEM_KEYS <= set(raw):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    item_id = required_source_id(raw, "item_id")
    archive_id = required_source_id(raw, "archive_id")
    document_id = required_source_id(raw, "document_id")
    text = raw.get("text")
    tokens = raw.get("estimated_tokens")
    refs = raw.get("source_refs")
    content_sha256 = raw.get("content_sha256")
    score = raw.get("score")
    rank = raw.get("rank")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text.encode("utf-8")) > 8 * 1024
        or isinstance(tokens, bool)
        or not isinstance(tokens, int)
        or not 0 < tokens <= ROOM_MEMORY_MAX_TOKENS
        or not isinstance(refs, list)
        or not refs
        or len(refs) > 8
        or not isinstance(content_sha256, str)
        or _DIGEST_RE.fullmatch(content_sha256) is None
        or isinstance(rank, bool)
        or not isinstance(rank, int)
        or not 1 <= rank <= ROOM_MEMORY_MAX_ITEMS
        or not isinstance(raw.get("truncated"), bool)
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if content_sha256 != f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}":
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    source_ids: list[str] = []
    for ref in refs:
        if (
            not isinstance(ref, Mapping)
            or not {"source_type", "source_id"} <= set(ref)
            or ref.get("source_type") != "document"
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        source_ids.append(required_source_id(ref, "source_id"))
    if len(set(source_ids)) != len(source_ids):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    layer = raw.get("layer", "archival")
    derived = raw.get("derived", layer in {"recall", "page"})
    if layer not in {"recall", "page", "core", "archival"} or not isinstance(derived, bool):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    return _SourceEvidenceItemWire(
        item_id=item_id,
        archive_id=archive_id,
        document_id=document_id,
        text=text,
        estimated_tokens=tokens,
        source_ids=tuple(source_ids),
        content_sha256=content_sha256,
        rank=rank,
        layer=layer,
        derived=derived,
    )


def _source_evidence_v2_item_wire(
    raw: Mapping[str, Any], *, expected_session_id: str | None
) -> _SourceEvidenceItemWire:
    if (
        set(raw) - _SOURCE_EVIDENCE_V2_ITEM_KEYS
        or not (_SOURCE_EVIDENCE_V2_ITEM_KEYS - {"document_id"}) <= set(raw)
        or not isinstance(expected_session_id, str)
        or not expected_session_id
    ):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    item_id = required_source_id(raw, "item_id")
    text = raw.get("text")
    tokens = raw.get("estimated_tokens")
    refs = raw.get("source_refs")
    content_sha256 = raw.get("content_sha256")
    score = raw.get("score")
    rank = raw.get("rank")
    layer = raw.get("layer")
    document_id_raw = raw.get("document_id")
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text.encode("utf-8")) > 8 * 1024
        or isinstance(tokens, bool)
        or not isinstance(tokens, int)
        or not 0 < tokens <= ROOM_MEMORY_MAX_TOKENS
        or not isinstance(refs, list)
        or not refs
        or len(refs) > 8
        or not isinstance(content_sha256, str)
        or _DIGEST_RE.fullmatch(content_sha256) is None
        or isinstance(rank, bool)
        or not isinstance(rank, int)
        or not 1 <= rank <= ROOM_MEMORY_MAX_ITEMS
        or layer not in {"recall", "page", "core", "archival"}
        or (document_id_raw is not None and optional_source_id(document_id_raw) is None)
        or raw.get("source_complete") is not True
        or not isinstance(raw.get("derived"), bool)
        or not isinstance(raw.get("truncated"), bool)
        or (score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))))
    ):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if score is not None and not math.isfinite(float(score)):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if content_sha256 != f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}":
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    source_type: Literal["document", "message"] | None = None
    source_session_id: str | None = None
    source_ids: list[str] = []
    for ref in refs:
        if not isinstance(ref, Mapping) or set(ref) - {"source_type", "source_id", "session_id"}:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        ref_type = ref.get("source_type")
        if ref_type not in {"document", "message"} or (
            source_type is not None and source_type != ref_type
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
        source_type = ref_type
        source_ids.append(required_source_id(ref, "source_id"))
        session = ref.get("session_id")
        if ref_type == "message":
            if session != expected_session_id or (
                source_session_id is not None and source_session_id != session
            ):
                raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
            source_session_id = session
        elif session is not None and (
            not isinstance(session, str) or not session or len(session.encode("utf-8")) > 512
        ):
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if source_type is None or len(set(source_ids)) != len(source_ids):
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    if source_type == "message" and layer == "archival":
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    document_id: str | None = None
    if source_type == "document":
        source_id = source_ids[0]
        document_id = (
            optional_source_id(document_id_raw)
            if document_id_raw is not None
            else (
                source_id
                if source_id.startswith((MEMORYOS_DOCUMENT_PREFIX, "xmuse-room-memory-candidate-"))
                else f"{MEMORYOS_DOCUMENT_PREFIX}{source_id}"
            )
        )
        if layer == "archival" and document_id is None:
            raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    return _SourceEvidenceItemWire(
        item_id=item_id,
        archive_id=None,
        document_id=document_id,
        text=text,
        estimated_tokens=tokens,
        source_ids=tuple(source_ids),
        content_sha256=content_sha256,
        rank=rank,
        source_type=source_type,
        source_session_id=source_session_id,
        layer=layer,
        derived=bool(raw["derived"]),
    )


def required_source_id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        raise MemoryOSAdapterError("memoryos_source_evidence_capability_drift")
    return value


def optional_source_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        return None
    return value


def canonical_digest(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MemoryOSAdapterError("room_memory_digest_invalid") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def memory_context_size(items: Sequence[RoomMemoryEvidenceItem]) -> int:
    evidence = RoomMemoryEvidence(
        status="ok",
        reason_code="room_memory_recalled",
        schema_version=MEMORYOS_CONTEXT_SCHEMA,
        latency_ms=0,
        evidence_sha256="sha256:" + "0" * 64,
        items=tuple(items),
    )
    return len(
        json.dumps(
            evidence.context_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


__all__ = [
    "MEMORYOS_CONTEXT_SCHEMA",
    "MEMORYOS_SOURCE_EVIDENCE_V2_SCHEMA",
    "MemoryOSEvidenceDecoder",
    "canonical_digest",
]
