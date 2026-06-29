from __future__ import annotations

import fcntl
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from xmuse_core.platform.execution.github_ops import (
    GitHubMainCiEvidence,
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


class GitHubMainCiTruthCollector(Protocol):
    def collect_main_ci(
        self,
        *,
        repo: str,
        merge_commit_sha: str,
    ) -> GitHubMainCiEvidence: ...


class GitHubGateEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    final_action_id: str
    repo: str
    pull_request_number: int
    required_checks: list[str] = Field(default_factory=list)
    evidence: GitHubServerSideTruthEvidence
    main_ci: GitHubMainCiEvidence | None = None
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
        main_ci_collector: GitHubMainCiTruthCollector | None = None,
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
        main_ci = _collect_main_ci(
            evidence=evidence,
            repo=repo,
            can_accept=can_accept,
            collector=main_ci_collector,
        )
        record = GitHubGateEvidenceRecord(
            id=_new_id("ghgate"),
            final_action_id=final_action_id,
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=list(required_checks),
            evidence=evidence,
            main_ci=main_ci,
            can_accept=can_accept,
            gap_reason=mismatch_reason or evidence.gap_reason,
            created_at=_utc_now(),
        )

        def append_record(data: dict[str, Any]) -> GitHubGateEvidenceRecord:
            data.setdefault("items", []).append(record.model_dump(mode="json"))
            return record

        return self._locked_update(append_record)

    def capture_main_ci_for_ref(
        self,
        ref: str,
        *,
        collector: GitHubMainCiTruthCollector,
        final_action_id: str | None = None,
    ) -> GitHubGateEvidenceRecord:
        prefix = f"{self._path.name}#evidence="
        if not ref.startswith(prefix):
            raise ValueError("github gate evidence ref does not match store")
        evidence_id = ref.removeprefix(prefix).strip()
        if not evidence_id:
            raise ValueError("github gate evidence ref missing id")

        def update_record(data: dict[str, Any]) -> GitHubGateEvidenceRecord:
            for item in data.get("items", []):
                if not isinstance(item, dict) or item.get("id") != evidence_id:
                    continue
                if (
                    final_action_id is not None
                    and item.get("final_action_id") != final_action_id
                ):
                    raise ValueError("github gate evidence final action mismatch")
                record = GitHubGateEvidenceRecord(**item)
                merge_commit_sha = record.evidence.merge_commit_sha
                if not merge_commit_sha:
                    raise ValueError("github gate evidence missing merge commit sha")
                item["main_ci"] = collector.collect_main_ci(
                    repo=record.repo,
                    merge_commit_sha=merge_commit_sha,
                ).model_dump(mode="json")
                return GitHubGateEvidenceRecord(**item)
            raise KeyError(f"unknown github gate evidence ref: {ref}")

        return self._locked_update(update_record)

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

    def _locked_update(
        self,
        mutator: Callable[[dict[str, Any]], GitHubGateEvidenceRecord],
    ) -> GitHubGateEvidenceRecord:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_name(f"{self._path.name}.lock")
        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                data = self._read()
                result = mutator(data)
                self._write(data)
                return result
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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


def _collect_main_ci(
    *,
    evidence: GitHubServerSideTruthEvidence,
    repo: str,
    can_accept: bool,
    collector: GitHubMainCiTruthCollector | None,
) -> GitHubMainCiEvidence | None:
    if collector is None or not can_accept or evidence.merge_commit_sha is None:
        return None
    return collector.collect_main_ci(
        repo=repo,
        merge_commit_sha=evidence.merge_commit_sha,
    )
