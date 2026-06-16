import json
from pathlib import Path

import pytest

from xmuse_core.platform.runner_session import (
    RUNNER_SESSION_COMPLETED_STATUS,
    RUNNER_SESSION_SCHEMA_VERSION,
    capture_runner_session_finished,
    capture_runner_session_started,
    load_runner_session_lineage,
)


def test_runner_session_records_completed_local_runtime_boundary(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work" / "runner_sessions" / "session-a.json"

    capture_runner_session_started(
        output_path=path,
        session_id="session-a",
        run_id="local-execution-runner-1",
        runner_id="runner-1",
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
        graph_id="graph-a",
        writer_lease_id="lease-a",
    )
    artifact = capture_runner_session_finished(
        output_path=path,
        status=RUNNER_SESSION_COMPLETED_STATUS,
        candidate_artifact_refs=["work/local_execution_candidates/graph-a.lane-a.json"],
        candidate_lane_ids=["lane-a"],
        worker_evidence_bundle_refs=[
            "feature_evidence_bundle:platform_runner_worker_evidence_graph-a_lane-a:v1"
        ],
    )

    assert artifact["schema_version"] == RUNNER_SESSION_SCHEMA_VERSION
    assert artifact["status"] == "session_completed"
    assert artifact["proof_level"] == "local_runtime_proof"
    assert artifact["candidate_count"] == 1
    assert artifact["worker_evidence_bundle_refs"] == [
        "feature_evidence_bundle:platform_runner_worker_evidence_graph-a_lane-a:v1"
    ]
    assert artifact["worker_evidence_bundle_count"] == 1
    assert "runner_session_is_review_truth" in artifact["forbidden_claims"]
    assert "review_truth_not_proven" in artifact["manual_gaps"]

    lineage = load_runner_session_lineage(
        root=tmp_path,
        artifact_ref="work/runner_sessions/session-a.json",
        session_id="session-a",
        run_id="local-execution-runner-1",
        runner_id="runner-1",
        candidate_artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
        graph_id="graph-a",
    )
    assert lineage["schema_version"] == "xmuse.runner_session_lineage.v1"
    assert lineage["status"] == "session_completed"
    assert lineage["proof_level"] == "local_runtime_proof"
    assert lineage["candidate_artifact_refs"] == [
        "work/local_execution_candidates/graph-a.lane-a.json"
    ]
    assert lineage["worker_evidence_bundle_refs"] == [
        "feature_evidence_bundle:platform_runner_worker_evidence_graph-a_lane-a:v1"
    ]
    assert lineage["worker_evidence_bundle_count"] == 1


def test_runner_session_completed_without_candidates_remains_manual_gap(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work" / "runner_sessions" / "session-a.json"

    capture_runner_session_started(
        output_path=path,
        session_id="session-a",
        run_id="local-execution-runner-1",
        runner_id="runner-1",
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
        graph_id="graph-a",
    )
    artifact = capture_runner_session_finished(
        output_path=path,
        status=RUNNER_SESSION_COMPLETED_STATUS,
    )

    assert artifact["status"] == "session_completed"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["candidate_count"] == 0
    assert "runner_session_candidate_refs_missing" in artifact["manual_gaps"]
    assert "runner_session_not_completed" not in artifact["manual_gaps"]
    assert "runner_session_is_review_truth" in artifact["forbidden_claims"]
    with pytest.raises(
        ValueError,
        match="runner session proof level is not local_runtime_proof",
    ):
        load_runner_session_lineage(
            root=tmp_path,
            artifact_ref="work/runner_sessions/session-a.json",
        )


def test_runner_session_lineage_fail_closes_incomplete_session(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work" / "runner_sessions" / "session-a.json"
    capture_runner_session_started(
        output_path=path,
        session_id="session-a",
        run_id="local-execution-runner-1",
        runner_id="runner-1",
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
    )

    with pytest.raises(ValueError, match="runner session is not completed"):
        load_runner_session_lineage(
            root=tmp_path,
            artifact_ref="work/runner_sessions/session-a.json",
        )


def test_runner_session_failed_status_remains_manual_gap(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work" / "runner_sessions" / "session-a.json"
    capture_runner_session_started(
        output_path=path,
        session_id="session-a",
        run_id="local-execution-runner-1",
        runner_id="runner-1",
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
    )
    artifact = capture_runner_session_finished(
        output_path=path,
        status="session_failed",
        failure="RuntimeError: writer lease lost",
    )

    assert artifact["status"] == "session_failed"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["failure"] == "RuntimeError: writer lease lost"
    assert "runner_session_not_completed" in artifact["manual_gaps"]
    with pytest.raises(ValueError, match="runner session is not completed"):
        load_runner_session_lineage(
            root=tmp_path,
            artifact_ref="work/runner_sessions/session-a.json",
        )


def test_runner_session_lineage_rejects_missing_forbidden_claims(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work" / "runner_sessions" / "session-a.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": RUNNER_SESSION_SCHEMA_VERSION,
                "source_authority": "platform_runner_session_boundary",
                "session_id": "session-a",
                "run_id": "local-execution-runner-1",
                "runner_id": "runner-1",
                "status": "session_completed",
                "proof_level": "local_runtime_proof",
                "started_at": "2026-06-15T00:00:00Z",
                "completed_at": "2026-06-15T00:01:00Z",
                "candidate_artifact_refs": [],
                "candidate_lane_ids": [],
                "manual_gaps": [
                    "review_truth_not_proven",
                    "server_truth_not_proven",
                    "github_truth_not_checked",
                    "live_memoryos_trace_not_proven",
                    "overnight_safe_recovery_not_proven",
                ],
                "forbidden_claims": ["ready_to_merge"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing forbidden claims"):
        load_runner_session_lineage(
            root=tmp_path,
            artifact_ref="work/runner_sessions/session-a.json",
        )
