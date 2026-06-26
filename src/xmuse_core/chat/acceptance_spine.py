from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AcceptanceSpineStatus(StrEnum):
    INTAKE = "intake"
    PROPOSED = "proposed"
    REVIEW_PENDING = "review_pending"
    REVIEW_CLEARED = "review_cleared"
    DISPATCHED = "dispatched"
    EXECUTED = "executed"
    REVIEWED = "reviewed"
    AWAITING_FINAL_ACTION = "awaiting_final_action"
    FINAL_ACTION_RECORDED = "final_action_recorded"
    GITHUB_GATE_PENDING = "github_gate_pending"
    GITHUB_GATE_VERIFIED = "github_gate_verified"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AcceptanceSpine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spine_id: str
    conversation_id: str
    intake_message_id: str
    status: AcceptanceSpineStatus
    proposal_id: str | None = None
    review_trigger_inbox_id: str | None = None
    review_or_execute_verdict_ref: str | None = None
    dispatch_item_id: str | None = None
    execution_evidence_refs: list[str] = Field(default_factory=list)
    review_verdict_ref: str | None = None
    final_action_ref: str | None = None
    github_gate_evidence_ref: str | None = None
    manual_gaps: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    created_at: str
    updated_at: str


class AcceptanceSpineStore:
    """Durable chat-owned acceptance spine records.

    The spine links existing chat/control-plane producers. It does not replace
    proposals, inbox items, dispatch queue entries, or GitHub evidence.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_for_intake(
        self,
        *,
        conversation_id: str,
        intake_message_id: str,
    ) -> AcceptanceSpine:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into acceptance_spines (
                    spine_id, conversation_id, intake_message_id, status,
                    execution_evidence_refs_json, manual_gaps_json,
                    created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(conversation_id, intake_message_id) do update set
                    updated_at = excluded.updated_at
                """,
                (
                    _new_id("goalrun"),
                    conversation_id,
                    intake_message_id,
                    AcceptanceSpineStatus.INTAKE.value,
                    "[]",
                    "[]",
                    now,
                    now,
                ),
            )
        return self.get_by_intake_message(intake_message_id)

    def get_by_intake_message(self, intake_message_id: str) -> AcceptanceSpine:
        with self._connect() as conn:
            row = conn.execute(
                "select * from acceptance_spines where intake_message_id = ?",
                (intake_message_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown acceptance spine intake: {intake_message_id}")
        return self._from_row(row)

    def list_by_conversation(self, conversation_id: str) -> list[AcceptanceSpine]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from acceptance_spines
                where conversation_id = ?
                order by rowid asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _has_intake(self, *, conversation_id: str, intake_message_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1 from acceptance_spines
                where conversation_id = ?
                  and intake_message_id = ?
                """,
                (conversation_id, intake_message_id),
            ).fetchone()
        return row is not None

    def attach_proposal_from_references(
        self,
        *,
        conversation_id: str,
        proposal_id: str,
        references: list[str],
    ) -> AcceptanceSpine | None:
        intake_message_id = _intake_message_id_from_refs(references)
        if intake_message_id is None:
            return None
        if not self._has_intake(
            conversation_id=conversation_id,
            intake_message_id=intake_message_id,
        ):
            return None
        return self.attach_proposal(
            conversation_id=conversation_id,
            intake_message_id=intake_message_id,
            proposal_id=proposal_id,
        )

    def attach_proposal(
        self,
        *,
        conversation_id: str,
        intake_message_id: str,
        proposal_id: str,
    ) -> AcceptanceSpine:
        now = _utc_now()
        with self._connect() as conn:
            updated = conn.execute(
                """
                update acceptance_spines
                set proposal_id = ?,
                    status = ?,
                    updated_at = ?
                where conversation_id = ?
                  and intake_message_id = ?
                """,
                (
                    proposal_id,
                    AcceptanceSpineStatus.PROPOSED.value,
                    now,
                    conversation_id,
                    intake_message_id,
                ),
            ).rowcount
        if updated != 1:
            raise KeyError(f"unknown acceptance spine intake: {intake_message_id}")
        return self.get_by_intake_message(intake_message_id)

    def attach_review_trigger_for_proposal(
        self,
        *,
        proposal_id: str,
        review_trigger_inbox_id: str,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "select intake_message_id from acceptance_spines where proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                update acceptance_spines
                set review_trigger_inbox_id = ?,
                    status = ?,
                    updated_at = ?
                where proposal_id = ?
                """,
                (
                    review_trigger_inbox_id,
                    AcceptanceSpineStatus.REVIEW_PENDING.value,
                    now,
                    proposal_id,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_verdict_for_proposal(
        self,
        *,
        proposal_id: str,
        verdict_ref: str,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "select intake_message_id from acceptance_spines where proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                update acceptance_spines
                set review_or_execute_verdict_ref = ?,
                    status = ?,
                    updated_at = ?
                where proposal_id = ?
                """,
                (
                    verdict_ref,
                    AcceptanceSpineStatus.REVIEW_CLEARED.value,
                    now,
                    proposal_id,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_review_blocker_for_proposal(
        self,
        *,
        proposal_id: str,
        blocker_ref: str,
        blocked_reason: str = "proposal_review_blocked",
        manual_gaps: list[str] | None = None,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                select intake_message_id, manual_gaps_json
                from acceptance_spines
                where proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            merged_gaps = _merge_json_list(row["manual_gaps_json"], manual_gaps or [])
            conn.execute(
                """
                update acceptance_spines
                set review_or_execute_verdict_ref = ?,
                    manual_gaps_json = ?,
                    blocked_reason = ?,
                    status = ?,
                    updated_at = ?
                where proposal_id = ?
                """,
                (
                    blocker_ref,
                    json.dumps(merged_gaps),
                    blocked_reason,
                    AcceptanceSpineStatus.BLOCKED.value,
                    now,
                    proposal_id,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_dispatch_for_proposal(
        self,
        *,
        proposal_id: str,
        dispatch_item_id: str,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "select intake_message_id from acceptance_spines where proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                update acceptance_spines
                set dispatch_item_id = ?,
                    status = ?,
                    updated_at = ?
                where proposal_id = ?
                """,
                (
                    dispatch_item_id,
                    AcceptanceSpineStatus.DISPATCHED.value,
                    now,
                    proposal_id,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_execution_evidence_for_dispatch(
        self,
        *,
        dispatch_item_id: str,
        evidence_refs: list[str],
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        clean_refs = [ref for ref in evidence_refs if isinstance(ref, str) and ref.strip()]
        with self._connect() as conn:
            row = conn.execute(
                """
                select intake_message_id, execution_evidence_refs_json
                from acceptance_spines
                where dispatch_item_id = ?
                """,
                (dispatch_item_id,),
            ).fetchone()
            if row is None:
                return None
            existing = _json_list(row["execution_evidence_refs_json"])
            merged = [*existing]
            for ref in clean_refs:
                if ref not in merged:
                    merged.append(ref)
            conn.execute(
                """
                update acceptance_spines
                set execution_evidence_refs_json = ?,
                    updated_at = ?
                where dispatch_item_id = ?
                """,
                (json.dumps(merged), now, dispatch_item_id),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_lane_execution_for_resolution(
        self,
        *,
        resolution_id: str,
        evidence_refs: list[str],
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        resolution_ref = f"resolution:{resolution_id}"
        clean_refs = [ref for ref in evidence_refs if isinstance(ref, str) and ref.strip()]
        with self._connect() as conn:
            row = conn.execute(
                """
                select intake_message_id, status, execution_evidence_refs_json
                from acceptance_spines
                where review_or_execute_verdict_ref = ?
                """,
                (resolution_ref,),
            ).fetchone()
            if row is None:
                return None
            existing = _json_list(row["execution_evidence_refs_json"])
            merged = [*existing]
            for ref in clean_refs:
                if ref not in merged:
                    merged.append(ref)
            status = str(row["status"])
            next_status = (
                AcceptanceSpineStatus.EXECUTED.value
                if status
                in {
                    AcceptanceSpineStatus.REVIEW_CLEARED.value,
                    AcceptanceSpineStatus.DISPATCHED.value,
                }
                else status
            )
            conn.execute(
                """
                update acceptance_spines
                set execution_evidence_refs_json = ?,
                    status = ?,
                    updated_at = ?
                where review_or_execute_verdict_ref = ?
                """,
                (json.dumps(merged), next_status, now, resolution_ref),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_review_verdict_for_resolution(
        self,
        *,
        resolution_id: str,
        review_verdict_ref: str,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        resolution_ref = f"resolution:{resolution_id}"
        with self._connect() as conn:
            row = conn.execute(
                """
                select intake_message_id from acceptance_spines
                where review_or_execute_verdict_ref = ?
                """,
                (resolution_ref,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                update acceptance_spines
                set review_verdict_ref = ?,
                    status = ?,
                    updated_at = ?
                where review_or_execute_verdict_ref = ?
                """,
                (
                    review_verdict_ref,
                    AcceptanceSpineStatus.REVIEWED.value,
                    now,
                    resolution_ref,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def attach_final_action_for_review_verdict(
        self,
        *,
        review_verdict_ref: str,
        final_action_ref: str,
        manual_gaps: list[str] | None = None,
        blocked_reason: str | None = None,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                select intake_message_id, manual_gaps_json
                from acceptance_spines
                where review_verdict_ref = ?
                """,
                (review_verdict_ref,),
            ).fetchone()
            if row is None:
                return None
            merged_gaps = _merge_json_list(row["manual_gaps_json"], manual_gaps or [])
            status = (
                AcceptanceSpineStatus.BLOCKED
                if blocked_reason
                else AcceptanceSpineStatus.AWAITING_FINAL_ACTION
            )
            conn.execute(
                """
                update acceptance_spines
                set final_action_ref = ?,
                    manual_gaps_json = ?,
                    blocked_reason = coalesce(?, blocked_reason),
                    status = ?,
                    updated_at = ?
                where review_verdict_ref = ?
                """,
                (
                    final_action_ref,
                    json.dumps(merged_gaps),
                    blocked_reason,
                    status.value,
                    now,
                    review_verdict_ref,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def resolve_final_action(
        self,
        *,
        final_action_ref: str,
        status: str,
        github_gate_evidence_ref: str | None = None,
        github_gate_evidence_store_path: Path | str | None = None,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        normalized_status = status.strip().lower()
        clean_github_ref = (
            github_gate_evidence_ref.strip()
            if isinstance(github_gate_evidence_ref, str)
            else ""
        )
        with self._connect() as conn:
            row = conn.execute(
                """
                select intake_message_id, manual_gaps_json
                from acceptance_spines
                where final_action_ref = ?
                """,
                (final_action_ref,),
            ).fetchone()
            if row is None:
                return None
            manual_gaps = _json_list(row["manual_gaps_json"])
            blocked_reason: str | None = None
            github_ref: str | None = None
            if normalized_status in {"approved", "accepted", "resolved"}:
                final_action_id = _final_action_id_from_ref(final_action_ref)
                evidence_store_path = (
                    Path(github_gate_evidence_store_path)
                    if github_gate_evidence_store_path is not None
                    else self._path.parent / "github_gate_evidence.json"
                )
                if clean_github_ref and _is_accepted_github_gate_ref(
                    clean_github_ref,
                    evidence_store_path=evidence_store_path,
                    final_action_id=final_action_id,
                ):
                    next_status = AcceptanceSpineStatus.ACCEPTED
                    manual_gaps = _remove_values(manual_gaps, {"github_gate_unverified"})
                    github_ref = clean_github_ref
                else:
                    next_status = AcceptanceSpineStatus.BLOCKED
                    manual_gaps = _merge_values(manual_gaps, ["github_gate_unverified"])
                    blocked_reason = "github_gate_unverified"
            elif normalized_status in {"rejected", "failed", "cancelled", "canceled"}:
                next_status = AcceptanceSpineStatus.FAILED
                blocked_reason = f"final_action_{normalized_status}"
            else:
                next_status = AcceptanceSpineStatus.BLOCKED
                blocked_reason = f"final_action_{normalized_status or 'unknown'}"
            conn.execute(
                """
                update acceptance_spines
                set status = ?,
                    github_gate_evidence_ref = ?,
                    manual_gaps_json = ?,
                    blocked_reason = ?,
                    updated_at = ?
                where final_action_ref = ?
                """,
                (
                    next_status.value,
                    github_ref,
                    json.dumps(manual_gaps),
                    blocked_reason,
                    now,
                    final_action_ref,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def mark_dispatch_failed(
        self,
        *,
        dispatch_item_id: str,
        blocked_reason: str,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "select intake_message_id from acceptance_spines where dispatch_item_id = ?",
                (dispatch_item_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                update acceptance_spines
                set status = ?,
                    blocked_reason = ?,
                    updated_at = ?
                where dispatch_item_id = ?
                """,
                (
                    AcceptanceSpineStatus.FAILED.value,
                    blocked_reason,
                    now,
                    dispatch_item_id,
                ),
            )
        return self.get_by_intake_message(str(row["intake_message_id"]))

    def mark_intake_failed(
        self,
        *,
        intake_message_id: str,
        blocked_reason: str,
        evidence_ref: str | None = None,
    ) -> AcceptanceSpine | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                select execution_evidence_refs_json
                from acceptance_spines
                where intake_message_id = ?
                """,
                (intake_message_id,),
            ).fetchone()
            if row is None:
                return None
            evidence_refs = _json_list(row["execution_evidence_refs_json"])
            if evidence_ref and evidence_ref not in evidence_refs:
                evidence_refs.append(evidence_ref)
            conn.execute(
                """
                update acceptance_spines
                set status = ?,
                    execution_evidence_refs_json = ?,
                    blocked_reason = ?,
                    updated_at = ?
                where intake_message_id = ?
                """,
                (
                    AcceptanceSpineStatus.FAILED.value,
                    json.dumps(evidence_refs),
                    blocked_reason,
                    now,
                    intake_message_id,
                ),
            )
        return self.get_by_intake_message(intake_message_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            create_acceptance_spine_schema(conn)

    def _from_row(self, row: sqlite3.Row) -> AcceptanceSpine:
        payload = dict(row)
        return AcceptanceSpine(
            spine_id=payload["spine_id"],
            conversation_id=payload["conversation_id"],
            intake_message_id=payload["intake_message_id"],
            status=AcceptanceSpineStatus(payload["status"]),
            proposal_id=payload["proposal_id"],
            review_trigger_inbox_id=payload["review_trigger_inbox_id"],
            review_or_execute_verdict_ref=payload["review_or_execute_verdict_ref"],
            dispatch_item_id=payload["dispatch_item_id"],
            execution_evidence_refs=_json_list(payload["execution_evidence_refs_json"]),
            review_verdict_ref=payload["review_verdict_ref"],
            final_action_ref=payload["final_action_ref"],
            github_gate_evidence_ref=payload["github_gate_evidence_ref"],
            manual_gaps=_json_list(payload["manual_gaps_json"]),
            blocked_reason=payload["blocked_reason"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )


def create_acceptance_spine_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists acceptance_spines (
            spine_id text primary key,
            conversation_id text not null references conversations(id),
            intake_message_id text not null references messages(id),
            status text not null,
            proposal_id text,
            review_trigger_inbox_id text,
            review_or_execute_verdict_ref text,
            dispatch_item_id text,
            execution_evidence_refs_json text not null default '[]',
            review_verdict_ref text,
            final_action_ref text,
            github_gate_evidence_ref text,
            manual_gaps_json text not null default '[]',
            blocked_reason text,
            created_at text not null,
            updated_at text not null,
            unique(conversation_id, intake_message_id)
        );

        create index if not exists idx_acceptance_spines_conversation_status
            on acceptance_spines(conversation_id, status);
        create index if not exists idx_acceptance_spines_proposal
            on acceptance_spines(proposal_id);
        create index if not exists idx_acceptance_spines_dispatch
            on acceptance_spines(dispatch_item_id);
        """
    )


def _final_action_id_from_ref(final_action_ref: str) -> str | None:
    _, separator, final_action_id = final_action_ref.partition("#hold=")
    if not separator:
        return None
    clean_final_action_id = final_action_id.strip()
    return clean_final_action_id or None


def _is_accepted_github_gate_ref(
    ref: str,
    *,
    evidence_store_path: Path,
    final_action_id: str | None,
) -> bool:
    if final_action_id is None:
        return False
    prefix = f"{evidence_store_path.name}#evidence="
    if not ref.startswith(prefix):
        return False
    evidence_id = ref.removeprefix(prefix).strip()
    if not evidence_id or not evidence_store_path.exists():
        return False
    try:
        payload = json.loads(evidence_store_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    for item in payload.get("items", []):
        if not isinstance(item, dict) or item.get("id") != evidence_id:
            continue
        if item.get("final_action_id") != final_action_id:
            return False
        evidence = item.get("evidence")
        return (
            item.get("can_accept") is True
            and isinstance(evidence, dict)
            and evidence.get("proof_level") == "server_side_merge_proof"
        )
    return False


def insert_acceptance_spine_for_intake(
    conn: sqlite3.Connection,
    *,
    spine_id: str,
    conversation_id: str,
    intake_message_id: str,
    now: str,
) -> None:
    conn.execute(
        """
        insert into acceptance_spines (
            spine_id, conversation_id, intake_message_id, status,
            execution_evidence_refs_json, manual_gaps_json,
            created_at, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(conversation_id, intake_message_id) do update set
            updated_at = excluded.updated_at
        """,
        (
            spine_id,
            conversation_id,
            intake_message_id,
            AcceptanceSpineStatus.INTAKE.value,
            "[]",
            "[]",
            now,
            now,
        ),
    )


def _intake_message_id_from_refs(references: list[str]) -> str | None:
    prefixes = ("intake_message:", "message:", "source_message:")
    for ref in references:
        clean = ref.strip() if isinstance(ref, str) else ""
        for prefix in prefixes:
            if clean.startswith(prefix):
                value = clean.removeprefix(prefix).strip()
                if value:
                    return value
    return None


def _json_list(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _merge_json_list(existing_json: object, new_values: list[str]) -> list[str]:
    return _merge_values(_json_list(existing_json), new_values)


def _merge_values(existing: list[str], new_values: list[str]) -> list[str]:
    merged = [*existing]
    for value in new_values:
        clean = value.strip() if isinstance(value, str) else ""
        if clean and clean not in merged:
            merged.append(clean)
    return merged


def _remove_values(existing: list[str], values: set[str]) -> list[str]:
    return [value for value in existing if value not in values]
