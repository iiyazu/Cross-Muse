from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.feature_lineage_evidence_capture import (
    capture_feature_lineage_evidence,
)
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)
from xmuse_core.structuring.feature_owner_contract import (
    build_feature_owner_execution_contract,
)


def test_capture_feature_lineage_evidence_exports_replay_ready_artifact(
    tmp_path: Path,
) -> None:
    contract_artifact = _write_contract(tmp_path / "feature-owner-contract.json")
    output = tmp_path / "feature-lineage-production-evidence.json"

    artifact = capture_feature_lineage_evidence(
        run_id="overnight-feature-lineage",
        contract_artifacts=[contract_artifact],
        output_path=output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == artifact
    assert artifact["schema_version"] == "xmuse.production_evidence.v1"
    assert artifact["run_id"] == "overnight-feature-lineage"
    assert artifact["stage_id"] == "S3"
    assert artifact["action"] == "feature_lineage_verified"
    assert artifact["status"] == "ok"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["source_authority"] == "feature_owner_execution_contract"
    assert artifact["source_refs"] == [
        "feature-owner:feature-runtime-loop",
        "graph-set:graph-set-1",
        "feature-graph:graph-runtime",
        "ready-set:graph-native:graph-set-1:graph-runtime",
        "blueprint:bp-1",
        "lane:lane-heartbeat",
        "lane:lane-replay",
        "lane:lane-docs",
        "lane-blocker:lane-replay:lane:lane-heartbeat",
        "memory://conversation/conv-1/context",
    ]
    assert artifact["target_refs"] == [
        "feature:feature-runtime-loop",
        "graph-set:graph-set-1",
        "feature-graph:graph-runtime",
        "lane:lane-heartbeat",
        "lane:lane-replay",
        "lane:lane-docs",
    ]
    assert artifact["artifacts"] == [str(contract_artifact)]
    assert artifact["blocked_reason"] is None
    assert artifact["summary"] == (
        "Feature lineage captured 1 feature owner contract(s), 3 lane(s): "
        "1 ready, 1 blocked, 1 completed, 1 blocker reason(s)."
    )
    assert artifact["feature_lineage"] == {
        "authority": "feature_owner_execution_contract",
        "contract_count": 1,
        "lane_count": 3,
        "ready_lane_count": 1,
        "blocked_lane_count": 1,
        "completed_lane_count": 1,
        "blocker_count": 1,
        "projection_authority": False,
        "status_write_policy": "read_only_contract_no_status_writes",
        "features": [
            {
                "feature_id": "feature-runtime-loop",
                "objective": "Run the overnight supervisor with replayable evidence.",
                "graph_set_id": "graph-set-1",
                "feature_graph_id": "graph-runtime",
                "lane_ids": ["lane-heartbeat", "lane-replay", "lane-docs"],
                "ready_lane_ids": ["lane-heartbeat"],
                "blocked_lane_ids": ["lane-replay"],
                "completed_lane_ids": ["lane-docs"],
                "lane_blockers": [
                    {
                        "lane_id": "lane-replay",
                        "blocker_type": "dependency_unsatisfied",
                        "blocker_ref": "lane:lane-heartbeat",
                        "blocker_status": "pending",
                        "dispatch_blocking": True,
                        "source_authority": "graph_native_ready_set",
                    }
                ],
                "ready_set_provenance": {
                    "authority": "graph_native_ready_set",
                    "computed_from": "graph_set_store",
                    "feature_graph_id": "graph-runtime",
                    "graph_set_id": "graph-set-1",
                    "projection_authority": False,
                    "source_refs": ["graph-set:graph-set-1", "blueprint:bp-1"],
                    "status_write_policy": "read_only_contract_no_status_writes",
                },
                "allowed_files": [
                    "src/xmuse_core/platform/overnight_operator_supervisor.py"
                ],
                "required_checks": [
                    "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"
                ],
                "review_profile": "internal-adversarial",
                "patch_forward_policy": "review_failures_spawn_patch_forward_lane",
                "rollback_constraints": ["do not mutate feature_lanes.json"],
            }
        ],
    }

    replay_bundle = capture_overnight_replay_bundle(
        run_id="overnight-feature-lineage",
        artifacts_dir=tmp_path / "empty-release-gates",
        output_path=tmp_path / "bundle.json",
        section_artifacts={"feature_lineage": output},
    )
    sections = {section["section_id"]: section for section in replay_bundle["sections"]}
    assert sections["feature_lineage"]["status"] == "ok"
    assert sections["feature_lineage"]["proof_level"] == "contract_proof"
    assert sections["feature_lineage"]["source_authority"] == (
        "feature_owner_execution_contract"
    )
    assert sections["feature_lineage"]["details"]["feature_lineage"] == (
        artifact["feature_lineage"]
    )


def test_capture_feature_lineage_evidence_reports_manual_gap_without_contracts(
    tmp_path: Path,
) -> None:
    artifact = capture_feature_lineage_evidence(
        run_id="overnight-feature-lineage",
        contract_artifacts=[],
        output_path=tmp_path / "feature-lineage-production-evidence.json",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["blocked_reason"] == (
        "no feature owner execution contracts were supplied"
    )
    assert artifact["next_action"] == (
        "Capture or attach feature owner execution contracts generated from "
        "graph-set authority."
    )


def test_feature_lineage_evidence_capture_cli_writes_artifact(
    tmp_path: Path,
) -> None:
    from xmuse.feature_lineage_evidence_capture import main

    contract_artifact = _write_contract(tmp_path / "feature-owner-contract.json")
    output = tmp_path / "feature-lineage-production-evidence.json"

    assert (
        main(
            [
                "--run-id",
                "overnight-feature-lineage",
                "--contract",
                str(contract_artifact),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "ok"
    assert artifact["action"] == "feature_lineage_verified"


def test_feature_lineage_evidence_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-feature-lineage-evidence-capture"]
        == "xmuse.feature_lineage_evidence_capture:main"
    )


def _write_contract(path: Path) -> Path:
    contract = build_feature_owner_execution_contract(
        feature_id="feature-runtime-loop",
        objective="Run the overnight supervisor with replayable evidence.",
        graph_set_id="graph-set-1",
        feature_graph_id="graph-runtime",
        source_authority="graph_set_store",
        source_refs=("graph-set:graph-set-1", "blueprint:bp-1"),
        allowed_files=("src/xmuse_core/platform/overnight_operator_supervisor.py",),
        lanes=(
            {
                "feature_id": "lane-heartbeat",
                "lane_local_id": "lane-heartbeat",
                "conversation_id": "conv-1",
                "graph_id": "graph-runtime",
                "status": "pending",
                "depends_on": [],
            },
            {
                "feature_id": "lane-replay",
                "lane_local_id": "lane-replay",
                "conversation_id": "conv-1",
                "graph_id": "graph-runtime",
                "status": "pending",
                "depends_on": ["lane-heartbeat"],
            },
            {
                "feature_id": "lane-docs",
                "lane_local_id": "lane-docs",
                "conversation_id": "conv-1",
                "graph_id": "graph-runtime",
                "status": "merged",
                "depends_on": [],
            },
        ),
        memory_refs=("memory://conversation/conv-1/context",),
        required_checks=("uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q",),
        review_profile="internal-adversarial",
        patch_forward_policy="review_failures_spawn_patch_forward_lane",
        rollback_constraints=("do not mutate feature_lanes.json",),
    )
    path.write_text(
        json.dumps(contract.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
