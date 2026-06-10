from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatusRecord,
    ProviderSessionBindingDegradationEvidence,
)


@dataclass(frozen=True)
class FeatureGraphProviderBindingDegradationOutcome:
    evidence: ProviderSessionBindingDegradationEvidence
    status: FeatureGraphExecutionStatusRecord


def record_feature_graph_provider_binding_degradation(
    *,
    store: FeatureGraphStatusStore,
    graph_set_id: str,
    feature_graph_id: str,
    binding_id: str,
    reason: str,
    updated_at: str,
    evidence_refs: list[str],
    failure: str | None = None,
    skip_if_present: bool = False,
) -> FeatureGraphProviderBindingDegradationOutcome:
    evidence = ProviderSessionBindingDegradationEvidence(
        binding_id=binding_id,
        reason=reason,
        evidence_refs=list(evidence_refs),
        failure=failure,
    )
    if skip_if_present:
        existing = _existing_provider_binding_degradation(
            store=store,
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
            binding_id=binding_id,
            reason=reason,
        )
        if existing is not None:
            return FeatureGraphProviderBindingDegradationOutcome(
                evidence=existing.evidence,
                status=existing.status,
            )
    status = store.record_provider_session_binding_degradation(
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
        evidence=evidence,
        updated_at=updated_at,
    )
    return FeatureGraphProviderBindingDegradationOutcome(
        evidence=evidence,
        status=status,
    )


def record_feature_graph_provider_binding_degradation_from_lane(
    *,
    store: FeatureGraphStatusStore,
    lane: dict[str, Any],
    updated_at: str,
    compatibility_bridge_enabled: bool = False,
) -> FeatureGraphProviderBindingDegradationOutcome | None:
    """Record provider binding degradation from migration lane metadata.

    This is a coordinator-facing bridge for the migration period:
    ``feature_lanes.json`` may carry live degradation metadata, but the durable
    execution evidence is written only through ``FeatureGraphStatusStore``.
    """

    if not compatibility_bridge_enabled:
        return None
    if lane.get("provider_session_binding_degraded") is not True:
        return None
    graph_set_id = _optional_text(lane.get("graph_set_id"))
    feature_graph_id = _optional_text(lane.get("graph_id"))
    binding_id = _optional_text(lane.get("provider_session_binding_id"))
    reason = _optional_text(lane.get("provider_session_binding_degraded_reason"))
    if (
        graph_set_id is None
        or feature_graph_id is None
        or binding_id is None
        or reason is None
    ):
        return None

    return record_feature_graph_provider_binding_degradation(
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
        binding_id=binding_id,
        reason=reason,
        updated_at=updated_at,
        evidence_refs=_provider_binding_degradation_evidence_refs(lane, binding_id),
        failure=_optional_text(lane.get("provider_session_binding_failure")),
        store=store,
        skip_if_present=True,
    )


def reconcile_feature_graph_provider_binding_degradations(
    *,
    store: FeatureGraphStatusStore,
    lanes: list[dict[str, Any]],
    updated_at: str,
    compatibility_bridge_enabled: bool = False,
) -> list[FeatureGraphProviderBindingDegradationOutcome]:
    if not compatibility_bridge_enabled:
        return []
    outcomes: list[FeatureGraphProviderBindingDegradationOutcome] = []
    for lane in lanes:
        try:
            outcome = record_feature_graph_provider_binding_degradation_from_lane(
                store=store,
                lane=lane,
                updated_at=updated_at,
                compatibility_bridge_enabled=True,
            )
        except (KeyError, ValueError):
            continue
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes


def _provider_binding_degradation_evidence_refs(
    lane: dict[str, Any],
    binding_id: str,
) -> list[str]:
    refs: list[str] = []
    projection_ref = _optional_text(lane.get("feature_lanes_projection_ref"))
    lane_id = _optional_text(lane.get("feature_id"))
    refs.append(
        projection_ref
        if projection_ref is not None
        else f"feature_lanes.json#lane={lane_id or 'unknown'}"
    )
    refs.append(binding_id)
    return refs


@dataclass(frozen=True)
class _ExistingProviderBindingDegradation:
    evidence: ProviderSessionBindingDegradationEvidence
    status: FeatureGraphExecutionStatusRecord


def _existing_provider_binding_degradation(
    *,
    store: FeatureGraphStatusStore,
    graph_set_id: str,
    feature_graph_id: str,
    binding_id: str,
    reason: str,
) -> _ExistingProviderBindingDegradation | None:
    try:
        status = store.get(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
    except KeyError:
        return None
    for evidence in status.provider_session_binding_degradations:
        if evidence.binding_id == binding_id and evidence.reason == reason:
            return _ExistingProviderBindingDegradation(
                evidence=evidence,
                status=status,
            )
    return None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
