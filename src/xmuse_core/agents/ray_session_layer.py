from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime


@dataclass
class LiveRayGodSession:
    record: GodSessionRecord
    actor: Any
    worktree: Path
    resumed_provider_session_id: str | None = None


RuntimeKey = AgentRuntime | str


class RayGodSessionLayer:
    """Ray-backed peer GOD sessions with the same surface as GodSessionLayer."""

    def __init__(
        self,
        *,
        registry_path: Path,
        db_path: Path,
        launchers: dict[RuntimeKey, object],
        actor_factory: Callable[..., Any] | None = None,
        transport_mode: str | None = None,
        reasoning_effort: str | None = None,
        enable_mcp: bool | None = None,
    ) -> None:
        self._registry = GodSessionRegistry(registry_path)
        self._db_path = db_path
        self._launchers = launchers
        self._actor_factory = actor_factory
        self._transport_mode = transport_mode or _ray_god_transport_mode()
        self._reasoning_effort = reasoning_effort or _ray_god_reasoning_effort()
        self._enable_mcp = _ray_god_mcp_enabled() if enable_mcp is None else enable_mcp
        self._live_sessions: dict[str, LiveRayGodSession] = {}

    async def prewarm(self) -> None:
        actor = self._build_actor(
            god_id="god-ray-prewarm",
            role="prewarm",
            display_name="Ray Prewarm GOD",
            model="",
            command=[sys.executable, "-c", "import time; time.sleep(300)"],
            db_path=str(self._db_path),
            worktree=str(self._db_path.parent),
            transport_mode="process",
        )
        try:
            await _call_actor(actor, "ensure_alive")
        finally:
            await _call_actor(actor, "shutdown")

    async def ensure_conversation_session(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        role: str,
        agent: AgentDescriptor,
        worktree: Path,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        feature_scope_id: str | None = None,
    ) -> GodSessionRecord:
        live = self._find_live_session_by_conversation_participant(
            conversation_id,
            participant_id,
        )
        if live is not None and await _actor_alive(live.actor):
            await self._refresh_provider_binding(live)
            return live.record

        try:
            record = self._registry.find_by_conversation_participant(
                conversation_id,
                participant_id,
            )
        except KeyError:
            session_address, session_inbox_id = build_conversation_session_identity(
                conversation_id=conversation_id,
                participant_id=participant_id,
            )
            record = self._registry.create(
                role=role,
                agent_name=agent.name,
                runtime=_runtime_value(agent.runtime),
                session_address=session_address,
                session_inbox_id=session_inbox_id,
                conversation_id=conversation_id,
                participant_id=participant_id,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=str(worktree),
                feature_scope_id=feature_scope_id,
            )

        actor, resumed_provider_session_id = self._spawn_actor(
            record=record,
            role=role,
            display_name=agent.name,
            runtime=agent.runtime,
            worktree=worktree,
            model=model,
        )
        await _call_actor(actor, "ensure_alive")
        live = LiveRayGodSession(
            record=record,
            actor=actor,
            worktree=worktree,
            resumed_provider_session_id=resumed_provider_session_id,
        )
        await self._refresh_provider_binding(live)
        self._live_sessions[record.god_session_id] = live
        return record

    async def send_message(
        self,
        god_session_id: str,
        message_type: str,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None:
        live = self._live_sessions.get(god_session_id)
        if live is None:
            raise RuntimeError(
                f"god_session_id '{god_session_id}' is registered but has no live Ray actor"
            )
        payload: dict[str, Any] = {
            "god_session_id": god_session_id,
            "prompt": prompt,
            "context": context,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        try:
            await _call_actor(live.actor, "send_typed", message_type, **payload)
        except Exception as exc:
            if not await self._retry_send_after_resume_failure(
                live,
                message_type=message_type,
                payload=payload,
                failure=exc,
            ):
                raise
            return
        await self._refresh_provider_binding(live)

    async def receive_message(self, god_session_id: str):
        live = self._live_sessions.get(god_session_id)
        if live is None:
            raise RuntimeError(
                f"god_session_id '{god_session_id}' is registered but has no live Ray actor"
            )
        message = await _call_actor(live.actor, "receive")
        await self._refresh_provider_binding(live)
        return message

    async def abort_session(self, god_session_id: str) -> None:
        live = self._live_sessions.pop(god_session_id, None)
        if live is None:
            return
        await _call_actor(live.actor, "shutdown")

    async def shutdown(self) -> None:
        live_sessions = list(self._live_sessions.values())
        self._live_sessions.clear()
        for live in live_sessions:
            await _call_actor(live.actor, "shutdown")

    def persistent_model_for_runtime(self, runtime: AgentRuntime | str) -> str | None:
        launcher = _find_launcher_for_runtime(self._launchers, runtime)
        return _persistent_model(launcher)

    def _find_live_session_by_conversation_participant(
        self,
        conversation_id: str,
        participant_id: str,
    ) -> LiveRayGodSession | None:
        for live in reversed(list(self._live_sessions.values())):
            if (
                live.record.conversation_id == conversation_id
                and live.record.participant_id == participant_id
            ):
                return live
        return None

    def _build_actor(self, **kwargs):
        if self._actor_factory is not None:
            return self._actor_factory(**kwargs)
        from xmuse_core.agents.ray_god_actor import RayGodActor

        ray = importlib.import_module("ray")
        if not ray.is_initialized():
            ray.init(
                ignore_reinit_error=True,
                include_dashboard=False,
                log_to_driver=False,
            )
        return RayGodActor.remote(**kwargs)

    def _spawn_actor(
        self,
        *,
        record: GodSessionRecord,
        role: str,
        display_name: str,
        runtime: RuntimeKey,
        worktree: Path,
        model: str | None,
        resume_thread_id: str | None = None,
    ) -> tuple[Any, str | None]:
        launcher = _launcher_for_runtime(self._launchers, runtime)
        command = _build_persistent_command(launcher, role, worktree)
        resumed_provider_session_id = (
            resume_thread_id
            if resume_thread_id is not None
            else _active_provider_session_id(record)
        )
        actor_kwargs = {
            "god_id": record.god_session_id,
            "role": role,
            "display_name": display_name,
            "model": model or record.model or _persistent_model(launcher) or "",
            "command": command,
            "db_path": str(self._db_path),
            "worktree": str(worktree),
            "transport_mode": self._transport_mode,
            "mcp_port": _persistent_mcp_port(launcher, command),
            "codex_command": _persistent_codex_command(launcher),
            "reasoning_effort": self._reasoning_effort,
            "enable_mcp": self._enable_mcp,
        }
        if resumed_provider_session_id is not None:
            actor_kwargs["resume_thread_id"] = resumed_provider_session_id
        return self._build_actor(**actor_kwargs), resumed_provider_session_id

    async def _refresh_provider_binding(self, live: LiveRayGodSession) -> None:
        info = await _call_actor(live.actor, "get_info")
        if not isinstance(info, dict):
            return
        thread_id = info.get("thread_id")
        transport = info.get("transport")
        if not isinstance(thread_id, str) or not thread_id.strip():
            return
        if transport != "codex-app-server":
            return
        updated = self._registry.update_provider_binding(
            live.record.god_session_id,
            provider_session_id=thread_id.strip(),
            provider_session_kind="codex_app_server_thread",
            provider_binding_status="active",
            provider_binding_failure_reason=None,
        )
        live.record = updated

    async def _retry_send_after_resume_failure(
        self,
        live: LiveRayGodSession,
        *,
        message_type: str,
        payload: dict[str, object],
        failure: Exception,
    ) -> bool:
        if live.resumed_provider_session_id is None:
            return False
        updated = self._registry.update_provider_binding(
            live.record.god_session_id,
            provider_session_id=None,
            provider_session_kind=live.record.provider_session_kind,
            provider_binding_status="stale",
            provider_binding_failure_reason=str(failure),
        )
        live.record = updated
        await _call_actor(live.actor, "shutdown")
        fallback_actor, _ = self._spawn_actor(
            record=live.record,
            role=live.record.role,
            display_name=live.record.agent_name,
            runtime=live.record.runtime,
            worktree=live.worktree,
            model=live.record.model,
            resume_thread_id=None,
        )
        await _call_actor(fallback_actor, "ensure_alive")
        live.actor = fallback_actor
        live.resumed_provider_session_id = None
        self._live_sessions[live.record.god_session_id] = live
        await _call_actor(live.actor, "send_typed", message_type, **payload)
        await self._refresh_provider_binding(live)
        return True


def _build_persistent_command(launcher: object, role: str, worktree: Path) -> list[str]:
    builder = getattr(launcher, "build_persistent_command", None)
    if not callable(builder):
        raise RuntimeError("persistent launcher is missing build_persistent_command")
    return list(builder(role, worktree))


def _runtime_value(runtime: RuntimeKey) -> str:
    return runtime.value if isinstance(runtime, AgentRuntime) else str(runtime)


def _find_launcher_for_runtime(
    launchers: dict[RuntimeKey, object],
    runtime: RuntimeKey,
) -> object | None:
    if runtime in launchers:
        return launchers[runtime]
    runtime_value = _runtime_value(runtime)
    return launchers.get(runtime_value)


def _launcher_for_runtime(
    launchers: dict[RuntimeKey, object],
    runtime: RuntimeKey,
) -> object:
    launcher = _find_launcher_for_runtime(launchers, runtime)
    if launcher is None:
        raise KeyError(_runtime_value(runtime))
    return launcher


def _persistent_model(launcher: object | None) -> str | None:
    if launcher is None:
        return None
    getter = getattr(launcher, "persistent_model", None)
    if callable(getter):
        value = getter()
        return value if isinstance(value, str) and value.strip() else None
    value = getattr(launcher, "model", None)
    return value if isinstance(value, str) and value.strip() else None


def _persistent_mcp_port(launcher: object | None, command: list[str]) -> int:
    value = getattr(launcher, "mcp_port", None)
    if isinstance(value, int):
        return value
    for index, item in enumerate(command):
        if item == "--mcp-port" and index + 1 < len(command):
            try:
                return int(command[index + 1])
            except ValueError:
                return 8100
    return 8100


def _persistent_codex_command(launcher: object | None) -> str:
    adapter = getattr(launcher, "provider_adapter", None)
    value = getattr(adapter, "codex_command", None)
    return value if isinstance(value, str) and value.strip() else "codex"


def _active_provider_session_id(record: GodSessionRecord) -> str | None:
    if record.provider_binding_status != "active":
        return None
    if record.provider_session_kind != "codex_app_server_thread":
        return None
    value = record.provider_session_id
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _ray_god_transport_mode() -> str:
    value = os.environ.get("XMUSE_RAY_GOD_TRANSPORT", "app-server")
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"app-server", "appserver", "codex-app-server"}:
        return "app-server"
    if normalized in {"process", "process-json", "batch", "codex-persistent"}:
        return "process"
    return "app-server"


def _ray_god_reasoning_effort() -> str:
    value = os.environ.get("XMUSE_RAY_GOD_EFFORT", "low")
    normalized = value.strip().lower()
    if normalized in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        return normalized
    return "low"


def _ray_god_mcp_enabled() -> bool:
    value = os.environ.get("XMUSE_RAY_GOD_MCP", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


async def _actor_alive(actor: Any) -> bool:
    info = await _call_actor(actor, "get_info")
    return bool(isinstance(info, dict) and info.get("alive"))


async def _call_actor(actor: Any, method_name: str, *args, **kwargs):
    method = getattr(actor, method_name)
    remote = getattr(method, "remote", None)
    result = remote(*args, **kwargs) if callable(remote) else method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    if _looks_like_ray_object_ref(result):
        ray = importlib.import_module("ray")
        return await asyncio.to_thread(ray.get, result)
    return result


def _looks_like_ray_object_ref(value: Any) -> bool:
    return type(value).__name__ == "ObjectRef" and hasattr(value, "hex")


__all__ = ["RayGodSessionLayer"]
