import json
from pathlib import Path

import pytest

from xmuse.local_execution_candidate_capture import main as capture_main
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER,
    LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
    LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION,
    build_local_execution_candidate,
    build_local_execution_candidate_lineage,
    build_validated_execution_candidate_boundary,
    load_local_execution_candidate_lineage,
)
from xmuse_core.platform.runner_session import (
    RUNNER_SESSION_COMPLETED_STATUS,
    build_runner_session_artifact,
    build_runner_session_lineage,
)


def test_local_execution_candidate_capture_cli_writes_candidate_only_artifact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts" / "lane-a" / "result.json"

    assert (
        capture_main(
            [
                "--lane-id",
                "lane-a",
                "--candidate-id",
                "candidate-a",
                "--conversation-id",
                "conv-a",
                "--graph-id",
                "graph-a",
                "--graph-set-id",
                "graph-a-graph-set",
                "--feature-graph-id",
                "graph-a-feature-a",
                "--feature-graph-status-id",
                "fgs:graph-a:feature-a:reviewing",
                "--feature-graph-status",
                "reviewing",
                "--run-id",
                "run-a",
                "--worker-id",
                "opencode-worker",
                "--source-ref",
                "goal-stage:l9-candidate",
                "--output-ref",
                "artifacts/lane-a/stdout.txt",
                "--verification-ref",
                "uv run pytest tests/xmuse/test_local_execution_candidate.py -q",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION
    assert artifact["status"] == "candidate_only"
    assert artifact["proof_level"] == "local_runtime_proof"
    assert artifact["producer"] == LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER
    assert artifact["candidate_truth_status"] == "candidate_only"
    assert artifact["conversation_id"] == "conv-a"
    assert artifact["graph_status_source_authority"] == "feature_graph_status_store"
    assert artifact["graph_status_lineage"]["status_id"] == (
        "fgs:graph-a:feature-a:reviewing"
    )
    assert "worker_output_is_review_truth" in artifact["forbidden_claims"]
    assert "review_truth_not_proven" in artifact["manual_gaps"]

    lineage = load_local_execution_candidate_lineage(
        root=tmp_path,
        artifact_ref="artifacts/lane-a/result.json",
        conversation_id="conv-a",
        lane_id="lane-a",
        graph_id="graph-a",
    )
    assert lineage["schema_version"] == "xmuse.local_execution_candidate_lineage.v1"
    assert lineage["artifact_ref"] == "artifacts/lane-a/result.json"
    assert lineage["producer"] == LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER
    assert lineage["conversation_id"] == "conv-a"
    assert lineage["candidate_truth_status"] == "candidate_only"
    assert lineage["graph_status_lineage"]["feature_graph_id"] == "graph-a-feature-a"
    assert "uv run pytest tests/xmuse/test_local_execution_candidate.py -q" in lineage[
        "verification_refs"
    ]


def test_local_execution_candidate_lineage_rejects_review_truth_overclaim(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifacts" / "lane-a" / "result.json"
    path.parent.mkdir(parents=True)
    artifact = _candidate_artifact()
    artifact["forbidden_claims"] = ["ready_to_merge"]
    path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="missing forbidden claims"):
        load_local_execution_candidate_lineage(
            root=tmp_path,
            artifact_ref="artifacts/lane-a/result.json",
            lane_id="lane-a",
        )


def test_local_execution_candidate_lineage_rejects_lane_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifacts" / "lane-a" / "result.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            _candidate_artifact()
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lane_id does not match"):
        load_local_execution_candidate_lineage(
            root=tmp_path,
            artifact_ref="artifacts/lane-a/result.json",
            lane_id="lane-b",
        )


def test_local_execution_candidate_rejects_candidate_only_without_graph_status() -> None:
    with pytest.raises(ValueError, match="requires graph status lineage"):
        build_local_execution_candidate(
            lane_id="lane-a",
            candidate_id="candidate-a",
        )


def test_local_execution_candidate_manual_gap_preserves_missing_graph_status() -> None:
    artifact = build_local_execution_candidate(
        lane_id="lane-a",
        candidate_id="candidate-a",
        proof_level="manual_gap",
        status="manual_gap",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert "graph_status_lineage_missing" in artifact["manual_gaps"]
    assert artifact["graph_status_lineage"] is None


def test_local_execution_candidate_rejects_status_proof_level_mismatch() -> None:
    with pytest.raises(ValueError, match="status/proof_level mismatch"):
        build_local_execution_candidate(
            lane_id="lane-a",
            candidate_id="candidate-a",
            graph_id="graph-a",
            graph_set_id="graph-a-graph-set",
            feature_graph_id="graph-a-feature-a",
            feature_graph_status_id="fgs:graph-a:feature-a:reviewing",
            feature_graph_status="reviewing",
            proof_level="manual_gap",
            status="candidate_only",
        )


def test_local_execution_candidate_rejects_unsupported_graph_status_authority() -> None:
    with pytest.raises(ValueError, match="source authority is unsupported"):
        build_local_execution_candidate(
            lane_id="lane-a",
            candidate_id="candidate-a",
            graph_id="graph-a",
            graph_status_lineage={
                "source_authority": "feature_lanes_json",
                "graph_set_id": "graph-a-graph-set",
                "feature_graph_id": "graph-a-feature-a",
                "status_id": "fgs:graph-a:feature-a:reviewing",
                "status": "reviewing",
            },
        )


def test_local_execution_candidate_lineage_rejects_graph_status_field_conflict(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifacts" / "lane-a" / "result.json"
    path.parent.mkdir(parents=True)
    artifact = _candidate_artifact()
    artifact["feature_graph_status_id"] = "fgs:wrong"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="graph status fields do not match"):
        load_local_execution_candidate_lineage(
            root=tmp_path,
            artifact_ref="artifacts/lane-a/result.json",
            conversation_id="conv-a",
            lane_id="lane-a",
            graph_id="graph-a",
        )


def test_local_execution_candidate_lineage_rejects_conversation_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifacts" / "lane-a" / "result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_candidate_artifact()), encoding="utf-8")

    with pytest.raises(ValueError, match="conversation_id does not match"):
        load_local_execution_candidate_lineage(
            root=tmp_path,
            artifact_ref="artifacts/lane-a/result.json",
            conversation_id="conv-b",
            lane_id="lane-a",
            graph_id="graph-a",
        )


def test_local_execution_candidate_lineage_rejects_required_platform_runner_producer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifacts" / "lane-a" / "result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_candidate_artifact()), encoding="utf-8")

    with pytest.raises(ValueError, match="producer is not platform_runner_dispatch"):
        load_local_execution_candidate_lineage(
            root=tmp_path,
            artifact_ref="artifacts/lane-a/result.json",
            lane_id="lane-a",
            required_producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        )


def test_platform_runner_candidate_requires_run_and_worker_identity() -> None:
    with pytest.raises(ValueError, match="requires run_id, worker_id"):
        build_local_execution_candidate(
            lane_id="lane-a",
            candidate_id="candidate-a",
            graph_id="graph-a",
            graph_set_id="graph-a-graph-set",
            feature_graph_id="graph-a-feature-a",
            feature_graph_status_id="fgs:graph-a:feature-a:reviewing",
            feature_graph_status="reviewing",
            producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        )


def test_platform_runner_candidate_records_runner_session_boundary() -> None:
    artifact = build_local_execution_candidate(
        lane_id="lane-a",
        candidate_id="candidate-a",
        graph_id="graph-a",
        graph_set_id="graph-a-graph-set",
        feature_graph_id="graph-a-feature-a",
        feature_graph_status_id="fgs:graph-a:feature-a:reviewing",
        feature_graph_status="reviewing",
        run_id="local-execution-runner-1",
        worker_id="runner-1",
        runner_session_id="runner-session-a",
        runner_session_ref="work/runner_sessions/runner-session-a.json",
        producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
    )

    assert artifact["runner_session_id"] == "runner-session-a"
    assert artifact["runner_session_ref"] == (
        "work/runner_sessions/runner-session-a.json"
    )


def test_validated_execution_candidate_accepts_bounded_runner_session() -> None:
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=_platform_runner_candidate_artifact(
            source_refs=[
                "feature_evidence_bundle:bundle-a:v1",
            ],
        ),
        artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
    )
    runner_session_lineage = build_runner_session_lineage(
        artifact=_runner_session_artifact(
            worker_evidence_bundle_refs=[
                "feature_evidence_bundle:bundle-a:v1",
            ],
        ),
        artifact_ref="work/runner_sessions/session-a.json",
        session_id="session-a",
        run_id="run-a",
        runner_id="runner-a",
        candidate_artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
        graph_id="graph-a",
    )

    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=runner_session_lineage,
        graph_id="graph-a",
        lane_id="lane-a",
    )

    assert boundary["status"] == "validated"
    assert boundary["proof_level"] == "local_runtime_proof"
    assert boundary["worker_evidence_bundle_refs"] == [
        "feature_evidence_bundle:bundle-a:v1"
    ]
    assert "worker_output_is_review_truth" in boundary["forbidden_claims"]
    assert "runner_session_is_review_truth" in boundary["forbidden_claims"]


def test_validated_execution_candidate_rejects_manual_cli_candidate() -> None:
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=_candidate_artifact(),
        artifact_ref="artifacts/lane-a/result.json",
    )

    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=None,
        graph_id="graph-a",
        lane_id="lane-a",
    )

    assert boundary["status"] == "manual_gap"
    assert "local execution candidate is not platform_runner_dispatch" in boundary[
        "issues"
    ]
    assert "runner session lineage is missing" in boundary["issues"]


def test_validated_execution_candidate_requires_reviewing_graph_status() -> None:
    candidate = _platform_runner_candidate_artifact()
    candidate["graph_status_lineage"]["status"] = "running"
    candidate["feature_graph_status"] = "running"
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=candidate,
        artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
    )
    runner_session_lineage = build_runner_session_lineage(
        artifact=_runner_session_artifact(),
        artifact_ref="work/runner_sessions/session-a.json",
    )

    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=runner_session_lineage,
        graph_id="graph-a",
        lane_id="lane-a",
    )

    assert boundary["status"] == "manual_gap"
    assert "local execution candidate graph status is not reviewing" in boundary[
        "issues"
    ]


def test_validated_execution_candidate_rejects_runner_session_mismatch() -> None:
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=_platform_runner_candidate_artifact(),
        artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
    )
    runner_session_lineage = build_runner_session_lineage(
        artifact=_runner_session_artifact(run_id="run-b"),
        artifact_ref="work/runner_sessions/session-a.json",
    )

    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=runner_session_lineage,
        graph_id="graph-a",
        lane_id="lane-a",
    )

    assert boundary["status"] == "manual_gap"
    assert "runner session run_id does not match candidate" in boundary["issues"]


def test_validated_execution_candidate_requires_worker_evidence_bundle_refs() -> None:
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=_platform_runner_candidate_artifact(),
        artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
    )
    runner_session_lineage = build_runner_session_lineage(
        artifact=_runner_session_artifact(),
        artifact_ref="work/runner_sessions/session-a.json",
    )

    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=runner_session_lineage,
        graph_id="graph-a",
        lane_id="lane-a",
    )

    assert boundary["status"] == "manual_gap"
    assert (
        "local execution candidate missing graph-native worker evidence bundle refs"
        in boundary["issues"]
    )
    assert (
        "runner session missing graph-native worker evidence bundle refs"
        in boundary["issues"]
    )


def test_validated_execution_candidate_rejects_worker_bundle_mismatch() -> None:
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=_platform_runner_candidate_artifact(
            source_refs=["feature_evidence_bundle:bundle-a:v1"]
        ),
        artifact_ref="work/local_execution_candidates/graph-a.lane-a.json",
    )
    runner_session_lineage = build_runner_session_lineage(
        artifact=_runner_session_artifact(
            worker_evidence_bundle_refs=["feature_evidence_bundle:bundle-b:v1"]
        ),
        artifact_ref="work/runner_sessions/session-a.json",
    )

    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=runner_session_lineage,
        graph_id="graph-a",
        lane_id="lane-a",
    )

    assert boundary["status"] == "manual_gap"
    assert (
        "local execution candidate worker evidence bundle refs do not match "
        "runner session"
    ) in boundary["issues"]


def _candidate_artifact() -> dict:
    return build_local_execution_candidate(
        lane_id="lane-a",
        candidate_id="candidate-a",
        conversation_id="conv-a",
        graph_id="graph-a",
        graph_set_id="graph-a-graph-set",
        feature_graph_id="graph-a-feature-a",
        feature_graph_status_id="fgs:graph-a:feature-a:reviewing",
        feature_graph_status="reviewing",
    )


def _platform_runner_candidate_artifact(
    *,
    source_refs: list[str] | None = None,
) -> dict:
    return build_local_execution_candidate(
        lane_id="lane-a",
        candidate_id="candidate-a",
        conversation_id="conv-a",
        lane_local_id="lane-local-a",
        graph_id="graph-a",
        graph_set_id="graph-a-graph-set",
        feature_graph_id="graph-a-feature-a",
        feature_graph_status_id="fgs:graph-a:feature-a:reviewing",
        feature_graph_status="reviewing",
        run_id="run-a",
        worker_id="runner-a",
        runner_session_id="session-a",
        runner_session_ref="work/runner_sessions/session-a.json",
        producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        source_refs=source_refs or [],
    )


def _runner_session_artifact(
    *,
    session_id: str = "session-a",
    run_id: str = "run-a",
    runner_id: str = "runner-a",
    worker_evidence_bundle_refs: list[str] | None = None,
) -> dict:
    return build_runner_session_artifact(
        session_id=session_id,
        run_id=run_id,
        runner_id=runner_id,
        status=RUNNER_SESSION_COMPLETED_STATUS,
        started_at="2026-06-16T00:00:00Z",
        completed_at="2026-06-16T00:01:00Z",
        graph_id="graph-a",
        candidate_artifact_refs=[
            "work/local_execution_candidates/graph-a.lane-a.json"
        ],
        candidate_lane_ids=["lane-a"],
        worker_evidence_bundle_refs=worker_evidence_bundle_refs or [],
    )
