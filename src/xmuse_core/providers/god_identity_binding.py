from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

ProofLevel = Literal["contract_proof", "real_provider_proof", "manual_gap"]
ResolutionStatus = Literal["resolved", "manual_gap"]

SCHEMA_VERSION = "xmuse.god_identity_binding_store.v1"


class ProviderAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_ref: str
    provider_kind: str
    auth_type: str
    models: tuple[str, ...]
    base_url: str | None = None
    env_vars_ref: tuple[str, ...] = Field(default_factory=tuple)
    credential_ref: str | None = None
    source_authority: Literal["operator_action_contract"] = "operator_action_contract"
    proof_level: ProofLevel = "contract_proof"

    @field_validator("account_ref", "provider_kind", "auth_type")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _required_text(value, info.field_name or "field")

    @field_validator("base_url", "credential_ref")
    @classmethod
    def _validate_optional_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        return _required_text(value, info.field_name or "field")

    @field_validator("models", "env_vars_ref")
    @classmethod
    def _validate_text_tuple(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        cleaned = tuple(_required_text(item, info.field_name or "field") for item in value)
        if info.field_name == "models" and not cleaned:
            raise ValueError("models must contain at least one item")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        return cleaned


class GodProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    god_id: str
    display_name: str
    role: str
    capabilities: tuple[str, ...]
    constraints: tuple[str, ...] = Field(default_factory=tuple)
    proof_policy: str
    source_authority: Literal["operator_action_contract"] = "operator_action_contract"
    proof_level: ProofLevel = "contract_proof"

    @field_validator("god_id", "display_name", "role", "proof_policy")
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _required_text(value, info.field_name or "field")

    @field_validator("capabilities", "constraints")
    @classmethod
    def _validate_text_tuple(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        cleaned = tuple(_required_text(item, info.field_name or "field") for item in value)
        if info.field_name == "capabilities" and not cleaned:
            raise ValueError("capabilities must contain at least one item")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        return cleaned


class RoomSelectedGodBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    room_id: str
    binding_revision: str
    participant_id: str
    god_id: str
    account_ref: str
    cli_command: str
    model: str
    variant: str | None = None
    proof_level: ProofLevel
    selected_by: str
    selected_at: str
    source_authority: Literal["operator_action_contract"] = "operator_action_contract"

    @field_validator(
        "room_id",
        "binding_revision",
        "participant_id",
        "god_id",
        "account_ref",
        "cli_command",
        "model",
        "selected_by",
        "selected_at",
    )
    @classmethod
    def _validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return _required_text(value, info.field_name or "field")

    @field_validator("variant")
    @classmethod
    def _validate_optional_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        return _required_text(value, info.field_name or "field")

    @model_validator(mode="after")
    def _validate_opencode_model_variant(self) -> RoomSelectedGodBinding:
        if self.cli_command == "opencode" and self.variant == "max":
            lowered = self.model.lower()
            if lowered.endswith(":max") or lowered.endswith("-max"):
                raise ValueError("opencode max must be stored in variant, not model")
        return self

    @property
    def binding_ref(self) -> str:
        return (
            f"room_selected_god_binding:{self.room_id}:"
            f"{self.participant_id}:{self.binding_revision}"
        )


class RoomSelectedGodBindingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xmuse.room_selected_god_binding_resolution.v1"] = (
        "xmuse.room_selected_god_binding_resolution.v1"
    )
    status: ResolutionStatus
    proof_level: Literal["contract_proof", "manual_gap"]
    room_id: str
    participant_id: str | None = None
    god_id: str | None = None
    binding_revision: str | None = None
    account_ref: str | None = None
    cli_command: str | None = None
    model: str | None = None
    variant: str | None = None
    blocked_reason: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    binding: RoomSelectedGodBinding | None = None
    provider_account: ProviderAccount | None = None
    god_profile: GodProfile | None = None


@dataclass(frozen=True)
class GodIdentityBindingRecord:
    provider_accounts: dict[str, ProviderAccount]
    god_profiles: dict[str, GodProfile]
    room_bindings: dict[str, RoomSelectedGodBinding]


class GodIdentityBindingStore:
    """Durable JSON authority for room-selected GOD/provider bindings."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def upsert_provider_account(self, account: ProviderAccount) -> ProviderAccount:
        record = self._read_record()
        record.provider_accounts[account.account_ref] = account
        self._write_record(record)
        return account

    def upsert_god_profile(self, profile: GodProfile) -> GodProfile:
        record = self._read_record()
        record.god_profiles[profile.god_id] = profile
        self._write_record(record)
        return profile

    def upsert_room_binding(
        self,
        binding: RoomSelectedGodBinding,
    ) -> RoomSelectedGodBinding:
        record = self._read_record()
        record.room_bindings[_binding_key(binding.room_id, binding.participant_id)] = binding
        self._write_record(record)
        return binding

    def upsert_selection(
        self,
        *,
        provider_account: ProviderAccount,
        god_profile: GodProfile,
        room_binding: RoomSelectedGodBinding,
    ) -> RoomSelectedGodBindingResolution:
        record = self._read_record()
        record.provider_accounts[provider_account.account_ref] = provider_account
        record.god_profiles[god_profile.god_id] = god_profile
        record.room_bindings[
            _binding_key(room_binding.room_id, room_binding.participant_id)
        ] = room_binding
        self._write_record(record)
        return self.resolve(
            room_id=room_binding.room_id,
            participant_id=room_binding.participant_id,
            god_id=room_binding.god_id,
        )

    def get_provider_account(self, account_ref: str) -> ProviderAccount | None:
        return self._read_record().provider_accounts.get(account_ref.strip())

    def get_god_profile(self, god_id: str) -> GodProfile | None:
        return self._read_record().god_profiles.get(god_id.strip())

    def get_room_binding(
        self,
        *,
        room_id: str,
        participant_id: str,
    ) -> RoomSelectedGodBinding | None:
        return self._read_record().room_bindings.get(_binding_key(room_id, participant_id))

    def list_room_bindings(self, room_id: str | None = None) -> list[RoomSelectedGodBinding]:
        record = self._read_record()
        bindings = list(record.room_bindings.values())
        if room_id is not None:
            cleaned_room_id = room_id.strip()
            bindings = [binding for binding in bindings if binding.room_id == cleaned_room_id]
        return sorted(
            bindings,
            key=lambda item: (item.room_id, item.participant_id, item.binding_revision),
        )

    def resolve(
        self,
        *,
        room_id: str,
        participant_id: str,
        god_id: str | None = None,
    ) -> RoomSelectedGodBindingResolution:
        room = _required_text(room_id, "room_id")
        participant = _required_text(participant_id, "participant_id")
        expected_god = god_id.strip() if isinstance(god_id, str) and god_id.strip() else None
        record = self._read_record()
        binding = record.room_bindings.get(_binding_key(room, participant))
        if binding is None:
            return _manual_gap(
                room_id=room,
                participant_id=participant,
                god_id=expected_god,
                blocked_reason="room selected GOD binding unavailable",
                source_refs=[f"god-room-participant:{participant}"],
            )
        if expected_god is not None and binding.god_id != expected_god:
            return _manual_gap(
                room_id=room,
                participant_id=participant,
                god_id=expected_god,
                binding=binding,
                blocked_reason=(
                    f"room selected GOD binding is for {binding.god_id}, "
                    f"not {expected_god}"
                ),
                source_refs=[binding.binding_ref],
            )
        account = record.provider_accounts.get(binding.account_ref)
        if account is None:
            return _manual_gap(
                room_id=room,
                participant_id=participant,
                god_id=binding.god_id,
                binding=binding,
                blocked_reason=f"provider account unavailable: {binding.account_ref}",
                source_refs=[binding.binding_ref],
            )
        profile = record.god_profiles.get(binding.god_id)
        if profile is None:
            return _manual_gap(
                room_id=room,
                participant_id=participant,
                god_id=binding.god_id,
                binding=binding,
                provider_account=account,
                blocked_reason=f"GOD profile unavailable: {binding.god_id}",
                source_refs=[binding.binding_ref, f"provider_account:{account.account_ref}"],
            )
        if binding.model not in account.models:
            return _manual_gap(
                room_id=room,
                participant_id=participant,
                god_id=binding.god_id,
                binding=binding,
                provider_account=account,
                god_profile=profile,
                blocked_reason=(
                    f"binding model {binding.model} is not allowed by "
                    f"provider account {account.account_ref}"
                ),
                source_refs=[
                    binding.binding_ref,
                    f"provider_account:{account.account_ref}",
                    f"god_profile:{profile.god_id}",
                ],
            )
        return RoomSelectedGodBindingResolution(
            status="resolved",
            proof_level="contract_proof",
            room_id=room,
            participant_id=participant,
            god_id=binding.god_id,
            binding_revision=binding.binding_revision,
            account_ref=binding.account_ref,
            cli_command=binding.cli_command,
            model=binding.model,
            variant=binding.variant,
            source_refs=[
                binding.binding_ref,
                f"provider_account:{account.account_ref}",
                f"god_profile:{profile.god_id}",
            ],
            binding=binding,
            provider_account=account,
            god_profile=profile,
        )

    def _read_record(self) -> GodIdentityBindingRecord:
        payload = self._read_payload()
        return GodIdentityBindingRecord(
            provider_accounts={
                key: account
                for key, account in (
                    _provider_account_item(item)
                    for item in _object_dict(payload.get("provider_accounts")).values()
                )
                if key is not None and account is not None
            },
            god_profiles={
                key: profile
                for key, profile in (
                    _god_profile_item(item)
                    for item in _object_dict(payload.get("god_profiles")).values()
                )
                if key is not None and profile is not None
            },
            room_bindings={
                key: binding
                for key, binding in (
                    _room_binding_item(item)
                    for item in _object_dict(payload.get("room_bindings")).values()
                )
                if key is not None and binding is not None
            },
        )

    def _write_record(self, record: GodIdentityBindingRecord) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "provider_accounts": {
                account_ref: account.model_dump(mode="json")
                for account_ref, account in sorted(record.provider_accounts.items())
            },
            "god_profiles": {
                god_id: profile.model_dump(mode="json")
                for god_id, profile in sorted(record.god_profiles.items())
            },
            "room_bindings": {
                key: binding.model_dump(mode="json")
                for key, binding in sorted(record.room_bindings.items())
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)

    def _read_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "schema_version": SCHEMA_VERSION,
                "provider_accounts": {},
                "god_profiles": {},
                "room_bindings": {},
            }
        if not isinstance(payload, dict):
            return {
                "schema_version": SCHEMA_VERSION,
                "provider_accounts": {},
                "god_profiles": {},
                "room_bindings": {},
            }
        return payload


def build_default_room_binding_revision(*, room_id: str, participant_id: str) -> str:
    room = _required_text(room_id, "room_id")
    participant = _required_text(participant_id, "participant_id")
    return f"binding:{room}:{participant}:1"


def build_operator_selected_god_binding(
    *,
    room_id: str,
    participant_id: str,
    god_id: str,
    account_ref: str,
    cli_command: str,
    model: str,
    selected_by: str,
    selected_at: str | None = None,
    binding_revision: str | None = None,
    variant: str | None = None,
    provider_kind: str | None = None,
    auth_type: str = "env_ref",
    base_url: str | None = None,
    env_vars_ref: tuple[str, ...] = (),
    credential_ref: str | None = None,
    display_name: str | None = None,
    role: str | None = None,
    capabilities: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    proof_policy: str = "contract_proof_until_live_provider_speech",
    proof_level: ProofLevel = "contract_proof",
) -> tuple[ProviderAccount, GodProfile, RoomSelectedGodBinding]:
    room = _required_text(room_id, "room_id")
    participant = _required_text(participant_id, "participant_id")
    account = ProviderAccount(
        account_ref=account_ref,
        provider_kind=provider_kind or cli_command,
        auth_type=auth_type,
        base_url=base_url,
        models=(model,),
        env_vars_ref=env_vars_ref,
        credential_ref=credential_ref,
        proof_level=proof_level,
    )
    profile = GodProfile(
        god_id=god_id,
        display_name=display_name or god_id,
        role=role or "god",
        capabilities=capabilities or ("peer_god_candidate",),
        constraints=constraints,
        proof_policy=proof_policy,
        proof_level=proof_level,
    )
    binding = RoomSelectedGodBinding(
        room_id=room,
        binding_revision=binding_revision
        or build_default_room_binding_revision(room_id=room, participant_id=participant),
        participant_id=participant,
        god_id=god_id,
        account_ref=account_ref,
        cli_command=cli_command,
        model=model,
        variant=variant,
        proof_level=proof_level,
        selected_by=selected_by,
        selected_at=selected_at or _utcnow(),
    )
    return account, profile, binding


def _manual_gap(
    *,
    room_id: str,
    blocked_reason: str,
    participant_id: str | None = None,
    god_id: str | None = None,
    binding: RoomSelectedGodBinding | None = None,
    provider_account: ProviderAccount | None = None,
    god_profile: GodProfile | None = None,
    source_refs: list[str] | None = None,
) -> RoomSelectedGodBindingResolution:
    return RoomSelectedGodBindingResolution(
        status="manual_gap",
        proof_level="manual_gap",
        room_id=room_id,
        participant_id=participant_id,
        god_id=god_id,
        binding_revision=binding.binding_revision if binding is not None else None,
        account_ref=binding.account_ref if binding is not None else None,
        cli_command=binding.cli_command if binding is not None else None,
        model=binding.model if binding is not None else None,
        variant=binding.variant if binding is not None else None,
        blocked_reason=blocked_reason,
        source_refs=_unique(source_refs or []),
        binding=binding,
        provider_account=provider_account,
        god_profile=god_profile,
    )


def _provider_account_item(item: object) -> tuple[str | None, ProviderAccount | None]:
    if not isinstance(item, dict):
        return None, None
    try:
        account = ProviderAccount.model_validate(item)
    except ValueError:
        return None, None
    return account.account_ref, account


def _god_profile_item(item: object) -> tuple[str | None, GodProfile | None]:
    if not isinstance(item, dict):
        return None, None
    try:
        profile = GodProfile.model_validate(item)
    except ValueError:
        return None, None
    return profile.god_id, profile


def _room_binding_item(item: object) -> tuple[str | None, RoomSelectedGodBinding | None]:
    if not isinstance(item, dict):
        return None, None
    try:
        binding = RoomSelectedGodBinding.model_validate(item)
    except ValueError:
        return None, None
    return _binding_key(binding.room_id, binding.participant_id), binding


def _object_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _binding_key(room_id: str, participant_id: str) -> str:
    return f"{room_id.strip()}::{participant_id.strip()}"


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "GodIdentityBindingStore",
    "GodProfile",
    "ProviderAccount",
    "RoomSelectedGodBinding",
    "RoomSelectedGodBindingResolution",
    "build_default_room_binding_revision",
    "build_operator_selected_god_binding",
]
