from pathlib import Path

from tests.xmuse.closure_test_fixtures import (
    review_chain_proof_payload as _review_chain_proof_payload,
)
from tests.xmuse.closure_test_fixtures import (
    review_closure_payload as _review_closure_payload,
)
from tests.xmuse.closure_test_fixtures import (
    write_candidate as _write_candidate,
)
from tests.xmuse.closure_test_fixtures import (
    write_runner_session as _write_runner_session,
)
from xmuse_core.platform.closure_objects import (
    CLOSURE_CONTROLLER_FRESH,
    CLOSURE_OBJECT_EVALUATOR_VERSION,
    INDEPENDENT_REVIEW_VERDICT_PRESENT,
    PATCH_FORWARD_LINEAGE_PRESENT,
    RECOVERY_ALLOWS_PROGRESS,
    RECOVERY_ARTIFACT_PRESENT,
    RELEASE_HANDOFF_EVALUATED,
    REQUIRED_FORBIDDEN_CLAIMS,
    REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
    SERVER_TRUTH_PENDING,
    VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    closure_condition_by_type,
)
from xmuse_core.platform.closure_reconciler import (
    reconcile_closure,
)


def test_reconcile_closure_emits_idempotent_conditions_for_current_artifacts(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    review_closure = _review_closure_payload(tmp_path, candidate_ref)
    release_handoff = _review_chain_proof_payload(candidate_ref)

    first = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_recovery_artifact("lane-runtime-evidence-patch"),
        execution_candidates=[candidate_ref],
        review_closure=review_closure,
        release_handoff=release_handoff,
    )
    second = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_recovery_artifact("lane-runtime-evidence-patch"),
        execution_candidates=[candidate_ref],
        review_closure=review_closure,
        release_handoff=release_handoff,
    )

    assert first.to_dict() == second.to_dict()
    assert first.metadata.generation == 1
    assert first.status.observed_generation == 1
    assert first.status.phase == "release_handoff_evaluated"
    assert first.status.proof_level == "contract_proof"
    assert _condition_status(first, CLOSURE_CONTROLLER_FRESH) == "true"
    assert _condition_status(first, RECOVERY_ARTIFACT_PRESENT) == "true"
    assert _condition_status(first, RECOVERY_ALLOWS_PROGRESS) == "true"
    assert _condition_status(first, VALIDATED_EXECUTION_CANDIDATE_PRESENT) == "true"
    assert _condition_status(first, INDEPENDENT_REVIEW_VERDICT_PRESENT) == "true"
    assert _condition_status(first, PATCH_FORWARD_LINEAGE_PRESENT) == "true"
    assert _condition_status(first, RELEASE_HANDOFF_EVALUATED) == "true"
    assert _condition_status(first, REQUIRED_FORBIDDEN_CLAIMS_PRESENT) == "true"
    assert _condition_status(first, SERVER_TRUTH_PENDING) == "true"
    assert all(
        condition.observed_generation == 1 for condition in first.status.conditions
    )
    assert set(REQUIRED_FORBIDDEN_CLAIMS).issubset(first.status.forbidden_claims)
    assert "live_memoryos" in first.status.forbidden_claims
    assert "github_review_truth" in first.status.forbidden_claims


def test_reconcile_closure_blocks_stale_previous_controller_version(
    tmp_path: Path,
) -> None:
    previous = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
    ).to_dict()
    previous["status"]["evaluator_version"] = "xmuse.closure_controller.v0"

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        generation=2,
        previous_closure=previous,
    )

    assert closure.status.phase == "blocked"
    condition = closure_condition_by_type(closure, CLOSURE_CONTROLLER_FRESH)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "blocked"
    assert "evaluator_version is stale" in condition.reason
    assert closure.status.evaluator_version == CLOSURE_OBJECT_EVALUATOR_VERSION


def test_reconcile_closure_preserves_manual_gap_for_generation_skip(
    tmp_path: Path,
) -> None:
    previous = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        generation=1,
    )

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        generation=3,
        previous_closure=previous,
    )

    condition = closure_condition_by_type(closure, CLOSURE_CONTROLLER_FRESH)
    assert condition is not None
    assert condition.status == "unknown"
    assert condition.severity == "manual_gap"
    assert "generation skipped from 1 to 3" in condition.reason
    assert "closure generation skipped from 1 to 3" in closure.status.manual_gaps


def test_reconcile_closure_fails_closed_when_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
    )

    assert closure.status.phase == "manual_gap"
    assert _condition_status(closure, CLOSURE_CONTROLLER_FRESH) == "true"
    assert _condition_status(closure, RECOVERY_ARTIFACT_PRESENT) == "false"
    assert _condition_status(closure, RECOVERY_ALLOWS_PROGRESS) == "unknown"
    assert _condition_status(closure, VALIDATED_EXECUTION_CANDIDATE_PRESENT) == "false"
    assert _condition_status(closure, INDEPENDENT_REVIEW_VERDICT_PRESENT) == "false"
    assert _condition_status(closure, PATCH_FORWARD_LINEAGE_PRESENT) == "false"
    assert _condition_status(closure, RELEASE_HANDOFF_EVALUATED) == "false"
    assert _condition_status(closure, REQUIRED_FORBIDDEN_CLAIMS_PRESENT) == "true"
    assert _condition_status(closure, SERVER_TRUTH_PENDING) == "true"
    assert "runner recovery artifact is missing" in closure.status.manual_gaps
    assert "validated local execution candidate is missing" in closure.status.manual_gaps
    assert set(REQUIRED_FORBIDDEN_CLAIMS).issubset(closure.status.forbidden_claims)


def test_reconcile_closure_blocks_overclaim_and_preserves_forbidden_claims(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    review_closure = _review_closure_payload(tmp_path, candidate_ref)
    review_closure["forbidden_claims"] = ["ready_to_merge"]
    review_closure["server_truth_status"] = "github_review_truth"

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_recovery_artifact("lane-runtime-evidence-patch"),
        execution_candidates=[candidate_ref],
        review_closure=review_closure,
    )

    assert closure.status.phase == "blocked"
    review_condition = closure_condition_by_type(
        closure,
        INDEPENDENT_REVIEW_VERDICT_PRESENT,
    )
    assert review_condition is not None
    assert review_condition.severity == "blocked"
    assert "overclaims server truth" in review_condition.reason
    server_condition = closure_condition_by_type(closure, SERVER_TRUTH_PENDING)
    assert server_condition is not None
    assert server_condition.severity == "blocked"
    assert set(REQUIRED_FORBIDDEN_CLAIMS).issubset(closure.status.forbidden_claims)
    assert "worker_output_is_review_truth" in closure.status.forbidden_claims


def test_reconcile_closure_does_not_treat_plain_handoff_as_patch_forward_lineage(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
            "forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
        },
    )

    condition = closure_condition_by_type(closure, PATCH_FORWARD_LINEAGE_PRESENT)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == (
        "patch-forward lineage requires review-chain proof artifact"
    )


def test_reconcile_closure_fails_closed_when_handoff_drops_forbidden_claims(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
            "forbidden_claims": ["ready_to_merge"],
        },
    )

    condition = closure_condition_by_type(
        closure,
        REQUIRED_FORBIDDEN_CLAIMS_PRESENT,
    )
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert "release_handoff missing forbidden claims" in condition.reason
    assert "live_memoryos" in condition.reason
    assert "github_review_truth" in closure.status.forbidden_claims


def test_reconcile_closure_blocks_when_recovery_artifact_blocks_lane(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_recovery_artifact("lane-runtime-evidence-patch", blocked=True),
    )

    assert closure.status.phase == "blocked"
    condition = closure_condition_by_type(closure, RECOVERY_ALLOWS_PROGRESS)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "blocked"
    assert "blocked by durable recovery artifact" in condition.reason


def test_reconcile_closure_accepts_orchestrator_lane_recovery_retry_artifact(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_god_room_lane_recovery_artifact(
            "lane-runtime-evidence-patch",
            retry_allowed=True,
            decision="retry",
        ),
    )

    assert _condition_status(closure, RECOVERY_ARTIFACT_PRESENT) == "true"
    condition = closure_condition_by_type(closure, RECOVERY_ALLOWS_PROGRESS)
    assert condition is not None
    assert condition.status == "true"
    assert condition.severity == "ok"
    assert condition.reason == (
        "lane lane-runtime-evidence-patch retry is allowed by durable recovery artifact"
    )


def test_reconcile_closure_blocks_orchestrator_lane_recovery_stop_artifact(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_god_room_lane_recovery_artifact(
            "lane-runtime-evidence-patch",
            retry_allowed=False,
            decision="refactor_required",
        ),
    )

    assert closure.status.phase == "blocked"
    condition = closure_condition_by_type(closure, RECOVERY_ALLOWS_PROGRESS)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "blocked"
    assert "refactor_required" in condition.reason


def test_reconcile_closure_fails_closed_release_handoff_without_source_refs(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "ready",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence-patch",
            "server_truth_status": "not_server_truth",
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "release handoff is missing source refs"


def test_reconcile_closure_fails_closed_release_handoff_with_unresolved_candidate_refs(
    tmp_path: Path,
) -> None:
    missing_ref = "work/local_execution_candidates/missing-candidate.json"
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "status": "chain_ready",
            "proof_level": "contract_proof",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-runtime",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
            "candidate_lineage": {
                "candidate_artifact_refs": [missing_ref],
            },
            "local_execution_review_session": {
                "candidate_artifact_refs": [missing_ref],
            },
            "release_evidence_handoff": {
                "review_closure_candidate_artifact_refs": [missing_ref],
            },
            "forbidden_claims": list(REQUIRED_FORBIDDEN_CLAIMS),
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == (
        "release handoff candidate artifact refs are not resolvable: "
        f"{missing_ref}"
    )


def test_reconcile_closure_rejects_review_chain_handoff_wrong_status(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "status": "ready",
            "proof_level": "contract_proof",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-runtime",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "release handoff status is not chain_ready"


def test_reconcile_closure_rejects_review_chain_handoff_wrong_graph_and_lane_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "status": "chain_ready",
            "proof_level": "contract_proof",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-other",
            "terminal_lane_id": "lane-other",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert (
        condition.reason == "release handoff graph_id does not match current closure graph"
    )


def test_reconcile_closure_rejects_patch_forward_lineage_wrong_graph_and_lane_scope(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    release_handoff = _review_chain_proof_payload(candidate_ref)
    release_handoff["graph_id"] = "graph-other"
    release_handoff["terminal_lane_id"] = "lane-other"
    session = release_handoff["local_execution_review_session"]
    assert isinstance(session, dict)
    session["graph_id"] = "graph-other"
    session["terminal_lane_id"] = "lane-other"

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff=release_handoff,
    )

    patch_condition = closure_condition_by_type(closure, PATCH_FORWARD_LINEAGE_PRESENT)
    assert patch_condition is not None
    assert patch_condition.status == "false"
    assert patch_condition.severity == "manual_gap"
    assert "review-chain proof graph_id does not match current closure graph" in (
        patch_condition.reason
    )
    assert "review-chain proof terminal_lane_id does not match current closure lane" in (
        patch_condition.reason
    )
    assert "local execution review session graph_id does not match" in (
        patch_condition.reason
    )
    assert "local execution review session terminal_lane_id does not match" in (
        patch_condition.reason
    )


def test_reconcile_closure_rejects_review_chain_handoff_missing_graph_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "status": "chain_ready",
            "proof_level": "contract_proof",
            "server_truth_status": "not_server_truth",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "release handoff graph_id is missing"


def test_reconcile_closure_rejects_review_chain_handoff_missing_terminal_lane_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "status": "chain_ready",
            "proof_level": "contract_proof",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-runtime",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "release handoff terminal_lane_id is missing"


def test_reconcile_closure_rejects_review_chain_handoff_wrong_proof_level(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
            "status": "chain_ready",
            "proof_level": "manual_gap",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-runtime",
            "terminal_lane_id": "lane-runtime-evidence-patch",
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "release handoff proof level is not contract_proof"


def test_reconcile_closure_rejects_review_closure_handoff_wrong_status_or_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "blocked",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-other",
            "lane_id": "lane-other",
            "candidate_artifact_refs": ["artifacts/local-exec/result.json"],
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "review-closure handoff status is not ready"


def test_reconcile_closure_rejects_review_closure_handoff_wrong_graph_and_lane_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-other",
            "lane_id": "lane-other",
            "candidate_artifact_refs": ["artifacts/local-exec/result.json"],
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert (
        condition.reason
        == "review-closure handoff graph_id does not match current closure graph"
    )


def test_reconcile_closure_rejects_release_handoff_scope_mismatch_with_review_closure_graph(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    review_closure = _review_closure_payload(tmp_path, candidate_ref)
    review_closure["graph_id"] = "graph-other"
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_recovery_artifact("lane-runtime-evidence-patch"),
        execution_candidates=[candidate_ref],
        review_closure=review_closure,
        release_handoff=_review_chain_proof_payload(candidate_ref),
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert (
        condition.reason
        == "release handoff graph_id does not match review closure graph_id"
    )


def test_reconcile_closure_rejects_release_handoff_scope_mismatch_with_review_closure_lane(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    review_closure = _review_closure_payload(tmp_path, candidate_ref)
    review_closure["terminal_lane_id"] = "lane-other"
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        recovery_artifact=_recovery_artifact("lane-runtime-evidence-patch"),
        execution_candidates=[candidate_ref],
        review_closure=review_closure,
        release_handoff=_review_chain_proof_payload(candidate_ref),
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert (
        condition.reason
        == "release handoff lane scope does not match review closure lane scope"
    )


def test_reconcile_closure_rejects_review_closure_handoff_missing_graph_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "lane_id": "lane-runtime-evidence-patch",
            "candidate_artifact_refs": ["artifacts/local-exec/result.json"],
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "review-closure handoff graph_id is missing"


def test_reconcile_closure_rejects_review_closure_handoff_missing_lane_scope(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        release_handoff={
            "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
            "status": "ready",
            "server_truth_status": "not_server_truth",
            "graph_id": "graph-runtime",
            "candidate_artifact_refs": ["artifacts/local-exec/result.json"],
            "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "review-closure handoff lane_id is missing"


def test_reconcile_closure_rejects_candidate_without_runner_session(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        execution_candidates=[candidate_ref],
    )

    condition = closure_condition_by_type(
        closure,
        VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    )
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert "runner session lineage is missing" in condition.reason


def test_reconcile_closure_rejects_candidate_runner_session_mismatch(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref, run_id="platform-runner:run-other")

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        execution_candidates=[candidate_ref],
    )

    condition = closure_condition_by_type(
        closure,
        VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    )
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert "runner session lineage is missing" in condition.reason


def test_reconcile_closure_rejects_manual_cli_candidate(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref, producer="manual_cli_capture")

    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
        execution_candidates=[candidate_ref],
    )

    condition = closure_condition_by_type(
        closure,
        VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    )
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert "local execution candidate is not platform_runner_dispatch" in (
        condition.reason
    )


def _condition_status(closure, condition_type: str) -> str:
    condition = closure_condition_by_type(closure, condition_type)
    assert condition is not None
    return condition.status


def _recovery_artifact(lane_id: str, *, blocked: bool = False) -> dict[str, object]:
    return {
        "schema_version": "xmuse.local_runner_recovery_proof.v1",
        "status": "ok",
        "proof_level": "local_runtime_proof",
        "source_authority": "platform_runner_candidate_selection",
        "source_refs": ["lane_recovery_artifact:lane-runtime-evidence"],
        "target_refs": [f"lane:{lane_id}"],
        "candidate_selection": {
            "candidate_lane_ids": [] if blocked else [lane_id],
            "excluded_recovery_blocked_lane_ids": [lane_id] if blocked else [],
            "invalid_recovery_artifact_lane_ids": [],
        },
        "manual_gaps": ["server_truth_not_proven"],
        "forbidden_claims": ["ready_to_merge", "pr_merged"],
    }


def _god_room_lane_recovery_artifact(
    lane_id: str,
    *,
    retry_allowed: bool,
    decision: str,
) -> dict[str, object]:
    return {
        "schema_version": "xmuse.god_room_lane_recovery.v1",
        "source_authority": "platform_orchestrator_merge_failure",
        "proof_level": "contract_proof",
        "graph_id": "graph-runtime",
        "lane_id": lane_id,
        "decision": {
            "lane_id": lane_id,
            "decision": decision,
            "retry_allowed": retry_allowed,
            "failure_class": "merge_conflict",
            "attempt": 1,
            "source_refs": ["review:merge-conflict"],
        },
        "source_refs": ["logs/gates/lane-1/report.json", "review:merge-conflict"],
        "manual_gaps": ["review_truth_not_proven", "server_truth_not_proven"],
        "forbidden_claims": [
            "independent_review_truth",
            "server_truth",
            "worker_output_is_review_truth",
            "ready_to_merge",
            "pr_merged",
        ],
    }
