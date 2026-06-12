from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

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
        supervisor._self_reviews = _dict_rows(snapshot.get("self_reviews"))
        supervisor._production_evidence = _dict_rows(snapshot.get("production_evidence"))
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
            "self_reviews": list(self._self_reviews),
            "production_evidence": list(self._production_evidence),
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
    ) -> dict[str, Any]:
        envelope = ProductionEvidenceEnvelope(
            run_id=self._config.run_id,
            stage_id=stage_id,
            action=action,
            status=status,
            proof_level=proof_level,
            source_authority="overnight_operator_supervisor",
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
