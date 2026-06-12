from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSimulationConfig,
    OvernightSimulationFailure,
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
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
