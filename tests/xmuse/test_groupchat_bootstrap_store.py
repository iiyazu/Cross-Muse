from __future__ import annotations

from xmuse_core.chat.bootstrap_contracts import (
    AppliedBootstrap,
    BootstrapDraft,
    BootstrapStatus,
    LogicalForkSpec,
    LogicalPeerSpec,
    TeamPlanProposal,
)
from xmuse_core.chat.bootstrap_store import BootstrapStateStore


def _peer(role: str) -> LogicalPeerSpec:
    return LogicalPeerSpec(
        role=role, address_slug=role, display_name=f"{role}-god",
        template_slug=role, provider_id="codex",
        profile_id="god" if role == "architect" else "review",
        cli_kind="codex", model="gpt-5.5",
    )


def test_draft_proposal_application_round_trip(tmp_path) -> None:
    store = BootstrapStateStore(tmp_path / "chat.db")
    draft = BootstrapDraft(
        draft_id="draft-1", conversation_id="conv-1", preset_id="architect-review",
        init_participant_id="part-init", init_session_id="god-init",
        requested_overrides={}, default_team=[_peer("architect"), _peer("review")],
        status=BootstrapStatus.DRAFTING,
        created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )
    proposal = TeamPlanProposal(
        proposal_id="proposal-1", draft_id=draft.draft_id,
        conversation_id=draft.conversation_id, source="deterministic",
        peers=draft.default_team,
        fork_plan=[LogicalForkSpec(
            target_address_slug="architect", prompt_delta="architect role",
            inherited_refs=[], fork_reason="bootstrap architect",
        )],
        rationale="default team", validation_status="accepted",
    )
    applied = AppliedBootstrap(
        apply_id="apply-1", draft_id=draft.draft_id,
        proposal_id=proposal.proposal_id, conversation_id=draft.conversation_id,
        participants=["part-architect", "part-review"],
        durable_god_sessions=["god-architect", "god-review"],
        fork_records=["fork-1"], status="bootstrapped",
        created_at="2026-06-04T00:00:01Z",
    )
    store.upsert_draft(draft)
    store.upsert_proposal(proposal)
    store.upsert_application(applied)
    assert store.get_draft(draft.draft_id) == draft
    assert store.get_latest_draft_for_conversation("conv-1") == draft
    assert store.get_proposal(proposal.proposal_id) == proposal
    assert store.get_application(applied.apply_id) == applied


def test_upsert_is_duplicate_safe(tmp_path) -> None:
    store = BootstrapStateStore(tmp_path / "chat.db")
    draft = BootstrapDraft(
        draft_id="draft-1", conversation_id="conv-1", preset_id="solo-architect",
        init_participant_id="part-init", init_session_id="god-init",
        requested_overrides={}, default_team=[_peer("architect")],
        status=BootstrapStatus.DRAFTING,
        created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )
    store.upsert_draft(draft)
    store.upsert_draft(draft)
    assert len(store.list_drafts_for_conversation("conv-1")) == 1
