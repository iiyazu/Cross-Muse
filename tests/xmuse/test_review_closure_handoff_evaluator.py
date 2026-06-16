from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.god_room_review_handoff import (
    REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION,
    build_review_closure_handoff_evaluation,
)
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS,
    capture_local_execution_candidate,
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.runner_session import build_runner_session_artifact


def test_review_closure_handoff_evaluation_marks_ready_contract_handoff(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)

    evaluation = build_review_closure_handoff_evaluation(
        root=tmp_path,
        review_closure=review_closure,
    )

    assert evaluation["schema_version"] == (
        REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION
    )
    assert evaluation["status"] == "ready"
    assert evaluation["review_truth_status"] == "independent_review_artifact"
    assert evaluation["execution_truth_status"] == "candidate_reviewed"
    assert evaluation["server_truth_status"] == "not_server_truth"
    assert evaluation["required_forbidden_claims_present"] is True
    assert evaluation["candidate_ref_count"] == 2
    assert evaluation["cited_candidate_ref_count"] == 2
    assert evaluation["candidate_artifact_ref_count"] == 1
    assert evaluation["source_event_lineage_count"] == 1
    assert evaluation["source_event_lineage_refs"] == [
        "god-room-event:evt-review-provider-speak",
        "provider_response_artifact:reports/provider-response-1.json",
        "god-room-event:evt-review-provider-speak:source",
    ]
    assert evaluation["issues"] == []


def test_review_closure_handoff_evaluation_preserves_manual_gap_forbidden_claims(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)
    review_closure["forbidden_claims"] = [
        claim
        for claim in review_closure["forbidden_claims"]
        if claim != "live_memoryos"
    ]

    evaluation = build_review_closure_handoff_evaluation(
        root=tmp_path,
        review_closure=review_closure,
    )

    assert evaluation["status"] == "manual_gap"
    assert evaluation["required_forbidden_claims_present"] is False
    assert evaluation["missing_forbidden_claims"] == ["live_memoryos"]
    assert "review_closure_handoff_not_ready" in evaluation["manual_gaps"]
    assert any("missing forbidden claims" in issue for issue in evaluation["issues"])


def test_review_closure_handoff_evaluation_blocks_server_truth_overclaim(
    tmp_path: Path,
) -> None:
    review_closure = _review_closure_payload(tmp_path)
    review_closure["server_truth_status"] = "github_review_truth"

    evaluation = build_review_closure_handoff_evaluation(
        root=tmp_path,
        review_closure=review_closure,
    )

    assert evaluation["status"] == "blocked"
    assert evaluation["server_truth_status"] == "github_review_truth"
    assert "review_closure_handoff_not_ready" in evaluation["manual_gaps"]
    assert any("overclaims server truth" in issue for issue in evaluation["issues"])


def _review_closure_payload(root: Path) -> dict[str, object]:
    candidate_ref = "artifacts/lane-runtime-evidence-patch/result.json"
    _write_candidate(root, candidate_ref)
    _write_runner_session(root, candidate_ref)
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


def _write_candidate(root: Path, candidate_ref: str) -> None:
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
        run_id="platform-runner:run-1",
        worker_id="platform-runner",
        runner_session_id="runner-session-1",
        runner_session_ref="work/runner_sessions/runner-session-1.json",
        producer="platform_runner_dispatch",
        source_refs=["worker-candidate:patch-reviewed"],
        output_refs=[candidate_ref],
        verification_refs=["uv run pytest tests/xmuse/test_review_closure_handoff_evaluator.py -q"],
    )


def _write_runner_session(root: Path, candidate_ref: str) -> None:
    artifact = build_runner_session_artifact(
        session_id="runner-session-1",
        run_id="platform-runner:run-1",
        runner_id="platform-runner",
        status="session_completed",
        started_at="2026-06-15T00:00:00Z",
        completed_at="2026-06-15T00:01:00Z",
        graph_id="graph-runtime",
        candidate_artifact_refs=[candidate_ref],
        candidate_lane_ids=["lane-runtime-evidence-patch"],
    )
    path = root / "work" / "runner_sessions" / "runner-session-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
