from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.structuring.models import PlanningRun, PlanningRunStatus

_TERMINAL_OR_FAILED_STATUSES = (
    PlanningRunStatus.TERMINAL.value,
    PlanningRunStatus.FAILED.value,
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class PlanningRunStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._init_db()

    def save(self, run: PlanningRun) -> PlanningRun:
        with self._connect() as conn:
            self._save_with_conn(conn, run)
        return run

    def get(self, planning_run_id: str) -> PlanningRun:
        with self._connect() as conn:
            row = conn.execute(
                "select * from planning_runs where planning_run_id = ?",
                (planning_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown planning run: {planning_run_id}")
        return self._from_row(row)

    def list_by_dedupe_key(self, dedupe_key: str) -> list[PlanningRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from planning_runs
                where dedupe_key = ?
                order by rerun_sequence asc, created_at asc, planning_run_id asc
                """,
                (dedupe_key,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_active_by_dedupe_key(self, dedupe_key: str) -> PlanningRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from planning_runs
                where dedupe_key = ?
                  and status not in (?, ?)
                order by rerun_sequence desc, updated_at desc, planning_run_id desc
                limit 1
                """,
                (dedupe_key, *_TERMINAL_OR_FAILED_STATUSES),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def get_latest_terminal_or_failed_by_dedupe_key(
        self,
        dedupe_key: str,
    ) -> PlanningRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from planning_runs
                where dedupe_key = ?
                  and status in (?, ?)
                order by rerun_sequence desc, updated_at desc, planning_run_id desc
                limit 1
                """,
                (dedupe_key, *_TERMINAL_OR_FAILED_STATUSES),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def create_or_get_initial(
        self,
        *,
        conversation_id: str,
        blueprint_ref: str,
        blueprint_version: int,
        dedupe_key: str,
        planning_run_id: str | None = None,
        created_by: str = "god",
    ) -> PlanningRun:
        with self._connect() as conn:
            conn.execute("begin immediate")
            active = conn.execute(
                """
                select * from planning_runs
                where dedupe_key = ?
                  and status not in (?, ?)
                order by rerun_sequence desc, updated_at desc, planning_run_id desc
                limit 1
                """,
                (dedupe_key, *_TERMINAL_OR_FAILED_STATUSES),
            ).fetchone()
            if active is not None:
                conn.commit()
                return self._from_row(active)

            closed = conn.execute(
                """
                select * from planning_runs
                where dedupe_key = ?
                  and status in (?, ?)
                order by rerun_sequence desc, updated_at desc, planning_run_id desc
                limit 1
                """,
                (dedupe_key, *_TERMINAL_OR_FAILED_STATUSES),
            ).fetchone()
            if closed is not None:
                conn.commit()
                return self._from_row(closed)

            now = _utc_now()
            run = PlanningRun(
                planning_run_id=planning_run_id or _new_id("planrun"),
                conversation_id=conversation_id,
                blueprint_ref=blueprint_ref,
                blueprint_version=blueprint_version,
                dedupe_key=dedupe_key,
                rerun_sequence=0,
                rerun_of=None,
                status=PlanningRunStatus.PLANNING,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                insert into planning_runs (
                    planning_run_id,
                    conversation_id,
                    blueprint_ref,
                    blueprint_version,
                    dedupe_key,
                    rerun_sequence,
                    rerun_of,
                    status,
                    feature_plan_id,
                    feature_plan_version,
                    graph_set_id,
                    graph_set_version,
                    risk_level,
                    trigger_owner,
                    human_trigger_enabled,
                    manual_review_mode,
                    review_policy,
                    queue_backend,
                    external_mq,
                    created_by,
                    audit_refs_json,
                    chat_card_refs_json,
                    retry_count,
                    created_at,
                    updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._params(run),
            )
            conn.commit()
            return run

    def create_next_rerun(
        self,
        *,
        conversation_id: str,
        blueprint_ref: str,
        blueprint_version: int,
        dedupe_key: str,
        rerun_of: str,
        planning_run_id: str | None = None,
        created_by: str = "god",
    ) -> PlanningRun:
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """
                select coalesce(max(rerun_sequence), 0) as max_sequence
                from planning_runs
                where dedupe_key = ?
                """,
                (dedupe_key,),
            ).fetchone()
            next_sequence = int(row["max_sequence"]) + 1
            now = _utc_now()
            run = PlanningRun(
                planning_run_id=planning_run_id or _new_id("planrun"),
                conversation_id=conversation_id,
                blueprint_ref=blueprint_ref,
                blueprint_version=blueprint_version,
                dedupe_key=dedupe_key,
                rerun_sequence=next_sequence,
                rerun_of=rerun_of,
                status=PlanningRunStatus.PLANNING,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                insert into planning_runs (
                    planning_run_id,
                    conversation_id,
                    blueprint_ref,
                    blueprint_version,
                    dedupe_key,
                    rerun_sequence,
                    rerun_of,
                    status,
                    feature_plan_id,
                    feature_plan_version,
                    graph_set_id,
                    graph_set_version,
                    risk_level,
                    trigger_owner,
                    human_trigger_enabled,
                    manual_review_mode,
                    review_policy,
                    queue_backend,
                    external_mq,
                    created_by,
                    audit_refs_json,
                    chat_card_refs_json,
                    retry_count,
                    created_at,
                    updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._params(run),
            )
            conn.commit()
            return run

    def append_artifact_refs(
        self,
        planning_run_id: str,
        *,
        audit_refs: list[str] | None = None,
        chat_card_refs: list[str] | None = None,
        human_trigger_enabled: bool | None = None,
        updated_at: str | None = None,
    ) -> PlanningRun:
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select * from planning_runs where planning_run_id = ?",
                (planning_run_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"unknown planning run: {planning_run_id}")
            run = self._from_row(row)
            run = run.model_copy(
                update={
                    "audit_refs": _append_unique_refs(run.audit_refs, audit_refs or []),
                    "chat_card_refs": _append_unique_refs(
                        run.chat_card_refs,
                        chat_card_refs or [],
                    ),
                    "human_trigger_enabled": (
                        run.human_trigger_enabled
                        if human_trigger_enabled is None
                        else human_trigger_enabled
                    ),
                    "updated_at": updated_at or run.updated_at,
                }
            )
            self._save_with_conn(conn, run)
            conn.commit()
            return run

    def _init_db(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists planning_runs (
                    planning_run_id text primary key,
                    conversation_id text not null,
                    blueprint_ref text not null,
                    blueprint_version integer not null,
                    dedupe_key text not null,
                    rerun_sequence integer not null,
                    rerun_of text,
                    status text not null,
                    feature_plan_id text,
                    feature_plan_version integer,
                    graph_set_id text,
                    graph_set_version integer,
                    risk_level text not null,
                    trigger_owner text not null,
                    human_trigger_enabled integer not null,
                    manual_review_mode integer not null,
                    review_policy text not null,
                    queue_backend text not null,
                    external_mq text not null,
                    created_by text not null,
                    audit_refs_json text not null,
                    chat_card_refs_json text not null,
                    retry_count integer not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create unique index if not exists planning_runs_dedupe_key_rerun_sequence_unique
                on planning_runs (dedupe_key, rerun_sequence)
                """
            )
            conn.execute(
                """
                create unique index if not exists planning_runs_single_active_per_dedupe_key
                on planning_runs (dedupe_key)
                where status not in ('terminal', 'failed')
                """
            )
            conn.execute(
                """
                create index if not exists planning_runs_dedupe_key_lookup
                on planning_runs (dedupe_key, rerun_sequence, updated_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _save_with_conn(self, conn: sqlite3.Connection, run: PlanningRun) -> None:
        conn.execute(
            """
            insert into planning_runs (
                planning_run_id,
                conversation_id,
                blueprint_ref,
                blueprint_version,
                dedupe_key,
                rerun_sequence,
                rerun_of,
                status,
                feature_plan_id,
                feature_plan_version,
                graph_set_id,
                graph_set_version,
                risk_level,
                trigger_owner,
                human_trigger_enabled,
                manual_review_mode,
                review_policy,
                queue_backend,
                external_mq,
                created_by,
                audit_refs_json,
                chat_card_refs_json,
                retry_count,
                created_at,
                updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(planning_run_id) do update set
                conversation_id = excluded.conversation_id,
                blueprint_ref = excluded.blueprint_ref,
                blueprint_version = excluded.blueprint_version,
                dedupe_key = excluded.dedupe_key,
                rerun_sequence = excluded.rerun_sequence,
                rerun_of = excluded.rerun_of,
                status = excluded.status,
                feature_plan_id = excluded.feature_plan_id,
                feature_plan_version = excluded.feature_plan_version,
                graph_set_id = excluded.graph_set_id,
                graph_set_version = excluded.graph_set_version,
                risk_level = excluded.risk_level,
                trigger_owner = excluded.trigger_owner,
                human_trigger_enabled = excluded.human_trigger_enabled,
                manual_review_mode = excluded.manual_review_mode,
                review_policy = excluded.review_policy,
                queue_backend = excluded.queue_backend,
                external_mq = excluded.external_mq,
                created_by = excluded.created_by,
                audit_refs_json = excluded.audit_refs_json,
                chat_card_refs_json = excluded.chat_card_refs_json,
                retry_count = excluded.retry_count,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            self._params(run),
        )

    def _from_row(self, row: sqlite3.Row) -> PlanningRun:
        return PlanningRun(
            planning_run_id=row["planning_run_id"],
            conversation_id=row["conversation_id"],
            blueprint_ref=row["blueprint_ref"],
            blueprint_version=row["blueprint_version"],
            dedupe_key=row["dedupe_key"],
            rerun_sequence=row["rerun_sequence"],
            rerun_of=row["rerun_of"],
            status=row["status"],
            feature_plan_id=row["feature_plan_id"],
            feature_plan_version=row["feature_plan_version"],
            graph_set_id=row["graph_set_id"],
            graph_set_version=row["graph_set_version"],
            risk_level=row["risk_level"],
            trigger_owner=row["trigger_owner"],
            human_trigger_enabled=bool(row["human_trigger_enabled"]),
            manual_review_mode=bool(row["manual_review_mode"]),
            review_policy=row["review_policy"],
            queue_backend=row["queue_backend"],
            external_mq=row["external_mq"],
            created_by=row["created_by"],
            audit_refs=json.loads(row["audit_refs_json"]),
            chat_card_refs=json.loads(row["chat_card_refs_json"]),
            retry_count=row["retry_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _params(self, run: PlanningRun) -> tuple[object, ...]:
        return (
            run.planning_run_id,
            run.conversation_id,
            run.blueprint_ref,
            run.blueprint_version,
            run.dedupe_key,
            run.rerun_sequence,
            run.rerun_of,
            run.status.value,
            run.feature_plan_id,
            run.feature_plan_version,
            run.graph_set_id,
            run.graph_set_version,
            run.risk_level,
            run.trigger_owner,
            int(run.human_trigger_enabled),
            int(run.manual_review_mode),
            run.review_policy,
            run.queue_backend,
            run.external_mq,
            run.created_by,
            json.dumps(run.audit_refs),
            json.dumps(run.chat_card_refs),
            run.retry_count,
            run.created_at,
            run.updated_at,
        )


def _append_unique_refs(existing: list[str], new_values: list[str]) -> list[str]:
    merged = list(existing)
    for value in new_values:
        if value not in merged:
            merged.append(value)
    return merged
