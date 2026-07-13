"""Closed request builders for the Codex 0.144 native Room Console surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

CAPABILITY_IDS = frozenset(
    {
        "goal_set",
        "goal_pause",
        "goal_resume",
        "goal_get",
        "goal_clear",
        "settings_update",
        "models_list",
        "console_turn_start",
        "turn_steer",
        "turn_interrupt",
        "compact_start",
        "review_start",
    }
)
GOAL_TERMINAL_STATUSES = frozenset(
    {"paused", "blocked", "usageLimited", "budgetLimited", "complete"}
)
MAX_ACTION_TEXT_BYTES = 4_096


class CodexNativeContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class NativeInvocation:
    capability_id: str
    method: str
    params: dict[str, object]


def build_native_invocation(
    capability_id: str,
    safe_request: Mapping[str, object],
    *,
    thread_id: str,
    active_turn_id: str | None = None,
    current_model: str | None = None,
    current_effort: str | None = None,
    supported_models: Mapping[str, frozenset[str]] | None = None,
    resolved_review_target: Mapping[str, object] | None = None,
) -> NativeInvocation:
    """Rebuild one allowlisted native RPC payload without forwarding raw params."""

    capability = _capability(capability_id)
    native_thread = _required_text(thread_id, "codex_native_thread_unavailable", 512)
    request = normalize_native_safe_request(capability, safe_request)
    if capability == "goal_set":
        _exact_keys(request, {"objective", "token_budget"})
        goal_params = {
            "threadId": native_thread,
            "objective": _required_text(request.get("objective"), "codex_native_objective_invalid"),
            "tokenBudget": _bounded_integer(
                request.get("token_budget"), 10_000, 1_000_000, "codex_native_budget_invalid"
            ),
            "status": "active",
        }
        return NativeInvocation(capability, "thread/goal/set", goal_params)
    if capability in {"goal_pause", "goal_resume"}:
        _exact_keys(request, set())
        return NativeInvocation(
            capability,
            "thread/goal/set",
            {
                "threadId": native_thread,
                "status": "paused" if capability == "goal_pause" else "active",
            },
        )
    if capability in {"goal_get", "goal_clear", "compact_start", "models_list"}:
        _exact_keys(request, set())
        method = {
            "goal_get": "thread/goal/get",
            "goal_clear": "thread/goal/clear",
            "compact_start": "thread/compact/start",
            "models_list": "model/list",
        }[capability]
        read_params: dict[str, object] = (
            {"includeHidden": False, "limit": 100}
            if capability == "models_list"
            else {"threadId": native_thread}
        )
        return NativeInvocation(capability, method, read_params)
    if capability == "settings_update":
        _exact_keys(request, {"model", "effort"}, require_any=True)
        model = _optional_text(request.get("model"), "codex_native_model_invalid", 256)
        effort = _optional_text(request.get("effort"), "codex_native_effort_invalid", 64)
        if model is None and effort is None:
            raise CodexNativeContractError("codex_native_settings_empty")
        catalog = supported_models or {}
        selected_model = model or current_model
        if selected_model is None or selected_model not in catalog:
            raise CodexNativeContractError("codex_native_model_unsupported")
        if effort is not None and (
            effort == "ultra" or effort not in catalog.get(selected_model, frozenset())
        ):
            raise CodexNativeContractError("codex_native_effort_unsupported")
        settings_params: dict[str, object] = {"threadId": native_thread}
        if model is not None:
            settings_params["model"] = model
        if effort is not None:
            settings_params["effort"] = effort
        return NativeInvocation(capability, "thread/settings/update", settings_params)
    if capability == "console_turn_start":
        _exact_keys(request, {"text", "mode"})
        text = _required_text(request.get("text"), "codex_native_turn_text_invalid")
        mode = request.get("mode")
        if mode not in {"default", "plan"}:
            raise CodexNativeContractError("codex_native_turn_mode_invalid")
        turn_params = _safe_turn_params(native_thread, text)
        if mode == "plan":
            model = _required_text(current_model, "codex_native_model_unavailable", 256)
            effort = _optional_text(current_effort, "codex_native_effort_invalid", 64)
            turn_params["collaborationMode"] = {
                "mode": "plan",
                "settings": {
                    "model": model,
                    "reasoning_effort": effort,
                    "developer_instructions": None,
                },
            }
        return NativeInvocation(capability, "turn/start", turn_params)
    if capability == "turn_steer":
        _exact_keys(request, {"text"})
        turn_id = _required_text(active_turn_id, "codex_native_active_turn_required", 512)
        text = _required_text(request.get("text"), "codex_native_turn_text_invalid")
        return NativeInvocation(
            capability,
            "turn/steer",
            {
                "threadId": native_thread,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": text}],
            },
        )
    if capability == "turn_interrupt":
        _exact_keys(request, set())
        turn_id = _required_text(active_turn_id, "codex_native_active_turn_required", 512)
        return NativeInvocation(
            capability,
            "turn/interrupt",
            {"threadId": native_thread, "turnId": turn_id},
        )
    if capability == "review_start":
        _exact_keys(request, {"target"})
        target_kind = request.get("target")
        expected = (
            {
                "uncommitted": "uncommittedChanges",
                "base": "baseBranch",
                "commit": "commit",
            }.get(target_kind)
            if isinstance(target_kind, str)
            else None
        )
        if expected is None or resolved_review_target is None:
            raise CodexNativeContractError("codex_native_review_target_invalid")
        target = dict(resolved_review_target)
        if target.get("type") != expected or expected == "custom":
            raise CodexNativeContractError("codex_native_review_target_invalid")
        return NativeInvocation(
            capability,
            "review/start",
            {"threadId": native_thread, "target": target, "delivery": "inline"},
        )
    raise AssertionError("unreachable capability")


def normalize_native_safe_request(
    capability_id: str, safe_request: Mapping[str, object]
) -> dict[str, object]:
    """Validate and normalize the browser-safe shape without native identifiers."""

    capability = _capability(capability_id)
    request = dict(safe_request)
    if capability == "goal_set":
        _exact_keys(request, {"objective", "token_budget"})
        return {
            "objective": _required_text(
                request.get("objective"), "codex_native_objective_invalid"
            ),
            "token_budget": _bounded_integer(
                request.get("token_budget"),
                10_000,
                1_000_000,
                "codex_native_budget_invalid",
            ),
        }
    if capability in {
        "goal_pause",
        "goal_resume",
        "goal_get",
        "goal_clear",
        "models_list",
        "turn_interrupt",
        "compact_start",
    }:
        _exact_keys(request, set())
        return {}
    if capability == "settings_update":
        _exact_keys(request, {"model", "effort"}, require_any=True)
        normalized: dict[str, object] = {}
        if "model" in request:
            normalized["model"] = _required_text(
                request.get("model"), "codex_native_model_invalid", 256
            )
        if "effort" in request:
            effort = _required_text(
                request.get("effort"), "codex_native_effort_invalid", 64
            )
            if effort == "ultra":
                raise CodexNativeContractError("codex_native_effort_unsupported")
            normalized["effort"] = effort
        return normalized
    if capability == "console_turn_start":
        _exact_keys(request, {"text", "mode"})
        mode = request.get("mode")
        if mode not in {"default", "plan"}:
            raise CodexNativeContractError("codex_native_turn_mode_invalid")
        return {
            "text": _required_text(request.get("text"), "codex_native_turn_text_invalid"),
            "mode": mode,
        }
    if capability == "turn_steer":
        _exact_keys(request, {"text"})
        return {
            "text": _required_text(request.get("text"), "codex_native_turn_text_invalid")
        }
    if capability == "review_start":
        _exact_keys(request, {"target"})
        target = request.get("target")
        if target not in {"uncommitted", "base", "commit"}:
            raise CodexNativeContractError("codex_native_review_target_invalid")
        return {"target": target}
    raise AssertionError("unreachable capability")


def _safe_turn_params(thread_id: str, text: str) -> dict[str, object]:
    return {
        "threadId": thread_id,
        "input": [{"type": "text", "text": text}],
        "approvalPolicy": "never",
        "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        "summary": "concise",
    }


def _capability(value: object) -> str:
    if not isinstance(value, str) or value not in CAPABILITY_IDS:
        raise CodexNativeContractError("codex_native_capability_forbidden")
    return value


def _exact_keys(
    value: Mapping[str, object], allowed: set[str], *, require_any: bool = False
) -> None:
    if set(value) - allowed or (require_any and not value):
        raise CodexNativeContractError("codex_native_request_shape_invalid")


def _required_text(value: object, code: str, maximum: int = MAX_ACTION_TEXT_BYTES) -> str:
    text = _optional_text(value, code, maximum)
    if text is None:
        raise CodexNativeContractError(code)
    return text


def _optional_text(value: object, code: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CodexNativeContractError(code)
    text = value.strip()
    if not text or len(text.encode("utf-8")) > maximum:
        raise CodexNativeContractError(code)
    return text


def _bounded_integer(value: object, minimum: int, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CodexNativeContractError(code)
    return value


CapabilityAvailability = Literal[
    "available", "runtime_unsupported", "policy_disabled", "session_conflict"
]


__all__ = [
    "CAPABILITY_IDS",
    "GOAL_TERMINAL_STATUSES",
    "CapabilityAvailability",
    "CodexNativeContractError",
    "NativeInvocation",
    "build_native_invocation",
    "normalize_native_safe_request",
]
