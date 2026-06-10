from __future__ import annotations

import sqlite3
from pathlib import Path

from xmuse_core.chat.bootstrap_contracts import (
    AppliedBootstrap,
    BootstrapDraft,
    BootstrapStatus,
    TeamPlanProposal,
)
from xmuse_core.chat.store import ChatStore


class BootstrapStateStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        # Ensure the DB file and all tables exist
        ChatStore(self._path)

    def upsert_draft(self, draft: BootstrapDraft) -> BootstrapDraft:
        with self._connect() as conn:
            conn.execute(
                """
                insert into bootstrap_drafts (
                    draft_id, conversation_id, payload_json, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(draft_id) do update set
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    draft.draft_id,
                    draft.conversation_id,
                    draft.model_dump_json(),
                    str(draft.status.value if hasattr(draft.status, "value") else draft.status),
                    draft.created_at,
                    draft.updated_at,
                ),
            )
        return draft

    def upsert_proposal(self, proposal: TeamPlanProposal) -> TeamPlanProposal:
        with self._connect() as conn:
            conn.execute(
                """
                insert into bootstrap_proposals (
                    proposal_id, draft_id, conversation_id, payload_json,
                    validation_status, created_at
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(proposal_id) do update set
                    payload_json = excluded.payload_json,
                    validation_status = excluded.validation_status
                """,
                (
                    proposal.proposal_id,
                    proposal.draft_id,
                    proposal.conversation_id,
                    proposal.model_dump_json(),
                    proposal.validation_status,
                    _created_at_from_payload(proposal.model_dump(mode="json")),
                ),
            )
        return proposal

    def upsert_application(self, applied: AppliedBootstrap) -> AppliedBootstrap:
        with self._connect() as conn:
            conn.execute(
                """
                insert into bootstrap_applications (
                    apply_id, draft_id, proposal_id, conversation_id,
                    payload_json, status, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(apply_id) do nothing
                """,
                (
                    applied.apply_id,
                    applied.draft_id,
                    applied.proposal_id,
                    applied.conversation_id,
                    applied.model_dump_json(),
                    applied.status,
                    applied.created_at,
                ),
            )
        return self.get_application(applied.apply_id)

    def update_draft_status(
        self,
        draft_id: str,
        *,
        status: BootstrapStatus,
        updated_at: str,
    ) -> BootstrapDraft:
        draft = self.get_draft(draft_id).model_copy(
            update={"status": status, "updated_at": updated_at},
        )
        return self.upsert_draft(draft)

    def get_draft(self, draft_id: str) -> BootstrapDraft:
        row = self._one("select payload_json from bootstrap_drafts where draft_id = ?", draft_id)
        return BootstrapDraft.model_validate_json(row["payload_json"])

    def get_latest_draft_for_conversation(self, conversation_id: str) -> BootstrapDraft | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from bootstrap_drafts "
                "where conversation_id = ? order by updated_at desc, rowid desc limit 1",
                (conversation_id,),
            ).fetchone()
        return BootstrapDraft.model_validate_json(row["payload_json"]) if row else None

    def list_drafts_for_conversation(self, conversation_id: str) -> list[BootstrapDraft]:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload_json from bootstrap_drafts "
                "where conversation_id = ? order by rowid asc",
                (conversation_id,),
            ).fetchall()
        return [BootstrapDraft.model_validate_json(row["payload_json"]) for row in rows]

    def get_proposal(self, proposal_id: str) -> TeamPlanProposal:
        row = self._one(
            "select payload_json from bootstrap_proposals where proposal_id = ?",
            proposal_id,
        )
        return TeamPlanProposal.model_validate_json(row["payload_json"])

    def get_latest_proposal_for_conversation(
        self,
        conversation_id: str,
    ) -> TeamPlanProposal | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from bootstrap_proposals "
                "where conversation_id = ? order by created_at desc, rowid desc limit 1",
                (conversation_id,),
            ).fetchone()
        return TeamPlanProposal.model_validate_json(row["payload_json"]) if row else None

    def get_application(self, apply_id: str) -> AppliedBootstrap:
        row = self._one(
            "select payload_json from bootstrap_applications where apply_id = ?",
            apply_id,
        )
        return AppliedBootstrap.model_validate_json(row["payload_json"])

    def get_latest_application_for_conversation(
        self,
        conversation_id: str,
    ) -> AppliedBootstrap | None:
        with self._connect() as conn:
            row = conn.execute(
                "select payload_json from bootstrap_applications "
                "where conversation_id = ? order by created_at desc, rowid desc limit 1",
                (conversation_id,),
            ).fetchone()
        return AppliedBootstrap.model_validate_json(row["payload_json"]) if row else None

    def _one(self, sql: str, value: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(sql, (value,)).fetchone()
        if row is None:
            raise KeyError(value)
        return row

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn


def _created_at_from_payload(payload: dict) -> str:
    value = payload.get("created_at")
    return str(value) if value else "1970-01-01T00:00:00Z"
