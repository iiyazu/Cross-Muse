from __future__ import annotations

from dataclasses import replace

from xmuse_core.platform.closure_spine import (
    CHAIN,
    CLOSURE_CONTROLLER_FRESH,
    CONDITION_ORDER,
    RELEASE_HANDOFF_READY,
    REQUIRED_FORBIDDEN_CLAIMS,
    REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
    SERVER_TRUTH_PENDING,
    admit_closure_spine,
    closure_condition_by_type,
    evaluate_minimal_closure_spine,
)


def test_minimal_closure_spine_admits_contract_path() -> None:
    spine = evaluate_minimal_closure_spine(**_valid_inputs(), generation=3)
    admission = admit_closure_spine(spine)

    assert spine.to_dict()["spec"]["chain"] == list(CHAIN)
    assert spine.to_dict()["spec"]["proof_level"] == "contract_proof"
    assert tuple(condition.type for condition in spine.conditions) == CONDITION_ORDER
    assert spine.phase == "release_handoff_contract_ready"
    assert spine.observed_generation == 3
    assert spine.manual_gaps == ()
    assert set(REQUIRED_FORBIDDEN_CLAIMS).issubset(spine.forbidden_claims)
    assert "worker-output:1" in spine.source_refs
    assert "local-test:focused" in spine.source_refs
    assert admission.ready is True
    assert admission.status == "ready"


def test_missing_candidate_refs_fail_closed() -> None:
    inputs = _valid_inputs()
    inputs["candidate"] = {**inputs["candidate"], "artifact_ref": ""}

    spine = evaluate_minimal_closure_spine(**inputs)
    admission = admit_closure_spine(spine)

    condition = closure_condition_by_type(spine, "ExecutionCandidateReady")
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "candidate artifact_ref is missing"
    assert admission.ready is False


def test_missing_candidate_object_fails_closed() -> None:
    inputs = _valid_inputs()
    inputs["candidate"] = None

    spine = evaluate_minimal_closure_spine(**inputs)

    condition = closure_condition_by_type(spine, "ExecutionCandidateReady")
    assert condition is not None
    assert condition.status == "false"
    assert condition.reason == "candidate is missing"


def test_review_and_handoff_must_cite_same_candidate() -> None:
    inputs = _valid_inputs()
    inputs["review"] = {**inputs["review"], "cited_candidate_refs": ["candidate:other"]}

    spine = evaluate_minimal_closure_spine(**inputs)

    condition = closure_condition_by_type(spine, "IndependentReviewReady")
    assert condition is not None
    assert condition.status == "false"
    assert condition.reason == "review does not cite candidate"
    assert admit_closure_spine(spine).status == "manual_gap"


def test_missing_review_verdict_refs_fail_closed() -> None:
    inputs = _valid_inputs()
    inputs["handoff"] = {**inputs["handoff"], "review_verdict_refs": []}

    spine = evaluate_minimal_closure_spine(**inputs)

    condition = closure_condition_by_type(spine, RELEASE_HANDOFF_READY)
    assert condition is not None
    assert condition.status == "false"
    assert condition.reason == "handoff does not cite review"


def test_missing_forbidden_claims_fail_closed_without_dropping_guardrail() -> None:
    inputs = _valid_inputs()
    inputs["handoff"] = {
        **inputs["handoff"],
        "forbidden_claims": [
            claim for claim in REQUIRED_FORBIDDEN_CLAIMS if claim != "live_memoryos"
        ],
    }

    spine = evaluate_minimal_closure_spine(**inputs)

    condition = closure_condition_by_type(spine, REQUIRED_FORBIDDEN_CLAIMS_PRESENT)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert "live_memoryos" in condition.reason
    assert "live_memoryos" in spine.forbidden_claims


def test_server_truth_overclaim_blocks_spine() -> None:
    inputs = _valid_inputs()
    inputs["handoff"] = {
        **inputs["handoff"],
        "server_truth_status": "github_review_truth",
    }

    spine = evaluate_minimal_closure_spine(**inputs)

    condition = closure_condition_by_type(spine, SERVER_TRUTH_PENDING)
    handoff = closure_condition_by_type(spine, RELEASE_HANDOFF_READY)
    assert condition is not None
    assert handoff is not None
    assert condition.severity == "blocked"
    assert handoff.severity == "blocked"
    assert spine.phase == "blocked"
    assert "github_review_truth" in admit_closure_spine(spine).summary


def test_worker_output_and_local_tests_remain_candidate_evidence_only() -> None:
    inputs = _valid_inputs()
    inputs["candidate"] = {
        **inputs["candidate"],
        "worker_output_truth_status": "independent_review_artifact",
    }

    spine = evaluate_minimal_closure_spine(**inputs)

    condition = closure_condition_by_type(spine, "ExecutionCandidateReady")
    assert condition is not None
    assert condition.status == "false"
    assert condition.reason == "worker output is not candidate evidence only"
    assert "worker_output_is_review_truth" in spine.forbidden_claims


def test_stale_object_or_condition_generation_fails_closed() -> None:
    spine = evaluate_minimal_closure_spine(**_valid_inputs(), generation=2)
    stale_object = replace(spine, observed_generation=1)
    stale_condition = replace(
        spine,
        conditions=(
            replace(spine.conditions[0], observed_generation=1),
            *spine.conditions[1:],
        ),
    )

    object_admission = admit_closure_spine(stale_object)
    condition_admission = admit_closure_spine(stale_condition)

    assert object_admission.ready is False
    assert "observed_generation does not match generation" in object_admission.summary
    assert condition_admission.ready is False
    assert "stale observed_generation" in condition_admission.summary
    assert CLOSURE_CONTROLLER_FRESH in condition_admission.summary


def _valid_inputs() -> dict:
    graph_id = "graph-a"
    lane_id = "lane-a"
    return {
        "graph_id": graph_id,
        "lane_id": lane_id,
        "recovery": _artifact("recovery", graph_id, lane_id, "recovery:1")
        | {"allows_progress": True},
        "candidate": _artifact("candidate", graph_id, lane_id, "candidate:1")
        | {
            "recovery_ref": "recovery:1",
            "worker_output_refs": ["worker-output:1"],
            "worker_output_truth_status": "candidate_evidence_only",
            "local_test_refs": ["local-test:focused"],
            "local_tests_truth_status": "candidate_evidence_only",
        },
        "review": _artifact("review", graph_id, lane_id, "review:1")
        | {
            "cited_candidate_refs": ["candidate:1"],
            "reviewer_ref": "reviewer:independent",
            "review_truth_status": "independent_review_artifact",
        },
        "handoff": _artifact("handoff", graph_id, lane_id, "handoff:1")
        | {
            "cited_candidate_refs": ["candidate:1"],
            "review_verdict_refs": ["review:1"],
            "handoff_status": "evaluated",
        },
    }


def _artifact(stage: str, graph_id: str, lane_id: str, artifact_ref: str) -> dict:
    schema_by_stage = {
        "recovery": "xmuse.minimal_recovery_artifact.v1",
        "candidate": "xmuse.minimal_execution_candidate.v1",
        "review": "xmuse.minimal_review_verdict.v1",
        "handoff": "xmuse.minimal_release_handoff.v1",
    }
    return {
        "schema_version": schema_by_stage[stage],
        "artifact_ref": artifact_ref,
        "graph_id": graph_id,
        "lane_id": lane_id,
        "proof_level": "contract_proof",
        "server_truth_status": "not_server_truth",
        "owner_refs": ["source_authority:minimal_closure_spine"],
        "forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
    }
