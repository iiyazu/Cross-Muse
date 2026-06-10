from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ChatDispatchQueueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    conversation_id: str
    source: Literal["user", "connector", "agent"]
    target: str = Field(min_length=1)
    status: Literal["queued", "processing", "dispatched", "failed", "canceled"]
    auto_execute: bool
    proposal_id: str | None = None
    resolution_id: str | None = None
    collaboration_run_id: str | None = None
    artifact_ref: str | None = None
    dispatch_policy: str = Field(min_length=1)
    claimed_by: str | None = None
    claimed_at: str | None = None
    provider_run_ref: str | None = None
    dispatch_evidence: str | None = None
    failure_reason: str | None = None
    completed_at: str | None = None
    created_at: str
    updated_at: str


class ChatDispatchQueueStore:
    """Chat-owned durable queue for structured dispatch intents.

    This is the control-plane record that a proposal/artifact passed the groupchat
    dispatch gate and may enter real-provider execution. It does not execute work.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def enqueue_agent_auto_dispatch(
        self,
        *,
        conversation_id: str,
        proposal_id: str,
        resolution_id: str,
        collaboration_run_id: str | None,
        artifact_ref: str,
        target: str = "execute",
        dispatch_policy: str = "real_provider_allowed",
    ) -> ChatDispatchQueueEntry:
        now = _utc_now()
        entry_id = f"dispatch:{conversation_id}:{resolution_id}:{target}"
        with self._connect() as conn:
            conn.execute(
                """
                insert into chat_dispatch_queue (
                    entry_id, conversation_id, source, target, status, auto_execute,
                    proposal_id, resolution_id, collaboration_run_id, artifact_ref,
                    dispatch_policy, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(entry_id) do update set
                    updated_at = excluded.updated_at
                """,
                (
                    entry_id,
                    conversation_id,
                    "agent",
                    _required(target, "target"),
                    "queued",
                    1,
                    proposal_id,
                    resolution_id,
                    collaboration_run_id,
                    _required(artifact_ref, "artifact_ref"),
                    _required(dispatch_policy, "dispatch_policy"),
                    now,
                    now,
                ),
            )
        return self.get(entry_id)

    def claim_next_auto_dispatch(
        self,
        *,
        conversation_id: str,
        claimed_by: str,
        claim_ttl_s: int = 900,
    ) -> ChatDispatchQueueEntry | None:
        now_dt = datetime.now(UTC).replace(microsecond=0)
        now = now_dt.isoformat().replace("+00:00", "Z")
        stale_before = (
            now_dt - timedelta(seconds=max(0, int(claim_ttl_s)))
        ).isoformat().replace("+00:00", "Z")
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """
                select entry_id from chat_dispatch_queue
                where conversation_id = ?
                  and (
                      status = 'queued'
                      or (
                          status = 'processing'
                          and claimed_at is not null
                          and claimed_at <= ?
                      )
                  )
                  and auto_execute = 1
                order by rowid asc
                limit 1
                """,
                (conversation_id, stale_before),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            entry_id = row["entry_id"]
            conn.execute(
                """
                update chat_dispatch_queue
                set status = 'processing',
                    claimed_by = ?,
                    claimed_at = ?,
                    updated_at = ?
                where entry_id = ?
                """,
                (_required(claimed_by, "claimed_by"), now, now, entry_id),
            )
            conn.commit()
        return self.get(str(entry_id))

    def mark_dispatched(
        self,
        entry_id: str,
        *,
        provider_run_ref: str,
        dispatch_evidence: str,
    ) -> ChatDispatchQueueEntry:
        now = _utc_now()
        with self._connect() as conn:
            updated = conn.execute(
                """
                update chat_dispatch_queue
                set status = 'dispatched',
                    provider_run_ref = ?,
                    dispatch_evidence = ?,
                    failure_reason = null,
                    completed_at = ?,
                    updated_at = ?
                where entry_id = ?
                  and status = 'processing'
                """,
                (
                    _required(provider_run_ref, "provider_run_ref"),
                    _required(dispatch_evidence, "dispatch_evidence"),
                    now,
                    now,
                    entry_id,
                ),
            ).rowcount
        if updated != 1:
            raise ValueError("dispatch queue entry must be processing to mark dispatched")
        return self.get(entry_id)

    def mark_failed(
        self,
        entry_id: str,
        *,
        failure_reason: str,
    ) -> ChatDispatchQueueEntry:
        now = _utc_now()
        with self._connect() as conn:
            updated = conn.execute(
                """
                update chat_dispatch_queue
                set status = 'failed',
                    failure_reason = ?,
                    completed_at = ?,
                    updated_at = ?
                where entry_id = ?
                  and status in ('queued', 'processing')
                """,
                (_required(failure_reason, "failure_reason"), now, now, entry_id),
            ).rowcount
        if updated != 1:
            raise ValueError("dispatch queue entry must be queued or processing to mark failed")
        return self.get(entry_id)

    def get(self, entry_id: str) -> ChatDispatchQueueEntry:
        with self._connect() as conn:
            row = conn.execute(
                "select * from chat_dispatch_queue where entry_id = ?",
                (entry_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown chat dispatch queue entry: {entry_id}")
        return self._from_row(row)

    def list_entries(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatDispatchQueueEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from chat_dispatch_queue
                where conversation_id = ?
                order by rowid desc
                limit ?
                """,
                (conversation_id, int(limit)),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists chat_dispatch_queue (
                    entry_id text primary key,
                    conversation_id text not null,
                    source text not null,
                    target text not null,
                    status text not null,
                    auto_execute integer not null,
                    proposal_id text,
                    resolution_id text,
                    collaboration_run_id text,
                    artifact_ref text,
                    dispatch_policy text not null,
                    claimed_by text,
                    claimed_at text,
                    provider_run_ref text,
                    dispatch_evidence text,
                    failure_reason text,
                    completed_at text,
                    created_at text not null,
                    updated_at text not null
                );

                create index if not exists idx_chat_dispatch_queue_conversation_status
                    on chat_dispatch_queue(conversation_id, status);
                """
            )
            _ensure_column(conn, "chat_dispatch_queue", "claimed_by", "text")
            _ensure_column(conn, "chat_dispatch_queue", "claimed_at", "text")
            _ensure_column(conn, "chat_dispatch_queue", "provider_run_ref", "text")
            _ensure_column(conn, "chat_dispatch_queue", "dispatch_evidence", "text")
            _ensure_column(conn, "chat_dispatch_queue", "failure_reason", "text")
            _ensure_column(conn, "chat_dispatch_queue", "completed_at", "text")

    def _from_row(self, row: sqlite3.Row) -> ChatDispatchQueueEntry:
        payload = dict(row)
        return ChatDispatchQueueEntry(
            entry_id=payload["entry_id"],
            conversation_id=payload["conversation_id"],
            source=payload["source"],
            target=payload["target"],
            status=payload["status"],
            auto_execute=bool(payload["auto_execute"]),
            proposal_id=payload["proposal_id"],
            resolution_id=payload["resolution_id"],
            collaboration_run_id=payload["collaboration_run_id"],
            artifact_ref=payload["artifact_ref"],
            dispatch_policy=payload["dispatch_policy"],
            claimed_by=payload["claimed_by"],
            claimed_at=payload["claimed_at"],
            provider_run_ref=payload["provider_run_ref"],
            dispatch_evidence=payload["dispatch_evidence"],
            failure_reason=payload["failure_reason"],
            completed_at=payload["completed_at"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"pragma table_info({table_name})").fetchall()
    }
    if column_name in columns:
        return
    conn.execute(f"alter table {table_name} add column {column_name} {column_type}")


def _required(value: str, name: str) -> str:
    clean = value.strip() if isinstance(value, str) else ""
    if not clean:
        raise ValueError(f"{name} must not be blank")
    return clean
