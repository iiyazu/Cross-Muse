from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.overnight_replay_bundle import REQUIRED_REPLAY_SECTIONS
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)


def test_capture_overnight_replay_bundle_indexes_release_gate_artifacts(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_gate(
        artifacts / "github-server-truth-status.json",
        gate_id="github-server-truth",
        kind="github_server_truth",
        status="ok",
        proof_level="server_side_enforcement_proof",
        summary="GitHub server truth captured for current head.",
        source_refs=["github:pr:43", "github:head:head-current"],
        artifacts=["github-server-truth-snapshot.json"],
    )
    _write_gate(
        artifacts / "live-memoryos-status.json",
        gate_id="live-memoryos",
        kind="live_memoryos",
        status="manual_gap",
        proof_level="manual_gap",
        summary="MemoryOS Lite live gate is not configured.",
        next_action="Configure MemoryOS Lite and rerun trace capture.",
    )
    _write_gate(
        artifacts / "natural-deliberation-status.json",
        gate_id="natural-god-deliberation",
        kind="natural_deliberation",
        status="manual_gap",
        proof_level="manual_gap",
        summary="Natural multi-GOD transcript is not configured.",
        next_action="Run a selected-GOD deliberation session.",
    )
    _write_gate(
        artifacts / "real-provider-status.json",
        gate_id="real-provider-runtime",
        kind="real_provider",
        status="manual_gap",
        proof_level="manual_gap",
        summary="Real provider runtime soak is missing.",
        next_action="Run a real provider fresh/resume soak.",
    )
    output = tmp_path / "overnight-replay-bundle.json"

    bundle = capture_overnight_replay_bundle(
        run_id="overnight-current",
        artifacts_dir=artifacts,
        output_path=output,
    )

    sections = {section["section_id"]: section for section in bundle["sections"]}
    missing_blockers = [
        blocker
        for blocker in bundle["blockers"]
        if blocker["reason"] == "required replay section is missing"
    ]

    assert bundle["schema_version"] == "xmuse.overnight_replay_bundle.v1"
    assert bundle["run_id"] == "overnight-current"
    assert bundle["authority"] == "replay_index_only"
    assert bundle["decision"] == "blocked"
    assert list(sections) == list(REQUIRED_REPLAY_SECTIONS)
    assert missing_blockers == []
    assert sections["github_truth"]["status"] == "ok"
    assert sections["github_truth"]["proof_level"] == "server_side_enforcement_proof"
    assert sections["github_truth"]["source_authority"] == "github_truth_release_gate"
    assert "github:head:head-current" in sections["github_truth"]["source_refs"]
    assert sections["memoryos_trace"]["status"] == "manual_gap"
    assert sections["memoryos_trace"]["source_authority"] == "memoryos_live_release_gate"
    assert sections["deliberation_transcript"]["status"] == "manual_gap"
    assert sections["release_readiness"]["status"] == "blocked"
    assert "live-memoryos" in sections["release_readiness"]["blocked_reason"]
    assert json.loads(output.read_text(encoding="utf-8")) == bundle


def test_capture_overnight_replay_bundle_accepts_explicit_section_artifacts(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_gate(
        artifacts / "github-server-truth-status.json",
        gate_id="github-server-truth",
        kind="github_server_truth",
        status="ok",
        proof_level="server_side_enforcement_proof",
        summary="GitHub server truth captured.",
    )
    memory_governance = tmp_path / "memory-governance.json"
    _write_production_evidence(
        memory_governance,
        stage_id="S5",
        action="memory_governance_policy_evaluated",
        status="ok",
        proof_level="contract_proof",
        source_authority="memoryos_governance_policy",
        source_refs=["memory-governance:plan:shared-review"],
        summary="MemoryOS shared promotion policy evaluated.",
    )
    supervisor = tmp_path / "supervisor.json"
    _write_production_evidence(
        supervisor,
        stage_id="S4",
        action="overnight_supervisor_checkpoint",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=["goal:stage:S4"],
        summary="Supervisor heartbeat and checkpoint captured.",
    )

    bundle = capture_overnight_replay_bundle(
        run_id="overnight-with-sections",
        artifacts_dir=artifacts,
        output_path=tmp_path / "bundle.json",
        section_artifacts={
            "memory_governance": memory_governance,
            "supervisor": supervisor,
        },
    )

    sections = {section["section_id"]: section for section in bundle["sections"]}
    assert sections["memory_governance"]["status"] == "ok"
    assert sections["memory_governance"]["source_authority"] == (
        "memoryos_governance_policy"
    )
    assert sections["memory_governance"]["source_refs"] == [
        "memory-governance:plan:shared-review"
    ]
    assert str(memory_governance) in sections["memory_governance"]["artifacts"]
    assert sections["supervisor"]["status"] == "ok"
    assert sections["supervisor"]["source_authority"] == (
        "overnight_operator_supervisor"
    )


def test_overnight_replay_bundle_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-overnight-replay-bundle-capture"]
        == "xmuse.overnight_replay_bundle_capture:main"
    )


def _write_gate(
    path: Path,
    *,
    gate_id: str,
    kind: str,
    status: str,
    proof_level: str,
    summary: str,
    source_refs: list[str] | None = None,
    artifacts: list[str] | None = None,
    next_action: str | None = None,
) -> None:
    payload = {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": gate_id,
        "kind": kind,
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "operator",
        "summary": summary,
        "attempted_command": "uv run xmuse-live-gate-status-capture",
        "next_action": next_action,
        "source_refs": source_refs or [],
        "artifacts": artifacts or [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_production_evidence(
    path: Path,
    *,
    stage_id: str,
    action: str,
    status: str,
    proof_level: str,
    source_authority: str,
    source_refs: list[str],
    summary: str,
) -> None:
    payload = {
        "schema_version": "xmuse.production_evidence.v1",
        "stage_id": stage_id,
        "action": action,
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
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
