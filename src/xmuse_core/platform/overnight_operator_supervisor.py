from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel

StageStatus = Literal["pending", "running", "ok", "manual_gap", "blocked"]
SelfReviewDecision = Literal[
    "continue",
    "retry",
    "manual_gap",
    "blocked",
    "patch_forward",
]


@dataclass(frozen=True)
class OvernightSupervisorStage:
    stage_id: str
    objective: str
    priority: int = 0
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class OvernightSupervisorConfig:
    run_id: str
    artifact_dir: Path
    stages: list[OvernightSupervisorStage]


@dataclass(frozen=True)
class OvernightSimulationFailure:
    minute: int
    stage_id: str
    reason: str
    failure_class: str
    retryable: bool = False
    attempted_command: str | None = None
    configured: bool = True
    required: bool = True
    source_refs: tuple[str, ...] = ()
    target_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class OvernightSimulationConfig:
    total_minutes: int
    heartbeat_interval_minutes: int = 15
    self_review_interval_minutes: int = 60
    checkpoint_interval_minutes: int = 120
    max_heartbeat_gap_minutes: int = 15
    max_self_review_gap_minutes: int = 60
    failures: list[OvernightSimulationFailure] | None = None


class OvernightSupervisor:
    def __init__(self, config: OvernightSupervisorConfig) -> None:
        self._config = config
        self._stages: list[dict[str, Any]] = [
            {
                "stage_id": stage.stage_id,
                "objective": stage.objective,
                "priority": stage.priority,
                "depends_on": list(stage.depends_on),
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
        self._self_reviews: list[dict[str, Any]] = []
        self._production_evidence: list[dict[str, Any]] = []
        self._goal_stage_results: list[dict[str, Any]] = []
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
                    "priority": stage.priority,
                    "depends_on": list(stage.depends_on),
                    "status": "pending",
                }
                for stage in config.stages
            ]
        else:
            for stage in supervisor._stages:
                stage.setdefault("priority", 0)
                stage.setdefault("depends_on", [])
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
        supervisor._self_reviews = _dict_rows(snapshot.get("self_reviews"))
        supervisor._production_evidence = _dict_rows(snapshot.get("production_evidence"))
        supervisor._goal_stage_results = _dict_rows(snapshot.get("goal_stage_results"))
        return supervisor

    def start_stage(self, stage_id: str) -> None:
        stage = self._stage(stage_id)
        stage["status"] = "running"
        stage["started_at"] = _utcnow()
        self._current_stage_id = stage_id
        self._journal("stage_started", stage_id=stage_id)
        self._persist()

    def record_heartbeat(
        self,
        *,
        note: str,
        logical_minute: int | None = None,
    ) -> dict[str, Any]:
        heartbeat: dict[str, Any] = {
            "run_id": self._config.run_id,
            "stage_id": self._current_stage_id,
            "note": note,
            "timestamp_utc": _utcnow(),
        }
        if logical_minute is not None:
            heartbeat["logical_minute"] = logical_minute
        self._heartbeats.append(heartbeat)
        self._journal(
            "heartbeat",
            stage_id=self._current_stage_id,
            note=note,
            logical_minute=logical_minute,
        )
        self._persist()
        return heartbeat

    def record_checkpoint(
        self,
        *,
        stage_id: str,
        summary: str,
        validation: list[str] | None = None,
        commands: list[str] | None = None,
        source_refs: list[str] | None = None,
        target_refs: list[str] | None = None,
        artifacts: list[str] | None = None,
        proof_level: ProofLevel = "contract_proof",
        owner: str = "codex",
        next_action: str | None = None,
        logical_minute: int | None = None,
    ) -> dict[str, Any]:
        checkpoint: dict[str, Any] = {
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "summary": summary,
            "validation": list(validation or []),
            "timestamp_utc": _utcnow(),
        }
        if logical_minute is not None:
            checkpoint["logical_minute"] = logical_minute
        self._checkpoints.append(checkpoint)
        self._journal(
            "checkpoint",
            stage_id=stage_id,
            summary=summary,
            logical_minute=logical_minute,
        )
        self._record_production_evidence(
            stage_id=stage_id,
            action="checkpoint",
            status="ok",
            proof_level=proof_level,
            source_refs=source_refs,
            target_refs=target_refs,
            commands=commands,
            test_results=validation,
            artifacts=artifacts,
            blocked_reason=None,
            owner=owner,
            next_action=next_action,
            summary=summary,
            gate_id=f"goal-stage-{stage_id}-checkpoint",
            kind="local_validation",
            configured=True,
            required=False,
        )
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

    def record_self_review(
        self,
        *,
        stage_id: str,
        summary: str,
        decision: SelfReviewDecision,
        findings: list[str] | None = None,
        minutes_since_previous_review: int | None = None,
        commands: list[str] | None = None,
        test_results: list[str] | None = None,
        source_refs: list[str] | None = None,
        target_refs: list[str] | None = None,
        artifacts: list[str] | None = None,
        proof_level: ProofLevel = "contract_proof",
        owner: str = "codex",
        next_action: str | None = None,
        logical_minute: int | None = None,
    ) -> dict[str, Any]:
        self._stage(stage_id)
        if decision not in _SELF_REVIEW_DECISIONS:
            raise ValueError(f"unsupported self-review decision: {decision}")
        review = {
            "schema_version": "xmuse.overnight_self_review.v1",
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "summary": summary,
            "findings": list(findings or []),
            "decision": decision,
            "minutes_since_previous_review": minutes_since_previous_review,
            "slo_status": _review_slo_status(minutes_since_previous_review),
            "timestamp_utc": _utcnow(),
        }
        if logical_minute is not None:
            review["logical_minute"] = logical_minute
        self._self_reviews.append(review)
        self._journal(
            "self_review_recorded",
            stage_id=stage_id,
            decision=decision,
            slo_status=str(review["slo_status"]),
            logical_minute=logical_minute,
        )
        self._record_production_evidence(
            stage_id=stage_id,
            action="self_review",
            status="ok",
            proof_level=proof_level,
            source_refs=source_refs,
            target_refs=target_refs,
            commands=commands,
            test_results=test_results,
            artifacts=artifacts,
            blocked_reason=None,
            owner=owner,
            next_action=next_action,
            summary=summary,
            gate_id=f"goal-stage-{stage_id}-self-review",
            kind="self_review",
            configured=True,
            required=True,
        )
        self._persist()
        return review

    def fallback_blocked_stage(
        self,
        *,
        stage_id: str,
        reason: str,
        failure_class: str,
        retryable: bool,
        attempted_command: str | None = None,
        next_action: str | None = None,
        owner: str = "codex",
        configured: bool = True,
        required: bool = True,
        source_refs: list[str] | None = None,
        target_refs: list[str] | None = None,
        artifacts: list[str] | None = None,
        start_next: bool = True,
        logical_minute: int | None = None,
    ) -> dict[str, Any]:
        stage = self._stage(stage_id)
        status: StageStatus = "blocked" if configured else "manual_gap"
        now = _utcnow()
        stage["status"] = status
        if status == "blocked":
            stage["blocked_reason"] = reason
        else:
            stage["manual_gap_reason"] = reason
        stage["completed_at"] = now
        if logical_minute is not None:
            stage["completed_logical_minute"] = logical_minute
        if self._current_stage_id == stage_id:
            self._current_stage_id = None

        source_ref = source_refs[0] if source_refs else None
        self._issue_queue.append(
            {
                "run_id": self._config.run_id,
                "stage_id": stage_id,
                "title": reason,
                "severity": status,
                "source_ref": source_ref,
                "status": "open",
                "timestamp_utc": now,
                "logical_minute": logical_minute,
            }
        )
        self._failure_classifications.append(
            {
                "run_id": self._config.run_id,
                "stage_id": stage_id,
                "failure_class": failure_class,
                "reason": reason,
                "retryable": retryable,
                "timestamp_utc": now,
                "logical_minute": logical_minute,
            }
        )

        fallback_path = self._config.artifact_dir / f"blocked-fallback-{stage_id}.json"
        evidence_artifacts = [str(fallback_path), *(artifacts or [])]
        self._record_production_evidence(
            stage_id=stage_id,
            action="blocked_fallback",
            status=status,
            proof_level="manual_gap",
            source_refs=source_refs,
            target_refs=target_refs,
            commands=[attempted_command] if attempted_command else [],
            test_results=[],
            artifacts=evidence_artifacts,
            blocked_reason=reason,
            owner=owner,
            next_action=next_action,
            summary=reason,
            gate_id=f"goal-stage-{stage_id}-blocked-fallback",
            kind="stage_fallback",
            configured=configured,
            required=required,
        )
        self._journal(
            "blocked_fallback",
            stage_id=stage_id,
            failure_class=failure_class,
            status=status,
            logical_minute=logical_minute,
        )
        next_stage_id = self.move_to_next_high_value_stage() if start_next else None
        fallback = {
            "schema_version": "xmuse.stage_fallback.v1",
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "status": status,
            "proof_level": "manual_gap",
            "reason": reason,
            "failure_class": failure_class,
            "retryable": retryable,
            "attempted_command": attempted_command,
            "next_action": next_action,
            "next_stage_id": next_stage_id,
            "artifact_path": str(fallback_path),
            "timestamp_utc": now,
        }
        if logical_minute is not None:
            fallback["logical_minute"] = logical_minute
        self._write_json(fallback_path, fallback)
        self._persist()
        return fallback

    def simulate_virtual_soak(
        self,
        config: OvernightSimulationConfig,
    ) -> dict[str, Any]:
        _validate_simulation_config(config)
        if self._current_stage_id is None:
            first_pending = self.move_to_next_high_value_stage()
            if first_pending is None:
                raise ValueError("cannot simulate overnight soak without stages")

        failures_by_minute: dict[int, list[OvernightSimulationFailure]] = {}
        for failure in config.failures or []:
            if failure.minute < 0 or failure.minute > config.total_minutes:
                raise ValueError(
                    f"simulation failure minute outside window: {failure.minute}"
                )
            failures_by_minute.setdefault(failure.minute, []).append(failure)

        for minute in range(0, config.total_minutes + 1):
            for failure in failures_by_minute.get(minute, []):
                self.fallback_blocked_stage(
                    stage_id=failure.stage_id,
                    reason=failure.reason,
                    failure_class=failure.failure_class,
                    retryable=failure.retryable,
                    attempted_command=failure.attempted_command,
                    configured=failure.configured,
                    required=failure.required,
                    source_refs=list(failure.source_refs),
                    target_refs=list(failure.target_refs),
                    next_action="continue to the next pending independent stage",
                    logical_minute=minute,
                )

            if minute % config.heartbeat_interval_minutes == 0:
                self.record_heartbeat(
                    note=f"virtual soak heartbeat at minute {minute}",
                    logical_minute=minute,
                )
            if minute > 0 and minute % config.checkpoint_interval_minutes == 0:
                current_stage_id = self._current_stage_id or _last_stage_id(self._stages)
                self.record_checkpoint(
                    stage_id=current_stage_id,
                    summary=f"virtual soak checkpoint at minute {minute}",
                    validation=[
                        "deterministic overnight virtual soak checkpoint"
                    ],
                    logical_minute=minute,
                )
            if minute > 0 and minute % config.self_review_interval_minutes == 0:
                current_stage_id = self._current_stage_id or _last_stage_id(self._stages)
                self.record_self_review(
                    stage_id=current_stage_id,
                    summary=f"virtual self-review at minute {minute}",
                    decision="continue",
                    findings=[
                        "projection authority and proof-level boundaries checked"
                    ],
                    minutes_since_previous_review=(
                        config.self_review_interval_minutes
                    ),
                    logical_minute=minute,
                )

        heartbeat_gaps = _logical_gaps(self._heartbeats)
        self_review_gaps = _logical_gaps(self._self_reviews)
        max_heartbeat_gap = (
            max(heartbeat_gaps)
            if heartbeat_gaps
            else config.heartbeat_interval_minutes
        )
        max_self_review_gap = (
            max(self_review_gaps)
            if self_review_gaps
            else config.self_review_interval_minutes
        )
        violations = _slo_violations(
            max_heartbeat_gap=max_heartbeat_gap,
            max_self_review_gap=max_self_review_gap,
            max_heartbeat_allowed=config.max_heartbeat_gap_minutes,
            max_self_review_allowed=config.max_self_review_gap_minutes,
        )
        result = {
            "schema_version": "xmuse.overnight_virtual_soak.v1",
            "run_id": self._config.run_id,
            "total_minutes": config.total_minutes,
            "heartbeat_count": len(self._heartbeats),
            "checkpoint_count": len(self._checkpoints),
            "self_review_count": len(self._self_reviews),
            "blocked_fallback_count": _evidence_action_count(
                self._production_evidence,
                "blocked_fallback",
            ),
            "max_heartbeat_gap_minutes": max_heartbeat_gap,
            "max_self_review_gap_minutes": max_self_review_gap,
            "slo_status": "violated" if violations else "ok",
            "slo_violations": violations,
            "final_stage_id": self._current_stage_id,
        }
        self._journal(
            "virtual_soak_completed",
            total_minutes=config.total_minutes,
            slo_status=str(result["slo_status"]),
        )
        self._persist()
        return result

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
        owner: str = "operator",
        source_refs: list[str] | None = None,
        target_refs: list[str] | None = None,
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        stage = self._stage(stage_id)
        stage["status"] = "manual_gap"
        stage["manual_gap_reason"] = reason
        stage["completed_at"] = _utcnow()
        manual_gap_path = self._config.artifact_dir / f"manual-gap-{stage_id}.json"
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
        self._write_json(manual_gap_path, gap)
        commands = [attempted_command] if attempted_command else []
        evidence_artifacts = [str(manual_gap_path), *(artifacts or [])]
        self._record_production_evidence(
            stage_id=stage_id,
            action="manual_gap",
            status="manual_gap",
            proof_level="manual_gap",
            source_refs=source_refs,
            target_refs=target_refs,
            commands=commands,
            test_results=[],
            artifacts=evidence_artifacts,
            blocked_reason=reason,
            owner=owner,
            next_action=next_action,
            summary=reason,
            gate_id=f"goal-stage-{stage_id}-manual-gap",
            kind="local_validation",
            configured=False,
            required=False,
        )
        self._journal("manual_gap", stage_id=stage_id, reason=reason)
        if self._current_stage_id == stage_id:
            self._current_stage_id = None
        self._persist()
        return gap

    def move_to_next_high_value_stage(self) -> str | None:
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for index, stage in enumerate(self._stages):
            if stage.get("status") != "pending":
                continue
            blocked_dependencies = _blocked_dependencies(stage, self._stages)
            if blocked_dependencies:
                self._journal(
                    "stage_selection_skipped",
                    stage_id=str(stage["stage_id"]),
                    blocked_dependencies=blocked_dependencies,
                )
                continue
            waiting_dependencies = _waiting_dependencies(stage, self._stages)
            if waiting_dependencies:
                self._journal(
                    "stage_selection_waiting",
                    stage_id=str(stage["stage_id"]),
                    waiting_dependencies=waiting_dependencies,
                )
                continue
            candidates.append((_priority(stage), index, stage))
        if candidates:
            _, _, selected = max(candidates, key=lambda item: (item[0], -item[1]))
            stage_id = str(selected["stage_id"])
            self.start_stage(stage_id)
            return stage_id
        return None

    def import_goal_stage_result(
        self,
        result_path: str | Path,
        *,
        start_next: bool = True,
        owner: str = "codex",
    ) -> dict[str, Any]:
        row = _load_goal_stage_result(Path(result_path))
        stage_id = str(row["stage_id"])
        stage = self._stage(stage_id)
        status = cast(ProductionEvidenceStatus, row["status"])
        now = _utcnow()
        blocked_reason = (
            _goal_stage_blocked_reason(row)
            if status in {"blocked", "retry"}
            else None
        )
        proof_level: ProofLevel = (
            "contract_proof" if status == "ok" else "manual_gap"
        )
        next_action = (
            "Continue to the next pending independent stage."
            if status == "blocked" and start_next
            else row.get("retry_hint") if status == "retry" else None
        )

        stage_result: dict[str, Any] = {
            "schema_version": "xmuse.goal_stage_result_import.v1",
            "run_id": self._config.run_id,
            "stage_id": stage_id,
            "status": status,
            "proof_level": proof_level,
            "engine": row["engine"],
            "result_path": row["result_path"],
            "issues": row["issues"],
            "command": row["command"],
            "artifacts": row["artifacts"],
            "returncode": row["returncode"],
            "attempt": row["attempt"],
            "blocked_reason": blocked_reason,
            "next_action": next_action,
            "timestamp_utc": now,
        }

        if status == "ok":
            stage["status"] = "ok"
            stage["completed_at"] = now
            stage["completed_summary"] = (
                f"Goal stage runner completed with engine {row['engine']}."
            )
            if self._current_stage_id == stage_id:
                self._current_stage_id = None
        elif status == "retry":
            stage["status"] = "running"
            stage["retry_hint"] = row.get("retry_hint")
            self._current_stage_id = stage_id
        else:
            stage["status"] = "blocked"
            stage["blocked_reason"] = blocked_reason
            stage["completed_at"] = now
            if self._current_stage_id == stage_id:
                self._current_stage_id = None
            self._issue_queue.append(
                {
                    "run_id": self._config.run_id,
                    "stage_id": stage_id,
                    "title": blocked_reason,
                    "severity": "blocked",
                    "source_ref": f"goal_stage_result:{row['result_path']}",
                    "status": "open",
                    "timestamp_utc": now,
                }
            )
            self._failure_classifications.append(
                {
                    "run_id": self._config.run_id,
                    "stage_id": stage_id,
                    "failure_class": "goal_stage_blocked",
                    "reason": blocked_reason,
                    "retryable": False,
                    "timestamp_utc": now,
                }
            )

        self._goal_stage_results.append(stage_result)
        self._record_production_evidence(
            stage_id=stage_id,
            action="goal_stage_result_imported",
            status=status,
            proof_level=proof_level,
            source_authority="goal_stage_harness",
            source_refs=[
                f"goal_run:{self._config.run_id}",
                f"goal_stage:{stage_id}",
                f"goal_stage_result:{row['result_path']}",
            ],
            target_refs=[
                f"overnight_supervisor:{self._config.run_id}",
                f"overnight_supervisor_stage:{stage_id}",
            ],
            commands=[_command_text(row["command"])],
            test_results=[],
            artifacts=list(row["artifacts"]),
            blocked_reason=blocked_reason,
            owner=owner,
            next_action=next_action,
            summary=_goal_stage_result_summary(row),
            gate_id=f"goal-stage-{stage_id}-stage-result",
            kind="goal_stage_harness",
            configured=True,
            required=True,
        )
        self._journal(
            "goal_stage_result_imported",
            stage_id=stage_id,
            status=status,
            result_path=str(row["result_path"]),
        )
        if status == "blocked" and start_next:
            stage_result["next_stage_id"] = self.move_to_next_high_value_stage()
        else:
            stage_result["next_stage_id"] = None
        self._persist()
        return stage_result

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
            "self_reviews": list(self._self_reviews),
            "production_evidence": list(self._production_evidence),
            "goal_stage_results": list(self._goal_stage_results),
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

    def _record_production_evidence(
        self,
        *,
        stage_id: str,
        action: str,
        status: ProductionEvidenceStatus,
        proof_level: ProofLevel,
        source_refs: list[str] | None = None,
        target_refs: list[str] | None = None,
        commands: list[str] | None = None,
        test_results: list[str] | None = None,
        artifacts: list[str] | None = None,
        blocked_reason: str | None = None,
        owner: str,
        next_action: str | None = None,
        summary: str | None = None,
        gate_id: str | None = None,
        kind: str | None = None,
        configured: bool | None = None,
        required: bool | None = None,
        source_authority: str = "overnight_operator_supervisor",
    ) -> dict[str, Any]:
        envelope = ProductionEvidenceEnvelope(
            run_id=self._config.run_id,
            stage_id=stage_id,
            action=action,
            status=status,
            proof_level=proof_level,
            source_authority=source_authority,
            source_refs=tuple(source_refs or ()),
            target_refs=tuple(target_refs or ()),
            commands=tuple(commands or ()),
            test_results=tuple(test_results or ()),
            artifacts=tuple(artifacts or ()),
            blocked_reason=blocked_reason,
            owner=owner,
            next_action=next_action,
            summary=summary,
            gate_id=gate_id,
            kind=kind,
            configured=configured,
            required=required,
        ).model_dump()
        self._production_evidence.append(envelope)
        self._write_json(
            self._production_evidence_path(stage_id=stage_id, action=action),
            envelope,
        )
        return envelope

    def _persist(self) -> None:
        self._write_json(
            self._snapshot_path(self._config),
            self.snapshot(),
        )

    @staticmethod
    def _snapshot_path(config: OvernightSupervisorConfig) -> Path:
        return config.artifact_dir / f"overnight-supervisor-{config.run_id}.json"

    def _production_evidence_path(self, *, stage_id: str, action: str) -> Path:
        index = len(self._production_evidence)
        return self._config.artifact_dir / (
            f"production-evidence-{index:03d}-{_slug(stage_id)}-{_slug(action)}.json"
        )

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


_SELF_REVIEW_DECISIONS = {
    "continue",
    "retry",
    "manual_gap",
    "blocked",
    "patch_forward",
}


def _review_slo_status(minutes_since_previous_review: int | None) -> str:
    if minutes_since_previous_review is None:
        return "not_evaluated"
    return "ok" if minutes_since_previous_review <= 60 else "violated"


def _validate_simulation_config(config: OvernightSimulationConfig) -> None:
    if config.total_minutes < 0:
        raise ValueError("total_minutes must be non-negative")
    if config.heartbeat_interval_minutes <= 0:
        raise ValueError("heartbeat_interval_minutes must be positive")
    if config.self_review_interval_minutes <= 0:
        raise ValueError("self_review_interval_minutes must be positive")
    if config.checkpoint_interval_minutes <= 0:
        raise ValueError("checkpoint_interval_minutes must be positive")
    if config.max_heartbeat_gap_minutes <= 0:
        raise ValueError("max_heartbeat_gap_minutes must be positive")
    if config.max_self_review_gap_minutes <= 0:
        raise ValueError("max_self_review_gap_minutes must be positive")


def _priority(stage: dict[str, Any]) -> int:
    value = stage.get("priority")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dependencies(stage: dict[str, Any]) -> list[str]:
    value = stage.get("depends_on")
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _stage_status_by_id(stages: list[dict[str, Any]]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for stage in stages:
        stage_id = stage.get("stage_id")
        status = stage.get("status")
        if isinstance(stage_id, str) and isinstance(status, str):
            statuses[stage_id] = status
    return statuses


def _blocked_dependencies(
    stage: dict[str, Any],
    stages: list[dict[str, Any]],
) -> list[str]:
    statuses = _stage_status_by_id(stages)
    return [
        dependency
        for dependency in _dependencies(stage)
        if statuses.get(dependency) in {"blocked", "manual_gap"}
    ]


def _waiting_dependencies(
    stage: dict[str, Any],
    stages: list[dict[str, Any]],
) -> list[str]:
    statuses = _stage_status_by_id(stages)
    return [
        dependency
        for dependency in _dependencies(stage)
        if statuses.get(dependency) != "ok"
        and statuses.get(dependency) not in {"blocked", "manual_gap"}
    ]


def _last_stage_id(stages: list[dict[str, Any]]) -> str:
    for stage in reversed(stages):
        stage_id = stage.get("stage_id")
        if isinstance(stage_id, str) and stage_id:
            return stage_id
    return "supervisor"


def _logical_gaps(rows: list[dict[str, Any]]) -> list[int]:
    minutes = [
        minute for row in rows if isinstance((minute := row.get("logical_minute")), int)
    ]
    return [right - left for left, right in zip(minutes, minutes[1:], strict=False)]


def _slo_violations(
    *,
    max_heartbeat_gap: int,
    max_self_review_gap: int,
    max_heartbeat_allowed: int,
    max_self_review_allowed: int,
) -> list[str]:
    violations: list[str] = []
    if max_heartbeat_gap > max_heartbeat_allowed:
        violations.append(
            f"heartbeat gap {max_heartbeat_gap}m exceeds {max_heartbeat_allowed}m"
        )
    if max_self_review_gap > max_self_review_allowed:
        violations.append(
            "self-review gap "
            f"{max_self_review_gap}m exceeds {max_self_review_allowed}m"
        )
    return violations


def _evidence_action_count(evidence_rows: list[dict[str, Any]], action: str) -> int:
    return sum(1 for evidence in evidence_rows if evidence.get("action") == action)


def _load_goal_stage_result(path: Path) -> dict[str, Any]:
    payload = _load_json_object(path)
    stage_id = _clean_text(payload.get("stage_id")) or "unknown"
    status = _goal_stage_status(payload.get("status"))
    command = _command(payload.get("command"))
    return {
        "stage_id": stage_id,
        "status": status,
        "engine": _clean_text(payload.get("engine")) or "unknown",
        "issues": _issue_messages(payload.get("issues")),
        "retry_hint": _clean_text(payload.get("retry_hint")),
        "result_path": str(path),
        "command": command,
        "artifacts": _goal_stage_artifacts(path=path, payload=payload),
        "returncode": payload.get("returncode"),
        "attempt": payload.get("attempt"),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"goal stage result does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"goal stage result is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"goal stage result must be a JSON object: {path}")
    return payload


def _goal_stage_status(value: object) -> ProductionEvidenceStatus:
    if value in {"ok", "retry", "blocked"}:
        return cast(ProductionEvidenceStatus, value)
    return "blocked"


def _issue_messages(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        message = _clean_text(item.get("message"))
        if message:
            messages.append(message)
    return messages


def _command(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _goal_stage_artifacts(*, path: Path, payload: dict[str, Any]) -> list[str]:
    artifacts = [
        str(path),
        str(path.parent / f"{path.name}.prompt.txt"),
        str(path.parent / f"{path.name}.manifest.jsonl"),
    ]
    stdout_path = _clean_text(payload.get("agent_stdout_path"))
    if stdout_path:
        artifacts.append(stdout_path)
    return _dedupe_existing(artifacts)


def _dedupe_existing(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw_path in paths:
        if not raw_path or raw_path in seen:
            continue
        if not Path(raw_path).exists():
            continue
        seen.add(raw_path)
        result.append(raw_path)
    return result


def _goal_stage_blocked_reason(row: dict[str, Any]) -> str:
    status = _clean_text(row.get("status")) or "blocked"
    issues = row.get("issues")
    if isinstance(issues, list) and issues:
        return f"goal stage result is {status}: " + "; ".join(
            str(issue) for issue in issues
        )
    return f"goal stage result is {status}"


def _goal_stage_result_summary(row: dict[str, Any]) -> str:
    return (
        f"Goal stage runner result imported for {row['stage_id']}: "
        f"{row['status']} via {row['engine']}."
    )


def _command_text(command: object) -> str:
    if not isinstance(command, list):
        return ""
    return " ".join(str(item) for item in command if str(item))


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in value.strip().lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "unknown"


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
