from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.chat.room_api_models import ParticipantInit
from xmuse_core.chat.roster_templates import (
    RosterRoleBinding,
    RosterTemplate,
    builtin_workroom_catalog,
    template_to_participant_inits,
    validate_roster_template,
)


def test_builtin_development_roster_exposes_product_roles_and_codex_profiles() -> None:
    catalog = builtin_workroom_catalog()

    template = catalog.roster_templates["builtin.development"]

    assert template.display_name == "Development Workroom"
    assert [role.role_id for role in template.roles] == [
        "architect",
        "builder",
        "reviewer",
        "critic",
    ]
    assert {
        role.role_id: role.default_provider_profile_ref for role in catalog.role_profiles.values()
    } == {
        "architect": "codex.god",
        "builder": "codex.worker",
        "reviewer": "codex.review",
        "critic": "codex.default",
    }
    assert catalog.role_profiles["builder"].participant_role == "execute"
    assert catalog.provider_profiles["codex.worker"].provider_id == "codex"
    assert {
        key for key, profile in catalog.provider_profiles.items() if profile.implemented
    } == set(catalog.provider_profiles)
    assert set(catalog.provider_profiles) == {
        "codex.default",
        "codex.worker",
        "codex.review",
        "codex.god",
    }
    assert "claude-code.default" not in catalog.provider_profiles
    assert "opencode.default" not in catalog.provider_profiles


def test_validate_roster_template_accepts_user_copy_with_known_roles_and_profiles() -> None:
    catalog = builtin_workroom_catalog()
    copied = RosterTemplate(
        template_id="user.project.default",
        display_name="My Workroom",
        description="Project-specific development roster.",
        roles=(
            RosterRoleBinding(role_id="architect", provider_profile_ref="codex.god"),
            RosterRoleBinding(
                role_id="builder",
                provider_profile_ref="codex.worker",
                display_name="Ship Builder",
            ),
            RosterRoleBinding(role_id="reviewer", provider_profile_ref="codex.review"),
        ),
    )

    validated = validate_roster_template(copied, catalog=catalog)

    assert validated.template_id == "user.project.default"
    assert [role.display_name for role in validated.roles] == [
        "Architect",
        "Ship Builder",
        "Reviewer",
    ]


def test_validate_roster_template_rejects_unknown_role_and_provider_profile() -> None:
    catalog = builtin_workroom_catalog()
    template = RosterTemplate(
        template_id="user.bad",
        display_name="Bad Workroom",
        description="Invalid roster.",
        roles=(
            RosterRoleBinding(role_id="architect", provider_profile_ref="codex.god"),
            RosterRoleBinding(role_id="unknown", provider_profile_ref="codex.worker"),
            RosterRoleBinding(role_id="reviewer", provider_profile_ref="codex.missing"),
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        validate_roster_template(template, catalog=catalog)

    message = str(excinfo.value)
    assert "unknown role profile: unknown" in message
    assert "unknown provider profile: codex.missing" in message


def test_validate_roster_template_rejects_future_provider_slots() -> None:
    catalog = builtin_workroom_catalog()
    template = RosterTemplate(
        template_id="user.future-provider",
        display_name="Future Provider Workroom",
        description="Invalid roster until provider is promoted to current catalog.",
        roles=(
            RosterRoleBinding(
                role_id="architect",
                provider_profile_ref="opencode.default",
            ),
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        validate_roster_template(template, catalog=catalog)

    assert "unknown provider profile: opencode.default" in str(excinfo.value)


def test_validate_roster_template_rejects_duplicate_product_roles() -> None:
    catalog = builtin_workroom_catalog()
    template = RosterTemplate(
        template_id="user.duplicate",
        display_name="Duplicate Workroom",
        description="Invalid roster.",
        roles=(
            RosterRoleBinding(role_id="architect", provider_profile_ref="codex.god"),
            RosterRoleBinding(role_id="architect", provider_profile_ref="codex.default"),
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        validate_roster_template(template, catalog=catalog)

    assert "duplicate role in roster: architect" in str(excinfo.value)


def test_roster_binding_rejects_browser_supplied_command_text() -> None:
    with pytest.raises(ValidationError) as excinfo:
        RosterRoleBinding.model_validate(
            {
                "role_id": "builder",
                "provider_profile_ref": "codex.worker",
                "command": "codex --dangerously-run-anything",
            }
        )

    assert "Extra inputs are not permitted" in str(excinfo.value)


def test_template_to_participant_inits_uses_backend_registry_not_browser_commands() -> None:
    catalog = builtin_workroom_catalog()
    template = validate_roster_template(
        RosterTemplate(
            template_id="user.project.default",
            display_name="My Workroom",
            description="Project-specific development roster.",
            roles=(
                RosterRoleBinding(role_id="architect", provider_profile_ref="codex.god"),
                RosterRoleBinding(role_id="builder", provider_profile_ref="codex.worker"),
                RosterRoleBinding(role_id="reviewer", provider_profile_ref="codex.review"),
            ),
        ),
        catalog=catalog,
    )

    participants = template_to_participant_inits(template, catalog=catalog)

    assert all(isinstance(participant, ParticipantInit) for participant in participants)
    assert [
        participant.model_dump(mode="json", exclude_none=True) for participant in participants
    ] == [
        {
            "role": "architect",
            "provider_id": "codex",
            "profile_id": "god",
            "cli_kind": "codex",
            "model": "gpt-5.6-sol",
            "display_name": "Architect",
        },
        {
            "role": "execute",
            "provider_id": "codex",
            "profile_id": "worker",
            "cli_kind": "codex",
            "model": "gpt-5.6-luna",
            "display_name": "Builder",
        },
        {
            "role": "review",
            "provider_id": "codex",
            "profile_id": "review",
            "cli_kind": "codex",
            "model": "gpt-5.6-sol",
            "display_name": "Reviewer",
        },
    ]
