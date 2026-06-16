import json
from pathlib import Path

from xmuse_core.platform.closure_objects import (
    INDEPENDENT_REVIEW_VERDICT_PRESENT,
    RECOVERY_ALLOWS_PROGRESS,
    RECOVERY_ARTIFACT_PRESENT,
    RELEASE_HANDOFF_EVALUATED,
    REQUIRED_FORBIDDEN_CLAIMS,
    SERVER_TRUTH_PENDING,
    VALIDATED_EXECUTION_CANDIDATE_PRESENT,
    closure_condition_by_type,
)
from xmuse_core.platform.closure_reconciler import (
    reconcile_closure,
)
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS,
    capture_local_execution_candidate,
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.runner_session import build_runner_session_artifact


def test_reconcile_closure_emits_idempotent_conditions_for_current_artifacts(
    tmp_path: Path,
) -> None:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(tmp_path, candidate_ref)
    _write_runner_session(tmp_path, candidate_ref)
    review_closure = _review_closure_payload(tmp_path, candidate_ref)
    release_handoff = {
        "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
        "status": "ready",
        "server_truth_status": "not_server_truth",
        "source_refs": ["god-room-review-closure:graph-runtime:failed:terminal"],
        "forbidden_claims": ["ready_to_merge"],
    }

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
    assert first.status.phase == "release_handoff_evaluated"
    assert first.status.proof_level == "contract_proof"
    assert _condition_status(first, RECOVERY_ARTIFACT_PRESENT) == "true"
    assert _condition_status(first, RECOVERY_ALLOWS_PROGRESS) == "true"
    assert _condition_status(first, VALIDATED_EXECUTION_CANDIDATE_PRESENT) == "true"
    assert _condition_status(first, INDEPENDENT_REVIEW_VERDICT_PRESENT) == "true"
    assert _condition_status(first, RELEASE_HANDOFF_EVALUATED) == "true"
    assert _condition_status(first, SERVER_TRUTH_PENDING) == "true"
    assert set(REQUIRED_FORBIDDEN_CLAIMS).issubset(first.status.forbidden_claims)
    assert "live_memoryos" in first.status.forbidden_claims
    assert "github_review_truth" in first.status.forbidden_claims


def test_reconcile_closure_fails_closed_when_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    closure = reconcile_closure(
        root=tmp_path,
        graph_id="graph-runtime",
        lane_id="lane-runtime-evidence-patch",
    )

    assert closure.status.phase == "manual_gap"
    assert _condition_status(closure, RECOVERY_ARTIFACT_PRESENT) == "false"
    assert _condition_status(closure, RECOVERY_ALLOWS_PROGRESS) == "unknown"
    assert _condition_status(closure, VALIDATED_EXECUTION_CANDIDATE_PRESENT) == "false"
    assert _condition_status(closure, INDEPENDENT_REVIEW_VERDICT_PRESENT) == "false"
    assert _condition_status(closure, RELEASE_HANDOFF_EVALUATED) == "false"
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
            "server_truth_status": "not_server_truth",
        },
    )

    condition = closure_condition_by_type(closure, RELEASE_HANDOFF_EVALUATED)
    assert condition is not None
    assert condition.status == "false"
    assert condition.severity == "manual_gap"
    assert condition.reason == "release handoff is missing source refs"


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


def _review_closure_payload(root: Path, candidate_ref: str) -> dict[str, object]:
    candidate_lineage = load_local_execution_candidate_lineage(
        root=root,
        artifact_ref=candidate_ref,
        lane_id="lane-runtime-evidence-patch",
        graph_id="graph-runtime",
        conversation_id="conv-runtime",
        required_producer="platform_runner_dispatch",
    )
    return {
        "schema_version": "xmuse.god_room_lane_review_closure.v1",
        "proof_level": "contract_proof",
        "review_truth_status": "independent_review_artifact",
        "execution_truth_status": "candidate_reviewed",
        "server_truth_status": "not_server_truth",
        "release_evidence_handoff_status": "candidate_input_ready",
        "conversation_id": "conv-runtime",
        "graph_id": "graph-runtime",
        "failed_lane_id": "lane-runtime-evidence",
        "terminal_lane_id": "lane-runtime-evidence-patch",
        "candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
        "cited_candidate_refs": ["worker-candidate:patch-reviewed", candidate_ref],
        "cited_candidate_artifact_refs": [candidate_ref],
        "cited_candidate_artifact_lineage": [candidate_lineage],
        "source_event_lineage": [
            {
                "event_id": "evt-review-provider-speak",
                "event_type": "speak",
                "proof_level": "opt_in_live_proof",
                "provider_response_artifact_ref": "reports/provider-response-1.json",
                "source_refs": ["god-room-event:evt-review-provider-speak:source"],
            }
        ],
        "terminal_review_verdict": {
            "evidence_refs": ["worker-candidate:patch-reviewed", candidate_ref],
        },
        "manual_gaps": ["release_evidence_not_linked"],
        "forbidden_claims": list(LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS),
    }


def _write_candidate(
    root: Path,
    candidate_ref: str,
    *,
    producer: str = "platform_runner_dispatch",
) -> None:
    platform_runner_candidate = producer == "platform_runner_dispatch"
    capture_local_execution_candidate(
        output_path=root / candidate_ref,
        lane_id="lane-runtime-evidence-patch",
        candidate_id="candidate-runtime-1",
        conversation_id="conv-runtime",
        graph_id="graph-runtime",
        graph_set_id="graph-runtime-graph-set",
        feature_graph_id="graph-runtime-feature",
        feature_graph_status_id="fgs:graph-runtime-feature:reviewing",
        feature_graph_status="reviewing",
        graph_status_lineage={
            "source_authority": "feature_graph_status_store",
            "graph_set_id": "graph-runtime-graph-set",
            "feature_graph_id": "graph-runtime-feature",
            "status_id": "fgs:graph-runtime-feature:reviewing",
            "status": "reviewing",
            "blueprint_proof_level": "contract_proof",
            "active_lane_ids": [],
            "completed_lane_ids": ["lane-runtime-evidence-patch"],
            "source_event_lineage": [],
        },
        run_id="platform-runner:run-1" if platform_runner_candidate else None,
        worker_id="platform-runner" if platform_runner_candidate else None,
        runner_session_id="runner-session-1" if platform_runner_candidate else None,
        runner_session_ref=(
            "work/runner_sessions/runner-session-1.json"
            if platform_runner_candidate
            else None
        ),
        producer=producer,
        source_refs=["worker-candidate:patch-reviewed"],
        output_refs=[candidate_ref],
        verification_refs=["uv run pytest tests/xmuse/test_closure_reconciler.py -q"],
    )


def _write_runner_session(
    root: Path,
    candidate_ref: str,
    *,
    run_id: str = "platform-runner:run-1",
) -> None:
    artifact = build_runner_session_artifact(
        session_id="runner-session-1",
        run_id=run_id,
        runner_id="platform-runner",
        status="session_completed",
        started_at="2026-06-16T00:00:00Z",
        completed_at="2026-06-16T00:01:00Z",
        graph_id="graph-runtime",
        candidate_artifact_refs=[candidate_ref],
        candidate_lane_ids=["lane-runtime-evidence-patch"],
    )
    path = root / "work" / "runner_sessions" / "runner-session-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
