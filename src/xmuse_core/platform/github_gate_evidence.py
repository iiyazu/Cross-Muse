from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.platform.execution.github_ops import (
    GitHubServerSideTruthEvidence,
    can_emit_pr_merged,
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class GitHubGateTruthCollector(Protocol):
    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence: ...


class GitHubGateEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    final_action_id: str
    repo: str
    pull_request_number: int
    required_checks: list[str] = Field(default_factory=list)
    evidence: GitHubServerSideTruthEvidence
    can_accept: bool
    gap_reason: str | None = None
    created_at: str


class GitHubGateEvidenceStore:
    """Durable producer for AcceptanceSpine GitHub gate evidence refs.

    The store captures read-only GitHub/server truth evidence and only exposes
    an acceptance ref when the captured evidence proves a server-side merge.
    Manual gaps are still persisted, but they are not accepted evidence refs.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def capture_for_final_action(
        self,
        *,
        final_action_id: str,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
        collector: GitHubGateTruthCollector,
    ) -> GitHubGateEvidenceRecord:
        evidence = collector.collect(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
        )
        mismatch_reason = _request_mismatch_reason(
            evidence=evidence,
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
        )
        can_accept = mismatch_reason is None and can_emit_pr_merged(evidence)
        record = GitHubGateEvidenceRecord(
            id=_new_id("ghgate"),
            final_action_id=final_action_id,
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=list(required_checks),
            evidence=evidence,
            can_accept=can_accept,
            gap_reason=mismatch_reason or evidence.gap_reason,
            created_at=_utc_now(),
        )
        data = self._read()
        data.setdefault("items", []).append(record.model_dump(mode="json"))
        self._write(data)
        return record

    def ref_for(self, record: GitHubGateEvidenceRecord) -> str:
        return f"{self._path.name}#evidence={record.id}"

    def is_accepted_ref(
        self,
        ref: str,
        *,
        final_action_id: str | None = None,
    ) -> bool:
        prefix = f"{self._path.name}#evidence="
        if not ref.startswith(prefix):
            return False
        evidence_id = ref.removeprefix(prefix).strip()
        if not evidence_id:
            return False
        for item in self._read().get("items", []):
            if not isinstance(item, dict) or item.get("id") != evidence_id:
                continue
            if final_action_id is not None and item.get("final_action_id") != final_action_id:
                return False
            return item.get("can_accept") is True
        return False

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": "github_gate_evidence.v1", "items": []}
        return json.loads(self._path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data["schema_version"] = "github_gate_evidence.v1"
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _request_mismatch_reason(
    *,
    evidence: GitHubServerSideTruthEvidence,
    repo: str,
    pull_request_number: int,
    required_checks: list[str],
) -> str | None:
    if evidence.repo != repo:
        return "github evidence repo mismatch"
    if evidence.pull_request_number != pull_request_number:
        return "github evidence pull request mismatch"
    if evidence.required_checks != required_checks:
        return "github evidence required checks mismatch"
    return None
