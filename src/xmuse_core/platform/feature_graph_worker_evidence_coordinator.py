from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_graph_worker_evidence_application import (
    apply_feature_graph_worker_evidence_submission_plan,
)
from xmuse_core.structuring.feature_graph_worker_evidence_submission import (
    build_feature_graph_worker_evidence_submission_plan,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerEvidenceSubmissionPlan,
)


@dataclass(frozen=True)
class FeatureGraphWorkerEvidenceSubmissionOutcome:
    plan: FeatureGraphWorkerEvidenceSubmissionPlan
    status: FeatureGraphExecutionStatusRecord


def submit_feature_graph_worker_evidence(
    *,
    store: FeatureGraphStatusStore,
    evidence_bundle: FeatureEvidenceBundle,
    evidence_bundle_ref: str,
    updated_at: str,
    artifact_store: FeatureGraphArtifactStore | None = None,
) -> FeatureGraphWorkerEvidenceSubmissionOutcome:
    """Submit feature-worker evidence into the graph-native review boundary.

    This helper is coordinator-facing. It consumes a worker-returned
    ``FeatureEvidenceBundle`` and writes only through ``FeatureGraphStatusStore``;
    it does not read or mutate the legacy lane projection.
    """

    bundle = FeatureEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json"))
    current = store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    )
    plan = build_feature_graph_worker_evidence_submission_plan(
        evidence_bundle=bundle,
        current_status=current,
        evidence_bundle_ref=evidence_bundle_ref,
        updated_at=updated_at,
    )
    status = apply_feature_graph_worker_evidence_submission_plan(store, plan)
    if artifact_store is not None:
        artifact_store.save_evidence_bundle(bundle)
    return FeatureGraphWorkerEvidenceSubmissionOutcome(plan=plan, status=status)
