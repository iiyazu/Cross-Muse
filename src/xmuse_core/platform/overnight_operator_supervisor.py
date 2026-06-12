from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

StageStatus = Literal["pending", "running", "ok", "manual_gap"]


@dataclass(frozen=True)
class OvernightSupervisorStage:
    stage_id: str
    objective: str


@dataclass(frozen=True)
class OvernightSupervisorConfig:
    run_id: str
    artifact_dir: Path
    stages: list[OvernightSupervisorStage]


class OvernightSupervisor:
    def __init__(self, config: OvernightSupervisorConfig) -> None:
        self._config = config
        self._stages: list[dict[str, Any]] = [
            {
                "stage_id": stage.stage_id,
                "objective": stage.objective,
                "status": "pending",
            }
            for stage in config.stages
        ]
        self._current_stage_id: str | None = None
        self._heartbeats: list[dict[str, Any]] = []
        self._checkpoints: list[dict[str, Any]] = []
        self._manual_gaps: list[dict[str, Any]] = []
        self._issue_queue: list[dict[str, Any]] = []
        self._failure_classifications: list[dict[str, Any]] = []
        self._stage_journal: list[dict[str, Any]] = []
        self._persist()

    @classmethod
    def resume(cls, config: OvernightSupervisorConfig) -> OvernightSupervisor:
        path = cls._snapshot_path(config)
        supervisor = cls.__new__(cls)
        supervisor._config = config
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        supervisor._stages = [
            dict(stage)
            for stage in snapshot.get("stages", [])
            if isinstance(stage, dict)
        ]
        if not supervisor._stages:
            supervisor._stages = [
                {
                    "stage_id": stage.stage_id,
                    "objective": stage.objective,
                    "status": "pending",
                }
                for stage in config.stages
            ]
        current_stage_id = snapshot.get("current_stage_id")
        supervisor._current_stage_id = (
            current_stage_id if isinstance(current_stage_id, str) else None
        )
        supervisor._heartbeats = _dict_rows(snapshot.get("heartbeats"))
        supervisor._checkpoints = _dict_rows(snapshot.get("checkpoints"))
        supervisor._manual_gaps = _dict_rows(snapshot.get("manual_gaps"))
        supervisor._issue_queue = _dict_rows(snapshot.get("issue_queue"))
        supervisor._failure_classifications = _dict_rows(
            snapshot.get("failure_classifications")
        )
        supervisor._stage_journal = _dict_rows(snapshot.get("stage_journal"))
        return supervisor

    def start_stage(self, stage_id: str) -> None:
        stage = self._stage(stage_id)
        stage["status"] = "running"
        stage["started_at"] = _utcnow()
        self._current_stage_id = stage_id
        self._journal("stage_started", stage_id=stage_id)
        self._persist()

    def record_heartbeat(self, *, note: str) -> dict[str, Any]:
        heartbeat = {
            "run_id": self._config.run_id,
            "stage_id": self._current_stage_id,
            "note": note,
            "timestamp_utc": _utcnow(),
        }
        self._heartbeats.append(heartbeat)
        self._journal("heartbeat", stage_id=self._current_stage_id, note=note)
        self._persist()
        return heartbeat

    def record_checkpoint(
        self,
        *,
        stage_id: str,
        summary: str,
        validation: list[str] | None = None,
    ) -> dict[str, Any]:
        checkpoint = {
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "summary": summary,
            "validation": list(validation or []),
            "timestamp_utc": _utcnow(),
        }
        self._checkpoints.append(checkpoint)
        self._journal("checkpoint", stage_id=stage_id, summary=summary)
        self._persist()
        return checkpoint

    def record_issue(
        self,
        *,
        stage_id: str,
        title: str,
        severity: str,
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        issue = {
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "title": title,
            "severity": severity,
            "source_ref": source_ref,
            "status": "open",
            "timestamp_utc": _utcnow(),
        }
        self._issue_queue.append(issue)
        self._journal("issue_recorded", stage_id=stage_id, title=title)
        self._persist()
        return issue

    def classify_failure(
        self,
        *,
        stage_id: str,
        failure_class: str,
        reason: str,
        retryable: bool,
    ) -> dict[str, Any]:
        failure = {
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "failure_class": failure_class,
            "reason": reason,
            "retryable": retryable,
            "timestamp_utc": _utcnow(),
        }
        self._failure_classifications.append(failure)
        self._journal(
            "failure_classified",
            stage_id=stage_id,
            failure_class=failure_class,
        )
        self._persist()
        return failure

    def complete_stage(self, stage_id: str, *, summary: str) -> None:
        stage = self._stage(stage_id)
        stage["status"] = "ok"
        stage["completed_at"] = _utcnow()
        stage["completed_summary"] = summary
        if self._current_stage_id == stage_id:
            self._current_stage_id = None
        self._journal("stage_completed", stage_id=stage_id, summary=summary)
        self._persist()

    def manual_gap(
        self,
        *,
        stage_id: str,
        reason: str,
        attempted_command: str | None = None,
        next_action: str | None = None,
    ) -> dict[str, Any]:
        stage = self._stage(stage_id)
        stage["status"] = "manual_gap"
        stage["manual_gap_reason"] = reason
        stage["completed_at"] = _utcnow()
        gap = {
            "schema_version": "xmuse.manual_gap.v1",
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "proof_level": "manual_gap",
            "reason": reason,
            "attempted_command": attempted_command,
            "next_action": next_action,
            "timestamp_utc": _utcnow(),
        }
        self._manual_gaps.append(gap)
        self._write_json(self._config.artifact_dir / f"manual-gap-{stage_id}.json", gap)
        self._journal("manual_gap", stage_id=stage_id, reason=reason)
        if self._current_stage_id == stage_id:
            self._current_stage_id = None
        self._persist()
        return gap

    def move_to_next_high_value_stage(self) -> str | None:
        for stage in self._stages:
            if stage.get("status") == "pending":
                self.start_stage(str(stage["stage_id"]))
                return str(stage["stage_id"])
        return None

    def live_soak_plan(
        self,
        *,
        env: dict[str, str],
        required_flags: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        plan: dict[str, dict[str, Any]] = {}
        for target, flag_name in required_flags.items():
            enabled = _truthy(env.get(flag_name))
            plan[target] = {
                "enabled": enabled,
                "proof_level": "live_service_proof" if enabled else "manual_gap",
                "manual_gap_reason": None
                if enabled
                else f"missing opt-in flag {flag_name}",
            }
        return plan

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "xmuse.overnight_supervisor.v1",
            "run_id": self._config.run_id,
            "current_stage_id": self._current_stage_id,
            "stages": [dict(stage) for stage in self._stages],
            "heartbeats": list(self._heartbeats),
            "checkpoints": list(self._checkpoints),
            "manual_gaps": list(self._manual_gaps),
            "issue_queue": list(self._issue_queue),
            "failure_classifications": list(self._failure_classifications),
            "stage_journal": list(self._stage_journal),
        }

    def _stage(self, stage_id: str) -> dict[str, Any]:
        for stage in self._stages:
            if stage.get("stage_id") == stage_id:
                return stage
        raise ValueError(f"unknown supervisor stage: {stage_id}")

    def _journal(self, event: str, **fields: Any) -> None:
        self._stage_journal.append(
            {"event": event, "timestamp_utc": _utcnow(), **fields}
        )

    def _persist(self) -> None:
        self._write_json(
            self._snapshot_path(self._config),
            self.snapshot(),
        )

    @staticmethod
    def _snapshot_path(config: OvernightSupervisorConfig) -> Path:
        return config.artifact_dir / f"overnight-supervisor-{config.run_id}.json"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
