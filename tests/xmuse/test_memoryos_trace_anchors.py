from __future__ import annotations

import pytest

from xmuse_core.integrations.memoryos_governance import (
    MemoryOSGovernanceScope,
    plan_memoryos_governed_write,
)
from xmuse_core.integrations.memoryos_namespace import (
    MemoryOSTraceAnchorKind,
    blueprint_namespace,
    god_private_namespace,
    memory_trace_anchor,
    operator_namespace,
    review_namespace,
)


def test_memoryos_trace_namespaces_cover_god_blueprint_review_and_operator() -> None:
    god_private = god_private_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        conversation_id="conv-1",
        god_id="god-review",
    )
    blueprint = blueprint_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        conversation_id="conv-1",
        blueprint_id="bp-1",
    )
    review = review_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        conversation_id="conv-1",
        feature_id="feature-1",
        lane_id="lane-1",
        review_id="rv-1",
    )
    operator = operator_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        operator_id="operator-1",
    )

    assert god_private.uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse"
        "/conversation/conv-1/god/god-review/private"
    )
    assert blueprint.uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse"
        "/conversation/conv-1/blueprint/bp-1"
    )
    assert review.uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse"
        "/conversation/conv-1/feature/feature-1/lane/lane-1/review/rv-1"
    )
    assert operator.uri == (
        "memory://repo/iiyazu/Cross-Muse/workspace/xmuse/operator/operator-1"
    )


def test_memoryos_trace_anchor_links_namespace_trace_and_source_refs() -> None:
    namespace = blueprint_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        conversation_id="conv-1",
        blueprint_id="bp-1",
    )

    anchor = memory_trace_anchor(
        kind=MemoryOSTraceAnchorKind.BLUEPRINT,
        namespace=namespace,
        trace_id="trace-bp-1",
        source_refs=["god-room-event:freeze-1", "blueprint:bp-1:1"],
    )

    assert anchor.uri == f"{namespace.uri}/traces/trace-bp-1"
    assert anchor.proof_level == "contract_proof"
    assert anchor.source_refs == ["god-room-event:freeze-1", "blueprint:bp-1:1"]
    with pytest.raises(ValueError, match="source_refs must contain at least one item"):
        memory_trace_anchor(
            kind=MemoryOSTraceAnchorKind.BLUEPRINT,
            namespace=namespace,
            trace_id="trace-bp-1",
            source_refs=[],
        )


def test_memoryos_governed_write_accepts_review_trace_anchor_source_refs() -> None:
    namespace = review_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        conversation_id="conv-1",
        feature_id="feature-1",
        lane_id="lane-1",
        review_id="rv-1",
    )
    anchor = memory_trace_anchor(
        kind=MemoryOSTraceAnchorKind.REVIEW,
        namespace=namespace,
        trace_id="trace-rv-1",
        source_refs=["review:rv-1", "lane:lane-1"],
    )

    plan = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.TASK,
        event_kind="review_verdict_finalized",
        namespace=namespace,
        actor_id="god-review",
        content="Review approved lane-1.",
        source_refs=[anchor.uri, "review:rv-1"],
    )

    request = plan.to_ingest_request()

    assert plan.status == "ok"
    assert request is not None
    assert request.namespace == namespace
    assert request.source_refs == [anchor.uri, "review:rv-1"]
