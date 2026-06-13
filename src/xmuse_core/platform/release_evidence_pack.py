from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.deliberation_transcript_evidence_capture import (
    capture_deliberation_transcript_evidence,
)
from xmuse_core.platform.feature_lineage_evidence_capture import (
    capture_feature_lineage_evidence,
)
from xmuse_core.platform.frozen_blueprint_evidence_capture import (
    capture_frozen_blueprint_evidence,
)
from xmuse_core.platform.github_truth_release_gate import (
    write_github_server_truth_release_gate,
)
from xmuse_core.platform.goal_stage_evidence_capture import capture_goal_stage_evidence
from xmuse_core.platform.god_room_runtime_closure_evidence_capture import (
    GOD_ROOM_RUNTIME_CLOSURE_SECTION,
    capture_god_room_runtime_closure_evidence,
)
from xmuse_core.platform.internal_review_release_gate import (
    capture_internal_review_release_gate,
)
from xmuse_core.platform.memoryos_governance_evidence_capture import (
    capture_memoryos_governance_evidence,
)
from xmuse_core.platform.memoryos_live_release_gate import (
    capture_memoryos_live_release_gate,
)
from xmuse_core.platform.natural_deliberation_release_gate import (
    capture_natural_deliberation_release_gate,
)
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)
from xmuse_core.platform.overnight_supervisor_evidence_capture import (
    capture_overnight_supervisor_evidence,
)
from xmuse_core.platform.proof_contamination_audit import (
    capture_proof_contamination_audit,
)
from xmuse_core.platform.real_provider_runtime_release_gate import (
    capture_real_provider_runtime_release_gate,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def capture_release_evidence_pack(
    *,
    artifacts_dir: str | Path,
    output_path: str | Path,
    run_id: str = "release-evidence-pack",
    readiness_output: str | Path | None = None,
    audit_output: str | Path | None = None,
    replay_output: str | Path | None = None,
    section_artifacts: Mapping[str, str | Path] | None = None,
    supervisor_snapshot: str | Path | None = None,
    supervisor_evidence_output: str | Path | None = None,
    deliberation_transcript: str | Path | None = None,
    god_runtime_artifact: str | Path | None = None,
    deliberation_transcript_evidence_output: str | Path | None = None,
    frozen_blueprint: str | Path | None = None,
    frozen_blueprint_evidence_output: str | Path | None = None,
    god_room_participants: str | Path | None = None,
    god_room_events: str | Path | None = None,
    god_room_blueprint_freeze: str | Path | None = None,
    god_room_lane_dag: str | Path | None = None,
    god_room_memory_trace: str | Path | None = None,
    god_room_tui_projection: str | Path | None = None,
    god_room_speaker_attempt: str | Path | None = None,
    god_room_speaker_response: str | Path | None = None,
    god_room_runtime_closure_evidence_output: str | Path | None = None,
    feature_contracts: tuple[str | Path, ...] = (),
    feature_lineage_evidence_output: str | Path | None = None,
    memoryos_governance_plans: tuple[str | Path, ...] = (),
    memoryos_writeback_events: tuple[str | Path, ...] = (),
    memoryos_governance_evidence_output: str | Path | None = None,
    memoryos_live_trace: str | Path | None = None,
    real_provider_runtime: str | Path | None = None,
    natural_deliberation_transcript: str | Path | None = None,
    natural_deliberation_god_runtime: str | Path | None = None,
    github_server_truth: str | Path | None = None,
    github_base_branch: str = "main",
    github_expected_head_sha: str | None = None,
    internal_review_artifact: str | Path | None = None,
    internal_review_expected_head_sha: str | None = None,
    production_baseline: str | Path | None = None,
    goal_stage_results: tuple[str | Path, ...] = (),
    goal_stage_evidence_output: str | Path | None = None,
    tombstoned_source_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    output = Path(output_path)
    report_dir = output.parent
    readiness_path = Path(readiness_output) if readiness_output is not None else (
        report_dir / "release-readiness.json"
    )
    audit_path = Path(audit_output) if audit_output is not None else (
        report_dir / "proof-contamination-audit.json"
    )
    replay_path = Path(replay_output) if replay_output is not None else (
        report_dir / "overnight-replay-bundle.json"
    )
    replay_section_artifacts, generated_source_reports = _replay_section_artifacts(
        report_dir=report_dir,
        section_artifacts=section_artifacts,
        supervisor_snapshot=supervisor_snapshot,
        supervisor_evidence_output=supervisor_evidence_output,
        deliberation_transcript=deliberation_transcript,
        god_runtime_artifact=god_runtime_artifact,
        deliberation_transcript_evidence_output=(
            deliberation_transcript_evidence_output
        ),
        frozen_blueprint=frozen_blueprint,
        frozen_blueprint_evidence_output=frozen_blueprint_evidence_output,
        feature_contracts=feature_contracts,
        feature_lineage_evidence_output=feature_lineage_evidence_output,
        run_id=run_id,
        memoryos_governance_plans=memoryos_governance_plans,
        memoryos_writeback_events=memoryos_writeback_events,
        memoryos_governance_evidence_output=memoryos_governance_evidence_output,
        goal_stage_results=goal_stage_results,
        goal_stage_evidence_output=goal_stage_evidence_output,
    )
    release_gate_source_reports = _release_gate_artifacts(
        artifacts_dir=Path(artifacts_dir),
        memoryos_live_trace=memoryos_live_trace,
        real_provider_runtime=real_provider_runtime,
        natural_deliberation_transcript=natural_deliberation_transcript,
        natural_deliberation_god_runtime=natural_deliberation_god_runtime,
        github_server_truth=github_server_truth,
        github_base_branch=github_base_branch,
        github_expected_head_sha=github_expected_head_sha,
        internal_review_artifact=internal_review_artifact,
        internal_review_expected_head_sha=internal_review_expected_head_sha,
    )
    real_provider_runtime_summary = _real_provider_runtime_summary(
        artifacts_dir=Path(artifacts_dir),
        source_reports=release_gate_source_reports,
    )
    github_truth_summary = _github_truth_summary(
        artifacts_dir=Path(artifacts_dir),
        source_reports=release_gate_source_reports,
    )
    baseline_summary = _production_baseline_summary(production_baseline)

    readiness = capture_release_readiness(
        artifacts_dir=artifacts_dir,
        output_path=readiness_path,
    )
    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts_dir,
        output_path=audit_path,
    )
    replay_section_artifacts, god_room_source_reports = (
        _with_god_room_runtime_closure_evidence(
            report_dir=report_dir,
            run_id=run_id,
            section_artifacts=replay_section_artifacts,
            participants_artifact=god_room_participants,
            events_artifact=god_room_events,
            blueprint_freeze_artifact=god_room_blueprint_freeze,
            lane_dag_artifact=god_room_lane_dag,
            memory_trace_artifact=god_room_memory_trace,
            tui_projection_artifact=god_room_tui_projection,
            speaker_attempt_artifact=god_room_speaker_attempt,
            speaker_response_artifact=god_room_speaker_response,
            github_truth_artifact=github_server_truth,
            release_readiness_artifact=readiness_path,
            evidence_output=god_room_runtime_closure_evidence_output,
        )
    )
    generated_source_reports.update(god_room_source_reports)
    replay = capture_overnight_replay_bundle(
        run_id=run_id,
        artifacts_dir=artifacts_dir,
        output_path=replay_path,
        section_artifacts=replay_section_artifacts,
        tombstoned_source_refs=tombstoned_source_refs,
    )
    replay_blockers = replay.get("blockers")
    if not isinstance(replay_blockers, list):
        replay_blockers = []
    recovery_queue = _recovery_queue(
        readiness=readiness,
        audit=audit,
        replay=replay,
        readiness_path=readiness_path,
        audit_path=audit_path,
        replay_path=replay_path,
        production_baseline=production_baseline,
    )

    pack = {
        "schema_version": "xmuse.release_evidence_pack.v1",
        "generated_at": _utc_now(),
        "artifacts_dir": str(Path(artifacts_dir)),
        "readiness_report": str(readiness_path),
        "proof_contamination_audit": str(audit_path),
        "overnight_replay_bundle": str(replay_path),
        "decision": _pack_decision(readiness=readiness, audit=audit, replay=replay),
        "release_readiness_decision": readiness["decision"],
        "proof_contamination_decision": audit["decision"],
        "overnight_replay_decision": replay["decision"],
        "overnight_replay_authority": replay["authority"],
        "proof_level_summary": _proof_level_summary(readiness),
        "release_gates": _release_gate_digests(readiness),
        "artifact_count": readiness["artifact_count"],
        "blocker_count": len(readiness["blockers"]),
        "replay_blocker_count": len(replay_blockers),
        "recovery_queue_count": len(recovery_queue),
        "finding_count": audit["finding_count"],
        "blockers": readiness["blockers"],
        "replay_blockers": replay_blockers,
        "recovery_queue": recovery_queue,
        "findings": audit["findings"],
        "source_reports": {
            "release_readiness": str(readiness_path),
            "proof_contamination_audit": str(audit_path),
            "overnight_replay_bundle": str(replay_path),
            **(
                {"production_baseline": str(production_baseline)}
                if production_baseline
                else {}
            ),
            **release_gate_source_reports,
            **generated_source_reports,
        },
    }
    if baseline_summary is not None:
        pack["production_baseline"] = baseline_summary
    if real_provider_runtime_summary is not None:
        pack["real_provider_runtime"] = real_provider_runtime_summary
    if github_truth_summary is not None:
        pack["github_truth"] = github_truth_summary
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pack


def _replay_section_artifacts(
    *,
    report_dir: Path,
    section_artifacts: Mapping[str, str | Path] | None,
    supervisor_snapshot: str | Path | None,
    supervisor_evidence_output: str | Path | None,
    deliberation_transcript: str | Path | None,
    god_runtime_artifact: str | Path | None,
    deliberation_transcript_evidence_output: str | Path | None,
    frozen_blueprint: str | Path | None,
    frozen_blueprint_evidence_output: str | Path | None,
    feature_contracts: tuple[str | Path, ...],
    feature_lineage_evidence_output: str | Path | None,
    run_id: str,
    memoryos_governance_plans: tuple[str | Path, ...],
    memoryos_writeback_events: tuple[str | Path, ...],
    memoryos_governance_evidence_output: str | Path | None,
    goal_stage_results: tuple[str | Path, ...],
    goal_stage_evidence_output: str | Path | None,
) -> tuple[dict[str, str | Path] | None, dict[str, str]]:
    artifacts = dict(section_artifacts or {})
    source_reports: dict[str, str] = {}
    if goal_stage_results:
        if "stage_evidence" in artifacts:
            raise ValueError(
                "stage_evidence source is ambiguous: pass either "
                "section_artifacts['stage_evidence'] or goal_stage_results, not both"
            )
        goal_stage_evidence_path = (
            Path(goal_stage_evidence_output)
            if goal_stage_evidence_output is not None
            else report_dir / "goal-stage-production-evidence.json"
        )
        capture_goal_stage_evidence(
            run_id=run_id,
            output_path=goal_stage_evidence_path,
            stage_results=goal_stage_results,
        )
        artifacts["stage_evidence"] = goal_stage_evidence_path
        source_reports["goal_stage_evidence"] = str(goal_stage_evidence_path)
    if supervisor_snapshot is not None:
        if "supervisor" in artifacts:
            raise ValueError(
                "supervisor evidence source is ambiguous: pass either "
                "section_artifacts['supervisor'] or supervisor_snapshot, not both"
            )
        supervisor_evidence_path = (
            Path(supervisor_evidence_output)
            if supervisor_evidence_output is not None
            else report_dir / "supervisor-production-evidence.json"
        )
        capture_overnight_supervisor_evidence(
            snapshot_path=supervisor_snapshot,
            output_path=supervisor_evidence_path,
        )
        artifacts["supervisor"] = supervisor_evidence_path
        source_reports["overnight_supervisor_evidence"] = str(supervisor_evidence_path)
    if deliberation_transcript is not None:
        if "deliberation_transcript" in artifacts:
            raise ValueError(
                "deliberation_transcript evidence source is ambiguous: pass either "
                "section_artifacts['deliberation_transcript'] or "
                "deliberation_transcript, not both"
            )
        deliberation_evidence_path = (
            Path(deliberation_transcript_evidence_output)
            if deliberation_transcript_evidence_output is not None
            else report_dir / "deliberation-transcript-production-evidence.json"
        )
        capture_deliberation_transcript_evidence(
            run_id=run_id,
            output_path=deliberation_evidence_path,
            transcript_artifact=deliberation_transcript,
            god_runtime_artifact=god_runtime_artifact,
        )
        artifacts["deliberation_transcript"] = deliberation_evidence_path
        source_reports["deliberation_transcript_evidence"] = str(
            deliberation_evidence_path
        )
    if frozen_blueprint is not None:
        if "frozen_blueprint" in artifacts:
            raise ValueError(
                "frozen_blueprint evidence source is ambiguous: pass either "
                "section_artifacts['frozen_blueprint'] or frozen_blueprint, not both"
            )
        frozen_blueprint_evidence_path = (
            Path(frozen_blueprint_evidence_output)
            if frozen_blueprint_evidence_output is not None
            else report_dir / "frozen-blueprint-production-evidence.json"
        )
        capture_frozen_blueprint_evidence(
            run_id=run_id,
            output_path=frozen_blueprint_evidence_path,
            blueprint_artifact=frozen_blueprint,
        )
        artifacts["frozen_blueprint"] = frozen_blueprint_evidence_path
        source_reports["frozen_blueprint_evidence"] = str(
            frozen_blueprint_evidence_path
        )
    if feature_contracts:
        if "feature_lineage" in artifacts:
            raise ValueError(
                "feature_lineage evidence source is ambiguous: pass either "
                "section_artifacts['feature_lineage'] or feature_contracts, not both"
            )
        feature_lineage_evidence_path = (
            Path(feature_lineage_evidence_output)
            if feature_lineage_evidence_output is not None
            else report_dir / "feature-lineage-production-evidence.json"
        )
        capture_feature_lineage_evidence(
            run_id=run_id,
            output_path=feature_lineage_evidence_path,
            contract_artifacts=feature_contracts,
        )
        artifacts["feature_lineage"] = feature_lineage_evidence_path
        source_reports["feature_lineage_evidence"] = str(feature_lineage_evidence_path)
    if memoryos_governance_plans or memoryos_writeback_events:
        if "memory_governance" in artifacts:
            raise ValueError(
                "memory_governance evidence source is ambiguous: pass either "
                "section_artifacts['memory_governance'] or MemoryOS governance "
                "plan/writeback inputs, not both"
            )
        memoryos_governance_path = (
            Path(memoryos_governance_evidence_output)
            if memoryos_governance_evidence_output is not None
            else report_dir / "memoryos-governance-production-evidence.json"
        )
        capture_memoryos_governance_evidence(
            run_id=run_id,
            output_path=memoryos_governance_path,
            plan_artifacts=memoryos_governance_plans,
            writeback_event_artifacts=memoryos_writeback_events,
        )
        artifacts["memory_governance"] = memoryos_governance_path
        source_reports["memoryos_governance_evidence"] = str(memoryos_governance_path)
    return (artifacts or None), source_reports


def _with_god_room_runtime_closure_evidence(
    *,
    report_dir: Path,
    run_id: str,
    section_artifacts: Mapping[str, str | Path] | None,
    participants_artifact: str | Path | None,
    events_artifact: str | Path | None,
    blueprint_freeze_artifact: str | Path | None,
    lane_dag_artifact: str | Path | None,
    memory_trace_artifact: str | Path | None,
    tui_projection_artifact: str | Path | None,
    speaker_attempt_artifact: str | Path | None,
    speaker_response_artifact: str | Path | None,
    github_truth_artifact: str | Path | None,
    release_readiness_artifact: str | Path,
    evidence_output: str | Path | None,
) -> tuple[dict[str, str | Path] | None, dict[str, str]]:
    artifacts = dict(section_artifacts or {})
    source_reports: dict[str, str] = {}
    has_inputs = any(
        value is not None
        for value in (
            participants_artifact,
            events_artifact,
            blueprint_freeze_artifact,
            lane_dag_artifact,
            memory_trace_artifact,
            tui_projection_artifact,
            speaker_attempt_artifact,
            speaker_response_artifact,
        )
    )
    if not has_inputs:
        return (artifacts or None), source_reports
    if GOD_ROOM_RUNTIME_CLOSURE_SECTION in artifacts:
        raise ValueError(
            "god_room_runtime_closure evidence source is ambiguous: pass either "
            "section_artifacts['god_room_runtime_closure'] or GOD room runtime "
            "closure inputs, not both"
        )
    closure_evidence_path = (
        Path(evidence_output)
        if evidence_output is not None
        else report_dir / "god-room-runtime-closure-production-evidence.json"
    )
    capture_god_room_runtime_closure_evidence(
        run_id=run_id,
        output_path=closure_evidence_path,
        participants_artifact=participants_artifact,
        events_artifact=events_artifact,
        blueprint_freeze_artifact=blueprint_freeze_artifact,
        lane_dag_artifact=lane_dag_artifact,
        memory_trace_artifact=memory_trace_artifact,
        tui_projection_artifact=tui_projection_artifact,
        speaker_attempt_artifact=speaker_attempt_artifact,
        speaker_response_artifact=speaker_response_artifact,
        github_truth_artifact=github_truth_artifact,
        release_readiness_artifact=release_readiness_artifact,
    )
    artifacts[GOD_ROOM_RUNTIME_CLOSURE_SECTION] = closure_evidence_path
    source_reports["god_room_runtime_closure_evidence"] = str(closure_evidence_path)
    return artifacts, source_reports


def _release_gate_artifacts(
    *,
    artifacts_dir: Path,
    memoryos_live_trace: str | Path | None,
    real_provider_runtime: str | Path | None,
    natural_deliberation_transcript: str | Path | None,
    natural_deliberation_god_runtime: str | Path | None,
    github_server_truth: str | Path | None,
    github_base_branch: str,
    github_expected_head_sha: str | None,
    internal_review_artifact: str | Path | None,
    internal_review_expected_head_sha: str | None,
) -> dict[str, str]:
    source_reports: dict[str, str] = {}
    if (
        internal_review_artifact is not None
        or internal_review_expected_head_sha is not None
    ):
        if internal_review_expected_head_sha is None:
            raise ValueError(
                "internal_review_expected_head_sha is required when "
                "internal_review_artifact is supplied for a release gate"
            )
        internal_review_gate_path = artifacts_dir / "internal-review.json"
        review_artifact = (
            internal_review_artifact
            if internal_review_artifact is not None
            else artifacts_dir / "internal-review-input.json"
        )
        capture_internal_review_release_gate(
            artifact_path=review_artifact,
            output_path=internal_review_gate_path,
            expected_head_sha=internal_review_expected_head_sha,
        )
        source_reports["internal_review_gate"] = str(internal_review_gate_path)
    if github_server_truth is not None:
        github_truth_path = Path(github_server_truth)
        github_gate_path = artifacts_dir / "github-server-truth.json"
        write_github_server_truth_release_gate(
            _load_json_object(github_truth_path, label="GitHub server truth"),
            artifact_path=github_truth_path,
            output_path=github_gate_path,
            base_branch=github_base_branch,
            expected_head_sha=github_expected_head_sha,
        )
        source_reports["github_server_truth_gate"] = str(github_gate_path)
    if natural_deliberation_transcript is not None:
        if natural_deliberation_god_runtime is None:
            raise ValueError(
                "natural_deliberation_god_runtime is required when "
                "natural_deliberation_transcript is supplied for a release gate"
            )
        natural_gate_path = artifacts_dir / "natural-deliberation.json"
        capture_natural_deliberation_release_gate(
            artifact_path=natural_deliberation_transcript,
            output_path=natural_gate_path,
            god_runtime_path=natural_deliberation_god_runtime,
        )
        source_reports["natural_deliberation_gate"] = str(natural_gate_path)
    if memoryos_live_trace is not None:
        memoryos_gate_path = artifacts_dir / "live-memoryos.json"
        capture_memoryos_live_release_gate(
            artifact_path=memoryos_live_trace,
            output_path=memoryos_gate_path,
        )
        source_reports["memoryos_live_gate"] = str(memoryos_gate_path)
    if real_provider_runtime is not None:
        provider_gate_path = artifacts_dir / "real-provider-runtime.json"
        capture_real_provider_runtime_release_gate(
            artifact_path=real_provider_runtime,
            output_path=provider_gate_path,
        )
        source_reports["real_provider_runtime_gate"] = str(provider_gate_path)
    return source_reports


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} artifact does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} artifact must be a JSON object: {path}")
    return payload


def _real_provider_runtime_summary(
    *,
    artifacts_dir: Path,
    source_reports: Mapping[str, str],
) -> dict[str, Any] | None:
    paths: list[Path] = []
    report = _text(source_reports.get("real_provider_runtime_gate"))
    if report is not None:
        paths.append(Path(report))
    if artifacts_dir.exists():
        paths.extend(sorted(artifacts_dir.rglob("*.json")))

    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        payload = _try_load_json_object(path)
        if payload is None or _text(payload.get("gate_id")) != "real-provider-runtime":
            continue
        details = payload.get("real_provider_runtime")
        if isinstance(details, dict):
            return _real_provider_runtime_pack_projection(
                payload,
                details,
                gate_artifact=path,
            )
    return None


def _try_load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _real_provider_runtime_pack_projection(
    gate: dict[str, Any],
    details: dict[str, Any],
    *,
    gate_artifact: Path,
) -> dict[str, Any]:
    runtime_artifacts = _string_list(gate.get("artifacts"))
    return {
        "authority": _text(details.get("authority"))
        or "real_provider_runtime_release_gate",
        "status": _text(gate.get("status")) or "not_evaluated",
        "proof_level": _text(gate.get("proof_level")) or "manual_gap",
        "gate_artifact": str(gate_artifact),
        "runtime_artifact": runtime_artifacts[0] if runtime_artifacts else None,
        "run_id": _text(details.get("run_id")),
        "conversation_id": _text(details.get("conversation_id")),
        "provider_id": _text(details.get("provider_id")),
        "runtime_backend": _text(details.get("runtime_backend")),
        "transport": _text(details.get("transport")),
        "provider_session_id": _text(details.get("provider_session_id")),
        "mcp_writeback": details.get("mcp_writeback") is True,
        "provider_session_reused": details.get("provider_session_reused") is True,
        "fresh_provider_session_id": _text(details.get("fresh_provider_session_id")),
        "resumed_provider_session_id": _text(
            details.get("resumed_provider_session_id")
        ),
        "turn_count": _int(details.get("turn_count")),
        "phases": _string_list(details.get("phases")),
        "mcp_writeback_turn_count": _int(details.get("mcp_writeback_turn_count")),
        "degraded_turn_count": _int(details.get("degraded_turn_count")),
        "blocker_count": _int(details.get("blocker_count")),
    }


def _github_truth_summary(
    *,
    artifacts_dir: Path,
    source_reports: Mapping[str, str],
) -> dict[str, Any] | None:
    paths: list[Path] = []
    report = _text(source_reports.get("github_server_truth_gate"))
    if report is not None:
        paths.append(Path(report))
    if artifacts_dir.exists():
        paths.extend(sorted(artifacts_dir.rglob("*.json")))

    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        gate = _try_load_json_object(path)
        if gate is None or _text(gate.get("gate_id")) != "github-server-truth":
            continue
        truth = _first_json_artifact(gate)
        if truth is None:
            continue
        return _github_truth_pack_projection(gate, truth, gate_artifact=path)
    return None


def _first_json_artifact(gate: dict[str, Any]) -> dict[str, Any] | None:
    for artifact in _string_list(gate.get("artifacts")):
        payload = _try_load_json_object(Path(artifact))
        if payload is not None:
            return payload
    return None


def _github_truth_pack_projection(
    gate: dict[str, Any],
    truth: dict[str, Any],
    *,
    gate_artifact: Path,
) -> dict[str, Any]:
    truth_artifacts = _string_list(gate.get("artifacts"))
    return {
        "authority": "github_truth_release_gate",
        "status": _text(gate.get("status")) or "not_evaluated",
        "proof_level": _text(gate.get("proof_level")) or "manual_gap",
        "gate_artifact": str(gate_artifact),
        "truth_artifact": truth_artifacts[0] if truth_artifacts else None,
        "repo": _text(truth.get("repo")),
        "pull_request_number": _optional_int(truth.get("pull_request_number")),
        "pull_request_state": _text(truth.get("pull_request_state")),
        "draft": _optional_bool(truth.get("draft")),
        "mergeable": _optional_bool(truth.get("mergeable")),
        "mergeable_state": _text(truth.get("mergeable_state")),
        "head_sha": _text(truth.get("head_sha")),
        "expected_head_sha": _text(truth.get("expected_head_sha")),
        "head_sha_matches_expected": truth.get("head_sha_matches_expected") is True,
        "required_check_count": len(_string_list(truth.get("required_checks"))),
        "check_run_count": len(_list_value(truth.get("check_run_ids"))),
        "expected_source_app": _text(truth.get("expected_source_app")),
        "server_enforcement": _github_server_enforcement(truth),
        "review_truth": _github_review_truth(truth),
        "merge_truth": _github_merge_truth(truth),
        "merged": truth.get("merged") is True,
        "can_emit_pr_merged": truth.get("can_emit_pr_merged") is True,
        "gap_reason": _text(truth.get("gap_reason")),
        "capture_mode": _text(truth.get("capture_mode")),
    }


def _github_server_enforcement(truth: dict[str, Any]) -> str:
    if isinstance(truth.get("branch_protection_snapshot"), dict):
        return "branch_protection"
    if isinstance(truth.get("ruleset_snapshot"), dict):
        return "ruleset"
    return "missing"


def _github_review_truth(truth: dict[str, Any]) -> str:
    if truth.get("review_event_id") is not None:
        return "github_review"
    if truth.get("internal_review_verified") is True:
        return "internal_review"
    return "missing"


def _github_merge_truth(truth: dict[str, Any]) -> str:
    if truth.get("can_emit_pr_merged") is True and truth.get("merged") is True:
        return "pr_merged"
    return "missing"


def _production_baseline_summary(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    baseline_path = Path(path)
    payload = _load_json_object(baseline_path, label="production baseline")
    if payload.get("schema_version") != "xmuse.production_baseline.v1":
        raise ValueError(
            f"production baseline artifact has unsupported schema: {baseline_path}"
        )
    git = payload.get("git")
    if not isinstance(git, dict):
        git = {}
    package_boundary = payload.get("package_boundary")
    if not isinstance(package_boundary, dict):
        package_boundary = {}
    return {
        "artifact": str(baseline_path),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "proof_level": payload.get("proof_level"),
        "head_sha": git.get("head_sha"),
        "dirty": git.get("dirty"),
        "xmuse_init_absent": package_boundary.get("xmuse_init_absent"),
        "blockers": _string_list(payload.get("blockers")),
    }


def _proof_level_summary(readiness: dict[str, Any]) -> dict[str, int]:
    summary = readiness.get("proof_level_summary")
    if not isinstance(summary, dict):
        return {}
    return {
        key: value
        for key, value in summary.items()
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
    }


def _release_gate_digests(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    digests: list[dict[str, Any]] = []
    for gate in _dicts(readiness.get("gates")):
        digests.append(
            {
                "gate_id": _text(gate.get("gate_id")) or "unknown",
                "kind": _text(gate.get("kind")) or "unknown",
                "status": _text(gate.get("status")) or "not_evaluated",
                "proof_level": _text(gate.get("proof_level")) or "manual_gap",
                "configured": gate.get("configured") is True,
                "required": gate.get("required") is True,
                "owner": _text(gate.get("owner")) or "operator",
                "summary": _text(gate.get("summary")) or "release gate evidence",
                "attempted_command": _text(gate.get("attempted_command")),
                "next_action": _text(gate.get("next_action")),
                "source_ref_count": len(_string_list(gate.get("source_refs"))),
                "artifact_count": len(_string_list(gate.get("artifacts"))),
            }
        )
    return digests


def _recovery_queue(
    *,
    readiness: dict[str, Any],
    audit: dict[str, Any],
    replay: dict[str, Any],
    readiness_path: Path,
    audit_path: Path,
    replay_path: Path,
    production_baseline: str | Path | None,
) -> list[dict[str, str | None]]:
    queue: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, ...]] = set()
    _append_production_baseline_recovery_items(
        queue,
        seen=seen,
        production_baseline=production_baseline,
    )
    for finding in _dicts(audit.get("findings")):
        code = _text(finding.get("code")) or "proof_contamination"
        summary = _text(finding.get("summary")) or "proof contamination finding"
        _append_recovery_item(
            queue,
            seen=seen,
            source="proof_contamination_audit",
            kind="proof_finding",
            identifier=_text(finding.get("gate_id")) or "unknown",
            owner="operator",
            reason=f"{code}: {summary}",
            next_action=_proof_contamination_next_action(code),
            artifact=str(audit_path),
        )
    for blocker in _dicts(readiness.get("blockers")):
        _append_recovery_item(
            queue,
            seen=seen,
            source="release_readiness",
            kind="release_gate",
            identifier=_text(blocker.get("gate_id")) or "unknown",
            owner=_text(blocker.get("owner")) or "operator",
            reason=_text(blocker.get("reason")) or "blocked",
            next_action=_text(blocker.get("next_action")),
            artifact=str(readiness_path),
        )
    for blocker in _dicts(replay.get("blockers")):
        _append_recovery_item(
            queue,
            seen=seen,
            source="overnight_replay_bundle",
            kind="replay_section",
            identifier=_text(blocker.get("section_id")) or "unknown",
            owner=_text(blocker.get("owner")) or "operator",
            reason=_text(blocker.get("reason")) or "blocked",
            next_action=_text(blocker.get("next_action")),
            artifact=str(replay_path),
        )
    return queue


def _append_production_baseline_recovery_items(
    queue: list[dict[str, str | None]],
    *,
    seen: set[tuple[str | None, ...]],
    production_baseline: str | Path | None,
) -> None:
    if production_baseline is None:
        return
    baseline_path = Path(production_baseline)
    payload = _load_json_object(baseline_path, label="production baseline")
    live_resources = payload.get("live_resources")
    if not isinstance(live_resources, dict):
        return
    owner = _text(payload.get("owner")) or "operator"
    default_next_action = _text(payload.get("next_action"))
    for resource_id, resource in live_resources.items():
        if not isinstance(resource_id, str) or not isinstance(resource, dict):
            continue
        next_action = _text(resource.get("next_action")) or default_next_action
        for blocker in _string_list(resource.get("blockers")):
            _append_recovery_item(
                queue,
                seen=seen,
                source="production_baseline",
                kind="production_resource",
                identifier=resource_id,
                owner=owner,
                reason=blocker,
                next_action=next_action,
                artifact=str(baseline_path),
            )


def _proof_contamination_next_action(code: str) -> str:
    if code == "fake_marker_in_production_proof":
        return (
            "Replace the contaminated artifact with live/server-side evidence "
            "and remove fake/local/stdout fallback sources."
        )
    if code == "weak_proof_for_production_gate":
        return (
            "Regenerate the gate artifact with the required production proof "
            "level; do not relabel weaker evidence."
        )
    if code == "pr_merged_without_merge_truth":
        return (
            "Capture server-side merge truth with can_emit_pr_merged=true "
            "before claiming pr_merged."
        )
    return "Replace or regenerate the contaminated production proof artifact."


def _append_recovery_item(
    queue: list[dict[str, str | None]],
    *,
    seen: set[tuple[str | None, ...]],
    source: str,
    kind: str,
    identifier: str,
    owner: str,
    reason: str,
    next_action: str | None,
    artifact: str,
) -> None:
    key = (source, kind, identifier, reason, next_action, artifact)
    if key in seen:
        return
    seen.add(key)
    queue.append(
        {
            "source": source,
            "kind": kind,
            "id": identifier,
            "owner": owner,
            "reason": reason,
            "next_action": next_action,
            "artifact": artifact,
        }
    )


def _dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _pack_decision(
    *,
    readiness: dict[str, Any],
    audit: dict[str, Any],
    replay: dict[str, Any],
) -> str:
    if audit["decision"] == "contaminated":
        return "contaminated"
    if readiness["decision"] == "not_evaluated" and readiness["artifact_count"] == 0:
        return "not_evaluated"
    if readiness["decision"] == "blocked" or replay["decision"] == "blocked":
        return "blocked"
    return str(readiness["decision"])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
