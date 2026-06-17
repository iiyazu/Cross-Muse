from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from xmuse_core.chat.participant_store import INIT_GOD_ROLE

_UNSET = object()


@dataclass
class GodSessionRecord:
    god_session_id: str
    role: str
    agent_name: str
    runtime: str
    session_address: str
    session_inbox_id: str
    conversation_id: str | None = None
    participant_id: str | None = None
    status: str = "starting"
    assignment_feature_id: str | None = None
    pid: int | None = None
    model: str | None = None
    prompt_fingerprint: str | None = None
    worktree: str | None = None
    feature_scope_id: str | None = None
    provider_session_id: str | None = None
    provider_session_kind: str | None = None
    provider_binding_status: str | None = None
    provider_binding_failure_reason: str | None = None


class GodSessionRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    def create(
        self,
        role: str,
        agent_name: str,
        runtime: str,
        session_address: str,
        session_inbox_id: str,
        conversation_id: str | None = None,
        participant_id: str | None = None,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        worktree: str | None = None,
        feature_scope_id: str | None = None,
    ) -> GodSessionRecord:
        with self._locked_file():
            sessions = self.list()
            for existing in sessions:
                if existing.session_address == session_address:
                    raise ValueError(f"duplicate session_address: {session_address}")
                if existing.session_inbox_id == session_inbox_id:
                    raise ValueError(f"duplicate session_inbox_id: {session_inbox_id}")
                if (
                    role == INIT_GOD_ROLE
                    and conversation_id is not None
                    and existing.conversation_id == conversation_id
                    and existing.role == INIT_GOD_ROLE
                ):
                    raise ValueError(
                        f"duplicate init god session for conversation_id: {conversation_id}"
                    )

            record = GodSessionRecord(
                god_session_id=f"god-{uuid4().hex}",
                role=role,
                agent_name=agent_name,
                runtime=runtime,
                session_address=session_address,
                session_inbox_id=session_inbox_id,
                conversation_id=conversation_id,
                participant_id=participant_id,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            )
            sessions.append(record)
            self._write(sessions)
            return record

    def list(self) -> list[GodSessionRecord]:
        payload = self._read()
        return [GodSessionRecord(**entry) for entry in payload["sessions"]]

    def get(self, god_session_id: str) -> GodSessionRecord:
        for record in self.list():
            if record.god_session_id == god_session_id:
                return record
        raise KeyError(god_session_id)

    def find_by_address(self, session_address: str) -> GodSessionRecord:
        for record in self.list():
            if record.session_address == session_address:
                return record
        raise KeyError(session_address)

    def find_by_inbox(self, session_inbox_id: str) -> GodSessionRecord:
        for record in self.list():
            if record.session_inbox_id == session_inbox_id:
                return record
        raise KeyError(session_inbox_id)

    def find_by_conversation_participant(
        self,
        conversation_id: str,
        participant_id: str,
        feature_scope_id: str | None | object = _UNSET,
    ) -> GodSessionRecord:
        for record in self.list():
            if record.conversation_id != conversation_id:
                continue
            if record.participant_id != participant_id:
                continue
            if feature_scope_id is not _UNSET and record.feature_scope_id != feature_scope_id:
                continue
            return record
        suffix = "" if feature_scope_id is _UNSET else f":{feature_scope_id}"
        raise KeyError(f"{conversation_id}:{participant_id}{suffix}")

    def find_by_conversation_role(
        self,
        conversation_id: str,
        role: str,
    ) -> GodSessionRecord:
        matches = [
            record
            for record in self.list()
            if record.conversation_id == conversation_id and record.role == role
        ]
        if not matches:
            raise KeyError(f"{conversation_id}:{role}")
        if len(matches) > 1:
            raise ValueError(f"duplicate conversation role sessions: {conversation_id}:{role}")
        return matches[0]

    def assign(self, god_session_id: str, feature_id: str | None) -> GodSessionRecord:
        with self._locked_file():
            sessions = self.list()
            for index, record in enumerate(sessions):
                if record.god_session_id == god_session_id:
                    updated = replace(record, assignment_feature_id=feature_id)
                    sessions[index] = updated
                    self._write(sessions)
                    return updated
            raise KeyError(god_session_id)

    def update_peer_metadata(
        self,
        god_session_id: str,
        *,
        model: str | None,
        prompt_fingerprint: str | None,
        worktree: str | None,
        feature_scope_id: str | None,
    ) -> GodSessionRecord:
        with self._locked_file():
            sessions = self.list()
            for index, record in enumerate(sessions):
                if record.god_session_id == god_session_id:
                    updated = replace(
                        record,
                        model=model,
                        prompt_fingerprint=prompt_fingerprint,
                        worktree=worktree,
                        feature_scope_id=feature_scope_id,
                    )
                    sessions[index] = updated
                    self._write(sessions)
                    return updated
            raise KeyError(god_session_id)

    def update_provider_binding(
        self,
        god_session_id: str,
        *,
        provider_session_id: str | None,
        provider_session_kind: str | None,
        provider_binding_status: str | None,
        provider_binding_failure_reason: str | None,
    ) -> GodSessionRecord:
        with self._locked_file():
            sessions = self.list()
            for index, record in enumerate(sessions):
                if record.god_session_id == god_session_id:
                    updated = replace(
                        record,
                        provider_session_id=provider_session_id,
                        provider_session_kind=provider_session_kind,
                        provider_binding_status=provider_binding_status,
                        provider_binding_failure_reason=provider_binding_failure_reason,
                    )
                    sessions[index] = updated
                    self._write(sessions)
                    return updated
            raise KeyError(god_session_id)

    def _read(self) -> dict[str, list[dict[str, object]]]:
        if not self.path.exists():
            return {"sessions": []}
        return json.loads(self.path.read_text())

    def _write(self, sessions: list[GodSessionRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sessions": [asdict(session) for session in sessions]}
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    @contextmanager
    def _locked_file(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
