from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from xmuse_core.structuring.models import PlanningEvent, PlanningEventStatus


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _coerce_now(value: datetime | None) -> datetime:
    return _utc_now() if value is None else value.astimezone(UTC).replace(microsecond=0)


def _coerce_ttl(value: timedelta | int | float) -> timedelta:
    if isinstance(value, timedelta):
        return value
    return timedelta(seconds=float(value))


class PlanningEventStore:
    def __init__(self, path: Path | str, *, backend: str = "sqlite") -> None:
        self._path = Path(path)
        normalized_backend = "json" if backend == "file" else backend
        self._backend = normalized_backend
        if normalized_backend == "sqlite":
            self._init_db()
        elif normalized_backend == "json":
            self._init_json()
        else:
            raise ValueError(f"unsupported planning event backend: {backend}")

    def enqueue(self, event: PlanningEvent) -> PlanningEvent:
        if self._backend == "sqlite":
            return self._enqueue_sqlite(event)
        return self._enqueue_json(event)

    def get(self, event_id: str) -> PlanningEvent:
        if self._backend == "sqlite":
            with self._connect() as conn:
                row = conn.execute(
                    "select * from planning_events where event_id = ?",
                    (event_id,),
                ).fetchone()
            if row is None:
                raise KeyError(event_id)
            return self._from_row(row)

        for event in self._load_json():
            if event.event_id == event_id:
                return event
        raise KeyError(event_id)

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_ttl: timedelta | int | float,
        event_type: str | None = None,
        now: datetime | None = None,
    ) -> PlanningEvent | None:
        if self._backend == "sqlite":
            return self._claim_next_sqlite(
                worker_id=worker_id,
                lease_ttl=lease_ttl,
                event_type=event_type,
                now=now,
            )
        return self._claim_next_json(
            worker_id=worker_id,
            lease_ttl=lease_ttl,
            event_type=event_type,
            now=now,
        )

    def heartbeat(self, event_id: str, *, now: datetime | None = None) -> PlanningEvent:
        if self._backend == "sqlite":
            return self._heartbeat_sqlite(event_id, now=now)
        return self._heartbeat_json(event_id, now=now)

    def attach_planning_run(self, event_id: str, planning_run_id: str) -> PlanningEvent:
        if self._backend == "sqlite":
            with self._connect() as conn:
                conn.execute(
                    """
                    update planning_events
                    set planning_run_id = ?, updated_at = ?
                    where event_id = ?
                    """,
                    (planning_run_id, _iso(_utc_now()), event_id),
                )
            return self.get(event_id)

        updated = self.get(event_id).model_copy(
            update={
                "planning_run_id": planning_run_id,
                "updated_at": _iso(_utc_now()),
            }
        )
        self._replace_json(updated)
        return updated

    def ack(self, event_id: str, *, now: datetime | None = None) -> PlanningEvent:
        if self._backend == "sqlite":
            return self._ack_sqlite(event_id, now=now)
        return self._ack_json(event_id, now=now)

    def nack(
        self,
        event_id: str,
        *,
        retry_after: timedelta | int | float,
        reason: str,
        now: datetime | None = None,
    ) -> PlanningEvent:
        if self._backend == "sqlite":
            return self._nack_sqlite(event_id, retry_after=retry_after, reason=reason, now=now)
        return self._nack_json(event_id, retry_after=retry_after, reason=reason, now=now)

    def reclaim_stale_leases(self, *, now: datetime | None = None) -> list[PlanningEvent]:
        if self._backend == "sqlite":
            return self._reclaim_stale_leases_sqlite(now=now)
        return self._reclaim_stale_leases_json(now=now)

    def _enqueue_sqlite(self, event: PlanningEvent) -> PlanningEvent:
        with self._connect() as conn:
            conn.execute(
                """
                insert into planning_events (
                    event_id,
                    event_type,
                    planning_run_id,
                    conversation_id,
                    blueprint_ref,
                    dedupe_key,
                    idempotency_key,
                    status,
                    attempt,
                    lease_owner,
                    lease_expires_at,
                    payload_json,
                    created_at,
                    updated_at,
                    available_at,
                    last_error_reason,
                    lease_ttl_seconds,
                    recovered_from_stale_lease
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(idempotency_key) do nothing
                """,
                self._params(event),
            )
            row = conn.execute(
                "select * from planning_events where idempotency_key = ?",
                (event.idempotency_key,),
            ).fetchone()
        if row is None:
            raise KeyError(event.idempotency_key)
        return self._from_row(row)

    def _enqueue_json(self, event: PlanningEvent) -> PlanningEvent:
        events = self._load_json()
        for existing in events:
            if existing.idempotency_key == event.idempotency_key:
                return existing
        events.append(event)
        self._write_json(events)
        return event

    def _claim_next_sqlite(
        self,
        *,
        worker_id: str,
        lease_ttl: timedelta | int | float,
        event_type: str | None,
        now: datetime | None,
    ) -> PlanningEvent | None:
        now_dt = _coerce_now(now)
        now_str = _iso(now_dt)
        lease = _coerce_ttl(lease_ttl)
        expires = _iso(now_dt + lease)
        query = """
            select * from planning_events
            where status = ?
              and (available_at is null or available_at <= ?)
        """
        params: list[object] = [PlanningEventStatus.QUEUED.value, now_str]
        if event_type is not None:
            query += "\n  and event_type = ?"
            params.append(event_type)
        query += "\norder by created_at asc, event_id asc\nlimit 1"
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(query, params).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                update planning_events
                set status = ?,
                    attempt = attempt + 1,
                    lease_owner = ?,
                    lease_expires_at = ?,
                    lease_ttl_seconds = ?,
                    updated_at = ?
                where event_id = ?
                """,
                (
                    PlanningEventStatus.CLAIMED.value,
                    worker_id,
                    expires,
                    int(lease.total_seconds()),
                    now_str,
                    row["event_id"],
                ),
            )
            conn.commit()
        return self.get(row["event_id"])

    def _claim_next_json(
        self,
        *,
        worker_id: str,
        lease_ttl: timedelta | int | float,
        event_type: str | None,
        now: datetime | None,
    ) -> PlanningEvent | None:
        now_dt = _coerce_now(now)
        lease = _coerce_ttl(lease_ttl)
        events = self._load_json()
        for event in sorted(events, key=lambda item: (item.created_at, item.event_id)):
            if event.status is not PlanningEventStatus.QUEUED:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            if event.available_at is not None and _parse(event.available_at) > now_dt:
                continue
            claimed = event.model_copy(
                update={
                    "status": PlanningEventStatus.CLAIMED,
                    "attempt": event.attempt + 1,
                    "lease_owner": worker_id,
                    "lease_expires_at": _iso(now_dt + lease),
                    "lease_ttl_seconds": int(lease.total_seconds()),
                    "updated_at": _iso(now_dt),
                }
            )
            self._replace_json(claimed, events=events)
            return claimed
        return None

    def _heartbeat_sqlite(self, event_id: str, *, now: datetime | None) -> PlanningEvent:
        event = self.get(event_id)
        ttl_seconds = event.lease_ttl_seconds or 60
        now_dt = _coerce_now(now)
        base_dt = now_dt
        if event.lease_expires_at is not None:
            base_dt = max(base_dt, _parse(event.lease_expires_at))
        with self._connect() as conn:
            conn.execute(
                """
                update planning_events
                set lease_expires_at = ?, updated_at = ?
                where event_id = ? and status = ?
                """,
                (
                    _iso(base_dt + timedelta(seconds=ttl_seconds)),
                    _iso(now_dt),
                    event_id,
                    PlanningEventStatus.CLAIMED.value,
                ),
            )
        return self.get(event_id)

    def _heartbeat_json(self, event_id: str, *, now: datetime | None) -> PlanningEvent:
        event = self.get(event_id)
        now_dt = _coerce_now(now)
        ttl_seconds = event.lease_ttl_seconds or 60
        base_dt = now_dt
        if event.lease_expires_at is not None:
            base_dt = max(base_dt, _parse(event.lease_expires_at))
        updated = event.model_copy(
            update={
                "lease_expires_at": _iso(base_dt + timedelta(seconds=ttl_seconds)),
                "updated_at": _iso(now_dt),
            }
        )
        self._replace_json(updated)
        return updated

    def _ack_sqlite(self, event_id: str, *, now: datetime | None) -> PlanningEvent:
        now_dt = _coerce_now(now)
        with self._connect() as conn:
            conn.execute(
                """
                update planning_events
                set status = ?,
                    lease_owner = null,
                    lease_expires_at = null,
                    lease_ttl_seconds = null,
                    updated_at = ?
                where event_id = ?
                """,
                (PlanningEventStatus.ACKED.value, _iso(now_dt), event_id),
            )
        return self.get(event_id)

    def _ack_json(self, event_id: str, *, now: datetime | None) -> PlanningEvent:
        now_dt = _coerce_now(now)
        updated = self.get(event_id).model_copy(
            update={
                "status": PlanningEventStatus.ACKED,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_ttl_seconds": None,
                "updated_at": _iso(now_dt),
            }
        )
        self._replace_json(updated)
        return updated

    def _nack_sqlite(
        self,
        event_id: str,
        *,
        retry_after: timedelta | int | float,
        reason: str,
        now: datetime | None,
    ) -> PlanningEvent:
        now_dt = _coerce_now(now)
        retry_at = _iso(now_dt + _coerce_ttl(retry_after))
        with self._connect() as conn:
            conn.execute(
                """
                update planning_events
                set status = ?,
                    lease_owner = null,
                    lease_expires_at = null,
                    lease_ttl_seconds = null,
                    available_at = ?,
                    last_error_reason = ?,
                    updated_at = ?
                where event_id = ?
                """,
                (
                    PlanningEventStatus.QUEUED.value,
                    retry_at,
                    reason,
                    _iso(now_dt),
                    event_id,
                ),
            )
        return self.get(event_id)

    def _nack_json(
        self,
        event_id: str,
        *,
        retry_after: timedelta | int | float,
        reason: str,
        now: datetime | None,
    ) -> PlanningEvent:
        now_dt = _coerce_now(now)
        updated = self.get(event_id).model_copy(
            update={
                "status": PlanningEventStatus.QUEUED,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_ttl_seconds": None,
                "available_at": _iso(now_dt + _coerce_ttl(retry_after)),
                "last_error_reason": reason,
                "updated_at": _iso(now_dt),
            }
        )
        self._replace_json(updated)
        return updated

    def _reclaim_stale_leases_sqlite(self, *, now: datetime | None) -> list[PlanningEvent]:
        now_dt = _coerce_now(now)
        now_str = _iso(now_dt)
        with self._connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """
                select * from planning_events
                where status = ?
                  and lease_expires_at is not null
                  and lease_expires_at <= ?
                order by created_at asc, event_id asc
                """,
                (PlanningEventStatus.CLAIMED.value, now_str),
            ).fetchall()
            event_ids = [row["event_id"] for row in rows]
            if event_ids:
                conn.executemany(
                    """
                    update planning_events
                    set status = ?,
                        lease_owner = null,
                        lease_expires_at = null,
                        lease_ttl_seconds = null,
                        recovered_from_stale_lease = 1,
                        updated_at = ?
                    where event_id = ?
                    """,
                    [
                        (PlanningEventStatus.QUEUED.value, now_str, event_id)
                        for event_id in event_ids
                    ],
                )
            conn.commit()
        return [self.get(event_id) for event_id in event_ids]

    def _reclaim_stale_leases_json(self, *, now: datetime | None) -> list[PlanningEvent]:
        now_dt = _coerce_now(now)
        events = self._load_json()
        updated_events: list[PlanningEvent] = []
        for event in events:
            if event.status is not PlanningEventStatus.CLAIMED:
                continue
            if event.lease_expires_at is None or _parse(event.lease_expires_at) > now_dt:
                continue
            updated = event.model_copy(
                update={
                    "status": PlanningEventStatus.QUEUED,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "lease_ttl_seconds": None,
                    "recovered_from_stale_lease": True,
                    "updated_at": _iso(now_dt),
                }
            )
            updated_events.append(updated)
            self._replace_json(updated, events=events)
            events = self._load_json()
        return updated_events

    def _init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists planning_events (
                    event_id text primary key,
                    event_type text not null,
                    planning_run_id text,
                    conversation_id text not null,
                    blueprint_ref text not null,
                    dedupe_key text not null,
                    idempotency_key text not null,
                    status text not null,
                    attempt integer not null,
                    lease_owner text,
                    lease_expires_at text,
                    payload_json text not null,
                    created_at text not null,
                    updated_at text not null,
                    available_at text,
                    last_error_reason text,
                    lease_ttl_seconds integer,
                    recovered_from_stale_lease integer not null default 0
                )
                """
            )
            conn.execute(
                """
                create unique index if not exists planning_events_idempotency_key_unique
                on planning_events (idempotency_key)
                """
            )
            conn.execute(
                """
                create index if not exists planning_events_claimable_lookup
                on planning_events (status, available_at, created_at)
                """
            )
            conn.execute(
                """
                create index if not exists planning_events_stale_lease_lookup
                on planning_events (status, lease_expires_at)
                """
            )

    def _init_json(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]\n", encoding="utf-8")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _from_row(self, row: sqlite3.Row) -> PlanningEvent:
        return PlanningEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            planning_run_id=row["planning_run_id"],
            conversation_id=row["conversation_id"],
            blueprint_ref=row["blueprint_ref"],
            dedupe_key=row["dedupe_key"],
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            attempt=row["attempt"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            available_at=row["available_at"],
            last_error_reason=row["last_error_reason"],
            lease_ttl_seconds=row["lease_ttl_seconds"],
            recovered_from_stale_lease=bool(row["recovered_from_stale_lease"]),
        )

    def _params(self, event: PlanningEvent) -> tuple[object, ...]:
        return (
            event.event_id,
            event.event_type,
            event.planning_run_id,
            event.conversation_id,
            event.blueprint_ref,
            event.dedupe_key,
            event.idempotency_key,
            event.status.value,
            event.attempt,
            event.lease_owner,
            event.lease_expires_at,
            json.dumps(event.payload),
            event.created_at,
            event.updated_at,
            event.available_at,
            event.last_error_reason,
            event.lease_ttl_seconds,
            int(event.recovered_from_stale_lease),
        )

    def _load_json(self) -> list[PlanningEvent]:
        self._init_json()
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return [PlanningEvent.model_validate(item) for item in raw]

    def _write_json(self, events: list[PlanningEvent]) -> None:
        payload = [event.model_dump(mode="json") for event in events]
        self._path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _replace_json(
        self,
        event: PlanningEvent,
        *,
        events: list[PlanningEvent] | None = None,
    ) -> None:
        loaded = list(events) if events is not None else self._load_json()
        replaced = False
        for index, existing in enumerate(loaded):
            if existing.event_id == event.event_id:
                loaded[index] = event
                replaced = True
                break
        if not replaced:
            raise KeyError(event.event_id)
        self._write_json(loaded)
