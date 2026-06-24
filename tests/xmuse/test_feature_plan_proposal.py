import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import xmuse_core.structuring.feature_plan_store as feature_plan_store_module
from xmuse.chat_api import create_app
from xmuse_core.chat.models import StructuredResolution
from xmuse_core.namespaces import build_conversation_graph_set_id
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_plan_store import (
    FeatureGraphSetStore,
    FeaturePlanStore,
    approve_feature_plan_proposal,
    build_feature_plan_proposal,
    read_approved_mission_blueprint,
)
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeaturePlanFeature,
    FeaturePlanProposal,
    FeaturePlanProposalApproval,
    FeaturePlanProposalStatus,
)
from xmuse_core.structuring.projection import project_feature_graph_set_ready_lanes


def _approved_blueprint_resolution() -> StructuredResolution:
    return StructuredResolution(
        id="res-blueprint-1",
        conversation_id="conv-1",
        version=4,
        status="approved",
        derived_from_proposal_ids=["proposal-1"],
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve blueprint",
        content={
            "type": "mission_blueprint",
            "title": "Chat-first mission",
            "body": "Make approved blueprints the source for feature planning.",
            "acceptance_criteria": [
                "Feature plans are reviewed before graph injection.",
            ],
            "references": [
                "docs/superpowers/specs/2026-05-31-xmuse-b-class-autonomy-product-contracts-blueprint-design.md",
            ],
            "proposal_blueprint_ref": "proposal_request:conv-1:blueprint-1:mission_blueprint",
            "revision_of": "resolution:res-blueprint-0:mission_blueprint",
            "blueprint_ref": "resolution:res-blueprint-1:mission_blueprint",
        },
        created_at="2026-05-31T00:00:00Z",
    )


def _feature_plan_proposal() -> FeaturePlanProposal:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())
    return FeaturePlanProposal(
        id="proposal-b2-1",
        conversation_id="conv-1",
        source_blueprint=blueprint,
        features=[
            FeaturePlanFeature(
                feature_id="feature-plan-schema",
                title="Feature plan schema",
                goal="Add the proposal domain model and store helpers.",
                acceptance_criteria=["Proposal snapshots validate."],
                graph_id="graph-feature-plan-schema",
                blueprint_refs=[blueprint.blueprint_ref],
            ),
            FeaturePlanFeature(
                feature_id="feature-plan-review",
                title="Feature plan review gate",
                goal="Require approval before graph-set injection.",
                acceptance_criteria=["Reviewed proposals are preserved."],
                dependencies=["feature-plan-schema"],
                graph_id="graph-feature-plan-review",
                blueprint_refs=[
                    blueprint.blueprint_ref,
                    blueprint.references[0],
                ],
            ),
        ],
    )


def test_read_approved_mission_blueprint_extracts_content_and_refs() -> None:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())

    assert blueprint.resolution_id == "res-blueprint-1"
    assert blueprint.conversation_id == "conv-1"
    assert blueprint.blueprint_ref == "resolution:res-blueprint-1:mission_blueprint"
    assert blueprint.acceptance_criteria == [
        "Feature plans are reviewed before graph injection.",
    ]
    assert blueprint.references == [
        "docs/superpowers/specs/2026-05-31-xmuse-b-class-autonomy-product-contracts-blueprint-design.md",
    ]


def test_feature_plan_proposal_validates_dependencies_and_blueprint_refs() -> None:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())

    with pytest.raises(ValidationError, match="dependencies reference unknown feature_id"):
        FeaturePlanProposal(
            id="proposal-bad-deps",
            conversation_id="conv-1",
            source_blueprint=blueprint,
            features=[
                FeaturePlanFeature(
                    feature_id="feature-a",
                    title="Feature A",
                    goal="Break dependency validation.",
                    acceptance_criteria=["Validation rejects missing deps."],
                    dependencies=["missing-feature"],
                    graph_id="graph-feature-a",
                    blueprint_refs=[blueprint.blueprint_ref],
                )
            ],
        )

    with pytest.raises(
        ValidationError,
        match="unknown blueprint refs for feature feature-a: docs/unknown-blueprint.md",
    ):
        FeaturePlanProposal(
            id="proposal-bad-refs",
            conversation_id="conv-1",
            source_blueprint=blueprint,
            features=[
                FeaturePlanFeature(
                    feature_id="feature-a",
                    title="Feature A",
                    goal="Break blueprint ref validation.",
                    acceptance_criteria=["Validation rejects foreign refs."],
                    graph_id="graph-feature-a",
                    blueprint_refs=["docs/unknown-blueprint.md"],
                )
            ],
        )


def test_feature_plan_proposal_rejects_dependency_cycles_before_approval() -> None:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())

    with pytest.raises(
        ValidationError,
        match="dependency cycle detected: feature-a -> feature-b -> feature-a",
    ):
        FeaturePlanProposal(
            id="proposal-cycle",
            conversation_id="conv-1",
            source_blueprint=blueprint,
            features=[
                FeaturePlanFeature(
                    feature_id="feature-a",
                    title="Feature A",
                    goal="Introduce the first node in a cycle.",
                    acceptance_criteria=["Cycles are rejected."],
                    dependencies=["feature-b"],
                    graph_id="graph-feature-a",
                    blueprint_refs=[blueprint.blueprint_ref],
                ),
                FeaturePlanFeature(
                    feature_id="feature-b",
                    title="Feature B",
                    goal="Introduce the second node in a cycle.",
                    acceptance_criteria=["Approval blocks cyclic DAGs."],
                    dependencies=["feature-a"],
                    graph_id="graph-feature-b",
                    blueprint_refs=[blueprint.blueprint_ref],
                ),
            ],
        )


def test_feature_plan_store_round_trips_proposal_without_touching_live_projection(
    tmp_path: Path,
) -> None:
    live_projection_path = tmp_path / "xmuse" / "feature_lanes.json"
    live_projection_path.parent.mkdir(parents=True)
    live_projection_path.write_text(
        json.dumps({"lanes": [{"feature_id": "existing", "status": "running"}]}) + "\n",
        encoding="utf-8",
    )
    before_projection = live_projection_path.read_text(encoding="utf-8")

    proposal = _feature_plan_proposal()
    store = FeaturePlanStore(tmp_path / "feature_plans")

    saved_path = store.save(proposal)
    loaded = store.load("proposal-b2-1")

    assert saved_path == tmp_path / "feature_plans" / "conv-1--proposal-b2-1.json"
    assert loaded == proposal
    assert live_projection_path.read_text(encoding="utf-8") == before_projection


def test_feature_plan_store_scopes_same_local_id_by_conversation(tmp_path: Path) -> None:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())
    store = FeaturePlanStore(tmp_path / "feature_plans")
    first = FeaturePlanProposal(
        id="proposal-shared",
        conversation_id="conv-1",
        source_blueprint=blueprint,
        features=[
            FeaturePlanFeature(
                feature_id="feature-a",
                title="Feature A",
                goal="Keep storage isolated.",
                acceptance_criteria=["Conversation one persists safely."],
                graph_id="graph-feature-a",
                blueprint_refs=[blueprint.blueprint_ref],
            )
        ],
    )
    second_blueprint = blueprint.model_copy(update={"conversation_id": "conv-2"})
    second = FeaturePlanProposal(
        id="proposal-shared",
        conversation_id="conv-2",
        source_blueprint=second_blueprint,
        features=[
            FeaturePlanFeature(
                feature_id="feature-b",
                title="Feature B",
                goal="Keep storage isolated.",
                acceptance_criteria=["Conversation two persists safely."],
                graph_id="graph-feature-b",
                blueprint_refs=[second_blueprint.blueprint_ref],
            )
        ],
    )

    first_path = store.save(first)
    second_path = store.save(second)

    assert first_path != second_path
    assert store.load("proposal-shared", conversation_id="conv-1") == first
    assert store.load("proposal-shared", conversation_id="conv-2") == second
    with pytest.raises(ValueError, match="ambiguous feature plan id"):
        store.load("proposal-shared")


@pytest.mark.parametrize(
    "proposal_id",
    [
        "../xmuse/feature_lanes",
        "/tmp/feature_lanes",
        "nested/feature_lanes",
        r"nested\feature_lanes",
    ],
)
def test_feature_plan_store_rejects_ids_that_escape_store_root(
    tmp_path: Path,
    proposal_id: str,
) -> None:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())
    store = FeaturePlanStore(tmp_path / "feature_plans")
    proposal = FeaturePlanProposal(
        id=proposal_id,
        conversation_id="conv-1",
        source_blueprint=blueprint,
        features=[
            FeaturePlanFeature(
                feature_id="feature-a",
                title="Feature A",
                goal="Keep ids inside the store root.",
                acceptance_criteria=["Unsafe ids are rejected."],
                graph_id="graph-feature-a",
                blueprint_refs=[blueprint.blueprint_ref],
            )
        ],
    )

    with pytest.raises(ValueError, match="unsafe feature plan id"):
        store.save(proposal)

    with pytest.raises(ValueError, match="unsafe feature plan id"):
        store.load(proposal_id)


def test_feature_plan_proposal_requires_explicit_approval_metadata_for_approval() -> None:
    blueprint = read_approved_mission_blueprint(_approved_blueprint_resolution())
    proposal = build_feature_plan_proposal(
        proposal_id="proposal-b2-approval",
        source_blueprint=blueprint,
        features=[
            FeaturePlanFeature(
                feature_id="feature-a",
                title="Feature A",
                goal="Keep approval explicit.",
                acceptance_criteria=["Approval metadata is required."],
                graph_id="graph-feature-a",
                blueprint_refs=[blueprint.blueprint_ref],
            )
        ],
    )

    with pytest.raises(ValueError, match="approved feature plan proposals require approval"):
        proposal.model_copy(update={"status": FeaturePlanProposalStatus.APPROVED}).to_feature_plan(
            resolution_id="res-approved-1",
            version=1,
        )

    with pytest.raises(
        ValidationError,
        match="approved feature plan proposals require approval metadata",
    ):
        FeaturePlanProposal(
            id="proposal-bad-approval",
            conversation_id="conv-1",
            source_blueprint=blueprint,
            status=FeaturePlanProposalStatus.APPROVED,
            features=[
                FeaturePlanFeature(
                    feature_id="feature-b",
                    title="Feature B",
                    goal="Fail validation cleanly.",
                    acceptance_criteria=["Metadata is mandatory."],
                    graph_id="graph-feature-b",
                    blueprint_refs=[blueprint.blueprint_ref],
                )
            ],
        )

    approved = approve_feature_plan_proposal(
        proposal,
        approval=FeaturePlanProposalApproval(
            approved_by=["human"],
            approval_mode="manual",
            approved_at="2026-05-31T01:00:00Z",
        ),
    )

    feature_plan = approved.to_feature_plan(resolution_id="res-approved-1", version=1)

    assert approved.status == FeaturePlanProposalStatus.APPROVED
    assert approved.approval is not None
    assert approved.approval.approved_by == ["human"]
    assert feature_plan.id == "proposal-b2-approval"
    assert feature_plan.features[0].blueprint_refs == [blueprint.blueprint_ref]


def test_feature_plan_proposal_api_approval_saves_graph_set_before_projecting_ready_lanes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post("/api/chat/conversations", json={"title": "xmuse b2"}).json()

    blueprint_proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": (
                '{"type":"mission_blueprint","title":"Chat-first mission",'
                '"body":"Approved blueprints should drive feature plans.",'
                '"acceptance_criteria":["Feature planning starts from approved refs."]}'
            ),
            "references": [],
        },
    ).json()
    blueprint_approval = client.post(
        f"/api/chat/proposals/{blueprint_proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve the blueprint",
        },
    ).json()
    blueprint_ref = blueprint_approval["content"]["blueprint_ref"]

    feature_plan_proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "feature_plan",
            "content": json.dumps(
                {
                    "type": "feature_plan",
                    "source_blueprint_ref": blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-plan-schema",
                            "title": "Feature plan schema",
                            "goal": "Persist approved feature plan proposals.",
                            "acceptance_criteria": ["Proposal records are saved."],
                            "graph_id": "graph-feature-plan-schema",
                            "blueprint_refs": [blueprint_ref],
                        },
                        {
                            "feature_id": "feature-plan-projection",
                            "title": "Feature plan projection",
                            "goal": "Project only dependency-ready lanes from the graph set.",
                            "acceptance_criteria": ["Projection waits for feature dependencies."],
                            "dependencies": ["feature-plan-schema"],
                            "graph_id": "graph-feature-plan-projection",
                            "blueprint_refs": [blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [blueprint_ref],
        },
    ).json()

    projection_calls: list[tuple[str, set[str]]] = []

    def _project_with_snapshot_assertion(graph_set, lanes_path, *, terminal_success_feature_ids):
        stored_graph_set = FeatureGraphSetStore(tmp_path / "lane_graphs").load(graph_set.id)
        assert stored_graph_set == graph_set
        projection_calls.append((graph_set.id, set(terminal_success_feature_ids)))
        return project_feature_graph_set_ready_lanes(
            graph_set,
            lanes_path,
            terminal_success_feature_ids=terminal_success_feature_ids,
        )

    monkeypatch.setattr(
        feature_plan_store_module,
        "project_feature_graph_set_ready_lanes",
        _project_with_snapshot_assertion,
        raising=False,
    )

    approved = client.post(
        f"/api/chat/proposals/{feature_plan_proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve feature plan proposal",
        },
    )

    assert approved.status_code == 200
    payload = approved.json()
    assert payload["content"] == {
        "type": "feature_plan",
        "proposal_id": feature_plan_proposal["id"],
        "source_blueprint_ref": blueprint_ref,
        "feature_ids": ["feature-plan-schema", "feature-plan-projection"],
        "graph_ids": ["graph-feature-plan-schema", "graph-feature-plan-projection"],
    }
    expected_graph_set_id = build_conversation_graph_set_id(
        conversation_id=conversation["id"],
        feature_plan_id=feature_plan_proposal["id"],
        version=payload["version"],
    )
    assert projection_calls == [(expected_graph_set_id, set())]
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))["lanes"]
    assert [lane["lane_local_id"] for lane in lanes] == [
        "feature-plan-schema-01-implement"
    ]
    assert lanes[0]["feature_plan_id"] == feature_plan_proposal["id"]
    assert lanes[0]["feature_plan_feature_id"] == "feature-plan-schema"
    assert lanes[0]["graph_id"] == "graph-feature-plan-schema"
    graph_set = FeatureGraphSetStore(tmp_path / "lane_graphs").load(expected_graph_set_id)
    status_records = FeatureGraphStatusStore(
        tmp_path / "feature_graph_statuses.json"
    ).list(graph_set_id=expected_graph_set_id)

    stored = FeaturePlanStore(tmp_path / "feature_plans").load(feature_plan_proposal["id"])

    assert stored.status == FeaturePlanProposalStatus.APPROVED
    assert stored.approval is not None
    assert stored.approval.approved_by == ["human"]
    assert stored.source_blueprint.blueprint_ref == blueprint_ref
    assert graph_set.feature_plan.id == feature_plan_proposal["id"]
    assert graph_set.feature_plan.resolution_id == payload["id"]
    assert graph_set.feature_plan.version == payload["version"]
    assert graph_set.version == payload["version"]
    assert graph_set.source_refs == [
        f"feature_plan:{feature_plan_proposal['id']}:v{payload['version']}",
        blueprint_ref,
    ]
    assert [record.feature_graph_id for record in status_records] == [
        "graph-feature-plan-schema",
        "graph-feature-plan-projection",
    ]
    assert [record.status for record in status_records] == [
        FeatureGraphExecutionStatus.READY,
        FeatureGraphExecutionStatus.PLANNED,
    ]
    assert status_records[0].ready_lane_ids == ["feature-plan-schema-01-implement"]
    assert status_records[0].projection_lane_ids == [lanes[0]["feature_id"]]
    assert status_records[1].ready_lane_ids == []
    assert status_records[1].projection_lane_ids == []
    assert [graph.id for graph in graph_set.graphs] == [
        "graph-feature-plan-schema",
        "graph-feature-plan-projection",
    ]
    assert [lane.feature_id for lane in graph_set.graphs[0].lanes] == [
        "feature-plan-schema-01-implement",
        "feature-plan-schema-99-verify",
    ]
    assert graph_set.graphs[0].lanes[1].depends_on == [
        "feature-plan-schema-01-implement"
    ]
    assert [lane.feature_id for lane in graph_set.graphs[1].lanes] == [
        "feature-plan-projection-01-implement",
        "feature-plan-projection-99-verify",
    ]
    assert graph_set.decomposition_review is not None
    assert graph_set.decomposition_review.source_blueprint_ref == blueprint_ref
    assert graph_set.decomposition_review.feature_packet.feature_ids == [
        "feature-plan-schema",
        "feature-plan-projection",
    ]
    assert [
        edge.model_dump(mode="json")
        for edge in graph_set.decomposition_review.feature_packet.dependency_edges
    ] == [
        {
            "source_id": "feature-plan-schema",
            "target_id": "feature-plan-projection",
            "rationale": (
                "Feature feature-plan-projection depends on feature-plan-schema "
                "because it declares that dependency."
            ),
            "evidence_refs": [blueprint_ref],
        }
    ]
    assert graph_set.decomposition_review.feature_packet.blueprint_refs == [blueprint_ref]
    assert graph_set.decomposition_review.supporting_refs == [blueprint_ref]
    assert [packet.graph_id for packet in graph_set.decomposition_review.lane_packets] == [
        "graph-feature-plan-schema",
        "graph-feature-plan-projection",
    ]
    assert graph_set.decomposition_review.lane_packets[0].lane_ids == [
        "feature-plan-schema-01-implement",
        "feature-plan-schema-99-verify",
    ]
    assert [
        edge.model_dump(mode="json")
        for edge in graph_set.decomposition_review.lane_packets[0].dependency_edges
    ] == [
        {
            "source_id": "feature-plan-schema-01-implement",
            "target_id": "feature-plan-schema-99-verify",
            "rationale": (
                "Lane feature-plan-schema-99-verify depends on "
                "feature-plan-schema-01-implement because it declares that dependency."
            ),
            "evidence_refs": [blueprint_ref],
        }
    ]


def test_feature_plan_proposal_api_rejects_ad_hoc_flat_lane_writes(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post("/api/chat/conversations", json={"title": "xmuse b2"}).json()

    blueprint_proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": (
                '{"type":"mission_blueprint","title":"Chat-first mission",'
                '"body":"Approved blueprints should drive feature plans.",'
                '"acceptance_criteria":["Feature planning starts from approved refs."]}'
            ),
            "references": [],
        },
    ).json()
    blueprint_ref = client.post(
        f"/api/chat/proposals/{blueprint_proposal['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve the blueprint",
        },
    ).json()["content"]["blueprint_ref"]

    feature_plan_proposal = client.post(
        f"/api/chat/conversations/{conversation['id']}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "feature_plan",
            "content": json.dumps(
                {
                    "type": "feature_plan",
                    "source_blueprint_ref": blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-plan-schema",
                            "title": "Feature plan schema",
                            "goal": "Persist approved feature plan proposals.",
                            "acceptance_criteria": ["Proposal records are saved."],
                            "graph_id": "graph-feature-plan-schema",
                            "blueprint_refs": [blueprint_ref],
                        }
                    ],
                    "lanes": [
                        {
                            "feature_id": "flat-lane-write",
                            "prompt": "This should stay out of feature plan proposals.",
                        }
                    ],
                }
            ),
            "references": [blueprint_ref],
        },
    )

    assert feature_plan_proposal.status_code == 400
    detail = feature_plan_proposal.json()["detail"]
    assert detail["code"] == "invalid_structured_escalation"
    assert "flat lanes" in detail["message"]
    assert not (tmp_path / "feature_plans").exists()
    assert not (tmp_path / "feature_lanes.json").exists()
