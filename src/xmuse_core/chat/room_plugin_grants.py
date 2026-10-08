"""Scoped plugin grants for host-plugin writes from the human's main window.

Implements the durable side of ``docs/contracts/plugin_grant_v1.md`` as
extended by ``docs/contracts/main_window_control_v1.md``: grants with a scope
set and a Room set (``plugin_grants_v2``, ``plugin_grant_rooms``), pairing
codes, secret digests, the global pairing limiter, and the bearer checks. HTTP
mapping lives in ``xmuse/chat_api_grants.py``.

The secret (256 bits) and the pairing code are never stored in the clear:
only their SHA-256 digests reach ``chat.db``. The v1 ``plugin_grants`` table
is still created for schema compatibility but no longer written: v1 grants
are short-lived and a new Workroom generation invalidates them anyway.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from xmuse_core.runtime.sqlite_connection import ClosingConnection

SCOPE_ROOM_CREATE = "room.create"
SCOPE_ROOM_MESSAGE = "room.message"
SCOPE_BOARD_SPLIT_DECIDE = "board.split.decide"
SCOPE_BOARD_REVIEW_DECIDE = "board.review.decide"
SCOPES = frozenset(
    {SCOPE_ROOM_CREATE, SCOPE_ROOM_MESSAGE, SCOPE_BOARD_SPLIT_DECIDE, SCOPE_BOARD_REVIEW_DECIDE}
)
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SECRET_RE = re.compile(r"^xpg_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{43}$")
PAIRING_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
PAIRING_CODE_RE = re.compile(
    r"^[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}$"
)
PAIRING_TTL_S = 120
DEFAULT_TTL_S = 3600
MIN_TTL_S = 60
MAX_TTL_S = 14400
MAX_FAILED_BEARERS = 5
EXCHANGE_FAIL_LIMIT = 10
EXCHANGE_FAIL_WINDOW_S = 60
TOKEN_FINGERPRINT_CONTEXT = "plugin-grant/v1"
GRANT_LIST_LIMIT = 50
MAX_LIVE_GRANTS_PER_HOST = 4
MAX_GRANT_ROOMS = 16
ROOM_CREATE_INTERVAL_S = 10


class PluginGrantError(Exception):
    """Stable, client-safe failure raised by the plugin grant store."""

    def __init__(self, code: str, *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def create_plugin_grant_schema(conn: sqlite3.Connection) -> None:
    """Create the additive plugin-grant tables in the caller transaction."""

    # v1 table: created for compatibility with existing databases, never written.
    conn.execute(
        """create table if not exists plugin_grants (
               grant_id text primary key,
               conversation_id text not null references conversations(id),
               host text not null,
               scope text not null,
               ttl_seconds integer not null,
               created_at text not null,
               activated_at text,
               expires_at text not null,
               pairing_expires_at text not null,
               revoked_at text,
               last_used_at text,
               use_count integer not null default 0,
               failed_attempts integer not null default 0,
               secret_digest text,
               pairing_code_digest text,
               pairing_consumed integer not null default 0,
               operator_token_fingerprint text not null
           )"""
    )
    conn.execute(
        """create table if not exists plugin_grants_v2 (
               grant_id text primary key,
               host text not null,
               scopes_json text not null,
               ttl_seconds integer not null,
               created_at text not null,
               activated_at text,
               expires_at text not null,
               pairing_expires_at text not null,
               revoked_at text,
               last_used_at text,
               use_count integer not null default 0,
               failed_attempts integer not null default 0,
               secret_digest text,
               pairing_code_digest text,
               pairing_consumed integer not null default 0,
               operator_token_fingerprint text not null,
               last_room_create_at text
           )"""
    )
    conn.execute(
        """create table if not exists plugin_grant_rooms (
               grant_id text not null references plugin_grants_v2(grant_id),
               conversation_id text not null references conversations(id),
               added_at text not null,
               added_via text not null check (added_via in ('issue', 'create')),
               primary key (grant_id, conversation_id)
           )"""
    )
    conn.execute(
        """create table if not exists plugin_grant_exchange_failures (
               failure_id text primary key,
               failed_at text not null
           )"""
    )
    conn.execute(
        "create index if not exists idx_plugin_grants_conversation_host "
        "on plugin_grants(conversation_id, host, created_at)"
    )
    conn.execute(
        "create index if not exists idx_plugin_grants_v2_host on plugin_grants_v2(host, created_at)"
    )
    conn.execute(
        "create index if not exists idx_plugin_grant_rooms_conversation "
        "on plugin_grant_rooms(conversation_id)"
    )
    conn.execute(
        "create index if not exists idx_plugin_grant_exchange_failures_at "
        "on plugin_grant_exchange_failures(failed_at)"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def operator_token_fingerprint(operator_token: str) -> str:
    """Return the non-exposed fingerprint binding a grant to an operator token."""

    return hmac.new(
        operator_token.encode("utf-8"),
        TOKEN_FINGERPRINT_CONTEXT.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_grant_id() -> str:
    return f"grant_{secrets.token_hex(16)}"


def _new_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _new_secret(grant_id: str) -> str:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    return f"xpg_{grant_id}_{raw}"


def _secret_grant_id(secret: str) -> str | None:
    # The token is always exactly 43 chars, so split structurally: a greedy
    # ``rpartition("_")`` would break when the base64url token itself holds
    # an underscore.
    if not isinstance(secret, str) or not SECRET_RE.match(secret):
        return None
    rest = secret[len("xpg_") :]
    if len(rest) < 45 or rest[-44] != "_":
        return None
    return rest[:-44] or None


def _derive_status(row: sqlite3.Row, now: datetime) -> str:
    if row["revoked_at"] is not None:
        return "revoked"
    if row["activated_at"] is not None:
        return "active" if now < _parse_time(str(row["expires_at"])) else "expired"
    return "pending" if now < _parse_time(str(row["pairing_expires_at"])) else "expired"


def _scopes(row: sqlite3.Row) -> list[str]:
    value = json.loads(str(row["scopes_json"]))
    return sorted(str(item) for item in value)


def _rooms_conn(conn: sqlite3.Connection, grant_id: str) -> list[str]:
    return [
        str(item["conversation_id"])
        for item in conn.execute(
            "select conversation_id from plugin_grant_rooms where grant_id = ? "
            "order by added_at, rowid",
            (grant_id,),
        ).fetchall()
    ]


def _public_grant(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict[str, Any]:
    return {
        "grant_id": str(row["grant_id"]),
        "host": str(row["host"]),
        "scopes": _scopes(row),
        "conversation_ids": _rooms_conn(conn, str(row["grant_id"])),
        "status": _derive_status(row, now),
        "created_at": str(row["created_at"]),
        "activated_at": row["activated_at"],
        "expires_at": str(row["expires_at"]),
        "revoked_at": row["revoked_at"],
        "last_used_at": row["last_used_at"],
        "use_count": int(row["use_count"]),
    }


def _live_clause() -> str:
    return (
        "revoked_at is null and ((activated_at is null and pairing_expires_at > ?) "
        "or (activated_at is not null and expires_at > ?))"
    )


def _normalize_scopes(scopes: Any) -> list[str]:
    if not isinstance(scopes, list) or not scopes:
        raise PluginGrantError("plugin_grant_scope_invalid")
    if any(not isinstance(item, str) or item not in SCOPES for item in scopes):
        raise PluginGrantError("plugin_grant_scope_invalid")
    if len(set(scopes)) != len(scopes):
        raise PluginGrantError("plugin_grant_scope_invalid")
    return sorted(scopes)


def _normalize_rooms(conversation_ids: Any) -> list[str]:
    if not isinstance(conversation_ids, list) or len(conversation_ids) > MAX_GRANT_ROOMS:
        raise PluginGrantError("plugin_grant_request_invalid")
    if any(not isinstance(item, str) or not item for item in conversation_ids):
        raise PluginGrantError("plugin_grant_request_invalid")
    if len(set(conversation_ids)) != len(conversation_ids):
        raise PluginGrantError("plugin_grant_request_invalid")
    return list(conversation_ids)


class PluginGrantStore:
    """Durable store for scoped plugin grants and pairing codes.

    Connections are opened directly (mirroring ``RoomDatabase`` pragmas) so
    this module never imports ``room_database``: the schema creator lives
    here, ``room_database`` imports it, and any back-edge would be an
    architecture import cycle.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if not self._path.is_file() or self._path.is_symlink():
            raise PluginGrantError("room_database_missing")
        try:
            if readonly:
                conn = sqlite3.connect(
                    f"{self._path.resolve().as_uri()}?mode=ro",
                    uri=True,
                    timeout=30,
                    factory=ClosingConnection,
                )
            else:
                conn = sqlite3.connect(self._path, timeout=30, factory=ClosingConnection)
        except sqlite3.Error as exc:
            raise PluginGrantError("room_database_unavailable") from exc
        conn.row_factory = sqlite3.Row
        conn.execute("pragma busy_timeout = 30000")
        conn.execute("pragma foreign_keys = on")
        if readonly:
            conn.execute("pragma query_only = on")
        return conn

    def _connect_readonly(self) -> sqlite3.Connection:
        return self._connect(readonly=True)

    @staticmethod
    def _grant_row(conn: sqlite3.Connection, grant_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = conn.execute(
            "select * from plugin_grants_v2 where grant_id = ?", (grant_id,)
        ).fetchone()
        return row

    # -- operator surface -------------------------------------------------

    def issue(
        self,
        *,
        host: Any,
        scopes: Any,
        conversation_ids: Any,
        ttl_seconds: Any = None,
        operator_token: str | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], str, str]:
        """Issue a pending grant.

        Revokes the host's live v1 grants and, beyond ``MAX_LIVE_GRANTS_PER_HOST``
        live v2 grants, the oldest ones.
        """

        if not operator_token:
            raise PluginGrantError("operator_auth_not_configured")
        if not isinstance(host, str) or not HOST_RE.match(host):
            raise PluginGrantError("plugin_grant_host_invalid")
        clean_scopes = _normalize_scopes(scopes)
        rooms = _normalize_rooms(conversation_ids)
        if ttl_seconds is None:
            ttl = DEFAULT_TTL_S
        elif isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise PluginGrantError("plugin_grant_request_invalid")
        elif not MIN_TTL_S <= ttl_seconds <= MAX_TTL_S:
            raise PluginGrantError("plugin_grant_request_invalid")
        else:
            ttl = ttl_seconds
        current = now or _utcnow()
        created = _stamp(current)
        pairing_expires = _stamp(current + timedelta(seconds=PAIRING_TTL_S))
        grant_id = _new_grant_id()
        pairing_code = _new_pairing_code()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                for conversation_id in rooms:
                    exists = conn.execute(
                        "select 1 from conversations where id = ?", (conversation_id,)
                    ).fetchone()
                    if exists is None:
                        raise PluginGrantError("room_conversation_unknown")
                conn.execute(
                    f"update plugin_grants set revoked_at = ? where host = ? and {_live_clause()}",
                    (created, host, created, created),
                )
                live = conn.execute(
                    f"select grant_id from plugin_grants_v2 where host = ? and {_live_clause()} "
                    "order by created_at, rowid",
                    (host, created, created),
                ).fetchall()
                excess = len(live) - (MAX_LIVE_GRANTS_PER_HOST - 1)
                for item in live[: max(0, excess)]:
                    conn.execute(
                        "update plugin_grants_v2 set revoked_at = ? where grant_id = ?",
                        (created, str(item["grant_id"])),
                    )
                conn.execute(
                    """insert into plugin_grants_v2
                       (grant_id, host, scopes_json, ttl_seconds, created_at, activated_at,
                        expires_at, pairing_expires_at, revoked_at, last_used_at, use_count,
                        failed_attempts, secret_digest, pairing_code_digest, pairing_consumed,
                        operator_token_fingerprint, last_room_create_at)
                       values (?, ?, ?, ?, ?, null, ?, ?, null, null, 0, 0, null, ?, 0, ?, null)""",
                    (
                        grant_id,
                        host,
                        json.dumps(clean_scopes),
                        ttl,
                        created,
                        pairing_expires,
                        pairing_expires,
                        _digest(pairing_code),
                        operator_token_fingerprint(operator_token),
                    ),
                )
                for conversation_id in rooms:
                    conn.execute(
                        "insert into plugin_grant_rooms"
                        "(grant_id, conversation_id, added_at, added_via) "
                        "values (?, ?, ?, 'issue')",
                        (grant_id, conversation_id, created),
                    )
                row = self._grant_row(conn, grant_id)
                assert row is not None
                grant = _public_grant(conn, row, current)
                conn.commit()
                return grant, pairing_code, pairing_expires
            except Exception:
                conn.rollback()
                raise

    def list_grants(
        self,
        *,
        conversation_id: str | None = None,
        host: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = now or _utcnow()
        with self._connect_readonly() as conn:
            if conversation_id is not None:
                rows = conn.execute(
                    "select g.* from plugin_grants_v2 g join plugin_grant_rooms r "
                    "on r.grant_id = g.grant_id where r.conversation_id = ? "
                    "order by g.created_at desc, g.rowid desc limit ?",
                    (conversation_id, GRANT_LIST_LIMIT),
                ).fetchall()
            else:
                rows = conn.execute(
                    "select * from plugin_grants_v2 where host = ? "
                    "order by created_at desc, rowid desc limit ?",
                    (host, GRANT_LIST_LIMIT),
                ).fetchall()
            return [_public_grant(conn, row, current) for row in rows]

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._connect_readonly() as conn:
            return (
                conn.execute(
                    "select 1 from conversations where id = ? limit 1",
                    (conversation_id,),
                ).fetchone()
                is not None
            )

    def revoke_grant(
        self,
        grant_id: str,
        conversation_id: str | None = None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Revoke one grant; idempotent. A named Room must be in the grant's set (T2)."""

        current = now or _utcnow()
        stamp = _stamp(current)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = self._grant_row(conn, grant_id)
                if row is None or (
                    conversation_id is not None
                    and conversation_id not in _rooms_conn(conn, grant_id)
                ):
                    raise PluginGrantError("plugin_grant_unknown")
                if row["revoked_at"] is None:
                    conn.execute(
                        "update plugin_grants_v2 set revoked_at = ? where grant_id = ?",
                        (stamp, grant_id),
                    )
                row = self._grant_row(conn, grant_id)
                assert row is not None
                grant = _public_grant(conn, row, current)
                conn.commit()
                return grant
            except Exception:
                conn.rollback()
                raise

    def revoke_host(self, host: Any, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Revoke every live v1 and v2 grant of one host."""

        if not isinstance(host, str) or not HOST_RE.match(host):
            raise PluginGrantError("plugin_grant_host_invalid")
        current = now or _utcnow()
        stamp = _stamp(current)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    f"update plugin_grants set revoked_at = ? where host = ? and {_live_clause()}",
                    (stamp, host, stamp, stamp),
                )
                rows = conn.execute(
                    f"select grant_id from plugin_grants_v2 where host = ? and {_live_clause()}",
                    (host, stamp, stamp),
                ).fetchall()
                revoked: list[dict[str, Any]] = []
                for item in rows:
                    conn.execute(
                        "update plugin_grants_v2 set revoked_at = ? where grant_id = ?",
                        (stamp, str(item["grant_id"])),
                    )
                    updated = self._grant_row(conn, str(item["grant_id"]))
                    assert updated is not None
                    revoked.append(_public_grant(conn, updated, current))
                conn.commit()
                return revoked
            except Exception:
                conn.rollback()
                raise

    # -- plugin surface ---------------------------------------------------

    def exchange(
        self, pairing_code: str, host: str, *, now: datetime | None = None
    ) -> tuple[dict[str, Any], str]:
        """Exchange a pairing code for the grant secret (single use)."""

        current = now or _utcnow()
        candidate = pairing_code.strip() if isinstance(pairing_code, str) else ""
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    "delete from plugin_grant_exchange_failures where failed_at <= ?",
                    (_stamp(current - timedelta(seconds=5 * EXCHANGE_FAIL_WINDOW_S)),),
                )
                # The lock lasts a full window from the failure that reached the limit.
                # Nothing is recorded while locked, so that failure is the newest one.
                window = timedelta(seconds=EXCHANGE_FAIL_WINDOW_S)
                failures = conn.execute(
                    "select failed_at from plugin_grant_exchange_failures "
                    "where failed_at > ? order by failed_at desc limit ?",
                    (_stamp(current - 2 * window), EXCHANGE_FAIL_LIMIT),
                ).fetchall()
                if len(failures) >= EXCHANGE_FAIL_LIMIT:
                    newest = _parse_time(str(failures[0]["failed_at"]))
                    limit_start = _parse_time(str(failures[-1]["failed_at"]))
                    if newest - limit_start < window and current < newest + window:
                        retry_after = max(1, math.ceil((newest + window - current).total_seconds()))
                        conn.commit()
                        raise PluginGrantError("plugin_pairing_locked", retry_after=retry_after)
                presented = _digest(candidate)
                match: sqlite3.Row | None = None
                for row in conn.execute(
                    "select * from plugin_grants_v2 "
                    "where pairing_code_digest is not null and pairing_consumed = 0"
                ).fetchall():
                    if hmac.compare_digest(str(row["pairing_code_digest"]), presented):
                        match = row
                        break
                if match is None:
                    self._record_exchange_failure(conn, current)
                    conn.commit()
                    raise PluginGrantError("plugin_pairing_invalid")
                live = (
                    match["revoked_at"] is None
                    and match["activated_at"] is None
                    and current < _parse_time(str(match["pairing_expires_at"]))
                )
                if not live:
                    self._record_exchange_failure(conn, current)
                    conn.commit()
                    raise PluginGrantError("plugin_pairing_invalid")
                if not isinstance(host, str) or host != str(match["host"]):
                    conn.execute(
                        "update plugin_grants_v2 set pairing_consumed = 1 where grant_id = ?",
                        (str(match["grant_id"]),),
                    )
                    self._record_exchange_failure(conn, current)
                    conn.commit()
                    raise PluginGrantError("plugin_pairing_invalid")
                secret = _new_secret(str(match["grant_id"]))
                stamp = _stamp(current)
                expires = _stamp(current + timedelta(seconds=int(match["ttl_seconds"])))
                conn.execute(
                    "update plugin_grants_v2 set pairing_consumed = 1, activated_at = ?, "
                    "expires_at = ?, secret_digest = ? where grant_id = ?",
                    (stamp, expires, _digest(secret), str(match["grant_id"])),
                )
                row = self._grant_row(conn, str(match["grant_id"]))
                assert row is not None
                grant = _public_grant(conn, row, current)
                conn.commit()
                return grant, secret
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    @staticmethod
    def _record_exchange_failure(conn: sqlite3.Connection, now: datetime) -> None:
        conn.execute(
            "insert into plugin_grant_exchange_failures(failure_id, failed_at) values (?, ?)",
            (f"pairfail_{uuid.uuid4().hex}", _stamp(now)),
        )

    def authenticate_bearer(
        self,
        secret: str | None,
        *,
        operator_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Check the bearer itself; one code for every failure (v1 T8).

        Scope and Room membership are checked by the caller afterwards
        (``require_scope``, ``require_room``): a valid bearer that lacks them is
        not a failed attempt.
        """

        current = now or _utcnow()
        grant_id = _secret_grant_id(secret) if isinstance(secret, str) else None
        presented = _digest(secret) if isinstance(secret, str) else ""
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = self._grant_row(conn, grant_id) if grant_id is not None else None
                valid = row is not None and self._bearer_valid(
                    row,
                    presented,
                    operator_token=operator_token,
                    now=current,
                )
                if not valid:
                    if row is not None:
                        failed = int(row["failed_attempts"]) + 1
                        if failed >= MAX_FAILED_BEARERS and row["revoked_at"] is None:
                            conn.execute(
                                "update plugin_grants_v2 set failed_attempts = ?, "
                                "revoked_at = ? where grant_id = ?",
                                (failed, _stamp(current), str(row["grant_id"])),
                            )
                        else:
                            conn.execute(
                                "update plugin_grants_v2 set failed_attempts = ? "
                                "where grant_id = ?",
                                (failed, str(row["grant_id"])),
                            )
                    conn.commit()
                    raise PluginGrantError("plugin_grant_invalid")
                assert row is not None
                auth = {
                    "grant_id": str(row["grant_id"]),
                    "host": str(row["host"]),
                    "scopes": _scopes(row),
                    "conversation_ids": _rooms_conn(conn, str(row["grant_id"])),
                }
                conn.commit()
                return auth
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    @staticmethod
    def has_room(auth: dict[str, Any], conversation_id: Any) -> bool:
        return isinstance(conversation_id, str) and conversation_id in auth["conversation_ids"]

    def _bearer_valid(
        self,
        row: sqlite3.Row,
        presented_digest: str,
        *,
        operator_token: str | None,
        now: datetime,
    ) -> bool:
        stored = row["secret_digest"]
        if not isinstance(stored, str) or not hmac.compare_digest(stored, presented_digest):
            return False
        if _derive_status(row, now) != "active":
            return False
        reference = str(row["activated_at"] or row["created_at"])
        if now < _parse_time(reference) - timedelta(seconds=5):
            return False
        if row["last_used_at"] is not None and now < _parse_time(
            str(row["last_used_at"])
        ) - timedelta(seconds=5):
            return False
        return bool(operator_token) and hmac.compare_digest(
            str(row["operator_token_fingerprint"]),
            operator_token_fingerprint(str(operator_token)),
        )

    def reserve_room_create(self, grant_id: str, *, now: datetime | None = None) -> None:
        """Serialize Room creation per grant: rate limit and the Room-set cap.

        Called after authentication and before the Room is created. At most one
        creation per ``ROOM_CREATE_INTERVAL_S`` per grant keeps concurrent
        creations from overrunning the cap.
        """

        current = now or _utcnow()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = self._grant_row(conn, grant_id)
                if row is None:
                    raise PluginGrantError("plugin_grant_invalid")
                if len(_rooms_conn(conn, grant_id)) >= MAX_GRANT_ROOMS:
                    raise PluginGrantError("plugin_grant_room_limit")
                last = row["last_room_create_at"]
                if last is not None:
                    elapsed = (current - _parse_time(str(last))).total_seconds()
                    if 0 <= elapsed < ROOM_CREATE_INTERVAL_S:
                        conn.commit()
                        raise PluginGrantError(
                            "plugin_room_rate_limited",
                            retry_after=max(1, math.ceil(ROOM_CREATE_INTERVAL_S - elapsed)),
                        )
                conn.execute(
                    "update plugin_grants_v2 set last_room_create_at = ? where grant_id = ?",
                    (_stamp(current), grant_id),
                )
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def add_rooms(
        self,
        grant_id: str,
        conversation_ids: Iterable[str],
        *,
        now: datetime | None = None,
    ) -> int:
        """Append created Rooms to the grant's set (idempotent); returns the set size."""

        current = now or _utcnow()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                for conversation_id in conversation_ids:
                    conn.execute(
                        "insert into plugin_grant_rooms"
                        "(grant_id, conversation_id, added_at, added_via) "
                        "values (?, ?, ?, 'create') on conflict do nothing",
                        (grant_id, conversation_id, _stamp(current)),
                    )
                size = len(_rooms_conn(conn, grant_id))
                conn.commit()
                return size
            except Exception:
                conn.rollback()
                raise

    def record_grant_use(self, grant_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    "update plugin_grants_v2 set last_used_at = ?, use_count = use_count + 1 "
                    "where grant_id = ?",
                    (_stamp(current), grant_id),
                )
                row = self._grant_row(conn, grant_id)
                if row is None:
                    raise PluginGrantError("plugin_grant_unknown")
                grant = _public_grant(conn, row, current)
                conn.commit()
                return grant
            except Exception:
                conn.rollback()
                raise
