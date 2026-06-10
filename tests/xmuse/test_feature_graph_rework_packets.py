from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_rework_packets import (
    build_feature_graph_rework_packet,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
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


def _rework_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_rework_demo",
            "decision": "rework",
            "summary": "Focused verification is missing for stale binding recovery.",
            "blocking_findings": [
                {
                    "finding_id": "finding-stale-binding",
                    "severity": "blocking",
                    "summary": "Add a stale binding recovery regression test.",
                    "evidence_refs": ["feature_evidence_bundle:fevb_demo:v1"],
                }
            ],
        }
    )


def test_rework_verdict_builds_same_worker_rework_packet() -> None:
    packet = build_feature_graph_rework_packet(
        evidence_bundle=_bundle(),
        verdict=_rework_verdict(),
        rework_id="rework:fverdict_rework_demo:fevb_demo:20260603T021500z",
        max_remaining_attempts=1,
        created_at="2026-06-03T02:15:00Z",
    )

    assert packet.source_verdict_id == "fverdict_rework_demo"
    assert packet.target_worker_session_id == "god-worker-demo"
    assert packet.target_provider_session_binding_ref == "provider_session_binding:psb_demo:v1"
    assert packet.required_changes == ["Add a stale binding recovery regression test."]
    assert packet.gates_to_rerun == [
        "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
    ]
    assert packet.model_dump(mode="json") == _artifact_payload(
        "feature_graph_rework_packet.v1.json"
    )


def test_rework_packet_builder_rejects_non_rework_verdict() -> None:
    with pytest.raises(ValueError, match="rework packet requires rework verdict"):
        build_feature_graph_rework_packet(
            evidence_bundle=_bundle(),
            verdict=_merge_verdict(),
            rework_id="rework:fverdict_merge_demo:fevb_demo:20260603T021500z",
            max_remaining_attempts=1,
            created_at="2026-06-03T02:15:00Z",
        )


def test_rework_packet_builder_rejects_mismatched_artifacts() -> None:
    mismatched_bundle = _bundle().model_copy(update={"bundle_id": "other-bundle"})

    with pytest.raises(ValueError, match="verdict evidence_bundle_id must match bundle_id"):
        build_feature_graph_rework_packet(
            evidence_bundle=mismatched_bundle,
            verdict=_rework_verdict(),
            rework_id="rework:fverdict_rework_demo:fevb_demo:20260603T021500z",
            max_remaining_attempts=1,
            created_at="2026-06-03T02:15:00Z",
        )


def test_rework_packet_builder_falls_back_to_feature_graph_scope() -> None:
    bundle = _bundle().model_copy(update={"touched_files": [], "changed_files": []})
    verdict = _rework_verdict().model_copy(
        update={
            "scope_assessment": _rework_verdict().scope_assessment.model_copy(
                update={"touched_files": []}
            )
        }
    )

    packet = build_feature_graph_rework_packet(
        evidence_bundle=bundle,
        verdict=verdict,
        rework_id="rework:fverdict_rework_demo:fevb_demo:20260603T021500z",
        max_remaining_attempts=1,
        created_at="2026-06-03T02:15:00Z",
    )

    assert packet.files_or_areas_to_revisit == [
        "feature_graph:graph-provider-session-binding"
    ]


def test_rework_packet_builder_revalidates_model_copy_bypass() -> None:
    invalid_verdict = _rework_verdict().model_copy(update={"blocking_findings": []})

    with pytest.raises(ValueError, match="rework verdicts require blocking_findings"):
        build_feature_graph_rework_packet(
            evidence_bundle=_bundle(),
            verdict=invalid_verdict,
            rework_id="rework:fverdict_rework_demo:fevb_demo:20260603T021500z",
            max_remaining_attempts=1,
            created_at="2026-06-03T02:15:00Z",
        )
