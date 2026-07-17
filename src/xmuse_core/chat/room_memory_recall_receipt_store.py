"""Recall receipt and context binding persistence capability."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_common import (
    RoomMemoryStoreError,
    json_dumps,
    json_loads,
    new_id,
    require_text,
    timestamp,
)
from xmuse_core.chat.room_memory_contracts import (
    MEMORY_RECEIPT_STATUSES,
    MemoryReceiptItem,
    RoomMemoryContractError,
    normalize_receipt_items,
    require_digest,
    sha256_json,
)
from xmuse_core.chat.room_memory_source_conn import (
    resolve_recall_message_source_conn,
    resolve_recall_source_conn,
)


def _receipt_view(row: sqlite3.Row) -> dict[str, Any]:
    item_refs = [
        {
            "item_id": item["item_id"],
            "source_activity_ids": item["source_activity_ids"],
            "content_sha256": item["content_sha256"],
        }
        for item in json_loads(row["item_refs_json"], [])
    ]
    return {
        "schema_version": "room_attempt_memory_receipt/v1",
        "receipt_id": row["receipt_id"],
        "conversation_id": row["conversation_id"],
        "participant_id": row["participant_id"],
        "status": row["status"],
        "memory_schema_version": row["schema_version"],
        "latency_ms": int(row["latency_ms"]),
        "item_count": int(row["item_count"]),
        "item_refs": item_refs,
        "source_activity_ids": json_loads(row["source_activity_ids_json"], []),
        "evidence_sha256": row["evidence_sha256"],
        "context_payload_sha256": row["context_payload_sha256"],
        "context_submitted_at": row["context_submitted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class RoomMemoryRecallReceiptStore:
    """Attempt receipt authority and immutable context binding."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def record_attempt_memory_receipt(
        self,
        *,
        attempt_id: str,
        status: str,
        schema_version: str | None,
        latency_ms: int,
        items: Sequence[Mapping[str, Any]],
        evidence_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if status not in MEMORY_RECEIPT_STATUSES:
            raise RoomMemoryStoreError("room_memory_receipt_status_invalid")
        if (
            isinstance(latency_ms, bool)
            or not isinstance(latency_ms, int)
            or not 0 <= latency_ms <= 60000
        ):
            raise RoomMemoryStoreError("room_memory_receipt_latency_invalid")
        clean_schema = (
            require_text(schema_version, "room_memory_receipt_schema_invalid", maximum=128)
            if schema_version is not None
            else None
        )
        if status in {"ok", "empty"} and clean_schema is None:
            raise RoomMemoryStoreError("room_memory_receipt_schema_invalid")
        evidence_sha256 = require_digest(
            evidence_sha256, "room_memory_receipt_evidence_digest_invalid"
        )
        normalized: tuple[MemoryReceiptItem, ...] = normalize_receipt_items(list(items))
        if (status == "ok") != bool(normalized):
            if status == "ok" or normalized:
                raise RoomMemoryStoreError("room_memory_receipt_items_invalid")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                authority = conn.execute(
                    """select t.conversation_id, t.participant_id, a.correlation_id
                       from room_observation_attempts t
                       join room_observations o on o.observation_id = t.observation_id
                       join room_activities a on a.activity_id = o.activity_id
                       where t.attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if authority is None:
                    raise RoomMemoryStoreError("room_memory_receipt_attempt_not_found")
                item_refs: list[dict[str, Any]] = []
                for item in normalized:
                    item_ref: dict[str, Any] = {
                        "item_id": item.item_id,
                        "document_id": item.document_id,
                        "source_activity_ids": list(item.source_activity_ids),
                        "content_sha256": item.content_sha256,
                        "layer": item.layer,
                        "derived": item.derived,
                    }
                    if item.proof_source_type == "message":
                        item_ref.update(
                            {
                                "proof_source_type": "message",
                                "proof_session_id": item.proof_session_id,
                                "proof_source_ids": list(item.proof_source_ids),
                            }
                        )
                    item_refs.append(item_ref)
                resolved: list[dict[str, Any]] = []
                for item in normalized:
                    if item.proof_source_type == "message":
                        assert item.proof_session_id is not None
                        proof = resolve_recall_message_source_conn(
                            conn,
                            conversation_id=str(authority["conversation_id"]),
                            session_id=item.proof_session_id,
                            source_message_ids=item.proof_source_ids,
                            content_sha256=item.content_sha256,
                            item_text=item.text,
                            derived=item.derived,
                        )
                        if tuple(
                            sorted(
                                str(source["activity_id"]) for source in proof["source_activities"]
                            )
                        ) != tuple(sorted(item.source_activity_ids)):
                            raise RoomMemoryStoreError("room_memory_recall_source_rejected")
                        resolved.append(proof)
                    else:
                        resolved.append(
                            resolve_recall_source_conn(
                                conn,
                                conversation_id=str(authority["conversation_id"]),
                                document_id=item.document_id,
                                source_activity_ids=item.source_activity_ids,
                                content_sha256=item.content_sha256,
                                item_text=item.text,
                            )
                        )
                source_ids = sorted(
                    {
                        str(activity["activity_id"])
                        for item in resolved
                        for activity in item["source_activities"]
                    }
                )
                fingerprint = sha256_json(
                    {
                        "attempt_id": attempt_id,
                        "status": status,
                        "schema_version": clean_schema,
                        "latency_ms": latency_ms,
                        "items": item_refs,
                        "evidence_sha256": evidence_sha256,
                    }
                )
                prior = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if prior is not None:
                    if prior["request_fingerprint"] != fingerprint:
                        raise RoomMemoryStoreError("room_memory_receipt_conflict")
                    conn.rollback()
                    return _receipt_view(prior)
                receipt_id = new_id("memory_receipt")
                conn.execute(
                    """insert into room_memory_attempt_receipts
                       (receipt_id, attempt_id, conversation_id, participant_id,
                        correlation_id, status, schema_version, latency_ms, item_count,
                        item_refs_json, source_activity_ids_json, evidence_sha256,
                        request_fingerprint, created_at, updated_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        receipt_id,
                        attempt_id,
                        authority["conversation_id"],
                        authority["participant_id"],
                        authority["correlation_id"],
                        status,
                        clean_schema,
                        latency_ms,
                        len(normalized),
                        json_dumps(item_refs),
                        json_dumps(source_ids),
                        evidence_sha256,
                        fingerprint,
                        stamp,
                        stamp,
                    ),
                )
                row = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where receipt_id = ?""",
                    (receipt_id,),
                ).fetchone()
                assert row is not None
                result = _receipt_view(row)
                conn.commit()
                return result
            except (RoomMemoryContractError, RoomMemoryStoreError):
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise

    def bind_attempt_memory_context(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
        included_items: Sequence[Mapping[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        evidence_sha256 = require_digest(
            evidence_sha256, "room_memory_receipt_evidence_digest_invalid"
        )
        context_payload_sha256 = require_digest(
            context_payload_sha256, "room_memory_context_digest_invalid"
        )
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if row is None or row["evidence_sha256"] != evidence_sha256:
                    raise RoomMemoryStoreError("room_memory_receipt_not_found")
                skill = conn.execute(
                    """select context_payload_sha256 from room_attempt_skill_decisions
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if (
                    skill is not None
                    and skill["context_payload_sha256"] is not None
                    and skill["context_payload_sha256"] != context_payload_sha256
                ):
                    raise RoomMemoryStoreError("room_memory_context_digest_mismatch")
                if row["context_payload_sha256"] is not None:
                    stored_refs = json_loads(row["item_refs_json"], [])
                    stored_included = sorted(
                        str(item["item_id"])
                        for item in stored_refs
                        if item.get("context_included") is True
                    )
                    expected_included_ids = (
                        sorted(str(item.get("item_id")) for item in included_items)
                        if included_items is not None
                        else None
                    )
                    if row["context_payload_sha256"] != context_payload_sha256 or (
                        expected_included_ids is not None
                        and stored_included != expected_included_ids
                    ):
                        raise RoomMemoryStoreError("room_memory_context_receipt_conflict")
                    conn.rollback()
                    return _receipt_view(row)
                item_refs = json_loads(row["item_refs_json"], [])
                if included_items is not None:
                    recorded = {str(item.get("item_id")): item for item in item_refs}
                    included_id_set: set[str] = set()
                    for fitted in included_items:
                        item_id = str(fitted.get("item_id"))
                        source_ids = fitted.get("source_activity_ids")
                        text = fitted.get("text")
                        layer = fitted.get("layer")
                        derived = fitted.get("derived")
                        prior = recorded.get(item_id)
                        if (
                            prior is None
                            or not isinstance(source_ids, list)
                            or not all(isinstance(value, str) for value in source_ids)
                            or not isinstance(text, str)
                            or layer not in {"recall", "page", "core", "archival"}
                            or not isinstance(derived, bool)
                            or prior.get("source_activity_ids") != source_ids
                            or prior.get("layer") != layer
                            or prior.get("derived") is not derived
                            or prior.get("content_sha256")
                            != f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
                        ):
                            raise RoomMemoryStoreError("room_memory_context_items_invalid")
                        if item_id in included_id_set:
                            raise RoomMemoryStoreError("room_memory_context_items_invalid")
                        included_id_set.add(item_id)
                    for item in item_refs:
                        item["context_included"] = str(item.get("item_id")) in included_id_set
                conn.execute(
                    """update room_memory_attempt_receipts
                       set context_payload_sha256 = ?, context_submitted_at = ?,
                           item_refs_json = ?, updated_at = ? where attempt_id = ?""",
                    (context_payload_sha256, stamp, json_dumps(item_refs), stamp, attempt_id),
                )
                updated = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                assert updated is not None
                result = _receipt_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def list_attempt_receipts(
        self, conversation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_memory_attempt_receipts
                   where conversation_id = ?
                   order by created_at desc, receipt_id desc limit ?""",
                (conversation_id, clean_limit),
            ).fetchall()
        return [_receipt_view(row) for row in rows]


__all__ = ["RoomMemoryRecallReceiptStore"]
