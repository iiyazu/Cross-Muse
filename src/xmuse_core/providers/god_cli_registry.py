from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal

from xmuse_core.providers.models import TaskCapability
from xmuse_core.providers.policy import BOUNDED_DELIBERATION_SPEECH_ACTS
from xmuse_core.providers.registry import build_default_provider_registry

ProofLevel = Literal[
    "contract_proof",
    "fake_runtime_proof",
    "live_service_proof",
    "server_side_enforcement_proof",
    "server_side_merge_proof",
    "real_provider_proof",
    "internal_review_proof",
    "manual_gap",
]
RegistrationKind = Literal["built_in", "manual"]

PEER_GOD_SPEECH_ACTS = (
    "propose",
    "ask",
    "challenge",
    "object",
    "vote",
    "decide",
    "handoff",
    "evidence",
    "retract",
)


class GodCliCapability(StrEnum):
    PEER_GOD = "peer_god"
    BOUNDED_DELIBERATION = "bounded_deliberation"
    BOUNDED_CODE_WRITING = "bounded_code_writing"
    REVIEW = "review"
    LANE_COORDINATION = "lane_coordination"
    PLANNING = "planning"
    TAKEOVER = "takeover"
    MERGE_FINAL_REVIEW = "merge_final_review"


@dataclass(frozen=True)
class GodCliRegistration:
    cli_id: str
    display_name: str
    command_family: str
    provider_profile_ref: str
    capabilities: tuple[GodCliCapability, ...]
    allowed_speech_acts: tuple[str, ...]
    supports_persistent_sessions: bool
    supports_mcp_writeback: bool
    state_write_allowed: bool
    proof_level: ProofLevel
    registration_kind: RegistrationKind = "manual"
    source_authority: str = "god_cli_registry"

    def __post_init__(self) -> None:
        _require_text(self.cli_id, "cli_id")
        _require_text(self.display_name, "display_name")
        _require_text(self.command_family, "command_family")
        _require_text(self.provider_profile_ref, "provider_profile_ref")
        if not self.capabilities:
            raise ValueError("capabilities must contain at least one item")
        if not self.allowed_speech_acts:
            raise ValueError("allowed_speech_acts must contain at least one item")
        _require_unique([capability.value for capability in self.capabilities], "capabilities")
        _require_unique(list(self.allowed_speech_acts), "allowed_speech_acts")
        if GodCliCapability.PEER_GOD in self.capabilities:
            if self.registration_kind == "manual" and self.proof_level != "real_provider_proof":
                raise ValueError("manual peer_god requires real_provider_proof")
            if not self.supports_persistent_sessions:
                raise ValueError("peer_god requires persistent sessions")
            if not self.supports_mcp_writeback:
                raise ValueError("peer_god requires MCP writeback")
            if not self.state_write_allowed:
                raise ValueError("peer_god requires state_write_allowed")

    def model_dump(self) -> dict[str, object]:
        data = asdict(self)
        data["capabilities"] = [capability.value for capability in self.capabilities]
        return data


@dataclass(frozen=True)
class GodCliSelection:
    cli_id: str
    allowed: bool
    required_capability: GodCliCapability
    reason: str
    registration: GodCliRegistration | None = None

    def model_dump(self) -> dict[str, object]:
        return {
            "cli_id": self.cli_id,
            "allowed": self.allowed,
            "required_capability": self.required_capability.value,
            "reason": self.reason,
            "registration": self.registration.model_dump()
            if self.registration is not None
            else None,
        }


class GodCliRegistry:
    def __init__(self, registrations: list[GodCliRegistration]) -> None:
        by_id: dict[str, GodCliRegistration] = {}
        for registration in registrations:
            if registration.cli_id in by_id:
                raise ValueError(f"duplicate GOD CLI registration: {registration.cli_id}")
            by_id[registration.cli_id] = registration
        self._registrations = tuple(registrations)
        self._by_id = by_id

    def list_registrations(self) -> list[GodCliRegistration]:
        return list(self._registrations)

    def get(self, cli_id: str) -> GodCliRegistration:
        clean_cli_id = cli_id.strip()
        if not clean_cli_id:
            raise KeyError("GOD CLI id must be non-empty")
        try:
            return self._by_id[clean_cli_id]
        except KeyError as exc:
            raise KeyError(f"unknown GOD CLI: {clean_cli_id}") from exc

    def select_for_god(self, cli_id: str) -> GodCliSelection:
        clean_cli_id = cli_id.strip()
        try:
            registration = self.get(clean_cli_id)
        except KeyError:
            return GodCliSelection(
                cli_id=clean_cli_id,
                allowed=False,
                required_capability=GodCliCapability.PEER_GOD,
                reason=f"unknown GOD CLI: {clean_cli_id}",
            )
        if GodCliCapability.PEER_GOD not in registration.capabilities:
            return GodCliSelection(
                cli_id=clean_cli_id,
                allowed=False,
                required_capability=GodCliCapability.PEER_GOD,
                reason=f"{clean_cli_id} does not advertise peer_god capability",
                registration=registration,
            )
        return GodCliSelection(
            cli_id=clean_cli_id,
            allowed=True,
            required_capability=GodCliCapability.PEER_GOD,
            reason=f"{clean_cli_id} is selectable as a GOD CLI",
            registration=registration,
        )


def build_default_god_cli_registry() -> GodCliRegistry:
    provider_registry = build_default_provider_registry()
    registrations: list[GodCliRegistration] = []
    for profile in provider_registry.list_profiles():
        capabilities = _god_cli_capabilities(profile.task_capabilities)
        if not capabilities:
            continue
        is_codex_god = profile.ref == "codex.god"
        is_bounded_opencode = profile.ref == "opencode.deepseek_flash_worker"
        if not is_codex_god and not is_bounded_opencode:
            continue
        registrations.append(
            GodCliRegistration(
                cli_id=profile.ref,
                display_name=_display_name(profile.ref),
                command_family=profile.provider_id.value,
                provider_profile_ref=profile.ref,
                capabilities=capabilities,
                allowed_speech_acts=PEER_GOD_SPEECH_ACTS
                if is_codex_god
                else BOUNDED_DELIBERATION_SPEECH_ACTS,
                supports_persistent_sessions=profile.supports_persistent_sessions,
                supports_mcp_writeback=profile.supports_mcp,
                state_write_allowed=is_codex_god,
                proof_level="contract_proof",
                registration_kind="built_in",
                source_authority="default_provider_registry",
            )
        )
    return GodCliRegistry(registrations)


def build_god_cli_inventory() -> dict[str, object]:
    registry = build_default_god_cli_registry()
    registrations = registry.list_registrations()
    return {
        "kind": "god_cli_inventory",
        "read_only": True,
        "source_authority": "god_cli_registry",
        "counts": {"registrations": len(registrations)},
        "registrations": [registration.model_dump() for registration in registrations],
    }


def _god_cli_capabilities(
    task_capabilities: tuple[TaskCapability, ...],
) -> tuple[GodCliCapability, ...]:
    mapped: list[GodCliCapability] = []
    for capability in task_capabilities:
        if capability is TaskCapability.BOUNDED_DELIBERATION:
            mapped.append(GodCliCapability.BOUNDED_DELIBERATION)
        elif capability is TaskCapability.BOUNDED_CODE_WRITING:
            mapped.append(GodCliCapability.BOUNDED_CODE_WRITING)
        elif capability is TaskCapability.REVIEW:
            mapped.append(GodCliCapability.REVIEW)
        elif capability is TaskCapability.LANE_COORDINATION:
            mapped.append(GodCliCapability.LANE_COORDINATION)
        elif capability is TaskCapability.PLANNING:
            mapped.append(GodCliCapability.PLANNING)
        elif capability is TaskCapability.TAKEOVER:
            mapped.append(GodCliCapability.TAKEOVER)
        elif capability is TaskCapability.MERGE_FINAL_REVIEW:
            mapped.append(GodCliCapability.MERGE_FINAL_REVIEW)
    if {
        GodCliCapability.BOUNDED_DELIBERATION,
        GodCliCapability.LANE_COORDINATION,
        GodCliCapability.PLANNING,
        GodCliCapability.TAKEOVER,
    }.issubset(set(mapped)):
        mapped.insert(0, GodCliCapability.PEER_GOD)
    return tuple(dict.fromkeys(mapped))


def _display_name(profile_ref: str) -> str:
    provider, _, profile = profile_ref.partition(".")
    return f"{provider.title()} {profile.replace('_', ' ').title()}"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_unique(values: list[str], field_name: str) -> None:
    cleaned = [value.strip() for value in values if value.strip()]
    duplicates = sorted({value for value in cleaned if cleaned.count(value) > 1})
    if duplicates:
        raise ValueError(
            f"{field_name} must not contain duplicates: {', '.join(duplicates)}"
        )
