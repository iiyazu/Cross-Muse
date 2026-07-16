"""Recall source proof and request persistence capability."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_common import (
    MEMORY_BINDING_SCOPES,
    MEMORY_DOCUMENT_PREFIX,
    RoomMemoryStoreError,
)
from xmuse_core.chat.room_memory_source_conn import (
    activity_source_conn,
    resolve_recall_message_source_conn,
    resolve_recall_source_conn,
)


class RoomMemoryRecallSourceStore:
    """Source proof and bounded recall request authority."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def get_activity_source(self, *, conversation_id: str, activity_id: str) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return activity_source_conn(
                conn, conversation_id=conversation_id, activity_id=activity_id
            )

    def resolve_recall_source(
        self,
        *,
        conversation_id: str,
        document_id: str,
        source_activity_ids: Sequence[str],
        content_sha256: str,
        item_text: str,
    ) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return resolve_recall_source_conn(
                conn,
                conversation_id=conversation_id,
                document_id=document_id,
                source_activity_ids=source_activity_ids,
                content_sha256=content_sha256,
                item_text=item_text,
            )

    def resolve_recall_message_source(
        self,
        *,
        conversation_id: str,
        session_id: str,
        source_message_ids: Sequence[str],
        content_sha256: str,
        item_text: str,
        derived: bool = False,
    ) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return resolve_recall_message_source_conn(
                conn,
                conversation_id=conversation_id,
                session_id=session_id,
                source_message_ids=source_message_ids,
                content_sha256=content_sha256,
                item_text=item_text,
                derived=derived,
            )

    def build_recall_request(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        correlation_id: str,
        causal_activity_ids: Sequence[str],
    ) -> dict[str, Any]:
        causal = tuple(sorted(set(causal_activity_ids)))
        if len(causal) != len(causal_activity_ids) or len(causal) > 64:
            raise RoomMemoryStoreError("room_memory_recall_causal_scope_invalid")
        with self._database.connect(readonly=True) as conn:
            authority = conn.execute(
                """select t.attempt_id, t.conversation_id, t.participant_id,
                          o.activity_id, a.correlation_id
                   from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                   join room_activities a on a.activity_id = o.activity_id
                   where t.attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if (
                authority is None
                or authority["conversation_id"] != conversation_id
                or authority["correlation_id"] != correlation_id
            ):
                raise RoomMemoryStoreError("room_memory_recall_authority_invalid")
            if causal:
                placeholders = ",".join("?" for _ in causal)
                count = int(
                    conn.execute(
                        f"""select count(*) from room_activities where conversation_id = ?
                            and activity_id in ({placeholders})""",
                        (conversation_id, *causal),
                    ).fetchone()[0]
                )
                if count != len(causal):
                    raise RoomMemoryStoreError("room_memory_recall_causal_scope_invalid")
            bindings = conn.execute(
                """select * from room_memory_bindings where conversation_id = ?
                   order by scope_type""",
                (conversation_id,),
            ).fetchall()
            by_scope = {str(row["scope_type"]): row for row in bindings}
            if set(by_scope) != MEMORY_BINDING_SCOPES or any(
                row["session_state"] != "bound" or row["attachment_state"] != "attached"
                for row in bindings
            ):
                raise RoomMemoryStoreError("room_memory_recall_unavailable")
            session_ids = {str(row["session_id"]) for row in bindings}
            if len(session_ids) != 1:
                raise RoomMemoryStoreError("room_memory_recall_unavailable")
            source = activity_source_conn(
                conn,
                conversation_id=conversation_id,
                activity_id=str(authority["activity_id"]),
            )
            correlated = {
                str(row["activity_id"])
                for row in conn.execute(
                    """select activity_id from room_activities
                       where conversation_id = ? and correlation_id = ?""",
                    (conversation_id, correlation_id),
                )
            }
            excluded = tuple(sorted(correlated | set(causal)))
            query = str(source["content"])
            if len(query.encode("utf-8")) > 4096:
                query = query.encode("utf-8")[:4096].decode("utf-8", errors="ignore")
            build_context_request = {
                "task": ("Recall prior source-backed Room evidence relevant to this observation."),
                "budget": 800,
                "retrieval_query": query,
                "include_global_core": False,
            }
            return {
                "schema_version": "room_memory_recall_request/v1",
                "session_id": next(iter(session_ids)),
                "archive_ids": [str(by_scope[scope]["archive_id"]) for scope in sorted(by_scope)],
                "build_context_request": build_context_request,
                "task": build_context_request["task"],
                "retrieval_query": query,
                "budget": 800,
                "top_k": 8,
                "max_response_bytes": 8192,
                "excluded_activity_ids": list(excluded),
                "excluded_document_ids": [
                    f"{MEMORY_DOCUMENT_PREFIX}{activity_id}" for activity_id in excluded
                ],
            }


__all__ = ["RoomMemoryRecallSourceStore"]
