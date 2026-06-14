from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.platform.feature_graph_worker_evidence_coordinator import (
    submit_feature_graph_worker_evidence,
)
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
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphWorkerEvidenceSubmissionPlan,
    ProviderSessionBindingDegradationEvidence,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


class RacingFeatureGraphStatusStore(FeatureGraphStatusStore):
    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        self._raced = False

    def get(
        self,
        *,
        graph_set_id: str,
        feature_graph_id: str,
    ) -> FeatureGraphExecutionStatusRecord:
        current = super().get(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
        if not self._raced and current.status is FeatureGraphExecutionStatus.RUNNING:
            self._raced = True
            blocked = current.model_copy(
                update={
                    "status_id": "fgstatus_blocked_race",
                    "status": FeatureGraphExecutionStatus.BLOCKED,
                    "updated_at": "2026-06-03T02:16:45Z",
                }
            )
            super().transition(
                blocked,
                expected_status=FeatureGraphExecutionStatus.RUNNING,
            )
        return current


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _bundle() -> FeatureEvidenceBundle:
    return FeatureEvidenceBundle.model_validate(
        _artifact_payload("feature_evidence_bundle.v1.json")
    )


def _running_status() -> FeatureGraphExecutionStatusRecord:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status_running_claim.v1.json")
    )
    return status.model_copy(update={"active_worker_session_id": "god-worker-demo"})


def _submission_plan() -> FeatureGraphWorkerEvidenceSubmissionPlan:
    return build_feature_graph_worker_evidence_submission_plan(
        evidence_bundle=_bundle(),
        current_status=_running_status(),
        evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
        updated_at="2026-06-03T02:17:00Z",
    )


def test_feature_graph_worker_evidence_submission_plan_golden_fixture_is_stable() -> None:
    plan = _submission_plan()

    assert plan.current_status is FeatureGraphExecutionStatus.RUNNING
    assert plan.expected_status is FeatureGraphExecutionStatus.RUNNING
    assert plan.target_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.target_status_record.status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.target_status_record.completed_lane_ids == ["binding-schema"]
    assert plan.target_status_record.active_worker_session_id == "god-worker-demo"
    assert (
        plan.target_status_record.active_provider_session_binding_ref
        == "provider_session_binding:psb_demo:v1"
    )
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_worker_evidence_submission_plan.v1.json"
    )


def test_worker_evidence_submission_preserves_blueprint_proof_level() -> None:
    current = _running_status().model_copy(
        update={"blueprint_proof_level": "opt_in_live_proof"}
    )

    plan = build_feature_graph_worker_evidence_submission_plan(
        evidence_bundle=_bundle(),
        current_status=current,
        evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
        updated_at="2026-06-03T02:17:00Z",
    )

    assert plan.target_status_record.blueprint_proof_level == "opt_in_live_proof"


def test_worker_evidence_submission_rejects_blueprint_proof_level_mismatch() -> None:
    current = _running_status().model_copy(
        update={"blueprint_proof_level": "opt_in_live_proof"}
    )
    bundle = _bundle().model_copy(update={"blueprint_proof_level": "contract_proof"})

    with pytest.raises(
        ValueError,
        match="evidence bundle blueprint_proof_level must match current status",
    ):
        build_feature_graph_worker_evidence_submission_plan(
            evidence_bundle=bundle,
            current_status=current,
            evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
            updated_at="2026-06-03T02:17:00Z",
        )


def test_worker_evidence_submission_plan_requires_running_status() -> None:
    with pytest.raises(ValueError, match="worker evidence submission requires running status"):
        build_feature_graph_worker_evidence_submission_plan(
            evidence_bundle=_bundle(),
            current_status=_running_status().model_copy(
                update={"status": FeatureGraphExecutionStatus.READY}
            ),
            evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
            updated_at="2026-06-03T02:17:00Z",
        )


def test_worker_evidence_submission_plan_requires_claimed_worker_binding() -> None:
    mismatched = _running_status().model_copy(
        update={
            "active_worker_session_id": "god-worker-other",
            "active_provider_session_binding_ref": "provider_session_binding:psb_other:v1",
        }
    )

    with pytest.raises(ValueError, match="current status active_worker_session_id"):
        build_feature_graph_worker_evidence_submission_plan(
            evidence_bundle=_bundle(),
            current_status=mismatched,
            evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
            updated_at="2026-06-03T02:17:00Z",
        )


def test_apply_worker_evidence_submission_plan_writes_reviewing_status_event(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_running_status())
    projection_path = tmp_path / "feature_lanes.json"
    projection_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = projection_path.read_text(encoding="utf-8")

    reviewing = apply_feature_graph_worker_evidence_submission_plan(
        store,
        _submission_plan(),
    )

    assert reviewing.status is FeatureGraphExecutionStatus.REVIEWING
    assert reviewing.ready_lane_ids == []
    assert reviewing.active_lane_ids == []
    assert reviewing.completed_lane_ids == ["binding-schema"]
    assert reviewing.active_worker_session_id == "god-worker-demo"
    assert store.get(
        graph_set_id="gs-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
    ) == reviewing
    events = store.list_events(graph_set_id="gs-xmuse-hardening")
    assert len(events) == 1
    assert events[0].from_status is FeatureGraphExecutionStatus.RUNNING
    assert events[0].to_status is FeatureGraphExecutionStatus.REVIEWING
    assert projection_path.read_text(encoding="utf-8") == before_projection


def test_submit_worker_evidence_persists_bundle_after_status_gate_passes(
    tmp_path: Path,
) -> None:
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    bundle = _bundle()
    status_store.upsert(_running_status())

    outcome = submit_feature_graph_worker_evidence(
        store=status_store,
        artifact_store=artifact_store,
        evidence_bundle=bundle,
        evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
        updated_at="2026-06-03T02:17:00Z",
    )

    assert outcome.plan.source_status_id == _running_status().status_id
    assert outcome.status.status is FeatureGraphExecutionStatus.REVIEWING
    assert artifact_store.get_evidence_bundle(bundle.bundle_id) == bundle
    events = status_store.list_events(graph_set_id=bundle.graph_set_id)
    assert len(events) == 1
    assert events[0].to_status is FeatureGraphExecutionStatus.REVIEWING


def test_submit_worker_evidence_does_not_persist_bundle_when_status_gate_fails(
    tmp_path: Path,
) -> None:
    status_store = RacingFeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_running_status())

    with pytest.raises(ValueError, match="expected feature graph status running"):
        submit_feature_graph_worker_evidence(
            store=status_store,
            artifact_store=artifact_store,
            evidence_bundle=_bundle(),
            evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
            updated_at="2026-06-03T02:17:00Z",
        )

    assert artifact_store.list_evidence_bundles() == []
    current = status_store.get(
        graph_set_id="gs-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
    )
    assert current.status is FeatureGraphExecutionStatus.BLOCKED


def test_submit_worker_evidence_duplicate_replay_does_not_double_write(
    tmp_path: Path,
) -> None:
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    bundle = _bundle()
    status_store.upsert(_running_status())

    first = submit_feature_graph_worker_evidence(
        store=status_store,
        artifact_store=artifact_store,
        evidence_bundle=bundle,
        evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
        updated_at="2026-06-03T02:17:00Z",
    )

    with pytest.raises(ValueError, match="worker evidence submission requires running status"):
        submit_feature_graph_worker_evidence(
            store=status_store,
            artifact_store=artifact_store,
            evidence_bundle=bundle,
            evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
            updated_at="2026-06-03T02:17:00Z",
        )

    assert artifact_store.list_evidence_bundles() == [bundle]
    events = status_store.list_events(graph_set_id=bundle.graph_set_id)
    assert len(events) == 1
    assert events[0].to_status is FeatureGraphExecutionStatus.REVIEWING
    assert (
        status_store.get(
            graph_set_id=bundle.graph_set_id,
            feature_graph_id=bundle.feature_graph_id,
        )
        == first.status
    )


def test_worker_evidence_submission_preserves_provider_binding_degradations() -> None:
    degradation = ProviderSessionBindingDegradationEvidence(
        binding_id="provider_session_binding:psb_demo:v1",
        reason="upsert_failed",
        failure="provider store write failed",
        evidence_refs=["feature_lanes.json#lane=binding-schema"],
    )
    current = _running_status().model_copy(
        update={"provider_session_binding_degradations": [degradation]}
    )

    plan = build_feature_graph_worker_evidence_submission_plan(
        evidence_bundle=_bundle(),
        current_status=current,
        evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
        updated_at="2026-06-03T02:17:00Z",
    )

    assert plan.target_status_record.provider_session_binding_degradations == [
        degradation
    ]


def test_apply_worker_evidence_submission_plan_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_running_status())
    plan = _submission_plan()

    first = apply_feature_graph_worker_evidence_submission_plan(store, plan)
    replay = apply_feature_graph_worker_evidence_submission_plan(store, plan)

    assert replay == first
    assert len(store.list_events(graph_set_id="gs-xmuse-hardening")) == 1


def test_apply_worker_evidence_submission_plan_revalidates_model_copy_bypass(
    tmp_path: Path,
) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(_running_status())
    plan = _submission_plan()
    invalid_plan = plan.model_copy(
        update={
            "expected_status": FeatureGraphExecutionStatus.REVIEWING,
            "target_status": FeatureGraphExecutionStatus.MERGED,
        }
    )

    with pytest.raises(ValueError, match="current_status must match expected_status"):
        apply_feature_graph_worker_evidence_submission_plan(store, invalid_plan)

    assert store.get(
        graph_set_id=plan.graph_set_id,
        feature_graph_id=plan.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=plan.graph_set_id) == []
