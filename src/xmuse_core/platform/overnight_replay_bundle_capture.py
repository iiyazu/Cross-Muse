from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from xmuse_core.platform.overnight_replay_bundle import (
    OPTIONAL_REPLAY_SECTIONS,
    REQUIRED_REPLAY_SECTIONS,
    ReplayBundleSection,
    ReplaySectionStatus,
    build_overnight_replay_bundle,
    write_overnight_replay_bundle,
)
from xmuse_core.platform.release_readiness import (
    ProofLevel,
    ReleaseGateEvidence,
    ReleaseGateKind,
    evaluate_release_readiness,
)
from xmuse_core.platform.release_readiness_capture import load_release_gate_artifacts

_KNOWN_REPLAY_SECTIONS = (*REQUIRED_REPLAY_SECTIONS, *OPTIONAL_REPLAY_SECTIONS)

_GATE_SECTION_AUTHORITY = {
    ReleaseGateKind.NATURAL_DELIBERATION: (
        "deliberation_transcript",
        "natural_deliberation_release_gate",
    ),
    ReleaseGateKind.LIVE_MEMORYOS: (
        "memoryos_trace",
        "memoryos_live_release_gate",
    ),
    ReleaseGateKind.GITHUB_SERVER_TRUTH: (
        "github_truth",
        "github_truth_release_gate",
    ),
}


def capture_overnight_replay_bundle(
    *,
    run_id: str,
    artifacts_dir: str | Path,
    output_path: str | Path,
    section_artifacts: Mapping[str, str | Path] | None = None,
    tombstoned_source_refs: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build an overnight replay index from release gates and section evidence.

    The returned bundle is an index of source authorities. It does not upgrade
    release gate proof, and it fills unattached required sections with
    ``manual_gap`` sections instead of omitting them.
    """
    artifacts_root = Path(artifacts_dir)
    gates = load_release_gate_artifacts(artifacts_root)
    gate_artifact_paths = _gate_artifact_paths(artifacts_root)
    sections = _default_sections()
    for gate in gates:
        section = _section_from_gate(gate, gate_artifact_paths=gate_artifact_paths)
        if section is not None:
            sections[section.section_id] = section
    sections["release_readiness"] = _release_readiness_section(
        gates,
        artifacts_root=artifacts_root,
    )
    for section_id, artifact_path in (section_artifacts or {}).items():
        normalized_section_id = _clean_text(section_id)
        if normalized_section_id not in _KNOWN_REPLAY_SECTIONS:
            continue
        sections[normalized_section_id] = _section_from_production_evidence(
            normalized_section_id,
            Path(artifact_path),
        )

    bundle = build_overnight_replay_bundle(
        run_id=run_id,
        sections=[
            sections[section_id]
            for section_id in _KNOWN_REPLAY_SECTIONS
            if section_id in sections
        ],
        tombstoned_source_refs=tombstoned_source_refs,
    )
    write_overnight_replay_bundle(bundle=bundle, output_path=output_path)
    return bundle


def _default_sections() -> dict[str, ReplayBundleSection]:
    return {
        section_id: ReplayBundleSection(
            section_id=section_id,
            status="manual_gap",
            proof_level="manual_gap",
            source_authority="overnight_replay_bundle_capture",
            summary=f"{section_id} replay evidence was not attached.",
            blocked_reason=f"{section_id} replay evidence was not attached.",
            next_action=f"Attach or capture {section_id} production evidence.",
        )
        for section_id in REQUIRED_REPLAY_SECTIONS
    }


def _section_from_gate(
    gate: ReleaseGateEvidence,
    *,
    gate_artifact_paths: Mapping[str, tuple[str, ...]],
) -> ReplayBundleSection | None:
    section_config = _GATE_SECTION_AUTHORITY.get(gate.kind)
    if section_config is None:
        return None
    section_id, source_authority = section_config
    artifacts = _dedupe((*gate.artifacts, *gate_artifact_paths.get(gate.gate_id, ())))
    blocked_reason = None
    if gate.status != "ok":
        blocked_reason = f"{gate.gate_id} status is {gate.status}: {gate.summary}"
    details = _section_details_from_artifacts(
        section_id=section_id,
        artifact_paths=gate_artifact_paths.get(gate.gate_id, ()),
    )
    return ReplayBundleSection(
        section_id=section_id,
        status=gate.status,
        proof_level=gate.proof_level,
        source_authority=source_authority,
        source_refs=gate.source_refs,
        artifacts=artifacts,
        summary=gate.summary,
        blocked_reason=blocked_reason,
        owner=gate.owner,
        next_action=gate.next_action,
        details=details,
    )


def _release_readiness_section(
    gates: list[ReleaseGateEvidence],
    *,
    artifacts_root: Path,
) -> ReplayBundleSection:
    readiness = evaluate_release_readiness(gates)
    if readiness.decision == "ready":
        status: ReplaySectionStatus = "ok"
        blocked_reason = None
    elif readiness.decision == "blocked":
        status = "blocked"
        blocked_ids = [
            str(blocker["gate_id"])
            for blocker in readiness.blockers
            if isinstance(blocker.get("gate_id"), str)
        ]
        blocked_reason = "release readiness blocked by gates: " + ", ".join(blocked_ids)
    else:
        status = "not_evaluated"
        blocked_reason = "release readiness has no gate artifacts to evaluate"
    return ReplayBundleSection(
        section_id="release_readiness",
        status=status,
        proof_level="contract_proof" if gates else "manual_gap",
        source_authority="release_readiness_capture",
        source_refs=tuple(f"release_gate:{gate.gate_id}" for gate in gates),
        artifacts=(str(artifacts_root),),
        summary=f"release readiness decision is {readiness.decision}",
        blocked_reason=blocked_reason,
        owner="operator",
        next_action=(
            "Resolve release gate blockers and regenerate the release evidence pack."
            if blocked_reason
            else None
        ),
    )


def _section_from_production_evidence(
    section_id: str,
    artifact_path: Path,
) -> ReplayBundleSection:
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _invalid_section_artifact(
            section_id,
            artifact_path=artifact_path,
            reason=f"attached section artifact could not be read: {exc}",
        )
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "xmuse.production_evidence.v1"
    ):
        return _invalid_section_artifact(
            section_id,
            artifact_path=artifact_path,
            reason="attached section artifact is not xmuse.production_evidence.v1",
        )
    artifacts = _dedupe((*_string_list(payload.get("artifacts")), str(artifact_path)))
    status = _section_status(payload.get("status"))
    return ReplayBundleSection(
        section_id=section_id,
        status=status,
        proof_level=_proof_level(payload.get("proof_level")),
        source_authority=_clean_text(payload.get("source_authority"))
        or "production_evidence",
        source_refs=tuple(_string_list(payload.get("source_refs"))),
        artifacts=artifacts,
        summary=_clean_text(payload.get("summary"))
        or _clean_text(payload.get("action"))
        or f"{section_id} production evidence attached",
        blocked_reason=_clean_text(payload.get("blocked_reason")),
        owner=_clean_text(payload.get("owner")) or "operator",
        next_action=_clean_text(payload.get("next_action")),
        details=_section_details(section_id=section_id, payload=payload),
    )


def _invalid_section_artifact(
    section_id: str,
    *,
    artifact_path: Path,
    reason: str,
) -> ReplayBundleSection:
    return ReplayBundleSection(
        section_id=section_id,
        status="manual_gap",
        proof_level="manual_gap",
        source_authority="overnight_replay_bundle_capture",
        artifacts=(str(artifact_path),),
        summary=reason,
        blocked_reason=reason,
        next_action=f"Regenerate {section_id} as xmuse.production_evidence.v1.",
    )


def _gate_artifact_paths(artifacts_dir: Path) -> dict[str, tuple[str, ...]]:
    if not artifacts_dir.exists():
        return {}
    paths_by_gate: dict[str, list[str]] = {}
    for path in sorted(artifacts_dir.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        gate_id = _clean_text(payload.get("gate_id"))
        if gate_id is None:
            continue
        paths_by_gate.setdefault(gate_id, []).append(str(path))
    return {gate_id: tuple(paths) for gate_id, paths in paths_by_gate.items()}


def _section_status(value: object) -> ReplaySectionStatus:
    if value in {"ok", "blocked", "manual_gap", "not_evaluated"}:
        return value  # type: ignore[return-value]
    if value in {"pending", "running"}:
        return "not_evaluated"
    return "blocked"


def _proof_level(value: object) -> ProofLevel:
    if value in {
        "contract_proof",
        "fake_runtime_proof",
        "live_service_proof",
        "server_side_enforcement_proof",
        "server_side_merge_proof",
        "real_provider_proof",
        "internal_review_proof",
        "manual_gap",
    }:
        return value  # type: ignore[return-value]
    return "manual_gap"


def _section_details(
    *,
    section_id: str,
    payload: dict[str, object],
) -> dict[str, object] | None:
    details = payload.get(section_id)
    if isinstance(details, dict):
        return {section_id: details}
    return None


def _section_details_from_artifacts(
    *,
    section_id: str,
    artifact_paths: tuple[str, ...],
) -> dict[str, object] | None:
    for artifact_path in artifact_paths:
        try:
            payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        details = _section_details(section_id=section_id, payload=payload)
        if details is not None:
            return details
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
