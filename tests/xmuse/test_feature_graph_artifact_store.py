from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardMergeGuardDecision,
    FeatureGraphPatchForwardMergeGuardHandoff,
    FeatureGraphPatchForwardPlan,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverFollowupReviewApplicationRecord,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureReviewDecision,
    FeatureReviewVerdict,
    ReworkPacket,
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


def _verdict() -> FeatureReviewVerdict:
    return FeatureReviewVerdict.model_validate(
        _artifact_payload("feature_review_verdict.v1.json")
    )


def _rework_packet() -> ReworkPacket:
    return ReworkPacket.model_validate(
        _artifact_payload("feature_graph_rework_packet.v1.json")
    )


def _patch_forward_plan() -> FeatureGraphPatchForwardPlan:
    return FeatureGraphPatchForwardPlan.model_validate(
        _artifact_payload("feature_graph_patch_forward_plan.v1.json")
    )


def _patch_forward_gate_result() -> FeatureGraphPatchForwardGateResult:
    return FeatureGraphPatchForwardGateResult.model_validate(
        _artifact_payload("feature_graph_patch_forward_gate_result.v1.json")
    )


def _patch_forward_merge_guard_handoff() -> FeatureGraphPatchForwardMergeGuardHandoff:
    return FeatureGraphPatchForwardMergeGuardHandoff.model_validate(
        _artifact_payload("feature_graph_patch_forward_merge_guard_handoff.v1.json")
    )


def _patch_forward_merge_guard_decision() -> FeatureGraphPatchForwardMergeGuardDecision:
    return FeatureGraphPatchForwardMergeGuardDecision.model_validate(
        _artifact_payload("feature_graph_patch_forward_merge_guard_decision.v1.json")
    )


def _blocked_review_plan() -> FeatureGraphBlockedReviewPlan:
    return FeatureGraphBlockedReviewPlan.model_validate(
        _artifact_payload("feature_graph_blocked_review_plan.v1.json")
    )


def _takeover_plan() -> FeatureGraphTakeoverPlan:
    return FeatureGraphTakeoverPlan.model_validate(
        _artifact_payload("feature_graph_takeover_plan.v1.json")
    )


def _takeover_decision() -> FeatureGraphTakeoverDecision:
    return FeatureGraphTakeoverDecision.model_validate(
        _artifact_payload("feature_graph_takeover_decision.v1.json")
    )


def _takeover_handoff() -> FeatureGraphTakeoverHandoff:
    return FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )


def _takeover_outcome() -> FeatureGraphTakeoverOutcome:
    return FeatureGraphTakeoverOutcome.model_validate(
        _artifact_payload("feature_graph_takeover_outcome.v1.json")
    )


def _takeover_review_handoff() -> FeatureGraphTakeoverReviewHandoff:
    return FeatureGraphTakeoverReviewHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_review_handoff.v1.json")
    )


def _takeover_followup_review_application() -> (
    FeatureGraphTakeoverFollowupReviewApplicationRecord
):
    return FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
        _artifact_payload("feature_graph_takeover_followup_review_application.v1.json")
    )


def _write_artifact_store_payload(
    path: Path,
    *,
    collection_name: str,
    rows: list[dict],
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                collection_name: rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_feature_graph_artifact_store_saves_and_reads_evidence_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    bundle = _bundle()

    saved = store.save_evidence_bundle(bundle)

    assert saved == bundle
    assert store.get_evidence_bundle("fevb_demo") == bundle
    assert store.list_evidence_bundles_for_feature_graph(
        graph_set_id="gs-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
    ) == [bundle]
    raw = json.loads((tmp_path / "feature_graph_artifacts.json").read_text())
    assert raw["schema_version"] == "xmuse.feature_graph_artifacts.v1"
    assert raw["evidence_bundles"][0]["bundle_id"] == "fevb_demo"


def test_feature_graph_artifact_store_upserts_evidence_bundle_idempotently(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    bundle = _bundle()

    store.save_evidence_bundle(bundle)
    store.save_evidence_bundle(bundle)

    assert store.list_evidence_bundles() == [bundle]


def test_feature_graph_artifact_store_rejects_conflicting_evidence_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    bundle = _bundle()
    store.save_evidence_bundle(bundle)
    conflicting = bundle.model_copy(update={"feature_goal": "Conflicting worker evidence."})

    with pytest.raises(ValueError, match="evidence bundle replay conflict"):
        store.save_evidence_bundle(conflicting)

    assert store.get_evidence_bundle(bundle.bundle_id) == bundle
    assert store.list_evidence_bundles() == [bundle]


def test_feature_graph_artifact_store_rejects_conflicting_persisted_evidence_bundle_replay(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    bundle = _bundle()
    conflicting = bundle.model_copy(
        update={"feature_goal": "Conflicting persisted worker evidence."}
    )
    _write_artifact_store_payload(
        store_path,
        collection_name="evidence_bundles",
        rows=[
            bundle.model_dump(mode="json"),
            conflicting.model_dump(mode="json"),
        ],
    )
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(
        ValueError,
        match="feature graph artifact replay conflict",
    ):
        store.list_evidence_bundles()


def test_feature_graph_artifact_store_rejects_duplicate_persisted_review_verdict_replay(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    verdict = _verdict()
    _write_artifact_store_payload(
        store_path,
        collection_name="review_verdicts",
        rows=[
            verdict.model_dump(mode="json"),
            verdict.model_dump(mode="json"),
        ],
    )
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(
        ValueError,
        match="duplicate feature graph artifact identity",
    ):
        store.list_review_verdicts()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"bundle_id": "fevb-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_evidence_bundle_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "evidence_bundles": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_evidence_bundle(_bundle())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_filters_feature_graph_artifacts(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    target = _bundle()
    other = target.model_copy(
        update={
            "bundle_id": "fevb-other",
            "feature_graph_id": "graph-other",
            "lane_graph_summary": target.lane_graph_summary.model_copy(
                update={"feature_graph_id": "graph-other"}
            ),
        }
    )

    store.save_evidence_bundle(other)
    store.save_evidence_bundle(target)

    assert store.list_evidence_bundles_for_feature_graph(
        graph_set_id="gs-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
    ) == [target]


def test_feature_graph_artifact_store_saves_review_verdicts_by_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    verdict = _verdict()

    saved = store.save_review_verdict(verdict)

    assert saved == verdict
    assert store.get_review_verdict("fverdict_merge_demo") == verdict
    assert store.list_review_verdicts_for_evidence_bundle("fevb_demo") == [verdict]

    replayed = store.save_review_verdict(verdict)

    assert replayed == verdict
    assert store.list_review_verdicts_for_evidence_bundle("fevb_demo") == [verdict]


def test_feature_graph_artifact_store_rejects_conflicting_review_verdict(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    verdict = _verdict()
    store.save_review_verdict(verdict)
    conflicting = verdict.model_copy(update={"summary": "Conflicting reviewer summary."})

    with pytest.raises(ValueError, match="review verdict replay conflict"):
        store.save_review_verdict(conflicting)

    assert store.get_review_verdict(verdict.verdict_id) == verdict
    assert store.list_review_verdicts() == [verdict]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"verdict_id": "fverdict-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_review_verdict_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "review_verdicts": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_review_verdict(_verdict())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_revalidates_review_verdict_bypass(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    initial = store.save_review_verdict(_verdict())
    invalid = initial.model_copy(
        update={
            "decision": FeatureReviewDecision.REWORK,
            "blocking_findings": [],
        }
    )

    with pytest.raises(ValueError, match="rework verdicts require blocking_findings"):
        store.save_review_verdict(invalid)

    assert store.get_review_verdict("fverdict_merge_demo") == initial
    assert store.list_review_verdicts() == [initial]


def test_feature_graph_artifact_store_saves_rework_packets_by_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    packet = _rework_packet()

    saved = store.save_rework_packet(packet)

    assert saved == packet
    assert (
        store.get_rework_packet("rework:fverdict_rework_demo:fevb_demo:20260603T021500z")
        == packet
    )
    assert store.list_rework_packets_for_evidence_bundle("fevb_demo") == [packet]

    replayed = store.save_rework_packet(packet)

    assert replayed == packet
    assert store.list_rework_packets_for_evidence_bundle("fevb_demo") == [packet]


def test_feature_graph_artifact_store_rejects_conflicting_rework_packet(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    packet = _rework_packet()
    store.save_rework_packet(packet)
    conflicting = packet.model_copy(update={"required_changes": ["Conflicting rework step."]})

    with pytest.raises(ValueError, match="rework packet replay conflict"):
        store.save_rework_packet(conflicting)

    assert store.get_rework_packet(packet.rework_id) == packet
    assert store.list_rework_packets() == [packet]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"rework_id": "rework-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_rework_packet_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "rework_packets": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_rework_packet(_rework_packet())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_patch_forward_plans_by_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()

    saved = store.save_patch_forward_plan(plan)

    assert saved == plan
    assert (
        store.get_patch_forward_plan(
            "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z"
        )
        == plan
    )
    assert store.list_patch_forward_plans_for_evidence_bundle("fevb_demo") == [plan]

    replayed = store.save_patch_forward_plan(plan)

    assert replayed == plan
    assert store.list_patch_forward_plans_for_evidence_bundle("fevb_demo") == [plan]


def test_feature_graph_artifact_store_rejects_conflicting_patch_forward_plan(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    store.save_patch_forward_plan(plan)
    conflicting = plan.model_copy(update={"rationale": "Conflicting patch-forward rationale."})

    with pytest.raises(ValueError, match="patch-forward plan replay conflict"):
        store.save_patch_forward_plan(conflicting)

    assert store.get_patch_forward_plan(plan.plan_id) == plan
    assert store.list_patch_forward_plans() == [plan]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"plan_id": "fgpf-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_patch_forward_plan_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "patch_forward_plans": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_patch_forward_plan(_patch_forward_plan())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_patch_forward_gate_results(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    result = _patch_forward_gate_result()

    saved = store.save_patch_forward_gate_result(result)

    assert saved == result
    assert (
        store.get_patch_forward_gate_result(
            "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
        )
        == result
    )
    assert store.list_patch_forward_gate_results_for_evidence_bundle("fevb_demo") == [
        result
    ]
    assert store.list_patch_forward_gate_results_for_plan(
        "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z"
    ) == [result]

    replayed = store.save_patch_forward_gate_result(result)

    assert replayed == result
    assert store.list_patch_forward_gate_results_for_plan(
        "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z"
    ) == [result]


def test_feature_graph_artifact_store_rejects_conflicting_patch_forward_gate_result(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    result = _patch_forward_gate_result()
    store.save_patch_forward_gate_result(result)
    conflicting = result.model_copy(
        update={"verification_summary": "Conflicting patch-forward gate result."}
    )

    with pytest.raises(ValueError, match="patch-forward gate result replay conflict"):
        store.save_patch_forward_gate_result(conflicting)

    assert store.get_patch_forward_gate_result(result.result_id) == result
    assert store.list_patch_forward_gate_results() == [result]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"result_id": "fgpfr-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_patch_forward_gate_result_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "patch_forward_gate_results": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_patch_forward_gate_result(_patch_forward_gate_result())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_patch_forward_merge_guard_handoffs(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    handoff = _patch_forward_merge_guard_handoff()

    saved = store.save_patch_forward_merge_guard_handoff(handoff)

    assert saved == handoff
    assert (
        store.get_patch_forward_merge_guard_handoff(
            "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
        )
        == handoff
    )
    assert store.list_patch_forward_merge_guard_handoffs_for_gate_result(
        "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    ) == [handoff]

    replayed = store.save_patch_forward_merge_guard_handoff(handoff)

    assert replayed == handoff
    assert store.list_patch_forward_merge_guard_handoffs_for_gate_result(
        "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    ) == [handoff]


def test_feature_graph_artifact_store_rejects_conflicting_patch_forward_merge_guard_handoff(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    handoff = _patch_forward_merge_guard_handoff()
    store.save_patch_forward_merge_guard_handoff(handoff)
    conflicting = handoff.model_copy(
        update={
            "required_merge_guard_checks": [
                "Conflicting patch-forward merge guard check."
            ]
        }
    )

    with pytest.raises(ValueError, match="merge guard handoff replay conflict"):
        store.save_patch_forward_merge_guard_handoff(conflicting)

    assert store.get_patch_forward_merge_guard_handoff(handoff.handoff_id) == handoff
    assert store.list_patch_forward_merge_guard_handoffs() == [handoff]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"handoff_id": "fgpfmgh-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_patch_forward_merge_guard_handoff_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "patch_forward_merge_guard_handoffs": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_patch_forward_merge_guard_handoff(
            _patch_forward_merge_guard_handoff()
        )

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_patch_forward_merge_guard_decisions(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    decision = _patch_forward_merge_guard_decision()

    saved = store.save_patch_forward_merge_guard_decision(decision)

    assert saved == decision
    assert (
        store.get_patch_forward_merge_guard_decision(
            "fgpfmgd:fgpfmgh:fgpfr:fverdict_patch_forward_demo:"
            "fevb_demo:20260603T021900z:20260603T022200z"
        )
        == decision
    )
    assert store.list_patch_forward_merge_guard_decisions_for_handoff(
        "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    ) == [decision]

    replayed = store.save_patch_forward_merge_guard_decision(decision)

    assert replayed == decision
    assert store.list_patch_forward_merge_guard_decisions_for_handoff(
        "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    ) == [decision]


def test_feature_graph_artifact_store_rejects_conflicting_patch_forward_merge_guard_decision(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    decision = _patch_forward_merge_guard_decision()
    store.save_patch_forward_merge_guard_decision(decision)
    conflicting = decision.model_copy(
        update={"merge_guard_ref": "logs/merge_guard/conflicting-patch-forward.json"}
    )

    with pytest.raises(ValueError, match="merge guard decision replay conflict"):
        store.save_patch_forward_merge_guard_decision(conflicting)

    assert store.get_patch_forward_merge_guard_decision(decision.decision_id) == decision
    assert store.list_patch_forward_merge_guard_decisions() == [decision]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"decision_id": "fgpfmgd-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_patch_forward_merge_guard_decision_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "patch_forward_merge_guard_decisions": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_patch_forward_merge_guard_decision(
            _patch_forward_merge_guard_decision()
        )

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_blocked_review_plans_by_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _blocked_review_plan()

    saved = store.save_blocked_review_plan(plan)

    assert saved == plan
    assert (
        store.get_blocked_review_plan(
            "fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021700z"
        )
        == plan
    )
    assert store.list_blocked_review_plans_for_evidence_bundle("fevb_demo") == [plan]

    replayed = store.save_blocked_review_plan(plan)

    assert replayed == plan
    assert store.list_blocked_review_plans_for_evidence_bundle("fevb_demo") == [plan]


def test_feature_graph_artifact_store_rejects_conflicting_blocked_review_plan(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _blocked_review_plan()
    store.save_blocked_review_plan(plan)
    conflicting = plan.model_copy(
        update={"blocked_reason": "Conflicting blocked review reason."}
    )

    with pytest.raises(ValueError, match="blocked review plan replay conflict"):
        store.save_blocked_review_plan(conflicting)

    assert store.get_blocked_review_plan(plan.plan_id) == plan
    assert store.list_blocked_review_plans() == [plan]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"plan_id": "fgblocked-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_blocked_review_plan_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "blocked_review_plans": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_blocked_review_plan(_blocked_review_plan())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_takeover_plans_by_bundle(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _takeover_plan()

    saved = store.save_takeover_plan(plan)

    assert saved == plan
    assert (
        store.get_takeover_plan(
            "fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T022000z"
        )
        == plan
    )
    assert store.list_takeover_plans_for_evidence_bundle("fevb_demo") == [plan]

    replayed = store.save_takeover_plan(plan)

    assert replayed == plan
    assert store.list_takeover_plans_for_evidence_bundle("fevb_demo") == [plan]


def test_feature_graph_artifact_store_rejects_conflicting_takeover_plan(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _takeover_plan()
    store.save_takeover_plan(plan)
    conflicting = plan.model_copy(update={"takeover_reason": "Conflicting takeover reason."})

    with pytest.raises(ValueError, match="takeover plan replay conflict"):
        store.save_takeover_plan(conflicting)

    assert store.get_takeover_plan(plan.plan_id) == plan
    assert store.list_takeover_plans() == [plan]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"plan_id": "fgtakeover-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_takeover_plan_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "takeover_plans": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_takeover_plan(_takeover_plan())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_takeover_decisions_by_plan(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = store.save_takeover_plan(_takeover_plan())
    decision = _takeover_decision()

    saved = store.save_takeover_decision(decision)

    assert saved == decision
    assert store.get_takeover_decision(decision.decision_id) == decision
    assert store.list_takeover_decisions_for_plan(plan.plan_id) == [decision]

    replayed = store.save_takeover_decision(decision)

    assert replayed == decision
    assert store.list_takeover_decisions_for_plan(plan.plan_id) == [decision]


def test_feature_graph_artifact_store_rejects_conflicting_takeover_decision(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    decision = _takeover_decision()
    store.save_takeover_decision(decision)
    conflicting = decision.model_copy(
        update={"takeover_reason": "Conflicting takeover gate decision."}
    )

    with pytest.raises(ValueError, match="takeover decision replay conflict"):
        store.save_takeover_decision(conflicting)

    assert store.get_takeover_decision(decision.decision_id) == decision
    assert store.list_takeover_decisions() == [decision]


def test_feature_graph_artifact_store_saves_takeover_handoffs_by_decision(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    decision = _takeover_decision()
    handoff = _takeover_handoff()

    saved = store.save_takeover_handoff(handoff)

    assert saved == handoff
    assert store.get_takeover_handoff(handoff.handoff_id) == handoff
    assert store.list_takeover_handoffs_for_decision(decision.decision_id) == [
        handoff
    ]

    replayed = store.save_takeover_handoff(handoff)

    assert replayed == handoff
    assert store.list_takeover_handoffs_for_decision(decision.decision_id) == [
        handoff
    ]


def test_feature_graph_artifact_store_rejects_conflicting_takeover_handoff(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    handoff = _takeover_handoff()
    store.save_takeover_handoff(handoff)
    conflicting = handoff.model_copy(
        update={
            "required_takeover_checks": [
                *handoff.required_takeover_checks,
                "verify_conflicting_handoff",
            ],
        }
    )

    with pytest.raises(ValueError, match="takeover handoff replay conflict"):
        store.save_takeover_handoff(conflicting)

    assert store.get_takeover_handoff(handoff.handoff_id) == handoff
    assert store.list_takeover_handoffs() == [handoff]


def test_feature_graph_artifact_store_saves_takeover_outcomes_by_handoff(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    handoff = _takeover_handoff()
    outcome = _takeover_outcome()

    saved = store.save_takeover_outcome(outcome)

    assert saved == outcome
    assert store.get_takeover_outcome(outcome.outcome_id) == outcome
    assert store.list_takeover_outcomes_for_handoff(handoff.handoff_id) == [outcome]

    replayed = store.save_takeover_outcome(outcome)

    assert replayed == outcome
    assert store.list_takeover_outcomes_for_handoff(handoff.handoff_id) == [outcome]


def test_feature_graph_artifact_store_rejects_conflicting_takeover_outcome(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    outcome = _takeover_outcome()
    store.save_takeover_outcome(outcome)
    conflicting = outcome.model_copy(update={"output_summary": "Conflicting outcome."})

    with pytest.raises(ValueError, match="takeover outcome replay conflict"):
        store.save_takeover_outcome(conflicting)

    assert store.get_takeover_outcome(outcome.outcome_id) == outcome
    assert store.list_takeover_outcomes() == [outcome]


def test_feature_graph_artifact_store_saves_takeover_review_handoffs_by_outcome(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    outcome = _takeover_outcome()
    handoff = _takeover_review_handoff()

    saved = store.save_takeover_review_handoff(handoff)

    assert saved == handoff
    assert store.get_takeover_review_handoff(handoff.review_handoff_id) == handoff
    assert store.list_takeover_review_handoffs_for_outcome(outcome.outcome_id) == [
        handoff
    ]

    replayed = store.save_takeover_review_handoff(handoff)

    assert replayed == handoff
    assert store.list_takeover_review_handoffs_for_outcome(outcome.outcome_id) == [
        handoff
    ]


def test_feature_graph_artifact_store_rejects_conflicting_takeover_review_handoff(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    handoff = _takeover_review_handoff()
    store.save_takeover_review_handoff(handoff)
    conflicting = handoff.model_copy(
        update={
            "reviewer_input_refs": [
                *handoff.reviewer_input_refs,
                "feature_graph_takeover_outcome:conflicting:v1",
            ],
        }
    )

    with pytest.raises(ValueError, match="takeover review handoff replay conflict"):
        store.save_takeover_review_handoff(conflicting)

    assert store.get_takeover_review_handoff(handoff.review_handoff_id) == handoff
    assert store.list_takeover_review_handoffs() == [handoff]


@pytest.mark.parametrize(
    ("collection_name", "rows", "message"),
    [
        ("takeover_decisions", {"decision_id": "fgtd-corrupt"}, "must be a list"),
        ("takeover_decisions", ["not-an-object"], "entries must be objects"),
        ("takeover_handoffs", {"handoff_id": "fgth-corrupt"}, "must be a list"),
        ("takeover_handoffs", ["not-an-object"], "entries must be objects"),
        ("takeover_outcomes", {"outcome_id": "fgto-corrupt"}, "must be a list"),
        ("takeover_outcomes", ["not-an-object"], "entries must be objects"),
        (
            "takeover_review_handoffs",
            {"review_handoff_id": "fgtrh-corrupt"},
            "must be a list",
        ),
        (
            "takeover_review_handoffs",
            ["not-an-object"],
            "entries must be objects",
        ),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_takeover_chain_collections(
    tmp_path: Path,
    collection_name: str,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                collection_name: rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        if collection_name == "takeover_decisions":
            store.save_takeover_decision(_takeover_decision())
        elif collection_name == "takeover_handoffs":
            store.save_takeover_handoff(_takeover_handoff())
        elif collection_name == "takeover_outcomes":
            store.save_takeover_outcome(_takeover_outcome())
        else:
            store.save_takeover_review_handoff(_takeover_review_handoff())

    assert store_path.read_text(encoding="utf-8") == before


def test_feature_graph_artifact_store_saves_takeover_followup_applications_by_handoff(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    handoff = _takeover_review_handoff()
    application = _takeover_followup_review_application()

    saved = store.save_takeover_followup_review_application(application)

    assert saved == application
    assert (
        store.get_takeover_followup_review_application(application.application_id)
        == application
    )
    assert store.list_takeover_followup_review_applications_for_handoff(
        handoff.review_handoff_id
    ) == [application]

    replayed = store.save_takeover_followup_review_application(application)

    assert replayed == application
    assert store.list_takeover_followup_review_applications_for_handoff(
        handoff.review_handoff_id
    ) == [application]


def test_feature_graph_artifact_store_rejects_conflicting_takeover_followup_application(
    tmp_path: Path,
) -> None:
    store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    application = _takeover_followup_review_application()
    store.save_takeover_followup_review_application(application)
    conflicting = application.model_copy(
        update={
            "output_refs": [
                *application.output_refs,
                "feature_graph_status:fgs-conflicting:v1",
            ],
        }
    )

    with pytest.raises(ValueError, match="application replay conflict"):
        store.save_takeover_followup_review_application(conflicting)

    assert store.get_takeover_followup_review_application(
        application.application_id
    ) == application


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ({"application_id": "fgtrha-corrupt"}, "must be a list"),
        (["not-an-object"], "entries must be objects"),
    ],
)
def test_feature_graph_artifact_store_rejects_corrupt_takeover_followup_collection(
    tmp_path: Path,
    rows: object,
    message: str,
) -> None:
    store_path = tmp_path / "feature_graph_artifacts.json"
    store_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.feature_graph_artifacts.v1",
                "takeover_followup_review_applications": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")
    store = FeatureGraphArtifactStore(store_path)

    with pytest.raises(ValueError, match=message):
        store.save_takeover_followup_review_application(
            _takeover_followup_review_application()
        )

    assert store_path.read_text(encoding="utf-8") == before
