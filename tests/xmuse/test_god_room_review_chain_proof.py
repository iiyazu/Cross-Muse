import json
from pathlib import Path

from xmuse.god_room_review_chain_proof_capture import main as capture_main
from xmuse_core.platform.closure_objects import (
    PATCH_FORWARD_LINEAGE_PRESENT,
    SERVER_TRUTH_PENDING,
    ClosureObject,
)
from xmuse_core.platform.god_room_review_chain_proof import (
    build_god_room_review_chain_proof,
    build_review_chain_proof_l10_handoff_evaluation,
    capture_god_room_review_chain_proof,
)
from xmuse_core.platform.local_execution_candidate import (
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.runner_recovery_proof import (
    build_runner_recovery_proof,
    build_runner_recovery_proof_lineage,
)


def test_god_room_review_chain_proof_validates_l9_to_l10_handoff(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)

    proof = capture_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
        output_path=tmp_path / "work" / "review-chain-proof.json",
    )

    assert proof["schema_version"] == "xmuse.god_room_lane_review_chain_proof.v1"
    assert proof["source_authority"] == (
        "god_room_lane_review_closure_artifact+"
        "local_execution_candidate_lineage+"
        "shared_god_room_review_closure_handoff_gate"
    )
    assert proof["status"] == "chain_ready"
    assert proof["proof_level"] == "contract_proof"
    assert proof["server_truth_status"] == "not_server_truth"
    assert proof["conversation_id"] == "conv-runtime"
    assert proof["graph_id"] == "graph-runtime"
    assert proof["terminal_lane_id"] == "lane-runtime-evidence-patch"
    assert proof["review_closure"]["graph_status_source_authority"] == (
        "feature_graph_status_store"
    )
    assert proof["review_closure"]["source_event_lineage_count"] == 1
    assert proof["review_closure"]["terminal_feature_graph_status"] == {
        "status": "merged",
        "source_event_lineage_count": 1,
    }
    assert proof["candidate_lineage"]["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    assert proof["candidate_lineage"]["producers"] == ["platform_runner_dispatch"]
    assert proof["candidate_lineage"]["graph_status_source_authorities"] == [
        "feature_graph_status_store",
    ]
    session = proof["local_execution_review_session"]
    assert session["schema_version"] == "xmuse.local_execution_review_session.v1"
    assert session["session_id"] == (
        "local-execution-review-session:"
        "graph-runtime:lane-runtime-evidence:lane-runtime-evidence-patch"
    )
    assert session["status"] == "bounded_session_ready"
    assert session["proof_level"] == "contract_proof"
    assert session["session_truth_status"] == "bounded_local_execution_review_session"
    assert session["server_truth_status"] == "not_server_truth"
    assert session["graph_id"] == "graph-runtime"
    assert session["failed_lane_id"] == "lane-runtime-evidence"
    assert session["terminal_lane_id"] == "lane-runtime-evidence-patch"
    patch_forward_ref = (
        "reports/god_room_patch_forward/"
        "graph-runtime.lane-runtime-evidence.patch-forward.json"
    )
    patch_intake_ref = (
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
    )
    patch_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
    )
    assert patch_forward_ref in session["session_artifact_refs"]
    assert patch_intake_ref in session["session_artifact_refs"]
    assert patch_verdict_ref in session["session_artifact_refs"]
    assert "reports/runner-recovery-proof.json" in session["session_artifact_refs"]
    assert "reports/lane-recovery/lane-runtime-evidence.json" in session[
        "session_source_refs"
    ]
    assert session["candidate_count"] == 1
    assert session["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    assert session["candidate_ids"] == ["candidate-lane-runtime-evidence-patch"]
    assert session["candidate_run_ids"] == ["platform-runner:run-1"]
    assert session["candidate_worker_ids"] == ["platform-runner"]
    assert session["candidate_runner_session_ids"] == ["runner-session-1"]
    assert session["candidate_runner_session_refs"] == [
        "work/runner_sessions/runner-session-1.json"
    ]
    assert session["candidate_producers"] == ["platform_runner_dispatch"]
    assert session["candidate_output_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    assert session["review_truth_status"] == "independent_review_artifact"
    assert session["execution_truth_status"] == "candidate_reviewed"
    assert session["runner_recovery_proof_status"] == "target_lane_recovery_blocked"
    session_scope = session["session_scope_boundary"]
    assert session_scope["status"] == "verified"
    assert session_scope["proof_level"] == "contract_proof"
    assert session_scope["session_id"] == session["session_id"]
    assert session_scope["runner_recovery_artifact_ref"] == (
        "reports/runner-recovery-proof.json"
    )
    assert session_scope["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    validation = session["session_artifact_validation"]
    assert validation["status"] == "validated"
    assert validation["proof_level"] == "contract_proof"
    assert validation["artifact_count"] == 4
    assert validation["manual_gaps"] == []
    assert validation["validated_artifacts"]["patch_forward_artifact"]["status"] == (
        "validated"
    )
    assert validation["validated_artifacts"]["patch_forward_review_verdict_artifact"][
        "status"
    ] == "validated"
    assert validation["validated_artifacts"]["patch_lane_review_intake_artifact"][
        "status"
    ] == "validated"
    assert validation["validated_artifacts"]["patch_lane_review_verdict_artifact"][
        "status"
    ] == "validated"
    patch_forward_boundary = session["patch_forward_artifact_boundary"]
    assert patch_forward_boundary["status"] == "resolved_with_retained_manual_gaps"
    assert patch_forward_boundary["source_manual_gaps"] == [
        "patch_lane_not_executed",
        "patch_lane_not_reviewed",
        "release_evidence_not_linked",
    ]
    assert patch_forward_boundary["resolved_manual_gaps"] == [
        "patch_lane_not_executed",
        "patch_lane_not_reviewed",
    ]
    assert patch_forward_boundary["retained_manual_gaps"] == [
        "release_evidence_not_linked",
    ]
    assert patch_forward_boundary["resolution_evidence_refs"][
        "patch_lane_not_executed"
    ] == [
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence-patch.review-intake.json",
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    assert patch_forward_boundary["resolution_evidence_refs"][
        "patch_lane_not_reviewed"
    ] == [
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence-patch.review-verdict.json",
        "review-plane:lane-runtime-evidence-patch:verdict-1",
    ]
    reviewer_independence = session["reviewer_independence"]
    assert reviewer_independence["status"] == "verified"
    assert reviewer_independence["proof_level"] == "contract_proof"
    assert reviewer_independence["reviewer_id"] == "review-god"
    assert reviewer_independence["candidate_worker_ids"] == ["platform-runner"]
    review_intake_graph_status = session["review_intake_graph_status_boundary"]
    assert review_intake_graph_status["status"] == "verified"
    assert review_intake_graph_status["proof_level"] == "contract_proof"
    assert review_intake_graph_status["source_authority"] == (
        "feature_graph_status_store+lane_dag_artifact"
    )
    assert review_intake_graph_status["feature_graph_status"] == "reviewing"
    assert review_intake_graph_status["source_event_lineage_count"] == 1
    candidate_graph_status = session["candidate_graph_status_boundary"]
    assert candidate_graph_status["status"] == "verified"
    assert candidate_graph_status["proof_level"] == "contract_proof"
    assert candidate_graph_status["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert candidate_graph_status["candidate_count"] == 1
    assert candidate_graph_status["intake_feature_graph_status"] == {
        "graph_set_id": "graph-runtime-graph-set",
        "feature_graph_id": "graph-runtime-feature-runtime",
        "status_id": "fgs:graph-runtime-feature-runtime:reviewing",
        "status": "reviewing",
        "source_event_lineage_count": 1,
    }
    candidate_artifact_ref_boundary = session["candidate_artifact_ref_boundary"]
    assert candidate_artifact_ref_boundary["status"] == "verified"
    assert candidate_artifact_ref_boundary["proof_level"] == "contract_proof"
    assert candidate_artifact_ref_boundary[
        "closure_cited_candidate_artifact_refs"
    ] == ["artifacts/lane-runtime-evidence-patch/result.json"]
    assert candidate_artifact_ref_boundary["resolved_candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    candidate_lineage_boundary = session["candidate_lineage_boundary"]
    assert candidate_lineage_boundary["status"] == "verified"
    assert candidate_lineage_boundary["proof_level"] == "contract_proof"
    assert candidate_lineage_boundary["closure_candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert candidate_lineage_boundary["resolved_candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    runner_recovery_boundary = session["runner_recovery_lineage_boundary"]
    assert runner_recovery_boundary["status"] == "verified"
    assert runner_recovery_boundary["proof_level"] == "contract_proof"
    assert runner_recovery_boundary["runner_recovery_status"] == (
        "target_lane_recovery_blocked"
    )
    runner_session_boundary = session["runner_session_boundary"]
    assert runner_session_boundary["schema_version"] == (
        "xmuse.runner_session_boundary.v1"
    )
    assert runner_session_boundary["status"] == "verified"
    assert runner_session_boundary["proof_level"] == "contract_proof"
    assert runner_session_boundary["server_truth_status"] == "not_server_truth"
    assert runner_session_boundary["runner_session_ids"] == ["runner-session-1"]
    assert runner_session_boundary["runner_session_refs"] == [
        "work/runner_sessions/runner-session-1.json"
    ]
    assert runner_session_boundary["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert runner_session_boundary["candidate_worker_evidence_bundle_refs"] == []
    assert runner_session_boundary["session_worker_evidence_bundle_refs"] == []
    assert runner_session_boundary["missing_session_worker_evidence_bundle_refs"] == []
    assert "runner_session_is_review_truth" in runner_session_boundary[
        "forbidden_claims"
    ]
    graph_accounting = session["graph_wide_lane_accounting_boundary"]
    assert graph_accounting["schema_version"] == (
        "xmuse.graph_wide_lane_accounting_boundary.v1"
    )
    assert graph_accounting["status"] == "verified"
    assert graph_accounting["proof_level"] == "contract_proof"
    assert graph_accounting["server_truth_status"] == "not_server_truth"
    assert graph_accounting["graph_set_loaded"] is True
    assert graph_accounting["status_store_loaded"] is True
    assert graph_accounting["expected_feature_graph_ids"] == [
        "graph-runtime-feature-runtime"
    ]
    assert graph_accounting["observed_feature_graph_ids"] == [
        "graph-runtime-feature-runtime"
    ]
    assert graph_accounting["completed_lane_ids"] == [
        "lane-runtime-evidence-patch"
    ]
    assert graph_accounting["candidate_covered_lane_ids"] == [
        "lane-runtime-evidence-patch"
    ]
    assert graph_accounting["candidate_artifact_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert graph_accounting["uncovered_completed_lane_ids"] == []
    assert "graph_wide_execution_review_closure" in graph_accounting[
        "forbidden_claims"
    ]
    assert proof["runner_recovery_proof_lineage"]["status"] == (
        "target_lane_recovery_blocked"
    )
    assert proof["release_evidence_handoff"]["review_closure_artifact_gate_ready"] is True
    assert proof["release_evidence_handoff"][
        "review_closure_candidate_artifact_refs"
    ] == ["artifacts/lane-runtime-evidence-patch/result.json"]
    handoff = build_review_chain_proof_l10_handoff_evaluation(
        root=tmp_path,
        artifact_path=tmp_path / "work" / "review-chain-proof.json",
        review_chain_proof=proof,
    )
    assert handoff["status"] == "ready"
    assert handoff["patch_forward_artifact_refs"] == [
        patch_forward_ref,
        patch_intake_ref,
        patch_verdict_ref,
    ]
    assert handoff["patch_forward_artifact_ref_count"] == 3
    assert "worker_output_is_review_truth" in proof["forbidden_claims"]
    assert "ready_to_merge" in proof["forbidden_claims"]
    assert "pr_merged" in proof["forbidden_claims"]
    assert "live_memoryos" in proof["forbidden_claims"]
    assert "worker_self_review_equals_review_truth" in proof["forbidden_claims"]
    assert "live_memoryos_trace_not_proven" in proof["manual_gaps"]
    assert "release_evidence_not_linked" in proof["manual_gaps"]
    assert "patch_lane_not_executed" not in proof["manual_gaps"]
    assert "patch_lane_not_reviewed" not in proof["manual_gaps"]
    assert (tmp_path / "work" / "review-chain-proof.json").exists()


def test_god_room_review_chain_proof_rejects_manual_candidate_for_bounded_session(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    candidate_path = tmp_path / "artifacts/lane-runtime-evidence-patch/result.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["producer"] = "manual_cli_capture"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["candidate_lineage"]["candidate_artifact_refs"] == []
    assert any(
        "producer is not platform_runner_dispatch" in issue
        for issue in proof["issues"]
    )
    session = proof["local_execution_review_session"]
    assert session["status"] == "manual_gap"
    assert session["candidate_producers"] == []
    assert session["session_scope_boundary"]["status"] == "manual_gap"
    assert "worker_output_is_review_truth" in proof["forbidden_claims"]


def test_god_room_review_chain_proof_fail_closes_missing_runner_recovery_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(
        tmp_path,
        include_runner_recovery_lineage=False,
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert "runner_recovery_proof_not_linked" in proof["manual_gaps"]
    boundary = proof["local_execution_review_session"][
        "runner_recovery_lineage_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "runner recovery proof lineage does not show target-lane recovery enforcement" in (
        boundary["issues"]
    )


def test_god_room_review_chain_proof_preserves_manual_gap_runner_recovery_proof(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    runner_recovery_artifact = tmp_path / "reports" / "runner-recovery-manual-gap.json"
    runner_recovery_artifact.parent.mkdir(parents=True, exist_ok=True)
    runner_recovery_proof = build_runner_recovery_proof(
        run_id="run-recovery-manual-gap",
        runner_id="platform-runner",
        lanes=[
            {
                "feature_id": "lane-runtime-evidence",
                "status": "reworking",
                "graph_id": "graph-runtime",
            }
        ],
        candidate_lanes=[
            {
                "feature_id": "lane-runtime-evidence",
                "status": "reworking",
                "graph_id": "graph-runtime",
            }
        ],
        runner_status={
            "health": {
                "recovery": {
                    "source_authority": "lane_recovery_artifact",
                    "proof_level": "contract_proof",
                    "counts": {
                        "blocked": 0,
                        "non_retry_decision": 0,
                        "invalid_artifact": 0,
                        "retry_allowed": 0,
                    },
                    "blocked_lanes": [],
                    "invalid_artifacts": [],
                    "source_refs": [],
                }
            }
        },
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
        graph_id="graph-runtime",
        resolution_id="resolution-runtime",
    )
    runner_recovery_artifact.write_text(
        json.dumps(runner_recovery_proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    runner_recovery_lineage = build_runner_recovery_proof_lineage(
        proof=runner_recovery_proof,
        artifact_ref="reports/runner-recovery-manual-gap.json",
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence",
    )
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["runner_recovery_proof_lineage"] = runner_recovery_lineage
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert "no_durable_recovery_block_observed" in proof["manual_gaps"]
    boundary = proof["local_execution_review_session"][
        "runner_recovery_lineage_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "runner recovery proof lineage does not show target-lane recovery enforcement" in (
        boundary["issues"]
    )
    assert "runner recovery proof lineage proof level is not local_runtime_proof" in (
        boundary["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_recovery_lineage_scope_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["runner_recovery_proof_lineage"]["target_refs"] = [
        "lane:other-failed-lane"
    ]
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "runner_recovery_lineage_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "runner recovery proof lineage does not target the failed lane" in (
        boundary["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_unscoped_recovery_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["runner_recovery_proof_lineage"].pop("filtered_graph_id")
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "runner_recovery_lineage_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "runner recovery proof lineage graph filter is missing" in (
        boundary["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_runner_recovery_artifact(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    (tmp_path / "reports" / "runner-recovery-proof.json").unlink()

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "runner_recovery_lineage_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "runner recovery proof lineage artifact ref is not readable" in (
        boundary["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_recovery_source_ref(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    (tmp_path / "reports" / "lane-recovery" / "lane-runtime-evidence.json").unlink()

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "runner_recovery_lineage_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert (
        "runner recovery proof lineage source refs are not readable: "
        "reports/lane-recovery/lane-runtime-evidence.json"
    ) in boundary["issues"]


def test_god_room_review_chain_proof_fail_closes_candidate_graph_status_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    candidate_path = tmp_path / "artifacts" / "lane-runtime-evidence-patch" / "result.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["feature_graph_status"] = "ready"
    payload["feature_graph_status_id"] = "fgs:graph-runtime-feature-runtime:ready"
    payload["graph_status_lineage"]["status"] = "ready"
    payload["graph_status_lineage"]["status_id"] = (
        "fgs:graph-runtime-feature-runtime:ready"
    )
    candidate_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "graph_status_lineage.status does not match review intake" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"][
        "candidate_graph_status_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "candidate_graph_status_boundary_not_proven" in boundary["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_candidate_graph_status_lineage_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    candidate_path = tmp_path / "artifacts" / "lane-runtime-evidence-patch" / "result.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["graph_status_lineage"]["source_event_lineage"] = [
        {
            "event_id": "evt-other",
            "event_type": "freeze_requested",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    candidate_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "graph_status_lineage.source_event_lineage does not match review intake"
        in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_unresolved_candidate_artifact_ref(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    missing_ref = "artifacts/lane-runtime-evidence-patch/missing-result.json"
    closure["cited_candidate_artifact_refs"].append(missing_ref)
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    intake_path = tmp_path / closure["patch_lane_review_intake_artifact"]
    intake = json.loads(intake_path.read_text(encoding="utf-8"))
    intake["execution_artifact_refs"].append(missing_ref)
    intake_path.write_text(
        json.dumps(intake, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["release_evidence_handoff"][
        "review_closure_artifact_gate_ready"
    ] is False
    assert any(
        "cited_candidate_artifact_refs not resolved as valid local execution "
        "candidate lineage" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"][
        "candidate_artifact_ref_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert boundary["missing_resolved_candidate_artifact_refs"] == [missing_ref]
    assert "candidate_artifact_refs_not_resolved" in boundary["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_undeclared_resolved_candidate_ref(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    extra_ref = "artifacts/lane-runtime-evidence-patch/extra-result.json"
    _write_candidate(tmp_path / extra_ref)
    closure["cited_candidate_refs"].append(extra_ref)
    closure["terminal_review_verdict"]["evidence_refs"].append(extra_ref)
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    intake_path = tmp_path / closure["patch_lane_review_intake_artifact"]
    intake = json.loads(intake_path.read_text(encoding="utf-8"))
    intake["execution_artifact_refs"].append(extra_ref)
    intake_path.write_text(
        json.dumps(intake, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verdict_path = tmp_path / closure["patch_lane_review_verdict_artifact"]
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["review_verdict"]["evidence_refs"].append(extra_ref)
    verdict_path.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["release_evidence_handoff"][
        "review_closure_artifact_gate_ready"
    ] is False
    assert any(
        "resolved local execution candidate lineage has artifact refs not "
        "declared by review closure cited_candidate_artifact_refs" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"][
        "candidate_artifact_ref_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert boundary["unexpected_resolved_candidate_artifact_refs"] == [extra_ref]
    assert "candidate_artifact_refs_not_resolved" in boundary["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_missing_candidate_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    closure["cited_candidate_artifact_lineage"] = []
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["release_evidence_handoff"][
        "review_closure_artifact_gate_ready"
    ] is False
    assert any(
        "cited_candidate_artifact_lineage missing resolved local execution "
        "candidate lineage refs" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"]["candidate_lineage_boundary"]
    assert boundary["status"] == "manual_gap"
    assert boundary["missing_closure_candidate_artifact_lineage_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert "candidate_artifact_lineage_not_resolved" in boundary["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_mismatched_candidate_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    closure["cited_candidate_artifact_lineage"][0]["worker_id"] = "stale-worker"
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["release_evidence_handoff"][
        "review_closure_artifact_gate_ready"
    ] is False
    assert any(
        "cited_candidate_artifact_lineage does not match resolved local execution "
        "candidate lineage" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"]["candidate_lineage_boundary"]
    assert boundary["status"] == "manual_gap"
    assert boundary["mismatched_closure_candidate_artifact_lineage_refs"] == [
        "artifacts/lane-runtime-evidence-patch/result.json"
    ]
    assert "candidate_artifact_lineage_not_resolved" in boundary["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_unexpected_candidate_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    unexpected_ref = "artifacts/lane-runtime-evidence-patch/stale-result.json"
    stale_lineage = dict(closure["cited_candidate_artifact_lineage"][0])
    stale_lineage["artifact_ref"] = unexpected_ref
    closure["cited_candidate_artifact_lineage"].append(stale_lineage)
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["release_evidence_handoff"][
        "review_closure_artifact_gate_ready"
    ] is False
    assert any(
        "cited_candidate_artifact_lineage contains refs not resolved as valid "
        "local execution candidate lineage" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"]["candidate_lineage_boundary"]
    assert boundary["status"] == "manual_gap"
    assert boundary["unexpected_closure_candidate_artifact_lineage_refs"] == [
        unexpected_ref
    ]
    assert "candidate_artifact_lineage_not_resolved" in boundary["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_review_intake_missing_graph_status_authority(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    intake_path = _patch_lane_review_intake_path(tmp_path)
    payload = json.loads(intake_path.read_text(encoding="utf-8"))
    payload["source_authority"] = "lane_dag_artifact"
    intake_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "review intake source_authority is missing feature_graph_status_store" in issue
        for issue in proof["issues"]
    )
    boundary = proof["local_execution_review_session"][
        "review_intake_graph_status_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert "review_intake_graph_status_boundary_not_proven" in boundary[
        "manual_gaps"
    ]


def test_god_room_review_chain_proof_fail_closes_review_intake_missing_source_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    intake_path = _patch_lane_review_intake_path(tmp_path)
    payload = json.loads(intake_path.read_text(encoding="utf-8"))
    payload["source_event_lineage"] = []
    payload["feature_graph_status"]["source_event_lineage"] = []
    intake_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert "patch lane review intake source_event_lineage is missing" in proof[
        "issues"
    ]


def test_god_room_review_chain_proof_fail_closes_review_intake_lineage_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    intake_path = _patch_lane_review_intake_path(tmp_path)
    payload = json.loads(intake_path.read_text(encoding="utf-8"))
    payload["feature_graph_status"]["source_event_lineage"] = [
        {
            "event_id": "evt-other",
            "event_type": "freeze_requested",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    intake_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "review intake feature graph status source_event_lineage does not match intake"
        in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_wrong_graph_status_authority(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["graph_status_source_authority"] = "lane_dag_artifact"
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "graph status authority is not feature_graph_status_store" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_source_event_lineage(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["source_event_lineage"] = []
    payload["terminal_feature_graph_status"]["source_event_lineage"] = []
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert "GOD room review closure source_event_lineage is missing" in proof["issues"]


def test_god_room_review_chain_proof_fail_closes_missing_terminal_graph_status(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload.pop("terminal_feature_graph_status")
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert (
        "GOD room review closure terminal feature graph status is missing"
        in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_terminal_graph_status_lineage_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    payload = json.loads(review_closure.read_text(encoding="utf-8"))
    payload["terminal_feature_graph_status"]["source_event_lineage"] = [
        {
            "event_id": "evt-other",
            "event_type": "freeze_requested",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    review_closure.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "terminal feature graph status source_event_lineage does not match closure"
        in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_without_candidate_artifact(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path, create_candidate=False)

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["candidate_lineage"]["candidate_count"] == 0
    assert proof["release_evidence_handoff"]["review_closure_artifact_gate_ready"] is False
    assert "release_evidence_candidate_gate_not_ready" in proof["manual_gaps"]
    boundary = proof["local_execution_review_session"][
        "patch_forward_artifact_boundary"
    ]
    assert boundary["resolved_manual_gaps"] == ["patch_lane_not_reviewed"]
    assert boundary["retained_manual_gaps"] == [
        "patch_lane_not_executed",
        "release_evidence_not_linked",
    ]
    assert "patch_lane_not_executed" in proof["manual_gaps"]
    assert any("no valid local execution candidate" in issue for issue in proof["issues"])
    assert "ready_to_merge" in proof["forbidden_claims"]


def test_god_room_review_chain_proof_fail_closes_without_session_artifacts(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path, create_session_artifacts=False)

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    session = proof["local_execution_review_session"]
    validation = session["session_artifact_validation"]
    assert session["status"] == "manual_gap"
    assert validation["status"] == "manual_gap"
    assert "local_execution_review_session_artifact_validation_failed" in proof[
        "manual_gaps"
    ]
    assert any("patch_forward_artifact artifact is missing" in issue for issue in proof["issues"])


def test_god_room_review_chain_proof_fail_closes_session_artifact_scope_mismatch(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(
        tmp_path,
        patch_forward_patch_lane_id="lane-runtime-evidence-other-patch",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    validation = proof["local_execution_review_session"][
        "session_artifact_validation"
    ]
    assert validation["status"] == "manual_gap"
    assert any(
        "patch_forward_artifact patch_lane_id does not match closure" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_session_artifact_path_escape(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    closure["patch_forward_artifact"] = "../../outside.json"
    review_closure.write_text(
        json.dumps(closure, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    validation = proof["local_execution_review_session"][
        "session_artifact_validation"
    ]
    assert validation["status"] == "manual_gap"
    assert any("session artifact ref escapes xmuse root" in issue for issue in proof["issues"])


def test_god_room_review_chain_proof_fail_closes_missing_intake_candidate_ref(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    intake_path = tmp_path / closure["patch_lane_review_intake_artifact"]
    intake = json.loads(intake_path.read_text(encoding="utf-8"))
    intake["execution_artifact_refs"] = ["artifacts/other/result.json"]
    intake_path.write_text(
        json.dumps(intake, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert any(
        "patch lane review intake execution_artifact_refs missing closure "
        "cited candidate artifact refs" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_verdict_candidate_ref(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    verdict_path = tmp_path / closure["patch_lane_review_verdict_artifact"]
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["review_verdict"]["evidence_refs"] = [
        closure["patch_lane_review_intake_artifact"]
    ]
    verdict_path.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert any(
        "patch lane review verdict evidence_refs missing closure cited candidate refs"
        in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_verdict_intake_ref(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    verdict_path = tmp_path / closure["patch_lane_review_verdict_artifact"]
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["review_verdict"]["evidence_refs"] = [
        "worker-candidate:patch-reviewed",
        "artifacts/lane-runtime-evidence-patch/result.json",
    ]
    verdict_path.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert any(
        "patch lane review verdict evidence_refs missing review intake artifact"
        in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_bad_patch_forward_verdict(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    patch_forward_path = tmp_path / closure["patch_forward_artifact"]
    patch_forward = json.loads(patch_forward_path.read_text(encoding="utf-8"))
    patch_forward_verdict_path = tmp_path / patch_forward["review_verdict_artifact"]
    patch_forward_verdict = json.loads(
        patch_forward_verdict_path.read_text(encoding="utf-8")
    )
    patch_forward_verdict["review_verdict"]["decision"] = "merge"
    patch_forward_verdict_path.write_text(
        json.dumps(patch_forward_verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert any(
        "patch forward review verdict artifact decision is not patch-forward" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_patch_forward_link(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    patch_forward_path = tmp_path / closure["patch_forward_artifact"]
    patch_forward = json.loads(patch_forward_path.read_text(encoding="utf-8"))
    patch_forward.pop("patch_forward_link")
    patch_forward_path.write_text(
        json.dumps(patch_forward, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert any(
        "patch forward artifact missing patch_forward_link" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_bad_patch_forward_link_verdict(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    patch_forward_path = tmp_path / closure["patch_forward_artifact"]
    patch_forward = json.loads(patch_forward_path.read_text(encoding="utf-8"))
    patch_forward["patch_forward_link"]["verdict_ref"] = (
        "god_room_review_verdict:other"
    )
    patch_forward_path.write_text(
        json.dumps(patch_forward, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert any(
        "patch forward artifact patch_forward_link.verdict_ref does not match "
        "patch-forward review verdict" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_bad_patch_lane_contract(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    patch_forward_path = tmp_path / closure["patch_forward_artifact"]
    patch_forward = json.loads(patch_forward_path.read_text(encoding="utf-8"))
    patch_forward["patch_lane_contract"]["dependency_refs"] = []
    patch_forward_path.write_text(
        json.dumps(patch_forward, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert any(
        "patch forward artifact patch_lane_contract.dependency_refs missing "
        "failed lane ref" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_retains_unresolved_patch_review_gap(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    verdict_path = tmp_path / closure["patch_lane_review_verdict_artifact"]
    verdict_path.unlink()

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "patch_forward_artifact_boundary"
    ]
    assert boundary["status"] == "resolved_with_retained_manual_gaps"
    assert boundary["resolved_manual_gaps"] == ["patch_lane_not_executed"]
    assert boundary["retained_manual_gaps"] == [
        "patch_lane_not_reviewed",
        "release_evidence_not_linked",
    ]
    assert "patch_lane_not_executed" not in proof["manual_gaps"]
    assert "patch_lane_not_reviewed" in proof["manual_gaps"]
    assert "release_evidence_not_linked" in proof["manual_gaps"]


def test_god_room_review_chain_proof_fail_closes_reviewer_worker_conflict(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    verdict_path = tmp_path / closure["patch_lane_review_verdict_artifact"]
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["reviewer_id"] = "platform-runner"
    verdict_path.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    reviewer_independence = proof["local_execution_review_session"][
        "reviewer_independence"
    ]
    assert reviewer_independence["status"] == "manual_gap"
    assert reviewer_independence["reviewer_id"] == "platform-runner"
    assert reviewer_independence["candidate_worker_ids"] == ["platform-runner"]
    assert "reviewer_matches_candidate_worker" in proof["manual_gaps"]
    assert any(
        "patch lane review verdict reviewer_id matches candidate worker_id" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_reviewer_id(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    closure = json.loads(review_closure.read_text(encoding="utf-8"))
    verdict_path = tmp_path / closure["patch_lane_review_verdict_artifact"]
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict.pop("reviewer_id")
    verdict_path.write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    reviewer_independence = proof["local_execution_review_session"][
        "reviewer_independence"
    ]
    assert reviewer_independence["status"] == "manual_gap"
    assert reviewer_independence["reviewer_id"] is None
    assert "reviewer_identity_not_proven" in proof["manual_gaps"]
    assert "patch lane review verdict reviewer_id is missing" in proof["issues"]


def test_god_room_review_chain_proof_fail_closes_missing_candidate_worker_id(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    candidate_path = tmp_path / "artifacts" / "lane-runtime-evidence-patch" / "result.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate.pop("worker_id")
    candidate_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    reviewer_independence = proof["local_execution_review_session"][
        "reviewer_independence"
    ]
    assert reviewer_independence["status"] == "manual_gap"
    assert reviewer_independence["candidate_worker_ids"] == []
    assert "candidate_worker_identity_not_proven" in proof["manual_gaps"]
    assert "reviewer independence has no candidate worker identity" in proof["issues"]


def test_god_room_review_chain_proof_fail_closes_missing_graph_set_artifact(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    (tmp_path / "graph_sets" / "conv-runtime--graph-runtime-graph-set.json").unlink()

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "graph_wide_lane_accounting_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert boundary["graph_set_loaded"] is False
    assert "graph_wide_lane_accounting_not_verified" in boundary["manual_gaps"]
    assert any(
        "feature graph set artifact is not readable" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_uncovered_graph_completed_lane(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(
        tmp_path,
        graph_completed_lane_ids=[
            "lane-runtime-evidence-patch",
            "lane-runtime-evidence-extra",
        ],
        graph_set_lane_ids=[
            "lane-runtime-evidence-patch",
            "lane-runtime-evidence-extra",
        ],
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"][
        "graph_wide_lane_accounting_boundary"
    ]
    assert boundary["status"] == "manual_gap"
    assert boundary["uncovered_completed_lane_ids"] == [
        "lane-runtime-evidence-extra"
    ]
    assert any(
        "completed lanes missing platform-runner candidate lineage" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_missing_runner_session(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    (tmp_path / "work" / "runner_sessions" / "runner-session-1.json").unlink()

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"]["runner_session_boundary"]
    assert boundary["status"] == "manual_gap"
    assert "runner_session_boundary_not_verified" in boundary["manual_gaps"]
    assert any(
        "runner session artifact is not readable" in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_candidate_bundle_not_in_session(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path)
    candidate_path = tmp_path / "artifacts/lane-runtime-evidence-patch/result.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["source_refs"].append(
        "feature_evidence_bundle:platform_runner_worker_evidence_runtime_patch:v1"
    )
    candidate_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    boundary = proof["local_execution_review_session"]["runner_session_boundary"]
    assert boundary["status"] == "manual_gap"
    assert boundary["candidate_worker_evidence_bundle_refs"] == [
        "feature_evidence_bundle:platform_runner_worker_evidence_runtime_patch:v1"
    ]
    assert boundary["session_worker_evidence_bundle_refs"] == []
    assert boundary["missing_session_worker_evidence_bundle_refs"] == [
        "feature_evidence_bundle:platform_runner_worker_evidence_runtime_patch:v1"
    ]
    assert "runner_session_boundary_not_verified" in boundary["manual_gaps"]
    assert any(
        "runner session artifact does not record candidate worker evidence bundle refs"
        in issue
        for issue in proof["issues"]
    )


def test_god_room_review_chain_proof_fail_closes_server_truth_overclaim(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path, server_truth_status="merged")

    proof = build_god_room_review_chain_proof(
        root=tmp_path,
        review_closure_artifact=review_closure,
    )

    assert proof["status"] == "manual_gap"
    assert proof["proof_level"] == "manual_gap"
    assert proof["release_evidence_handoff"]["review_closure_artifact_gate_ready"] is False
    assert "GOD room review closure server_truth_status is not not_server_truth" in proof[
        "issues"
    ]
    assert "server_side_truth" in proof["forbidden_claims"]


def test_god_room_review_chain_proof_cli_writes_artifact(tmp_path: Path) -> None:
    review_closure = _write_review_closure(tmp_path)
    output = tmp_path / "reports" / "review-chain-proof.json"
    closure_output = tmp_path / "reports" / "closure-object.json"

    assert capture_main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--god-room-review-closure",
            str(review_closure),
            "--output",
            str(output),
            "--closure-object-output",
            str(closure_output),
        ]
    ) == 0

    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["status"] == "chain_ready"
    assert proof["release_evidence_handoff"]["review_closure_artifact_gate_ready"] is True
    closure = ClosureObject.from_dict(json.loads(closure_output.read_text(encoding="utf-8")))
    assert closure.status.condition(PATCH_FORWARD_LINEAGE_PRESENT).status == "true"
    assert closure.status.condition(SERVER_TRUTH_PENDING).status == "true"
    assert "pr_merged" in closure.status.forbidden_claims


def test_god_room_review_chain_proof_cli_returns_nonzero_for_manual_gap(
    tmp_path: Path,
) -> None:
    review_closure = _write_review_closure(tmp_path, create_candidate=False)
    output = tmp_path / "reports" / "review-chain-proof.json"

    assert capture_main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--god-room-review-closure",
            str(review_closure),
            "--output",
            str(output),
        ]
    ) == 2

    proof = json.loads(output.read_text(encoding="utf-8"))
    assert proof["status"] == "manual_gap"
    assert "release_evidence_candidate_gate_not_ready" in proof["manual_gaps"]


def _write_review_closure(
    root: Path,
    *,
    create_candidate: bool = True,
    create_session_artifacts: bool = True,
    create_graph_authority: bool = True,
    server_truth_status: str = "not_server_truth",
    patch_forward_patch_lane_id: str = "lane-runtime-evidence-patch",
    patch_verdict_decision: str = "merge",
    include_runner_recovery_lineage: bool = True,
    graph_completed_lane_ids: list[str] | None = None,
    graph_set_lane_ids: list[str] | None = None,
) -> Path:
    source_event_lineage = [
        {
            "event_id": "evt-runtime-freeze",
            "event_type": "freeze_requested",
            "participant_id": "part-review",
            "god_id": "god-review",
            "proof_level": "contract_proof",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    candidate_lineage: list[dict[str, object]] = []
    if create_candidate:
        _write_candidate(root / candidate_ref)
        candidate_lineage = [
            load_local_execution_candidate_lineage(
                root=root,
                artifact_ref=candidate_ref,
                lane_id="lane-runtime-evidence-patch",
                graph_id="graph-runtime",
                conversation_id="conv-runtime",
            )
        ]
    patch_forward_ref = (
        "reports/god_room_patch_forward/"
        "graph-runtime.lane-runtime-evidence.patch-forward.json"
    )
    patch_intake_ref = (
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
    )
    patch_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence-patch.review-verdict.json"
    )
    patch_forward_verdict_ref = (
        "reports/god_room_review_verdicts/"
        "graph-runtime.lane-runtime-evidence.review-verdict.json"
    )
    source_authority = (
        "god_room_lane_patch_forward_artifact+"
        "patch_lane_review_verdict_artifact+"
        "feature_graph_status_store"
    )
    if include_runner_recovery_lineage:
        source_authority += "+local_runner_recovery_proof_artifact"
    closure_path = root / "reports" / "god-room" / "review-closure.json"
    closure_path.parent.mkdir(parents=True, exist_ok=True)
    closure_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.god_room_lane_review_closure.v1",
                "source_authority": source_authority,
                "proof_level": "contract_proof",
                "review_truth_status": "independent_review_artifact",
                "execution_truth_status": "candidate_reviewed",
                "server_truth_status": server_truth_status,
                "release_evidence_handoff_status": "candidate_input_ready",
                "conversation_id": "conv-runtime",
                "graph_id": "graph-runtime",
                "failed_lane_id": "lane-runtime-evidence",
                "terminal_lane_id": "lane-runtime-evidence-patch",
                "patch_forward_artifact": patch_forward_ref,
                "patch_lane_review_intake_artifact": patch_intake_ref,
                "patch_lane_review_verdict_artifact": patch_verdict_ref,
                "candidate_refs": [
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
                "cited_candidate_refs": [
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
                "cited_candidate_artifact_refs": [candidate_ref],
                "cited_candidate_artifact_lineage": candidate_lineage,
                "terminal_review_verdict": {
                    "id": "god-room-review-verdict-merge",
                    "decision": "merge",
                    "evidence_refs": [
                        patch_intake_ref,
                        "worker-candidate:patch-reviewed",
                        candidate_ref,
                    ],
                },
                "review_plane_sync_status": "review_plane_store_updated",
                "review_plane_verdict_ref": (
                    "review-plane:lane-runtime-evidence-patch:verdict-1"
                ),
                "graph_status_source_authority": "feature_graph_status_store",
                "graph_status_merge_status": "verified_merged",
                "source_event_lineage": source_event_lineage,
                "terminal_feature_graph_status": {
                    "graph_set_id": "graph-runtime-graph-set",
                    "feature_graph_id": "graph-runtime-feature-runtime",
                    "status_id": "fgs:graph-runtime-feature-runtime:merged",
                    "status": "merged",
                    "blueprint_proof_level": "contract_proof",
                    "active_lane_ids": [],
                    "completed_lane_ids": ["lane-runtime-evidence-patch"],
                    "source_event_lineage": source_event_lineage,
                },
                "manual_gaps": [
                    "release_evidence_not_linked",
                    "github_truth_not_checked",
                ],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                    "ready_to_merge",
                    "pr_merged",
                    "github_review_truth",
                    "live_memoryos",
                    "overnight_safe_recovery",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if include_runner_recovery_lineage:
        runner_recovery_artifact = root / "reports" / "runner-recovery-proof.json"
        runner_recovery_artifact.parent.mkdir(parents=True, exist_ok=True)
        lane_recovery_artifact = (
            root / "reports" / "lane-recovery" / "lane-runtime-evidence.json"
        )
        lane_recovery_artifact.parent.mkdir(parents=True, exist_ok=True)
        lane_recovery_artifact.write_text(
            json.dumps(
                {
                    "schema_version": "xmuse.lane_recovery.v1",
                    "lane_id": "lane-runtime-evidence",
                    "status": "blocked",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        runner_recovery_proof = build_runner_recovery_proof(
            run_id="run-recovery-proof",
            runner_id="platform-runner",
            lanes=[
                {
                    "feature_id": "lane-runtime-evidence",
                    "status": "reworking",
                    "graph_id": "graph-runtime",
                },
                {
                    "feature_id": "lane-runtime-evidence-patch",
                    "status": "merged",
                    "graph_id": "graph-runtime",
                },
            ],
            candidate_lanes=[
                {
                    "feature_id": "lane-runtime-evidence-patch",
                    "status": "merged",
                    "graph_id": "graph-runtime",
                }
            ],
            runner_status={
                "health": {
                    "recovery": {
                        "source_authority": "lane_recovery_artifact",
                        "proof_level": "contract_proof",
                        "counts": {
                            "blocked": 1,
                            "non_retry_decision": 1,
                            "invalid_artifact": 0,
                            "retry_allowed": 0,
                        },
                        "blocked_lanes": [
                            {
                                "lane_id": "lane-runtime-evidence",
                                "decision": "refactor_required",
                                "artifact_ref": (
                                    "reports/lane-recovery/"
                                    "lane-runtime-evidence.json"
                                ),
                            }
                        ],
                        "invalid_artifacts": [],
                        "source_refs": [
                            "reports/lane-recovery/lane-runtime-evidence.json"
                        ],
                    }
                }
            },
            lanes_path=root / "feature_lanes.json",
            xmuse_root=root,
            graph_id="graph-runtime",
            resolution_id="resolution-runtime",
        )
        runner_recovery_artifact.write_text(
            json.dumps(runner_recovery_proof, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        runner_recovery_lineage = build_runner_recovery_proof_lineage(
            proof=runner_recovery_proof,
            artifact_ref="reports/runner-recovery-proof.json",
            graph_id="graph-runtime",
            lane_id="lane-runtime-evidence",
        )
        payload = json.loads(closure_path.read_text(encoding="utf-8"))
        payload["runner_recovery_proof_lineage"] = runner_recovery_lineage
        closure_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if create_session_artifacts:
        _write_session_artifacts(
            root=root,
            patch_forward_ref=patch_forward_ref,
            patch_intake_ref=patch_intake_ref,
            patch_verdict_ref=patch_verdict_ref,
            patch_forward_verdict_ref=patch_forward_verdict_ref,
            candidate_ref=candidate_ref,
            patch_forward_patch_lane_id=patch_forward_patch_lane_id,
            patch_verdict_decision=patch_verdict_decision,
        )
    if create_graph_authority:
        _write_graph_authority(
            root=root,
            source_event_lineage=source_event_lineage,
            completed_lane_ids=graph_completed_lane_ids
            or ["lane-runtime-evidence-patch"],
            graph_set_lane_ids=graph_set_lane_ids or ["lane-runtime-evidence-patch"],
        )
    return closure_path


def _write_graph_authority(
    *,
    root: Path,
    source_event_lineage: list[dict[str, str]],
    completed_lane_ids: list[str],
    graph_set_lane_ids: list[str],
) -> None:
    graph_set_path = root / "graph_sets" / "conv-runtime--graph-runtime-graph-set.json"
    _write_json(
        graph_set_path,
        {
            "id": "graph-runtime-graph-set",
            "version": 1,
            "source_refs": ["lane_dag:graph-runtime"],
            "source_event_lineage": source_event_lineage,
            "feature_plan": {
                "id": "graph-runtime-feature-plan",
                "conversation_id": "conv-runtime",
                "resolution_id": "resolution-runtime",
                "version": 1,
                "features": [
                    {
                        "feature_id": "feature-runtime",
                        "title": "Runtime evidence",
                        "goal": "Review runtime evidence.",
                        "acceptance_criteria": ["Review candidate evidence."],
                        "dependencies": [],
                        "graph_id": "graph-runtime-feature-runtime",
                        "expected_touched_areas": [],
                        "blueprint_refs": ["blueprint:runtime"],
                    }
                ],
            },
            "graphs": [
                {
                    "id": "graph-runtime-feature-runtime",
                    "conversation_id": "conv-runtime",
                    "resolution_id": "resolution-runtime",
                    "version": 1,
                    "status": "planned",
                    "source_refs": ["lane_dag:graph-runtime"],
                    "lanes": [
                        {
                            "feature_id": lane_id,
                            "title": lane_id,
                            "prompt": f"Execute {lane_id}",
                            "task_type": "execute",
                            "priority": 0,
                            "capabilities": ["code"],
                            "depends_on": [],
                            "gate_profile": None,
                            "gate_profiles": [],
                            "source_lane_id": None,
                            "feature_group": "feature-runtime",
                            "blueprint_refs": ["blueprint:runtime"],
                            "acceptance_criteria": ["Review candidate evidence."],
                            "expected_touched_areas": [],
                        }
                        for lane_id in graph_set_lane_ids
                    ],
                }
            ],
        },
    )
    _write_json(
        root / "feature_graph_statuses.json",
        {
            "schema_version": "xmuse.feature_graph_statuses.v1",
            "statuses": [
                {
                    "status_id": "fgs:graph-runtime-feature-runtime:merged",
                    "conversation_id": "conv-runtime",
                    "planning_run_id": "planning-runtime",
                    "graph_set_id": "graph-runtime-graph-set",
                    "graph_set_version": 1,
                    "feature_plan_id": "graph-runtime-feature-plan",
                    "feature_plan_version": 1,
                    "feature_id": "feature-runtime",
                    "feature_graph_id": "graph-runtime-feature-runtime",
                    "blueprint_proof_level": "contract_proof",
                    "source_event_lineage": source_event_lineage,
                    "status": "merged",
                    "ready_lane_ids": [],
                    "active_lane_ids": [],
                    "completed_lane_ids": completed_lane_ids,
                    "blocked_lane_ids": [],
                    "projection_lane_ids": [],
                    "feature_lanes_projection_ref": None,
                    "provider_session_binding_degradations": [],
                    "updated_at": "2026-06-15T00:00:00Z",
                }
            ],
            "events": [],
        },
    )


def _write_session_artifacts(
    *,
    root: Path,
    patch_forward_ref: str,
    patch_intake_ref: str,
    patch_verdict_ref: str,
    patch_forward_verdict_ref: str,
    candidate_ref: str,
    patch_forward_patch_lane_id: str,
    patch_verdict_decision: str,
) -> None:
    source_event_lineage = [
        {
            "event_id": "evt-runtime-freeze",
            "event_type": "freeze_requested",
            "participant_id": "part-review",
            "god_id": "god-review",
            "proof_level": "contract_proof",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    patch_forward_evidence_refs = [
        patch_forward_verdict_ref,
        "reports/god_room_review_intake/"
        "graph-runtime.lane-runtime-evidence.review-intake.json",
        "worker-candidate:patch-needed",
    ]
    _write_json(
        root / patch_forward_ref,
        {
            "schema_version": "xmuse.god_room_lane_patch_forward.v1",
            "proof_level": "contract_proof",
            "conversation_id": "conv-runtime",
            "graph_id": "graph-runtime",
            "failed_lane_id": "lane-runtime-evidence",
            "patch_lane_id": patch_forward_patch_lane_id,
            "review_verdict_artifact": patch_forward_verdict_ref,
            "patch_forward_link": {
                "failed_lane_id": "lane-runtime-evidence",
                "patch_lane_id": patch_forward_patch_lane_id,
                "verdict_ref": (
                    "god_room_review_verdict:"
                    "god-room-review-verdict-patch-forward"
                ),
                "evidence_refs": patch_forward_evidence_refs,
            },
            "patch_lane_contract": {
                "lane_id": patch_forward_patch_lane_id,
                "feature_id": "feature-runtime-evidence",
                "owner": "codex",
                "inputs": [
                    "lane:lane-runtime-evidence",
                    *patch_forward_evidence_refs,
                ],
                "outputs": [
                    f"artifact://{patch_forward_patch_lane_id}/"
                    "patch-forward-evidence.json"
                ],
                "dependency_refs": ["lane:lane-runtime-evidence"],
                "required_checks": ["focused-pytest"],
                "allowed_files": [],
                "rollback_constraints": ["preserve failed lane evidence"],
                "review_profile": "patch-forward-review",
                "memory_refs": [],
                "budget": {
                    "max_attempts": 3,
                    "max_consecutive_same_failure": 2,
                    "max_runtime_seconds": None,
                    "retry_backoff_seconds": 0,
                    "source_refs": [],
                },
                "source_refs": patch_forward_evidence_refs,
            },
            "manual_gaps": [
                "patch_lane_not_executed",
                "patch_lane_not_reviewed",
                "release_evidence_not_linked",
            ],
            "forbidden_claims": [
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
            ],
        },
    )
    _write_json(
        root / patch_forward_verdict_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-runtime",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence",
            "review_verdict": {
                "id": "god-room-review-verdict-patch-forward",
                "decision": "patch-forward",
                "evidence_refs": patch_forward_evidence_refs[1:],
            },
        },
    )
    _write_json(
        root / patch_intake_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_intake.v1",
            "source_authority": "feature_graph_status_store+lane_dag_artifact",
            "proof_level": "contract_proof",
            "review_truth_status": "pending_independent_review",
            "conversation_id": "conv-runtime",
            "graph_id": "graph-runtime",
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature-runtime",
            "feature_graph_status": {
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:reviewing",
                "status": "reviewing",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": source_event_lineage,
            },
            "lane_id": "lane-runtime-evidence-patch",
            "blueprint_proof_level": "contract_proof",
            "source_event_lineage": source_event_lineage,
            "candidate_truth_status": "candidate_only",
            "execution_artifact_refs": [candidate_ref],
        },
    )
    _write_json(
        root / patch_verdict_ref,
        {
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "proof_level": "contract_proof",
            "review_truth_status": "independent_review_artifact",
            "server_truth_status": "not_server_truth",
            "conversation_id": "conv-runtime",
            "graph_id": "graph-runtime",
            "lane_id": "lane-runtime-evidence-patch",
            "reviewer_id": "review-god",
            "review_plane_verdict_ref": (
                "review-plane:lane-runtime-evidence-patch:verdict-1"
            ),
            "review_verdict": {
                "id": "god-room-review-verdict-merge",
                "decision": patch_verdict_decision,
                "evidence_refs": [
                    patch_intake_ref,
                    "worker-candidate:patch-reviewed",
                    candidate_ref,
                ],
            },
        },
    )


def _patch_lane_review_intake_path(root: Path) -> Path:
    return (
        root
        / "reports"
        / "god_room_review_intake"
        / "graph-runtime.lane-runtime-evidence-patch.review-intake.json"
    )


def _write_candidate(path: Path) -> None:
    source_event_lineage = [
        {
            "event_id": "evt-runtime-freeze",
            "event_type": "freeze_requested",
            "participant_id": "part-review",
            "god_id": "god-review",
            "proof_level": "contract_proof",
            "source_authority": "god_room_event_store+blueprint_freeze",
        }
    ]
    _write_json(
        path,
        {
            "schema_version": "xmuse.local_execution_candidate.v1",
            "candidate_id": "candidate-lane-runtime-evidence-patch",
            "source_authority": "local_execution_candidate_capture",
            "producer": "platform_runner_dispatch",
            "conversation_id": "conv-runtime",
            "proof_level": "local_runtime_proof",
            "status": "candidate_only",
            "candidate_truth_status": "candidate_only",
            "graph_id": "graph-runtime",
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature-runtime",
            "feature_graph_status_id": "fgs:graph-runtime-feature-runtime:reviewing",
            "feature_graph_status": "reviewing",
            "graph_status_source_authority": "feature_graph_status_store",
            "graph_status_lineage": {
                "source_authority": "feature_graph_status_store",
                "graph_set_id": "graph-runtime-graph-set",
                "feature_graph_id": "graph-runtime-feature-runtime",
                "status_id": "fgs:graph-runtime-feature-runtime:reviewing",
                "status": "reviewing",
                "blueprint_proof_level": "contract_proof",
                "active_lane_ids": [],
                "completed_lane_ids": ["lane-runtime-evidence-patch"],
                "source_event_lineage": source_event_lineage,
            },
            "lane_id": "lane-runtime-evidence-patch",
            "run_id": "platform-runner:run-1",
            "worker_id": "platform-runner",
            "runner_session_id": "runner-session-1",
            "runner_session_ref": "work/runner_sessions/runner-session-1.json",
            "source_refs": ["worker-candidate:patch-reviewed"],
            "output_refs": ["artifacts/lane-runtime-evidence-patch/result.json"],
            "changed_file_refs": [],
            "verification_refs": [
                "uv run pytest tests/xmuse/test_god_room_review_chain_proof.py -q",
            ],
            "manual_gaps": [
                "review_truth_not_proven",
                "server_truth_not_proven",
                "github_truth_not_checked",
                "live_memoryos_trace_not_proven",
            ],
            "forbidden_claims": [
                "worker_output_is_review_truth",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
                "github_review_truth",
                "live_memoryos",
            ],
        },
    )
    _write_runner_session(path.parent.parent.parent)


def _write_runner_session(root: Path) -> None:
    _write_json(
        root / "work" / "runner_sessions" / "runner-session-1.json",
        {
            "schema_version": "xmuse.runner_session.v1",
            "source_authority": "platform_runner_session_boundary",
            "session_id": "runner-session-1",
            "run_id": "platform-runner:run-1",
            "runner_id": "platform-runner",
            "status": "session_completed",
            "proof_level": "local_runtime_proof",
            "started_at": "2026-06-15T00:00:00Z",
            "completed_at": "2026-06-15T00:01:00Z",
            "graph_id": "graph-runtime",
            "resolution_id": "resolution-runtime",
            "writer_lease_id": "lease-runtime",
            "candidate_artifact_refs": [
                "artifacts/lane-runtime-evidence-patch/result.json"
            ],
            "candidate_lane_ids": ["lane-runtime-evidence-patch"],
            "candidate_count": 1,
            "manual_gaps": [
                "review_truth_not_proven",
                "server_truth_not_proven",
                "github_truth_not_checked",
                "live_memoryos_trace_not_proven",
                "overnight_safe_recovery_not_proven",
            ],
            "forbidden_claims": [
                "runner_session_is_review_truth",
                "runner_session_is_server_truth",
                "runner_session_is_live_invocation_proof",
                "runner_session_is_graph_wide_closure",
                "end_to_end_execution_review_closure",
                "ready_to_merge",
                "pr_merged",
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
