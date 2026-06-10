from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.planning_god_adapters import (
    ArchitectGodAdapter,
    PlannerGodAdapter,
    PlanningGodAdapterError,
    ReviewGodAdapter,
    build_architect_god_prompt,
    build_planner_god_prompt,
    build_planning_review_prompt,
)
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.structuring.models import ApprovedMissionBlueprint
from xmuse_core.structuring.planning_contracts import (
    ArchitectGodRequest,
    ArchitectGodResponse,
    PlannerGodRequest,
    PlannerGodResponse,
    PlanningReviewRequest,
    PlanningReviewResponse,
)


class FakeSessionLayer:
    def __init__(self, *, message: StdoutMessage | None = None) -> None:
        self.message = message
        self.ensure_calls: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []

    async def ensure_conversation_session(self, **kwargs: Any) -> GodSessionRecord:
        self.ensure_calls.append(kwargs)
        return GodSessionRecord(
            god_session_id="god-peer-1",
            role=kwargs["role"],
            agent_name=kwargs["agent"].name,
            runtime=kwargs["agent"].runtime.value,
            session_address="@peer",
            session_inbox_id="inbox-peer",
            conversation_id=kwargs["conversation_id"],
            participant_id=kwargs["participant_id"],
            model=kwargs.get("model"),
            prompt_fingerprint=kwargs.get("prompt_fingerprint"),
            worktree=str(kwargs.get("worktree")),
            feature_scope_id=kwargs.get("feature_scope_id"),
        )

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None:
        return self.message


def _approved_blueprint(*, conversation_id: str = "conv-1") -> ApprovedMissionBlueprint:
    return ApprovedMissionBlueprint(
        resolution_id="res-blueprint-1",
        conversation_id=conversation_id,
        version=1,
        title="Autonomous blueprint execution MVP",
        body="Turn approved mission blueprints into feature plans and graph sets.",
        acceptance_criteria=[
            "Planner returns a medium-grained feature plan proposal.",
            "Architect returns per-feature lane DAGs.",
        ],
        references=[
            "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
            "xmuse/work/c_class_autonomous_blueprint_execution_graph_preview.md",
        ],
        blueprint_ref="resolution:res-blueprint-1:mission_blueprint",
    )


def _planner_request(*, conversation_id: str = "conv-1") -> PlannerGodRequest:
    return PlannerGodRequest(
        request_id="planner-req-1",
        correlation_id="corr-1",
        conversation_id=conversation_id,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        artifact_refs=["artifact:blueprint-card-1"],
        blueprint=_approved_blueprint(conversation_id=conversation_id),
    )


def _planner_response_payload(*, conversation_id: str = "conv-1") -> dict[str, Any]:
    return {
        "request_id": "planner-req-1",
        "correlation_id": "corr-1",
        "conversation_id": conversation_id,
        "feature_plan_id": "feature-plan-1",
        "feature_plan_version": 1,
        "source_blueprint_ref": "resolution:res-blueprint-1:mission_blueprint",
        "artifact_refs": [
            "artifact:blueprint-card-1",
            "artifact:planner-proposal-1",
        ],
        "blueprint_refs": [
            "resolution:res-blueprint-1:mission_blueprint",
            "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
        ],
        "planning_rationale": "Split the MVP into durable planning and DAG generation.",
        "features": [
            {
                "feature_id": "C1",
                "title": "Planning run durability",
                "goal": "Persist planning runs and durable outbox state.",
                "acceptance_criteria": [
                    "Planning runs are replay-safe.",
                ],
                "dependencies": [],
                "graph_id": "graph-C1",
                "blueprint_refs": [
                    "resolution:res-blueprint-1:mission_blueprint",
                ],
                "artifact_refs": ["artifact:planner-proposal-1"],
                "risk_notes": ["Touches idempotent recovery behavior."],
                "planning_rationale": "This is the root persistence slice.",
                "dependency_rationale": "No prerequisite feature exists.",
            },
            {
                "feature_id": "C3",
                "title": "Planner and Architect contracts",
                "goal": "Define GOD planning contracts and adapters.",
                "acceptance_criteria": [
                    "Planner and Architect outputs validate.",
                ],
                "dependencies": ["C1"],
                "graph_id": "graph-C3",
                "blueprint_refs": [
                    "resolution:res-blueprint-1:mission_blueprint",
                    "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
                ],
                "artifact_refs": ["artifact:planner-proposal-1"],
                "risk_notes": ["Requires strict request correlation."],
                "planning_rationale": "Contracts unlock structured feature-to-lane handoff.",
                "dependency_rationale": "Contracts depend on durable planning identifiers.",
            },
        ],
    }


def _architect_request(*, conversation_id: str = "conv-1") -> ArchitectGodRequest:
    planner_response = _planner_response_payload(conversation_id=conversation_id)
    return ArchitectGodRequest(
        request_id="architect-req-1",
        correlation_id="corr-2",
        conversation_id=conversation_id,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        graph_set_id="graph-set-1",
        graph_set_version=1,
        artifact_refs=["artifact:planner-proposal-1"],
        blueprint_refs=planner_response["blueprint_refs"],
        features=planner_response["features"],
    )


def _architect_response_payload(*, conversation_id: str = "conv-1") -> dict[str, Any]:
    return {
        "request_id": "architect-req-1",
        "correlation_id": "corr-2",
        "conversation_id": conversation_id,
        "feature_plan_id": "feature-plan-1",
        "feature_plan_version": 1,
        "graph_set_id": "graph-set-1",
        "graph_set_version": 1,
        "artifact_refs": [
            "artifact:planner-proposal-1",
            "artifact:graph-set-proposal-1",
        ],
        "blueprint_refs": [
            "resolution:res-blueprint-1:mission_blueprint",
            "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
        ],
        "feature_graphs": [
            {
                "feature_id": "C1",
                "graph_id": "graph-C1",
                "title": "Planning run durability",
                "goal": "Persist planning runs and durable outbox state.",
                "dependencies": [],
                "artifact_refs": ["artifact:graph-set-proposal-1"],
                "lanes": [
                    {
                        "lane_id": "lane-c1-01",
                        "local_lane_id": "C1-01",
                        "feature_id": "C1",
                        "title": "Durable planning identifiers",
                        "prompt": "Persist durable identifiers for planning runs.",
                        "acceptance_criteria": [
                            "Planner/architect requests can reuse durable ids.",
                        ],
                        "dependencies": [],
                        "capabilities": ["code", "test"],
                        "expected_touched_areas": ["src/xmuse_core/structuring/*"],
                        "artifact_refs": ["artifact:graph-set-proposal-1"],
                        "blueprint_refs": [
                            "resolution:res-blueprint-1:mission_blueprint",
                        ],
                        "feature_refs": ["feature-plan-1:C1"],
                        "dependency_rationale": "This root lane establishes the identifiers.",
                    }
                ],
            },
            {
                "feature_id": "C3",
                "graph_id": "graph-C3",
                "title": "Planner Architect Contracts",
                "goal": "Define bounded planning adapter contracts.",
                "dependencies": ["C1"],
                "artifact_refs": ["artifact:graph-set-proposal-1"],
                "lanes": [
                    {
                        "lane_id": "lane-c3-01",
                        "local_lane_id": "C3-01",
                        "feature_id": "C3",
                        "title": "Planner Architect Contracts",
                        "prompt": "Add planner/architect contracts and tests.",
                        "acceptance_criteria": [
                            "Requests and responses carry request and correlation ids.",
                            "Architect output includes self-check and dependency rationale.",
                        ],
                        "dependencies": [],
                        "capabilities": ["code", "test"],
                        "expected_touched_areas": [
                            "src/xmuse_core/agents/*",
                            "src/xmuse_core/structuring/*",
                        ],
                        "artifact_refs": ["artifact:graph-set-proposal-1"],
                        "blueprint_refs": [
                            "resolution:res-blueprint-1:mission_blueprint",
                        ],
                        "feature_refs": ["feature-plan-1:C3"],
                        "dependency_rationale": "This lane can start once the feature exists.",
                    }
                ],
            }
        ],
        "decomposition_review": {
            "packet_id": "feature-plan-1:graph-set-review",
            "source_blueprint_ref": "resolution:res-blueprint-1:mission_blueprint",
            "supporting_refs": [
                "resolution:res-blueprint-1:mission_blueprint",
                "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
            ],
            "feature_packet": {
                "packet_id": "feature-plan-1:feature-review",
                "source_blueprint_ref": "resolution:res-blueprint-1:mission_blueprint",
                "feature_ids": ["C1", "C3"],
                "dependency_edges": [
                    {
                        "source_id": "C1",
                        "target_id": "C3",
                        "rationale": "Contracts depend on durable planning identifiers.",
                        "evidence_refs": ["resolution:res-blueprint-1:mission_blueprint"],
                    }
                ],
                "review_warnings": [],
                "blueprint_refs": [
                    "resolution:res-blueprint-1:mission_blueprint",
                    "docs/superpowers/specs/2026-05-31-xmuse-c-class-autonomous-blueprint-execution-mvp-design.md",
                ],
            },
            "lane_packets": [
                {
                    "packet_id": "feature-plan-1:graph-C1:lane-review",
                    "graph_id": "graph-C1",
                    "source_feature_id": "C1",
                    "lane_ids": ["lane-c1-01"],
                    "dependency_edges": [],
                    "review_warnings": [],
                    "blueprint_refs": [
                        "resolution:res-blueprint-1:mission_blueprint",
                    ],
                },
                {
                    "packet_id": "feature-plan-1:graph-C3:lane-review",
                    "graph_id": "graph-C3",
                    "source_feature_id": "C3",
                    "lane_ids": ["lane-c3-01"],
                    "dependency_edges": [],
                    "review_warnings": [],
                    "blueprint_refs": [
                        "resolution:res-blueprint-1:mission_blueprint",
                    ],
                }
            ],
        },
        "architect_self_check": {
            "summary": "Lane count is bounded and dependency shape is acyclic.",
            "dependency_shape": "ok",
            "lane_size": "ok",
            "risk_level": "medium",
            "readiness_warnings": [],
        },
    }


def _conversation_with_participant(
    tmp_path: Path,
    *,
    role: str,
    display_name: str,
) -> tuple[Path, str, str]:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Planning")
    participant = ParticipantStore(db_path).add(
        conversation_id=conversation.id,
        role=role,
        display_name=display_name,
        cli_kind="codex",
        model="gpt-5.5",
    )
    return db_path, conversation.id, participant.participant_id


@pytest.mark.asyncio
async def test_planner_god_adapter_parses_structured_feature_plan_reply(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="planner",
        display_name="Planner GOD",
    )
    payload = _planner_response_payload(conversation_id=conversation_id)
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="planner-req-1",
            artifacts={"stdout": json.dumps(payload)},
        )
    )
    adapter = PlannerGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    response = await adapter.request_plan(_planner_request(conversation_id=conversation_id))

    assert response.conversation_id == conversation_id
    assert response.features[1].feature_id == "C3"
    assert response.features[1].dependency_rationale == (
        "Contracts depend on durable planning identifiers."
    )
    assert layer.sent[0]["message_type"] == "planner"
    assert json.loads(layer.sent[0]["context"])["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_architect_god_adapter_parses_graph_set_reply_and_self_check(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="architect",
        display_name="Architect GOD",
    )
    payload = _architect_response_payload(conversation_id=conversation_id)
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="architect-req-1",
            artifacts={"stdout": json.dumps(payload)},
        )
    )
    adapter = ArchitectGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    response = await adapter.request_graph_set(
        _architect_request(conversation_id=conversation_id)
    )

    lane = response.feature_graphs[1].lanes[0]
    assert response.conversation_id == conversation_id
    assert lane.title == "Planner Architect Contracts"
    assert lane.expected_touched_areas == [
        "src/xmuse_core/agents/*",
        "src/xmuse_core/structuring/*",
    ]
    assert lane.dependency_rationale == "This lane can start once the feature exists."
    assert response.decomposition_review is not None
    assert response.decomposition_review.lane_packets[1].lane_ids == ["lane-c3-01"]
    assert response.architect_self_check.risk_level == "medium"
    assert json.loads(layer.sent[0]["context"])["correlation_id"] == "corr-2"


@pytest.mark.asyncio
async def test_architect_god_adapter_rejects_invalid_structured_reply(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="architect",
        display_name="Architect GOD",
    )
    invalid = _architect_response_payload(conversation_id=conversation_id)
    invalid.pop("architect_self_check")
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="architect-req-1",
            artifacts={"stdout": json.dumps(invalid)},
        )
    )
    adapter = ArchitectGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    with pytest.raises(PlanningGodAdapterError, match="invalid_structured_output"):
        await adapter.request_graph_set(_architect_request(conversation_id=conversation_id))


@pytest.mark.asyncio
async def test_review_god_adapter_rejects_invalid_structured_reply(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="reviewer",
        display_name="Review GOD",
    )
    invalid = {
        "request_id": "review-req-1",
        "correlation_id": "corr-3",
        "conversation_id": conversation_id,
        "phase": "feature_plan_review",
        "artifact_id": "feature-plan-1",
        "artifact_version": 1,
        "verdict": "approve",
        "artifact_refs": ["artifact:feature-plan-1"],
        "blueprint_refs": ["resolution:res-blueprint-1:mission_blueprint"],
    }
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="review-req-1",
            artifacts={"stdout": json.dumps(invalid)},
        )
    )
    adapter = ReviewGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    with pytest.raises(PlanningGodAdapterError, match="invalid_structured_output"):
        await adapter.request_review(
            PlanningReviewRequest(
                request_id="review-req-1",
                correlation_id="corr-3",
                conversation_id=conversation_id,
                phase="feature_plan_review",
                artifact_id="feature-plan-1",
                artifact_version=1,
                artifact_refs=["artifact:feature-plan-1"],
                blueprint_refs=["resolution:res-blueprint-1:mission_blueprint"],
                feature_plan=PlannerGodResponse.model_validate(
                    _planner_response_payload(conversation_id=conversation_id)
                ),
            )
        )


@pytest.mark.asyncio
async def test_review_god_adapter_rejects_request_id_mismatch(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="reviewer",
        display_name="Review GOD",
    )
    payload = {
        "request_id": "wrong-request-id",
        "correlation_id": "corr-3",
        "conversation_id": conversation_id,
        "phase": "feature_plan_review",
        "artifact_id": "feature-plan-1",
        "artifact_version": 1,
        "verdict": "approve",
        "summary": "Ready.",
        "artifact_refs": ["artifact:feature-plan-1"],
        "blueprint_refs": ["resolution:res-blueprint-1:mission_blueprint"],
        "feature_ids": ["C3"],
        "lane_ids": [],
        "dependency_rationale_notes": [],
        "findings": [],
    }
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="review-req-1",
            artifacts={"stdout": json.dumps(payload)},
        )
    )
    adapter = ReviewGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    with pytest.raises(PlanningGodAdapterError, match="request_id_mismatch"):
        await adapter.request_review(
            PlanningReviewRequest(
                request_id="review-req-1",
                correlation_id="corr-3",
                conversation_id=conversation_id,
                phase="feature_plan_review",
                artifact_id="feature-plan-1",
                artifact_version=1,
                artifact_refs=["artifact:feature-plan-1"],
                blueprint_refs=["resolution:res-blueprint-1:mission_blueprint"],
                feature_plan=PlannerGodResponse.model_validate(
                    _planner_response_payload(conversation_id=conversation_id)
                ),
            )
        )


@pytest.mark.asyncio
async def test_planner_god_adapter_rejects_feature_plan_identity_mismatch(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="planner",
        display_name="Planner GOD",
    )
    payload = _planner_response_payload(conversation_id=conversation_id)
    payload["feature_plan_id"] = "wrong-feature-plan"
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="planner-req-1",
            artifacts={"stdout": json.dumps(payload)},
        )
    )
    adapter = PlannerGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    with pytest.raises(PlanningGodAdapterError, match="feature_plan_id_mismatch"):
        await adapter.request_plan(_planner_request(conversation_id=conversation_id))


@pytest.mark.asyncio
async def test_review_god_adapter_rejects_artifact_identity_mismatch(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="reviewer",
        display_name="Review GOD",
    )
    payload = {
        "request_id": "review-req-1",
        "correlation_id": "corr-3",
        "conversation_id": conversation_id,
        "phase": "feature_plan_review",
        "artifact_id": "wrong-feature-plan",
        "artifact_version": 1,
        "verdict": "approve",
        "summary": "Ready.",
        "artifact_refs": ["artifact:feature-plan-1"],
        "blueprint_refs": ["resolution:res-blueprint-1:mission_blueprint"],
        "feature_ids": ["C3"],
        "lane_ids": [],
        "dependency_rationale_notes": [],
        "findings": [],
    }
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="review-req-1",
            artifacts={"stdout": json.dumps(payload)},
        )
    )
    adapter = ReviewGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    with pytest.raises(PlanningGodAdapterError, match="artifact_id_mismatch"):
        await adapter.request_review(
            PlanningReviewRequest(
                request_id="review-req-1",
                correlation_id="corr-3",
                conversation_id=conversation_id,
                phase="feature_plan_review",
                artifact_id="feature-plan-1",
                artifact_version=1,
                artifact_refs=["artifact:feature-plan-1"],
                blueprint_refs=["resolution:res-blueprint-1:mission_blueprint"],
                feature_plan=PlannerGodResponse.model_validate(
                    _planner_response_payload(conversation_id=conversation_id)
                ),
            )
        )


@pytest.mark.asyncio
async def test_architect_god_adapter_rejects_invalid_lane_graph_dependencies(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="architect",
        display_name="Architect GOD",
    )
    invalid = _architect_response_payload(conversation_id=conversation_id)
    invalid["feature_graphs"][1]["lanes"] = [
        {
            "lane_id": "lane-c3-01",
            "local_lane_id": "C3-01",
            "feature_id": "C3",
            "title": "Planner Architect Contracts",
            "prompt": "Add planner/architect contracts and tests.",
            "acceptance_criteria": ["Requests carry correlation metadata."],
            "dependencies": ["lane-c3-02"],
            "capabilities": ["code"],
            "expected_touched_areas": ["src/xmuse_core/agents/*"],
            "artifact_refs": ["artifact:graph-set-proposal-1"],
            "blueprint_refs": ["resolution:res-blueprint-1:mission_blueprint"],
            "feature_refs": ["feature-plan-1:C3"],
            "dependency_rationale": "This lane depends on a missing upstream lane.",
        }
    ]
    invalid["decomposition_review"]["lane_packets"][1]["dependency_edges"] = [
        {
            "source_id": "lane-c3-02",
            "target_id": "lane-c3-01",
            "rationale": "Invalid dependency for test coverage.",
            "evidence_refs": ["artifact:graph-set-proposal-1"],
        }
    ]
    layer = FakeSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="architect-req-1",
            artifacts={"stdout": json.dumps(invalid)},
        )
    )
    adapter = ArchitectGodAdapter(
        db_path=db_path,
        session_layer=layer,
        participant_id=participant_id,
        model="gpt-5.5",
        worktree=tmp_path,
    )

    with pytest.raises(PlanningGodAdapterError, match="invalid_structured_output"):
        await adapter.request_graph_set(_architect_request(conversation_id=conversation_id))


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda payload: payload["feature_graphs"][1]["lanes"].append(
                {
                    **payload["feature_graphs"][1]["lanes"][0],
                    "local_lane_id": "C3-02",
                }
            ),
            "duplicate lane_id",
        ),
        (
            lambda payload: payload["feature_graphs"][1]["lanes"][0].update(
                {"dependencies": ["lane-c3-01"]}
            ),
            "must not depend on itself",
        ),
        (
            lambda payload: payload["feature_graphs"][1].update(
                {
                    "lanes": [
                        {
                            "lane_id": "lane-c3-01",
                            "local_lane_id": "C3-01",
                            "feature_id": "C3",
                            "title": "Planner Architect Contracts",
                            "prompt": "Add planner/architect contracts and tests.",
                            "acceptance_criteria": [
                                "Requests and responses carry request metadata."
                            ],
                            "dependencies": ["lane-c3-02"],
                            "capabilities": ["code"],
                            "expected_touched_areas": ["src/xmuse_core/agents/*"],
                            "artifact_refs": ["artifact:graph-set-proposal-1"],
                            "blueprint_refs": [
                                "resolution:res-blueprint-1:mission_blueprint"
                            ],
                            "feature_refs": ["feature-plan-1:C3"],
                            "dependency_rationale": "Lane 1 waits for lane 2 in the test.",
                        },
                        {
                            "lane_id": "lane-c3-02",
                            "local_lane_id": "C3-02",
                            "feature_id": "C3",
                            "title": "Planner Architect Tests",
                            "prompt": "Add architect validation tests.",
                            "acceptance_criteria": ["Invalid DAGs are rejected."],
                            "dependencies": ["lane-c3-01"],
                            "capabilities": ["test"],
                            "expected_touched_areas": ["tests/*"],
                            "artifact_refs": ["artifact:graph-set-proposal-1"],
                            "blueprint_refs": [
                                "resolution:res-blueprint-1:mission_blueprint"
                            ],
                            "feature_refs": ["feature-plan-1:C3"],
                            "dependency_rationale": "Lane 2 waits for lane 1 in the test.",
                        },
                    ]
                }
            ),
            "dependency cycle detected",
        ),
    ],
)
def test_architect_god_response_rejects_invalid_lane_dag_shapes(
    mutator: Any,
    match: str,
) -> None:
    payload = _architect_response_payload()
    mutator(payload)

    with pytest.raises(ValidationError, match=match):
        ArchitectGodResponse.model_validate(payload)


def test_planning_review_contracts_carry_graph_metadata_and_self_check() -> None:
    graph_set = ArchitectGodResponse.model_validate(_architect_response_payload())

    request = PlanningReviewRequest(
        request_id="review-req-1",
        correlation_id="corr-3",
        conversation_id="conv-1",
        phase="graph_set_review",
        artifact_id="graph-set-1",
        artifact_version=1,
        artifact_refs=["artifact:graph-set-proposal-1"],
        blueprint_refs=graph_set.blueprint_refs,
        graph_set=graph_set,
    )
    response = PlanningReviewResponse(
        request_id="review-req-1",
        correlation_id="corr-3",
        conversation_id="conv-1",
        phase="graph_set_review",
        artifact_id="graph-set-1",
        artifact_version=1,
        verdict="approve",
        summary="Graph-set proposal is ready for review-plane processing.",
        artifact_refs=["artifact:graph-set-proposal-1"],
        blueprint_refs=graph_set.blueprint_refs,
        feature_ids=["C3"],
        lane_ids=["lane-c3-01"],
        dependency_rationale_notes=[
            "The contract lane has no graph-local dependency.",
        ],
        architect_self_check=graph_set.architect_self_check,
    )

    assert request.graph_set is not None
    assert request.graph_set.feature_graphs[1].lanes[0].dependency_rationale == (
        "This lane can start once the feature exists."
    )
    assert response.architect_self_check is not None
    assert response.architect_self_check.lane_size == "ok"


def test_planning_prompts_include_request_and_correlation_ids() -> None:
    planner_prompt = build_planner_god_prompt(_planner_request())
    architect_prompt = build_architect_god_prompt(_architect_request())
    review_prompt = build_planning_review_prompt(
        PlanningReviewRequest(
            request_id="review-req-1",
            correlation_id="corr-3",
            conversation_id="conv-1",
            phase="graph_set_review",
            artifact_id="graph-set-1",
            artifact_version=1,
            artifact_refs=["artifact:graph-set-proposal-1"],
            blueprint_refs=_architect_response_payload()["blueprint_refs"],
            graph_set=ArchitectGodResponse.model_validate(_architect_response_payload()),
        )
    )

    assert "request_id" in planner_prompt
    assert "correlation_id" in planner_prompt
    assert "dependency_rationale" in planner_prompt
    assert "architect_self_check" in architect_prompt
    assert "expected_touched_areas" in architect_prompt
    assert "correlation_id" in review_prompt
    assert "manual_review_required" in review_prompt


def test_planning_review_response_requires_request_and_correlation_ids() -> None:
    with pytest.raises(ValidationError, match="request_id"):
        PlanningReviewResponse(
            request_id="",
            correlation_id="corr-3",
            conversation_id="conv-1",
            phase="feature_plan_review",
            artifact_id="feature-plan-1",
            artifact_version=1,
            verdict="approve",
            summary="ok",
            artifact_refs=["artifact:feature-plan-1"],
            blueprint_refs=["resolution:res-blueprint-1:mission_blueprint"],
        )
