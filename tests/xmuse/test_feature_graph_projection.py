import json
from pathlib import Path

import pytest

from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.platform.state_validation import StateValidationError
from xmuse_core.structuring import projection as projection_module
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)
from xmuse_core.structuring.projection import (
    project_feature_graph_set_ready_lanes,
    project_ready_lanes,
)
from xmuse_core.structuring.ready_set import (
    build_graph_ready_set,
    build_ready_set_parity_evidence,
)


def _read_lanes(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["lanes"]


def _read_doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_lanes(path: Path, lanes: list[dict]) -> None:
    path.write_text(json.dumps({"lanes": lanes}, indent=2) + "\n", encoding="utf-8")


def _graph_set(*, duplicate_lane_id: bool = False) -> FeatureGraphSet:
    plan = FeaturePlan(
        id="plan-b4",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=7,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Add graph-set schema.",
                acceptance_criteria=["Schema validates."],
                graph_id="graph-schema",
            ),
            FeaturePlanFeature(
                feature_id="projection",
                title="Projection",
                goal="Project ready lanes.",
                acceptance_criteria=["Projection is safe."],
                dependencies=["schema"],
                graph_id="graph-projection",
            ),
            FeaturePlanFeature(
                feature_id="summary",
                title="Summary",
                goal="Summarize features.",
                acceptance_criteria=["Summary is read-only."],
                dependencies=["projection"],
                graph_id="graph-summary",
            ),
        ],
    )
    duplicate_id = "projection-root" if duplicate_lane_id else "schema-root"
    return FeatureGraphSet(
        id="graph-set-b4",
        feature_plan=plan,
        graphs=[
            LaneGraph(
                id="graph-schema",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[
                    LaneNode(
                        feature_id=duplicate_id,
                        prompt="Implement schema.",
                        feature_group="b4/schema",
                    )
                ],
            ),
            LaneGraph(
                id="graph-projection",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[
                    LaneNode(
                        feature_id="projection-root",
                        prompt="Implement projection.",
                        priority=90,
                        depends_on=[],
                        capabilities=["code", "test"],
                        gate_profiles=["xmuse-core"],
                        feature_group="b4/projection",
                    ),
                    LaneNode(
                        feature_id="projection-dependent",
                        prompt="Wire dependents.",
                        depends_on=["projection-root"],
                        feature_group="b4/projection",
                    ),
                ],
            ),
            LaneGraph(
                id="graph-summary",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[
                    LaneNode(
                        feature_id="summary-root",
                        prompt="Implement summary.",
                        feature_group="b4/summary",
                    )
                ],
            ),
        ],
    )


def test_project_feature_graph_set_gates_features_then_lane_dependencies(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert [lane["lane_local_id"] for lane in projected] == ["projection-root"]
    lanes = _read_lanes(lanes_path)
    assert [lane["lane_local_id"] for lane in lanes] == ["projection-root"]
    assert _read_doc(lanes_path)["projection_revision"] == 1
    assert lanes[0]["graph_id"] == "graph-projection"
    assert lanes[0]["graph_version"] == 7
    assert lanes[0]["graph_set_id"] == "graph-set-b4"
    assert lanes[0]["graph_set_version"] == 7
    assert lanes[0]["feature_plan_id"] == "plan-b4"
    assert lanes[0]["feature_plan_version"] == 7
    assert lanes[0]["plan_feature_id"] == "projection"
    assert lanes[0]["feature_plan_feature_id"] == "projection"
    assert lanes[0]["lane_local_id"] == "projection-root"
    assert lanes[0]["projection_source"] == "graph_set"
    assert (
        lanes[0]["feature_id"]
        == lanes[0]["lane_id"]
        == build_projection_lane_id(
            conversation_id="conv-1",
            graph_id="graph-projection",
            lane_local_id="projection-root",
        )
    )
    assert lanes[0]["lane_depends_on_ids"] == []
    assert lanes[0]["feature_group"] == "b4/projection"
    assert lanes[0]["depends_on"] == []
    assert lanes[0]["acceptance_criteria"] == ["Projection is safe."]


def test_project_feature_graph_set_returned_lane_carries_projection_revision(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert projected[0]["projection_revision"] == 1
    assert projected[0]["projection_source"] == "graph_set"
    assert projected[0]["graph_set_id"] == "graph-set-b4"
    assert projected[0]["feature_plan_id"] == "plan-b4"
    assert projected[0]["lane_id"] == projected[0]["feature_id"]
    assert "projection_revision" not in _read_lanes(lanes_path)[0]


def test_project_ready_lanes_carries_dispatch_authority_refs(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph = LaneGraph(
        id="graph-dispatch",
        conversation_id="conv-dispatch",
        resolution_id="res-dispatch",
        version=1,
        source_refs=[
            "proposal:prop-dispatch",
            "collaboration:run-dispatch",
            "resolution:res-dispatch",
            "chat_dispatch_queue:dispatch:conv-dispatch:res-dispatch:execute",
        ],
        lanes=[
            LaneNode(
                feature_id="dispatch-consumer",
                prompt="Consume the approved dispatch authority.",
            )
        ],
    )

    projected = project_ready_lanes(graph, lanes_path)

    assert projected[0]["source_refs"] == graph.source_refs
    assert (
        projected[0]["dispatch_queue_entry_id"]
        == "dispatch:conv-dispatch:res-dispatch:execute"
    )
    stored = _read_lanes(lanes_path)
    assert stored[0]["source_refs"] == graph.source_refs
    assert (
        stored[0]["dispatch_queue_entry_id"]
        == "dispatch:conv-dispatch:res-dispatch:execute"
    )


def test_project_feature_graph_set_is_idempotent_without_revision_churn(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"

    first_projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )
    first_doc = _read_doc(lanes_path)
    second_projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )
    second_doc = _read_doc(lanes_path)

    assert [lane["lane_local_id"] for lane in first_projected] == ["projection-root"]
    assert second_projected == []
    assert second_doc["projection_revision"] == first_doc["projection_revision"] == 1
    assert [lane["feature_id"] for lane in second_doc["lanes"]] == [
        first_projected[0]["feature_id"]
    ]


def test_project_feature_graph_set_rejects_existing_state_machine_guard_violation(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    before = {
        "lanes": [
            {
                "feature_id": build_projection_lane_id(
                    conversation_id="conv-1",
                    graph_id="graph-schema",
                    lane_local_id="schema-root",
                ),
                "lane_id": build_projection_lane_id(
                    conversation_id="conv-1",
                    graph_id="graph-schema",
                    lane_local_id="schema-root",
                ),
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "graph_id": "graph-schema",
                "status": "not-a-lane-state",
            }
        ],
        "projection_revision": 7,
    }
    lanes_path.write_text(json.dumps(before, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(StateValidationError, match="unknown status"):
        project_feature_graph_set_ready_lanes(
            _graph_set(),
            lanes_path,
            terminal_success_feature_ids={"schema"},
        )

    assert _read_doc(lanes_path) == before


def test_project_feature_graph_set_prefers_lane_acceptance_when_present(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph_set = _graph_set()
    graph_set.graphs[1].lanes[0].acceptance_criteria = [
        "Implement only the projection root slice."
    ]

    projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert projected[0]["acceptance_criteria"] == [
        "Implement only the projection root slice."
    ]


def test_project_feature_graph_set_uses_authoritative_feature_terminal_evidence(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": build_projection_lane_id(
                    conversation_id="conv-1",
                    graph_id="graph-schema",
                    lane_local_id="schema-root",
                ),
                "lane_id": build_projection_lane_id(
                    conversation_id="conv-1",
                    graph_id="graph-schema",
                    lane_local_id="schema-root",
                ),
                "lane_local_id": "schema-root",
                "conversation_id": "conv-1",
                "graph_id": "graph-schema",
                "status": "merged",
            }
        ],
    )

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids=set(),
    )

    assert projected == []
    assert _read_lanes(lanes_path)[0]["lane_local_id"] == "schema-root"


def test_project_feature_graph_set_releases_lane_dependents_after_successful_projection(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": build_projection_lane_id(
                    conversation_id="conv-1",
                    graph_id="graph-projection",
                    lane_local_id="projection-root",
                ),
                "lane_id": build_projection_lane_id(
                    conversation_id="conv-1",
                    graph_id="graph-projection",
                    lane_local_id="projection-root",
                ),
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "graph_id": "graph-projection",
                "status": "merged",
            }
        ],
    )

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert [lane["lane_local_id"] for lane in projected] == ["projection-dependent"]
    assert projected[0]["lane_depends_on_ids"] == [
        build_projection_lane_id(
            conversation_id="conv-1",
            graph_id="graph-projection",
            lane_local_id="projection-root",
        )
    ]
    assert projected[0]["depends_on"] == projected[0]["lane_depends_on_ids"]
    assert [lane["lane_local_id"] for lane in _read_lanes(lanes_path)] == [
        "projection-root",
        "projection-dependent",
    ]
    assert _read_doc(lanes_path)["projection_revision"] == 1


def test_project_feature_graph_set_uses_scoped_identity_for_legacy_lineage_rows(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "projection-root",
                "lane_id": "projection-root",
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "graph_id": "graph-projection",
                "status": "merged",
            }
        ],
    )

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert [lane["lane_local_id"] for lane in projected] == ["projection-dependent"]
    assert projected[0]["lane_depends_on_ids"] == [
        build_projection_lane_id(
            conversation_id="conv-1",
            graph_id="graph-projection",
            lane_local_id="projection-root",
        )
    ]


def test_project_feature_graph_set_legacy_lineage_ready_set_uses_scoped_lane_ids(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "projection-root",
                "lane_id": "projection-root",
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "graph_id": "graph-projection",
                "status": "merged",
            }
        ],
    )

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert [lane["feature_id"] for lane in projected] == [
        build_projection_lane_id(
            conversation_id="conv-1",
            graph_id="graph-projection",
            lane_local_id="projection-dependent",
        )
    ]
    assert projected[0]["depends_on"] == [
        build_projection_lane_id(
            conversation_id="conv-1",
            graph_id="graph-projection",
            lane_local_id="projection-root",
        )
    ]


def test_graph_ready_set_read_model_emits_parity_evidence_for_scoped_dependencies(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_lanes(
        lanes_path,
        [
            {
                "feature_id": "projection-root",
                "lane_id": "projection-root",
                "lane_local_id": "projection-root",
                "conversation_id": "conv-1",
                "graph_id": "graph-projection",
                "resolution_id": "res-1",
                "status": "merged",
            }
        ],
    )

    projected = project_feature_graph_set_ready_lanes(
        _graph_set(),
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )
    ready_set = build_graph_ready_set(
        _read_lanes(lanes_path),
        graph_id="graph-projection",
        resolution_id="res-1",
    )
    parity = build_ready_set_parity_evidence(
        legacy_candidates=projected,
        ready_set_candidates=ready_set,
        graph_id="graph-projection",
        resolution_id="res-1",
    )

    assert [lane["feature_id"] for lane in ready_set] == [
        build_projection_lane_id(
            conversation_id="conv-1",
            graph_id="graph-projection",
            lane_local_id="projection-dependent",
        )
    ]
    assert parity == {
        "matches": True,
        "runner_source": "legacy_projection",
        "ready_set_source": "graph_native",
        "graph_id": "graph-projection",
        "resolution_id": "res-1",
        "legacy_candidate_lane_ids": [
            build_projection_lane_id(
                conversation_id="conv-1",
                graph_id="graph-projection",
                lane_local_id="projection-dependent",
            )
        ],
        "ready_set_lane_ids": [
            build_projection_lane_id(
                conversation_id="conv-1",
                graph_id="graph-projection",
                lane_local_id="projection-dependent",
            )
        ],
        "legacy_only_lane_ids": [],
        "ready_set_only_lane_ids": [],
    }


def test_project_feature_graph_set_allows_same_local_lane_id_across_conversations(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    shared_graph = _graph_set()
    shared_graph.graphs[1].lanes[0].feature_id = "lane-shared"
    shared_graph.graphs[1].lanes[1].depends_on = ["lane-shared"]
    shared_graph.graphs[1].lanes[1].feature_id = "lane-shared-dependent"

    other_graph = _graph_set()
    other_graph.feature_plan.conversation_id = "conv-2"
    other_graph.feature_plan.resolution_id = "res-2"
    other_graph.graphs[0].conversation_id = "conv-2"
    other_graph.graphs[0].resolution_id = "res-2"
    other_graph.graphs[1].conversation_id = "conv-2"
    other_graph.graphs[1].resolution_id = "res-2"
    other_graph.graphs[1].lanes[0].feature_id = "lane-shared"
    other_graph.graphs[1].lanes[1].feature_id = "lane-shared-dependent"
    other_graph.graphs[1].lanes[1].depends_on = ["lane-shared"]
    other_graph.graphs[2].conversation_id = "conv-2"
    other_graph.graphs[2].resolution_id = "res-2"

    first_projected = project_feature_graph_set_ready_lanes(
        shared_graph,
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )
    second_projected = project_feature_graph_set_ready_lanes(
        other_graph,
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert [lane["lane_local_id"] for lane in first_projected] == ["lane-shared"]
    assert [lane["lane_local_id"] for lane in second_projected] == ["lane-shared"]
    assert first_projected[0]["feature_id"] == first_projected[0]["lane_id"]
    assert second_projected[0]["feature_id"] == second_projected[0]["lane_id"]
    assert first_projected[0]["lane_id"] != second_projected[0]["lane_id"]
    assert [lane["feature_id"] for lane in _read_lanes(lanes_path)] == [
        first_projected[0]["feature_id"],
        second_projected[0]["feature_id"],
    ]


def test_project_feature_graph_set_allows_duplicate_local_lane_ids_across_graphs(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph_set = _graph_set(duplicate_lane_id=True)
    graph_set.feature_plan.features[1].dependencies = []

    projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids=set(),
    )

    assert [lane["lane_local_id"] for lane in projected] == [
        "projection-root",
        "projection-root",
    ]
    assert projected[0]["lane_id"] != projected[1]["lane_id"]
    assert projected[0]["graph_id"] != projected[1]["graph_id"]
    assert [lane["lane_local_id"] for lane in _read_lanes(lanes_path)] == [
        "projection-root",
        "projection-root",
    ]


def test_project_feature_graph_set_preflight_failure_never_leaves_partial_update(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    before = json.dumps({"lanes": [{"feature_id": "existing", "status": "pending"}]}) + "\n"
    lanes_path.write_text(before, encoding="utf-8")
    graph_set = _graph_set()
    graph_set.graphs[1].lanes[1].depends_on = ["missing-lane"]

    with pytest.raises(ValueError, match="unknown lane dependency: missing-lane"):
        project_feature_graph_set_ready_lanes(
            graph_set,
            lanes_path,
            terminal_success_feature_ids={"schema"},
        )

    assert lanes_path.read_text(encoding="utf-8") == before


def test_project_feature_graph_set_rejects_unknown_feature_dependency_before_write(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    before = json.dumps({"lanes": [{"feature_id": "existing", "status": "pending"}]}) + "\n"
    lanes_path.write_text(before, encoding="utf-8")
    graph_set = _graph_set()
    graph_set.feature_plan.features[1].dependencies = ["missing-feature"]

    with pytest.raises(ValueError, match="unknown feature dependency: missing-feature"):
        project_feature_graph_set_ready_lanes(
            graph_set,
            lanes_path,
            terminal_success_feature_ids={"schema"},
        )

    assert lanes_path.read_text(encoding="utf-8") == before


def test_project_feature_graph_set_payload_uses_explicit_safe_allowlist(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph_set = _graph_set()
    root = graph_set.graphs[1].lanes[0]
    root.__dict__.update(
        {
            "stdout": "large stdout",
            "review_text": "long review",
            "worker_logs": ["log"],
            "dashboard_summary": "summary",
            "runtime_telemetry": {"tokens": 1000},
        }
    )

    projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )

    assert set(projected[0]) == {
        "feature_id",
        "lane_id",
        "lane_local_id",
        "lane_depends_on_ids",
        "task_type",
        "status",
        "prompt_summary",
        "prompt_ref",
        "capabilities",
        "priority",
        "depends_on",
        "conversation_id",
        "resolution_id",
        "graph_id",
        "graph_version",
        "graph_set_id",
        "graph_set_version",
        "source_refs",
        "gate_profiles",
        "feature_group",
        "feature_plan_id",
        "feature_plan_version",
        "plan_feature_id",
        "feature_plan_feature_id",
        "projection_source",
        "projection_revision",
        "acceptance_criteria",
    }
    forbidden = {
        "prompt",
        "stdout",
        "review_text",
        "worker_logs",
        "dashboard_summary",
        "runtime_telemetry",
    }
    assert forbidden.isdisjoint(projected[0])
    assert projected[0]["prompt_summary"] == "Implement projection."
    assert projected[0]["prompt_ref"].endswith(".md")


def test_feature_lane_field_classifications_are_explicit_for_retained_projection_fields() -> None:
    assert hasattr(projection_module, "FEATURE_LANE_FIELD_CLASSIFICATIONS")
    classifications = projection_module.FEATURE_LANE_FIELD_CLASSIFICATIONS

    assert classifications["feature_id"] == "projection"
    assert classifications["review_runtime"] == "projection"
    assert classifications["final_action"] == "projection"
    assert classifications["proof_boundary"] == "projection"
    assert classifications["feature_scope_id"] == "projection"
    assert classifications["prompt_summary"] == "projection"
    assert classifications["prompt_ref"] == "projection"
    assert classifications["status"] == "legacy"
    assert classifications["worktree"] == "operational"
    assert classifications["branch"] == "operational"
    assert classifications["base_head_sha"] == "operational"
    assert "provider_profile_ref" not in classifications


def test_project_ready_lanes_single_graph_remains_backward_compatible(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph = LaneGraph(
        id="legacy-graph",
        conversation_id="conv-legacy",
        resolution_id="res-legacy",
        version=2,
        lanes=[
            LaneNode(feature_id="legacy-root", prompt="Build root."),
            LaneNode(
                feature_id="legacy-dependent",
                prompt="Build dependent.",
                depends_on=["legacy-root"],
            ),
        ],
    )

    projected = project_ready_lanes(graph, lanes_path)

    assert [lane["feature_id"] for lane in projected] == ["legacy-root"]
    assert _read_lanes(lanes_path)[0]["graph_id"] == "legacy-graph"
    assert _read_doc(lanes_path)["projection_revision"] == 1
    assert "feature_plan_id" not in projected[0]
    assert "plan_feature_id" not in projected[0]


def test_project_ready_lanes_rejects_duplicate_lane_ids_before_write(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    with pytest.raises(ValueError, match="duplicate lane id: duplicate"):
        LaneGraph(
            id="duplicate-graph",
            conversation_id="conv-legacy",
            resolution_id="res-legacy",
            version=2,
            lanes=[
                LaneNode(feature_id="duplicate", prompt="Build root."),
                LaneNode(feature_id="duplicate", prompt="Build duplicate."),
            ],
        )

    assert not lanes_path.exists()


def test_project_ready_lanes_increments_revision_for_later_successful_projection(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph = LaneGraph(
        id="legacy-graph",
        conversation_id="conv-legacy",
        resolution_id="res-legacy",
        version=2,
        lanes=[
            LaneNode(feature_id="legacy-root", prompt="Build root."),
            LaneNode(
                feature_id="legacy-dependent",
                prompt="Build dependent.",
                depends_on=["legacy-root"],
            ),
        ],
    )

    project_ready_lanes(graph, lanes_path)
    data = _read_doc(lanes_path)
    data["lanes"][0]["status"] = "merged"
    lanes_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    projected = project_ready_lanes(graph, lanes_path)

    assert [lane["feature_id"] for lane in projected] == ["legacy-dependent"]
    assert _read_doc(lanes_path)["projection_revision"] == 2
