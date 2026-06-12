from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel
from xmuse_core.structuring.feature_owner_contract import (
    FeatureOwnerExecutionContract,
)

FEATURE_LINEAGE_ACTION = "feature_lineage_verified"
FEATURE_LINEAGE_AUTHORITY = "feature_owner_execution_contract"


def capture_feature_lineage_evidence(
    *,
    run_id: str,
    output_path: str | Path,
    contract_artifacts: Sequence[str | Path] = (),
    stage_id: str = "S3",
) -> dict[str, object]:
    contracts, invalid_artifacts = _contracts_from_artifacts(contract_artifacts)
    evidence = build_feature_lineage_evidence(
        run_id=run_id,
        stage_id=stage_id,
        contracts=contracts,
        invalid_artifacts=invalid_artifacts,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_feature_lineage_evidence(
    *,
    run_id: str,
    stage_id: str,
    contracts: Sequence[tuple[Path, FeatureOwnerExecutionContract]],
    invalid_artifacts: Sequence[tuple[Path, str]] = (),
) -> dict[str, object]:
    blocked_reason = _blocked_reason(
        contracts=contracts,
        invalid_artifacts=invalid_artifacts,
    )
    if blocked_reason is None:
        status: ProductionEvidenceStatus = "ok"
        proof_level: ProofLevel = "contract_proof"
        next_action = None
    else:
        status = "manual_gap"
        proof_level = "manual_gap"
        next_action = _next_action(blocked_reason)
    envelope = ProductionEvidenceEnvelope(
        run_id=run_id,
        stage_id=stage_id,
        action=FEATURE_LINEAGE_ACTION,
        status=status,
        proof_level=proof_level,
        source_authority=FEATURE_LINEAGE_AUTHORITY,
        source_refs=tuple(_source_refs(contracts)),
        target_refs=tuple(_target_refs(contracts)),
        artifacts=tuple(_artifacts(contracts=contracts, invalid_artifacts=invalid_artifacts)),
        blocked_reason=blocked_reason,
        owner="codex",
        next_action=next_action,
        summary=_summary(contracts),
    )
    return envelope.model_dump()


def _contracts_from_artifacts(
    artifacts: Sequence[str | Path],
) -> tuple[
    list[tuple[Path, FeatureOwnerExecutionContract]],
    list[tuple[Path, str]],
]:
    contracts: list[tuple[Path, FeatureOwnerExecutionContract]] = []
    invalid_artifacts: list[tuple[Path, str]] = []
    for artifact in artifacts:
        path = Path(artifact)
        try:
            payload = _read_json(path)
            contract = FeatureOwnerExecutionContract.model_validate(payload)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            invalid_artifacts.append((path, str(exc)))
            continue
        contracts.append((path, contract))
    return contracts, invalid_artifacts


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def _blocked_reason(
    *,
    contracts: Sequence[tuple[Path, FeatureOwnerExecutionContract]],
    invalid_artifacts: Sequence[tuple[Path, str]],
) -> str | None:
    if invalid_artifacts:
        reasons = [
            f"{path.name}: {_one_line(reason)}"
            for path, reason in invalid_artifacts
        ]
        return "feature lineage artifacts rejected: " + "; ".join(reasons)
    if not contracts:
        return "no feature owner execution contracts were supplied"
    empty_features = [
        contract.feature_id for _path, contract in contracts if not contract.lane_ids
    ]
    if empty_features:
        return (
            "feature owner contracts have no lane lineage: "
            + ", ".join(empty_features)
        )
    return None


def _next_action(blocked_reason: str) -> str:
    if "rejected" in blocked_reason:
        return (
            "Regenerate feature owner execution contracts from graph-set authority, "
            "not feature_lanes.json."
        )
    return (
        "Capture or attach feature owner execution contracts generated from "
        "graph-set authority."
    )


def _source_refs(
    contracts: Sequence[tuple[Path, FeatureOwnerExecutionContract]],
) -> list[str]:
    refs: list[str] = []
    for _path, contract in contracts:
        refs.extend(
            [
                f"feature-owner:{contract.feature_id}",
                f"graph-set:{contract.graph_set_id}",
                f"feature-graph:{contract.feature_graph_id}",
                _ready_set_ref(contract),
            ]
        )
        refs.extend(contract.source_refs)
        refs.extend(f"lane:{lane_id}" for lane_id in contract.lane_ids)
        refs.extend(_lane_blocker_refs(contract))
        refs.extend(contract.memory_refs)
    return _dedupe(refs)


def _target_refs(
    contracts: Sequence[tuple[Path, FeatureOwnerExecutionContract]],
) -> list[str]:
    refs: list[str] = []
    for _path, contract in contracts:
        refs.extend(
            [
                f"feature:{contract.feature_id}",
                f"graph-set:{contract.graph_set_id}",
                f"feature-graph:{contract.feature_graph_id}",
            ]
        )
        refs.extend(f"lane:{lane_id}" for lane_id in contract.lane_ids)
    return _dedupe(refs)


def _artifacts(
    *,
    contracts: Sequence[tuple[Path, FeatureOwnerExecutionContract]],
    invalid_artifacts: Sequence[tuple[Path, str]],
) -> list[str]:
    return _dedupe(
        [str(path) for path, _contract in contracts]
        + [str(path) for path, _reason in invalid_artifacts]
    )


def _summary(
    contracts: Sequence[tuple[Path, FeatureOwnerExecutionContract]],
) -> str:
    contract_count = len(contracts)
    lane_count = sum(contract.lane_count for _path, contract in contracts)
    ready_count = sum(len(contract.ready_lane_ids) for _path, contract in contracts)
    blocked_count = sum(len(contract.blocked_lane_ids) for _path, contract in contracts)
    completed_count = sum(
        len(contract.completed_lane_ids) for _path, contract in contracts
    )
    blocker_count = sum(len(contract.lane_blockers) for _path, contract in contracts)
    return (
        f"Feature lineage captured {contract_count} feature owner contract(s), "
        f"{lane_count} lane(s): {ready_count} ready, {blocked_count} blocked, "
        f"{completed_count} completed, {blocker_count} blocker reason(s)."
    )


def _ready_set_ref(contract: FeatureOwnerExecutionContract) -> str:
    provenance = contract.ready_set_provenance
    if provenance is None:
        return (
            "ready-set:graph-native:"
            f"{contract.graph_set_id}:{contract.feature_graph_id}"
        )
    return (
        "ready-set:graph-native:"
        f"{provenance.graph_set_id}:{provenance.feature_graph_id}"
    )


def _lane_blocker_refs(contract: FeatureOwnerExecutionContract) -> list[str]:
    return [
        f"lane-blocker:{blocker.lane_id}:{blocker.blocker_ref}"
        for blocker in contract.lane_blockers
    ]


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _dedupe(values: Sequence[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
