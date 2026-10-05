"""Scoped plugin grants for host-plugin split decisions.

Implements the durable side of ``docs/contracts/plugin_grant_v1.md``: the
``plugin_grants`` tables, pairing codes, secret digests, the global pairing
limiter, and the section 4.2 bearer checks. HTTP mapping lives in
``xmuse/chat_api_grants.py``; approved split writes still go through
``RoomBoardStore.decide_split`` with ``decided_via="plugin:<host>"`` and
``operator_identity="plugin-grant:<grant_id>"``.

The secret (256 bits) and the pairing code are never stored in the clear:
only their SHA-256 digests reach ``chat.db``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCOPE_BOARD_SPLIT_DECIDE = "board.split.decide"
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SECRET_RE = re.compile(r"^xpg_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{43}$")
PAIRING_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
PAIRING_CODE_RE = re.compile(
    r"^[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}$"
)
PAIRING_TTL_S = 120
DEFAULT_TTL_S = 600
MIN_TTL_S = 60
MAX_TTL_S = 3600
MAX_FAILED_BEARERS = 5
EXCHANGE_FAIL_LIMIT = 10
EXCHANGE_FAIL_WINDOW_S = 60
TOKEN_FINGERPRINT_CONTEXT = "plugin-grant/v1"
GRANT_LIST_LIMIT = 50


class PluginGrantError(Exception):
    """Stable, client-safe failure raised by the plugin grant store."""

    def __init__(self, code: str, *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def create_plugin_grant_schema(conn: sqlite3.Connection) -> None:
    """Create the additive plugin-grant tables in the caller transaction."""

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


def _public_grant(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
    return {
        "grant_id": str(row["grant_id"]),
        "conversation_id": str(row["conversation_id"]),
        "host": str(row["host"]),
        "scope": str(row["scope"]),
        "status": _derive_status(row, now),
        "created_at": str(row["created_at"]),
        "activated_at": row["activated_at"],
        "expires_at": str(row["expires_at"]),
        "revoked_at": row["revoked_at"],
        "last_used_at": row["last_used_at"],
        "use_count": int(row["use_count"]),
    }


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
                )
            else:
                conn = sqlite3.connect(self._path, timeout=30)
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

    # -- operator surface -------------------------------------------------

    def issue(
        self,
        *,
        conversation_id: str,
        host: Any,
        scope: Any,
        ttl_seconds: Any = None,
        operator_token: str | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], str, str]:
        """Issue a pending grant; revokes earlier live grants for the pair."""

        if not operator_token:
            raise PluginGrantError("operator_auth_not_configured")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise PluginGrantError("plugin_grant_request_invalid")
        if not isinstance(host, str) or not HOST_RE.match(host):
            raise PluginGrantError("plugin_grant_host_invalid")
        if scope != SCOPE_BOARD_SPLIT_DECIDE:
            raise PluginGrantError("plugin_grant_scope_invalid")
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
                exists = conn.execute(
                    "select 1 from conversations where id = ?", (conversation_id,)
                ).fetchone()
                if exists is None:
                    raise PluginGrantError("room_conversation_unknown")
                conn.execute(
                    "update plugin_grants set revoked_at = ? "
                    "where conversation_id = ? and host = ? and revoked_at is null "
                    "and ((activated_at is null and pairing_expires_at > ?) "
                    "or (activated_at is not null and expires_at > ?))",
                    (created, conversation_id, host, created, created),
                )
                conn.execute(
                    """insert into plugin_grants
                       (grant_id, conversation_id, host, scope, ttl_seconds,
                        created_at, activated_at, expires_at, pairing_expires_at,
                        revoked_at, last_used_at, use_count, failed_attempts,
                        secret_digest, pairing_code_digest, pairing_consumed,
                        operator_token_fingerprint)
                       values (?, ?, ?, ?, ?, ?, null, ?, ?, null, null,
                               0, 0, null, ?, 0, ?)""",
                    (
                        grant_id,
                        conversation_id,
                        host,
                        SCOPE_BOARD_SPLIT_DECIDE,
                        ttl,
                        created,
                        pairing_expires,
                        pairing_expires,
                        _digest(pairing_code),
                        operator_token_fingerprint(operator_token),
                    ),
                )
                row = conn.execute(
                    "select * from plugin_grants where grant_id = ?", (grant_id,)
                ).fetchone()
                conn.commit()
                assert row is not None
                return _public_grant(row, current), pairing_code, pairing_expires
            except Exception:
                conn.rollback()
                raise

    def list_grants(
        self, conversation_id: str, *, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        current = now or _utcnow()
        with self._connect_readonly() as conn:
            rows = conn.execute(
                "select * from plugin_grants where conversation_id = ? "
                "order by created_at desc, rowid desc limit ?",
                (conversation_id, GRANT_LIST_LIMIT),
            ).fetchall()
        return [_public_grant(row, current) for row in rows]

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
        self, grant_id: str, conversation_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Revoke one grant; idempotent, conversation-scoped (T2)."""

        current = now or _utcnow()
        stamp = _stamp(current)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from plugin_grants where grant_id = ?", (grant_id,)
                ).fetchone()
                if row is None or str(row["conversation_id"]) != conversation_id:
                    raise PluginGrantError("plugin_grant_unknown")
                if row["revoked_at"] is None:
                    conn.execute(
                        "update plugin_grants set revoked_at = ? where grant_id = ?",
                        (stamp, grant_id),
                    )
                row = conn.execute(
                    "select * from plugin_grants where grant_id = ?", (grant_id,)
                ).fetchone()
                assert row is not None
                conn.commit()
                return _public_grant(row, current)
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
                    "select * from plugin_grants "
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
                        "update plugin_grants set pairing_consumed = 1 where grant_id = ?",
                        (str(match["grant_id"]),),
                    )
                    self._record_exchange_failure(conn, current)
                    conn.commit()
                    raise PluginGrantError("plugin_pairing_invalid")
                secret = _new_secret(str(match["grant_id"]))
                stamp = _stamp(current)
                expires = _stamp(current + timedelta(seconds=int(match["ttl_seconds"])))
                conn.execute(
                    "update plugin_grants set pairing_consumed = 1, activated_at = ?, "
                    "expires_at = ?, secret_digest = ? where grant_id = ?",
                    (stamp, expires, _digest(secret), str(match["grant_id"])),
                )
                row = conn.execute(
                    "select * from plugin_grants where grant_id = ?",
                    (str(match["grant_id"]),),
                ).fetchone()
                assert row is not None
                conn.commit()
                return _public_grant(row, current), secret
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
        conversation_id: str | None = None,
        operator_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        """Run the section 4.2 step-1 checks; one code for every failure (T8)."""

        current = now or _utcnow()
        grant_id = _secret_grant_id(secret) if isinstance(secret, str) else None
        presented = _digest(secret) if isinstance(secret, str) else ""
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = (
                    conn.execute(
                        "select * from plugin_grants where grant_id = ?", (grant_id,)
                    ).fetchone()
                    if grant_id is not None
                    else None
                )
                valid = row is not None and self._bearer_valid(
                    row,
                    presented,
                    conversation_id=conversation_id,
                    operator_token=operator_token,
                    now=current,
                )
                if not valid:
                    if row is not None:
                        failed = int(row["failed_attempts"]) + 1
                        if failed >= MAX_FAILED_BEARERS and row["revoked_at"] is None:
                            conn.execute(
                                "update plugin_grants set failed_attempts = ?, "
                                "revoked_at = ? where grant_id = ?",
                                (failed, _stamp(current), str(row["grant_id"])),
                            )
                        else:
                            conn.execute(
                                "update plugin_grants set failed_attempts = ? where grant_id = ?",
                                (failed, str(row["grant_id"])),
                            )
                    conn.commit()
                    raise PluginGrantError("plugin_grant_invalid")
                assert row is not None
                conn.commit()
                return {
                    "grant_id": str(row["grant_id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "host": str(row["host"]),
                }
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def _bearer_valid(
        self,
        row: sqlite3.Row,
        presented_digest: str,
        *,
        conversation_id: str | None,
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
        if not operator_token or not hmac.compare_digest(
            str(row["operator_token_fingerprint"]),
            operator_token_fingerprint(operator_token),
        ):
            return False
        if str(row["scope"]) != SCOPE_BOARD_SPLIT_DECIDE:
            return False
        if conversation_id is not None and conversation_id != str(row["conversation_id"]):
            return False
        return True

    def record_grant_use(self, grant_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or _utcnow()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                conn.execute(
                    "update plugin_grants set last_used_at = ?, use_count = use_count + 1 "
                    "where grant_id = ?",
                    (_stamp(current), grant_id),
                )
                row = conn.execute(
                    "select * from plugin_grants where grant_id = ?", (grant_id,)
                ).fetchone()
                if row is None:
                    raise PluginGrantError("plugin_grant_unknown")
                conn.commit()
                return _public_grant(row, current)
            except Exception:
                conn.rollback()
                raise
