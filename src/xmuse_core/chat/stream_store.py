from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ChatStream(BaseModel):
    id: str
    conversation_id: str
    author: str
    role: str
    request_id: str | None = None
    source_inbox_item_id: str | None = None
    content: str
    status: Literal["active", "done", "error"]
    first_delta_at: str | None = None
    created_at: str
    updated_at: str


class ChatStreamStore:
    def __init__(self, path: Path | str) -> None:
        from xmuse_core.chat.store import ChatStore

        self._path = Path(path)
        ChatStore(self._path)
        self._init_db()

    def start_or_reset(
        self,
        *,
        conversation_id: str,
        author: str,
        role: str,
        request_id: str | None,
        source_inbox_item_id: str | None = None,
    ) -> ChatStream:
        now = _utc_now()
        stream_id = self._stream_id(request_id)
        with self._connect() as conn:
            conn.execute(
                """
                insert into chat_streams (
                    id, conversation_id, author, role, request_id,
                    source_inbox_item_id, content, status, first_delta_at, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, '', 'active', null, ?, ?)
                on conflict(id) do update set
                    conversation_id = excluded.conversation_id,
                    author = excluded.author,
                    role = excluded.role,
                    request_id = excluded.request_id,
                    source_inbox_item_id = excluded.source_inbox_item_id,
                    content = '',
                    status = 'active',
                    first_delta_at = null,
                    updated_at = excluded.updated_at
                """,
                (
                    stream_id,
                    conversation_id,
                    author,
                    role,
                    request_id,
                    source_inbox_item_id,
                    now,
                    now,
                ),
            )
        return self.get(stream_id)

    def append_delta(self, stream_id: str, delta: str) -> ChatStream:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                update chat_streams
                set content = content || ?,
                    first_delta_at = coalesce(first_delta_at, ?),
                    updated_at = ?
                where id = ? and status = 'active'
                """,
                (delta, now, now, stream_id),
            )
        return self.get(stream_id)

    def finish(self, stream_id: str, *, status: Literal["done", "error"] = "done") -> ChatStream:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "update chat_streams set status = ?, updated_at = ? where id = ?",
                (status, now, stream_id),
            )
        return self.get(stream_id)

    def finish_active_for_source(
        self,
        *,
        conversation_id: str,
        source_inbox_item_id: str,
        status: Literal["done", "error"] = "done",
    ) -> list[ChatStream]:
        now = _utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id from chat_streams
                where conversation_id = ?
                  and source_inbox_item_id = ?
                  and status = 'active'
                order by rowid asc
                """,
                (conversation_id, source_inbox_item_id),
            ).fetchall()
            stream_ids = [str(row["id"]) for row in rows]
            if stream_ids:
                conn.executemany(
                    "update chat_streams set status = ?, updated_at = ? where id = ?",
                    [(status, now, stream_id) for stream_id in stream_ids],
                )
        return [self.get(stream_id) for stream_id in stream_ids]

    def list_active(self, conversation_id: str) -> list[ChatStream]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from chat_streams
                where conversation_id = ? and status = 'active'
                order by rowid asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, stream_id: str) -> ChatStream:
        with self._connect() as conn:
            row = conn.execute("select * from chat_streams where id = ?", (stream_id,)).fetchone()
        if row is None:
            raise KeyError(stream_id)
        return self._from_row(row)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists chat_streams (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    author text not null,
                    role text not null,
                    request_id text,
                    source_inbox_item_id text,
                    content text not null default '',
                    status text not null,
                    first_delta_at text,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("pragma table_info(chat_streams)").fetchall()
            }
            if "first_delta_at" not in columns:
                conn.execute("alter table chat_streams add column first_delta_at text")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _from_row(self, row: sqlite3.Row) -> ChatStream:
        return ChatStream(**dict(row))

    def _stream_id(self, request_id: str | None) -> str:
        if request_id:
            return f"stream_{request_id}"
        return f"stream_{uuid.uuid4().hex}"


class PeerTurnLatencyTraceStore:
    def __init__(self, path: Path | str) -> None:
        from xmuse_core.chat.store import ChatStore

        self._path = Path(path)
        ChatStore(self._path)
        self._init_db()

    def record(
        self,
        *,
        conversation_id: str,
        inbox_item_id: str,
        participant_id: str | None,
        target_role: str | None,
        message_created_at: str,
        inbox_claimed_at: str | None,
        delivery_started_at: float,
        provider_turn_started_at: float,
        first_delta_at: float | None,
        writeback_at: float,
        total_latency_ms: int,
        delivery_mode: str,
        degraded_reason: str | None,
        stage_timings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace = {
            "id": f"peer_latency_{inbox_item_id}",
            "conversation_id": conversation_id,
            "inbox_item_id": inbox_item_id,
            "participant_id": participant_id,
            "target_role": target_role,
            "message_created_at": message_created_at,
            "inbox_claimed_at": inbox_claimed_at,
            "delivery_started_at": delivery_started_at,
            "provider_turn_started_at": provider_turn_started_at,
            "first_delta_at": first_delta_at,
            "writeback_at": writeback_at,
            "total_latency_ms": total_latency_ms,
            "delivery_mode": delivery_mode,
            "degraded_reason": degraded_reason,
            "stage_timings": stage_timings or {},
        }
        stage_timings_json = json.dumps(trace["stage_timings"], sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert into peer_turn_latency_traces (
                    id, conversation_id, inbox_item_id, participant_id, target_role,
                    message_created_at, inbox_claimed_at, delivery_started_at,
                    provider_turn_started_at, first_delta_at, writeback_at,
                    total_latency_ms, delivery_mode, degraded_reason, stage_timings_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    participant_id = excluded.participant_id,
                    target_role = excluded.target_role,
                    inbox_claimed_at = excluded.inbox_claimed_at,
                    delivery_started_at = excluded.delivery_started_at,
                    provider_turn_started_at = excluded.provider_turn_started_at,
                    first_delta_at = excluded.first_delta_at,
                    writeback_at = excluded.writeback_at,
                    total_latency_ms = excluded.total_latency_ms,
                    delivery_mode = excluded.delivery_mode,
                    degraded_reason = excluded.degraded_reason,
                    stage_timings_json = excluded.stage_timings_json
                """,
                (
                    trace["id"],
                    conversation_id,
                    inbox_item_id,
                    participant_id,
                    target_role,
                    message_created_at,
                    inbox_claimed_at,
                    delivery_started_at,
                    provider_turn_started_at,
                    first_delta_at,
                    writeback_at,
                    total_latency_ms,
                    delivery_mode,
                    degraded_reason,
                    stage_timings_json,
                ),
            )
        return trace

    def list_recent(self, conversation_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from peer_turn_latency_traces
                where conversation_id = ?
                order by writeback_at desc
                limit ?
                """,
                (conversation_id, limit),
            ).fetchall()
        return [self._trace_from_row(row) for row in rows]

    def record_mcp_tool_stage(
        self,
        *,
        conversation_id: str,
        inbox_item_id: str,
        tool_name: str,
        called_at: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into peer_turn_mcp_tool_traces (
                    id, conversation_id, inbox_item_id, tool_name, called_at
                )
                values (?, ?, ?, ?, ?)
                on conflict(id) do nothing
                """,
                (
                    f"peer_mcp_tool_{inbox_item_id}_{tool_name}",
                    conversation_id,
                    inbox_item_id,
                    tool_name,
                    called_at,
                ),
            )

    def list_mcp_tool_stages(
        self,
        conversation_id: str,
        inbox_item_id: str,
    ) -> dict[str, dict[str, float]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select tool_name, called_at from peer_turn_mcp_tool_traces
                where conversation_id = ? and inbox_item_id = ?
                order by called_at asc
                """,
                (conversation_id, inbox_item_id),
            ).fetchall()
        return {
            row["tool_name"]: {"at": row["called_at"]}
            for row in rows
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists peer_turn_latency_traces (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    inbox_item_id text not null,
                    participant_id text,
                    target_role text,
                    message_created_at text not null,
                    inbox_claimed_at text,
                    delivery_started_at real not null,
                    provider_turn_started_at real not null,
                    first_delta_at real,
                    writeback_at real not null,
                    total_latency_ms integer not null,
                    delivery_mode text not null,
                    degraded_reason text,
                    stage_timings_json text not null default '{}'
                )
                """
            )
            conn.execute(
                """
                create table if not exists peer_turn_mcp_tool_traces (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    inbox_item_id text not null,
                    tool_name text not null,
                    called_at real not null
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("pragma table_info(peer_turn_latency_traces)").fetchall()
            }
            if "stage_timings_json" not in columns:
                conn.execute(
                    "alter table peer_turn_latency_traces "
                    "add column stage_timings_json text not null default '{}'"
                )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _trace_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        trace = dict(row)
        raw_stage_timings = trace.pop("stage_timings_json", None)
        try:
            parsed = json.loads(raw_stage_timings) if isinstance(raw_stage_timings, str) else {}
        except json.JSONDecodeError:
            parsed = {}
        trace["stage_timings"] = parsed if isinstance(parsed, dict) else {}
        return trace


__all__ = ["ChatStream", "ChatStreamStore", "PeerTurnLatencyTraceStore"]
