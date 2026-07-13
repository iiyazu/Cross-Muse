"""Capability discovery and safe projection over native Codex App Server RPC."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from xmuse_core.agents.codex_native_contract import (
    CAPABILITY_IDS,
    CodexNativeContractError,
    NativeInvocation,
    build_native_invocation,
)

CAPABILITIES_SCHEMA = "room_codex_native_capabilities/v1"
SNAPSHOT_SCHEMA = "room_codex_native_snapshot/v1"
_GOAL_STATUSES = frozenset(
    {"active", "paused", "blocked", "usageLimited", "budgetLimited", "complete"}
)
_MAX_MODEL_PAGES = 32
_MAX_MODELS = 1_000


class NativeRpc(Protocol):
    async def request(self, method: str, params: Mapping[str, object]) -> object: ...


class CodexNativeAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class NativeModelCatalog:
    models: tuple[dict[str, object], ...]
    supported_efforts: Mapping[str, frozenset[str]]


@dataclass(frozen=True, slots=True)
class NativeInvokeResult:
    invocation: NativeInvocation
    safe_ack: dict[str, object]
    private_active_turn_id: str | None = None


class CodexNativeAdapter:
    def __init__(self, rpc: NativeRpc) -> None:
        self._rpc = rpc

    async def discover_capabilities(
        self,
        *,
        thread_id: str,
        session_guard: str,
    ) -> tuple[dict[str, object], NativeModelCatalog]:
        goal_available = True
        try:
            await self._rpc.request("thread/goal/get", {"threadId": thread_id})
        except Exception:
            goal_available = False
        try:
            catalog = await self.list_models()
            models_available = True
        except Exception:
            catalog = NativeModelCatalog((), {})
            models_available = False
        descriptors = []
        for capability_id in sorted(CAPABILITY_IDS):
            available = True
            if capability_id.startswith("goal_"):
                available = goal_available
            elif capability_id in {"settings_update", "models_list"}:
                available = models_available
            descriptors.append(
                {
                    "capability_id": capability_id,
                    "native_source": _method_for(capability_id),
                    "availability": "available" if available else "runtime_unsupported",
                    "disabled_reason": None if available else "codex_native_runtime_unsupported",
                    "session_guard": session_guard,
                }
            )
        return (
            {
                "schema_version": CAPABILITIES_SCHEMA,
                "source": "codex_app_server",
                "capabilities": descriptors,
            },
            catalog,
        )

    async def list_models(self) -> NativeModelCatalog:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        models: list[dict[str, object]] = []
        efforts: dict[str, frozenset[str]] = {}
        for _page in range(_MAX_MODEL_PAGES):
            params: dict[str, object] = {"includeHidden": False, "limit": 100}
            if cursor is not None:
                params["cursor"] = cursor
            response = await self._rpc.request("model/list", params)
            if not isinstance(response, Mapping) or not isinstance(response.get("data"), list):
                raise CodexNativeAdapterError("codex_native_model_schema_invalid")
            for raw in response["data"]:
                model = _safe_model(raw)
                if model is None:
                    continue
                model_id = str(model["id"])
                if model_id in efforts:
                    raise CodexNativeAdapterError("codex_native_model_duplicate")
                models.append(model)
                model_efforts = model["efforts"]
                if not isinstance(model_efforts, list):
                    raise CodexNativeAdapterError("codex_native_model_schema_invalid")
                efforts[model_id] = frozenset(str(item) for item in model_efforts)
                if len(models) > _MAX_MODELS:
                    raise CodexNativeAdapterError("codex_native_model_limit_exceeded")
            next_cursor = response.get("nextCursor")
            if next_cursor is None:
                return NativeModelCatalog(tuple(models), efforts)
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise CodexNativeAdapterError("codex_native_model_cursor_invalid")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise CodexNativeAdapterError("codex_native_model_page_limit_exceeded")

    async def snapshot(
        self,
        *,
        thread_id: str,
        session_identity: str,
        connection_generation: int,
        current_model: str | None,
        current_effort: str | None,
        active_turn_id: str | None,
    ) -> dict[str, object]:
        response = await self._rpc.request("thread/goal/get", {"threadId": thread_id})
        goal = _safe_goal(response)
        settings = {
            "model": _safe_text(current_model, 256),
            "effort": _safe_text(current_effort, 64),
        }
        session_guard = _digest({"session": session_identity, "generation": connection_generation})
        return {
            "schema_version": SNAPSHOT_SCHEMA,
            "source": "codex_app_server",
            "observed_at": _timestamp(),
            "goal": goal,
            "settings": settings,
            "active_turn": active_turn_id is not None,
            "guards": {
                "session": session_guard,
                "goal": _digest(goal),
                "settings": _digest(settings),
                "turn": _digest({"active": active_turn_id}) if active_turn_id else None,
            },
        }

    async def invoke(
        self,
        capability_id: str,
        safe_request: Mapping[str, object],
        *,
        thread_id: str,
        active_turn_id: str | None,
        current_model: str | None,
        current_effort: str | None,
        catalog: NativeModelCatalog,
        resolved_review_target: Mapping[str, object] | None = None,
    ) -> NativeInvokeResult:
        try:
            invocation = build_native_invocation(
                capability_id,
                safe_request,
                thread_id=thread_id,
                active_turn_id=active_turn_id,
                current_model=current_model,
                current_effort=current_effort,
                supported_models=catalog.supported_efforts,
                resolved_review_target=resolved_review_target,
            )
        except CodexNativeContractError as exc:
            raise CodexNativeAdapterError(exc.code) from exc
        response = await self._rpc.request(invocation.method, invocation.params)
        private_turn_id = (
            _response_turn_id(response) if capability_id == "console_turn_start" else None
        )
        return NativeInvokeResult(
            invocation=invocation,
            safe_ack={
                "native_method": invocation.method,
                "acknowledged": True,
            },
            private_active_turn_id=private_turn_id,
        )


def _safe_model(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping) or value.get("hidden") is True:
        return None
    model_id = _safe_text(value.get("id"), 256) or _safe_text(value.get("model"), 256)
    model_name = _safe_text(value.get("model"), 256) or model_id
    display = _safe_text(value.get("displayName"), 256) or model_name
    raw_efforts = value.get("supportedReasoningEfforts")
    if (
        model_id is None
        or model_name is None
        or display is None
        or not isinstance(raw_efforts, list)
    ):
        raise CodexNativeAdapterError("codex_native_model_schema_invalid")
    supported: list[str] = []
    for raw in raw_efforts:
        effort = raw.get("reasoningEffort") if isinstance(raw, Mapping) else None
        clean = _safe_text(effort, 64)
        if clean is not None and clean != "ultra" and clean not in supported:
            supported.append(clean)
    default = _safe_text(value.get("defaultReasoningEffort"), 64)
    if default == "ultra" or default not in supported:
        default = supported[0] if supported else None
    return {
        "id": model_id,
        "model": model_name,
        "display_name": display,
        "description": _safe_text(value.get("description"), 512),
        "is_default": value.get("isDefault") is True,
        "default_effort": default,
        "efforts": supported,
    }


def _safe_goal(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        raise CodexNativeAdapterError("codex_native_goal_schema_invalid")
    raw = value.get("goal")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise CodexNativeAdapterError("codex_native_goal_schema_invalid")
    status = raw.get("status")
    objective = _safe_text(raw.get("objective"), 4_096)
    if status not in _GOAL_STATUSES or objective is None:
        raise CodexNativeAdapterError("codex_native_goal_schema_invalid")
    token_budget = _safe_integer(raw.get("tokenBudget"))
    tokens_used = _safe_integer(raw.get("tokensUsed"))
    time_used = _safe_integer(raw.get("timeUsedSeconds"))
    return {
        "objective": objective,
        "status": status,
        "token_budget": token_budget,
        "tokens_used": tokens_used,
        "time_used_seconds": time_used,
    }


def _response_turn_id(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    turn = value.get("turn")
    return _safe_text(turn.get("id"), 512) if isinstance(turn, Mapping) else None


def _safe_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if not clean or len(clean.encode("utf-8")) > maximum:
        return None
    return clean


def _safe_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _method_for(capability_id: str) -> str:
    return {
        "goal_set": "thread/goal/set",
        "goal_pause": "thread/goal/set",
        "goal_resume": "thread/goal/set",
        "goal_get": "thread/goal/get",
        "goal_clear": "thread/goal/clear",
        "settings_update": "thread/settings/update",
        "models_list": "model/list",
        "console_turn_start": "turn/start",
        "turn_steer": "turn/steer",
        "turn_interrupt": "turn/interrupt",
        "compact_start": "thread/compact/start",
        "review_start": "review/start",
    }[capability_id]


__all__ = [
    "CAPABILITIES_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "CodexNativeAdapter",
    "CodexNativeAdapterError",
    "NativeInvokeResult",
    "NativeModelCatalog",
]
