from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.structuring.feature_owner_contract_export import (
    export_feature_owner_contracts_from_graph_set,
)


def test_export_feature_owner_contracts_from_graph_set_writes_graph_native_contracts(
    tmp_path: Path,
) -> None:
    graph_set = _write_graph_set(tmp_path / "graph-set.json")
    output_dir = tmp_path / "contracts"

    contracts = export_feature_owner_contracts_from_graph_set(
        graph_set_artifact=graph_set,
        output_dir=output_dir,
        feature_ids=("feature-runtime-loop",),
        required_checks=("uv run pytest tests/xmuse/test_feature_owner_contract.py -q",),
        review_profile="internal-adversarial",
        patch_forward_policy="review_failures_spawn_patch_forward_lane",
        rollback_constraints=("do not mutate feature_lanes.json",),
    )

    assert [path.name for path in contracts] == ["feature-runtime-loop-contract.json"]
    payload = json.loads(contracts[0].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.feature_owner_execution_contract.v2"
    assert payload["feature_id"] == "feature-runtime-loop"
    assert payload["objective"] == "Run the overnight supervisor with replayable evidence."
    assert payload["graph_set_id"] == "graph-set-1"
    assert payload["feature_graph_id"] == "graph-runtime"
    assert payload["source_authority"] == "graph_set_store"
    assert payload["source_refs"] == [
        "graph-set:graph-set-1",
        f"artifact:{graph_set}",
        "blueprint:bp-1",
    ]
    assert payload["allowed_files"] == [
        "src/xmuse_core/platform/overnight_operator_supervisor.py",
        "tests/xmuse/test_overnight_operator_supervisor.py",
    ]
    assert payload["lane_ids"] == ["lane-heartbeat", "lane-replay", "lane-docs"]
    assert payload["ready_lane_ids"] == ["lane-heartbeat"]
    assert payload["blocked_lane_ids"] == ["lane-replay"]
    assert payload["completed_lane_ids"] == ["lane-docs"]
    assert payload["lane_blockers"] == [
        {
            "blocker_ref": "lane:lane-heartbeat",
            "blocker_status": "pending",
            "blocker_type": "dependency_unsatisfied",
            "dispatch_blocking": True,
            "lane_id": "lane-replay",
            "source_authority": "graph_native_ready_set",
        }
    ]
    assert payload["feature_lanes_projection_authority"] is False
    assert payload["ready_set_provenance"]["computed_from"] == "graph_set_store"


def test_feature_owner_contract_export_cli_writes_selected_contract(
    tmp_path: Path,
) -> None:
    from xmuse.feature_owner_contract_export import main

    graph_set = _write_graph_set(tmp_path / "graph-set.json")
    output_dir = tmp_path / "contracts"

    assert (
        main(
            [
                "--graph-set",
                str(graph_set),
                "--output-dir",
                str(output_dir),
                "--feature-id",
                "feature-runtime-loop",
                "--required-check",
                "uv run pytest tests/xmuse/test_feature_owner_contract.py -q",
            ]
        )
        == 0
    )

    assert (output_dir / "feature-runtime-loop-contract.json").exists()


def test_feature_owner_contract_export_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-feature-owner-contract-export"]
        == "xmuse.feature_owner_contract_export:main"
    )


def _write_graph_set(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "id": "graph-set-1",
                "feature_plan": {
                    "id": "plan-1",
                    "conversation_id": "conv-1",
                    "features": [
                        {
                            "feature_id": "feature-runtime-loop",
                            "graph_id": "graph-runtime",
                            "goal": "Run the overnight supervisor with replayable evidence.",
                            "blueprint_refs": ["blueprint:bp-1"],
                        }
                    ],
                },
                "graphs": [
                    {
                        "id": "graph-runtime",
                        "conversation_id": "conv-1",
                        "lanes": [
                            {
                                "feature_id": "lane-heartbeat",
                                "lane_local_id": "lane-heartbeat",
                                "conversation_id": "conv-1",
                                "graph_id": "graph-runtime",
                                "status": "pending",
                                "depends_on": [],
                                "expected_touched_areas": [
                                    "src/xmuse_core/platform/overnight_operator_supervisor.py"
                                ],
                            },
                            {
                                "feature_id": "lane-replay",
                                "lane_local_id": "lane-replay",
                                "conversation_id": "conv-1",
                                "graph_id": "graph-runtime",
                                "status": "pending",
                                "depends_on": ["lane-heartbeat"],
                                "expected_touched_areas": [
                                    "tests/xmuse/test_overnight_operator_supervisor.py"
                                ],
                            },
                            {
                                "feature_id": "lane-docs",
                                "lane_local_id": "lane-docs",
                                "conversation_id": "conv-1",
                                "graph_id": "graph-runtime",
                                "status": "merged",
                                "depends_on": [],
                                "expected_touched_areas": [
                                    "src/xmuse_core/platform/overnight_operator_supervisor.py"
                                ],
                            },
                        ],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
