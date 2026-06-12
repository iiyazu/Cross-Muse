from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
)
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)
from xmuse_core.platform.overnight_supervisor_evidence_capture import (
    capture_overnight_supervisor_evidence,
)


def test_capture_overnight_supervisor_evidence_exports_replay_ready_artifact(
    tmp_path: Path,
) -> None:
    config = OvernightSupervisorConfig(
        run_id="overnight-supervised",
        artifact_dir=tmp_path,
        stages=[
            OvernightSupervisorStage(stage_id="S3", objective="supervise goal loop"),
            OvernightSupervisorStage(stage_id="S4", objective="live soak gates"),
        ],
    )
    supervisor = OvernightSupervisor(config)
    supervisor.start_stage("S3")
    supervisor.record_heartbeat(note="S3 running")
    supervisor.record_checkpoint(
        stage_id="S3",
        summary="supervisor checkpoint captured",
        validation=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        commands=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        source_refs=["goal:stage:S3"],
    )
    supervisor.start_stage("S4")
    supervisor.manual_gap(
        stage_id="S4",
        reason="MemoryOS Lite live gate is not configured",
        attempted_command="uv run xmuse-memoryos-live-gate-capture",
        next_action="Configure MemoryOS Lite and rerun the live trace gate.",
    )

    output = tmp_path / "supervisor-production-evidence.json"
    artifact = capture_overnight_supervisor_evidence(
        snapshot_path=tmp_path / "overnight-supervisor-overnight-supervised.json",
        output_path=output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == artifact
    assert artifact["schema_version"] == "xmuse.production_evidence.v1"
    assert artifact["run_id"] == "overnight-supervised"
    assert artifact["stage_id"] == "S3"
    assert artifact["action"] == "overnight_supervisor_checkpoint"
    assert artifact["status"] == "ok"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["source_authority"] == "overnight_operator_supervisor"
    assert artifact["source_refs"] == [
        "overnight_supervisor:overnight-supervised",
        "goal:stage:S3",
        "goal:stage:S4",
    ]
    assert artifact["commands"] == [
        "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q",
        "uv run xmuse-memoryos-live-gate-capture",
    ]
    assert artifact["test_results"] == [
        "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"
    ]
    assert str(tmp_path / "overnight-supervisor-overnight-supervised.json") in artifact[
        "artifacts"
    ]
    assert str(tmp_path / "manual-gap-S4.json") in artifact["artifacts"]
    assert artifact["blocked_reason"] is None
    assert artifact["next_action"] is None

    replay_bundle = capture_overnight_replay_bundle(
        run_id="overnight-supervised",
        artifacts_dir=tmp_path / "empty-release-gates",
        output_path=tmp_path / "bundle.json",
        section_artifacts={"supervisor": output},
    )
    sections = {section["section_id"]: section for section in replay_bundle["sections"]}
    assert sections["supervisor"]["status"] == "ok"
    assert sections["supervisor"]["proof_level"] == "contract_proof"
    assert sections["supervisor"]["source_authority"] == "overnight_operator_supervisor"


def test_capture_overnight_supervisor_evidence_reports_manual_gap_without_checkpoint(
    tmp_path: Path,
) -> None:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="overnight-unsupervised",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S3", objective="supervise goal loop"),
            ],
        )
    )
    supervisor.start_stage("S3")

    artifact = capture_overnight_supervisor_evidence(
        snapshot_path=tmp_path / "overnight-supervisor-overnight-unsupervised.json",
        output_path=tmp_path / "supervisor-production-evidence.json",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["blocked_reason"] == (
        "overnight supervisor snapshot has no checkpoint evidence"
    )
    assert artifact["next_action"] == (
        "Record a supervisor checkpoint and regenerate supervisor replay evidence."
    )


def test_capture_overnight_supervisor_evidence_cli_writes_artifact(tmp_path: Path) -> None:
    from xmuse.overnight_supervisor_evidence_capture import main

    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id="overnight-cli",
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(stage_id="S3", objective="supervise goal loop"),
            ],
        )
    )
    supervisor.start_stage("S3")
    supervisor.record_heartbeat(note="cli heartbeat")
    supervisor.record_checkpoint(stage_id="S3", summary="cli checkpoint")
    output = tmp_path / "supervisor-production-evidence.json"

    assert (
        main(
            [
                "--snapshot",
                str(tmp_path / "overnight-supervisor-overnight-cli.json"),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "ok"
    assert artifact["action"] == "overnight_supervisor_checkpoint"


def test_overnight_supervisor_evidence_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-overnight-supervisor-evidence-capture"]
        == "xmuse.overnight_supervisor_evidence_capture:main"
    )
