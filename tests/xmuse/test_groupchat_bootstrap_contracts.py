from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.chat.bootstrap_contracts import (
    BootstrapInitMode,
    LogicalPeerSpec,
    TeamPlanProposal,
    bootstrap_apply_id,
    bootstrap_fork_idempotency_key,
    resolve_groupchat_preset,
    validate_logical_proposal_payload,
)


def test_default_preset_resolves_logical_team() -> None:
    preset = resolve_groupchat_preset("architect-review-execute")
    assert preset.preset_id == "architect-review-execute"
    assert [role.role for role in preset.roles] == ["architect", "review", "execute"]
    assert [role.address_slug for role in preset.roles] == ["architect", "review", "execute"]
    assert {role.provider_id for role in preset.roles} == {"codex"}


def test_logical_peer_allows_same_role_but_requires_unique_address_in_proposal() -> None:
    proposal = TeamPlanProposal(
        proposal_id="proposal-1",
        draft_id="draft-1",
        conversation_id="conv-1",
        source="deterministic",
        peers=[
            LogicalPeerSpec(
                role="review", address_slug="review-main", display_name="review-main",
                template_slug="review", provider_id="codex", profile_id="review",
                cli_kind="codex", model="gpt-5.5",
            ),
            LogicalPeerSpec(
                role="review", address_slug="review-security", display_name="review-security",
                template_slug="review", provider_id="codex", profile_id="review",
                cli_kind="codex", model="gpt-5.5",
            ),
        ],
        fork_plan=[],
        rationale="two independent reviewers",
        validation_status="pending",
    )
    assert [peer.address_slug for peer in proposal.peers] == ["review-main", "review-security"]


def test_duplicate_address_slug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="address_slug"):
        TeamPlanProposal(
            proposal_id="proposal-1", draft_id="draft-1", conversation_id="conv-1",
            source="deterministic",
            peers=[
                LogicalPeerSpec(
                    role="review", address_slug="review", display_name="review-a",
                    template_slug="review", provider_id="codex", profile_id="review",
                    cli_kind="codex", model="gpt-5.5",
                ),
                LogicalPeerSpec(
                    role="execute", address_slug="review", display_name="execute-a",
                    template_slug="execute", provider_id="codex", profile_id="worker",
                    cli_kind="codex", model="gpt-5.5",
                ),
            ],
            fork_plan=[], rationale="bad duplicate", validation_status="pending",
        )


def test_proposal_rejects_authority_ids() -> None:
    payload = {
        "proposal_id": "proposal-1", "draft_id": "draft-1", "conversation_id": "conv-1",
        "source": "init_god",
        "peers": [{
            "role": "architect", "address_slug": "architect", "display_name": "architect-god",
            "template_slug": "architect", "provider_id": "codex", "profile_id": "god",
            "cli_kind": "codex", "model": "gpt-5.5", "participant_id": "part-forged",
        }],
        "fork_plan": [], "rationale": "forged ids", "validation_status": "pending",
    }
    with pytest.raises(ValueError, match="authority ids"):
        validate_logical_proposal_payload(payload)


def test_opencode_requires_explicit_model() -> None:
    with pytest.raises(ValidationError, match="explicit model"):
        LogicalPeerSpec(
            role="execute", address_slug="execute", display_name="execute-god",
            template_slug="execute", provider_id="opencode", profile_id="worker",
            cli_kind="opencode", model="",
        )


def test_logical_peer_accepts_grok_with_explicit_model() -> None:
    peer = LogicalPeerSpec(
        role="review",
        address_slug="review",
        display_name="review-grok-god",
        template_slug="review",
        provider_id="grok",
        profile_id="review",
        cli_kind="grok",
        model="grok-composer-2.5-fast",
    )

    assert peer.provider_id == "grok"
    assert peer.cli_kind == "grok"
    assert peer.model == "grok-composer-2.5-fast"


def test_deterministic_ids_are_stable() -> None:
    assert BootstrapInitMode.PROPOSAL_THEN_APPROVE.value == "proposal_then_approve"
    assert bootstrap_apply_id("conv-1", "proposal-1") == "bootstrap-apply:conv-1:proposal-1"
    key = bootstrap_fork_idempotency_key("conv-1", "proposal-1", "part-init", "review")
    assert key == "bootstrap-fork:conv-1:proposal-1:part-init:review"
