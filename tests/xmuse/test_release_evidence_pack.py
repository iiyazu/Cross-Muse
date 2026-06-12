from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
)
from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_section_evidence(
    path: Path,
    *,
    section_id: str,
    status: str,
    proof_level: str,
    source_authority: str,
    source_refs: list[str],
    summary: str,
) -> None:
    _write_json(
        path,
        {
            "schema_version": "xmuse.production_evidence.v1",
            "stage_id": "S4",
            "action": f"{section_id}_evidence",
            "status": status,
            "proof_level": proof_level,
            "source_authority": source_authority,
            "source_refs": source_refs,
            "target_refs": [],
            "commands": [],
            "test_results": [],
            "artifacts": [],
            "blocked_reason": None,
            "owner": "codex",
            "next_action": None,
            "summary": summary,
        },
    )


def _write_supervisor_snapshot(tmp_path: Path, *, run_id: str) -> Path:
    supervisor = OvernightSupervisor(
        OvernightSupervisorConfig(
            run_id=run_id,
            artifact_dir=tmp_path,
            stages=[
                OvernightSupervisorStage(
                    stage_id="S4",
                    objective="supervise overnight closure",
                )
            ],
        )
    )
    supervisor.start_stage("S4")
    supervisor.record_heartbeat(note="supervisor running")
    supervisor.record_checkpoint(
        stage_id="S4",
        summary="supervisor checkpoint captured",
        validation=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        commands=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
        source_refs=["goal:stage:S4"],
    )
    return tmp_path / f"overnight-supervisor-{run_id}.json"


def _gate(
    *,
    gate_id: str,
    kind: str,
    status: str,
    proof_level: str,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": gate_id,
        "kind": kind,
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "operator",
        "summary": f"{gate_id} evidence",
        "source_refs": [f"{kind}:source"],
        "artifacts": [f"/tmp/{gate_id}.json"],
    }
    payload.update(overrides)
    return payload


def test_release_evidence_pack_writes_readiness_audit_and_summary(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    supervisor = tmp_path / "supervisor-production-evidence.json"
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
            source_refs=["github:pr:43", "github:branch:main"],
        ),
    )
    _write_json(
        artifacts / "real-provider-runtime.json",
        _gate(
            gate_id="real-provider-runtime",
            kind="real_provider",
            status="manual_gap",
            proof_level="manual_gap",
            summary="Ray/Codex runtime was not started.",
            next_action="Start the configured production provider bundle.",
        ),
    )
    _write_section_evidence(
        supervisor,
        section_id="supervisor",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor heartbeat and checkpoint captured.",
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="overnight-pack-test",
        section_artifacts={"supervisor": supervisor},
    )

    readiness_output = output.parent / "release-readiness.json"
    audit_output = output.parent / "proof-contamination-audit.json"
    replay_output = output.parent / "overnight-replay-bundle.json"
    assert output.exists()
    assert readiness_output.exists()
    assert audit_output.exists()
    assert replay_output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == pack
    assert pack["schema_version"] == "xmuse.release_evidence_pack.v1"
    assert pack["decision"] == "blocked"
    assert pack["release_readiness_decision"] == "blocked"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["overnight_replay_decision"] == "blocked"
    assert pack["overnight_replay_authority"] == "replay_index_only"
    assert pack["artifact_count"] == 2
    assert pack["blocker_count"] == 1
    assert pack["replay_blocker_count"] >= 1
    assert pack["finding_count"] == 0
    assert pack["readiness_report"] == str(readiness_output)
    assert pack["proof_contamination_audit"] == str(audit_output)
    assert pack["overnight_replay_bundle"] == str(replay_output)
    assert pack["blockers"][0]["gate_id"] == "real-provider-runtime"
    assert pack["source_reports"] == {
        "release_readiness": str(readiness_output),
        "proof_contamination_audit": str(audit_output),
        "overnight_replay_bundle": str(replay_output),
    }
    replay = json.loads(replay_output.read_text(encoding="utf-8"))
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert replay["run_id"] == "overnight-pack-test"
    assert replay["authority"] == "replay_index_only"
    assert sections["supervisor"]["status"] == "ok"
    assert sections["supervisor"]["source_authority"] == "overnight_operator_supervisor"


def test_release_evidence_pack_converts_supervisor_snapshot_into_replay_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack" / "evidence-pack.json"
    snapshot = _write_supervisor_snapshot(tmp_path / "supervisor", run_id="pack-supervisor")
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=output,
        run_id="pack-supervisor",
        supervisor_snapshot=snapshot,
    )

    supervisor_evidence = output.parent / "supervisor-production-evidence.json"
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert supervisor_evidence.exists()
    assert pack["source_reports"]["overnight_supervisor_evidence"] == str(
        supervisor_evidence
    )
    assert sections["supervisor"]["status"] == "ok"
    assert sections["supervisor"]["source_authority"] == "overnight_operator_supervisor"
    assert sections["supervisor"]["artifacts"][0] == str(snapshot)


def test_release_evidence_pack_rejects_ambiguous_supervisor_sources(
    tmp_path: Path,
) -> None:
    supervisor = tmp_path / "supervisor-production-evidence.json"
    snapshot = _write_supervisor_snapshot(
        tmp_path / "supervisor",
        run_id="ambiguous-supervisor",
    )
    _write_section_evidence(
        supervisor,
        section_id="supervisor",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor captured.",
    )

    try:
        capture_release_evidence_pack(
            artifacts_dir=tmp_path / "artifacts",
            output_path=tmp_path / "pack.json",
            supervisor_snapshot=snapshot,
            section_artifacts={"supervisor": supervisor},
        )
    except ValueError as exc:
        assert "supervisor evidence source is ambiguous" in str(exc)
    else:
        raise AssertionError("expected ambiguous supervisor source to be rejected")


def test_release_evidence_pack_marks_contaminated_audit_as_terminal(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_json(
        artifacts / "real-provider-runtime.json",
        _gate(
            gate_id="real-provider-runtime",
            kind="real_provider",
            status="ok",
            proof_level="real_provider_proof",
            summary="fake provider emitted stdout_fallback trace",
            source_refs=["provider:codex", "transport:stdout_fallback"],
        ),
    )

    pack = capture_release_evidence_pack(
        artifacts_dir=artifacts,
        output_path=tmp_path / "evidence-pack.json",
    )

    assert pack["decision"] == "contaminated"
    assert pack["release_readiness_decision"] == "ready"
    assert pack["proof_contamination_decision"] == "contaminated"
    assert pack["finding_count"] == 1
    assert pack["findings"][0]["code"] == "fake_marker_in_production_proof"


def test_release_evidence_pack_reports_not_evaluated_without_artifacts(
    tmp_path: Path,
) -> None:
    pack = capture_release_evidence_pack(
        artifacts_dir=tmp_path / "missing",
        output_path=tmp_path / "evidence-pack.json",
    )

    assert pack["decision"] == "not_evaluated"
    assert pack["artifact_count"] == 0
    assert pack["blockers"] == []
    assert pack["findings"] == []


def test_release_evidence_pack_cli_writes_pack(tmp_path: Path) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    _write_json(
        artifacts / "provider.json",
        _gate(
            gate_id="provider-soak",
            kind="real_provider",
            status="manual_gap",
            proof_level="manual_gap",
            summary="Provider soak was not supplied.",
        ),
    )

    assert main(["--artifacts-dir", str(artifacts), "--output", str(output)]) == 0
    pack = json.loads(output.read_text(encoding="utf-8"))
    assert pack["decision"] == "blocked"
    assert pack["blocker_count"] == 1
    assert pack["overnight_replay_bundle"] == str(
        output.parent / "overnight-replay-bundle.json"
    )


def test_release_evidence_pack_cli_accepts_replay_section_artifacts(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    supervisor = tmp_path / "supervisor.json"
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )
    _write_section_evidence(
        supervisor,
        section_id="supervisor",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor captured.",
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--section-artifact",
                f"supervisor={supervisor}",
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["overnight_replay_decision"] == "blocked"
    assert replay["run_id"] == "overnight-cli-pack"
    assert sections["supervisor"]["status"] == "ok"


def test_release_evidence_pack_cli_accepts_supervisor_snapshot(
    tmp_path: Path,
) -> None:
    from xmuse.release_evidence_pack import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "pack.json"
    snapshot = _write_supervisor_snapshot(
        tmp_path / "supervisor",
        run_id="overnight-cli-pack",
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
        ),
    )

    assert (
        main(
            [
                "--artifacts-dir",
                str(artifacts),
                "--output",
                str(output),
                "--run-id",
                "overnight-cli-pack",
                "--supervisor-snapshot",
                str(snapshot),
            ]
        )
        == 0
    )

    pack = json.loads(output.read_text(encoding="utf-8"))
    replay = json.loads(
        (output.parent / "overnight-replay-bundle.json").read_text(encoding="utf-8")
    )
    sections = {section["section_id"]: section for section in replay["sections"]}
    assert pack["source_reports"]["overnight_supervisor_evidence"] == str(
        output.parent / "supervisor-production-evidence.json"
    )
    assert sections["supervisor"]["status"] == "ok"


def test_release_evidence_pack_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-release-evidence-pack"]
        == "xmuse.release_evidence_pack:main"
    )
