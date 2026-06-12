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
    )

    readiness = capture_release_readiness(
        artifacts_dir=artifacts_dir,
        output_path=readiness_path,
    )
    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts_dir,
        output_path=audit_path,
    )
    replay = capture_overnight_replay_bundle(
        run_id=run_id,
        artifacts_dir=artifacts_dir,
        output_path=replay_path,
        section_artifacts=replay_section_artifacts,
        tombstoned_source_refs=tombstoned_source_refs,
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
        "artifact_count": readiness["artifact_count"],
        "blocker_count": len(readiness["blockers"]),
        "replay_blocker_count": len(replay["blockers"]),
        "finding_count": audit["finding_count"],
        "blockers": readiness["blockers"],
        "replay_blockers": replay["blockers"],
        "findings": audit["findings"],
        "source_reports": {
            "release_readiness": str(readiness_path),
            "proof_contamination_audit": str(audit_path),
            "overnight_replay_bundle": str(replay_path),
            **release_gate_source_reports,
            **generated_source_reports,
        },
    }
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
) -> tuple[dict[str, str | Path] | None, dict[str, str]]:
    artifacts = dict(section_artifacts or {})
    source_reports: dict[str, str] = {}
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
) -> dict[str, str]:
    source_reports: dict[str, str] = {}
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
