from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.proof_contamination_audit import (
    capture_proof_contamination_audit,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def capture_release_evidence_pack(
    *,
    artifacts_dir: str | Path,
    output_path: str | Path,
    readiness_output: str | Path | None = None,
    audit_output: str | Path | None = None,
) -> dict[str, Any]:
    output = Path(output_path)
    report_dir = output.parent
    readiness_path = Path(readiness_output) if readiness_output is not None else (
        report_dir / "release-readiness.json"
    )
    audit_path = Path(audit_output) if audit_output is not None else (
        report_dir / "proof-contamination-audit.json"
    )

    readiness = capture_release_readiness(
        artifacts_dir=artifacts_dir,
        output_path=readiness_path,
    )
    audit = capture_proof_contamination_audit(
        artifacts_dir=artifacts_dir,
        output_path=audit_path,
    )

    pack = {
        "schema_version": "xmuse.release_evidence_pack.v1",
        "generated_at": _utc_now(),
        "artifacts_dir": str(Path(artifacts_dir)),
        "readiness_report": str(readiness_path),
        "proof_contamination_audit": str(audit_path),
        "decision": _pack_decision(readiness=readiness, audit=audit),
        "release_readiness_decision": readiness["decision"],
        "proof_contamination_decision": audit["decision"],
        "artifact_count": readiness["artifact_count"],
        "blocker_count": len(readiness["blockers"]),
        "finding_count": audit["finding_count"],
        "blockers": readiness["blockers"],
        "findings": audit["findings"],
        "source_reports": {
            "release_readiness": str(readiness_path),
            "proof_contamination_audit": str(audit_path),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pack


def _pack_decision(*, readiness: dict[str, Any], audit: dict[str, Any]) -> str:
    if audit["decision"] == "contaminated":
        return "contaminated"
    return str(readiness["decision"])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
