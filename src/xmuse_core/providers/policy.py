from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from xmuse_core.providers.adapters.base import ProviderFailureKind
from xmuse_core.providers.health import (
    ProviderHealthSnapshot,
    infer_provider_health_failure_kind,
)
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.registry import ProviderRegistry, build_default_provider_registry
from xmuse_core.providers.selection_record import ProviderSelectionRecord

PolicyPeerType = Literal["god", "review", "coordinator", "worker", "deliberation"]
EscalationLevel = Literal["none", "medium", "high"]

DEFAULT_GOD_PROFILE_REF = "codex.god"
DEFAULT_FINAL_QUALITY_PROFILE_REF = "codex.final_quality"
DEFAULT_REVIEW_PROFILE_REF = "codex.review"
DEFAULT_COORDINATOR_PROFILE_REF = "codex.god"
DEFAULT_LOW_COST_WORKER_PROFILE_REF = "opencode.deepseek_flash_worker"
DEFAULT_FALLBACK_WORKER_PROFILE_REF = "codex.worker"
DEFAULT_ESCALATED_WORKER_PROFILE_REF = "codex.god"
DEFAULT_FALLBACK_DELIBERATION_PROFILE_REF = "codex.god"
DEFAULT_A2A_REMOTE_PROFILE_REF = "a2a.remote"
BOUNDED_DELIBERATION_SPEECH_ACTS = ("propose", "ask", "challenge")


def _require_text(value: str, field_name: str | None) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name or 'field'} must be non-empty")
    return cleaned


def _require_optional_text(value: str | None, field_name: str | None) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _requested_review_runtime(lane: Mapping[str, Any] | None) -> str | None:
    if lane is None:
        return None
    value = lane.get("review_runtime")
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


class LanePolicySignals(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repeated_failure: bool
    ambiguous_review: bool
    cross_module_blast_radius: bool
    high_risk_files: bool
    bounded_context: bool
    well_specified: bool
    low_risk_bounded_task: bool
    downgrade_to_low_cost: bool
    escalation_level: EscalationLevel
    escalation_reasons: tuple[str, ...] = Field(default_factory=tuple)
    lane_risk: RiskTier

    def to_adjustment_summary(self) -> dict[str, object]:
        return {
            "repeated_failure": self.repeated_failure,
            "ambiguous_review": self.ambiguous_review,
            "cross_module_blast_radius": self.cross_module_blast_radius,
            "high_risk_files": self.high_risk_files,
            "bounded_context": self.bounded_context,
            "well_specified": self.well_specified,
            "low_risk_bounded_task": self.low_risk_bounded_task,
            "downgrade_to_low_cost": self.downgrade_to_low_cost,
            "escalation_level": self.escalation_level,
            "escalation_reasons": list(self.escalation_reasons),
        }


class ProviderPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    profile_id: ProviderProfileId
    task_type: TaskCapability
    lane_risk: RiskTier
    peer_type: PolicyPeerType
    selected_model: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1, max_length=512)
    fallback_cause: str | None = Field(default=None, max_length=256)
    health_failure_kind: str | None = Field(default=None, max_length=256)
    escalation_level: EscalationLevel = "none"
    escalation_reasons: tuple[str, ...] = Field(default_factory=tuple)
    allowed_speech_acts: tuple[str, ...] = Field(default_factory=tuple)
    state_write_allowed: bool = True

    @field_validator("selected_model", "selection_reason")
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        return _require_text(value, info.field_name)

    @field_validator("fallback_cause", "health_failure_kind")
    @classmethod
    def _validate_optional_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return _require_optional_text(value, info.field_name)

    @field_validator("allowed_speech_acts")
    @classmethod
    def _validate_allowed_speech_acts(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(_require_text(item, "allowed_speech_acts") for item in value)
        duplicates = sorted({item for item in cleaned if cleaned.count(item) > 1})
        if duplicates:
            raise ValueError(
                "allowed_speech_acts must not contain duplicates: "
                + ", ".join(duplicates)
            )
        return cleaned

    @property
    def provider_profile_ref(self) -> str:
        return f"{self.provider_id.value}.{self.profile_id.value}"

    def to_selection_record(
        self,
        *,
        lane_id: str,
        selected_at: datetime,
    ) -> ProviderSelectionRecord:
        return ProviderSelectionRecord(
            lane_id=lane_id,
            selected_at=selected_at,
            provider_id=self.provider_id,
            profile_id=self.profile_id,
            task_type=self.task_type,
            lane_risk=self.lane_risk,
            selection_reason=self.selection_reason,
            peer_type=self.peer_type,
            fallback_cause=self.fallback_cause,
            health_failure_kind=self.health_failure_kind,
            source_authority="provider_policy",
        )


class ProviderPolicyService:
    def __init__(
        self,
        *,
        registry: ProviderRegistry | None = None,
        god_profile_ref: str = DEFAULT_GOD_PROFILE_REF,
        final_quality_profile_ref: str = DEFAULT_FINAL_QUALITY_PROFILE_REF,
        review_profile_ref: str = DEFAULT_REVIEW_PROFILE_REF,
        coordinator_profile_ref: str = DEFAULT_COORDINATOR_PROFILE_REF,
        low_cost_worker_profile_ref: str = DEFAULT_LOW_COST_WORKER_PROFILE_REF,
        fallback_worker_profile_ref: str = DEFAULT_FALLBACK_WORKER_PROFILE_REF,
        escalated_worker_profile_ref: str = DEFAULT_ESCALATED_WORKER_PROFILE_REF,
        fallback_deliberation_profile_ref: str = DEFAULT_FALLBACK_DELIBERATION_PROFILE_REF,
    ) -> None:
        self._registry = registry or build_default_provider_registry()
        self._god_profile_ref = god_profile_ref
        self._final_quality_profile_ref = final_quality_profile_ref
        self._review_profile_ref = review_profile_ref
        self._coordinator_profile_ref = coordinator_profile_ref
        self._low_cost_worker_profile_ref = low_cost_worker_profile_ref
        self._fallback_worker_profile_ref = fallback_worker_profile_ref
        self._escalated_worker_profile_ref = escalated_worker_profile_ref
        self._fallback_deliberation_profile_ref = fallback_deliberation_profile_ref

    def select_god(
        self,
        *,
        task_type: TaskCapability = TaskCapability.TAKEOVER,
        lane: Mapping[str, Any] | None = None,
    ) -> ProviderPolicyDecision:
        profile_ref = (
            self._final_quality_profile_ref
            if task_type is TaskCapability.MERGE_FINAL_REVIEW
            else self._god_profile_ref
        )
        profile = self._registry.get(profile_ref)
        if task_type not in profile.task_capabilities:
            raise ValueError(f"{profile.ref} does not support {task_type.value}")
        lane_risk = (
            evaluate_lane_policy_signals(lane).lane_risk
            if lane is not None
            else RiskTier.HIGH
        )
        selection_reason = "Route GOD work to the high-quality codex GOD profile."
        if task_type is TaskCapability.MERGE_FINAL_REVIEW:
            selection_reason = (
                "Route merge final review to the reserved final-quality codex "
                "profile."
            )
        return ProviderPolicyDecision(
            provider_id=profile.provider_id,
            profile_id=profile.profile_id,
            task_type=task_type,
            lane_risk=lane_risk,
            peer_type="god",
            selected_model=profile.model_id,
            selection_reason=selection_reason,
        )

    def select_review(
        self,
        *,
        lane: Mapping[str, Any] | None = None,
    ) -> ProviderPolicyDecision:
        signals = evaluate_lane_policy_signals(lane or {})
        requested_review_runtime = _requested_review_runtime(lane)
        if requested_review_runtime in {"a2a", "a2a.remote"}:
            profile = self._registry.get(DEFAULT_A2A_REMOTE_PROFILE_REF)
            selection_reason = (
                "Route review to the requested A2A remote profile from lane "
                "review_runtime authority."
            )
            return ProviderPolicyDecision(
                provider_id=profile.provider_id,
                profile_id=profile.profile_id,
                task_type=TaskCapability.REVIEW,
                lane_risk=signals.lane_risk if lane is not None else RiskTier.HIGH,
                peer_type="review",
                selected_model=profile.model_id,
                selection_reason=selection_reason,
                escalation_level=signals.escalation_level,
                escalation_reasons=signals.escalation_reasons,
            )
        profile = self._registry.get(self._review_profile_ref)
        selection_reason = "Route review to the high-quality codex review profile."
        if signals.escalation_reasons:
            selection_reason = (
                "Keep review on the high-quality codex review profile for "
                f"{_format_reason_list(list(signals.escalation_reasons))}."
            )
        return ProviderPolicyDecision(
            provider_id=profile.provider_id,
            profile_id=profile.profile_id,
            task_type=TaskCapability.REVIEW,
            lane_risk=signals.lane_risk if lane is not None else RiskTier.HIGH,
            peer_type="review",
            selected_model=profile.model_id,
            selection_reason=selection_reason,
            escalation_level=signals.escalation_level,
            escalation_reasons=signals.escalation_reasons,
        )

    def select_coordinator(
        self,
        *,
        lane: Mapping[str, Any] | None = None,
    ) -> ProviderPolicyDecision:
        profile = self._registry.get(self._coordinator_profile_ref)
        signals = evaluate_lane_policy_signals(lane or {})
        return ProviderPolicyDecision(
            provider_id=profile.provider_id,
            profile_id=profile.profile_id,
            task_type=TaskCapability.LANE_COORDINATION,
            lane_risk=signals.lane_risk if lane is not None else RiskTier.MEDIUM,
            peer_type="coordinator",
            selected_model=profile.model_id,
            selection_reason=(
                "Route coordination to the mid-tier codex coordinator profile."
            ),
            escalation_level=signals.escalation_level,
            escalation_reasons=signals.escalation_reasons,
        )

    def select_worker(
        self,
        *,
        lane: Mapping[str, Any],
        health_by_profile: Mapping[str, ProviderHealthSnapshot] | None = None,
    ) -> ProviderPolicyDecision:
        signals = evaluate_lane_policy_signals(lane)

        if signals.escalation_level != "none":
            profile = self._registry.get(self._escalated_worker_profile_ref)
            return ProviderPolicyDecision(
                provider_id=profile.provider_id,
                profile_id=profile.profile_id,
                task_type=TaskCapability.BOUNDED_CODE_WRITING,
                lane_risk=signals.lane_risk,
                peer_type="worker",
                selected_model=profile.model_id,
                selection_reason=(
                    "Escalated bounded code writing to the mid-tier "
                    "codex GOD profile for "
                    f"{_format_reason_list(list(signals.escalation_reasons))}."
                ),
                escalation_level=signals.escalation_level,
                escalation_reasons=signals.escalation_reasons,
            )

        if signals.low_risk_bounded_task:
            low_cost_profile = self._registry.get(self._low_cost_worker_profile_ref)
            low_cost_health = _select_health_snapshot(
                low_cost_profile.provider_id,
                low_cost_profile.profile_id,
                health_by_profile,
            )
            if _is_healthy(low_cost_health):
                return ProviderPolicyDecision(
                    provider_id=low_cost_profile.provider_id,
                    profile_id=low_cost_profile.profile_id,
                    task_type=TaskCapability.BOUNDED_CODE_WRITING,
                    lane_risk=signals.lane_risk,
                    peer_type="worker",
                    selected_model=low_cost_profile.model_id,
                    selection_reason=(
                        "Prefer the healthy low-cost worker profile for "
                        "bounded low-risk work."
                    ),
                )

            fallback_profile = self._registry.get(self._fallback_worker_profile_ref)
            health_failure_kind = classify_provider_health_failure(low_cost_health)
            return ProviderPolicyDecision(
                provider_id=fallback_profile.provider_id,
                profile_id=fallback_profile.profile_id,
                task_type=TaskCapability.BOUNDED_CODE_WRITING,
                lane_risk=signals.lane_risk,
                peer_type="worker",
                selected_model=fallback_profile.model_id,
                selection_reason=(
                    "Fallback to the codex worker profile because the low-cost "
                    "worker is unavailable."
                ),
                fallback_cause=health_failure_kind,
                health_failure_kind=health_failure_kind,
            )

        fallback_profile = self._registry.get(self._fallback_worker_profile_ref)
        return ProviderPolicyDecision(
            provider_id=fallback_profile.provider_id,
            profile_id=fallback_profile.profile_id,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=signals.lane_risk,
            peer_type="worker",
            selected_model=fallback_profile.model_id,
            selection_reason=(
                "Use the codex worker profile for bounded code writing outside "
                "the low-risk bulk-worker path."
            ),
        )

    def select_bounded_deliberation(
        self,
        *,
        lane: Mapping[str, Any],
        health_by_profile: Mapping[str, ProviderHealthSnapshot] | None = None,
    ) -> ProviderPolicyDecision:
        signals = evaluate_lane_policy_signals(lane)
        low_cost_profile = self._registry.get(self._low_cost_worker_profile_ref)
        if TaskCapability.BOUNDED_DELIBERATION not in low_cost_profile.task_capabilities:
            raise ValueError(
                f"{low_cost_profile.ref} does not support "
                f"{TaskCapability.BOUNDED_DELIBERATION.value}"
            )
        low_cost_health = _select_health_snapshot(
            low_cost_profile.provider_id,
            low_cost_profile.profile_id,
            health_by_profile,
        )
        if _is_healthy(low_cost_health):
            return ProviderPolicyDecision(
                provider_id=low_cost_profile.provider_id,
                profile_id=low_cost_profile.profile_id,
                task_type=TaskCapability.BOUNDED_DELIBERATION,
                lane_risk=signals.lane_risk,
                peer_type="deliberation",
                selected_model=low_cost_profile.model_id,
                selection_reason=(
                    "Select healthy OpenCode as a bounded deliberation participant "
                    "with no state-write authority."
                ),
                allowed_speech_acts=BOUNDED_DELIBERATION_SPEECH_ACTS,
                state_write_allowed=False,
            )

        fallback_profile = self._registry.get(self._fallback_deliberation_profile_ref)
        if TaskCapability.BOUNDED_DELIBERATION not in fallback_profile.task_capabilities:
            raise ValueError(
                f"{fallback_profile.ref} does not support "
                f"{TaskCapability.BOUNDED_DELIBERATION.value}"
            )
        health_failure_kind = classify_provider_health_failure(low_cost_health)
        return ProviderPolicyDecision(
            provider_id=fallback_profile.provider_id,
            profile_id=fallback_profile.profile_id,
            task_type=TaskCapability.BOUNDED_DELIBERATION,
            lane_risk=signals.lane_risk,
            peer_type="deliberation",
            selected_model=fallback_profile.model_id,
            selection_reason=(
                "Fallback to Codex for bounded deliberation because OpenCode is "
                "unavailable."
            ),
            fallback_cause=health_failure_kind,
            health_failure_kind=health_failure_kind,
            allowed_speech_acts=BOUNDED_DELIBERATION_SPEECH_ACTS,
            state_write_allowed=False,
        )


def classify_provider_health_failure(
    snapshot: ProviderHealthSnapshot | None,
) -> str:
    failure_kind = infer_provider_health_failure_kind(snapshot)
    if failure_kind is None:
        return ProviderFailureKind.UNAVAILABLE.value
    return failure_kind.value


def evaluate_lane_policy_signals(lane: Mapping[str, Any]) -> LanePolicySignals:
    changed_files = _changed_files(lane)
    repeated_failure = is_repeated_failure_lane(lane)
    ambiguous_review = has_ambiguous_review_signal(lane)
    cross_module_blast_radius = _has_cross_module_blast_radius(changed_files)
    high_risk_files = has_high_risk_files(lane)
    bounded_context = _bool_flag(lane, "bounded_context")
    well_specified = _bool_flag(lane, "well_specified")
    low_risk_bounded_task = is_low_risk_bounded_task(lane)
    downgrade_to_low_cost = (
        low_risk_bounded_task
        and not repeated_failure
        and not ambiguous_review
        and not cross_module_blast_radius
        and not high_risk_files
    )

    escalation_reasons: list[str] = []
    if repeated_failure:
        escalation_reasons.append("repeated failure")
    if ambiguous_review:
        escalation_reasons.append("ambiguous review")
    if high_risk_files:
        escalation_reasons.append("high-risk files")
    if cross_module_blast_radius:
        escalation_reasons.append("cross-module blast radius")

    escalation_level: EscalationLevel = "none"
    if escalation_reasons:
        escalation_level = "medium"
    if _explicit_risk(lane) == "high" or len(escalation_reasons) >= 3:
        escalation_level = "high"
    if repeated_failure and ambiguous_review and escalation_level != "high":
        escalation_level = "high"

    return LanePolicySignals(
        repeated_failure=repeated_failure,
        ambiguous_review=ambiguous_review,
        cross_module_blast_radius=cross_module_blast_radius,
        high_risk_files=high_risk_files,
        bounded_context=bounded_context,
        well_specified=well_specified,
        low_risk_bounded_task=low_risk_bounded_task,
        downgrade_to_low_cost=downgrade_to_low_cost,
        escalation_level=escalation_level,
        escalation_reasons=tuple(escalation_reasons),
        lane_risk=_lane_risk_for_selection(
            lane,
            downgrade_to_low_cost=downgrade_to_low_cost,
            escalation_level=escalation_level,
        ),
    )


def is_repeated_failure_lane(lane: Mapping[str, Any]) -> bool:
    return (
        _positive_int(lane.get("retry_count"))
        + _positive_int(lane.get("review_retry_count"))
    ) >= 2


def has_ambiguous_review_signal(lane: Mapping[str, Any]) -> bool:
    review_decision = _optional_text(lane.get("review_decision"))
    status = _optional_text(lane.get("status"))
    if review_decision == "merge" and status in {"reworking", "rejected", "gate_failed"}:
        return True
    summary = _optional_text(lane.get("review_summary"))
    if summary is None:
        return False
    lowered = summary.lower()
    return any(
        marker in lowered
        for marker in (
            "no blocking findings",
            "no blocking finding",
            "no findings",
            "approved",
            "merge",
        )
    ) and status in {"reworking", "rejected", "gate_failed"}


def has_high_risk_files(lane: Mapping[str, Any]) -> bool:
    changed_files = _changed_files(lane)
    explicit = lane.get("high_risk_files")
    if explicit is True:
        return True
    markers = (
        "orchestrator",
        "state_machine",
        "run_health",
        "review_plane",
        "projection",
        "graph",
        "schema",
        "policy",
        "store",
    )
    return any(marker in path.lower() for path in changed_files for marker in markers)


def is_low_risk_bounded_task(lane: Mapping[str, Any]) -> bool:
    return (
        _explicit_risk(lane) == "low"
        and _bool_flag(lane, "bounded_context")
        and _bool_flag(lane, "well_specified")
        and _task_type(lane)
        in {
            TaskCapability.BOUNDED_CODE_WRITING.value,
            TaskCapability.BOUNDED_DELIBERATION.value,
            "mechanical_cleanup",
            "cleanup",
            "rename",
            "formatting",
        }
    )


def _lane_risk_for_selection(
    lane: Mapping[str, Any],
    *,
    downgrade_to_low_cost: bool,
    escalation_level: EscalationLevel,
) -> RiskTier:
    explicit = _explicit_risk(lane)
    if explicit in {"low", "medium", "high"}:
        return RiskTier(explicit)
    if downgrade_to_low_cost:
        return RiskTier.LOW
    if escalation_level == "high":
        return RiskTier.HIGH
    if escalation_level == "medium":
        return RiskTier.MEDIUM
    return RiskTier.MEDIUM


def _has_cross_module_blast_radius(changed_files: list[str]) -> bool:
    roots = {_module_root(path) for path in changed_files if _module_root(path)}
    return len(roots) >= 2


def _module_root(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part and part != "."]
    if len(parts) >= 3 and parts[0] in {"src", "tests"}:
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else ""


def _select_health_snapshot(
    provider_id: ProviderId,
    profile_id: ProviderProfileId,
    health_by_profile: Mapping[str, ProviderHealthSnapshot] | None,
) -> ProviderHealthSnapshot | None:
    if not health_by_profile:
        return None
    return health_by_profile.get(f"{provider_id.value}.{profile_id.value}")


def _is_healthy(snapshot: ProviderHealthSnapshot | None) -> bool:
    return snapshot is not None and (
        snapshot.is_available
        and snapshot.is_configured
        and snapshot.auth_ok
        and snapshot.model_available
    )


def _changed_files(lane: Mapping[str, Any]) -> list[str]:
    for key in (
        "changed_files",
        "changed_paths",
        "files_changed",
        "touched_files",
        "target_paths",
    ):
        value = lane.get(key)
        if isinstance(value, list):
            return [str(item) for item in value if isinstance(item, str) and item.strip()]
    return []


def _explicit_risk(lane: Mapping[str, Any]) -> Literal["low", "medium", "high"] | None:
    for key in ("lane_risk", "risk", "risk_level"):
        value = _optional_text(lane.get(key))
        if value == "low":
            return "low"
        if value == "medium":
            return "medium"
        if value == "high":
            return "high"
    return None


def _task_type(lane: Mapping[str, Any]) -> str:
    for key in ("selection_task_type", "task_type"):
        value = _optional_text(lane.get(key))
        if value is not None:
            return value
    return "lane_coordination"


def _bool_flag(lane: Mapping[str, Any], key: str) -> bool:
    return lane.get(key) is True


def _positive_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _format_reason_list(reasons: list[str]) -> str:
    if not reasons:
        return "normal risk"
    if len(reasons) == 1:
        return reasons[0]
    if len(reasons) == 2:
        return f"{reasons[0]} and {reasons[1]}"
    return f"{', '.join(reasons[:-1])}, and {reasons[-1]}"
