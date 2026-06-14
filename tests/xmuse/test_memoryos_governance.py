from __future__ import annotations

import pytest

from xmuse_core.integrations.memoryos_client import MemoryOSMemoryLayer
from xmuse_core.integrations.memoryos_governance import (
    MemoryOSGovernanceScope,
    plan_memoryos_governed_write,
)
from xmuse_core.integrations.memoryos_namespace import (
    conversation_namespace,
    participant_namespace,
    shared_namespace,
    task_namespace,
)


def _task_namespace():
    return task_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        god_id="god-review",
        conversation_id="conv-1",
        thread_id="thread-1",
        blueprint_id="bp-1",
        feature_id="feature-1",
        lane_id="lane-1",
    )


def test_memory_governance_plans_task_write_without_shared_promotion() -> None:
    namespace = _task_namespace()

    plan = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.TASK,
        event_kind="review_verdict_finalized",
        namespace=namespace,
        actor_id="god-review",
        content="Review approved lane-1.",
        source_refs=["review:verdict-1", "lane:lane-1"],
    )

    assert plan.status == "ok"
    assert plan.decision == "ingest"
    assert plan.proof_level == "contract_proof"
    assert plan.target_namespace_uri == namespace.uri
    assert plan.shared_namespace_uri is None
    assert plan.blocked_reason is None
    assert plan.next_action is None
    request = plan.to_ingest_request()
    assert request.namespace == namespace
    assert request.actor_id == "god-review"
    assert request.content == "Review approved lane-1."
    assert request.memory_layer is MemoryOSMemoryLayer.TASK_STATE
    assert request.promote_to_shared is False
    assert request.source_refs == ["review:verdict-1", "lane:lane-1"]
    assert request.metadata == {
        "xmuse_memory_governance_scope": "task",
        "xmuse_memory_governance_decision": "ingest",
        "xmuse_memory_event_kind": "review_verdict_finalized",
        "xmuse_memory_reviewed": False,
    }


def test_memory_governance_requires_review_and_shared_namespace_for_shared_promotion() -> None:
    namespace = conversation_namespace("conv-1")
    shared = shared_namespace("iiyazu/Cross-Muse")

    missing_namespace = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.SHARED,
        event_kind="decision_rationale",
        namespace=namespace,
        actor_id="god-architect",
        content="Promote this decision rationale.",
        source_refs=["message:m1"],
        promote_to_shared=True,
        reviewed=True,
    )
    assert missing_namespace.status == "blocked"
    assert missing_namespace.decision == "blocked"
    assert missing_namespace.proof_level == "manual_gap"
    assert missing_namespace.to_ingest_request() is None
    assert missing_namespace.blocked_reason == "shared promotion requires shared_namespace"

    unreviewed = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.SHARED,
        event_kind="decision_rationale",
        namespace=namespace,
        actor_id="god-architect",
        content="Promote this decision rationale.",
        source_refs=["message:m1"],
        promote_to_shared=True,
        shared_namespace=shared,
    )
    assert unreviewed.status == "blocked"
    assert unreviewed.decision == "blocked"
    assert unreviewed.proof_level == "manual_gap"
    assert unreviewed.to_ingest_request() is None
    assert unreviewed.blocked_reason == "shared promotion requires explicit review"

    reviewed = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.SHARED,
        event_kind="decision_rationale",
        namespace=namespace,
        actor_id="god-architect",
        content="Promote this reviewed decision rationale.",
        source_refs=["message:m1", "review:rv-1"],
        promote_to_shared=True,
        shared_namespace=shared,
        reviewed=True,
    )
    request = reviewed.to_ingest_request()
    assert request is not None
    assert reviewed.status == "ok"
    assert reviewed.decision == "promote_to_shared"
    assert reviewed.target_namespace_uri == namespace.uri
    assert reviewed.shared_namespace_uri == shared.uri
    assert request.promote_to_shared is True
    assert request.shared_namespace == shared
    assert request.metadata["xmuse_memory_governance_scope"] == "shared"
    assert request.metadata["xmuse_memory_reviewed"] is True


def test_memory_governance_keeps_provider_session_continuity_out_of_memoryos() -> None:
    namespace = participant_namespace("conv-1", "god-review")

    plan = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.PERSONAL,
        event_kind="provider_session_continuity",
        namespace=namespace,
        actor_id="god-review",
        content="Provider session codex-thread-1 is still active.",
        source_refs=["god_session:session-1", "provider_session:codex-thread-1"],
    )

    assert plan.status == "ok"
    assert plan.decision == "provider_session_binding_only"
    assert plan.proof_level == "contract_proof"
    assert plan.to_ingest_request() is None
    assert plan.blocked_reason is None
    assert plan.next_action == (
        "Keep provider continuity in GodSessionRecord/ProviderSessionBindingStore; "
        "do not mirror live session state into MemoryOS."
    )


def test_memory_governance_rejects_blank_actor_or_source_refs() -> None:
    with pytest.raises(ValueError, match="actor_id must be non-empty"):
        plan_memoryos_governed_write(
            scope=MemoryOSGovernanceScope.TASK,
            event_kind="review_verdict_finalized",
            namespace=_task_namespace(),
            actor_id=" ",
            content="Review approved lane-1.",
            source_refs=["review:verdict-1"],
        )

    plan = plan_memoryos_governed_write(
        scope=MemoryOSGovernanceScope.TASK,
        event_kind="review_verdict_finalized",
        namespace=_task_namespace(),
        actor_id="god-review",
        content="Review approved lane-1.",
        source_refs=[],
    )
    assert plan.status == "blocked"
    assert plan.proof_level == "manual_gap"
    assert plan.blocked_reason == "memory writes require source_refs"
