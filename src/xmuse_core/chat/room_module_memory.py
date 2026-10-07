"""Module memory: the host-kept handover notebook per board module.

Contract ``docs/contracts/module_memory_v1.md``. This module owns the durable
side: the ``room_module_memories`` / ``room_module_memory_runs`` /
``room_module_memory_cursors`` tables, building ``/curate`` windows from a
module's Room activities, storing a curate response (new versions, supersession
and the cursor in one transaction), and rendering ``memory.md`` for the owner's
board view. The MemoryOS HTTP call lives in the application layer
(``xmuse/room_module_memory_worker.py``); core never imports it.

Everything here is inert unless the worker runs, which only happens when the
switch is on: with it off no row is ever written and ``render_memory_md``
returns ``None`` for every module.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from xmuse_core.runtime.sqlite_connection import ClosingConnection

MODULE_MEMORY_ENV = "XMUSE_MODULE_MEMORY"
WINDOW_MAX = 32
CONTEXT_MAX = 8
ACTIVE_MAX = 60
MESSAGE_FLUSH = 12
SCAN_LIMIT = 500
STATEMENT_MAX = 1000
QUOTE_MAX = 500
SOURCES_MAX = 8
MEMORY_KINDS = frozenset({"lesson", "decision", "fact", "rule", "preference"})
TEXT_MAX = 8192
MAX_ATTEMPTS = 3
RETRY_BASE_S = 30
EMPTY_MAX_SENDS = 3
FAILURE_TYPES = frozenset({"gate_failure", "review_objection"})


def module_memory_enabled(environ: dict[str, str] | Any) -> bool:
    value = environ.get(MODULE_MEMORY_ENV, "") if environ is not None else ""
    return str(value).strip().lower() == "on"


def create_module_memory_schema(conn: sqlite3.Connection) -> None:
    """Additive tables, created in the caller's transaction."""

    conn.execute(
        """create table if not exists room_module_memories (
               memory_id text not null,
               conversation_id text not null references conversations(id),
               module_id text not null,
               kind text not null,
               topic_key text not null,
               statement text not null,
               version integer not null,
               occurrences integer not null default 0,
               sources_json text not null,
               supersedes_id text,
               status text not null check (status in ('active', 'superseded')),
               superseded_by text,
               run_id text not null,
               created_at text not null,
               primary key (conversation_id, module_id, memory_id)
           )"""
    )
    conn.execute(
        """create table if not exists room_module_memory_runs (
               run_id text primary key,
               conversation_id text not null references conversations(id),
               module_id text not null,
               first_seq integer not null,
               last_seq integer not null,
               activity_ids_json text not null,
               status text not null check (
                   status in ('pending', 'done', 'failed', 'skipped', 'empty')
               ),
               attempts integer not null default 0,
               error_code text,
               unaccounted_json text,
               diagnostics_json text,
               not_before text,
               created_at text not null,
               updated_at text not null
           )"""
    )
    conn.execute(
        """create table if not exists room_module_memory_cursors (
               conversation_id text not null references conversations(id),
               module_id text not null,
               last_seq integer not null,
               updated_at text not null,
               primary key (conversation_id, module_id)
           )"""
    )
    conn.execute(
        "create index if not exists idx_room_module_memories_module "
        "on room_module_memories(conversation_id, module_id, status)"
    )
    conn.execute(
        "create index if not exists idx_room_module_memory_runs_module "
        "on room_module_memory_runs(conversation_id, module_id, status)"
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode(raw: Any) -> Any:
    try:
        return json.loads(str(raw)) if raw is not None else None
    except ValueError:
        return None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= minimum else None
    if value is None:
        return 0
    return None


def _valid_memory(raw: Any) -> dict[str, Any] | None:
    """A curate memory with the fields this store needs, bounded, or None."""

    if not isinstance(raw, dict):
        return None
    memory_id = raw.get("id")
    kind = raw.get("kind")
    statement = raw.get("statement")
    topic_key = raw.get("topic_key")
    version = _as_int(raw.get("version"))
    occurrences = _as_int(raw.get("occurrences"))
    supersedes = raw.get("supersedes_id")
    if (
        not isinstance(memory_id, str)
        or not 0 < len(memory_id) <= 200
        or kind not in MEMORY_KINDS
        or not isinstance(statement, str)
        or not statement.strip()
        or not isinstance(topic_key, str)
        or len(topic_key) > 200
        or version is None
        or occurrences is None
        or (supersedes is not None and not isinstance(supersedes, str))
    ):
        return None
    sources = [
        {
            "activity_id": str(source.get("activity_id", ""))[:200],
            "quote": str(source.get("quote", ""))[:QUOTE_MAX],
        }
        for source in _list(raw.get("sources"))[:SOURCES_MAX]
        if isinstance(source, dict)
    ]
    return {
        "id": memory_id,
        "kind": str(kind),
        "topic_key": topic_key,
        "statement": statement.strip()[:STATEMENT_MAX],
        "version": version,
        "occurrences": occurrences,
        "sources": sources,
        "supersedes_id": supersedes or None,
    }


def _bounded(text: str) -> str:
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1] + "…"


def response_has_storable_memory(response: Mapping[str, Any] | Any) -> bool:
    """Whether a curate response holds at least one valid memory.

    The worker peeks with this before storing so an empty success can be
    resent under the retry budget without moving the cursor first.
    """

    if not isinstance(response, Mapping):
        return False
    return any(_valid_memory(raw) is not None for raw in _list(response.get("memories")))


@dataclass(frozen=True)
class ModuleRef:
    conversation_id: str
    module_id: str
    owner_participant_id: str


@dataclass
class Window:
    module: ModuleRef
    activities: list[dict[str, Any]]
    context: list[dict[str, Any]]
    first_seq: int
    last_seq: int
    active: list[dict[str, Any]] = field(default_factory=list)

    def curate_request(self) -> dict[str, Any]:
        return {
            "scope_id": self.module.module_id,
            "profile": "module",
            "active": self.active,
            "context": self.context,
            "window": self.activities,
            "max_repairs": 2,
        }


def _activity_item(row: sqlite3.Row, module: ModuleRef) -> dict[str, Any] | None:
    """Map one Room activity to a curate activity of this module, or None."""

    kind = str(row["activity_type"])
    payload = _decode(row["payload_json"])
    if not isinstance(payload, dict):
        return None
    actor = row["actor_participant_id"]
    owner = module.owner_participant_id
    item_type: str | None = None
    speaker = "host"
    text = ""
    if kind == "board.verification":
        if payload.get("module_id") != module.module_id or payload.get("status") != "failed":
            return None
        item_type, speaker = "gate_failure", "ci"
        gates = _list(payload.get("gates"))
        failed = [
            str(gate.get("gate_id"))
            for gate in gates
            if isinstance(gate, dict) and gate.get("status") not in ("passed", None)
        ]
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        tails = evidence.get("output_tails") if isinstance(evidence, dict) else None
        tail_text = ""
        if isinstance(tails, dict):
            tail_text = "\n".join(f"[{key}]\n{value}" for key, value in tails.items())
        elif isinstance(tails, list):
            tail_text = "\n".join(str(value) for value in tails)
        text = (
            f"verification failed: {payload.get('reason_code') or 'gate_failed'}; "
            f"failed gates: {', '.join(failed) or 'unknown'}\n{tail_text}"
        )
    elif kind == "board.review":
        if payload.get("module_id") != module.module_id or payload.get("verdict") != "object":
            return None
        item_type, speaker = "review_objection", "reviewer"
        findings = _list(payload.get("findings"))
        lines = [str(payload.get("summary") or "")]
        for finding in findings[:16]:
            if isinstance(finding, dict):
                lines.append(
                    f"[{finding.get('severity')}] {finding.get('path') or ''} {finding.get('text')}"
                )
        text = "\n".join(lines)
    elif kind == "board.integration":
        conflicts = _list(payload.get("conflicts"))
        conflict_modules = {
            str(item.get("module_id")) for item in conflicts if isinstance(item, dict)
        }
        suspects = payload.get("suspect_module_ids")
        suspect_ids = set(suspects) if isinstance(suspects, list) else set()
        if module.module_id not in conflict_modules | suspect_ids:
            return None
        item_type, speaker = "gate_failure", "integration"
        paths = [
            str(path)
            for item in conflicts
            if isinstance(item, dict) and item.get("module_id") == module.module_id
            for path in (_list(item.get("paths")))
        ]
        gate_ids = _list(payload.get("gate_ids"))
        text = (
            f"integration {payload.get('status')}: {payload.get('reason_code') or ''}; "
            f"conflict paths: {', '.join(paths) or 'none'}; "
            f"gates: {', '.join(str(gate) for gate in gate_ids) or 'none'}"
        )
    elif kind == "board.progress":
        if payload.get("module_id") != module.module_id or actor != owner:
            return None
        item_type, speaker = "message", "owner"
        claims = _list(payload.get("claims"))
        text = f"progress {payload.get('status')}: {payload.get('summary') or ''}" + "".join(
            f"\n- {claim}" for claim in claims[:16]
        )
    elif kind == "board.question":
        target = payload.get("target_participant_id")
        if owner not in (actor, target):
            return None
        item_type = "message"
        speaker = "owner" if actor == owner else "peer"
        text = f"question: {payload.get('question') or ''}"
    elif kind == "message.posted":
        mentions = _list(payload.get("mentions"))
        mentioned = {str(item).removeprefix("@participant:") for item in mentions}
        is_human = str(row["actor_kind"]) == "human"
        if not ((is_human and owner in mentioned) or actor == owner):
            return None
        item_type = "message"
        speaker = "human" if is_human else "owner"
        text = str(payload.get("content") or "")
    if item_type is None or not text.strip():
        return None
    return {
        "id": str(row["activity_id"]),
        "seq": int(row["seq"]),
        "type": item_type,
        "speaker": speaker,
        "text": _bounded(text),
    }


class ModuleMemoryStore:
    """Durable module memory for one ``chat.db``."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        # Every caller uses ``with self._connect() as conn:`` once; closing on exit
        # keeps Python 3.13's warning-strict suite clean (#462).
        conn = sqlite3.connect(self._path, timeout=30, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 30000")
        conn.execute("pragma foreign_keys = on")
        return conn

    def active_modules(self) -> list[ModuleRef]:
        """Modules whose latest charter is active, with their owners."""

        with self._connect() as conn:
            rows = conn.execute(
                """select c.conversation_id, c.module_id, c.owner_participant_id
                   from room_board_charters c
                   where c.status = 'active' and c.version = (
                       select max(version) from room_board_charters c2
                       where c2.conversation_id = c.conversation_id
                         and c2.module_id = c.module_id)
                   order by c.conversation_id, c.module_id"""
            ).fetchall()
        return [
            ModuleRef(str(row[0]), str(row[1]), str(row[2])) for row in rows if row[2] is not None
        ]

    def _cursor_conn(self, conn: sqlite3.Connection, module: ModuleRef) -> int:
        row = conn.execute(
            "select last_seq from room_module_memory_cursors "
            "where conversation_id = ? and module_id = ?",
            (module.conversation_id, module.module_id),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def _active_conn(self, conn: sqlite3.Connection, module: ModuleRef) -> list[dict[str, Any]]:
        rows = conn.execute(
            "select * from room_module_memories where conversation_id = ? and module_id = ? "
            "and status = 'active' order by version desc limit ?",
            (module.conversation_id, module.module_id, ACTIVE_MAX),
        ).fetchall()
        # Bounded so 60 active memories plus a full window stay well under the
        # curate request limit.
        return [
            {
                "id": str(row["memory_id"]),
                "kind": str(row["kind"]),
                "topic_key": str(row["topic_key"]),
                "statement": str(row["statement"])[:STATEMENT_MAX],
                "version": int(row["version"]),
                "occurrences": int(row["occurrences"]),
                "sources": [
                    {**source, "quote": str(source.get("quote", ""))[:QUOTE_MAX]}
                    for source in _list(_decode(row["sources_json"]))[:SOURCES_MAX]
                    if isinstance(source, dict)
                ],
            }
            for row in rows
        ]

    def next_window(self, module: ModuleRef, *, now: datetime | None = None) -> Window | None:
        """The next window to curate, or None when nothing is ready.

        A window is ready when it holds a failure (gate or review) or
        ``MESSAGE_FLUSH`` messages; otherwise the activities wait for more. A
        window still in backoff after a failed attempt is not ready.
        """

        current = now or _now()
        with self._connect() as conn:
            pending = conn.execute(
                "select not_before, last_seq from room_module_memory_runs "
                "where conversation_id = ? and module_id = ? and status = 'failed' "
                "order by created_at desc limit 1",
                (module.conversation_id, module.module_id),
            ).fetchone()
            if pending is not None and pending["not_before"] is not None:
                if _stamp(current) < str(pending["not_before"]):
                    return None
            # A retry resends the same window: it never grows past the failed one, so a
            # skip after the last attempt cannot jump over activities never sent.
            upper = int(pending["last_seq"]) if pending is not None else None
            cursor = self._cursor_conn(conn, module)
            rows = conn.execute(
                "select * from room_activities where conversation_id = ? and seq > ? "
                "and (? is null or seq <= ?) order by seq limit ?",
                (module.conversation_id, cursor, upper, upper, SCAN_LIMIT),
            ).fetchall()
            items: list[dict[str, Any]] = []
            last_seen = cursor
            ready = False
            for row in rows:
                last_seen = int(row["seq"])
                item = _activity_item(row, module)
                if item is None:
                    continue
                items.append(item)
                if item["type"] in FAILURE_TYPES:
                    ready = True
                    break
                if len(items) >= min(MESSAGE_FLUSH, WINDOW_MAX):
                    ready = True
                    break
            if not ready and not items and rows:
                # Nothing of this module in a full scan: move past it, unless another
                # writer moved the cursor meanwhile.
                conn.execute("begin immediate")
                if self._cursor_conn(conn, module) == cursor:
                    self._advance_cursor_conn(conn, module, last_seen, _stamp(current))
                conn.commit()
                return None
            if not ready and items and (upper is not None or len(rows) >= SCAN_LIMIT):
                # A retried window, or a long stretch of other activity: flush what
                # accumulated rather than wait.
                ready = True
            if not ready:
                return None
            context_rows = conn.execute(
                "select * from room_activities where conversation_id = ? and seq <= ? "
                "order by seq desc limit 200",
                (module.conversation_id, cursor),
            ).fetchall()
            context: list[dict[str, Any]] = []
            for row in context_rows:
                item = _activity_item(row, module)
                if item is not None:
                    context.append(item)
                if len(context) >= CONTEXT_MAX:
                    break
            context.reverse()
            return Window(
                module=module,
                activities=items[:WINDOW_MAX],
                context=context,
                first_seq=int(items[0]["seq"]),
                last_seq=last_seen,
                active=self._active_conn(conn, module),
            )

    def store_result(
        self, window: Window, response: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Store a curate response: versions, supersession and cursor, one transaction."""

        current = now or _now()
        stamp = _stamp(current)
        module = window.module
        memories = _list(response.get("memories"))
        run_id = f"modmem_{uuid.uuid4().hex}"
        stored = 0
        rejected = 0
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                for raw in memories:
                    memory = _valid_memory(raw)
                    if memory is None:
                        # One malformed memory never sinks the rest of the response.
                        rejected += 1
                        continue
                    memory_id = memory["id"]
                    exists = conn.execute(
                        "select 1 from room_module_memories where conversation_id = ? "
                        "and module_id = ? and memory_id = ?",
                        (module.conversation_id, module.module_id, memory_id),
                    ).fetchone()
                    if exists is not None:
                        continue
                    supersedes = memory["supersedes_id"]
                    if supersedes is not None:
                        # Only an active memory of this module, never itself.
                        target = conn.execute(
                            "select 1 from room_module_memories where conversation_id = ? "
                            "and module_id = ? and memory_id = ? and status = 'active'",
                            (module.conversation_id, module.module_id, supersedes),
                        ).fetchone()
                        if supersedes == memory_id or target is None:
                            supersedes = None
                    conn.execute(
                        """insert into room_module_memories
                           (memory_id, conversation_id, module_id, kind, topic_key, statement,
                            version, occurrences, sources_json, supersedes_id, status,
                            superseded_by, run_id, created_at)
                           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', null, ?, ?)""",
                        (
                            memory_id,
                            module.conversation_id,
                            module.module_id,
                            memory["kind"],
                            memory["topic_key"],
                            memory["statement"],
                            memory["version"] or window.last_seq,
                            memory["occurrences"],
                            json.dumps(memory["sources"], sort_keys=True),
                            supersedes,
                            run_id,
                            stamp,
                        ),
                    )
                    stored += 1
                    if supersedes is not None:
                        conn.execute(
                            "update room_module_memories set status = 'superseded', "
                            "superseded_by = ? where conversation_id = ? and module_id = ? "
                            "and memory_id = ?",
                            (memory_id, module.conversation_id, module.module_id, supersedes),
                        )
                # An empty success is a violation, not a silent pass: the window
                # is marked empty so missing memories stay visible. The cursor
                # still advances past exactly this window.
                empty = stored == 0
                self._finish_run_conn(
                    conn,
                    window,
                    run_id=run_id,
                    status="empty" if empty else "done",
                    stamp=stamp,
                    error_code="curate_empty" if empty else None,
                    unaccounted=response.get("unaccounted"),
                    diagnostics=response.get("diagnostics"),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"run_id": run_id, "stored": stored, "rejected": rejected}

    def record_failure(
        self, window: Window, error_code: str, *, now: datetime | None = None
    ) -> str:
        """Record a failed call; after ``MAX_ATTEMPTS`` the window is skipped.

        Returns the new status (``failed`` or ``skipped``).
        """

        current = now or _now()
        stamp = _stamp(current)
        module = window.module
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                prior = conn.execute(
                    "select run_id, attempts from room_module_memory_runs "
                    "where conversation_id = ? and module_id = ? and status = 'failed' "
                    "and first_seq = ? order by created_at desc limit 1",
                    (module.conversation_id, module.module_id, window.first_seq),
                ).fetchone()
                attempts = (int(prior["attempts"]) if prior is not None else 0) + 1
                if attempts >= MAX_ATTEMPTS:
                    if prior is not None:
                        conn.execute(
                            "delete from room_module_memory_runs where run_id = ?",
                            (str(prior["run_id"]),),
                        )
                    self._finish_run_conn(
                        conn,
                        window,
                        run_id=f"modmem_{uuid.uuid4().hex}",
                        status="skipped",
                        stamp=stamp,
                        attempts=attempts,
                        error_code=error_code,
                    )
                    conn.commit()
                    return "skipped"
                not_before = _stamp(current + timedelta(seconds=RETRY_BASE_S * attempts))
                if prior is None:
                    conn.execute(
                        """insert into room_module_memory_runs
                           (run_id, conversation_id, module_id, first_seq, last_seq,
                            activity_ids_json, status, attempts, error_code, not_before,
                            created_at, updated_at)
                           values (?, ?, ?, ?, ?, ?, 'failed', ?, ?, ?, ?, ?)""",
                        (
                            f"modmem_{uuid.uuid4().hex}",
                            module.conversation_id,
                            module.module_id,
                            window.first_seq,
                            window.last_seq,
                            json.dumps([item["id"] for item in window.activities]),
                            attempts,
                            error_code,
                            not_before,
                            stamp,
                            stamp,
                        ),
                    )
                else:
                    conn.execute(
                        "update room_module_memory_runs set attempts = ?, error_code = ?, "
                        "not_before = ?, updated_at = ? where run_id = ?",
                        (attempts, error_code, not_before, stamp, str(prior["run_id"])),
                    )
                conn.commit()
                return "failed"
            except Exception:
                conn.rollback()
                raise

    def _finish_run_conn(
        self,
        conn: sqlite3.Connection,
        window: Window,
        *,
        run_id: str,
        status: str,
        stamp: str,
        attempts: int = 1,
        error_code: str | None = None,
        unaccounted: Any = None,
        diagnostics: Any = None,
    ) -> None:
        module = window.module
        # A retried window that finally succeeds or is skipped drops its failed row.
        conn.execute(
            "delete from room_module_memory_runs where conversation_id = ? and module_id = ? "
            "and status = 'failed' and first_seq = ?",
            (module.conversation_id, module.module_id, window.first_seq),
        )
        conn.execute(
            """insert into room_module_memory_runs
               (run_id, conversation_id, module_id, first_seq, last_seq, activity_ids_json,
                status, attempts, error_code, unaccounted_json, diagnostics_json, not_before,
                created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, ?, ?)""",
            (
                run_id,
                module.conversation_id,
                module.module_id,
                window.first_seq,
                window.last_seq,
                json.dumps([item["id"] for item in window.activities]),
                status,
                attempts,
                error_code,
                json.dumps(unaccounted) if unaccounted is not None else None,
                json.dumps(diagnostics, sort_keys=True) if diagnostics is not None else None,
                stamp,
                stamp,
            ),
        )
        self._advance_cursor_conn(conn, module, window.last_seq, stamp)

    @staticmethod
    def _advance_cursor_conn(
        conn: sqlite3.Connection, module: ModuleRef, last_seq: int, stamp: str
    ) -> None:
        conn.execute(
            """insert into room_module_memory_cursors(conversation_id, module_id, last_seq,
                                                       updated_at)
               values (?, ?, ?, ?)
               on conflict(conversation_id, module_id) do update
               set last_seq = excluded.last_seq, updated_at = excluded.updated_at""",
            (module.conversation_id, module.module_id, last_seq, stamp),
        )

    def memories(self, conversation_id: str, module_id: str) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "select * from room_module_memories where conversation_id = ? "
                    "and module_id = ? order by version desc, created_at desc",
                    (conversation_id, module_id),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]


def render_memory_md(module_id: str, memories: list[dict[str, Any]]) -> str | None:
    """The owner-facing notebook for one module, or None when there is nothing to show."""

    if not memories:
        return None
    by_id = {str(item["memory_id"]): item for item in memories}
    active = [item for item in memories if item["status"] == "active"]
    lessons = sorted(
        (item for item in active if item["kind"] == "lesson"),
        key=lambda item: (-int(item["occurrences"]), -int(item["version"])),
    )
    others = [item for item in active if item["kind"] != "lesson"]
    superseded = [item for item in memories if item["status"] == "superseded"]
    lines = [
        f"# Module memory: {module_id}",
        "",
        "Curated from this module's history (gate failures, review objections, messages).",
        "It is derived and may be incomplete: your charter and contracts win on any conflict.",
        "",
        "## Do not repeat (lessons)",
        "",
    ]
    if lessons:
        for item in lessons:
            lines.append(f"- [seen {int(item['occurrences'])}x] {item['statement']}")
    else:
        lines.append("- none yet")
    lines += ["", "## Superseded: do not use", ""]
    if superseded:
        for item in superseded[:30]:
            current = by_id.get(str(item.get("superseded_by") or ""))
            now = f" Now: {current['statement']}" if current is not None else ""
            lines.append(f"- No longer true: {item['statement']}.{now}")
    else:
        lines.append("- none")
    lines += ["", "## Current decisions and facts", ""]
    if others:
        for item in others:
            lines.append(f"- ({item['kind']}) {item['statement']}")
    else:
        lines.append("- none yet")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "MODULE_MEMORY_ENV",
    "ModuleMemoryStore",
    "ModuleRef",
    "Window",
    "create_module_memory_schema",
    "module_memory_enabled",
    "render_memory_md",
    "response_has_storable_memory",
]
