"""Externally proposed MemoryOS advisory governance capability."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_common import (
    RoomMemoryStoreError,
    json_dumps,
    json_loads,
    new_id,
    timestamp,
)
from xmuse_core.chat.room_memory_contracts import MemoryCandidateInput, sha256_json
from xmuse_core.chat.room_memory_source_conn import (
    resolve_external_source_activity_ids_conn,
)


class RoomMemoryAdvisoryStore:
    """Re-prove MemoryOS suggestions before entering Room governance."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def record_external_advisories(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        advisories: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Re-prove MemoryOS kernel suggestions and enter Room governance.

        MemoryOS is only a proposer.  Source IDs are translated through the
        Room message-delivery ledger or visible activity table.  Historical
        recalled sources are allowed through the explicitly external path;
        ordinary Agent candidates still use the causal batch authority.  Every
        advisory receives a durable accepted/duplicate/rejected receipt.
        """

        if not advisories or len(advisories) > 32:
            return []
        from xmuse_core.chat.room_memory_governance_store import record_memory_candidates_conn

        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                authority = conn.execute(
                    """select t.observation_id, t.batch_id, t.participant_id,
                              b.primary_observation_id
                       from room_observation_attempts t
                       left join room_observation_batches b on b.batch_id = t.batch_id
                       where t.attempt_id = ? and t.conversation_id = ?""",
                    (attempt_id, conversation_id),
                ).fetchone()
                if authority is None or authority["batch_id"] is None:
                    raise RoomMemoryStoreError("room_memory_advisory_authority_invalid")
                batch_id = str(authority["batch_id"])
                primary_observation_id = str(
                    authority["primary_observation_id"] or authority["observation_id"]
                )
                batch_activity_ids = {
                    str(row["activity_id"])
                    for row in conn.execute(
                        """select activity_id from room_observation_batch_members
                           where batch_id = ?""",
                        (batch_id,),
                    ).fetchall()
                }
                if not batch_activity_ids:
                    batch_activity_ids.add(
                        str(
                            conn.execute(
                                "select activity_id from room_observations "
                                "where observation_id = ?",
                                (primary_observation_id,),
                            ).fetchone()[0]
                        )
                    )
                candidates: list[tuple[str, str, MemoryCandidateInput]] = []
                for advisory in advisories:
                    advisory_id = advisory.get("advisory_id")
                    fingerprint = advisory.get("fingerprint")
                    if not isinstance(advisory_id, str) or not advisory_id:
                        continue
                    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                        fingerprint = sha256_json(
                            {
                                "advisory_id": advisory_id,
                                "proposal_type": advisory.get("proposal_type"),
                                "content": advisory.get("content"),
                                "source_refs": advisory.get("source_refs"),
                            }
                        ).removeprefix("sha256:")
                    prior = conn.execute(
                        """select advisory_fingerprint, status, candidate_digest
                           from room_memory_advisory_receipts
                           where attempt_id = ? and advisory_id = ?""",
                        (attempt_id, advisory_id),
                    ).fetchone()
                    if prior is not None:
                        if prior["advisory_fingerprint"] != fingerprint:
                            self._write_advisory_receipt_conn(
                                conn,
                                conversation_id=conversation_id,
                                attempt_id=attempt_id,
                                advisory_id=advisory_id,
                                fingerprint=fingerprint,
                                status="rejected",
                                reason_code="room_memory_advisory_conflict",
                                source_activity_ids=(),
                                candidate_digest=None,
                                stamp=stamp,
                            )
                        continue
                    proposal_type = advisory.get("proposal_type")
                    kind: Literal["room_fact", "project_rule"] | None
                    if proposal_type == "archive_write":
                        kind = "room_fact"
                    elif proposal_type == "core_promotion_request":
                        kind = "project_rule"
                    else:
                        kind = None
                    content = advisory.get("content")
                    refs = advisory.get("source_refs")
                    if (
                        kind is None
                        or not isinstance(content, str)
                        or not content.strip()
                        or not isinstance(refs, list)
                        or not refs
                        or len(refs) > 8
                    ):
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=advisory_id,
                            fingerprint=fingerprint,
                            status="rejected",
                            reason_code="memoryos_advisory_contract_invalid",
                            source_activity_ids=(),
                            candidate_digest=None,
                            stamp=stamp,
                        )
                        continue
                    source_activity_ids = resolve_external_source_activity_ids_conn(
                        conn,
                        conversation_id=conversation_id,
                        source_refs=refs,
                    )
                    if not source_activity_ids:
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=advisory_id,
                            fingerprint=fingerprint,
                            status="rejected",
                            reason_code="room_memory_advisory_source_rejected",
                            source_activity_ids=(),
                            candidate_digest=None,
                            stamp=stamp,
                        )
                        continue
                    candidates.append(
                        (
                            advisory_id,
                            fingerprint,
                            MemoryCandidateInput(
                                kind=kind,
                                content=content.strip(),
                                source_activity_ids=tuple(source_activity_ids),
                            ),
                        )
                    )
                unique: list[MemoryCandidateInput] = []
                candidate_meta: dict[str, tuple[str, str, tuple[str, ...]]] = {}
                seen: set[str] = set()
                for advisory_id, fingerprint, item in candidates:
                    digest = sha256_json(
                        {
                            "conversation_id": conversation_id,
                            "author_participant_id": authority["participant_id"],
                            "kind": item.kind,
                            "content": item.content,
                            "source_activity_ids": tuple(sorted(item.source_activity_ids)),
                        }
                    )
                    if digest in seen:
                        continue
                    seen.add(digest)
                    existing = conn.execute(
                        """select 1 from room_memory_candidates
                           where conversation_id = ? and candidate_digest = ? limit 1""",
                        (conversation_id, digest),
                    ).fetchone()
                    if existing is None:
                        unique.append(item)
                        candidate_meta[digest] = (
                            advisory_id,
                            fingerprint,
                            tuple(sorted(item.source_activity_ids)),
                        )
                    else:
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=advisory_id,
                            fingerprint=fingerprint,
                            status="duplicate",
                            reason_code="room_memory_advisory_duplicate",
                            source_activity_ids=item.source_activity_ids,
                            candidate_digest=digest,
                            stamp=stamp,
                        )
                if not unique:
                    conn.commit()
                    return []
                result = record_memory_candidates_conn(
                    conn,
                    conversation_id=conversation_id,
                    author_participant_id=str(authority["participant_id"]),
                    source_observation_id=primary_observation_id,
                    source_batch_id=batch_id,
                    source_attempt_id=attempt_id,
                    batch_activity_ids=batch_activity_ids,
                    candidates=unique[:3],
                    stamp=stamp,
                    allow_external_sources=True,
                )
                for reference in result:
                    digest = str(reference["candidate_digest"])
                    meta = candidate_meta.get(digest)
                    if meta is not None:
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=meta[0],
                            fingerprint=meta[1],
                            status="accepted",
                            reason_code="room_memory_advisory_accepted",
                            source_activity_ids=meta[2],
                            candidate_digest=digest,
                            stamp=stamp,
                        )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def record_external_advisory_failure(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        reason_code: str,
        now: datetime | None = None,
    ) -> None:
        """Persist a safe bridge failure without changing recall authority."""

        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                self._write_advisory_receipt_conn(
                    conn,
                    conversation_id=conversation_id,
                    attempt_id=attempt_id,
                    advisory_id="__bridge__",
                    fingerprint=sha256_json({"attempt_id": attempt_id, "reason": reason_code}),
                    status="rejected",
                    reason_code=reason_code[:128],
                    source_activity_ids=(),
                    candidate_digest=None,
                    stamp=stamp,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _write_advisory_receipt_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        attempt_id: str,
        advisory_id: str,
        fingerprint: str,
        status: str,
        reason_code: str,
        source_activity_ids: Sequence[str],
        candidate_digest: str | None,
        stamp: str,
    ) -> None:
        existing = conn.execute(
            """select advisory_fingerprint from room_memory_advisory_receipts
               where attempt_id = ? and advisory_id = ?""",
            (attempt_id, advisory_id),
        ).fetchone()
        if existing is not None:
            return
        conn.execute(
            """insert into room_memory_advisory_receipts
               (receipt_id, conversation_id, attempt_id, advisory_id,
                advisory_fingerprint, status, reason_code, candidate_digest,
                source_activity_ids_json, created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id("memory_advisory_receipt"),
                conversation_id,
                attempt_id,
                advisory_id[:256],
                fingerprint[:128],
                status,
                reason_code[:128],
                candidate_digest,
                json_dumps(list(source_activity_ids)[:8]),
                stamp,
                stamp,
            ),
        )

    def list_external_advisory_receipts(
        self, conversation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_memory_advisory_receipts
                   where conversation_id = ?
                   order by created_at desc, receipt_id desc limit ?""",
                (conversation_id, clean_limit),
            ).fetchall()
        return [
            {
                "schema_version": "room_memory_advisory_receipt/v1",
                "receipt_id": row["receipt_id"],
                "conversation_id": row["conversation_id"],
                "attempt_id": row["attempt_id"],
                "advisory_id": row["advisory_id"],
                "status": row["status"],
                "reason_code": row["reason_code"],
                "candidate_digest": row["candidate_digest"],
                "source_activity_ids": json_loads(row["source_activity_ids_json"], []),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]


__all__ = ["RoomMemoryAdvisoryStore"]
