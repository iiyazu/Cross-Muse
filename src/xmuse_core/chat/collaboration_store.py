from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from xmuse_core.chat.collaboration_contracts import (
    MAX_COLLABORATION_TARGETS,
    TERMINAL_COLLABORATION_STATUSES,
    CollaborationBlocker,
    CollaborationDispatchGateEvent,
    CollaborationResponse,
    CollaborationRun,
    CollaborationStatus,
    DispatchGateDecision,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ChatCollaborationStore:
    """Durable chat-owned store for V14 groupchat collaboration state."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_request(
        self,
        *,
        conversation_id: str,
        goal: str,
        initiator: str,
        targets: list[str],
        callback_target: str,
        question: str,
        context_refs: list[str],
        idempotency_key: str | None,
        timeout_s: int,
        orchestration_mode: Literal["peer_consensus", "leader_assisted"] = "peer_consensus",
        max_depth: int = 1,
        current_depth: int = 0,
    ) -> CollaborationRun:
        clean_targets = _clean_unique(targets)
        if not 1 <= len(clean_targets) <= MAX_COLLABORATION_TARGETS:
            raise ValueError(f"collaboration request requires 1-3 targets, got {len(targets)}")
        clean_initiator = _required(initiator, "initiator")
        clean_callback = _required(callback_target, "callback_target")
        if idempotency_key:
            existing = self.find_by_idempotency_key(conversation_id, idempotency_key)
            if existing is not None:
                return existing
        if self.is_active_target(conversation_id, clean_initiator):
            raise ValueError("anti-cascade: active collaboration targets cannot create requests")

        now = _utc_now()
        run = CollaborationRun(
            run_id=_new_id("collab"),
            conversation_id=conversation_id,
            goal=_required(goal, "goal"),
            orchestration_mode=orchestration_mode,
            status=CollaborationStatus.RUNNING,
            initiator=clean_initiator,
            targets=clean_targets,
            callback_target=clean_callback,
            question=_required(question, "question"),
            context_refs=[ref for ref in context_refs if str(ref).strip()],
            idempotency_key=idempotency_key.strip() if isinstance(idempotency_key, str) else None,
            timeout_s=int(timeout_s),
            max_depth=max_depth,
            current_depth=current_depth,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_runs (
                    run_id, conversation_id, goal, orchestration_mode, status,
                    initiator, targets_json, callback_target, question,
                    context_refs_json, idempotency_key, timeout_s, max_depth,
                    current_depth, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.conversation_id,
                    run.goal,
                    run.orchestration_mode,
                    run.status.value,
                    run.initiator,
                    json.dumps(run.targets),
                    run.callback_target,
                    run.question,
                    json.dumps(run.context_refs),
                    run.idempotency_key,
                    run.timeout_s,
                    run.max_depth,
                    run.current_depth,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    def find_by_idempotency_key(
        self,
        conversation_id: str,
        idempotency_key: str,
    ) -> CollaborationRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from collaboration_runs
                where conversation_id = ? and idempotency_key = ?
                """,
                (conversation_id, idempotency_key),
            ).fetchone()
        return self._run_from_row(row) if row else None

    def get_run(self, run_id: str) -> CollaborationRun:
        with self._connect() as conn:
            row = conn.execute(
                "select * from collaboration_runs where run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown collaboration run: {run_id}")
        return self._run_from_row(row)

    def list_runs(self, conversation_id: str) -> list[CollaborationRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_runs
                where conversation_id = ?
                order by rowid asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def record_response(
        self,
        run_id: str,
        *,
        target: str,
        content: str,
        response_status: Literal["received", "timeout", "failed"],
    ) -> CollaborationRun:
        run = self.get_run(run_id)
        if run.status in TERMINAL_COLLABORATION_STATUSES:
            return run
        clean_target = _required(target, "target")
        if clean_target not in run.targets:
            return run
        if any(response.target == clean_target for response in run.responses):
            return run

        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_responses (
                    response_id, run_id, target, content, status, created_at
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("collab_resp"),
                    run_id,
                    clean_target,
                    content,
                    response_status,
                    now,
                ),
            )
            response_count = conn.execute(
                "select count(*) as c from collaboration_responses where run_id = ?",
                (run_id,),
            ).fetchone()["c"]
            new_status = (
                CollaborationStatus.DONE
                if int(response_count) >= len(run.targets)
                else CollaborationStatus.PARTIAL
            )
            conn.execute(
                """
                update collaboration_runs
                set status = ?, updated_at = ?
                where run_id = ?
                """,
                (new_status.value, now, run_id),
            )
        return self.get_run(run_id)

    def mark_timeout(self, run_id: str) -> CollaborationRun:
        run = self.get_run(run_id)
        if run.status in TERMINAL_COLLABORATION_STATUSES:
            return run
        existing = {response.target for response in run.responses}
        now = _utc_now()
        with self._connect() as conn:
            for target in run.targets:
                if target in existing:
                    continue
                conn.execute(
                    """
                    insert into collaboration_responses (
                        response_id, run_id, target, content, status, created_at
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (_new_id("collab_resp"), run_id, target, "", "timeout", now),
                )
            conn.execute(
                """
                update collaboration_runs
                set status = ?, updated_at = ?
                where run_id = ?
                """,
                (CollaborationStatus.TIMEOUT.value, now, run_id),
            )
        return self.get_run(run_id)

    def raise_blocker(
        self,
        run_id: str,
        *,
        issuer: str,
        severity: Literal["info", "warning", "blocker", "veto"],
        reason: str,
        affected_ref: str,
        suggested_fix: str,
        blocks_dispatch: bool,
    ) -> CollaborationBlocker:
        run = self.get_run(run_id)
        now = _utc_now()
        blocker = CollaborationBlocker(
            blocker_id=_new_id("collab_blocker"),
            run_id=run_id,
            conversation_id=run.conversation_id,
            issuer=_required(issuer, "issuer"),
            severity=severity,
            reason=_required(reason, "reason"),
            affected_ref=_required(affected_ref, "affected_ref"),
            suggested_fix=_required(suggested_fix, "suggested_fix"),
            active=True,
            blocks_dispatch=blocks_dispatch,
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_blockers (
                    blocker_id, run_id, conversation_id, issuer, severity,
                    reason, affected_ref, suggested_fix, active, blocks_dispatch,
                    resolution_evidence, resolved_by, created_at, resolved_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    blocker.blocker_id,
                    blocker.run_id,
                    blocker.conversation_id,
                    blocker.issuer,
                    blocker.severity,
                    blocker.reason,
                    blocker.affected_ref,
                    blocker.suggested_fix,
                    1,
                    1 if blocker.blocks_dispatch else 0,
                    blocker.resolution_evidence,
                    blocker.resolved_by,
                    blocker.created_at,
                    blocker.resolved_at,
                ),
            )
        return blocker

    def resolve_blocker(
        self,
        blocker_id: str,
        *,
        resolved_by: str,
        resolution_evidence: str,
    ) -> CollaborationBlocker:
        now = _utc_now()
        with self._connect() as conn:
            updated = conn.execute(
                """
                update collaboration_blockers
                set active = 0, resolved_by = ?, resolution_evidence = ?, resolved_at = ?
                where blocker_id = ?
                """,
                (
                    _required(resolved_by, "resolved_by"),
                    _required(resolution_evidence, "resolution_evidence"),
                    now,
                    blocker_id,
                ),
            ).rowcount
        if updated != 1:
            raise KeyError(f"unknown collaboration blocker: {blocker_id}")
        return self.get_blocker(blocker_id)

    def get_blocker(self, blocker_id: str) -> CollaborationBlocker:
        with self._connect() as conn:
            row = conn.execute(
                "select * from collaboration_blockers where blocker_id = ?",
                (blocker_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown collaboration blocker: {blocker_id}")
        return self._blocker_from_row(row)

    def list_blockers(
        self,
        conversation_id: str,
        *,
        active_only: bool = False,
    ) -> list[CollaborationBlocker]:
        query = "select * from collaboration_blockers where conversation_id = ?"
        params: tuple[object, ...] = (conversation_id,)
        if active_only:
            query += " and active = 1"
        query += " order by rowid asc"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._blocker_from_row(row) for row in rows]

    def evaluate_dispatch_gate(
        self,
        *,
        conversation_id: str,
        run_id: str,
        proposal_ref: str | None,
        artifact_ref: str | None,
        execute_confirmed: bool,
        policy_allows_real_provider: bool,
    ) -> DispatchGateDecision:
        decision: DispatchGateDecision
        try:
            run = self.get_run(run_id)
        except KeyError:
            decision = DispatchGateDecision.BLOCKED_UNKNOWN_RUN
            self._record_dispatch_gate_event(
                conversation_id=conversation_id,
                run_id=run_id,
                decision=decision,
                proposal_ref=proposal_ref,
                artifact_ref=artifact_ref,
                execute_confirmed=execute_confirmed,
                policy_allows_real_provider=policy_allows_real_provider,
            )
            return decision
        if run.conversation_id != conversation_id:
            decision = DispatchGateDecision.BLOCKED_UNKNOWN_RUN
            self._record_dispatch_gate_event(
                conversation_id=conversation_id,
                run_id=run_id,
                decision=decision,
                proposal_ref=proposal_ref,
                artifact_ref=artifact_ref,
                execute_confirmed=execute_confirmed,
                policy_allows_real_provider=policy_allows_real_provider,
            )
            return decision
        if not proposal_ref:
            decision = DispatchGateDecision.BLOCKED_MISSING_PROPOSAL
        elif not artifact_ref:
            decision = DispatchGateDecision.BLOCKED_MISSING_ARTIFACT
        elif any(blocker.active and blocker.blocks_dispatch for blocker in run.blockers):
            decision = DispatchGateDecision.BLOCKED_ACTIVE_VETO
        elif not execute_confirmed:
            decision = DispatchGateDecision.BLOCKED_EXECUTE_NOT_CONFIRMED
        elif not policy_allows_real_provider:
            decision = DispatchGateDecision.BLOCKED_POLICY
        else:
            decision = DispatchGateDecision.ALLOWED
        self._record_dispatch_gate_event(
            conversation_id=conversation_id,
            run_id=run_id,
            decision=decision,
            proposal_ref=proposal_ref,
            artifact_ref=artifact_ref,
            execute_confirmed=execute_confirmed,
            policy_allows_real_provider=policy_allows_real_provider,
        )
        return decision

    def list_dispatch_gate_events(
        self,
        conversation_id: str,
        *,
        limit: int = 20,
    ) -> list[CollaborationDispatchGateEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_dispatch_gate_events
                where conversation_id = ?
                order by rowid desc
                limit ?
                """,
                (conversation_id, int(limit)),
            ).fetchall()
        return [self._dispatch_gate_event_from_row(row) for row in rows]

    def _record_dispatch_gate_event(
        self,
        *,
        conversation_id: str,
        run_id: str,
        decision: DispatchGateDecision,
        proposal_ref: str | None,
        artifact_ref: str | None,
        execute_confirmed: bool,
        policy_allows_real_provider: bool,
    ) -> CollaborationDispatchGateEvent:
        now = _utc_now()
        event = CollaborationDispatchGateEvent(
            event_id=_new_id("collab_gate"),
            run_id=run_id,
            conversation_id=conversation_id,
            decision=decision,
            proposal_ref=proposal_ref,
            artifact_ref=artifact_ref,
            execute_confirmed=execute_confirmed,
            policy_allows_real_provider=policy_allows_real_provider,
            created_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_dispatch_gate_events (
                    event_id, run_id, conversation_id, decision, proposal_ref,
                    artifact_ref, execute_confirmed, policy_allows_real_provider,
                    created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.conversation_id,
                    event.decision.value,
                    event.proposal_ref,
                    event.artifact_ref,
                    1 if event.execute_confirmed else 0,
                    1 if event.policy_allows_real_provider else 0,
                    event.created_at,
                ),
            )
        return event

    def _dispatch_gate_event_from_row(
        self,
        row: sqlite3.Row,
    ) -> CollaborationDispatchGateEvent:
        payload = dict(row)
        return CollaborationDispatchGateEvent(
            event_id=payload["event_id"],
            run_id=payload["run_id"],
            conversation_id=payload["conversation_id"],
            decision=DispatchGateDecision(payload["decision"]),
            proposal_ref=payload["proposal_ref"],
            artifact_ref=payload["artifact_ref"],
            execute_confirmed=bool(payload["execute_confirmed"]),
            policy_allows_real_provider=bool(payload["policy_allows_real_provider"]),
            created_at=payload["created_at"],
        )

    def is_active_target(self, conversation_id: str, target: str) -> bool:
        clean_target = target.strip()
        if not clean_target:
            return False
        with self._connect() as conn:
            rows = conn.execute(
                """
                select targets_json from collaboration_runs
                where conversation_id = ? and status in (?, ?)
                """,
                (
                    conversation_id,
                    CollaborationStatus.RUNNING.value,
                    CollaborationStatus.PARTIAL.value,
                ),
            ).fetchall()
        for row in rows:
            targets = json.loads(row["targets_json"])
            if clean_target in targets:
                return True
        return False

    def _run_from_row(self, row: sqlite3.Row) -> CollaborationRun:
        payload = dict(row)
        run_id = payload["run_id"]
        return CollaborationRun(
            run_id=run_id,
            conversation_id=payload["conversation_id"],
            goal=payload["goal"],
            orchestration_mode=payload["orchestration_mode"],
            status=CollaborationStatus(payload["status"]),
            initiator=payload["initiator"],
            targets=json.loads(payload["targets_json"]),
            callback_target=payload["callback_target"],
            question=payload["question"],
            context_refs=json.loads(payload["context_refs_json"]),
            idempotency_key=payload["idempotency_key"],
            timeout_s=int(payload["timeout_s"]),
            max_depth=int(payload["max_depth"]),
            current_depth=int(payload["current_depth"]),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            responses=self._responses_for_run(run_id),
            blockers=self._blockers_for_run(run_id),
        )

    def _responses_for_run(self, run_id: str) -> list[CollaborationResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_responses
                where run_id = ?
                order by rowid asc
                """,
                (run_id,),
            ).fetchall()
        return [self._response_from_row(row) for row in rows]

    def _blockers_for_run(self, run_id: str) -> list[CollaborationBlocker]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_blockers
                where run_id = ?
                order by rowid asc
                """,
                (run_id,),
            ).fetchall()
        return [self._blocker_from_row(row) for row in rows]

    def _response_from_row(self, row: sqlite3.Row) -> CollaborationResponse:
        payload = dict(row)
        return CollaborationResponse(
            response_id=payload["response_id"],
            run_id=payload["run_id"],
            target=payload["target"],
            content=payload["content"],
            status=payload["status"],
            created_at=payload["created_at"],
        )

    def _blocker_from_row(self, row: sqlite3.Row) -> CollaborationBlocker:
        payload = dict(row)
        return CollaborationBlocker(
            blocker_id=payload["blocker_id"],
            run_id=payload["run_id"],
            conversation_id=payload["conversation_id"],
            issuer=payload["issuer"],
            severity=payload["severity"],
            reason=payload["reason"],
            affected_ref=payload["affected_ref"],
            suggested_fix=payload["suggested_fix"],
            active=bool(payload["active"]),
            blocks_dispatch=bool(payload["blocks_dispatch"]),
            resolution_evidence=payload["resolution_evidence"],
            resolved_by=payload["resolved_by"],
            created_at=payload["created_at"],
            resolved_at=payload["resolved_at"],
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists collaboration_runs (
                    run_id text primary key,
                    conversation_id text not null,
                    goal text not null,
                    orchestration_mode text not null,
                    status text not null,
                    initiator text not null,
                    targets_json text not null,
                    callback_target text not null,
                    question text not null,
                    context_refs_json text not null,
                    idempotency_key text,
                    timeout_s integer not null,
                    max_depth integer not null,
                    current_depth integer not null,
                    created_at text not null,
                    updated_at text not null
                );

                create unique index if not exists idx_collaboration_runs_idempotency
                    on collaboration_runs(conversation_id, idempotency_key)
                    where idempotency_key is not null;

                create index if not exists idx_collaboration_runs_conversation_status
                    on collaboration_runs(conversation_id, status);

                create table if not exists collaboration_responses (
                    response_id text primary key,
                    run_id text not null references collaboration_runs(run_id),
                    target text not null,
                    content text not null,
                    status text not null,
                    created_at text not null,
                    unique(run_id, target)
                );

                create table if not exists collaboration_blockers (
                    blocker_id text primary key,
                    run_id text not null references collaboration_runs(run_id),
                    conversation_id text not null,
                    issuer text not null,
                    severity text not null,
                    reason text not null,
                    affected_ref text not null,
                    suggested_fix text not null,
                    active integer not null,
                    blocks_dispatch integer not null,
                    resolution_evidence text,
                    resolved_by text,
                    created_at text not null,
                    resolved_at text
                );

                create index if not exists idx_collaboration_blockers_conversation_active
                    on collaboration_blockers(conversation_id, active);

                create table if not exists collaboration_dispatch_gate_events (
                    event_id text primary key,
                    run_id text not null,
                    conversation_id text not null,
                    decision text not null,
                    proposal_ref text,
                    artifact_ref text,
                    execute_confirmed integer not null,
                    policy_allows_real_provider integer not null,
                    created_at text not null
                );

                create index if not exists idx_collaboration_gate_events_conversation
                    on collaboration_dispatch_gate_events(conversation_id, created_at);
                """
            )


def _required(value: str, name: str) -> str:
    clean = value.strip() if isinstance(value, str) else ""
    if not clean:
        raise ValueError(f"{name} must not be blank")
    return clean


def _clean_unique(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip() if isinstance(value, str) else ""
        if not clean or clean in seen:
            continue
        seen.add(clean)
        cleaned.append(clean)
    return cleaned
