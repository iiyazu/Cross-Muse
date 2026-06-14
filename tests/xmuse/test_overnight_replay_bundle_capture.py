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


def test_capture_overnight_replay_bundle_preserves_memoryos_trace_details(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_gate(
        artifacts / "live-memoryos.json",
        gate_id="live-memoryos",
        kind="live_memoryos",
        status="ok",
        proof_level="live_service_proof",
        summary="MemoryOS Lite live trace captured.",
        source_refs=["conversation:conv-live", "memoryos:session:ses-live-1"],
        artifacts=["memoryos-trace.json"],
        details={
            "memoryos_trace": {
                "authority": "memoryos_live_release_gate",
                "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
                "session_id": "ses-live-1",
                "trace_event_count": 3,
                "event_kinds": ["session_created", "ingest", "context_built"],
                "estimated_tokens": 96,
                "source_ref_count": 5,
                "blocker_count": 0,
                "live_service_proof": True,
            }
        },
    )

    bundle = capture_overnight_replay_bundle(
        run_id="overnight-memoryos-trace",
        artifacts_dir=artifacts,
        output_path=tmp_path / "bundle.json",
    )

    sections = {section["section_id"]: section for section in bundle["sections"]}
    assert sections["memoryos_trace"]["details"] == {
        "memoryos_trace": {
            "authority": "memoryos_live_release_gate",
            "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
            "session_id": "ses-live-1",
            "trace_event_count": 3,
            "event_kinds": ["session_created", "ingest", "context_built"],
            "estimated_tokens": 96,
            "source_ref_count": 5,
            "blocker_count": 0,
            "live_service_proof": True,
        }
    }


def test_capture_overnight_replay_bundle_preserves_natural_transcript_details(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    _write_gate(
        artifacts / "natural-deliberation.json",
        gate_id="natural-god-deliberation",
        kind="natural_deliberation",
        status="ok",
        proof_level="real_provider_proof",
        summary="Natural GOD deliberation transcript captured.",
        source_refs=["conversation:conv-prod-1", "god:architect-god"],
        artifacts=["natural-transcript.json", "god-runtime.json"],
        details={
            "deliberation_transcript": {
                "authority": "natural_deliberation_release_gate",
                "conversation_id": "conv-prod-1",
                "message_count": 2,
                "distinct_god_count": 2,
                "god_ids": ["architect-god", "review-god"],
                "speech_act_counts": {"propose": 1, "vote": 1},
                "natural_deliberation": True,
                "real_provider_proof": True,
                "runtime_required": True,
                "runtime_artifact_attached": True,
                "runtime_peer_god_ready_count": 2,
                "runtime_blocked_count": 0,
                "missing_provider_session_god_ids": [],
                "blocker_count": 0,
            }
        },
    )

    bundle = capture_overnight_replay_bundle(
        run_id="overnight-natural-deliberation",
        artifacts_dir=artifacts,
        output_path=tmp_path / "bundle.json",
    )

    sections = {section["section_id"]: section for section in bundle["sections"]}
    assert sections["deliberation_transcript"]["details"] == {
        "deliberation_transcript": {
            "authority": "natural_deliberation_release_gate",
            "conversation_id": "conv-prod-1",
            "message_count": 2,
            "distinct_god_count": 2,
            "god_ids": ["architect-god", "review-god"],
            "speech_act_counts": {"propose": 1, "vote": 1},
            "natural_deliberation": True,
            "real_provider_proof": True,
            "runtime_required": True,
            "runtime_artifact_attached": True,
            "runtime_peer_god_ready_count": 2,
            "runtime_blocked_count": 0,
            "missing_provider_session_god_ids": [],
            "blocker_count": 0,
        }
    }


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


def test_capture_overnight_replay_bundle_accepts_stage_evidence_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    stage_evidence = tmp_path / "stage-evidence.json"
    _write_production_evidence(
        stage_evidence,
        stage_id="S1",
        action="goal_stage_results_indexed",
        status="ok",
        proof_level="contract_proof",
        source_authority="goal_stage_harness",
        source_refs=["goal_run:overnight-stage-run", "goal_stage:S1"],
        summary="Goal stage harness indexed 1 result(s): ok=1.",
    )

    bundle = capture_overnight_replay_bundle(
        run_id="overnight-with-stage-evidence",
        artifacts_dir=artifacts,
        output_path=tmp_path / "bundle.json",
        section_artifacts={"stage_evidence": stage_evidence},
    )

    sections = {section["section_id"]: section for section in bundle["sections"]}
    assert "stage_evidence" in REQUIRED_REPLAY_SECTIONS
    assert sections["stage_evidence"]["status"] == "ok"
    assert sections["stage_evidence"]["source_authority"] == "goal_stage_harness"
    assert sections["stage_evidence"]["source_refs"] == [
        "goal_run:overnight-stage-run",
        "goal_stage:S1",
    ]
    assert str(stage_evidence) in sections["stage_evidence"]["artifacts"]


def test_capture_overnight_replay_bundle_accepts_runtime_closure_section(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    closure = tmp_path / "god-room-runtime-closure.json"
    _write_production_evidence(
        closure,
        stage_id="S8",
        action="god_room_runtime_closure_indexed",
        status="ok",
        proof_level="contract_proof",
        source_authority="god_room_runtime_closure_contract",
        source_refs=["god-room-event:evt-freeze", "blueprint:bp-runtime:1"],
        summary="GOD room runtime closure evidence indexed.",
        details={
            "room_replay": {"status": "ok", "event_count": 2},
            "github_truth": {"merged": False, "can_emit_pr_merged": False},
        },
    )

    bundle = capture_overnight_replay_bundle(
        run_id="overnight-with-runtime-closure",
        artifacts_dir=artifacts,
        output_path=tmp_path / "bundle.json",
        section_artifacts={"god_room_runtime_closure": closure},
    )

    section_ids = [section["section_id"] for section in bundle["sections"]]
    sections = {section["section_id"]: section for section in bundle["sections"]}
    assert section_ids[-1] == "god_room_runtime_closure"
    assert "god_room_runtime_closure" not in REQUIRED_REPLAY_SECTIONS
    assert sections["god_room_runtime_closure"]["status"] == "ok"
    assert sections["god_room_runtime_closure"]["source_authority"] == (
        "god_room_runtime_closure_contract"
    )
    assert sections["god_room_runtime_closure"]["details"] == {
        "god_room_runtime_closure": {
            "room_replay": {"status": "ok", "event_count": 2},
            "github_truth": {"merged": False, "can_emit_pr_merged": False},
        }
    }


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
    details: dict[str, object] | None = None,
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
    if details is not None:
        payload.update(details)
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
    details: dict[str, object] | None = None,
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
    if details is not None:
        payload["god_room_runtime_closure"] = details
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
