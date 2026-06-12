from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.internal_review_release_gate import (
    capture_internal_review_release_gate,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_internal_review_gate_accepts_verified_approved_artifact(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "internal-review.json"
    gate_output = tmp_path / "gates" / "internal-review.json"
    _write_json(
        artifact,
        {
            "schema_version": "xmuse.internal_review.v1",
            "review_id": "review-pr43-4cbed89",
            "reviewer": "codex-reviewer",
            "reviewed_head_sha": "4cbed89",
            "decision": "approved",
            "summary": "No blocking findings.",
            "findings": [
                {"severity": "minor", "status": "open", "summary": "Doc polish"}
            ],
            "source_refs": ["github:pr:43"],
        },
    )

    gate = capture_internal_review_release_gate(
        artifact_path=artifact,
        output_path=gate_output,
        expected_head_sha="4cbed89",
    )

    assert gate_output.exists()
    assert gate["schema_version"] == "xmuse.production_evidence.v1"
    assert gate["gate_id"] == "internal-review"
    assert gate["kind"] == "internal_review"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "internal_review_proof"
    assert gate["source_refs"] == ["github:pr:43", "internal_review:review-pr43-4cbed89"]
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "gates",
        output_path=tmp_path / "release-readiness.json",
    )
    assert report["decision"] == "ready"


def test_internal_review_gate_blocks_head_sha_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "internal-review.json"
    _write_json(
        artifact,
        {
            "schema_version": "xmuse.internal_review.v1",
            "review_id": "review-pr43-old",
            "reviewer": "codex-reviewer",
            "reviewed_head_sha": "old-head",
            "decision": "approved",
            "summary": "No blocking findings.",
        },
    )

    gate = capture_internal_review_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
        expected_head_sha="new-head",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "reviewed_head_sha mismatch" in gate["summary"]


def test_internal_review_gate_blocks_open_important_findings(tmp_path: Path) -> None:
    artifact = tmp_path / "internal-review.json"
    _write_json(
        artifact,
        {
            "schema_version": "xmuse.internal_review.v1",
            "review_id": "review-pr43-findings",
            "reviewer": "codex-reviewer",
            "reviewed_head_sha": "4cbed89",
            "decision": "approved",
            "summary": "Important finding remains open.",
            "findings": [
                {
                    "severity": "important",
                    "status": "open",
                    "summary": "Release gate accepts stale proof.",
                }
            ],
        },
    )

    gate = capture_internal_review_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
        expected_head_sha="4cbed89",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "open blocking review findings" in gate["summary"]


def test_internal_review_gate_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-internal-review-gate-capture"]
        == "xmuse.internal_review_gate_capture:main"
    )
