from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.memoryos_governance_evidence_capture import (
    capture_memoryos_governance_evidence,
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
    memoryos_governance_plans: tuple[str | Path, ...] = (),
    memoryos_writeback_events: tuple[str | Path, ...] = (),
    memoryos_governance_evidence_output: str | Path | None = None,
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
        run_id=run_id,
        memoryos_governance_plans=memoryos_governance_plans,
        memoryos_writeback_events=memoryos_writeback_events,
        memoryos_governance_evidence_output=memoryos_governance_evidence_output,
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
