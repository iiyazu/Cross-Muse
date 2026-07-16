"""Disposable Room Agent response previews.

The stream cache is deliberately separate from ``chat.db``.  It is a bounded,
single-writer UI projection and never participates in Room completion,
causality, memory, or execution authority.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import Mapping
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase

STREAM_CACHE_SCHEMA = "room_agent_stream_cache/v1"
STREAM_PROJECTION_SCHEMA = "room_agent_stream_projection/v1"
STREAM_PROOF_BOUNDARY = "provider_preview_not_room_or_codex_authority"
STREAM_CACHE_RELATIVE_PATH = Path("runtime") / "room-agent-streams.sqlite3"
STREAM_STATES = frozenset({"streaming", "committing", "resolved", "invalidated"})
MAX_RAW_BYTES = 32 * 1024
MAX_PREVIEW_BYTES = 16 * 1024
STREAM_FLUSH_INTERVAL_S = 0.1
STREAM_TOMBSTONE_TTL_S = 60

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_SECRET = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]\s*\S+)")
_ABSOLUTE_PATH = re.compile(
    r"(?:(?<![:A-Za-z0-9._-])/(?!/)[A-Za-z0-9._~+-]+(?:/[A-Za-z0-9._~+@%=-]+)*|"
    r"\b[A-Za-z]:\\[^\s'\"`]+)"
)


class RoomAgentStreamError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def room_agent_stream_cache_path(xmuse_root: Path | str) -> Path:
    return Path(xmuse_root).expanduser().resolve() / STREAM_CACHE_RELATIVE_PATH


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _truncate_utf8(value: str, maximum: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return value, False
    return encoded[:maximum].decode("utf-8", errors="ignore"), True


def sanitize_stream_preview(value: str, *, final: bool) -> tuple[str, bool]:
    """Return a redacted, bounded prefix safe to copy into the UI cache.

    While a token is still being streamed, its trailing non-whitespace run is
    withheld.  This prevents a secret or absolute path split across deltas from
    being published before the complete run can be redacted.
    """

    text = value.replace("\x00", "").encode("utf-8", errors="replace").decode("utf-8")
    if not final and text:
        boundary = max((index for index, char in enumerate(text) if char.isspace()), default=-1)
        text = text[: boundary + 1] if boundary >= 0 else ""
    text = _BEARER.sub("[redacted]", text)
    text = _SECRET.sub("[redacted]", text)
    text = _ABSOLUTE_PATH.sub("[path]", text)
    return _truncate_utf8(text, MAX_PREVIEW_BYTES)


def _private_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise RoomAgentStreamError("room_agent_stream_cache_symlink_rejected")
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            path.chmod(0o600)


class RoomAgentStreamCache:
    """Synchronous SQLite cache used through one async projector writer."""

    def __init__(self, xmuse_root: Path | str) -> None:
        self.root = Path(xmuse_root).expanduser().resolve()
        self.path = room_agent_stream_cache_path(self.root)

    def initialize_boot(self, epoch: str) -> None:
        _private_database(self.path)
        with closing(sqlite3.connect(self.path, timeout=30.0)) as conn:
            conn.execute("pragma journal_mode = wal")
            conn.execute("pragma foreign_keys = on")
            conn.execute(
                """create table if not exists stream_meta (
                       singleton integer primary key check(singleton = 1),
                       schema_version text not null,
                       epoch text not null,
                       next_seq integer not null check(next_seq >= 1),
                       created_at text not null
                   )"""
            )
            conn.execute(
                """create table if not exists room_agent_streams (
                       stream_id text primary key,
                       conversation_id text not null,
                       participant_id text not null,
                       observation_id text not null,
                       attempt_id text not null,
                       state text not null check(state in
                           ('streaming', 'committing', 'resolved', 'invalidated')),
                       content text not null,
                       truncated integer not null check(truncated in (0, 1)),
                       stream_seq integer not null,
                       started_at text not null,
                       updated_at text not null,
                       closed_at text,
                       unique(conversation_id, attempt_id)
                   )"""
            )
            conn.execute(
                """create index if not exists room_agent_streams_conversation_seq
                   on room_agent_streams(conversation_id, stream_seq)"""
            )
            row = conn.execute(
                "select schema_version from stream_meta where singleton = 1"
            ).fetchone()
            if row is not None and row[0] != STREAM_CACHE_SCHEMA:
                raise RoomAgentStreamError("room_agent_stream_cache_schema_unsupported")
            stamp = _utc_now()
            conn.execute("delete from room_agent_streams")
            conn.execute(
                """insert into stream_meta(singleton, schema_version, epoch, next_seq, created_at)
                   values (1, ?, ?, 1, ?)
                   on conflict(singleton) do update set epoch = excluded.epoch,
                       next_seq = 1, created_at = excluded.created_at""",
                (STREAM_CACHE_SCHEMA, epoch, stamp),
            )
            conn.commit()
        os.chmod(self.path, 0o600)

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = f"file:{self.path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        else:
            conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _next_seq(conn: sqlite3.Connection) -> int:
        row = conn.execute("select next_seq from stream_meta where singleton = 1").fetchone()
        if row is None:
            raise RoomAgentStreamError("room_agent_stream_cache_uninitialized")
        seq = int(row[0])
        conn.execute("update stream_meta set next_seq = ? where singleton = 1", (seq + 1,))
        return seq

    def open_stream(
        self,
        *,
        stream_id: str,
        conversation_id: str,
        participant_id: str,
        observation_id: str,
        attempt_id: str,
        started_at: str,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute("begin immediate")
            seq = self._next_seq(conn)
            conn.execute(
                """insert into room_agent_streams(
                       stream_id, conversation_id, participant_id, observation_id, attempt_id,
                       state, content, truncated, stream_seq, started_at, updated_at, closed_at
                   ) values (?, ?, ?, ?, ?, 'streaming', '', 0, ?, ?, ?, null)""",
                (
                    stream_id,
                    conversation_id,
                    participant_id,
                    observation_id,
                    attempt_id,
                    seq,
                    started_at,
                    started_at,
                ),
            )
            conn.commit()

    def update_stream(
        self,
        stream_id: str,
        *,
        state: str,
        content: str,
        truncated: bool,
        closed: bool = False,
    ) -> None:
        if state not in STREAM_STATES:
            raise RoomAgentStreamError("room_agent_stream_state_invalid")
        stamp = _utc_now()
        with closing(self._connect()) as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select state from room_agent_streams where stream_id = ?", (stream_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return
            if row[0] in {"resolved", "invalidated"}:
                conn.rollback()
                return
            seq = self._next_seq(conn)
            conn.execute(
                """update room_agent_streams set state = ?, content = ?, truncated = ?,
                       stream_seq = ?, updated_at = ?, closed_at = ? where stream_id = ?""",
                (state, content, int(truncated), seq, stamp, stamp if closed else None, stream_id),
            )
            self._trim(conn, stamp)
            conn.commit()

    def prune_tombstones(self, *, now: str | None = None) -> bool:
        stamp = now or _utc_now()
        with closing(self._connect()) as conn:
            conn.execute("begin immediate")
            deleted = self._trim(conn, stamp)
            if deleted:
                self._next_seq(conn)
            conn.commit()
        return deleted

    @staticmethod
    def _trim(conn: sqlite3.Connection, stamp: str) -> bool:
        cutoff = (
            (
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                - timedelta(seconds=STREAM_TOMBSTONE_TTL_S)
            )
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        cursor = conn.execute(
            "delete from room_agent_streams where closed_at is not null and closed_at < ?",
            (cutoff,),
        )
        return cursor.rowcount > 0

    def read_raw(self, conversation_id: str) -> dict[str, Any]:
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise RoomAgentStreamError("room_agent_stream_cache_symlink_rejected")
        if not self.path.exists():
            return {
                "projection_available": False,
                "epoch": None,
                "stream_seq": 0,
                "streams": [],
            }
        try:
            with closing(self._connect(readonly=True)) as conn:
                meta = conn.execute(
                    "select schema_version, epoch, next_seq from stream_meta where singleton = 1"
                ).fetchone()
                if meta is None or meta["schema_version"] != STREAM_CACHE_SCHEMA:
                    raise RoomAgentStreamError("room_agent_stream_cache_schema_unsupported")
                rows = conn.execute(
                    """select * from room_agent_streams where conversation_id = ?
                       order by started_at, stream_id""",
                    (conversation_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RoomAgentStreamError("room_agent_stream_cache_unavailable") from exc
        return {
            "projection_available": True,
            "epoch": str(meta["epoch"]),
            "stream_seq": max(0, int(meta["next_seq"]) - 1),
            "streams": [dict(row) for row in rows],
        }


@dataclass
class _StreamBuffer:
    raw: str
    state: Literal["streaming", "committing", "resolved", "invalidated"]
    last_flush: float
    truncated: bool = False
    published_content: str = ""
    published_truncated: bool = False


class RoomAgentStreamProjector:
    """One asynchronous writer for all Room preview streams in a Runner."""

    def __init__(self, cache: RoomAgentStreamCache, *, epoch: str | None = None) -> None:
        self.cache = cache
        self.epoch = epoch or secrets.token_urlsafe(18)
        self._queue: asyncio.Queue[tuple[str, tuple[Any, ...]]] = asyncio.Queue(maxsize=1024)
        self._buffers: dict[str, _StreamBuffer] = {}
        self._overflow: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None
        self._failed = False
        self._last_prune = time.monotonic()

    @property
    def failed(self) -> bool:
        return self._failed

    async def start(self) -> None:
        if self._task is not None:
            return
        await asyncio.to_thread(self.cache.initialize_boot, self.epoch)
        self._task = asyncio.create_task(self._run(), name="room-agent-stream-projector")

    async def open_stream(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        observation_id: str,
        attempt_id: str,
    ) -> str | None:
        if self._failed:
            return None
        await self.start()
        stream_id = f"room_stream_{secrets.token_hex(16)}"
        await self._queue.put(
            (
                "open",
                (
                    stream_id,
                    conversation_id,
                    participant_id,
                    observation_id,
                    attempt_id,
                    _utc_now(),
                ),
            )
        )
        return stream_id

    def feed_delta(self, stream_id: str | None, delta: str) -> None:
        if not stream_id or self._failed or not delta:
            return
        try:
            self._queue.put_nowait(("delta", (stream_id, delta)))
        except asyncio.QueueFull:
            current = self._overflow.get(stream_id, "")
            self._overflow[stream_id], _ = _truncate_utf8(current + delta, MAX_RAW_BYTES)

    async def committing(self, stream_id: str | None) -> None:
        if stream_id and not self._failed:
            await self._queue.put(("committing", (stream_id,)))

    async def resolve(self, stream_id: str | None) -> None:
        if stream_id and not self._failed:
            await self._queue.put(("resolved", (stream_id,)))

    async def invalidate(self, stream_id: str | None) -> None:
        if stream_id and not self._failed:
            await self._queue.put(("invalidated", (stream_id,)))

    async def shutdown(self) -> None:
        if self._task is None:
            return
        await self._queue.put(("stop", ()))
        await self._task
        self._task = None

    async def _run(self) -> None:
        try:
            stopping = False
            while not stopping:
                try:
                    operation, arguments = await asyncio.wait_for(
                        self._queue.get(), timeout=STREAM_FLUSH_INTERVAL_S / 2
                    )
                except TimeoutError:
                    operation, arguments = "tick", ()
                if operation == "stop":
                    stopping = True
                elif operation == "open":
                    await self._open(*arguments)
                elif operation == "delta":
                    self._append_delta(*arguments)
                elif operation in {"committing", "resolved", "invalidated"}:
                    await self._transition(str(arguments[0]), operation)
                self._drain_overflow()
                await self._flush_due(force=stopping)
            for stream_id, buffer in tuple(self._buffers.items()):
                if buffer.state not in {"resolved", "invalidated"}:
                    await self._transition(stream_id, "invalidated")
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failed = True
            for stream_id, buffer in tuple(self._buffers.items()):
                content, clipped = sanitize_stream_preview(buffer.raw, final=True)
                with suppress(Exception):
                    await asyncio.to_thread(
                        self.cache.update_stream,
                        stream_id,
                        state="invalidated",
                        content=content,
                        truncated=buffer.truncated or clipped,
                        closed=True,
                    )
            self._buffers.clear()
            self._overflow.clear()

    async def _open(
        self,
        stream_id: str,
        conversation_id: str,
        participant_id: str,
        observation_id: str,
        attempt_id: str,
        stamp: str,
    ) -> None:
        self._buffers[stream_id] = _StreamBuffer("", "streaming", time.monotonic())
        await asyncio.to_thread(
            self.cache.open_stream,
            stream_id=stream_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            observation_id=observation_id,
            attempt_id=attempt_id,
            started_at=stamp,
        )

    def _append_delta(self, stream_id: str, delta: str) -> None:
        buffer = self._buffers.get(stream_id)
        if buffer is None or buffer.state != "streaming":
            return
        buffer.raw, clipped = _truncate_utf8(buffer.raw + delta, MAX_RAW_BYTES)
        buffer.truncated = buffer.truncated or clipped

    def _drain_overflow(self) -> None:
        pending, self._overflow = self._overflow, {}
        for stream_id, delta in pending.items():
            self._append_delta(stream_id, delta)

    async def _transition(self, stream_id: str, state: str) -> None:
        buffer = self._buffers.get(stream_id)
        if buffer is None or buffer.state in {"resolved", "invalidated"}:
            return
        assert state in STREAM_STATES
        buffer.state = state  # type: ignore[assignment]
        content, clipped = sanitize_stream_preview(buffer.raw, final=True)
        buffer.truncated = buffer.truncated or clipped
        await asyncio.to_thread(
            self.cache.update_stream,
            stream_id,
            state=state,
            content=content,
            truncated=buffer.truncated,
            closed=state in {"resolved", "invalidated"},
        )
        buffer.published_content = content
        buffer.published_truncated = buffer.truncated
        buffer.last_flush = time.monotonic()
        if state in {"resolved", "invalidated"}:
            self._buffers.pop(stream_id, None)

    async def _flush_due(self, *, force: bool) -> None:
        now = time.monotonic()
        for stream_id, buffer in tuple(self._buffers.items()):
            if buffer.state != "streaming":
                continue
            if not force and now - buffer.last_flush < STREAM_FLUSH_INTERVAL_S:
                continue
            content, clipped = sanitize_stream_preview(buffer.raw, final=False)
            buffer.truncated = buffer.truncated or clipped
            if (
                content == buffer.published_content
                and buffer.truncated == buffer.published_truncated
            ):
                buffer.last_flush = now
                continue
            await asyncio.to_thread(
                self.cache.update_stream,
                stream_id,
                state="streaming",
                content=content,
                truncated=buffer.truncated,
            )
            buffer.published_content = content
            buffer.published_truncated = buffer.truncated
            buffer.last_flush = now
        if now - self._last_prune >= 1.0:
            await asyncio.to_thread(self.cache.prune_tombstones)
            self._last_prune = now


def build_room_agent_stream_projection(
    xmuse_root: Path | str,
    conversation_id: str,
    *,
    raw_cache: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read the disposable cache and re-prove every stream against ``chat.db``."""

    root = Path(xmuse_root).expanduser().resolve()
    raw = (
        dict(raw_cache)
        if raw_cache is not None
        else RoomAgentStreamCache(root).read_raw(conversation_id)
    )
    rows = raw["streams"]
    authority: dict[str, sqlite3.Row] = {}
    if rows:
        observation_ids = sorted({str(row["observation_id"]) for row in rows})
        placeholders = ",".join("?" for _ in observation_ids)
        with RoomDatabase(root / "chat.db").connect(readonly=True) as conn:
            authority = {
                str(row["observation_id"]): row
                for row in conn.execute(
                    f"""select o.observation_id, o.current_attempt_id, o.status,
                               o.control_state, o.expires_at, o.outcome_type,
                               o.produced_activity_id, a.state attempt_state,
                               a.provider_phase, a.recovery_state
                        from room_observations o
                        left join room_observation_attempts a
                          on a.attempt_id = o.current_attempt_id
                        where o.observation_id in ({placeholders})""",
                    observation_ids,
                ).fetchall()
            }
    projected: list[dict[str, Any]] = []
    for row in rows:
        proven = authority.get(str(row["observation_id"]))
        state = str(row["state"])
        resolution: dict[str, Any] | None = None
        expired = False
        if proven is not None and proven["expires_at"]:
            try:
                expired = datetime.fromisoformat(
                    str(proven["expires_at"]).replace("Z", "+00:00")
                ) <= datetime.now(UTC)
            except ValueError:
                expired = True
        if proven is None or proven["current_attempt_id"] != row["attempt_id"]:
            state = "invalidated"
        elif proven["status"] == "completed" and proven["attempt_state"] == "completed":
            state = "resolved"
            resolution = {
                "outcome_type": str(proven["outcome_type"]),
                "produced_activity_id": proven["produced_activity_id"],
            }
        elif (
            proven["status"] != "claimed"
            or proven["control_state"] != "active"
            or proven["attempt_state"] not in {"claimed", "delivering"}
            or proven["provider_phase"] in {"cleanup_pending", "cleanup_succeeded"}
            or proven["recovery_state"] != "none"
            or expired
        ):
            state = "invalidated"
        elif state == "resolved":
            state = "invalidated"
        projected.append(
            {
                "stream_id": str(row["stream_id"]),
                "participant_id": str(row["participant_id"]),
                "observation_id": str(row["observation_id"]),
                "state": state,
                "content": str(row["content"]),
                "truncated": bool(row["truncated"]),
                "started_at": str(row["started_at"]),
                "updated_at": str(row["updated_at"]),
                "resolution": resolution,
            }
        )
    return {
        "schema_version": STREAM_PROJECTION_SCHEMA,
        "proof_boundary": STREAM_PROOF_BOUNDARY,
        "projection_available": bool(raw["projection_available"]),
        "conversation_id": conversation_id,
        "epoch": raw["epoch"],
        "stream_seq": int(raw["stream_seq"]),
        "streams": projected,
    }


def encode_stream_projection_event(event: str, payload: Mapping[str, Any]) -> bytes:
    epoch = payload.get("epoch") or "unavailable"
    sequence = payload.get("stream_seq") or 0
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"event: {event}\nid: {epoch}:{sequence}\ndata: {data}\n\n".encode()


__all__ = [
    "RoomAgentStreamCache",
    "RoomAgentStreamError",
    "RoomAgentStreamProjector",
    "STREAM_CACHE_SCHEMA",
    "STREAM_PROJECTION_SCHEMA",
    "build_room_agent_stream_projection",
    "encode_stream_projection_event",
    "room_agent_stream_cache_path",
    "sanitize_stream_preview",
]
