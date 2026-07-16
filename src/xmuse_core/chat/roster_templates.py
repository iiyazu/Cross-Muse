from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xmuse_core.chat.participant_store import PersonaSnapshot
from xmuse_core.chat.room_api_models import ParticipantInit
from xmuse_core.providers.models import ProviderId, ProviderProfileId
from xmuse_core.providers.registry import (
    ProviderRegistry,
    build_default_provider_registry,
    normalize_codex_model_id,
)

ProviderRuntimeKind = Literal["codex"]


class RoleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role_id: str = Field(min_length=1)
    participant_role: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    collaboration_focus: str = Field(min_length=1)
    default_provider_profile_ref: str = Field(min_length=1)

    @field_validator(
        "role_id",
        "participant_role",
        "display_name",
        "description",
        "collaboration_focus",
        "default_provider_profile_ref",
        mode="before",
    )
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be blank")
            return stripped
        return value


class WorkroomProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_profile_ref: str = Field(min_length=1)
    provider_id: ProviderRuntimeKind
    profile_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    implemented: bool
    cli_kind: ProviderRuntimeKind

    @field_validator(
        "provider_profile_ref",
        "profile_id",
        "display_name",
        "description",
        "model_id",
        mode="before",
    )
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be blank")
            return stripped
        return value


class RosterRoleBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role_id: str = Field(min_length=1)
    provider_profile_ref: str = Field(min_length=1)
    display_name: str | None = None
    model: str | None = None

    @field_validator("role_id", "provider_profile_ref", "display_name", "model", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class RosterTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    roles: tuple[RosterRoleBinding, ...]

    @field_validator("template_id", "display_name", "description", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be blank")
            return stripped
        return value


class WorkroomCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role_profiles: dict[str, RoleProfile]
    provider_profiles: dict[str, WorkroomProviderProfile]
    roster_templates: dict[str, RosterTemplate]


class WorkroomRosterTemplateStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def list_custom(self) -> list[RosterTemplate]:
        if not self._path.exists():
            return []
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        templates = payload.get("roster_templates", [])
        if not isinstance(templates, list):
            return []
        return [
            RosterTemplate.model_validate(template)
            for template in templates
            if isinstance(template, dict)
        ]

    def list_all(
        self,
        *,
        catalog: WorkroomCatalog | None = None,
    ) -> list[RosterTemplate]:
        catalog = catalog or builtin_workroom_catalog()
        templates = list(catalog.roster_templates.values())
        by_id = {template.template_id: template for template in templates}
        for template in self.list_custom():
            by_id[template.template_id] = validate_roster_template(
                template,
                catalog=catalog,
            )
        return list(by_id.values())

    def list_valid(
        self,
        *,
        catalog: WorkroomCatalog | None = None,
    ) -> list[RosterTemplate]:
        """Return builtin plus individually valid custom templates for safe discovery UIs."""

        catalog = catalog or builtin_workroom_catalog()
        by_id = dict(catalog.roster_templates)
        if not self._path.exists():
            return list(by_id.values())
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return list(by_id.values())
        templates = payload.get("roster_templates", []) if isinstance(payload, dict) else []
        if not isinstance(templates, list):
            return list(by_id.values())
        for value in templates:
            if not isinstance(value, dict):
                continue
            try:
                template = validate_roster_template(
                    RosterTemplate.model_validate(value),
                    catalog=catalog,
                )
            except (ValueError, TypeError):
                continue
            by_id[template.template_id] = template
        return list(by_id.values())

    def get(
        self,
        template_id: str,
        *,
        catalog: WorkroomCatalog | None = None,
    ) -> RosterTemplate:
        catalog = catalog or builtin_workroom_catalog()
        if template_id in catalog.roster_templates:
            return validate_roster_template(
                catalog.roster_templates[template_id],
                catalog=catalog,
            )
        for template in self.list_custom():
            if template.template_id == template_id:
                return validate_roster_template(template, catalog=catalog)
        raise KeyError(template_id)

    def save(
        self,
        template: RosterTemplate,
        *,
        catalog: WorkroomCatalog | None = None,
    ) -> RosterTemplate:
        catalog = catalog or builtin_workroom_catalog()
        validated = validate_roster_template(template, catalog=catalog)
        custom = [
            existing
            for existing in self.list_custom()
            if existing.template_id != validated.template_id
        ]
        custom.append(validated)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "schema_version": "workroom_roster_templates/v1",
                    "roster_templates": [item.model_dump(mode="json") for item in custom],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return validated


def builtin_workroom_catalog(
    *,
    registry: ProviderRegistry | None = None,
) -> WorkroomCatalog:
    registry = registry or build_default_provider_registry()
    return WorkroomCatalog(
        role_profiles=_builtin_role_profiles(),
        provider_profiles=_builtin_provider_profiles(registry),
        roster_templates=_builtin_roster_templates(),
    )


def _builtin_role_profiles() -> dict[str, RoleProfile]:
    return {
        "architect": RoleProfile(
            role_id="architect",
            participant_role="architect",
            display_name="Architect",
            description="Frames the problem, identifies constraints, and plans coherent work.",
            collaboration_focus=(
                "Connect peer evidence into a decision-complete direction; avoid taking over "
                "implementation or repeating another participant's answer."
            ),
            default_provider_profile_ref="codex.god",
        ),
        "builder": RoleProfile(
            role_id="builder",
            participant_role="execute",
            display_name="Builder",
            description="Turns agreed direction into concrete, bounded implementation work.",
            collaboration_focus=(
                "Contribute implementation-specific evidence, feasibility, and exact changes; "
                "when a durable handoff targets you, perform the bounded read-only work now "
                "and report evidence or an exact-patch candidate; surface blockers instead "
                "of restating the plan or promising future work."
            ),
            default_provider_profile_ref="codex.worker",
        ),
        "reviewer": RoleProfile(
            role_id="reviewer",
            participant_role="review",
            display_name="Reviewer",
            description="Reviews claims and results against durable evidence and invariants.",
            collaboration_focus=(
                "Independently verify correctness, regressions, and proof gaps; respond only "
                "when review adds information the Room does not already have."
            ),
            default_provider_profile_ref="codex.review",
        ),
        "critic": RoleProfile(
            role_id="critic",
            participant_role="critic",
            display_name="Critic",
            description="Challenges assumptions, proposals, and hidden failure modes.",
            collaboration_focus=(
                "Stress-test consensus with distinct counterevidence and bounded alternatives; "
                "do not manufacture objections after concerns are already resolved."
            ),
            default_provider_profile_ref="codex.default",
        ),
    }


def _builtin_provider_profiles(
    registry: ProviderRegistry,
) -> dict[str, WorkroomProviderProfile]:
    codex_default = registry.get("codex.default")
    codex_worker = registry.get("codex.worker")
    codex_review = registry.get("codex.review")
    codex_god = registry.get("codex.god")
    return {
        "codex.default": _codex_provider_summary(
            "codex.default",
            profile_id=codex_default.profile_id,
            display_name="Codex Default",
            description="General Codex CLI role profile.",
            model_id=codex_default.model_id,
        ),
        "codex.worker": _codex_provider_summary(
            "codex.worker",
            profile_id=codex_worker.profile_id,
            display_name="Codex Worker",
            description="Codex CLI worker profile for bounded implementation.",
            model_id=codex_worker.model_id,
        ),
        "codex.review": _codex_provider_summary(
            "codex.review",
            profile_id=codex_review.profile_id,
            display_name="Codex Reviewer",
            description="Codex CLI review profile.",
            model_id=codex_review.model_id,
        ),
        "codex.god": _codex_provider_summary(
            "codex.god",
            profile_id=codex_god.profile_id,
            display_name="Codex Planner",
            description="Codex CLI planning profile.",
            model_id=codex_god.model_id,
        ),
    }


def _builtin_roster_templates() -> dict[str, RosterTemplate]:
    return {
        "builtin.development": RosterTemplate(
            template_id="builtin.development",
            display_name="Development Workroom",
            description="Default software-development role group.",
            roles=(
                RosterRoleBinding(
                    role_id="architect",
                    provider_profile_ref="codex.god",
                ),
                RosterRoleBinding(
                    role_id="builder",
                    provider_profile_ref="codex.worker",
                ),
                RosterRoleBinding(
                    role_id="reviewer",
                    provider_profile_ref="codex.review",
                ),
                RosterRoleBinding(
                    role_id="critic",
                    provider_profile_ref="codex.default",
                ),
            ),
        )
    }


def validate_roster_template(
    template: RosterTemplate,
    *,
    catalog: WorkroomCatalog | None = None,
) -> RosterTemplate:
    catalog = catalog or builtin_workroom_catalog()
    errors: list[str] = []
    seen_roles: set[str] = set()
    normalized_roles: list[RosterRoleBinding] = []
    for binding in template.roles:
        role = catalog.role_profiles.get(binding.role_id)
        provider = catalog.provider_profiles.get(binding.provider_profile_ref)
        if binding.role_id in seen_roles:
            errors.append(f"duplicate role in roster: {binding.role_id}")
        seen_roles.add(binding.role_id)
        if role is None:
            errors.append(f"unknown role profile: {binding.role_id}")
        if provider is None:
            errors.append(f"unknown provider profile: {binding.provider_profile_ref}")
        if role is None or provider is None:
            normalized_roles.append(binding)
            continue
        normalized_roles.append(
            binding.model_copy(
                update={
                    "display_name": binding.display_name or role.display_name,
                    "model": binding.model or provider.model_id,
                }
            )
        )
    if not normalized_roles:
        errors.append("roster template must include at least one role")
    if errors:
        raise ValueError("; ".join(errors))
    return template.model_copy(update={"roles": tuple(normalized_roles)})


def template_to_participant_inits(
    template: RosterTemplate,
    *,
    catalog: WorkroomCatalog | None = None,
) -> list[ParticipantInit]:
    catalog = catalog or builtin_workroom_catalog()
    validated = validate_roster_template(template, catalog=catalog)
    participants: list[ParticipantInit] = []
    for binding in validated.roles:
        role = catalog.role_profiles[binding.role_id]
        provider = catalog.provider_profiles[binding.provider_profile_ref]
        if not provider.implemented:
            raise ValueError(
                f"provider profile is not implemented for runtime start: "
                f"{provider.provider_profile_ref}"
            )
        if provider.provider_id != "codex":
            raise ValueError(
                f"provider profile is not supported in this slice: {provider.provider_profile_ref}"
            )
        profile_id = ProviderProfileId(provider.profile_id)
        participants.append(
            ParticipantInit(
                role=role.participant_role,
                provider_id=ProviderId.CODEX,
                profile_id=profile_id,
                cli_kind="codex",
                model=normalize_codex_model_id(
                    binding.model,
                    profile_id=profile_id,
                    allow_final_quality=False,
                ),
                display_name=binding.display_name or role.display_name,
            )
        )
    return participants


def persona_snapshot_for_role_profile(role: RoleProfile) -> PersonaSnapshot:
    """Freeze only the catalog's declarative collaboration fields."""

    return PersonaSnapshot(
        role_description=role.description,
        collaboration_focus=role.collaboration_focus,
    )


def _codex_provider_summary(
    provider_profile_ref: str,
    *,
    profile_id: ProviderProfileId,
    display_name: str,
    description: str,
    model_id: str,
) -> WorkroomProviderProfile:
    return WorkroomProviderProfile(
        provider_profile_ref=provider_profile_ref,
        provider_id="codex",
        profile_id=profile_id.value,
        display_name=display_name,
        description=description,
        model_id=model_id,
        implemented=True,
        cli_kind="codex",
    )
