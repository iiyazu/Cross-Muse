from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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

    pack = capture_release_evidence_pack(artifacts_dir=artifacts, output_path=output)

    readiness_output = output.parent / "release-readiness.json"
    audit_output = output.parent / "proof-contamination-audit.json"
    assert output.exists()
    assert readiness_output.exists()
    assert audit_output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == pack
    assert pack["schema_version"] == "xmuse.release_evidence_pack.v1"
    assert pack["decision"] == "blocked"
    assert pack["release_readiness_decision"] == "blocked"
    assert pack["proof_contamination_decision"] == "clean"
    assert pack["artifact_count"] == 2
    assert pack["blocker_count"] == 1
    assert pack["finding_count"] == 0
    assert pack["readiness_report"] == str(readiness_output)
    assert pack["proof_contamination_audit"] == str(audit_output)
    assert pack["blockers"][0]["gate_id"] == "real-provider-runtime"


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


def test_release_evidence_pack_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-release-evidence-pack"]
        == "xmuse.release_evidence_pack:main"
    )
