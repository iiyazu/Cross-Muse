from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.chat.participant_store import Participant, ParticipantStore, _new_id, _utc_now
from xmuse_core.namespaces import normalize_memory_ref


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class PeerForkRecord(BaseModel):
    fork_id: str
    conversation_id: str
    source_peer_id: str
    new_peer_id: str
    prompt_delta: str
    inherited_refs: list[str] = Field(default_factory=list)
    model_policy: dict[str, Any]
    feature_scope_id: str | None = None
    fork_reason: str
    created_at: str

    @field_validator("conversation_id", "source_peer_id", "new_peer_id")
    @classmethod
    def _require_non_blank_identity(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("peer fork identity fields must not be blank")
        return stripped

    @field_validator("prompt_delta", "fork_reason")
    @classmethod
    def _require_non_blank_text(cls, value: str, info) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} must not be blank")
        return stripped

    @field_validator("feature_scope_id")
    @classmethod
    def _clean_feature_scope_id(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("inherited_refs")
    @classmethod
    def _clean_inherited_refs(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for ref in value:
            stripped = ref.strip()
            if not stripped or stripped in seen:
                continue
            cleaned.append(stripped)
            seen.add(stripped)
        return cleaned

    @field_validator("model_policy")
    @classmethod
    def _normalize_model_policy(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(value)
        if "runtime" in normalized and "model_policy_runtime" not in normalized:
            normalized["model_policy_runtime"] = normalized.pop("runtime")
        if "enabled" in normalized and "model_policy_enabled" not in normalized:
            normalized["model_policy_enabled"] = normalized.pop("enabled")
        runtime = normalized.get("model_policy_runtime")
        if not isinstance(runtime, str) or not runtime.strip():
            raise ValueError("model_policy must declare model_policy_runtime")
        normalized["model_policy_runtime"] = runtime.strip()
        return normalized

    @model_validator(mode="after")
    def _validate_distinct_peers(self) -> PeerForkRecord:
        if self.source_peer_id == self.new_peer_id:
            raise ValueError("source_peer_id and new_peer_id must differ")
        normalized_refs: list[str] = []
        seen: set[str] = set()
        for ref in self.inherited_refs:
            normalized = normalize_memory_ref(
                ref,
                conversation_id=self.conversation_id,
                feature_scope_id=self.feature_scope_id,
            )
            if not normalized or normalized in seen:
                continue
            normalized_refs.append(normalized)
            seen.add(normalized)
        self.inherited_refs = normalized_refs
        return self


class PeerForkSummary(BaseModel):
    fork_id: str
    conversation_id: str
    source_peer_id: str
    source_role: str
    source_display_name: str
    source_god_session_id: str
    new_peer_id: str
    new_role: str
    new_display_name: str
    new_god_session_id: str
    prompt_delta: str
    inherited_ref_count: int
    model_policy_runtime: str
    feature_scope_id: str | None = None
    fork_reason: str
    created_at: str


class PeerForkStore:
    """CRUD store for the `peer_forks` table in chat.db."""

    def __init__(
        self,
        path: Path | str,
        *,
        registry_path: Path | str,
    ) -> None:
        self._path = Path(path)
        self._participants = ParticipantStore(path)
        self._registry = GodSessionRegistry(registry_path)

    def record(
        self,
        *,
        conversation_id: str,
        source_peer_id: str,
        new_peer_id: str,
        prompt_delta: str,
        inherited_refs: list[str] | None = None,
        model_policy: dict[str, Any],
        feature_scope_id: str | None = None,
        fork_reason: str,
    ) -> PeerForkRecord:
        record = self.validate_contract(
            conversation_id=conversation_id,
            source_peer_id=source_peer_id,
            new_peer_id=new_peer_id,
            prompt_delta=prompt_delta,
            inherited_refs=inherited_refs,
            model_policy=model_policy,
            feature_scope_id=feature_scope_id,
            fork_reason=fork_reason,
        )
        self._validate_participant_lineage(record)
        with self._connect() as conn:
            conn.execute(
                """
                insert into peer_forks (
                    fork_id,
                    conversation_id,
                    source_peer_id,
                    new_peer_id,
                    prompt_delta,
                    inherited_refs_json,
                    model_policy_json,
                    feature_scope_id,
                    fork_reason,
                    created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.fork_id,
                    record.conversation_id,
                    record.source_peer_id,
                    record.new_peer_id,
                    record.prompt_delta,
                    json.dumps(record.inherited_refs),
                    json.dumps(record.model_policy),
                    record.feature_scope_id,
                    record.fork_reason,
                    record.created_at,
                ),
            )
        return record

    def record_bootstrap_once(
        self,
        *,
        fork_id: str,
        conversation_id: str,
        source_peer_id: str,
        new_peer_id: str,
        prompt_delta: str,
        inherited_refs: list[str] | None,
        model_policy: dict[str, Any],
        feature_scope_id: str | None,
        fork_reason: str,
    ) -> PeerForkRecord:
        try:
            return self.get(fork_id)
        except KeyError:
            pass
        record = PeerForkRecord(
            fork_id=fork_id,
            conversation_id=conversation_id,
            source_peer_id=source_peer_id,
            new_peer_id=new_peer_id,
            prompt_delta=prompt_delta,
            inherited_refs=inherited_refs or [],
            model_policy=model_policy,
            feature_scope_id=feature_scope_id,
            fork_reason=fork_reason,
            created_at=_utc_now(),
        )
        self._validate_participant_lineage(record)
        with self._connect() as conn:
            conn.execute(
                """
                insert into peer_forks (
                    fork_id, conversation_id, source_peer_id, new_peer_id,
                    prompt_delta, inherited_refs_json, model_policy_json,
                    feature_scope_id, fork_reason, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(fork_id) do nothing
                """,
                (
                    record.fork_id,
                    record.conversation_id,
                    record.source_peer_id,
                    record.new_peer_id,
                    record.prompt_delta,
                    json.dumps(record.inherited_refs),
                    json.dumps(record.model_policy),
                    record.feature_scope_id,
                    record.fork_reason,
                    record.created_at,
                ),
            )
        return self.get(fork_id)

    def validate_contract(
        self,
        *,
        conversation_id: str,
        source_peer_id: str,
        new_peer_id: str,
        prompt_delta: str,
        inherited_refs: list[str] | None,
        model_policy: dict[str, Any],
        feature_scope_id: str | None,
        fork_reason: str,
    ) -> PeerForkRecord:
        return PeerForkRecord(
            fork_id=_new_id("fork"),
            conversation_id=conversation_id,
            source_peer_id=source_peer_id,
            new_peer_id=new_peer_id,
            prompt_delta=prompt_delta,
            inherited_refs=inherited_refs or [],
            model_policy=model_policy,
            feature_scope_id=feature_scope_id,
            fork_reason=fork_reason,
            created_at=_utc_now(),
        )

    def get(self, fork_id: str) -> PeerForkRecord:
        with self._connect() as conn:
            row = conn.execute(
                "select * from peer_forks where fork_id = ?",
                (fork_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown peer fork: {fork_id}")
        return self._from_row(row)

    def list_by_conversation(self, conversation_id: str) -> list[PeerForkRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from peer_forks
                where conversation_id = ?
                order by rowid asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_summaries_by_conversation(
        self,
        conversation_id: str,
    ) -> list[PeerForkSummary]:
        summaries: list[PeerForkSummary] = []
        for record in self.list_by_conversation(conversation_id):
            source = self._participants.get(record.source_peer_id)
            if source.role == "init":
                continue
            new = self._participants.get(record.new_peer_id)
            source_session = self._registry.find_by_conversation_participant(
                conversation_id,
                record.source_peer_id,
            )
            new_session = self._registry.find_by_conversation_participant(
                conversation_id,
                record.new_peer_id,
            )
            summaries.append(
                PeerForkSummary(
                    fork_id=record.fork_id,
                    conversation_id=record.conversation_id,
                    source_peer_id=record.source_peer_id,
                    source_role=source.role,
                    source_display_name=source.display_name,
                    source_god_session_id=source_session.god_session_id,
                    new_peer_id=record.new_peer_id,
                    new_role=new.role,
                    new_display_name=new.display_name,
                    new_god_session_id=new_session.god_session_id,
                    prompt_delta=record.prompt_delta,
                    inherited_ref_count=len(record.inherited_refs),
                    model_policy_runtime=str(
                        record.model_policy["model_policy_runtime"]
                    ),
                    feature_scope_id=record.feature_scope_id,
                    fork_reason=record.fork_reason,
                    created_at=record.created_at,
                )
            )
        return summaries

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _from_row(self, row: sqlite3.Row) -> PeerForkRecord:
        data = dict(row)
        return PeerForkRecord(
            fork_id=data["fork_id"],
            conversation_id=data["conversation_id"],
            source_peer_id=data["source_peer_id"],
            new_peer_id=data["new_peer_id"],
            prompt_delta=data["prompt_delta"],
            inherited_refs=json.loads(data["inherited_refs_json"]),
            model_policy=json.loads(data["model_policy_json"]),
            feature_scope_id=data.get("feature_scope_id"),
            fork_reason=data["fork_reason"],
            created_at=data["created_at"],
        )

    def _validate_participant_lineage(self, record: PeerForkRecord) -> None:
        source = self._participant_in_conversation(
            record.conversation_id,
            record.source_peer_id,
        )
        new = self._participant_in_conversation(
            record.conversation_id,
            record.new_peer_id,
        )
        self._session_for(record.conversation_id, source)
        self._session_for(record.conversation_id, new)

    def _participant_in_conversation(
        self,
        conversation_id: str,
        participant_id: str,
    ) -> Participant:
        try:
            participant = self._participants.get(participant_id)
        except KeyError as exc:
            raise ValueError(f"unknown participant in peer fork: {participant_id}") from exc
        if participant.conversation_id != conversation_id:
            raise ValueError(
                "peer forks require both peers to belong to the target conversation"
            )
        return participant

    def _session_for(
        self,
        conversation_id: str,
        participant: Participant,
    ) -> GodSessionRecord:
        try:
            return self._registry.find_by_conversation_participant(
                conversation_id,
                participant.participant_id,
            )
        except KeyError as exc:
            raise ValueError(
                "peer forks require both peers to be backed by persistent peer sessions"
            ) from exc
