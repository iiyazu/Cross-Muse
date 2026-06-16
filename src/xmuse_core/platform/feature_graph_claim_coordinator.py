from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_graph_worker_claim_application import (
    apply_feature_graph_worker_claim_plan,
)
from xmuse_core.structuring.feature_graph_worker_claims import (
    build_feature_graph_worker_claim_plan,
)
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerClaimPlan,
)


@dataclass(frozen=True)
class FeatureGraphWorkerClaimOutcome:
    plan: FeatureGraphWorkerClaimPlan
    status: FeatureGraphExecutionStatusRecord


def claim_next_ready_feature_graph_worker(
    *,
    store: FeatureGraphStatusStore,
    worker_session_id: str,
    provider_session_binding_ref: str | None,
    updated_at: str,
    graph_set_id: str | None = None,
    conversation_id: str | None = None,
    feature_graph_id: str | None = None,
    active_lane_ids: list[str] | None = None,
) -> FeatureGraphWorkerClaimOutcome | None:
    """Claim one graph-native ready feature graph for a feature worker.

    This helper is a coordinator-facing shadow path. It intentionally consumes
    only ``FeatureGraphStatusStore`` state and does not read or mutate the
    legacy lane projection.
    """

    candidates = store.list_ready(
        graph_set_id=graph_set_id,
        conversation_id=conversation_id,
    )
    if feature_graph_id is not None:
        candidates = [
            record
            for record in candidates
            if record.feature_graph_id == feature_graph_id
        ]
    if not candidates:
        return None
    current = sorted(
        candidates,
        key=lambda record: (
            record.updated_at,
            record.graph_set_id,
            record.feature_graph_id,
            record.feature_id,
        ),
    )[0]
    plan = build_feature_graph_worker_claim_plan(
        current_status=current,
        worker_session_id=worker_session_id,
        provider_session_binding_ref=provider_session_binding_ref,
        updated_at=updated_at,
        active_lane_ids=active_lane_ids,
    )
    status = apply_feature_graph_worker_claim_plan(store, plan)
    return FeatureGraphWorkerClaimOutcome(plan=plan, status=status)
