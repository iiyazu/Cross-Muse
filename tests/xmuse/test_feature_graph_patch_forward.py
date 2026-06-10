from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_patch_forward import (
    build_feature_graph_patch_forward_plan,
)
from xmuse_core.structuring.feature_graph_patch_forward_gate import (
    build_feature_graph_patch_forward_merge_guard_decision,
    build_feature_graph_patch_forward_merge_guard_handoff,
    validate_feature_graph_patch_forward_gate_result,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardPlan,
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


def _patch_forward_plan() -> FeatureGraphPatchForwardPlan:
    return FeatureGraphPatchForwardPlan.model_validate(
        _artifact_payload("feature_graph_patch_forward_plan.v1.json")
    )


def _patch_forward_gate_result() -> FeatureGraphPatchForwardGateResult:
    return FeatureGraphPatchForwardGateResult.model_validate(
        _artifact_payload("feature_graph_patch_forward_gate_result.v1.json")
    )


def test_patch_forward_verdict_builds_gate_plan() -> None:
    plan = build_feature_graph_patch_forward_plan(
        evidence_bundle=_bundle(),
        verdict=_patch_forward_verdict(),
        current_status=_reviewing_status(),
        plan_id="fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z",
        created_at="2026-06-03T02:16:00Z",
    )

    assert plan.verdict_id == "fverdict_patch_forward_demo"
    assert plan.current_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.expected_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.risk == "low"
    assert plan.max_files_changed == 1
    assert plan.max_lines_changed == 5
    assert plan.disallow_new_dependencies is True
    assert plan.disallow_public_contract_changes is True
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_plan.v1.json"
    )


def test_patch_forward_plan_fixture_is_stable() -> None:
    plan = FeatureGraphPatchForwardPlan.model_validate(
        _artifact_payload("feature_graph_patch_forward_plan.v1.json")
    )

    assert plan.plan_id == "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z"
    assert plan.allowed_file_refs == ["src/xmuse_core/agents/provider_session_binding.py"]
    assert plan.focused_gates_to_rerun == [
        "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
    ]
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_plan.v1.json"
        )


def test_patch_forward_gate_result_fixture_is_stable() -> None:
    result = _patch_forward_gate_result()

    assert result.result_id == "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    assert result.changed_file_refs == ["src/xmuse_core/agents/provider_session_binding.py"]
    assert result.lines_changed == 3
    assert result.passed is True
    assert result.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_gate_result.v1.json"
    )


def test_patch_forward_gate_result_passes_plan_limits() -> None:
    result = validate_feature_graph_patch_forward_gate_result(
        plan=_patch_forward_plan(),
        result=_patch_forward_gate_result(),
    )

    assert result.passed is True
    assert result.patch_diff_ref == "diffs/patch-forward/provider-session-binding.diff"


def test_patch_forward_gate_result_builds_merge_guard_handoff() -> None:
    handoff = build_feature_graph_patch_forward_merge_guard_handoff(
        plan=_patch_forward_plan(),
        result=_patch_forward_gate_result(),
        handoff_id="fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z",
        gate_result_ref=(
            "feature_graph_patch_forward_gate_result:"
            "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z:v1"
        ),
        created_at="2026-06-03T02:19:00Z",
    )

    assert handoff.gate_result_id == (
        "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    )
    assert handoff.patch_diff_ref == "diffs/patch-forward/provider-session-binding.diff"
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_merge_guard_handoff.v1.json"
    )


def test_patch_forward_merge_guard_handoff_builds_decision() -> None:
    handoff = build_feature_graph_patch_forward_merge_guard_handoff(
        plan=_patch_forward_plan(),
        result=_patch_forward_gate_result(),
        handoff_id="fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z",
        gate_result_ref=(
            "feature_graph_patch_forward_gate_result:"
            "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z:v1"
        ),
        created_at="2026-06-03T02:19:00Z",
    )

    decision = build_feature_graph_patch_forward_merge_guard_decision(
        handoff=handoff,
        decision_id=(
            "fgpfmgd:fgpfmgh:fgpfr:fverdict_patch_forward_demo:"
            "fevb_demo:20260603T021900z:20260603T022200z"
        ),
        merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
        merge_guard_evidence_refs=[
            "feature_graph_patch_forward_merge_guard_handoff:"
            "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z:v1",
            "logs/merge_guard/provider-binding-patch-forward.json",
        ],
        passed=True,
        failure_reasons=None,
        checked_at="2026-06-03T02:22:00Z",
    )

    assert decision.handoff_id == handoff.handoff_id
    assert decision.passed is True
    assert decision.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_merge_guard_decision.v1.json"
    )


def test_patch_forward_merge_guard_decision_allows_failed_guard_with_reason() -> None:
    handoff = FeatureGraphPatchForwardPlan.model_validate(
        _artifact_payload("feature_graph_patch_forward_plan.v1.json")
    )
    gate_result = _patch_forward_gate_result()
    merge_handoff = build_feature_graph_patch_forward_merge_guard_handoff(
        plan=handoff,
        result=gate_result,
        handoff_id="fgpfmgh:failed-merge-guard",
        gate_result_ref="feature_graph_patch_forward_gate_result:failed-merge-guard:v1",
        created_at="2026-06-03T02:19:00Z",
    )

    decision = build_feature_graph_patch_forward_merge_guard_decision(
        handoff=merge_handoff,
        decision_id="fgpfmgd:failed-merge-guard",
        merge_guard_ref="logs/merge_guard/failed.json",
        merge_guard_evidence_refs=["logs/merge_guard/failed.json"],
        passed=False,
        failure_reasons=["target branch changed before merge"],
        checked_at="2026-06-03T02:22:00Z",
    )

    assert decision.passed is False
    assert decision.failure_reasons == ["target branch changed before merge"]


def test_patch_forward_gate_result_rejects_changed_file_outside_plan() -> None:
    result = _patch_forward_gate_result().model_copy(
        update={"changed_file_refs": ["src/xmuse_core/agents/other.py"]}
    )

    with pytest.raises(ValueError, match="changed files"):
        validate_feature_graph_patch_forward_gate_result(
            plan=_patch_forward_plan(),
            result=result,
        )


def test_patch_forward_gate_result_rejects_file_count_over_limit() -> None:
    plan = _patch_forward_plan().model_copy(
        update={
            "allowed_file_refs": [
                "src/xmuse_core/agents/provider_session_binding.py",
                "tests/xmuse/test_provider_session_binding.py",
            ],
            "max_files_changed": 1,
        }
    )
    result = _patch_forward_gate_result().model_copy(
        update={
            "changed_file_refs": [
                "src/xmuse_core/agents/provider_session_binding.py",
                "tests/xmuse/test_provider_session_binding.py",
            ]
        }
    )

    with pytest.raises(ValueError, match="file count"):
        validate_feature_graph_patch_forward_gate_result(plan=plan, result=result)


def test_patch_forward_gate_result_rejects_line_count_over_limit() -> None:
    result = _patch_forward_gate_result().model_copy(update={"lines_changed": 6})

    with pytest.raises(ValueError, match="line count"):
        validate_feature_graph_patch_forward_gate_result(
            plan=_patch_forward_plan(),
            result=result,
        )


def test_patch_forward_gate_result_rejects_missing_focused_gate() -> None:
    result = _patch_forward_gate_result().model_copy(update={"focused_gates_rerun": ["other"]})

    with pytest.raises(ValueError, match="rerun every focused gate"):
        validate_feature_graph_patch_forward_gate_result(
            plan=_patch_forward_plan(),
            result=result,
        )


def test_patch_forward_gate_result_rejects_new_dependencies() -> None:
    result = _patch_forward_gate_result().model_copy(
        update={"introduced_dependency_refs": ["pyproject.toml#dependencies"]}
    )

    with pytest.raises(ValueError, match="must not introduce dependencies"):
        validate_feature_graph_patch_forward_gate_result(
            plan=_patch_forward_plan(),
            result=result,
        )


def test_patch_forward_gate_result_rejects_public_contract_changes() -> None:
    result = _patch_forward_gate_result().model_copy(
        update={"public_contract_change_refs": ["src/xmuse_core/structuring/models.py"]}
    )

    with pytest.raises(ValueError, match="must not change public contracts"):
        validate_feature_graph_patch_forward_gate_result(
            plan=_patch_forward_plan(),
            result=result,
        )


def test_patch_forward_gate_result_rejects_failed_result() -> None:
    result = _patch_forward_gate_result().model_copy(
        update={"passed": False, "failure_reasons": ["focused gate failed"]}
    )

    with pytest.raises(ValueError, match="must be passed"):
        validate_feature_graph_patch_forward_gate_result(
            plan=_patch_forward_plan(),
            result=result,
        )


def test_patch_forward_merge_guard_handoff_rejects_failed_result() -> None:
    result = _patch_forward_gate_result().model_copy(
        update={"passed": False, "failure_reasons": ["focused gate failed"]}
    )

    with pytest.raises(ValueError, match="must be passed"):
        build_feature_graph_patch_forward_merge_guard_handoff(
            plan=_patch_forward_plan(),
            result=result,
            handoff_id="fgpfmgh:failed",
            gate_result_ref="feature_graph_patch_forward_gate_result:failed:v1",
            created_at="2026-06-03T02:19:00Z",
        )


def test_patch_forward_builder_rejects_non_patch_forward_verdict() -> None:
    with pytest.raises(ValueError, match="patch-forward plan requires patch_forward verdict"):
        build_feature_graph_patch_forward_plan(
            evidence_bundle=_bundle(),
            verdict=_merge_verdict(),
            current_status=_reviewing_status(),
            plan_id="fgpf:fverdict_merge_demo:fevb_demo:20260603T021600z",
            created_at="2026-06-03T02:16:00Z",
        )


def test_patch_forward_builder_requires_reviewing_status() -> None:
    running = _reviewing_status().model_copy(
        update={"status": FeatureGraphExecutionStatus.RUNNING}
    )

    with pytest.raises(ValueError, match="patch-forward plan requires reviewing status"):
        build_feature_graph_patch_forward_plan(
            evidence_bundle=_bundle(),
            verdict=_patch_forward_verdict(),
            current_status=running,
            plan_id="fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z",
            created_at="2026-06-03T02:16:00Z",
        )


def test_patch_forward_builder_rejects_mismatched_artifacts() -> None:
    mismatched_bundle = _bundle().model_copy(update={"bundle_id": "other-bundle"})

    with pytest.raises(ValueError, match="verdict evidence_bundle_id must match bundle_id"):
        build_feature_graph_patch_forward_plan(
            evidence_bundle=mismatched_bundle,
            verdict=_patch_forward_verdict(),
            current_status=_reviewing_status(),
            plan_id="fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z",
            created_at="2026-06-03T02:16:00Z",
        )


def test_patch_forward_builder_revalidates_model_copy_bypass() -> None:
    invalid_gate = _patch_forward_verdict().patch_forward_gate
    assert invalid_gate is not None
    invalid_verdict = _patch_forward_verdict().model_copy(
        update={
            "patch_forward_gate": invalid_gate.model_copy(
                update={"disallow_new_dependencies": False}
            )
        }
    )

    with pytest.raises(ValueError, match="patch_forward must disallow new dependencies"):
        build_feature_graph_patch_forward_plan(
            evidence_bundle=_bundle(),
            verdict=invalid_verdict,
            current_status=_reviewing_status(),
            plan_id="fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z",
            created_at="2026-06-03T02:16:00Z",
        )
