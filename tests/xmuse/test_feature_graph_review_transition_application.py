from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_review_transition_application import (
    apply_feature_graph_review_status_transition_plan,
)
from xmuse_core.structuring.feature_graph_review_transitions import (
    build_feature_graph_review_status_transition_plan,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphReviewCoordinatorAction,
    FeatureReviewDecision,
    FeatureReviewVerdict,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


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
    return FeatureReviewVerdict.model_validate(_artifact_payload("feature_review_verdict.v1.json"))


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


def _patch_forward_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_patch_forward_demo",
            "decision": "patch_forward",
            "summary": "A one-line import fix can be patched by reviewer under gate.",
            "patch_forward_gate": {
                "risk": "low",
                "reason_not_rework": "The fix is a one-line import in an existing touched file.",
                "allowed_file_refs": ["src/xmuse_core/agents/provider_session_binding.py"],
                "max_files_changed": 1,
                "max_lines_changed": 5,
                "focused_gates_to_rerun": [
                    "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
                ],
                "disallow_new_dependencies": True,
                "disallow_public_contract_changes": True,
            },
        }
    )


def test_apply_review_transition_plan_writes_graph_status_event(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reviewing_status())
    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_merge_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )

    transitioned = apply_feature_graph_review_status_transition_plan(store, plan)

    assert transitioned.status is FeatureGraphExecutionStatus.MERGED
    assert store.get(
        graph_set_id=plan.graph_set_id,
        feature_graph_id=plan.feature_graph_id,
    ) == transitioned
    events = store.list_events(graph_set_id=plan.graph_set_id)
    assert len(events) == 1
    assert events[0].event_type == "feature_graph_status.transitioned"
    assert events[0].from_status is FeatureGraphExecutionStatus.REVIEWING
    assert events[0].to_status is FeatureGraphExecutionStatus.MERGED


def test_apply_review_transition_plan_replay_is_idempotent(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    store.upsert(_reviewing_status())
    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_merge_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )

    first = apply_feature_graph_review_status_transition_plan(store, plan)
    replay = apply_feature_graph_review_status_transition_plan(store, plan)

    assert replay == first
    assert len(store.list_events(graph_set_id=plan.graph_set_id)) == 1


def test_apply_review_transition_plan_rejects_non_transition_action(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(_reviewing_status())
    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_patch_forward_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )

    assert plan.coordinator_action is FeatureGraphReviewCoordinatorAction.PATCH_FORWARD_GATE
    with pytest.raises(ValueError, match="only transition_status review plans can be applied"):
        apply_feature_graph_review_status_transition_plan(store, plan)

    assert store.get(
        graph_set_id=plan.graph_set_id,
        feature_graph_id=plan.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=plan.graph_set_id) == []


def test_apply_review_transition_plan_revalidates_model_copy_bypass(tmp_path: Path) -> None:
    store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    initial = store.upsert(_reviewing_status())
    plan = build_feature_graph_review_status_transition_plan(
        evidence_bundle=_bundle(),
        verdict=_merge_verdict(),
        current_status=_reviewing_status(),
        updated_at="2026-06-03T02:14:00Z",
    )
    invalid_plan = plan.model_copy(update={"decision": FeatureReviewDecision.PATCH_FORWARD})

    with pytest.raises(
        ValueError,
        match="transition_status action requires merge, rework, or blocked decision",
    ):
        apply_feature_graph_review_status_transition_plan(store, invalid_plan)

    assert store.get(
        graph_set_id=plan.graph_set_id,
        feature_graph_id=plan.feature_graph_id,
    ) == initial
    assert store.list_events(graph_set_id=plan.graph_set_id) == []
