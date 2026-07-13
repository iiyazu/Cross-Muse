"""Disposable, non-authoritative projection of native Codex UI events.

The Room Runner is the only writer.  Chat API processes may open this database
read-only, but must never treat it as Room, bridge, or Codex authority.  Raw App
Server messages are rebuilt through a closed allowlist before any bytes reach
SQLite.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import threading
from collections import Counter
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.codex_native_contract import CAPABILITY_IDS

EVENT_CACHE_SCHEMA = "room_codex_event_projection/v1"
EVENT_CACHE_PROOF_BOUNDARY = "codex_projection_not_room_or_native_authority"
EVENT_CACHE_RELATIVE_PATH = Path("runtime") / "room-codex-projection.sqlite3"
MAX_EVENT_BYTES = 16 * 1024
MAX_EVENTS_PER_PARTICIPANT = 500
MAX_EVENT_BYTES_PER_PARTICIPANT = 2 * 1024 * 1024
MAX_CURRENT_BYTES = 512 * 1024
MAX_READ_LIMIT = 100

_SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_GUARD = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_SECRET = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|api[_-]?key\s*[:=]\s*\S+)")
_ABSOLUTE_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9._-])/(?:home|root|tmp|etc|var|Users)/[^\s'\"`]+|"
    r"\b[A-Za-z]:\\[^\s'\"`]+)"
)
_GOAL_STATUSES = frozenset(
    {"active", "paused", "blocked", "usageLimited", "budgetLimited", "complete"}
)
_TURN_STATUSES = frozenset(
    {"inProgress", "completed", "interrupted", "failed", "cancelled", "canceled"}
)
_PLAN_STATUSES = {
    "pending": "pending",
    "inProgress": "in_progress",
    "completed": "completed",
}
_SAFE_ITEM_TYPES = frozenset(
    {
        "agentMessage",
        "plan",
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "enteredReviewMode",
        "exitedReviewMode",
        "contextCompaction",
    }
)
_CAPABILITY_METHODS = {
    "goal_set": "thread/goal/set",
    "goal_pause": "thread/goal/set",
    "goal_resume": "thread/goal/set",
    "goal_get": "thread/goal/get",
    "goal_clear": "thread/goal/clear",
    "settings_update": "thread/settings/update",
    "models_list": "model/list",
    "console_turn_start": "turn/start",
    "turn_steer": "turn/steer",
    "turn_interrupt": "turn/interrupt",
    "compact_start": "thread/compact/start",
    "review_start": "review/start",
}
_CAPABILITY_AVAILABILITY = frozenset(
    {"available", "runtime_unsupported", "policy_disabled", "session_conflict"}
)
_SCHEMA_STATEMENTS = (
    """create table if not exists projection_meta (
           schema_version text primary key,
           created_at text not null
       )""",
    """create table if not exists participant_projection (
           participant_id text primary key,
           conversation_id text not null,
           snapshot_json text,
           capabilities_json text,
           observed_at text,
           history_partial integer not null check(history_partial in (0, 1)),
           omitted_count integer not null check(omitted_count >= 0),
           next_participant_seq integer not null check(next_participant_seq >= 1)
       )""",
    """create index if not exists participant_projection_conversation
       on participant_projection(conversation_id, participant_id)""",
    """create table if not exists native_events (
           cache_seq integer primary key autoincrement,
           participant_id text not null,
           participant_seq integer not null,
           conversation_id text not null,
           kind text not null,
           observed_at text not null,
           payload_json text not null,
           serialized_bytes integer not null
               check(serialized_bytes > 0 and serialized_bytes <= 16384),
           unique(participant_id, participant_seq),
           foreign key(participant_id) references participant_projection(participant_id)
               on delete cascade
       )""",
    """create index if not exists native_events_conversation_seq
       on native_events(conversation_id, cache_seq)""",
    """create index if not exists native_events_participant_seq
       on native_events(participant_id, participant_seq)""",
)


class RoomCodexProjectionCacheError(RuntimeError):
    """Stable, content-free failure at the disposable cache boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def room_codex_projection_cache_path(xmuse_root: Path | str) -> Path:
    return Path(xmuse_root).expanduser().resolve() / EVENT_CACHE_RELATIVE_PATH


class RoomCodexProjectionCache:
    """Bounded projection cache with one logical event stream per participant."""

    def __init__(self, xmuse_root: Path | str) -> None:
        self._path = room_codex_projection_cache_path(xmuse_root)
        self._initialize_lock = threading.Lock()
        self._database_identity: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        with self._initialize_lock:
            if self._initialized_identity_matches():
                return
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        _prepare_private_database(self._path)
        with closing(self._connect()) as conn:
            conn.execute("begin immediate")
            meta_exists = conn.execute(
                """select 1 from sqlite_master
                   where type = 'table' and name = 'projection_meta'"""
            ).fetchone()
            if meta_exists is not None:
                try:
                    versions = [
                        str(row[0])
                        for row in conn.execute(
                            "select schema_version from projection_meta"
                        ).fetchall()
                    ]
                except sqlite3.Error as exc:
                    raise RoomCodexProjectionCacheError("codex_projection_schema_invalid") from exc
                if versions != [EVENT_CACHE_SCHEMA]:
                    raise RoomCodexProjectionCacheError("codex_projection_schema_unsupported")
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            if meta_exists is None:
                conn.execute(
                    "insert into projection_meta(schema_version, created_at) values (?, ?)",
                    (EVENT_CACHE_SCHEMA, _timestamp()),
                )
            conn.commit()
        metadata = self._path.lstat()
        self._database_identity = (metadata.st_dev, metadata.st_ino)

    def _initialized_identity_matches(self) -> bool:
        if self._database_identity is None or self._path.parent.is_symlink():
            return False
        try:
            metadata = self._path.lstat()
        except OSError:
            return False
        return bool(
            stat.S_ISREG(metadata.st_mode)
            and not stat.S_ISLNK(metadata.st_mode)
            and (metadata.st_dev, metadata.st_ino) == self._database_identity
        )

    def replace_current(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        snapshot: Mapping[str, object],
        capabilities: Mapping[str, object],
        history_partial: bool = True,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Replace safe current state; never retain the caller's raw mappings."""

        conversation = _trusted_room_id(conversation_id, "codex_projection_room_invalid")
        participant = _trusted_room_id(participant_id, "codex_projection_participant_invalid")
        safe_snapshot = sanitize_native_snapshot(snapshot)
        safe_capabilities = sanitize_native_capabilities(capabilities)
        snapshot_json = _bounded_json(
            safe_snapshot, maximum=MAX_CURRENT_BYTES, code="codex_projection_snapshot_too_large"
        )
        capabilities_json = _bounded_json(
            safe_capabilities,
            maximum=MAX_CURRENT_BYTES,
            code="codex_projection_capabilities_too_large",
        )
        stamp = _safe_timestamp(observed_at)
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("begin immediate")
            prior = conn.execute(
                "select * from participant_projection where participant_id = ?",
                (participant,),
            ).fetchone()
            if prior is not None and prior["conversation_id"] != conversation:
                raise RoomCodexProjectionCacheError("codex_projection_participant_room_conflict")
            omitted = int(prior["omitted_count"]) if prior is not None else 0
            next_seq = int(prior["next_participant_seq"]) if prior is not None else 1
            partial = bool(history_partial) or omitted > 0
            conn.execute(
                """insert into participant_projection
                   (participant_id, conversation_id, snapshot_json, capabilities_json,
                    observed_at, history_partial, omitted_count, next_participant_seq)
                   values (?, ?, ?, ?, ?, ?, ?, ?)
                   on conflict(participant_id) do update set
                       snapshot_json = excluded.snapshot_json,
                       capabilities_json = excluded.capabilities_json,
                       observed_at = excluded.observed_at,
                       history_partial = excluded.history_partial""",
                (
                    participant,
                    conversation,
                    snapshot_json,
                    capabilities_json,
                    stamp,
                    int(partial),
                    omitted,
                    next_seq,
                ),
            )
            conn.commit()
        return {
            "participant_id": participant,
            "conversation_id": conversation,
            "native_snapshot": safe_snapshot,
            "capabilities": safe_capabilities,
            "observed_at": stamp,
            "history_partial": partial,
            "omitted_count": omitted,
        }

    def append_notification(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        notification: Mapping[str, object],
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Append one allowlisted summary, or ignore an unsafe/unknown notification."""

        event = sanitize_native_notification(notification)
        if event is None:
            return None
        conversation = _trusted_room_id(conversation_id, "codex_projection_room_invalid")
        participant = _trusted_room_id(participant_id, "codex_projection_participant_invalid")
        stamp = _safe_timestamp(observed_at)
        payload_json = _bounded_json(
            event, maximum=MAX_EVENT_BYTES, code="codex_projection_event_too_large"
        )
        payload_bytes = len(payload_json.encode("utf-8"))
        self.initialize()
        with closing(self._connect()) as conn:
            conn.execute("begin immediate")
            current = conn.execute(
                "select * from participant_projection where participant_id = ?",
                (participant,),
            ).fetchone()
            if current is None:
                conn.execute(
                    """insert into participant_projection
                       (participant_id, conversation_id, snapshot_json, capabilities_json,
                        observed_at, history_partial, omitted_count, next_participant_seq)
                       values (?, ?, null, null, null, 1, 0, 1)""",
                    (participant, conversation),
                )
                participant_seq = 1
            else:
                if current["conversation_id"] != conversation:
                    raise RoomCodexProjectionCacheError(
                        "codex_projection_participant_room_conflict"
                    )
                participant_seq = int(current["next_participant_seq"])
            cursor = conn.execute(
                """insert into native_events
                   (participant_id, participant_seq, conversation_id, kind, observed_at,
                    payload_json, serialized_bytes)
                   values (?, ?, ?, ?, ?, ?, ?)""",
                (
                    participant,
                    participant_seq,
                    conversation,
                    event["kind"],
                    stamp,
                    payload_json,
                    payload_bytes,
                ),
            )
            if cursor.lastrowid is None:
                raise RoomCodexProjectionCacheError("codex_projection_insert_failed")
            cache_seq = cursor.lastrowid
            conn.execute(
                """update participant_projection set next_participant_seq = ?, observed_at = ?
                   where participant_id = ?""",
                (participant_seq + 1, stamp, participant),
            )
            omitted_now = _trim_participant(conn, participant)
            if omitted_now:
                conn.execute(
                    """update participant_projection
                       set omitted_count = omitted_count + ?, history_partial = 1
                       where participant_id = ?""",
                    (omitted_now, participant),
                )
            conn.commit()
        return {
            "event_seq": cache_seq,
            "participant_seq": participant_seq,
            "participant_id": participant,
            "conversation_id": conversation,
            "observed_at": stamp,
            **event,
        }

    def read_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = MAX_READ_LIMIT,
        before_event_seq: int | None = None,
        after_event_seq: int | None = None,
    ) -> dict[str, Any]:
        """Read one bounded page without creating or mutating a missing cache."""

        conversation = _trusted_room_id(conversation_id, "codex_projection_room_invalid")
        _validate_page(limit, before_event_seq, after_event_seq)
        if self._path.parent.is_symlink():
            raise RoomCodexProjectionCacheError("codex_projection_runtime_symlink_rejected")
        try:
            self._path.lstat()
        except FileNotFoundError:
            return _empty_page(conversation)
        except OSError as exc:
            raise RoomCodexProjectionCacheError("codex_projection_database_unavailable") from exc
        with closing(_readonly_connection(self._path)) as conn:
            _require_schema(conn)
            participants = [
                _participant_view(row)
                for row in conn.execute(
                    """select * from participant_projection where conversation_id = ?
                       order by participant_id""",
                    (conversation,),
                )
            ]
            predicate = "conversation_id = ?"
            values: list[object] = [conversation]
            if after_event_seq is not None:
                predicate += " and cache_seq > ?"
                values.append(after_event_seq)
                order = "asc"
            else:
                if before_event_seq is not None:
                    predicate += " and cache_seq < ?"
                    values.append(before_event_seq)
                order = "desc"
            rows = conn.execute(
                f"""select * from native_events where {predicate}
                    order by cache_seq {order} limit ?""",
                (*values, limit),
            ).fetchall()
            if order == "desc":
                rows.reverse()
            events = [_event_view(row) for row in rows]
            latest = int(
                conn.execute(
                    """select coalesce(max(cache_seq), 0) from native_events
                       where conversation_id = ?""",
                    (conversation,),
                ).fetchone()[0]
            )
            first = int(rows[0]["cache_seq"]) if rows else None
            last = int(rows[-1]["cache_seq"]) if rows else None
            has_older = bool(
                first is not None
                and conn.execute(
                    """select 1 from native_events
                       where conversation_id = ? and cache_seq < ? limit 1""",
                    (conversation, first),
                ).fetchone()
            )
            has_newer = bool(
                last is not None
                and conn.execute(
                    """select 1 from native_events
                       where conversation_id = ? and cache_seq > ? limit 1""",
                    (conversation, last),
                ).fetchone()
            )
        return {
            "schema_version": EVENT_CACHE_SCHEMA,
            "source": "codex_app_server_projection_cache",
            "projection_available": True,
            "proof_boundary": EVENT_CACHE_PROOF_BOUNDARY,
            "conversation_id": conversation,
            "participants": participants,
            "events": events,
            "latest_event_seq": latest,
            "has_older": has_older,
            "has_newer": has_newer,
            "next_before_event_seq": first if has_older else None,
            "next_after_event_seq": last if has_newer else None,
        }

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._path, timeout=30.0)
            _configure_connection(conn, readonly=False)
            conn.execute("pragma journal_mode = delete")
            conn.execute("pragma synchronous = full")
            conn.execute("pragma secure_delete = on")
            return conn
        except sqlite3.Error as exc:
            raise RoomCodexProjectionCacheError("codex_projection_database_unavailable") from exc


def sanitize_native_snapshot(value: Mapping[str, object]) -> dict[str, object]:
    if value.get("schema_version") != "room_codex_native_snapshot/v1":
        raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
    if value.get("source") != "codex_app_server":
        raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
    goal_raw = value.get("goal")
    goal: dict[str, object] | None = None
    if goal_raw is not None:
        if not isinstance(goal_raw, Mapping) or goal_raw.get("status") not in _GOAL_STATUSES:
            raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
        goal = {"status": goal_raw["status"]}
        objective = _safe_console_text(goal_raw.get("objective"), 4_096)
        if objective is not None:
            goal["objective"] = objective
        for source, target in (
            ("token_budget", "token_budget"),
            ("tokens_used", "tokens_used"),
            ("time_used_seconds", "time_used_seconds"),
        ):
            goal[target] = _safe_nonnegative_integer(goal_raw.get(source))
    settings_raw = value.get("settings")
    guards_raw = value.get("guards")
    if not isinstance(settings_raw, Mapping) or not isinstance(guards_raw, Mapping):
        raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
    settings = {
        "model": _safe_model(settings_raw.get("model"), optional=True),
        "effort": _safe_model(settings_raw.get("effort"), optional=True),
    }
    guards: dict[str, object] = {}
    for name in ("session", "goal", "settings", "turn"):
        raw = guards_raw.get(name)
        if raw is not None and (not isinstance(raw, str) or _GUARD.fullmatch(raw) is None):
            raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
        guards[name] = raw
    if guards["session"] is None:
        raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
    active_turn = value.get("active_turn")
    if not isinstance(active_turn, bool):
        raise RoomCodexProjectionCacheError("codex_projection_snapshot_invalid")
    return {
        "schema_version": "room_codex_native_snapshot/v1",
        "source": "codex_app_server",
        "goal": goal,
        "settings": settings,
        "active_turn": active_turn,
        "guards": guards,
    }


def sanitize_native_capabilities(value: Mapping[str, object]) -> dict[str, object]:
    if value.get("schema_version") != "room_codex_native_capabilities/v1":
        raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
    if value.get("source") != "codex_app_server":
        raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
    raw_descriptors = value.get("capabilities")
    raw_models = value.get("models")
    if not isinstance(raw_descriptors, list) or not isinstance(raw_models, list):
        raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
    descriptors: list[dict[str, object]] = []
    seen_capabilities: set[str] = set()
    for raw in raw_descriptors:
        if not isinstance(raw, Mapping):
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        capability = raw.get("capability_id")
        if capability not in CAPABILITY_IDS or capability in seen_capabilities:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        assert isinstance(capability, str)
        if raw.get("native_source") != _CAPABILITY_METHODS[capability]:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        availability = raw.get("availability")
        if availability not in _CAPABILITY_AVAILABILITY:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        reason = raw.get("disabled_reason")
        if reason is not None and (
            not isinstance(reason, str) or _SAFE_REASON.fullmatch(reason) is None
        ):
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        guard = raw.get("session_guard")
        if not isinstance(guard, str) or _GUARD.fullmatch(guard) is None:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        descriptors.append(
            {
                "capability_id": capability,
                "native_source": _CAPABILITY_METHODS[capability],
                "availability": availability,
                "disabled_reason": reason,
                "session_guard": guard,
            }
        )
        seen_capabilities.add(capability)
    models: list[dict[str, object]] = []
    seen_models: set[str] = set()
    for raw in raw_models:
        if not isinstance(raw, Mapping):
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        model_id = _required_model(raw.get("id"))
        model = _required_model(raw.get("model"))
        if model_id in seen_models:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        raw_efforts = raw.get("efforts")
        if not isinstance(raw_efforts, list):
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        efforts = [_required_model(item) for item in raw_efforts]
        if len(set(efforts)) != len(efforts) or "ultra" in efforts:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        default = _safe_model(raw.get("default_effort"), optional=True)
        if default is not None and default not in efforts:
            raise RoomCodexProjectionCacheError("codex_projection_capabilities_invalid")
        models.append(
            {
                "id": model_id,
                "model": model,
                "is_default": raw.get("is_default") is True,
                "default_effort": default,
                "efforts": efforts,
            }
        )
        seen_models.add(model_id)
    return {
        "schema_version": "room_codex_native_capabilities/v1",
        "source": "codex_app_server",
        "capabilities": descriptors,
        "models": models,
    }


def sanitize_native_notification(value: Mapping[str, object]) -> dict[str, object] | None:
    """Convert one raw notification into a safe summary without copying identifiers."""

    method = value.get("method")
    params = value.get("params")
    if not isinstance(method, str) or not isinstance(params, Mapping):
        return None
    if method == "thread/goal/updated":
        goal = params.get("goal")
        if not isinstance(goal, Mapping) or goal.get("status") not in _GOAL_STATUSES:
            return None
        return {"kind": "goal_updated", "status": goal["status"]}
    if method == "thread/goal/cleared":
        return {"kind": "goal_cleared"}
    if method == "thread/settings/updated":
        settings = params.get("threadSettings")
        if not isinstance(settings, Mapping):
            return None
        try:
            return {
                "kind": "settings_updated",
                "model": _safe_model(settings.get("model"), optional=True),
                "effort": _safe_model(
                    settings.get("reasoningEffort", settings.get("effort")), optional=True
                ),
            }
        except RoomCodexProjectionCacheError:
            return None
    if method == "thread/tokenUsage/updated":
        usage = _token_usage(params.get("tokenUsage"))
        return {"kind": "token_usage_updated", "usage": usage} if usage is not None else None
    if method in {"turn/started", "turn/completed"}:
        turn = params.get("turn")
        if not isinstance(turn, Mapping):
            return None
        status = turn.get("status")
        if status is not None and status not in _TURN_STATUSES:
            status = None
        return {
            "kind": "turn_started" if method.endswith("started") else "turn_completed",
            "status": status,
        }
    if method == "turn/plan/updated":
        plan = params.get("plan")
        if not isinstance(plan, list):
            return None
        counts: Counter[str] = Counter()
        steps: list[dict[str, str]] = []
        for raw in plan[:128]:
            if not isinstance(raw, Mapping):
                continue
            status = raw.get("status")
            if status in _PLAN_STATUSES:
                assert isinstance(status, str)
                counts[_PLAN_STATUSES[status]] += 1
                step = _safe_console_text(raw.get("step"), 512)
                if step is not None and len(steps) < 24:
                    steps.append({"step": step, "status": _PLAN_STATUSES[status]})
        return {
            "kind": "plan_updated",
            "step_count": min(len(plan), 128),
            "truncated": len(plan) > 128,
            "status_counts": {key: counts[key] for key in sorted(counts)},
            "steps": steps,
            "explanation": _safe_console_text(params.get("explanation"), 1_024),
        }
    if method == "turn/diff/updated":
        diff = params.get("diff")
        if not isinstance(diff, str) or len(diff.encode("utf-8")) > 2 * 1024 * 1024:
            return None
        return {"kind": "diff_updated", **_diff_summary(diff)}
    if method in {"item/started", "item/completed"}:
        item = params.get("item")
        if not isinstance(item, Mapping) or item.get("type") not in _SAFE_ITEM_TYPES:
            return None
        item_type = item["type"]
        assert isinstance(item_type, str)
        result: dict[str, object] = {
            "kind": "item_started" if method.endswith("started") else "item_completed",
            "item_type": item_type,
        }
        status_value = item.get("status")
        if isinstance(status_value, str) and _SAFE_REASON.fullmatch(status_value):
            result["status"] = status_value
        duration = _safe_nonnegative_integer(item.get("durationMs"))
        if duration is not None:
            result["duration_ms"] = duration
        exit_code = item.get("exitCode")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            result["exit_code"] = max(-(2**31), min(exit_code, 2**31 - 1))
        if method == "item/completed" and item_type in {"agentMessage", "plan"}:
            text = _safe_console_text(item.get("text"), 8 * 1024)
            if text is not None:
                result["text"] = text
        return result
    if method == "thread/compacted":
        return {"kind": "context_compacted"}
    return None


def _token_usage(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, object] = {}
    for section in ("last", "total"):
        raw = value.get(section)
        if not isinstance(raw, Mapping):
            return None
        safe: dict[str, int] = {}
        for source, target in (
            ("cachedInputTokens", "cached_input_tokens"),
            ("inputTokens", "input_tokens"),
            ("outputTokens", "output_tokens"),
            ("reasoningOutputTokens", "reasoning_output_tokens"),
            ("totalTokens", "total_tokens"),
        ):
            number = _safe_nonnegative_integer(raw.get(source))
            if number is None:
                return None
            safe[target] = number
        result[section] = safe
    window = _safe_nonnegative_integer(value.get("modelContextWindow"))
    result["model_context_window"] = window
    return result


def _safe_console_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\x00", "")
    if not text:
        return None
    text = _BEARER.sub("[redacted]", text)
    text = _SECRET.sub("[redacted]", text)
    text = _ABSOLUTE_PATH.sub("[path]", text)
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum:
        return text
    shortened = encoded[: max(0, maximum - 3)].decode("utf-8", errors="ignore").rstrip()
    return f"{shortened}…" if shortened else None


def _diff_summary(diff: str) -> dict[str, object]:
    files = additions = deletions = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {
        "file_count": min(files, 10_000),
        "addition_count": min(additions, 10_000_000),
        "deletion_count": min(deletions, 10_000_000),
        "truncated": files > 10_000 or additions > 10_000_000 or deletions > 10_000_000,
    }


def _trim_participant(conn: sqlite3.Connection, participant_id: str) -> int:
    rows = conn.execute(
        """select cache_seq, serialized_bytes from native_events
           where participant_id = ? order by participant_seq""",
        (participant_id,),
    ).fetchall()
    count = len(rows)
    total = sum(int(row["serialized_bytes"]) for row in rows)
    delete: list[int] = []
    for row in rows:
        if count <= MAX_EVENTS_PER_PARTICIPANT and total <= MAX_EVENT_BYTES_PER_PARTICIPANT:
            break
        delete.append(int(row["cache_seq"]))
        count -= 1
        total -= int(row["serialized_bytes"])
    if delete:
        conn.executemany(
            "delete from native_events where cache_seq = ?",
            ((item,) for item in delete),
        )
    return len(delete)


def _participant_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "participant_id": row["participant_id"],
        "conversation_id": row["conversation_id"],
        "native_snapshot": json.loads(row["snapshot_json"]) if row["snapshot_json"] else None,
        "capabilities": (
            json.loads(row["capabilities_json"]) if row["capabilities_json"] else None
        ),
        "observed_at": row["observed_at"],
        "history_partial": bool(row["history_partial"]),
        "omitted_count": int(row["omitted_count"]),
    }


def _event_view(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    return {
        "event_seq": int(row["cache_seq"]),
        "participant_seq": int(row["participant_seq"]),
        "participant_id": row["participant_id"],
        "conversation_id": row["conversation_id"],
        "observed_at": row["observed_at"],
        **payload,
    }


def _prepare_private_database(path: Path) -> None:
    runtime = path.parent
    try:
        if runtime.is_symlink():
            raise RoomCodexProjectionCacheError("codex_projection_runtime_symlink_rejected")
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        if runtime.is_symlink() or not runtime.is_dir():
            raise RoomCodexProjectionCacheError("codex_projection_runtime_invalid")
        os.chmod(runtime, 0o700)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o600)
            os.close(descriptor)
        else:
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise RoomCodexProjectionCacheError("codex_projection_database_unsafe")
        os.chmod(path, 0o600, follow_symlinks=False)
    except RoomCodexProjectionCacheError:
        raise
    except FileExistsError:
        _prepare_private_database(path)
    except OSError as exc:
        raise RoomCodexProjectionCacheError("codex_projection_database_unavailable") from exc


def _configure_connection(conn: sqlite3.Connection, *, readonly: bool) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 30000")
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma trusted_schema = off")
    if readonly:
        conn.execute("pragma query_only = on")


def _readonly_connection(path: Path) -> sqlite3.Connection:
    try:
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise RoomCodexProjectionCacheError("codex_projection_runtime_invalid")
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RoomCodexProjectionCacheError("codex_projection_database_unsafe")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
        _configure_connection(conn, readonly=True)
        return conn
    except RoomCodexProjectionCacheError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise RoomCodexProjectionCacheError("codex_projection_database_unavailable") from exc


def _require_schema(conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute("select schema_version from projection_meta").fetchall()
    except sqlite3.Error as exc:
        raise RoomCodexProjectionCacheError("codex_projection_schema_invalid") from exc
    if [str(row[0]) for row in rows] != [EVENT_CACHE_SCHEMA]:
        raise RoomCodexProjectionCacheError("codex_projection_schema_unsupported")


def _safe_nonnegative_integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1:
        return value
    return None


def _safe_model(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _SAFE_MODEL.fullmatch(value) is None:
        raise RoomCodexProjectionCacheError("codex_projection_model_invalid")
    return value


def _required_model(value: object) -> str:
    result = _safe_model(value)
    assert result is not None
    return result


def _trusted_room_id(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise RoomCodexProjectionCacheError(code)
    clean = value.strip()
    if not clean or len(clean.encode("utf-8")) > 256 or "\x00" in clean:
        raise RoomCodexProjectionCacheError(code)
    return clean


def _bounded_json(value: object, *, maximum: int, code: str) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RoomCodexProjectionCacheError(code) from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise RoomCodexProjectionCacheError(code)
    return encoded


def _safe_timestamp(value: str | None) -> str:
    if value is None:
        return _timestamp()
    if not isinstance(value, str) or len(value) > 64:
        raise RoomCodexProjectionCacheError("codex_projection_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RoomCodexProjectionCacheError("codex_projection_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise RoomCodexProjectionCacheError("codex_projection_timestamp_invalid")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_page(limit: int, before_event_seq: int | None, after_event_seq: int | None) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_READ_LIMIT:
        raise RoomCodexProjectionCacheError("codex_projection_page_invalid")
    if before_event_seq is not None and after_event_seq is not None:
        raise RoomCodexProjectionCacheError("codex_projection_cursor_conflict")
    for cursor in (before_event_seq, after_event_seq):
        if cursor is not None and (
            isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0
        ):
            raise RoomCodexProjectionCacheError("codex_projection_cursor_invalid")


def _empty_page(conversation_id: str) -> dict[str, Any]:
    return {
        "schema_version": EVENT_CACHE_SCHEMA,
        "source": "codex_app_server_projection_cache",
        "projection_available": False,
        "proof_boundary": EVENT_CACHE_PROOF_BOUNDARY,
        "conversation_id": conversation_id,
        "participants": [],
        "events": [],
        "latest_event_seq": 0,
        "has_older": False,
        "has_newer": False,
        "next_before_event_seq": None,
        "next_after_event_seq": None,
    }


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "EVENT_CACHE_PROOF_BOUNDARY",
    "EVENT_CACHE_SCHEMA",
    "MAX_EVENT_BYTES",
    "MAX_EVENT_BYTES_PER_PARTICIPANT",
    "MAX_EVENTS_PER_PARTICIPANT",
    "RoomCodexProjectionCache",
    "RoomCodexProjectionCacheError",
    "room_codex_projection_cache_path",
    "sanitize_native_capabilities",
    "sanitize_native_notification",
    "sanitize_native_snapshot",
]
