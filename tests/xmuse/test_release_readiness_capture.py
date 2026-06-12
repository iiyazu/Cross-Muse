from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_capture_release_readiness_blocks_fake_live_proof_and_redacts_tokens(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "readiness" / "release-readiness.json"
    _write_json(
        artifacts / "memoryos-live.json",
        {
            "schema_version": "xmuse.production_evidence.v1",
            "gate_id": "memoryos-live",
            "release_gate_kind": "live_memoryos",
            "configured": True,
            "required": True,
            "status": "ok",
            "proof_level": "fake_runtime_proof",
            "owner": "operator",
            "summary": "fixture trace was captured",
            "commands": [
                "XMUSE_MEMORYOS_LITE_TOKEN=secret-token uv run python capture.py "
                "--api-key sk-live"
            ],
            "artifacts": ["memory://conversation/secret-token/trace"],
            "next_action": "Run the live MemoryOS Lite trace capture.",
        },
    )
    _write_json(
        artifacts / "tests.json",
        {
            "gate_id": "local-validation",
            "kind": "local_validation",
            "configured": True,
            "required": True,
            "status": "ok",
            "proof_level": "contract_proof",
            "owner": "codex",
            "summary": "focused tests passed",
            "attempted_command": "uv run pytest tests/xmuse/test_release_readiness.py -q",
        },
    )

    report = capture_release_readiness(artifacts_dir=artifacts, output_path=output)

    assert output.exists()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == report
    assert report["schema_version"] == "xmuse.release_readiness_report.v1"
    assert report["decision"] == "blocked"
    assert report["blockers"][0]["gate_id"] == "memoryos-live"
    assert "requires live_service_proof" in report["blockers"][0]["reason"]
    rendered = json.dumps(report, sort_keys=True)
    assert "secret-token" not in rendered
    assert "sk-live" not in rendered
    assert "<redacted>" in rendered


def test_capture_release_readiness_reports_not_evaluated_without_artifacts(
    tmp_path: Path,
) -> None:
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "missing",
        output_path=tmp_path / "release-readiness.json",
    )

    assert report["decision"] == "not_evaluated"
    assert report["gates"] == []
    assert report["blockers"] == []
    assert report["artifact_count"] == 0


def test_capture_release_readiness_deduplicates_gate_id_with_stronger_proof(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "release-readiness.json"
    _write_json(
        artifacts / "live_gate_status" / "github-server-truth-status.json",
        {
            "gate_id": "github-server-truth",
            "kind": "github_server_truth",
            "configured": True,
            "required": True,
            "status": "blocked",
            "proof_level": "manual_gap",
            "owner": "operator",
            "summary": "GitHub auth is available, but server truth was not captured.",
        },
    )
    _write_json(
        artifacts / "github-server-truth.json",
        {
            "gate_id": "github-server-truth",
            "kind": "github_server_truth",
            "configured": True,
            "required": True,
            "status": "ok",
            "proof_level": "server_side_enforcement_proof",
            "owner": "github",
            "summary": "Branch protection and required checks were captured.",
            "source_refs": ["github:pr:43", "github:branch:main"],
        },
    )

    report = capture_release_readiness(artifacts_dir=artifacts, output_path=output)

    assert report["decision"] == "ready"
    assert report["artifact_count"] == 1
    assert report["blockers"] == []
    assert report["gates"][0]["gate_id"] == "github-server-truth"
    assert report["gates"][0]["proof_level"] == "server_side_enforcement_proof"


def test_release_readiness_capture_cli_writes_report(tmp_path: Path) -> None:
    from xmuse.release_readiness_capture import main

    artifacts = tmp_path / "artifacts"
    output = tmp_path / "release-readiness.json"
    _write_json(
        artifacts / "provider.json",
        {
            "gate_id": "provider-soak",
            "kind": "real_provider",
            "configured": True,
            "required": True,
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "owner": "operator",
            "summary": "Ray/Codex runtime was not started.",
            "next_action": "Start the configured production bundle.",
        },
    )

    assert main(["--artifacts-dir", str(artifacts), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "blocked"
    assert report["blockers"][0]["gate_id"] == "provider-soak"


def test_release_readiness_capture_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-release-readiness-capture"]
        == "xmuse.release_readiness_capture:main"
    )
