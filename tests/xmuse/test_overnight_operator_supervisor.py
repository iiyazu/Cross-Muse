from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSimulationConfig,
    OvernightSimulationFailure,
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
    build_overnight_supervisor_recovery_gate,
)
from xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts import (
    lane_recovery_artifact_path,
)


def test_overnight_supervisor_records_heartbeat_checkpoint_and_stage_journal(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-1",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S1",
                    objective="TUI evidence actions",
                )
            ],
        )
    )

    supervisor.start_stage("S1")
    supervisor.record_heartbeat(note="wrote failing tests")
    supervisor.record_checkpoint(
        stage_id="S1",
        summary="red tests define evidence action contract",
        validation=["uv run pytest tests/xmuse/test_operator_evidence_actions.py -q"],
    )
    supervisor.complete_stage("S1", summary="evidence action spine green")

    snapshot = supervisor.snapshot()
    assert snapshot["schema_version"] == "xmuse.overnight_supervisor.v1"
    assert snapshot["run_id"] == "run-1"
    assert snapshot["current_stage_id"] is None
    assert snapshot["stages"][0]["status"] == "ok"
    assert snapshot["heartbeats"][0]["note"] == "wrote failing tests"
    assert snapshot["checkpoints"][0]["summary"] == "red tests define evidence action contract"
    assert snapshot["stage_journal"][-1]["event"] == "stage_completed"

    persisted = json.loads((tmp_path / "overnight-supervisor-run-1.json").read_text())
    assert persisted["run_id"] == "run-1"
    assert persisted["stages"][0]["completed_summary"] == "evidence action spine green"


def test_overnight_supervisor_recovery_gate_snapshots_durable_blocks(
    tmp_path: Path,
) -> None:
    _write_lane_recovery_artifact(
        tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-blocked",
        decision="refactor_required",
        retry_allowed=False,
    )
    _write_lane_recovery_artifact(
        tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-retry",
        decision="retry",
        retry_allowed=True,
    )

    gate = build_overnight_supervisor_recovery_gate(tmp_path)

    assert gate["schema_version"] == "xmuse.overnight_supervisor_recovery_gate.v1"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert gate["source_authority"] == "lane_recovery_artifact"
    assert gate["counts"]["blocked"] == 1
    assert gate["counts"]["non_retry_decision"] == 1
    assert gate["counts"]["retry_allowed"] == 1
    assert gate["blocked_lanes"][0]["lane_id"] == "lane-blocked"
    assert gate["blocked_lanes"][0]["decision"] == "refactor_required"
    assert "lane_graphs/graph-runtime.lane-blocked.recovery.json" in gate[
        "source_refs"
    ]
    assert "overnight_safe_recovery_not_proven" in gate["manual_gaps"]
    assert "worker_output_is_review_truth" in gate["forbidden_claims"]
    assert "overnight_safe_recovery" in gate["forbidden_claims"]


def test_overnight_supervisor_blocks_stage_with_refactor_required_recovery_artifact(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "overnight"
    _write_lane_recovery_artifact(
        tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-blocked",
        decision="refactor_required",
        retry_allowed=False,
    )
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-recovery-gate",
            artifact_dir=artifact_dir,
            xmuse_root=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S4",
                    objective="overnight supervisor loop",
                )
            ],
        )
    )

    with pytest.raises(RuntimeError, match="recovery gate blocked stage S4"):
        supervisor.start_stage("S4")

    snapshot = supervisor.snapshot()
    assert snapshot["current_stage_id"] is None
    assert snapshot["stages"][0]["status"] == "blocked"
    assert snapshot["stages"][0]["blocked_reason"] == (
        "Durable lane recovery artifacts block overnight supervisor stage start."
    )
    assert snapshot["issue_queue"][0]["severity"] == "blocked"
    assert snapshot["failure_classifications"][0]["failure_class"] == (
        "durable_lane_recovery_block"
    )
    evidence = snapshot["production_evidence"][0]
    assert evidence["action"] == "recovery_gate_block"
    assert evidence["status"] == "blocked"
    assert evidence["proof_level"] == "manual_gap"
    assert evidence["kind"] == "supervisor_recovery_gate"
    assert evidence["source_refs"] == [
        "lane_graphs/graph-runtime.lane-blocked.recovery.json"
    ]
    assert evidence["target_refs"] == ["overnight_supervisor_stage:S4"]
    gate_path = artifact_dir / "overnight-recovery-gate-s4.json"
    assert evidence["artifacts"] == [str(gate_path)]
    assert json.loads(gate_path.read_text(encoding="utf-8"))["status"] == "blocked"


def test_overnight_supervisor_records_checkpoint_production_evidence(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-evidence",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S1",
                    objective="shared production evidence envelope",
                )
            ],
        )
    )

    supervisor.start_stage("S1")
    supervisor.record_checkpoint(
        stage_id="S1",
        summary="shared envelope contract is green",
        validation=["1 passed"],
        commands=["uv run pytest tests/xmuse/test_production_evidence.py -q"],
        source_refs=["goal:stage:S1"],
        target_refs=["artifact://stage/S1/result.json"],
        artifacts=["artifact://stage/S1/result.json"],
        next_action="continue to S2",
    )

    snapshot = supervisor.snapshot()
    evidence = snapshot["production_evidence"][0]
    assert evidence["schema_version"] == "xmuse.production_evidence.v1"
    assert evidence["run_id"] == "run-evidence"
    assert evidence["stage_id"] == "S1"
    assert evidence["action"] == "checkpoint"
    assert evidence["status"] == "ok"
    assert evidence["proof_level"] == "contract_proof"
    assert evidence["source_authority"] == "overnight_operator_supervisor"
    assert evidence["source_refs"] == ["goal:stage:S1"]
    assert evidence["target_refs"] == ["artifact://stage/S1/result.json"]
    assert evidence["commands"] == [
        "uv run pytest tests/xmuse/test_production_evidence.py -q"
    ]
    assert evidence["test_results"] == ["1 passed"]
    assert evidence["artifacts"] == ["artifact://stage/S1/result.json"]
    assert evidence["blocked_reason"] is None
    assert evidence["owner"] == "codex"
    assert evidence["next_action"] == "continue to S2"
    assert evidence["gate_id"] == "goal-stage-S1-checkpoint"
    assert evidence["kind"] == "local_validation"
    assert evidence["required"] is False

    persisted = json.loads((tmp_path / "overnight-supervisor-run-evidence.json").read_text())
    assert persisted["production_evidence"] == [evidence]
    evidence_files = sorted(tmp_path.glob("production-evidence-*.json"))
    assert len(evidence_files) == 1
    assert json.loads(evidence_files[0].read_text()) == evidence


def test_overnight_supervisor_blocks_stage_with_manual_gap_and_moves_on(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-2",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S4", objective="live soak"),
                OvernightSupervisorStage(stage_id="S5", objective="docs and validation"),
            ],
        )
    )

    supervisor.start_stage("S4")
    gap = supervisor.manual_gap(
        stage_id="S4",
        reason="XMUSE_LIVE_MEMORYOS_LITE is not enabled",
        attempted_command="uv run pytest tests/xmuse/test_memoryos_lite_interop.py -q",
        next_action="Continue with contract/fake validation and docs.",
    )
    supervisor.move_to_next_high_value_stage()

    snapshot = supervisor.snapshot()
    assert gap["proof_level"] == "manual_gap"
    assert gap["stage_id"] == "S4"
    assert gap["reason"] == "XMUSE_LIVE_MEMORYOS_LITE is not enabled"
    assert snapshot["stages"][0]["status"] == "manual_gap"
    assert snapshot["stages"][1]["status"] == "running"
    assert snapshot["current_stage_id"] == "S5"
    assert snapshot["manual_gaps"] == [gap]
    assert (tmp_path / "manual-gap-S4.json").exists()


def test_overnight_supervisor_records_manual_gap_production_evidence(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-gap-evidence",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S4", objective="live soak"),
            ],
        )
    )

    supervisor.start_stage("S4")
    supervisor.manual_gap(
        stage_id="S4",
        reason="XMUSE_LIVE_MEMORYOS_LITE is not enabled",
        attempted_command="uv run xmuse-memoryos-live-gate-capture",
        next_action="Enable XMUSE_LIVE_MEMORYOS_LITE and rerun live trace capture.",
    )

    evidence = supervisor.snapshot()["production_evidence"][0]
    assert evidence["schema_version"] == "xmuse.production_evidence.v1"
    assert evidence["run_id"] == "run-gap-evidence"
    assert evidence["stage_id"] == "S4"
    assert evidence["action"] == "manual_gap"
    assert evidence["status"] == "manual_gap"
    assert evidence["proof_level"] == "manual_gap"
    assert evidence["source_authority"] == "overnight_operator_supervisor"
    assert evidence["commands"] == ["uv run xmuse-memoryos-live-gate-capture"]
    assert evidence["blocked_reason"] == "XMUSE_LIVE_MEMORYOS_LITE is not enabled"
    assert evidence["owner"] == "operator"
    assert evidence["next_action"] == (
        "Enable XMUSE_LIVE_MEMORYOS_LITE and rerun live trace capture."
    )
    assert evidence["gate_id"] == "goal-stage-S4-manual-gap"
    assert evidence["kind"] == "local_validation"
    assert evidence["configured"] is False
    assert evidence["required"] is False
    assert str(tmp_path / "manual-gap-S4.json") in evidence["artifacts"]


def test_overnight_supervisor_tracks_issue_queue_and_failure_classification(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-issues",
            artifact_dir=tmp_path,
            stages=[OvernightSupervisorStage(stage_id="S3", objective="supervise")],
        )
    )

    issue = supervisor.record_issue(
        stage_id="S3",
        title="GitHub auth unavailable",
        severity="manual_gap",
        source_ref="github://repo/pull/new/branch",
    )
    failure = supervisor.classify_failure(
        stage_id="S3",
        failure_class="auth_unavailable",
        reason="gh auth status cannot access repository",
        retryable=False,
    )

    snapshot = supervisor.snapshot()
    assert snapshot["issue_queue"] == [issue]
    assert issue["status"] == "open"
    assert issue["source_ref"] == "github://repo/pull/new/branch"
    assert snapshot["failure_classifications"] == [failure]
    assert failure["retryable"] is False
    assert failure["failure_class"] == "auth_unavailable"


def test_overnight_supervisor_escalates_repeated_failure_to_refactor(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-refactor-escalation",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S4",
                    objective="stabilize release evidence export",
                ),
            ],
        )
    )

    supervisor.start_stage("S4")
    first = supervisor.classify_failure(
        stage_id="S4",
        failure_class="release_export_failed",
        reason="memoryos export raised before writing a replay artifact",
        retryable=True,
    )
    second = supervisor.classify_failure(
        stage_id="S4",
        failure_class="release_export_failed",
        reason="memoryos export still raised after a local fix",
        retryable=True,
    )
    third = supervisor.classify_failure(
        stage_id="S4",
        failure_class="release_export_failed",
        reason="memoryos export failed a third time on the same boundary",
        retryable=True,
    )

    snapshot = supervisor.snapshot()
    assert first["repeat_count"] == 1
    assert second["repeat_count"] == 2
    assert third["repeat_count"] == 3
    assert third["retryable"] is False
    assert third["escalation"] == "refactor_required"
    assert third["recommended_action"] == (
        "refactor the failing function boundary before retrying"
    )
    assert snapshot["stages"][0]["status"] == "blocked"
    assert snapshot["stages"][0]["blocked_reason"] == (
        "Repeated failure requires refactor: release_export_failed"
    )
    assert snapshot["current_stage_id"] is None
    assert snapshot["issue_queue"] == [
        {
            "run_id": "run-refactor-escalation",
            "stage_id": "S4",
            "title": "Repeated failure requires refactor: release_export_failed",
            "severity": "refactor_required",
            "source_ref": "failure_class:S4:release_export_failed",
            "status": "open",
            "timestamp_utc": snapshot["issue_queue"][0]["timestamp_utc"],
        }
    ]
    evidence = snapshot["production_evidence"][0]
    assert evidence["action"] == "failure_refactor_escalation"
    assert evidence["status"] == "blocked"
    assert evidence["proof_level"] == "manual_gap"
    assert evidence["blocked_reason"] == (
        "Repeated failure requires refactor: release_export_failed"
    )
    assert evidence["next_action"] == (
        "refactor the failing function boundary before retrying"
    )
    assert evidence["kind"] == "supervisor_failure_policy"


def test_overnight_supervisor_records_self_review_checkpoint_and_evidence(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-self-review",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S4",
                    objective="overnight supervisor loop",
                ),
            ],
        )
    )

    supervisor.start_stage("S4")
    review = supervisor.record_self_review(
        stage_id="S4",
        summary="45 minute review found no projection authority leak.",
        findings=["TUI remains an operator surface, not a durable authority."],
        decision="continue",
        minutes_since_previous_review=52,
        commands=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        test_results=["self-review contract red/green covered"],
        source_refs=["goal:stage:S4"],
        target_refs=["artifact://overnight-supervisor/run-self-review"],
        artifacts=["artifact://self-review/S4"],
        next_action="continue S4 until the next checkpoint",
    )

    snapshot = supervisor.snapshot()
    assert snapshot["self_reviews"] == [review]
    assert review["run_id"] == "run-self-review"
    assert review["stage_id"] == "S4"
    assert review["decision"] == "continue"
    assert review["minutes_since_previous_review"] == 52
    assert review["slo_status"] == "ok"
    assert review["findings"] == [
        "TUI remains an operator surface, not a durable authority."
    ]
    assert snapshot["stage_journal"][-1]["event"] == "self_review_recorded"

    evidence = snapshot["production_evidence"][0]
    assert evidence["schema_version"] == "xmuse.production_evidence.v1"
    assert evidence["run_id"] == "run-self-review"
    assert evidence["stage_id"] == "S4"
    assert evidence["action"] == "self_review"
    assert evidence["status"] == "ok"
    assert evidence["proof_level"] == "contract_proof"
    assert evidence["source_authority"] == "overnight_operator_supervisor"
    assert evidence["commands"] == [
        "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"
    ]
    assert evidence["test_results"] == ["self-review contract red/green covered"]
    assert evidence["artifacts"] == ["artifact://self-review/S4"]
    assert evidence["owner"] == "codex"
    assert evidence["next_action"] == "continue S4 until the next checkpoint"
    assert evidence["gate_id"] == "goal-stage-S4-self-review"
    assert evidence["kind"] == "self_review"
    assert evidence["configured"] is True
    assert evidence["required"] is True

    persisted = json.loads(
        (tmp_path / "overnight-supervisor-run-self-review.json").read_text()
    )
    assert persisted["self_reviews"] == [review]


def test_overnight_supervisor_blocked_fallback_records_issue_failure_and_next_stage(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-blocked-fallback",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S6",
                    objective="fresh GitHub truth",
                ),
                OvernightSupervisorStage(
                    stage_id="S7",
                    objective="TUI proof cockpit",
                ),
            ],
        )
    )

    supervisor.start_stage("S6")
    fallback = supervisor.fallback_blocked_stage(
        stage_id="S6",
        reason="GitHub review truth is configured but unavailable.",
        failure_class="github_review_truth_unavailable",
        retryable=False,
        attempted_command="gh api repos/iiyazu/Cross-Muse/pulls/43/reviews",
        next_action="continue to independent TUI proof cockpit work",
        source_refs=["github://iiyazu/Cross-Muse/pull/43"],
        target_refs=["artifact://github-truth/pr-43"],
    )

    snapshot = supervisor.snapshot()
    assert fallback["status"] == "blocked"
    assert fallback["proof_level"] == "manual_gap"
    assert fallback["stage_id"] == "S6"
    assert fallback["next_stage_id"] == "S7"
    assert snapshot["stages"][0]["status"] == "blocked"
    assert snapshot["stages"][0]["blocked_reason"] == (
        "GitHub review truth is configured but unavailable."
    )
    assert snapshot["stages"][1]["status"] == "running"
    assert snapshot["current_stage_id"] == "S7"
    assert snapshot["issue_queue"][0]["title"] == (
        "GitHub review truth is configured but unavailable."
    )
    assert snapshot["issue_queue"][0]["severity"] == "blocked"
    assert snapshot["failure_classifications"][0]["failure_class"] == (
        "github_review_truth_unavailable"
    )
    assert snapshot["failure_classifications"][0]["retryable"] is False
    assert snapshot["stage_journal"][-1]["event"] == "stage_started"

    evidence = snapshot["production_evidence"][0]
    assert evidence["action"] == "blocked_fallback"
    assert evidence["status"] == "blocked"
    assert evidence["proof_level"] == "manual_gap"
    assert evidence["blocked_reason"] == (
        "GitHub review truth is configured but unavailable."
    )
    assert evidence["commands"] == [
        "gh api repos/iiyazu/Cross-Muse/pulls/43/reviews"
    ]
    assert evidence["source_refs"] == ["github://iiyazu/Cross-Muse/pull/43"]
    assert evidence["target_refs"] == ["artifact://github-truth/pr-43"]
    assert evidence["gate_id"] == "goal-stage-S6-blocked-fallback"
    assert evidence["kind"] == "stage_fallback"
    assert evidence["configured"] is True
    assert evidence["required"] is True

    artifact_path = Path(fallback["artifact_path"])
    assert artifact_path.exists()
    assert json.loads(artifact_path.read_text()) == fallback


def test_overnight_supervisor_fallback_skips_dependent_stage_and_prefers_priority(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-dependent-fallback",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S4",
                    objective="live evidence gates",
                    priority=100,
                ),
                OvernightSupervisorStage(
                    stage_id="S5",
                    objective="release pack that depends on live gates",
                    priority=95,
                    depends_on=("S4",),
                ),
                OvernightSupervisorStage(
                    stage_id="S6",
                    objective="independent docs and validation",
                    priority=40,
                ),
            ],
        )
    )

    supervisor.start_stage("S4")
    fallback = supervisor.fallback_blocked_stage(
        stage_id="S4",
        reason="MemoryOS live trace is configured but unavailable.",
        failure_class="memoryos_live_trace_unavailable",
        retryable=False,
        attempted_command="uv run xmuse-memoryos-live-trace-capture",
        next_action="continue to the next independent stage",
        source_refs=["memoryos://live-trace"],
    )

    snapshot = supervisor.snapshot()
    assert fallback["next_stage_id"] == "S6"
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "blocked",
        "pending",
        "running",
    ]
    assert snapshot["current_stage_id"] == "S6"
    assert snapshot["stages"][1]["depends_on"] == ["S4"]
    assert snapshot["stages"][1]["priority"] == 95
    skipped = [
        row for row in snapshot["stage_journal"] if row["event"] == "stage_selection_skipped"
    ]
    assert skipped[-1]["stage_id"] == "S5"
    assert skipped[-1]["blocked_dependencies"] == ["S4"]


def test_overnight_supervisor_imports_goal_stage_runner_result_evidence(
    tmp_path: Path,
) -> None:
    ok_result = tmp_path / "goal" / "S1.result.json"
    blocked_result = tmp_path / "goal" / "S4.result.json"
    _write_goal_stage_runner_result(
        ok_result,
        stage_id="S1",
        status="ok",
        engine="opencode",
        command=[
            "opencode",
            "run",
            "--model",
            "opencode-go/deepseek-v4-flash",
            "--variant",
            "max",
        ],
    )
    _write_goal_stage_runner_result(
        blocked_result,
        stage_id="S4",
        status="blocked",
        engine="codex",
        command=["codex", "exec", "-"],
        issues=[{"message": "MemoryOS Lite live trace is configured but unavailable."}],
    )

    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-stage-result-import",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S1", objective="stage harness smoke"),
                OvernightSupervisorStage(stage_id="S4", objective="live evidence gates"),
                OvernightSupervisorStage(stage_id="S6", objective="independent docs"),
            ],
        )
    )

    ok_import = supervisor.import_goal_stage_result(ok_result)
    supervisor.start_stage("S4")
    blocked_import = supervisor.import_goal_stage_result(blocked_result)

    snapshot = supervisor.snapshot()
    assert ok_import["status"] == "ok"
    assert blocked_import["status"] == "blocked"
    assert blocked_import["next_stage_id"] == "S6"
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "ok",
        "blocked",
        "running",
    ]
    assert snapshot["current_stage_id"] == "S6"
    assert snapshot["goal_stage_results"] == [ok_import, blocked_import]

    ok_evidence = snapshot["production_evidence"][0]
    assert ok_evidence["action"] == "goal_stage_result_imported"
    assert ok_evidence["status"] == "ok"
    assert ok_evidence["proof_level"] == "contract_proof"
    assert ok_evidence["source_authority"] == "goal_stage_harness"
    assert ok_evidence["source_refs"] == [
        "goal_run:run-stage-result-import",
        "goal_stage:S1",
        f"goal_stage_result:{ok_result}",
    ]
    assert ok_evidence["commands"] == [
        "opencode run --model opencode-go/deepseek-v4-flash --variant max"
    ]
    assert ok_evidence["artifacts"] == [
        str(ok_result),
        str(ok_result.parent / f"{ok_result.name}.prompt.txt"),
        str(ok_result.parent / f"{ok_result.name}.manifest.jsonl"),
        str(ok_result.parent / f"{ok_result.name}.evidence" / "engine_output.txt"),
    ]
    assert ok_evidence["gate_id"] == "goal-stage-S1-stage-result"
    assert ok_evidence["kind"] == "goal_stage_harness"

    blocked_evidence = snapshot["production_evidence"][1]
    assert blocked_evidence["status"] == "blocked"
    assert blocked_evidence["proof_level"] == "manual_gap"
    assert blocked_evidence["blocked_reason"] == (
        "goal stage result is blocked: "
        "MemoryOS Lite live trace is configured but unavailable."
    )
    assert snapshot["issue_queue"][0]["title"] == (
        "goal stage result is blocked: "
        "MemoryOS Lite live trace is configured but unavailable."
    )
    assert snapshot["failure_classifications"][0]["failure_class"] == (
        "goal_stage_blocked"
    )
    assert snapshot["stage_journal"][-1]["event"] == "stage_started"


def test_overnight_supervisor_imported_repeated_retry_result_requires_refactor(
    tmp_path: Path,
) -> None:
    retry_results = [
        tmp_path / "goal" / f"S4.retry-{attempt}.json"
        for attempt in (1, 2, 3)
    ]
    for attempt, result_path in enumerate(retry_results, start=1):
        _write_goal_stage_runner_result(
            result_path,
            stage_id="S4",
            status="retry",
            engine="opencode",
            command=[
                "opencode",
                "run",
                "--model",
                "opencode-go/deepseek-v4-flash",
                "--variant",
                "max",
            ],
            issues=[{"message": "same stage boundary still needs retry"}],
            attempt=attempt,
        )

    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-stage-retry-refactor",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S4", objective="live evidence gates"),
            ],
        )
    )

    first = supervisor.import_goal_stage_result(retry_results[0])
    second = supervisor.import_goal_stage_result(retry_results[1])
    third = supervisor.import_goal_stage_result(retry_results[2])

    snapshot = supervisor.snapshot()
    assert first["status"] == "retry"
    assert second["status"] == "retry"
    assert third["status"] == "retry"
    assert third["escalation"] == "refactor_required"
    assert third["next_action"] == (
        "refactor the failing function boundary before retrying"
    )
    assert snapshot["stages"][0]["status"] == "blocked"
    assert snapshot["stages"][0]["refactor_required"] is True
    assert snapshot["current_stage_id"] is None
    assert snapshot["failure_classifications"][-1]["failure_class"] == (
        "goal_stage_retry"
    )
    assert snapshot["failure_classifications"][-1]["repeat_count"] == 3
    assert snapshot["issue_queue"][0]["severity"] == "refactor_required"
    assert any(
        evidence["action"] == "failure_refactor_escalation"
        and evidence["kind"] == "supervisor_failure_policy"
        for evidence in snapshot["production_evidence"]
    )


def test_overnight_supervisor_can_resume_from_persisted_snapshot(tmp_path: Path) -> None:
    config = OvernightSupervisorConfig(
        run_id="run-resume",
        artifact_dir=tmp_path,
        stages=[OvernightSupervisorStage(stage_id="S3", objective="supervise")],
    )
    supervisor = OvernightSupervisor(config)
    supervisor.start_stage("S3")
    supervisor.record_checkpoint(stage_id="S3", summary="checkpoint before resume")

    resumed = OvernightSupervisor.resume(config)

    snapshot = resumed.snapshot()
    assert snapshot["current_stage_id"] == "S3"
    assert snapshot["stages"][0]["status"] == "running"
    assert snapshot["checkpoints"][0]["summary"] == "checkpoint before resume"


def test_overnight_supervisor_live_soak_requires_explicit_flags(tmp_path: Path) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="run-3",
            artifact_dir=tmp_path,
            stages=[OvernightSupervisorStage(stage_id="S4", objective="live soak")],
        )
    )

    disabled = supervisor.live_soak_plan(
        env={},
        required_flags={
            "memoryos": "XMUSE_LIVE_MEMORYOS_LITE",
            "github": "XMUSE_LIVE_GITHUB_TRUTH",
        },
    )
    enabled = supervisor.live_soak_plan(
        env={"XMUSE_LIVE_MEMORYOS_LITE": "1", "XMUSE_LIVE_GITHUB_TRUTH": "true"},
        required_flags={
            "memoryos": "XMUSE_LIVE_MEMORYOS_LITE",
            "github": "XMUSE_LIVE_GITHUB_TRUTH",
        },
    )

    assert disabled == {
        "memoryos": {
            "enabled": False,
            "proof_level": "manual_gap",
            "manual_gap_reason": "missing opt-in flag XMUSE_LIVE_MEMORYOS_LITE",
        },
        "github": {
            "enabled": False,
            "proof_level": "manual_gap",
            "manual_gap_reason": "missing opt-in flag XMUSE_LIVE_GITHUB_TRUTH",
        },
    }
    assert enabled == {
        "memoryos": {
            "enabled": True,
            "proof_level": "live_service_proof",
            "manual_gap_reason": None,
        },
        "github": {
            "enabled": True,
            "proof_level": "live_service_proof",
            "manual_gap_reason": None,
        },
    }


def test_overnight_supervisor_virtual_soak_simulates_8h_and_blocked_fallback(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="virtual-overnight",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S4", objective="live gates"),
                OvernightSupervisorStage(stage_id="S5", objective="docs and validation"),
            ],
        )
    )

    result = supervisor.simulate_virtual_soak(
        OvernightSimulationConfig(
            total_minutes=480,
            heartbeat_interval_minutes=15,
            self_review_interval_minutes=60,
            checkpoint_interval_minutes=120,
            failures=[
                OvernightSimulationFailure(
                    minute=180,
                    stage_id="S4",
                    reason="GitHub review truth is configured but unavailable.",
                    failure_class="github_review_truth_unavailable",
                    retryable=False,
                    attempted_command="gh api repos/iiyazu/Cross-Muse/pulls/43/reviews",
                    source_refs=("github://iiyazu/Cross-Muse/pull/43",),
                )
            ],
        )
    )

    snapshot = supervisor.snapshot()
    assert result == {
        "schema_version": "xmuse.overnight_virtual_soak.v1",
        "run_id": "virtual-overnight",
        "total_minutes": 480,
        "heartbeat_count": 33,
        "checkpoint_count": 4,
        "self_review_count": 8,
        "blocked_fallback_count": 1,
        "max_heartbeat_gap_minutes": 15,
        "max_self_review_gap_minutes": 60,
        "slo_status": "ok",
        "slo_violations": [],
        "final_stage_id": "S5",
    }
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "blocked",
        "running",
    ]
    assert snapshot["current_stage_id"] == "S5"
    assert snapshot["heartbeats"][0]["logical_minute"] == 0
    assert snapshot["heartbeats"][-1]["logical_minute"] == 480
    assert {row["logical_minute"] for row in snapshot["self_reviews"]} == {
        60,
        120,
        180,
        240,
        300,
        360,
        420,
        480,
    }
    assert snapshot["checkpoints"][-1]["stage_id"] == "S5"
    assert snapshot["checkpoints"][-1]["logical_minute"] == 480
    assert snapshot["virtual_soaks"] == [result]
    assert snapshot["issue_queue"][0]["severity"] == "blocked"
    assert snapshot["failure_classifications"][0]["failure_class"] == (
        "github_review_truth_unavailable"
    )
    assert any(
        evidence["action"] == "checkpoint"
        and evidence["summary"] == "virtual soak checkpoint at minute 480"
        for evidence in snapshot["production_evidence"]
    )
    assert any(
        evidence["action"] == "blocked_fallback"
        and evidence["blocked_reason"]
        == "GitHub review truth is configured but unavailable."
        for evidence in snapshot["production_evidence"]
    )


def test_overnight_supervisor_virtual_soak_reports_slo_violations(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="virtual-slo-violation",
            artifact_dir=tmp_path,
            stages=[OvernightSupervisorStage(stage_id="S4", objective="live gates")],
        )
    )

    result = supervisor.simulate_virtual_soak(
        OvernightSimulationConfig(
            total_minutes=180,
            heartbeat_interval_minutes=20,
            self_review_interval_minutes=75,
            checkpoint_interval_minutes=90,
            max_heartbeat_gap_minutes=15,
            max_self_review_gap_minutes=60,
        )
    )

    assert result["slo_status"] == "violated"
    assert result["max_heartbeat_gap_minutes"] == 20
    assert result["max_self_review_gap_minutes"] == 75
    assert result["slo_violations"] == [
        "heartbeat gap 20m exceeds 15m",
        "self-review gap 75m exceeds 60m",
    ]
    assert supervisor.snapshot()["virtual_soaks"][0]["slo_status"] == "violated"
    assert supervisor.snapshot()["virtual_soaks"][0]["slo_violations"] == [
        "heartbeat gap 20m exceeds 15m",
        "self-review gap 75m exceeds 60m",
    ]


def test_overnight_supervisor_cli_records_resumable_stage_flow(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    common = [
        "--run-id",
        "overnight-cli-run",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S3=supervise goal loop",
        "--stage",
        "S4=attempt live soak",
    ]

    assert main([*common, "start-stage", "S3"]) == 0
    assert main([*common, "--resume", "heartbeat", "--note", "S3 heartbeat"]) == 0
    assert (
        main(
            [
                *common,
                "--resume",
                "checkpoint",
                "S3",
                "--summary",
                "supervisor checkpoint captured",
                "--command",
                "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q",
                "--test-result",
                "test_overnight_supervisor_cli_records_resumable_stage_flow passed",
                "--source-ref",
                "goal:stage:S3",
                "--target-ref",
                "artifact://overnight-supervisor/overnight-cli-run",
            ]
        )
        == 0
    )
    assert main([*common, "--resume", "complete-stage", "S3", "--summary", "S3 done"]) == 0
    assert (
        main(
            [
                *common,
                "--resume",
                "manual-gap",
                "S4",
                "--reason",
                "MemoryOS Lite live gate is not configured",
                "--attempted-command",
                "uv run xmuse-memoryos-live-trace-capture",
                "--next-action",
                "Configure MemoryOS Lite and rerun live trace capture.",
            ]
        )
        == 0
    )

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-cli-run.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["run_id"] == "overnight-cli-run"
    assert [stage["status"] for stage in snapshot["stages"]] == ["ok", "manual_gap"]
    assert snapshot["heartbeats"][0]["note"] == "S3 heartbeat"
    assert snapshot["checkpoints"][0]["summary"] == "supervisor checkpoint captured"
    assert snapshot["manual_gaps"][0]["reason"] == (
        "MemoryOS Lite live gate is not configured"
    )
    assert snapshot["production_evidence"][0]["commands"] == [
        "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"
    ]
    assert snapshot["production_evidence"][0]["source_refs"] == ["goal:stage:S3"]
    assert snapshot["production_evidence"][0]["target_refs"] == [
        "artifact://overnight-supervisor/overnight-cli-run"
    ]
    assert snapshot["production_evidence"][1]["status"] == "manual_gap"


def test_overnight_supervisor_cli_can_move_to_next_stage(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    common = [
        "--run-id",
        "overnight-next-stage",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S3=supervise goal loop",
        "--stage",
        "S4=attempt live soak",
    ]

    assert main([*common, "start-stage", "S3"]) == 0
    assert (
        main(
            [
                *common,
                "--resume",
                "manual-gap",
                "S3",
                "--reason",
                "GitHub review truth is unavailable",
            ]
        )
        == 0
    )
    assert main([*common, "--resume", "next-stage"]) == 0

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-next-stage.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["current_stage_id"] == "S4"
    assert snapshot["stages"][1]["status"] == "running"


def test_overnight_supervisor_cli_escalates_repeated_failure_to_refactor(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    common = [
        "--run-id",
        "overnight-cli-refactor",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S4=release export stability",
    ]

    assert main([*common, "start-stage", "S4"]) == 0
    for reason in [
        "memoryos export failed before writing replay input",
        "memoryos export failed again after local patch",
        "memoryos export failed a third time on same boundary",
    ]:
        assert (
            main(
                [
                    *common,
                    "--resume",
                    "classify-failure",
                    "S4",
                    "--failure-class",
                    "release_export_failed",
                    "--reason",
                    reason,
                    "--retryable",
                ]
            )
            == 0
        )

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-cli-refactor.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["stages"][0]["status"] == "blocked"
    assert snapshot["stages"][0]["refactor_required"] is True
    assert snapshot["failure_classifications"][-1]["escalation"] == (
        "refactor_required"
    )
    assert snapshot["issue_queue"][0]["severity"] == "refactor_required"


def test_overnight_supervisor_cli_accepts_stage_priority_and_dependencies(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    common = [
        "--run-id",
        "overnight-cli-dependencies",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S4=live evidence gates",
        "--stage",
        "S5=release pack",
        "--stage",
        "S6=independent docs",
        "--stage-priority",
        "S4=100",
        "--stage-priority",
        "S5=95",
        "--stage-priority",
        "S6=40",
        "--stage-depends-on",
        "S5=S4",
    ]

    assert main([*common, "start-stage", "S4"]) == 0
    assert (
        main(
            [
                *common,
                "--resume",
                "blocked-fallback",
                "S4",
                "--reason",
                "GitHub review truth is configured but unavailable.",
                "--failure-class",
                "github_review_truth_unavailable",
                "--attempted-command",
                "gh api repos/iiyazu/Cross-Muse/pulls/43/reviews",
            ]
        )
        == 0
    )

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-cli-dependencies.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["current_stage_id"] == "S6"
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "blocked",
        "pending",
        "running",
    ]
    assert snapshot["stages"][1]["depends_on"] == ["S4"]
    assert snapshot["stages"][1]["priority"] == 95


def test_overnight_supervisor_cli_imports_goal_stage_result_and_falls_back(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    result = tmp_path / "goal" / "S4.result.json"
    _write_goal_stage_runner_result(
        result,
        stage_id="S4",
        status="blocked",
        engine="codex",
        command=["codex", "exec", "-"],
        issues=[{"message": "GitHub review truth is configured but unavailable."}],
    )
    common = [
        "--run-id",
        "overnight-cli-stage-import",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S4=fresh GitHub truth",
        "--stage",
        "S7=TUI proof cockpit",
    ]

    assert main([*common, "start-stage", "S4"]) == 0
    assert main([*common, "--resume", "import-stage-result", str(result)]) == 0

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-cli-stage-import.json").read_text(
            encoding="utf-8"
        )
    )
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "blocked",
        "running",
    ]
    assert snapshot["current_stage_id"] == "S7"
    assert snapshot["goal_stage_results"][0]["result_path"] == str(result)
    assert snapshot["production_evidence"][0]["source_authority"] == (
        "goal_stage_harness"
    )
    assert snapshot["production_evidence"][0]["status"] == "blocked"


def test_overnight_supervisor_cli_records_self_review_and_blocked_fallback(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    common = [
        "--run-id",
        "overnight-review-fallback",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S6=fresh GitHub truth",
        "--stage",
        "S7=TUI proof cockpit",
    ]

    assert main([*common, "start-stage", "S6"]) == 0
    assert (
        main(
            [
                *common,
                "--resume",
                "self-review",
                "S6",
                "--summary",
                "reviewed current GitHub truth boundary",
                "--finding",
                "review truth is not merge truth",
                "--decision",
                "continue",
                "--minutes-since-previous-review",
                "48",
                "--command",
                "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q",
                "--test-result",
                "self-review CLI covered",
                "--source-ref",
                "goal:stage:S6",
                "--target-ref",
                "artifact://overnight-supervisor/overnight-review-fallback",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                *common,
                "--resume",
                "blocked-fallback",
                "S6",
                "--reason",
                "GitHub review truth is configured but unavailable.",
                "--failure-class",
                "github_review_truth_unavailable",
                "--attempted-command",
                "gh api repos/iiyazu/Cross-Muse/pulls/43/reviews",
                "--next-action",
                "continue to independent TUI proof cockpit work",
                "--source-ref",
                "github://iiyazu/Cross-Muse/pull/43",
                "--target-ref",
                "artifact://github-truth/pr-43",
            ]
        )
        == 0
    )

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-review-fallback.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["self_reviews"][0]["decision"] == "continue"
    assert snapshot["self_reviews"][0]["slo_status"] == "ok"
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "blocked",
        "running",
    ]
    assert snapshot["current_stage_id"] == "S7"
    assert snapshot["production_evidence"][0]["action"] == "self_review"
    assert snapshot["production_evidence"][1]["action"] == "blocked_fallback"


def test_overnight_supervisor_cli_simulates_virtual_soak_with_failure_json(
    tmp_path: Path,
) -> None:
    from xmuse.overnight_operator_supervisor import main

    common = [
        "--run-id",
        "overnight-cli-virtual",
        "--artifact-dir",
        str(tmp_path),
        "--stage",
        "S4=live gates",
        "--stage",
        "S5=docs and validation",
    ]

    assert (
        main(
            [
                *common,
                "simulate",
                "--total-minutes",
                "120",
                "--heartbeat-interval-minutes",
                "15",
                "--self-review-interval-minutes",
                "60",
                "--checkpoint-interval-minutes",
                "60",
                "--failure-json",
                json.dumps(
                    {
                        "minute": 45,
                        "stage_id": "S4",
                        "reason": "MemoryOS live trace is configured but unavailable.",
                        "failure_class": "memoryos_live_trace_unavailable",
                        "attempted_command": "uv run xmuse-memoryos-live-trace-capture",
                        "source_refs": ["memoryos://live-trace"],
                    }
                ),
            ]
        )
        == 0
    )

    snapshot = json.loads(
        (tmp_path / "overnight-supervisor-overnight-cli-virtual.json").read_text(
            encoding="utf-8"
        )
    )
    assert [stage["status"] for stage in snapshot["stages"]] == [
        "blocked",
        "running",
    ]
    assert snapshot["current_stage_id"] == "S5"
    assert snapshot["heartbeats"][-1]["logical_minute"] == 120
    assert snapshot["self_reviews"][-1]["logical_minute"] == 120
    assert snapshot["checkpoints"][-1]["logical_minute"] == 120
    assert snapshot["issue_queue"][0]["title"] == (
        "MemoryOS live trace is configured but unavailable."
    )


def test_overnight_supervisor_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-overnight-supervisor"]
        == "xmuse.overnight_operator_supervisor:main"
    )


def _write_goal_stage_runner_result(
    path: Path,
    *,
    stage_id: str,
    status: str,
    engine: str,
    command: list[str],
    issues: list[dict[str, str]] | None = None,
    attempt: int = 1,
) -> None:
    evidence_dir = path.parent / f"{path.name}.evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage_id": stage_id,
        "status": status,
        "engine": engine,
        "issues": issues or [],
        "review_decision": "pass" if status == "ok" else status,
        "retry_hint": None if status == "ok" else "Resolve blocked stage result.",
        "evidence_dir": str(evidence_dir),
        "agent_output_path": str(path),
        "command": command,
        "agent_stdout_path": str(evidence_dir / "engine_output.txt"),
        "returncode": 0 if status == "ok" else 2,
        "attempt": attempt,
        "timestamp_utc": "2026-06-12T00:00:00Z",
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (path.parent / f"{path.name}.prompt.txt").write_text(
        f"Stage: {stage_id}\n",
        encoding="utf-8",
    )
    (path.parent / f"{path.name}.manifest.jsonl").write_text(
        json.dumps({"stage_id": stage_id, "status": status}) + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "engine_output.txt").write_text(
        "bounded worker output\n",
        encoding="utf-8",
    )


def _write_lane_recovery_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
    decision: str,
    retry_allowed: bool,
) -> Path:
    path = lane_recovery_artifact_path(
        base_dir,
        graph_id=graph_id,
        lane_id=lane_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.god_room_lane_recovery.v1",
                "decision": {
                    "lane_id": lane_id,
                    "decision": decision,
                    "retry_allowed": retry_allowed,
                    "failure_class": "demo_grade_boundary",
                    "attempt": 2,
                    "refactor_required_reason": (
                        "same path failed repeatedly"
                        if decision == "refactor_required"
                        else None
                    ),
                    "next_action": (
                        "refactor or replace the failing lane boundary before retrying"
                    ),
                    "source_refs": ["pytest:overnight-supervisor-recovery-gate"],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
