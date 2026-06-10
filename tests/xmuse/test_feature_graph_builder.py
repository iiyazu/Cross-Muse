from xmuse_core.chat.models import StructuredResolution
from xmuse_core.structuring.feature_graph_builder import build_feature_graph_set
from xmuse_core.structuring.models import FeaturePlan, FeaturePlanFeature
from xmuse_core.structuring.planner import build_lane_graph


def _feature_plan() -> FeaturePlan:
    return FeaturePlan(
        id="plan-1",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=3,
        features=[
            FeaturePlanFeature(
                feature_id="schema-store",
                title="Schema and store",
                goal="Add feature plan graph-set models and persistence.",
                acceptance_criteria=["Models validate.", "Store round-trips."],
                graph_id="graph-schema-store",
                expected_touched_areas=[
                    "src/xmuse_core/structuring/models.py",
                    "src/xmuse_core/structuring/feature_plan_store.py",
                ],
                blueprint_refs=["blueprint:bp-1:v1"],
            ),
            FeaturePlanFeature(
                feature_id="builder",
                title="Builder",
                goal="Build one lane graph per feature.",
                acceptance_criteria=["Each feature produces one graph."],
                dependencies=["schema-store"],
                graph_id="graph-builder",
                expected_touched_areas=[
                    "src/xmuse_core/structuring/feature_graph_builder.py",
                    "tests/xmuse/test_feature_graph_builder.py",
                ],
                blueprint_refs=["blueprint:bp-1:v1"],
            ),
        ],
    )


def test_build_feature_graph_set_creates_one_stable_graph_per_feature() -> None:
    graph_set = build_feature_graph_set(_feature_plan(), graph_set_id="graph-set-1")

    assert graph_set.id == "graph-set-1"
    assert graph_set.feature_plan == _feature_plan()
    assert [graph.id for graph in graph_set.graphs] == [
        "graph-schema-store",
        "graph-builder",
    ]
    assert [len(graph.lanes) for graph in graph_set.graphs] == [3, 3]
    assert [lane.feature_id for lane in graph_set.graphs[0].lanes] == [
        "schema-store-01-models-py",
        "schema-store-02-feature-plan-store-py",
        "schema-store-99-verify",
    ]
    assert [lane.feature_id for lane in graph_set.graphs[1].lanes] == [
        "builder-01-feature-graph-builder-py",
        "builder-02-test-feature-graph-builder-py",
        "builder-99-verify",
    ]


def test_build_feature_graph_set_keeps_root_lanes_out_of_patch_forward_lineage() -> None:
    graph_set = build_feature_graph_set(_feature_plan(), graph_set_id="graph-set-1")

    assert [
        lane.source_lane_id
        for graph in graph_set.graphs
        for lane in graph.lanes
    ] == [None, None, None, None, None, None]


def test_build_feature_graph_set_keeps_feature_dependencies_at_graph_set_level() -> None:
    graph_set = build_feature_graph_set(_feature_plan(), graph_set_id="graph-set-1")

    builder_feature = graph_set.feature_plan.features[1]
    builder_root_lanes = [
        lane for lane in graph_set.graphs[1].lanes if not lane.depends_on
    ]

    assert builder_feature.dependencies == ["schema-store"]
    assert [lane.feature_id for lane in builder_root_lanes] == [
        "builder-01-feature-graph-builder-py",
        "builder-02-test-feature-graph-builder-py",
    ]


def test_build_feature_graph_set_adds_stable_version_and_source_refs() -> None:
    graph_set = build_feature_graph_set(_feature_plan(), graph_set_id="graph-set-1")

    assert graph_set.version == 3
    assert graph_set.source_refs == ["feature_plan:plan-1:v3", "blueprint:bp-1:v1"]
    assert [graph.version for graph in graph_set.graphs] == [3, 3]
    assert [graph.source_refs for graph in graph_set.graphs] == [
        ["feature_plan:plan-1:v3", "blueprint:bp-1:v1"],
        ["feature_plan:plan-1:v3", "blueprint:bp-1:v1"],
    ]


def test_build_feature_graph_set_generates_lane_dag_with_parallel_ready_heads() -> None:
    graph = build_feature_graph_set(_feature_plan(), graph_set_id="graph-set-1").graphs[0]
    root_lanes = [lane for lane in graph.lanes if not lane.depends_on]
    verify_lane = graph.lanes[-1]

    assert [lane.feature_id for lane in root_lanes] == [
        "schema-store-01-models-py",
        "schema-store-02-feature-plan-store-py",
    ]
    assert verify_lane.feature_id == "schema-store-99-verify"
    assert verify_lane.depends_on == [
        "schema-store-01-models-py",
        "schema-store-02-feature-plan-store-py",
    ]
    assert verify_lane.acceptance_criteria == [
        "Models validate.",
        "Store round-trips.",
    ]


def test_build_feature_graph_set_disambiguates_duplicate_area_basenames() -> None:
    feature_plan = FeaturePlan(
        id="plan-duplicate-areas",
        conversation_id="conv-1",
        resolution_id="res-1",
        version=1,
        features=[
            FeaturePlanFeature(
                feature_id="schema",
                title="Schema",
                goal="Update source and test schemas.",
                acceptance_criteria=["Both schema paths are handled."],
                graph_id="graph-schema",
                expected_touched_areas=["src/pkg/models.py", "tests/models.py"],
                blueprint_refs=["blueprint:bp-1:v1"],
            )
        ],
    )

    graph = build_feature_graph_set(feature_plan, graph_set_id="graph-set-1").graphs[0]

    assert [lane.feature_id for lane in graph.lanes] == [
        "schema-01-src-pkg-models-py",
        "schema-02-tests-models-py",
        "schema-99-verify",
    ]


def test_build_feature_graph_set_defaults_to_stable_plan_graph_set_id() -> None:
    graph_set = build_feature_graph_set(_feature_plan())

    assert graph_set.id == "conv-1--plan-1-graph-set-v3"


def test_build_lane_graph_legacy_lanes_payload_is_unchanged() -> None:
    resolution = StructuredResolution(
        id="res-legacy",
        conversation_id="conv-1",
        version=4,
        derived_from_proposal_ids=["prop-1"],
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Build xmuse MVP",
        status="approved",
        created_at="2026-05-30T00:00:00Z",
        content={
            "lanes": [
                {
                    "feature_id": "legacy-a",
                    "title": "Legacy A",
                    "prompt": "Implement legacy A.",
                    "priority": 90,
                    "capabilities": ["code"],
                    "depends_on": [],
                },
                {
                    "feature_id": "legacy-b",
                    "title": "Legacy B",
                    "prompt": "Implement legacy B.",
                    "priority": 60,
                    "capabilities": ["code", "test"],
                    "depends_on": ["legacy-a"],
                },
            ]
        },
    )

    graph = build_lane_graph(resolution)

    assert graph.id == "res-legacy-graph-v4"
    assert [lane.feature_id for lane in graph.lanes] == ["legacy-a", "legacy-b"]
    assert graph.lanes[0].source_lane_id is None
    assert graph.lanes[1].depends_on == ["legacy-a"]
