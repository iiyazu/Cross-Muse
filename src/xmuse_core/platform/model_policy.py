from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from xmuse_core.providers.policy import evaluate_lane_policy_signals
from xmuse_core.providers.policy import (
    has_ambiguous_review_signal as provider_has_ambiguous_review_signal,
)
from xmuse_core.providers.policy import has_high_risk_files as provider_has_high_risk_files
from xmuse_core.providers.policy import (
    is_low_risk_bounded_task as provider_is_low_risk_bounded_task,
)
from xmuse_core.providers.policy import (
    is_repeated_failure_lane as provider_is_repeated_failure_lane,
)
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    DEFAULT_CODEX_REVIEW_MODEL_ID,
    DEFAULT_CODEX_WORKER_MODEL_ID,
    normalize_codex_model_id,
)
from xmuse_core.providers.models import ProviderProfileId

DelegationMode = Literal["legacy_single_agent", "bounded_worker"]

DEFAULT_CODEX_MODEL = DEFAULT_CODEX_REVIEW_MODEL_ID
DEFAULT_TIERED_REVIEW_MODEL = DEFAULT_CODEX_REVIEW_MODEL_ID
DEFAULT_TIERED_COORDINATOR_MODEL = DEFAULT_CODEX_GOD_MODEL_ID
DEFAULT_TIERED_WORKER_MODEL = DEFAULT_CODEX_WORKER_MODEL_ID
BOUNDED_CODE_WRITING_DELEGATION_CONTRACT = "bounded_code_writing_v1"
MODEL_TIER_FRONTIER = "frontier_high_reasoning"
MODEL_TIER_MID = "mid_tier"
MODEL_TIER_LOW = "low_cost"


class CodexModelPolicy(BaseModel):
    """Codex-only model policy metadata for opt-in tiered execution."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    runtime: Literal["codex"] = "codex"
    review_model: str = Field(default=DEFAULT_CODEX_REVIEW_MODEL_ID, min_length=1)
    coordinator_model: str = Field(default=DEFAULT_CODEX_GOD_MODEL_ID, min_length=1)
    worker_model: str = Field(default=DEFAULT_CODEX_WORKER_MODEL_ID, min_length=1)
    delegation_mode: DelegationMode = "legacy_single_agent"

    @field_validator("review_model", "coordinator_model", "worker_model")
    @classmethod
    def _sanitize_ordinary_role_model(
        cls,
        value: str,
        info: ValidationInfo,
    ) -> str:
        profile_id = {
            "review_model": ProviderProfileId.REVIEW,
            "coordinator_model": ProviderProfileId.GOD,
            "worker_model": ProviderProfileId.WORKER,
        }[str(info.field_name)]
        return normalize_codex_model_id(value, profile_id=profile_id)

    @classmethod
    def default(cls) -> CodexModelPolicy:
        return cls()

    @classmethod
    def tiered(
        cls,
        *,
        review_model: str | None = None,
        coordinator_model: str | None = None,
        worker_model: str | None = None,
        delegation_mode: DelegationMode | None = None,
    ) -> CodexModelPolicy:
        return cls(
            enabled=True,
            review_model=review_model or DEFAULT_TIERED_REVIEW_MODEL,
            coordinator_model=coordinator_model or DEFAULT_TIERED_COORDINATOR_MODEL,
            worker_model=worker_model or DEFAULT_TIERED_WORKER_MODEL,
            delegation_mode=delegation_mode or "bounded_worker",
        )

    def metadata_defaults(
        self,
        *,
        lane: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        if not self.enabled:
            return {}
        metadata: dict[str, object] = {
            "model_policy_runtime": self.runtime,
            "model_policy_enabled": True,
            "review_model": self.review_model,
            "coordinator_model": self.coordinator_model,
            "worker_model": self.worker_model,
            "delegation_mode": self.delegation_mode,
            "model_selection_records": self.selection_records(lane=lane),
        }
        if self.delegation_mode == "bounded_worker":
            metadata["delegation_contract"] = (
                BOUNDED_CODE_WRITING_DELEGATION_CONTRACT
            )
        return metadata

    def selection_records(
        self,
        *,
        lane: Mapping[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        if not self.enabled:
            return []
        if lane is None or not _has_selection_context(lane):
            return _default_selection_records(self)
        lane_signals = evaluate_lane_policy_signals(lane)
        signals = _selection_signal_summary(lane_signals)
        lane_risk = lane_signals.lane_risk.value
        return [
            {
                "peer_type": "review",
                "lane_risk": lane_risk,
                "task_type": "review",
                "model_tier": MODEL_TIER_FRONTIER,
                "selected_model": self.review_model,
                "selection_reason": _review_selection_reason(signals),
            },
            {
                "peer_type": "coordinator",
                "lane_risk": lane_risk,
                "task_type": "lane_coordination",
            }
            | _coordinator_selection_record(self, signals=signals),
            {
                "peer_type": "worker",
                "lane_risk": lane_risk,
                "task_type": "bounded_code_writing",
            }
            | _worker_selection_record(self, lane_risk=lane_risk, signals=signals),
        ]


def resolve_codex_model_policy(
    *,
    enabled: bool,
    review_model: str | None = None,
    coordinator_model: str | None = None,
    worker_model: str | None = None,
    delegation_mode: DelegationMode | None = None,
) -> CodexModelPolicy | None:
    if not enabled:
        return None
    return CodexModelPolicy.tiered(
        review_model=_clean_optional(review_model),
        coordinator_model=_clean_optional(coordinator_model),
        worker_model=_clean_optional(worker_model),
        delegation_mode=delegation_mode,
    )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def evaluate_model_tier_adjustment(lane: Mapping[str, Any]) -> dict[str, object]:
    return evaluate_lane_policy_signals(lane).to_adjustment_summary()


def is_repeated_failure_lane(lane: Mapping[str, Any]) -> bool:
    return provider_is_repeated_failure_lane(lane)


def has_ambiguous_review_signal(lane: Mapping[str, Any]) -> bool:
    return provider_has_ambiguous_review_signal(lane)


def has_high_risk_files(lane: Mapping[str, Any]) -> bool:
    return provider_has_high_risk_files(lane)


def is_low_risk_bounded_task(lane: Mapping[str, Any]) -> bool:
    return provider_is_low_risk_bounded_task(lane)


def _default_selection_records(policy: CodexModelPolicy) -> list[dict[str, str]]:
    return [
        {
            "peer_type": "review",
            "lane_risk": "high",
            "task_type": "review",
            "model_tier": MODEL_TIER_FRONTIER,
            "selected_model": policy.review_model,
            "selection_reason": (
                "Persistent review and high-risk decisions stay on the "
                "frontier high-reasoning tier."
            ),
        },
        {
            "peer_type": "coordinator",
            "lane_risk": "medium",
            "task_type": "lane_coordination",
            "model_tier": MODEL_TIER_MID,
            "selected_model": policy.coordinator_model,
            "selection_reason": (
                "Lane coordination and integration default to the mid-tier "
                "Codex model."
            ),
        },
        {
            "peer_type": "worker",
            "lane_risk": "low",
            "task_type": "bounded_code_writing",
            "model_tier": MODEL_TIER_LOW,
            "selected_model": policy.worker_model,
            "selection_reason": (
                "Bounded low-risk code writing defaults to the low-cost "
                "worker tier."
            ),
        },
    ]


def _review_selection_reason(signals: dict[str, object]) -> str:
    escalation_reasons = _escalation_reasons(signals)
    if not escalation_reasons:
        return (
            "Persistent review and high-risk decisions stay on the frontier "
            "high-reasoning tier."
        )
    return (
        "Persistent review stays on the frontier high-reasoning tier for "
        f"{_format_reason_list(escalation_reasons)}."
    )


def _coordinator_selection_record(
    policy: CodexModelPolicy,
    *,
    signals: dict[str, object],
) -> dict[str, str]:
    if bool(signals["downgrade_to_low_cost"]):
        return {
            "model_tier": MODEL_TIER_LOW,
            "selected_model": policy.worker_model,
            "selection_reason": (
                "Downgraded coordination to the low-cost tier for bounded, "
                "well-specified, low-risk work."
            ),
        }
    escalation_level = str(signals["escalation_level"])
    if escalation_level == "high":
        return {
            "model_tier": MODEL_TIER_FRONTIER,
            "selected_model": policy.review_model,
            "selection_reason": (
                "Escalated lane coordination to the frontier high-reasoning "
                f"tier for {_format_reason_list(_escalation_reasons(signals))}."
            ),
        }
    return {
        "model_tier": MODEL_TIER_MID,
        "selected_model": policy.coordinator_model,
        "selection_reason": (
            "Lane coordination and integration default to the mid-tier "
            "Codex model."
        ),
    }


def _worker_selection_record(
    policy: CodexModelPolicy,
    *,
    lane_risk: str,
    signals: dict[str, object],
) -> dict[str, str]:
    escalation_level = str(signals["escalation_level"])
    if escalation_level == "high":
        return {
            "model_tier": MODEL_TIER_FRONTIER,
            "selected_model": policy.review_model,
            "selection_reason": (
                "Escalated bounded code writing to the frontier high-reasoning "
                f"tier for {_format_reason_list(_escalation_reasons(signals))}."
            ),
        }
    if escalation_level == "medium":
        return {
            "model_tier": MODEL_TIER_MID,
            "selected_model": policy.coordinator_model,
            "selection_reason": (
                "Escalated bounded code writing to the mid-tier Codex model "
                f"for {_format_reason_list(_escalation_reasons(signals))}."
            ),
        }
    if lane_risk == "low":
        return {
            "model_tier": MODEL_TIER_LOW,
            "selected_model": policy.worker_model,
            "selection_reason": (
                "Bounded, well-specified, low-risk code writing stays on the "
                "low-cost worker tier."
            ),
        }
    return {
        "model_tier": MODEL_TIER_LOW,
        "selected_model": policy.worker_model,
        "selection_reason": (
            "Bounded low-risk code writing defaults to the low-cost worker tier."
        ),
    }


def _selection_signal_summary(lane_signals) -> dict[str, object]:
    return {
        "repeated_failure": lane_signals.repeated_failure,
        "ambiguous_review": lane_signals.ambiguous_review,
        "cross_module_blast_radius": lane_signals.cross_module_blast_radius,
        "high_risk_files": lane_signals.high_risk_files,
        "bounded_context": lane_signals.bounded_context,
        "well_specified": lane_signals.well_specified,
        "downgrade_to_low_cost": lane_signals.downgrade_to_low_cost,
        "escalation_level": lane_signals.escalation_level,
        "escalation_reasons": list(lane_signals.escalation_reasons),
    }


def _has_selection_context(lane: Mapping[str, Any]) -> bool:
    if _explicit_risk(lane) is not None:
        return True
    if _changed_files(lane):
        return True
    if _positive_int(lane.get("retry_count")) > 0:
        return True
    if _positive_int(lane.get("review_retry_count")) > 0:
        return True
    if _optional_text(lane.get("review_summary")) is not None:
        return True
    if _optional_text(lane.get("review_decision")) is not None:
        return True
    if _bool_flag(lane, "bounded_context") or _bool_flag(lane, "well_specified"):
        return True
    return _task_type(lane) in {"mechanical_cleanup", "cleanup", "rename", "formatting"}


def _lane_risk_for_selection(
    lane: Mapping[str, Any],
    signals: dict[str, object],
) -> Literal["low", "medium", "high"]:
    explicit = _explicit_risk(lane)
    if explicit in {"low", "medium", "high"}:
        return explicit
    if bool(signals["downgrade_to_low_cost"]):
        return "low"
    if str(signals["escalation_level"]) == "high":
        return "high"
    if str(signals["escalation_level"]) == "medium":
        return "medium"
    return "medium"


def _escalation_reasons(signals: dict[str, object]) -> list[str]:
    value = signals.get("escalation_reasons")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _has_ambiguous_review_signal(lane: Mapping[str, Any]) -> bool:
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


def _has_high_risk_files(
    lane: Mapping[str, Any],
    changed_files: list[str],
) -> bool:
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
