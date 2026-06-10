from __future__ import annotations

from collections.abc import Iterable

from xmuse_core.providers.models import (
    AdapterKind,
    CostTier,
    PersistentCapability,
    ProviderId,
    ProviderProfile,
    ProviderProfileId,
    RiskTier,
    SupportLevel,
    TaskCapability,
)

DEFAULT_CODEX_ORDINARY_MODEL_ID = "gpt-5.4"
DEFAULT_CODEX_MODEL_ID = DEFAULT_CODEX_ORDINARY_MODEL_ID
DEFAULT_CODEX_GOD_MODEL_ID = DEFAULT_CODEX_ORDINARY_MODEL_ID
DEFAULT_CODEX_REVIEW_MODEL_ID = DEFAULT_CODEX_ORDINARY_MODEL_ID
DEFAULT_CODEX_WORKER_MODEL_ID = "gpt-5.4-mini"
DEFAULT_CODEX_FINAL_QUALITY_MODEL_ID = "gpt-5.5"
DEFAULT_OPENCODE_DEEPSEEK_MODEL_ID = "deepseek-v4-flash"
DEFAULT_OPENCODE_DEEPSEEK_MODEL_ENV_NAME = "DEEPSEEK_MODEL"
DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME = "DEEPSEEK_BASE_URL"
DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME = "DEEPSEEK_API_KEY"


def is_reserved_final_quality_model_id(model_id: str | None) -> bool:
    normalized = _clean_model_id(model_id)
    return normalized is not None and normalized.lower().startswith("gpt-5.5")


def default_codex_model_id_for_profile(
    profile_id: ProviderProfileId | str,
    *,
    allow_final_quality: bool = False,
) -> str:
    normalized_profile_id = _coerce_profile_id(profile_id)
    if normalized_profile_id is ProviderProfileId.WORKER:
        return DEFAULT_CODEX_WORKER_MODEL_ID
    if (
        allow_final_quality
        and normalized_profile_id is ProviderProfileId.FINAL_QUALITY
    ):
        return DEFAULT_CODEX_FINAL_QUALITY_MODEL_ID
    return DEFAULT_CODEX_ORDINARY_MODEL_ID


def normalize_codex_model_id(
    model_id: str | None,
    *,
    profile_id: ProviderProfileId | str,
    allow_final_quality: bool = False,
) -> str:
    default_model_id = default_codex_model_id_for_profile(
        profile_id,
        allow_final_quality=allow_final_quality,
    )
    normalized = _clean_model_id(model_id)
    if normalized is None:
        return default_model_id
    if is_reserved_final_quality_model_id(normalized) and not allow_final_quality:
        return default_model_id
    return normalized


def _clean_model_id(model_id: str | None) -> str | None:
    if not isinstance(model_id, str):
        return None
    normalized = model_id.strip()
    return normalized or None


def _coerce_profile_id(profile_id: ProviderProfileId | str) -> ProviderProfileId:
    if isinstance(profile_id, ProviderProfileId):
        return profile_id
    return ProviderProfileId(profile_id.strip())


class ProviderRegistry:
    def __init__(self, profiles: Iterable[ProviderProfile]) -> None:
        ordered_profiles = tuple(profiles)
        by_ref: dict[str, ProviderProfile] = {}
        for profile in ordered_profiles:
            if profile.ref in by_ref:
                raise ValueError(f"duplicate provider profile ref: {profile.ref}")
            by_ref[profile.ref] = profile
        self._profiles = ordered_profiles
        self._by_ref = by_ref

    def list_profiles(self) -> list[ProviderProfile]:
        return list(self._profiles)

    def list_provider_profiles(self, provider_id: ProviderId) -> list[ProviderProfile]:
        return [
            profile
            for profile in self._profiles
            if profile.provider_id is provider_id
        ]

    def get(self, ref: str) -> ProviderProfile:
        cleaned_ref = ref.strip()
        if not cleaned_ref:
            raise KeyError("provider profile ref must be non-empty")
        try:
            return self._by_ref[cleaned_ref]
        except KeyError as exc:
            raise KeyError(f"unknown provider profile: {cleaned_ref}") from exc


def build_default_provider_registry(
    *,
    opencode_deepseek_model_id: str = DEFAULT_OPENCODE_DEEPSEEK_MODEL_ID,
) -> ProviderRegistry:
    return ProviderRegistry(
        [
            ProviderProfile(
                provider_id=ProviderId.CODEX,
                profile_id=ProviderProfileId.DEFAULT,
                adapter_kind=AdapterKind.CODEX_CLI,
                model_id=DEFAULT_CODEX_MODEL_ID,
                supports_mcp=True,
                persistent_capability=PersistentCapability.SUPPORTED,
                support_level=SupportLevel.PRIMARY,
                cost_tier=CostTier.HIGH,
                risk_tier=RiskTier.HIGH,
                task_capabilities=(
                    TaskCapability.BOUNDED_CODE_WRITING,
                    TaskCapability.REVIEW,
                    TaskCapability.LANE_COORDINATION,
                    TaskCapability.PLANNING,
                    TaskCapability.TAKEOVER,
                ),
            ),
            ProviderProfile(
                provider_id=ProviderId.CODEX,
                profile_id=ProviderProfileId.WORKER,
                adapter_kind=AdapterKind.CODEX_CLI,
                model_id=DEFAULT_CODEX_WORKER_MODEL_ID,
                supports_mcp=True,
                persistent_capability=PersistentCapability.SUPPORTED,
                support_level=SupportLevel.PRIMARY,
                cost_tier=CostTier.LOW,
                risk_tier=RiskTier.LOW,
                task_capabilities=(TaskCapability.BOUNDED_CODE_WRITING,),
            ),
            ProviderProfile(
                provider_id=ProviderId.CODEX,
                profile_id=ProviderProfileId.REVIEW,
                adapter_kind=AdapterKind.CODEX_CLI,
                model_id=DEFAULT_CODEX_REVIEW_MODEL_ID,
                supports_mcp=True,
                persistent_capability=PersistentCapability.SUPPORTED,
                support_level=SupportLevel.PRIMARY,
                cost_tier=CostTier.HIGH,
                risk_tier=RiskTier.HIGH,
                task_capabilities=(TaskCapability.REVIEW,),
            ),
            ProviderProfile(
                provider_id=ProviderId.CODEX,
                profile_id=ProviderProfileId.GOD,
                adapter_kind=AdapterKind.CODEX_CLI,
                model_id=DEFAULT_CODEX_GOD_MODEL_ID,
                supports_mcp=True,
                persistent_capability=PersistentCapability.SUPPORTED,
                support_level=SupportLevel.PRIMARY,
                cost_tier=CostTier.MEDIUM,
                risk_tier=RiskTier.HIGH,
                task_capabilities=(
                    TaskCapability.LANE_COORDINATION,
                    TaskCapability.PLANNING,
                    TaskCapability.TAKEOVER,
                ),
            ),
            ProviderProfile(
                provider_id=ProviderId.CODEX,
                profile_id=ProviderProfileId.FINAL_QUALITY,
                adapter_kind=AdapterKind.CODEX_CLI,
                model_id=DEFAULT_CODEX_FINAL_QUALITY_MODEL_ID,
                supports_mcp=True,
                persistent_capability=PersistentCapability.SUPPORTED,
                support_level=SupportLevel.PRIMARY,
                cost_tier=CostTier.HIGH,
                risk_tier=RiskTier.HIGH,
                task_capabilities=(TaskCapability.MERGE_FINAL_REVIEW,),
            ),
            ProviderProfile(
                provider_id=ProviderId.OPENCODE,
                profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
                adapter_kind=AdapterKind.OPENCODE_CLI,
                model_id=opencode_deepseek_model_id,
                model_id_env_name=DEFAULT_OPENCODE_DEEPSEEK_MODEL_ENV_NAME,
                api_base_env_name=DEFAULT_OPENCODE_DEEPSEEK_BASE_ENV_NAME,
                env_requirement_names=(DEFAULT_OPENCODE_DEEPSEEK_API_KEY_ENV_NAME,),
                supports_mcp=False,
                persistent_capability=PersistentCapability.UNSUPPORTED,
                support_level=SupportLevel.SECONDARY,
                cost_tier=CostTier.LOW,
                risk_tier=RiskTier.LOW,
                task_capabilities=(TaskCapability.BOUNDED_CODE_WRITING,),
            ),
        ]
    )
