from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.platform.feature_graph_review_coordinator import (
    submit_feature_graph_review_verdict,
)
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureReviewVerdict,
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
        if not self._raced and current.status is FeatureGraphExecutionStatus.REVIEWING:
            self._raced = True
            blocked = current.model_copy(
                update={
                    "status_id": "fgstatus_blocked_race",
                    "status": FeatureGraphExecutionStatus.BLOCKED,
                    "updated_at": "2026-06-03T02:13:45Z",
                }
            )
            super().transition(
                blocked,
                expected_status=FeatureGraphExecutionStatus.REVIEWING,
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


def _merge_verdict() -> FeatureReviewVerdict:
    return FeatureReviewVerdict.model_validate(
        _artifact_payload("feature_review_verdict.v1.json")
    )


def _reviewing_status() -> FeatureGraphExecutionStatusRecord:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )
    return status.model_copy(
        update={
            "status_id": "fgstatus_reviewing_demo",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "ready_lane_ids": [],
            "active_lane_ids": [],
            "completed_lane_ids": ["binding-schema"],
            "updated_at": "2026-06-03T02:13:30Z",
        }
    )


def test_submit_review_verdict_does_not_persist_artifacts_when_transition_gate_fails(
    tmp_path: Path,
) -> None:
    status_store = RacingFeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_reviewing_status())

    with pytest.raises(ValueError, match="expected feature graph status reviewing"):
        submit_feature_graph_review_verdict(
            store=status_store,
            artifact_store=artifact_store,
            evidence_bundle=_bundle(),
            verdict=_merge_verdict(),
            updated_at="2026-06-03T02:14:00Z",
        )

    assert artifact_store.list_review_verdicts() == []
    assert artifact_store.list_rework_packets() == []
    current = status_store.get(
        graph_set_id="gs-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
    )
    assert current.status is FeatureGraphExecutionStatus.BLOCKED
