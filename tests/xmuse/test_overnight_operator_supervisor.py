from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.overnight_operator_supervisor import (
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


def test_overnight_supervisor_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-overnight-supervisor"]
        == "xmuse.overnight_operator_supervisor:main"
    )
