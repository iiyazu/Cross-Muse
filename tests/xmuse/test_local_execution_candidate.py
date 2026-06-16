import json
from pathlib import Path

import pytest

from xmuse.local_execution_candidate_capture import main as capture_main
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER,
    LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
    LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION,
    build_local_execution_candidate,
    load_local_execution_candidate_lineage,
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
