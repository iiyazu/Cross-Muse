"""Safe, bounded read model for source-backed Room memory.

``chat.db`` remains authoritative for outbox, recall receipts, and candidate
approval.  The managed MemoryOS process is only a rebuildable index, so this
projection deliberately exposes a small health summary rather than its API,
configuration, traces, or process identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

ROOM_MEMORY_PROJECTION_SCHEMA = "room_memory_projection/v1"
ROOM_MEMORY_PROJECTION_V2_SCHEMA = "room_memory_projection/v2"
ROOM_MEMORY_PROOF_BOUNDARY = "memory_projection_not_room_or_memory_index_authority"
_CANDIDATE_KINDS = {"room_fact", "room_decision", "user_preference", "project_rule"}
_APPROVAL_STATES = {"pending", "approved", "rejected"}
_PUBLISH_STATES = {"not_queued", "queued", "delivered", "failed", "conflict"}
_TARGET_SCOPES = {"room", "local_user", "project"}
_RUNTIME_STATES = {
    "disabled",
    "starting",
    "recovering",
    "rebuilding",
    "ready",
    "degraded",
    "stopping",
    "stopped",
    "failed",
    "unknown",
}


class RoomMemoryBindingReadStore(Protocol):
    def get_binding(
        self, *, conversation_id: str, scope_type: str = "room"
    ) -> Mapping[str, Any] | None: ...


class RoomMemoryGovernanceReadStore(Protocol):
    def list_candidates(
        self,
        *,
        conversation_id: str,
        approval_state: str | None = None,
        limit: int = 50,
    ) -> object: ...

    def count_candidates(
        self,
        conversation_id: str,
        *,
        approval_state: str | None = None,
    ) -> int: ...


class RoomMemoryDeliveryReadStore(Protocol):
    def count_outbox_by_state(self, *, conversation_id: str) -> Mapping[str, int]: ...


class RoomMemoryMessageDeliveryReadStore(Protocol):
    def count_message_outbox_by_state(self, *, conversation_id: str) -> Mapping[str, int]: ...


class RoomMemoryRecallReadStore(Protocol):
    def list_attempt_receipts(self, *, conversation_id: str, limit: int = 20) -> object: ...


class RoomMemoryAdvisoryReadStore(Protocol):
    def list_external_advisory_receipts(
        self, conversation_id: str, *, limit: int = 20
    ) -> object: ...


def _generated_at() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: object, *, maximum: int = 512) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned and len(cleaned.encode("utf-8")) <= maximum else None


def _identifier(value: object) -> str | None:
    return _text(value, maximum=200)


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _records(value: object, *keys: str) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        for key in keys:
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                return [item for item in nested if isinstance(item, Mapping)]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _identifiers(value: object, *, limit: int = 64) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    for item in value[:limit]:
        identifier = _identifier(item)
        if identifier is not None and identifier not in result:
            result.append(identifier)
    return result


def _safe_runtime_status(value: Mapping[str, Any] | None) -> dict[str, Any]:
    source = value or {}
    enabled = source.get("enabled") is True
    raw_state = _identifier(source.get("state")) or ("disabled" if not enabled else "unknown")
    state = raw_state if raw_state in _RUNTIME_STATES else "unknown"
    code = _identifier(source.get("code") or source.get("reason_code"))
    degraded = enabled and state not in {"ready", "starting"}
    return {
        "enabled": enabled,
        "degraded": degraded,
        "state": state,
        "code": code,
        "consecutive_restart_count": _integer(source.get("consecutive_restart_count")),
        "next_retry_at": _text(source.get("next_retry_at"), maximum=100),
        "last_healthy_at": _text(source.get("last_healthy_at"), maximum=100),
        "started_at": _text(source.get("started_at"), maximum=100),
        "updated_at": _text(source.get("updated_at") or source.get("heartbeat_at"), maximum=100),
    }


def _safe_source_refs(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    activity_ids = _identifiers(value.get("source_activity_ids"), limit=32)
    direct = _identifier(value.get("source_activity_id") or value.get("activity_id"))
    if direct is not None and direct not in activity_ids:
        activity_ids.append(direct)
    content_sha256 = _identifier(value.get("content_sha256") or value.get("evidence_sha256"))
    scope = _identifier(value.get("archive_scope") or value.get("scope_type"))
    return [
        {
            "activity_id": activity_id,
            "content_sha256": content_sha256,
            "archive_scope": scope,
        }
        for activity_id in activity_ids
    ]


def _safe_receipt(value: Mapping[str, Any]) -> dict[str, Any] | None:
    receipt_id = _identifier(value.get("receipt_id"))
    created_at = _text(
        value.get("created_at") or value.get("completed_at") or value.get("updated_at"),
        maximum=100,
    )
    participant_id = _identifier(value.get("participant_id"))
    status = _identifier(value.get("status")) or "unknown"
    if receipt_id is None:
        return {
            "receipt_id": None,
            "participant_id": participant_id,
            "status": status,
            "created_at": created_at,
        }
    item_refs = [
        safe
        for item in _records(value.get("item_refs"), "items", "refs")[:8]
        for safe in _safe_source_refs(item)
    ]
    source_ids = _identifiers(value.get("source_activity_ids"), limit=32)
    known = {item["activity_id"] for item in item_refs if item["activity_id"] is not None}
    item_refs.extend(
        {
            "activity_id": activity_id,
            "content_sha256": None,
            "archive_scope": None,
        }
        for activity_id in source_ids
        if activity_id not in known
    )
    return {
        "receipt_id": receipt_id,
        "participant_id": participant_id,
        "status": status,
        "schema_version": _identifier(
            value.get("memory_schema_version")
            or value.get("context_schema")
            or value.get("schema_version")
        ),
        "latency_ms": _integer(value.get("latency_ms")),
        "item_count": _integer(value.get("item_count")),
        "source_refs": item_refs,
        "evidence_sha256": _identifier(value.get("evidence_sha256")),
        "created_at": created_at,
    }


def _safe_candidate(value: Mapping[str, Any]) -> dict[str, Any] | None:
    candidate_id = _identifier(value.get("candidate_id"))
    conversation_id = _identifier(value.get("conversation_id"))
    digest = _identifier(
        value.get("candidate_digest") or value.get("content_sha256") or value.get("digest")
    )
    kind = _identifier(value.get("kind"))
    approval_state = _identifier(value.get("approval_state"))
    publish_state = _identifier(value.get("publish_state")) or "not_queued"
    target_scope = _identifier(value.get("target_scope")) or "room"
    content = _text(value.get("content"), maximum=8 * 1024)
    if (
        candidate_id is None
        or conversation_id is None
        or digest is None
        or kind not in _CANDIDATE_KINDS
        or approval_state not in _APPROVAL_STATES
        or publish_state not in _PUBLISH_STATES
        or target_scope not in _TARGET_SCOPES
        or content is None
    ):
        return None
    revision = _integer(value.get("revision"))
    actionable = approval_state == "pending"
    return {
        "candidate_id": candidate_id,
        "conversation_id": conversation_id,
        "author_participant_id": _identifier(value.get("author_participant_id")),
        "kind": kind,
        "content": content,
        "digest": digest,
        "source_activity_ids": _identifiers(value.get("source_activity_ids")),
        "approval_state": approval_state,
        "publish_state": publish_state,
        "target_scope": target_scope,
        "revision": revision,
        "reason_code": _identifier(value.get("reason_code")),
        "created_at": _text(value.get("created_at"), maximum=100),
        "resolved_at": _text(value.get("resolved_at"), maximum=100),
        "updated_at": _text(value.get("updated_at"), maximum=100),
        "actions": {
            "resolve": {
                "available": actionable,
                "method": "POST",
                "href": f"/api/chat/operator/memory-candidates/{candidate_id}/resolve",
                "expected_digest": digest,
                "expected_revision": revision,
                "allowed_decisions": ["approve", "reject"],
            }
        },
    }


def _safe_advisory_receipt(value: Mapping[str, Any]) -> dict[str, Any] | None:
    receipt_id = _identifier(value.get("receipt_id"))
    attempt_id = _identifier(value.get("attempt_id"))
    advisory_id = _identifier(value.get("advisory_id"))
    status = _identifier(value.get("status"))
    reason_code = _identifier(value.get("reason_code"))
    if None in {receipt_id, attempt_id, advisory_id, status, reason_code}:
        return None
    if status not in {"accepted", "duplicate", "rejected"}:
        return None
    return {
        "receipt_id": receipt_id,
        "attempt_id": attempt_id,
        "advisory_id": advisory_id,
        "status": status,
        "reason_code": reason_code,
        "candidate_digest": _identifier(value.get("candidate_digest")),
        "source_activity_ids": _identifiers(value.get("source_activity_ids"), limit=8),
        "created_at": _text(value.get("created_at"), maximum=100),
        "updated_at": _text(value.get("updated_at"), maximum=100),
    }


def _outbox_counts(value: Mapping[str, int]) -> dict[str, int]:
    pending = _integer(value.get("pending"))
    claimed = _integer(value.get("claimed"))
    failed = _integer(value.get("failed"))
    conflict = _integer(value.get("conflict"))
    delivered = _integer(value.get("delivered"))
    return {
        "backlog": pending + claimed + failed + conflict,
        "pending": pending,
        "processing": claimed,
        "failed": failed,
        "conflict": conflict,
        "delivered": delivered,
    }


def build_room_memory_projection(
    conversation_id: str,
    *,
    binding_store: RoomMemoryBindingReadStore,
    governance_store: RoomMemoryGovernanceReadStore,
    delivery_store: RoomMemoryDeliveryReadStore,
    recall_store: RoomMemoryRecallReadStore,
    advisory_store: RoomMemoryAdvisoryReadStore | None = None,
    message_delivery_store: RoomMemoryMessageDeliveryReadStore | None = None,
    runtime_status: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
    schema_version: str = ROOM_MEMORY_PROJECTION_SCHEMA,
) -> dict[str, Any]:
    if _identifier(conversation_id) is None:
        raise ValueError("room_memory_conversation_id_invalid")
    binding = binding_store.get_binding(conversation_id=conversation_id, scope_type="room")
    raw_candidates = governance_store.list_candidates(
        conversation_id=conversation_id, approval_state="pending", limit=20
    )
    pending_candidate_total = governance_store.count_candidates(
        conversation_id, approval_state="pending"
    )
    outbox_counts = delivery_store.count_outbox_by_state(conversation_id=conversation_id)
    raw_receipts = recall_store.list_attempt_receipts(conversation_id=conversation_id, limit=8)
    raw_advisory_receipts = (
        advisory_store.list_external_advisory_receipts(conversation_id, limit=8)
        if advisory_store is not None
        else []
    )
    candidates = [
        candidate
        for item in _records(raw_candidates, "candidates", "items")[:20]
        if (candidate := _safe_candidate(item)) is not None
        and candidate["conversation_id"] == conversation_id
        and candidate["approval_state"] == "pending"
    ]
    receipts = [
        receipt
        for item in _records(raw_receipts, "receipts", "items")[:8]
        if (receipt := _safe_receipt(item)) is not None
    ]
    advisory_receipts = [
        receipt
        for item in _records(raw_advisory_receipts, "receipts", "items")[:8]
        if (receipt := _safe_advisory_receipt(item)) is not None
    ]
    runtime = _safe_runtime_status(runtime_status)
    binding_present = isinstance(binding, Mapping)
    binding_source: Mapping[str, Any] = binding if isinstance(binding, Mapping) else {}
    projection = {
        "schema_version": schema_version,
        "projection_only": True,
        "proof_boundary": ROOM_MEMORY_PROOF_BOUNDARY,
        "generated_at": generated_at or _generated_at(),
        "conversation_id": conversation_id,
        "enabled": runtime["enabled"],
        "degraded": runtime["degraded"],
        "runtime": runtime,
        "binding": {
            "present": binding_present,
            "session_state": _identifier(binding_source.get("session_state")),
            "attachment_state": _identifier(binding_source.get("attachment_state")),
            "revision": _integer(binding_source.get("revision")),
            "updated_at": (
                _text(binding_source.get("updated_at"), maximum=100) if binding_present else None
            ),
        },
        "sync": _outbox_counts(outbox_counts),
        "recent_recalls": receipts,
        "advisory_receipts": advisory_receipts,
        "pending_candidate_total": pending_candidate_total,
        "pending_candidates": candidates,
    }
    if schema_version == ROOM_MEMORY_PROJECTION_V2_SCHEMA:
        profile = _identifier((runtime_status or {}).get("profile"))
        if profile not in {"full-local", "archive-only"}:
            profile = "archive-only"
        raw_message_counts = (
            message_delivery_store.count_message_outbox_by_state(conversation_id=conversation_id)
            if message_delivery_store is not None
            else {}
        )
        message_counts = raw_message_counts if isinstance(raw_message_counts, Mapping) else {}
        projection["profile"] = profile
        projection["capabilities"] = {
            "hybrid": profile == "full-local" and runtime["state"] == "ready",
            "message_ingest": profile == "full-local" and runtime["state"] == "ready",
            "agentic_advisory": profile == "full-local" and runtime["state"] == "ready",
        }
        projection["sync"]["messages"] = _outbox_counts(message_counts)
    return projection


def build_room_memory_projection_v2(
    conversation_id: str,
    *,
    binding_store: RoomMemoryBindingReadStore,
    governance_store: RoomMemoryGovernanceReadStore,
    delivery_store: RoomMemoryDeliveryReadStore,
    recall_store: RoomMemoryRecallReadStore,
    advisory_store: RoomMemoryAdvisoryReadStore | None = None,
    message_delivery_store: RoomMemoryMessageDeliveryReadStore | None = None,
    runtime_status: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the v2 capability-aware projection without changing v1 callers."""

    return build_room_memory_projection(
        conversation_id,
        binding_store=binding_store,
        governance_store=governance_store,
        delivery_store=delivery_store,
        recall_store=recall_store,
        advisory_store=advisory_store,
        message_delivery_store=message_delivery_store,
        runtime_status=runtime_status,
        generated_at=generated_at,
        schema_version=ROOM_MEMORY_PROJECTION_V2_SCHEMA,
    )
