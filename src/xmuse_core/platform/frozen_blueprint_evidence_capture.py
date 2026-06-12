from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
)

FROZEN_BLUEPRINT_ACTION = "frozen_blueprint_verified"
FROZEN_BLUEPRINT_AUTHORITY = "mission_blueprint_v1"


def capture_frozen_blueprint_evidence(
    *,
    run_id: str,
    blueprint_artifact: str | Path,
    output_path: str | Path,
    stage_id: str = "S3",
) -> dict[str, object]:
    artifact_path = Path(blueprint_artifact)
    blueprint = _load_blueprint(artifact_path)
    evidence = build_frozen_blueprint_evidence(
        run_id=run_id,
        stage_id=stage_id,
        blueprint=blueprint,
        blueprint_artifact=artifact_path,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_frozen_blueprint_evidence(
    *,
    run_id: str,
    stage_id: str,
    blueprint: MissionBlueprintV1,
    blueprint_artifact: str | Path,
) -> dict[str, object]:
    blocked_reason = _blocked_reason(blueprint)
    if blocked_reason is None:
        status: ProductionEvidenceStatus = "ok"
        proof_level: ProofLevel = "contract_proof"
        next_action = None
    else:
        status = "manual_gap"
        proof_level = "manual_gap"
        next_action = (
            "Freeze the mission blueprint through the deliberation/freeze contract "
            "and regenerate frozen blueprint replay evidence."
        )
    envelope = ProductionEvidenceEnvelope(
        run_id=run_id,
        stage_id=stage_id,
        action=FROZEN_BLUEPRINT_ACTION,
        status=status,
        proof_level=proof_level,
        source_authority=FROZEN_BLUEPRINT_AUTHORITY,
        source_refs=tuple(_source_refs(blueprint)),
        target_refs=tuple(
            [
                f"blueprint:{blueprint.blueprint_id}",
                f"conversation:{blueprint.conversation_id}",
            ]
        ),
        artifacts=(str(Path(blueprint_artifact)),),
        blocked_reason=blocked_reason,
        owner="codex",
        next_action=next_action,
        summary=_summary(blueprint),
    )
    return envelope.model_dump()


def _load_blueprint(path: Path) -> MissionBlueprintV1:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected mission_blueprint.v1 JSON object")
    return MissionBlueprintV1.model_validate(payload)


def _blocked_reason(blueprint: MissionBlueprintV1) -> str | None:
    if blueprint.status is MissionBlueprintStatus.FROZEN:
        return None
    return (
        f"mission blueprint {blueprint.blueprint_id} status is "
        f"{blueprint.status.value}, expected frozen"
    )


def _source_refs(blueprint: MissionBlueprintV1) -> list[str]:
    refs = [
        f"mission_blueprint:{blueprint.blueprint_id}:r{blueprint.revision}",
        f"conversation:{blueprint.conversation_id}",
        *blueprint.source_refs,
    ]
    return _dedupe(refs)


def _summary(blueprint: MissionBlueprintV1) -> str:
    if blueprint.status is MissionBlueprintStatus.FROZEN:
        return (
            f"Mission blueprint {blueprint.blueprint_id} revision "
            f"{blueprint.revision} is frozen with "
            f"{len(blueprint.acceptance_contracts)} acceptance contract(s)."
        )
    return (
        f"Mission blueprint {blueprint.blueprint_id} revision "
        f"{blueprint.revision} is {blueprint.status.value}, not frozen."
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
