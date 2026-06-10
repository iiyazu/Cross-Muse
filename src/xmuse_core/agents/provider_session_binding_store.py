from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from xmuse_core.structuring.feature_review_contracts import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)

SCHEMA_VERSION = "xmuse.provider_session_bindings.v1"


@dataclass(frozen=True)
class ProviderSessionBindingCompatibility:
    compatible: bool
    binding: ProviderSessionBindingRecord | None = None
    reason: str | None = None


class ProviderSessionBindingStore:
    """Durable provider-native session binding store.

    This store intentionally lives outside ``GodSessionRegistry``.  GOD session
    records identify xmuse business sessions; provider session bindings identify
    resumable Codex/Claude/OpenCode-native session state.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    def upsert_active(
        self,
        binding: ProviderSessionBindingRecord,
    ) -> ProviderSessionBindingRecord:
        validated = ProviderSessionBindingRecord.model_validate(
            binding.model_dump(mode="json")
        )
        if validated.status is not ProviderSessionBindingStatus.ACTIVE:
            validated = validated.model_copy(
                update={"status": ProviderSessionBindingStatus.ACTIVE}
            )
        with self._locked_file():
            records = self.list()
            updated: list[ProviderSessionBindingRecord] = []
            replaced = False
            for existing in records:
                if existing.binding_id == validated.binding_id:
                    if existing != validated:
                        raise ValueError(
                            "provider session binding replay conflict: "
                            f"{validated.binding_id}"
                        )
                    updated.append(existing)
                    replaced = True
                    continue
                if _same_binding_slot(existing, validated) and (
                    existing.status is ProviderSessionBindingStatus.ACTIVE
                ):
                    updated.append(
                        existing.model_copy(
                            update={"status": ProviderSessionBindingStatus.RETIRED}
                        )
                    )
                    continue
                updated.append(existing)
            if not replaced:
                updated.append(validated)
            self._write(updated)
        return validated

    def list(self) -> list[ProviderSessionBindingRecord]:
        payload = self._read()
        bindings = payload.get("bindings", [])
        if not isinstance(bindings, list):
            raise ValueError("provider session bindings must be a list")
        for binding in bindings:
            if not isinstance(binding, dict):
                raise ValueError("provider session binding must be an object")
        return [
            ProviderSessionBindingRecord.model_validate(row)
            for row in bindings
        ]

    def list_for_god_session(self, god_session_id: str) -> list[ProviderSessionBindingRecord]:
        return [
            binding
            for binding in self.list()
            if binding.god_session_id == god_session_id
        ]

    def get(self, binding_id: str) -> ProviderSessionBindingRecord:
        for binding in self.list():
            if binding.binding_id == binding_id:
                return binding
        raise KeyError(f"provider session binding not found: {binding_id}")

    def find_active(
        self,
        *,
        god_session_id: str,
        provider: str,
        kind: str,
    ) -> ProviderSessionBindingRecord:
        matches = [
            binding
            for binding in self.list_for_god_session(god_session_id)
            if binding.provider == provider
            and binding.session_kind == kind
            and binding.status is ProviderSessionBindingStatus.ACTIVE
        ]
        if not matches:
            raise KeyError("active provider session binding not found")
        return matches[-1]

    def find_resume_compatible(
        self,
        *,
        god_session_id: str,
        provider: str,
        kind: str,
        model: str | None,
        worktree: str | None,
        prompt_fingerprint: str | None,
        feature_graph_id: str | None,
    ) -> ProviderSessionBindingCompatibility:
        try:
            binding = self.find_active(
                god_session_id=god_session_id,
                provider=provider,
                kind=kind,
            )
        except KeyError:
            return ProviderSessionBindingCompatibility(
                compatible=False,
                reason="active_binding_not_found",
            )

        checks = (
            ("model_mismatch", binding.model, model),
            ("worktree_mismatch", binding.worktree, worktree),
            (
                "prompt_fingerprint_mismatch",
                binding.prompt_fingerprint,
                prompt_fingerprint,
            ),
            ("feature_graph_id_mismatch", binding.feature_graph_id, feature_graph_id),
        )
        for reason, expected, actual in checks:
            if expected is not None and actual is not None and expected != actual:
                return ProviderSessionBindingCompatibility(
                    compatible=False,
                    reason=reason,
                )
        return ProviderSessionBindingCompatibility(compatible=True, binding=binding)

    def mark_failed(
        self,
        binding_id: str,
        *,
        status: ProviderSessionBindingStatus,
        reason: str,
        failed_at: str | None = None,
    ) -> ProviderSessionBindingRecord:
        if status not in {
            ProviderSessionBindingStatus.FAILED,
            ProviderSessionBindingStatus.STALE,
        }:
            raise ValueError("mark_failed only supports failed or stale status")
        with self._locked_file():
            records = self.list()
            updated: list[ProviderSessionBindingRecord] = []
            target: ProviderSessionBindingRecord | None = None
            for binding in records:
                if binding.binding_id != binding_id:
                    updated.append(binding)
                    continue
                target = binding.model_copy(
                    update={
                        "status": status,
                        "failure_reason": reason,
                        "last_verified_at": failed_at or binding.last_verified_at,
                    }
                )
                target = ProviderSessionBindingRecord.model_validate(
                    target.model_dump(mode="json")
                )
                updated.append(target)
            if target is None:
                raise KeyError(f"provider session binding not found: {binding_id}")
            self._write(updated)
            return target

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "bindings": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("provider session binding payload must be an object")
        return payload

    def _write(self, bindings: list[ProviderSessionBindingRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "bindings": [
                binding.model_dump(mode="json")
                for binding in bindings
            ],
        }
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
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


def _same_binding_slot(
    left: ProviderSessionBindingRecord,
    right: ProviderSessionBindingRecord,
) -> bool:
    return (
        left.god_session_id == right.god_session_id
        and left.provider == right.provider
        and left.session_kind == right.session_kind
    )
