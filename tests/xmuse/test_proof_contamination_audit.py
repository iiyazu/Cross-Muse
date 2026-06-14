from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.proof_contamination_audit import (
    capture_proof_contamination_audit,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _gate(
    *,
    gate_id: str,
    kind: str,
    proof_level: str,
    status: str = "ok",
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


def test_proof_contamination_audit_accepts_clean_release_gates(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "audit.json"
    _write_json(
        artifacts / "local-validation.json",
        _gate(
            gate_id="local-validation",
            kind="local_validation",
            proof_level="contract_proof",
        ),
    )
    _write_json(
        artifacts / "github-server-truth.json",
        _gate(
            gate_id="github-server-truth",
            kind="github_server_truth",
            proof_level="server_side_enforcement_proof",
            source_refs=["github:pr:43", "github:branch:main"],
        ),
    )
    _write_json(
        artifacts / "live-memoryos.json",
        _gate(
            gate_id="live-memoryos",
            kind="live_memoryos",
            proof_level="live_service_proof",
            source_refs=[
                "memoryos:namespace:memory://conversation/conv-1",
                "memoryos:session:ses-1",
            ],
        ),
    )
    _write_json(
        artifacts / "real-provider-runtime.json",
        _gate(
            gate_id="real-provider-runtime",
            kind="real_provider",
            proof_level="real_provider_proof",
            source_refs=["provider:codex", "provider_session:thread-1"],
        ),
    )

    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts,
        output_path=output,
    )

    assert output.exists()
    assert audit["schema_version"] == "xmuse.proof_contamination_audit.v1"
    assert audit["decision"] == "clean"
    assert audit["finding_count"] == 0
    assert audit["findings"] == []


def test_proof_contamination_audit_flags_weak_live_gate_proof(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_json(
        artifacts / "live-memoryos.json",
        _gate(
            gate_id="live-memoryos",
            kind="live_memoryos",
            proof_level="contract_proof",
            source_refs=["fixture:memoryos-trace"],
        ),
    )

    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts,
        output_path=tmp_path / "audit.json",
    )

    assert audit["decision"] == "contaminated"
    assert audit["findings"][0]["gate_id"] == "live-memoryos"
    assert audit["findings"][0]["code"] == "weak_proof_for_production_gate"
    assert "requires live_service_proof" in audit["findings"][0]["summary"]


def test_proof_contamination_audit_flags_fake_marker_in_real_proof(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_json(
        artifacts / "real-provider-runtime.json",
        _gate(
            gate_id="real-provider-runtime",
            kind="real_provider",
            proof_level="real_provider_proof",
            summary="fake-provider-app-server emitted stdout_fallback trace",
            source_refs=["provider:codex", "transport:stdout_fallback"],
        ),
    )

    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts,
        output_path=tmp_path / "audit.json",
    )

    assert audit["decision"] == "contaminated"
    assert audit["findings"][0]["gate_id"] == "real-provider-runtime"
    assert audit["findings"][0]["code"] == "fake_marker_in_production_proof"
    assert "fake/local/stdout" in audit["findings"][0]["summary"]


def test_proof_contamination_audit_flags_pr_merged_without_merge_proof(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_json(
        artifacts / "github-merge-truth.json",
        _gate(
            gate_id="github-merge-truth",
            kind="github_merge_truth",
            proof_level="server_side_enforcement_proof",
            summary="fact_state=pr_merged but only enforcement was captured",
            source_refs=["github:pr:43"],
            can_emit_pr_merged=False,
        ),
    )

    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts,
        output_path=tmp_path / "audit.json",
    )

    codes = {finding["code"] for finding in audit["findings"]}
    assert audit["decision"] == "contaminated"
    assert "weak_proof_for_production_gate" in codes
    assert "pr_merged_without_merge_truth" in codes


def test_proof_contamination_audit_reports_not_evaluated_without_artifacts(
    tmp_path: Path,
) -> None:
    audit = capture_proof_contamination_audit(
        artifacts_dir=tmp_path / "missing",
        output_path=tmp_path / "audit.json",
    )

    assert audit["decision"] == "not_evaluated"
    assert audit["artifact_count"] == 0
    assert audit["findings"] == []


def test_proof_contamination_audit_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-proof-contamination-audit"]
        == "xmuse.proof_contamination_audit:main"
    )
