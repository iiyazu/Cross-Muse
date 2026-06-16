from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS,
    capture_local_execution_candidate,
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.runner_session import build_runner_session_artifact

DEFAULT_GRAPH_ID = "graph-runtime"
DEFAULT_FAILED_LANE_ID = "lane-runtime-evidence"
DEFAULT_TERMINAL_LANE_ID = "lane-runtime-evidence-patch"
DEFAULT_CONVERSATION_ID = "conv-runtime"
DEFAULT_CANDIDATE_REF = "artifacts/lane-runtime-evidence-patch/result.json"
DEFAULT_RUN_ID = "platform-runner:run-1"
DEFAULT_RUNNER_ID = "platform-runner"
DEFAULT_RUNNER_SESSION_ID = "runner-session-1"
DEFAULT_RUNNER_SESSION_REF = "work/runner_sessions/runner-session-1.json"
DEFAULT_WORKER_EVIDENCE_BUNDLE_REF = (
    "feature_evidence_bundle:platform_runner_worker_evidence_runtime_patch:v1"
)


def write_candidate(
    root: Path,
    candidate_ref: str = DEFAULT_CANDIDATE_REF,
    *,
    producer: str = "platform_runner_dispatch",
    worker_evidence_bundle_ref: str | None = DEFAULT_WORKER_EVIDENCE_BUNDLE_REF,
    verification_refs: list[str] | None = None,
) -> None:
    platform_runner_candidate = producer == "platform_runner_dispatch"
    source_refs = ["worker-candidate:patch-reviewed"]
    if platform_runner_candidate and worker_evidence_bundle_ref is not None:
        source_refs.append(worker_evidence_bundle_ref)
    capture_local_execution_candidate(
        output_path=root / candidate_ref,
        lane_id=DEFAULT_TERMINAL_LANE_ID,
        candidate_id="candidate-runtime-1",
        conversation_id=DEFAULT_CONVERSATION_ID,
        graph_id=DEFAULT_GRAPH_ID,
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
            "completed_lane_ids": [DEFAULT_TERMINAL_LANE_ID],
            "source_event_lineage": [],
        },
        run_id=DEFAULT_RUN_ID if platform_runner_candidate else None,
        worker_id=DEFAULT_RUNNER_ID if platform_runner_candidate else None,
        runner_session_id=(
            DEFAULT_RUNNER_SESSION_ID if platform_runner_candidate else None
        ),
        runner_session_ref=(
            DEFAULT_RUNNER_SESSION_REF if platform_runner_candidate else None
        ),
        producer=producer,
        source_refs=source_refs,
        output_refs=[candidate_ref],
        verification_refs=verification_refs
        or ["uv run pytest tests/xmuse/test_closure_reconciler.py -q"],
    )


def write_runner_session(
    root: Path,
    candidate_ref: str = DEFAULT_CANDIDATE_REF,
    *,
    run_id: str = DEFAULT_RUN_ID,
    worker_evidence_bundle_ref: str | None = DEFAULT_WORKER_EVIDENCE_BUNDLE_REF,
) -> None:
    artifact = build_runner_session_artifact(
        session_id=DEFAULT_RUNNER_SESSION_ID,
        run_id=run_id,
        runner_id=DEFAULT_RUNNER_ID,
        status="session_completed",
        started_at="2026-06-16T00:00:00Z",
        completed_at="2026-06-16T00:01:00Z",
        graph_id=DEFAULT_GRAPH_ID,
        candidate_artifact_refs=[candidate_ref],
        candidate_lane_ids=[DEFAULT_TERMINAL_LANE_ID],
        worker_evidence_bundle_refs=(
            [worker_evidence_bundle_ref]
            if worker_evidence_bundle_ref is not None
            else []
        ),
    )
    path = root / DEFAULT_RUNNER_SESSION_REF
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def review_closure_payload(
    root: Path,
    candidate_ref: str = DEFAULT_CANDIDATE_REF,
    *,
    ensure_artifacts: bool = True,
) -> dict[str, object]:
    if ensure_artifacts:
        write_candidate(root, candidate_ref)
        write_runner_session(root, candidate_ref)
    candidate_lineage = load_local_execution_candidate_lineage(
        root=root,
        artifact_ref=candidate_ref,
        lane_id=DEFAULT_TERMINAL_LANE_ID,
        graph_id=DEFAULT_GRAPH_ID,
        conversation_id=DEFAULT_CONVERSATION_ID,
        required_producer="platform_runner_dispatch",
    )
    return {
        "schema_version": "xmuse.god_room_lane_review_closure.v1",
        "proof_level": "contract_proof",
        "review_truth_status": "independent_review_artifact",
        "execution_truth_status": "candidate_reviewed",
        "server_truth_status": "not_server_truth",
        "release_evidence_handoff_status": "candidate_input_ready",
        "conversation_id": DEFAULT_CONVERSATION_ID,
        "graph_id": DEFAULT_GRAPH_ID,
        "failed_lane_id": DEFAULT_FAILED_LANE_ID,
        "terminal_lane_id": DEFAULT_TERMINAL_LANE_ID,
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


def review_chain_proof_payload(
    candidate_ref: str = DEFAULT_CANDIDATE_REF,
) -> dict[str, object]:
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
    return {
        "schema_version": "xmuse.god_room_lane_review_chain_proof.v1",
        "status": "chain_ready",
        "proof_level": "contract_proof",
        "server_truth_status": "not_server_truth",
        "graph_id": DEFAULT_GRAPH_ID,
        "failed_lane_id": DEFAULT_FAILED_LANE_ID,
        "terminal_lane_id": DEFAULT_TERMINAL_LANE_ID,
        "review_closure_artifact": (
            "reports/god_room_review_closures/"
            "graph-runtime.lane-runtime-evidence.review-closure.json"
        ),
        "source_refs": [
            "god-room-review-closure:graph-runtime:failed:terminal",
            patch_forward_ref,
            patch_intake_ref,
            patch_verdict_ref,
        ],
        "release_evidence_handoff": {
            "review_closure_artifact_gate_ready": True,
            "review_closure_candidate_artifact_refs": [candidate_ref],
        },
        "local_execution_review_session": {
            "schema_version": "xmuse.local_execution_review_session.v1",
            "status": "bounded_session_ready",
            "proof_level": "contract_proof",
            "graph_id": DEFAULT_GRAPH_ID,
            "failed_lane_id": DEFAULT_FAILED_LANE_ID,
            "terminal_lane_id": DEFAULT_TERMINAL_LANE_ID,
            "candidate_artifact_refs": [candidate_ref],
            "session_source_refs": [
                "reports/runner-recovery-proof.json",
                "reports/lane-recovery/lane-runtime-evidence.json",
            ],
            "patch_forward_artifact": patch_forward_ref,
            "patch_lane_review_intake_artifact": patch_intake_ref,
            "patch_lane_review_verdict_artifact": patch_verdict_ref,
            "session_artifact_validation": {
                "status": "validated",
                "proof_level": "contract_proof",
            },
            "patch_forward_artifact_boundary": {
                "status": "resolved_with_retained_manual_gaps",
                "proof_level": "contract_proof",
                "retained_manual_gaps": ["release_evidence_not_linked"],
            },
        },
        "forbidden_claims": list(LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS),
    }


def release_handoff_payload() -> dict[str, object]:
    return review_chain_proof_payload()
