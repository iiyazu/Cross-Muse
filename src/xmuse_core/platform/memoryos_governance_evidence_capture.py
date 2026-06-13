from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from xmuse_core.integrations.memoryos_events import MemoryOSWritebackEvent
from xmuse_core.integrations.memoryos_governance import MemoryOSGovernedWritePlan
from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel

MEMORYOS_GOVERNANCE_ACTION = "memory_governance_policy_evaluated"
MEMORYOS_GOVERNANCE_AUTHORITY = "memoryos_governance_policy"


def capture_memoryos_governance_evidence(
    *,
    run_id: str,
    output_path: str | Path,
    plan_artifacts: Sequence[str | Path] = (),
    writeback_event_artifacts: Sequence[str | Path] = (),
    stage_id: str = "S5",
) -> dict[str, object]:
    plans = [
        *_plans_from_artifacts(plan_artifacts),
        *_plans_from_writeback_events(writeback_event_artifacts),
    ]
    evidence = build_memoryos_governance_evidence(
        run_id=run_id,
        stage_id=stage_id,
        plans=plans,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_memoryos_governance_evidence(
    *,
    run_id: str,
    stage_id: str,
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> dict[str, object]:
    blocked_reasons = _blocked_reasons(plans)
    if not plans:
        status: ProductionEvidenceStatus = "manual_gap"
        proof_level: ProofLevel = "manual_gap"
        blocked_reason = "no MemoryOS governance plans were supplied"
        next_action = "Capture or attach MemoryOS writeback events or governed write plans."
    elif blocked_reasons:
        status = "manual_gap"
        proof_level = "manual_gap"
        blocked_reason = "memory governance blocked plans: " + ", ".join(blocked_reasons)
        next_action = _first_next_action(plans)
    else:
        status = "ok"
        proof_level = "contract_proof"
        blocked_reason = None
        next_action = None
    envelope = ProductionEvidenceEnvelope(
        run_id=run_id,
        stage_id=stage_id,
        action=MEMORYOS_GOVERNANCE_ACTION,
        status=status,
        proof_level=proof_level,
        source_authority=MEMORYOS_GOVERNANCE_AUTHORITY,
        source_refs=tuple(_source_refs(plans)),
        target_refs=tuple(_target_refs(plans)),
        artifacts=tuple(_artifacts(plans)),
        blocked_reason=blocked_reason,
        owner="codex",
        next_action=next_action,
        summary=_summary(plans),
    )
    evidence = envelope.model_dump()
    evidence["memory_governance"] = _memory_governance_details(plans)
    return evidence


def _plans_from_artifacts(
    artifacts: Sequence[str | Path],
) -> list[tuple[str, Path, MemoryOSGovernedWritePlan]]:
    plans: list[tuple[str, Path, MemoryOSGovernedWritePlan]] = []
    for artifact in artifacts:
        path = Path(artifact)
        payload = _read_json(path)
        plans.append((path.stem, path, MemoryOSGovernedWritePlan.model_validate(payload)))
    return plans


def _plans_from_writeback_events(
    artifacts: Sequence[str | Path],
) -> list[tuple[str, Path, MemoryOSGovernedWritePlan]]:
    plans: list[tuple[str, Path, MemoryOSGovernedWritePlan]] = []
    for artifact in artifacts:
        path = Path(artifact)
        payload = _read_json(path)
        event = MemoryOSWritebackEvent.model_validate(payload)
        plans.append((path.stem, path, event.to_governed_write_plan()))
    return plans


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def _source_refs(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> list[str]:
    refs: list[str] = []
    for plan_id, _path, plan in plans:
        refs.append(f"memory-governance:plan:{plan_id}")
        refs.extend(plan.source_refs)
    return _dedupe(refs)


def _target_refs(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> list[str]:
    refs: list[str] = []
    for _plan_id, _path, plan in plans:
        refs.append(plan.target_namespace_uri)
        if plan.shared_namespace_uri is not None:
            refs.append(plan.shared_namespace_uri)
    return _dedupe(refs)


def _artifacts(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> list[str]:
    return _dedupe([str(path) for _plan_id, path, _plan in plans])


def _blocked_reasons(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> list[str]:
    return _dedupe(
        [
            plan.blocked_reason
            for _plan_id, _path, plan in plans
            if plan.status == "blocked" and plan.blocked_reason
        ]
    )


def _first_next_action(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> str | None:
    for _plan_id, _path, plan in plans:
        if plan.status == "blocked" and plan.next_action:
            return plan.next_action
    return None


def _summary(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> str:
    counts = {
        "ingest": 0,
        "promote_to_shared": 0,
        "provider_session_binding_only": 0,
        "blocked": 0,
    }
    for _plan_id, _path, plan in plans:
        counts[plan.decision] += 1
    return (
        f"MemoryOS governance evaluated {len(plans)} plan(s): "
        f"{counts['ingest']} ingest, "
        f"{counts['promote_to_shared']} promote_to_shared, "
        f"{counts['provider_session_binding_only']} provider_session_binding_only, "
        f"{counts['blocked']} blocked."
    )


def _memory_governance_details(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> dict[str, object]:
    counts = _decision_counts(plans)
    return {
        "authority": MEMORYOS_GOVERNANCE_AUTHORITY,
        "plan_count": len(plans),
        "ingest_count": counts["ingest"],
        "promote_to_shared_count": counts["promote_to_shared"],
        "provider_session_binding_only_count": counts[
            "provider_session_binding_only"
        ],
        "blocked_count": counts["blocked"],
        "live_trace_proof": False,
        "write_policy": "governed_rest_ingest_only",
        "plans": [
            _memory_governance_plan_details(plan_id, plan)
            for plan_id, _path, plan in plans
        ],
    }


def _memory_governance_plan_details(
    plan_id: str,
    plan: MemoryOSGovernedWritePlan,
) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "scope": plan.scope.value,
        "event_kind": plan.event_kind,
        "status": plan.status,
        "decision": plan.decision,
        "proof_level": plan.proof_level,
        "target_namespace_uri": plan.target_namespace_uri,
        "shared_namespace_uri": plan.shared_namespace_uri,
        "memory_layer": plan.memory_layer.value,
        "reviewed": plan.metadata.get("xmuse_memory_reviewed") is True,
        "write_request_allowed": plan.to_ingest_request() is not None,
        "source_refs": list(plan.source_refs),
        "blocked_reason": plan.blocked_reason,
        "next_action": plan.next_action,
    }


def _decision_counts(
    plans: Sequence[tuple[str, Path, MemoryOSGovernedWritePlan]],
) -> dict[str, int]:
    counts = {
        "ingest": 0,
        "promote_to_shared": 0,
        "provider_session_binding_only": 0,
        "blocked": 0,
    }
    for _plan_id, _path, plan in plans:
        counts[plan.decision] += 1
    return counts


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
