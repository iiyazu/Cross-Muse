from __future__ import annotations

import json
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
