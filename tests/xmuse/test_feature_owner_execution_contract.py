from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.structuring.feature_owner_contract import (
    FeatureOwnerExecutionContract,
    build_feature_owner_execution_contract,
)


def test_feature_owner_contract_summarizes_graph_native_ready_set() -> None:
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

    payload = contract.model_dump(mode="json")

    assert payload["schema_version"] == "xmuse.feature_owner_execution_contract.v2"
    assert payload["feature_id"] == "feature-runtime-loop"
    assert payload["source_authority"] == "graph_set_store"
    assert payload["source_refs"] == ["graph-set:graph-set-1", "blueprint:bp-1"]
    assert payload["ready_lane_ids"] == ["lane-heartbeat"]
    assert payload["blocked_lane_ids"] == ["lane-replay"]
    assert payload["completed_lane_ids"] == ["lane-docs"]
    assert payload["lane_count"] == 3
    assert payload["lane_authority"] == "graph_native_ready_set"
    assert payload["feature_lanes_projection_authority"] is False
    assert payload["memory_refs"] == ["memory://conversation/conv-1/context"]
    assert payload["required_checks"] == [
        "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"
    ]
    assert payload["ready_set_provenance"] == {
        "authority": "graph_native_ready_set",
        "computed_from": "graph_set_store",
        "feature_graph_id": "graph-runtime",
        "graph_set_id": "graph-set-1",
        "projection_authority": False,
        "source_refs": ["graph-set:graph-set-1", "blueprint:bp-1"],
        "status_write_policy": "read_only_contract_no_status_writes",
    }
    assert payload["lane_blockers"] == [
        {
            "lane_id": "lane-replay",
            "blocker_type": "dependency_unsatisfied",
            "blocker_ref": "lane:lane-heartbeat",
            "blocker_status": "pending",
            "dispatch_blocking": True,
            "source_authority": "graph_native_ready_set",
        }
    ]
    assert payload["review_profile"] == "internal-adversarial"
    assert payload["patch_forward_policy"] == "review_failures_spawn_patch_forward_lane"
    assert payload["rollback_constraints"] == ["do not mutate feature_lanes.json"]


def test_feature_owner_contract_rejects_feature_lanes_projection_as_authority() -> None:
    with pytest.raises(ValidationError, match="feature_lanes.json is projection"):
        FeatureOwnerExecutionContract(
            feature_id="feature-runtime-loop",
            objective="Reject projection authority.",
            graph_set_id="graph-set-1",
            feature_graph_id="graph-runtime",
            source_authority="feature_lanes_projection",
            source_refs=["xmuse/feature_lanes.json"],
            allowed_files=["src/xmuse_core/platform/overnight_operator_supervisor.py"],
            lane_ids=["lane-heartbeat"],
            ready_lane_ids=["lane-heartbeat"],
            required_checks=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
            review_profile="internal-adversarial",
            patch_forward_policy="review_failures_spawn_patch_forward_lane",
            rollback_constraints=["do not mutate feature_lanes.json"],
        )


def test_feature_owner_contract_rejects_ready_lanes_not_owned_by_feature() -> None:
    with pytest.raises(ValidationError, match="ready_lane_ids must be owned lanes"):
        FeatureOwnerExecutionContract(
            feature_id="feature-runtime-loop",
            objective="Reject foreign ready lanes.",
            graph_set_id="graph-set-1",
            feature_graph_id="graph-runtime",
            source_authority="graph_set_store",
            source_refs=["graph-set:graph-set-1"],
            allowed_files=["src/xmuse_core/platform/overnight_operator_supervisor.py"],
            lane_ids=["lane-heartbeat"],
            ready_lane_ids=["lane-foreign"],
            required_checks=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
            review_profile="internal-adversarial",
            patch_forward_policy="review_failures_spawn_patch_forward_lane",
            rollback_constraints=["revert feature branch"],
        )


def test_feature_owner_contract_rejects_blocked_lane_without_blocker_evidence() -> None:
    with pytest.raises(ValidationError, match="blocked_lane_ids require lane_blockers"):
        FeatureOwnerExecutionContract(
            feature_id="feature-runtime-loop",
            objective="Reject opaque blocked lanes.",
            graph_set_id="graph-set-1",
            feature_graph_id="graph-runtime",
            source_authority="graph_set_store",
            source_refs=["graph-set:graph-set-1"],
            allowed_files=["src/xmuse_core/platform/overnight_operator_supervisor.py"],
            lane_ids=["lane-heartbeat"],
            blocked_lane_ids=["lane-heartbeat"],
            required_checks=["uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"],
            review_profile="internal-adversarial",
            patch_forward_policy="review_failures_spawn_patch_forward_lane",
            rollback_constraints=["revert feature branch"],
        )
