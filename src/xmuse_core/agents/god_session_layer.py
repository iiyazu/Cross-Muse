from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from inspect import Parameter, isawaitable, signature
from pathlib import Path
from typing import Never

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.agents.session import AgentSession, LocalSession
from xmuse_core.chat.participant_store import INIT_GOD_ROLE


@dataclass
class LiveGodSession:
    record: GodSessionRecord
    session: AgentSession
    worktree: Path


RuntimeKey = AgentRuntime | str
_UNSET = object()


class GodSessionLayer:
    def __init__(self, registry_path: Path, launchers: dict[RuntimeKey, object]) -> None:
        self._db_path = registry_path.parent / "chat.db"
        self._registry = GodSessionRegistry(registry_path)
        self._launchers = launchers
        self._live_sessions: dict[str, LiveGodSession] = {}
        self._pending_conversation_sessions: dict[
            tuple[str, str, str | None, str, str, str, str | None, str | None, str],
            asyncio.Task[GodSessionRecord],
        ] = {}

    async def ensure_session(
        self,
        role: str,
        agent: AgentDescriptor,
        worktree: Path,
    ) -> GodSessionRecord:
        live = self._find_live_session_by_role(role)
        if live is not None:
            self._assert_session_shape_matches(live, agent, worktree)
            if live.session.is_alive():
                return live.record

        runtime = _runtime_value(agent.runtime)
        launcher = _launcher_for_runtime(self._launchers, agent.runtime)
        _assert_launcher_supports_persistent_sessions(launcher, runtime)
        session = await _spawn_persistent_session(
            launcher,
            role=role,
            worktree=worktree,
            provider_session_id=(
                _active_provider_session_id(live.record) if live is not None else None
            ),
            db_path=self._db_path,
        )
        if live is not None:
            record = await self._promote_running_record(live.record, session)
            self._live_sessions[live.record.god_session_id] = LiveGodSession(
                record=record,
                session=session,
                worktree=worktree,
            )
            return record
        record = self._registry.create(
            role=role,
            agent_name=agent.name,
            runtime=runtime,
            session_address=f"@{role}",
            session_inbox_id=f"inbox-{role}",
        )
        record = await self._promote_running_record(record, session)
        self._live_sessions[record.god_session_id] = LiveGodSession(
            record=record,
            session=session,
            worktree=worktree,
        )
        return record

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
        pending_key = _conversation_session_pending_key(
            conversation_id=conversation_id,
            participant_id=participant_id,
            role=role,
            agent=agent,
            worktree=worktree,
            model=model,
            prompt_fingerprint=prompt_fingerprint,
            feature_scope_id=feature_scope_id,
        )
        pending = self._pending_conversation_sessions.get(pending_key)
        if pending is not None:
            return await pending
        task = asyncio.create_task(
            self._ensure_conversation_session_uncached(
                conversation_id=conversation_id,
                participant_id=participant_id,
                role=role,
                agent=agent,
                worktree=worktree,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                feature_scope_id=feature_scope_id,
            )
        )
        self._pending_conversation_sessions[pending_key] = task
        try:
            return await task
        finally:
            if self._pending_conversation_sessions.get(pending_key) is task:
                self._pending_conversation_sessions.pop(pending_key, None)

    async def _ensure_conversation_session_uncached(
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
            feature_scope_id=feature_scope_id,
        )
        if live is not None:
            if self._record_peer_metadata_can_migrate(
                live.record,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            ):
                await live.session.abort()
                self._live_sessions.pop(live.record.god_session_id, None)
                self._registry.update_peer_metadata(
                    live.record.god_session_id,
                    **_merged_peer_metadata(
                        live.record,
                        model=model,
                        prompt_fingerprint=prompt_fingerprint,
                        worktree=worktree,
                        feature_scope_id=feature_scope_id,
                    ),
                )
                live = None
            else:
                if not self._session_identity_matches(
                    live,
                    role,
                    agent,
                    model=model,
                    prompt_fingerprint=prompt_fingerprint,
                    worktree=worktree,
                    feature_scope_id=feature_scope_id,
                ):
                    self._raise_session_shape_mismatch(live)
                if live.worktree != worktree:
                    self._raise_session_shape_mismatch(live)
                if live.session.is_alive():
                    return live.record

        if live is not None:
            runtime = _runtime_value(agent.runtime)
            launcher = _launcher_for_runtime(self._launchers, agent.runtime)
            _assert_launcher_supports_persistent_sessions(launcher, runtime)
            session = await _spawn_persistent_session(
                launcher,
                role=role,
                worktree=worktree,
                model=live.record.model,
                provider_session_id=_active_provider_session_id(live.record),
                db_path=self._db_path,
            )
            record = await self._promote_running_record(live.record, session)
            self._live_sessions[live.record.god_session_id] = LiveGodSession(
                record=record,
                session=session,
                worktree=worktree,
            )
            return record

        try:
            record = self._registry.find_by_conversation_participant(
                conversation_id,
                participant_id,
                feature_scope_id=feature_scope_id,
            )
        except KeyError:
            migrated = self._record_for_feature_scope_migration(
                conversation_id=conversation_id,
                participant_id=participant_id,
                role=role,
                agent=agent,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            )
            if migrated is None:
                record = self._create_conversation_record(
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    role=role,
                    agent=agent,
                    model=model,
                    prompt_fingerprint=prompt_fingerprint,
                    worktree=worktree,
                    feature_scope_id=feature_scope_id,
                )
            else:
                record = migrated
                record = self._registry.update_peer_metadata(
                    record.god_session_id,
                    **_merged_peer_metadata(
                        record,
                        model=model,
                        prompt_fingerprint=prompt_fingerprint,
                        worktree=worktree,
                        feature_scope_id=feature_scope_id,
                    ),
                )
                self._assert_record_shape_matches(
                    record,
                    role,
                    agent,
                    model=model,
                    prompt_fingerprint=prompt_fingerprint,
                    worktree=worktree,
                    feature_scope_id=feature_scope_id,
                )
        else:
            if self._record_peer_metadata_can_migrate(
                record,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            ):
                record = self._registry.update_peer_metadata(
                    record.god_session_id,
                    **_merged_peer_metadata(
                        record,
                        model=model,
                        prompt_fingerprint=prompt_fingerprint,
                        worktree=worktree,
                        feature_scope_id=feature_scope_id,
                    ),
                )
            self._assert_record_shape_matches(
                record,
                role,
                agent,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            )

        runtime = _runtime_value(agent.runtime)
        launcher = _launcher_for_runtime(self._launchers, agent.runtime)
        _assert_launcher_supports_persistent_sessions(launcher, runtime)
        session = await _spawn_persistent_session(
            launcher,
            role=role,
            worktree=worktree,
            model=record.model,
            provider_session_id=_active_provider_session_id(record),
            db_path=self._db_path,
        )
        record = await self._promote_running_record(record, session)
        self._live_sessions[record.god_session_id] = LiveGodSession(
            record=record,
            session=session,
            worktree=worktree,
        )
        return record

    async def _promote_running_record(
        self,
        record: GodSessionRecord,
        session: AgentSession,
    ) -> GodSessionRecord:
        try:
            is_codex = record.runtime == AgentRuntime.CODEX.value
            provider_session_id = _live_provider_session_id(session) if is_codex else None
            if provider_session_id is not None:
                self._raise_if_cross_room_provider_thread(
                    provider_session_id,
                    god_session_id=record.god_session_id,
                )
                self._registry.update_provider_binding(
                    record.god_session_id,
                    provider_session_id=provider_session_id,
                    provider_session_kind="codex_app_server_thread",
                    provider_binding_status="active",
                    provider_binding_failure_reason=None,
                )
            return self._registry.promote_running(
                record.god_session_id,
                pid=_session_pid(session),
            )
        except Exception as error:
            try:
                await session.abort()
            except Exception as cleanup_error:
                error.add_note(f"session abort failed: {cleanup_error}")
            raise

    async def ensure_init_session(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        agent: AgentDescriptor,
        worktree: Path,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
    ) -> GodSessionRecord:
        self._assert_init_session_identity(conversation_id, participant_id)
        return await self.ensure_conversation_session(
            conversation_id=conversation_id,
            participant_id=participant_id,
            role=INIT_GOD_ROLE,
            agent=agent,
            worktree=worktree,
            model=model,
            prompt_fingerprint=prompt_fingerprint,
        )

    def record_prompt_contract(
        self,
        god_session_id: str,
        *,
        prompt_contract_version: str | None,
        prompt_layer_order: list[str] | None,
        prompt_layer_hashes: dict[str, str] | None,
        prompt_artifact_fingerprint: str | None,
    ) -> GodSessionRecord:
        record = self._registry.update_prompt_contract(
            god_session_id,
            prompt_contract_version=prompt_contract_version,
            prompt_layer_order=prompt_layer_order,
            prompt_layer_hashes=prompt_layer_hashes,
            prompt_artifact_fingerprint=prompt_artifact_fingerprint,
        )
        live = self._live_sessions.get(god_session_id)
        if live is not None:
            self._live_sessions[god_session_id] = LiveGodSession(
                record=record,
                session=live.session,
                worktree=live.worktree,
            )
        return record

    def _create_conversation_record(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        role: str,
        agent: AgentDescriptor,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        worktree: Path | None = None,
        feature_scope_id: str | None = None,
    ) -> GodSessionRecord:
        session_address, session_inbox_id = build_conversation_session_identity(
            conversation_id=conversation_id,
            participant_id=participant_id,
            feature_scope_id=feature_scope_id,
        )
        return self._registry.create(
            role=role,
            agent_name=agent.name,
            runtime=_runtime_value(agent.runtime),
            session_address=session_address,
            session_inbox_id=session_inbox_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            model=model,
            prompt_fingerprint=prompt_fingerprint,
            worktree=str(worktree) if worktree is not None else None,
            feature_scope_id=feature_scope_id,
        )

    def _record_for_feature_scope_migration(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        role: str,
        agent: AgentDescriptor,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        worktree: Path | None = None,
        feature_scope_id: str | None = None,
    ) -> GodSessionRecord | None:
        if feature_scope_id is None:
            return None
        try:
            record = self._registry.find_by_conversation_participant(
                conversation_id,
                participant_id,
            )
        except KeyError:
            return None
        if record.feature_scope_id is not None:
            return None
        if (
            record.role != role
            or record.agent_name != agent.name
            or record.runtime != _runtime_value(agent.runtime)
        ):
            return None
        if not self._record_peer_metadata_can_migrate(
            record,
            model=model,
            prompt_fingerprint=prompt_fingerprint,
            worktree=worktree,
            feature_scope_id=feature_scope_id,
        ):
            return None
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
            try:
                self._registry.get(god_session_id)
            except KeyError as exc:
                raise LookupError(f"Unknown god_session_id: {god_session_id}") from exc
            raise RuntimeError(
                f"god_session_id '{god_session_id}' is registered but has no live "
                "transport attached in this process"
            )
        payload = {
            "god_session_id": god_session_id,
            "prompt": prompt,
            "context": context,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        await live.session.send_typed(message_type, **payload)

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None:
        live = self._live_sessions.get(god_session_id)
        if live is None:
            try:
                self._registry.get(god_session_id)
            except KeyError as exc:
                raise LookupError(f"Unknown god_session_id: {god_session_id}") from exc
            raise RuntimeError(
                f"god_session_id '{god_session_id}' is registered but has no live "
                "transport attached in this process"
            )
        message = await live.session.receive()
        self._persist_provider_binding_from_message(live, message)
        return message

    async def abort_session(self, god_session_id: str) -> None:
        live = self._live_sessions.get(god_session_id)
        if live is None:
            return
        await live.session.abort()
        self._live_sessions.pop(god_session_id, None)

    async def shutdown(self) -> None:
        """Stop pending starts and every transport owned by this process."""

        pending = list(self._pending_conversation_sessions.values())
        self._pending_conversation_sessions.clear()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        live = list(self._live_sessions.values())
        self._live_sessions.clear()
        if live:
            await asyncio.gather(
                *(item.session.abort() for item in live),
                return_exceptions=True,
            )

    def require_live_provider_session_binding(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        runtime: AgentRuntime | str,
        provider_session_kind: str,
        feature_scope_id: str | None,
    ) -> GodSessionRecord:
        records = [
            record
            for record in self._registry.list()
            if (record.conversation_id, record.participant_id, record.feature_scope_id)
            == (conversation_id, participant_id, feature_scope_id)
        ]
        if not records:
            _raise_provider_binding("provider_session_binding_not_found")
        if len(records) != 1:
            _raise_provider_binding("provider_session_binding_ambiguous")
        record = records[0]
        if record.runtime != _runtime_value(runtime):
            _raise_provider_binding("provider_session_binding_identity_mismatch")
        live = self._live_sessions.get(record.god_session_id)
        if live is None:
            _raise_provider_binding("provider_session_binding_not_live")
        fields = "god_session_id conversation_id participant_id runtime feature_scope_id".split()
        if any(getattr(live.record, name) != getattr(record, name) for name in fields):
            _raise_provider_binding("provider_session_binding_identity_mismatch")
        provider_session_id = _active_provider_binding_id(record, provider_session_kind)
        if record.status != "running" or provider_session_id is None:
            _raise_provider_binding("provider_session_binding_inactive")
        if not live.session.is_alive():
            _raise_provider_binding("provider_session_binding_not_live")
        if _live_provider_session_id(live.session) != provider_session_id:
            _raise_provider_binding("provider_session_binding_stale")
        self._raise_if_cross_room_provider_thread(
            provider_session_id,
            god_session_id=record.god_session_id,
        )
        return record

    def persistent_model_for_runtime(self, runtime: AgentRuntime | str) -> str | None:
        launcher = _find_launcher_for_runtime(self._launchers, runtime)
        if launcher is None:
            return None
        model_getter = getattr(launcher, "persistent_model", None)
        if callable(model_getter):
            value = model_getter()
            return value if isinstance(value, str) and value.strip() else None
        value = getattr(launcher, "model", None)
        return value if isinstance(value, str) and value.strip() else None

    def _find_live_session_by_role(self, role: str) -> LiveGodSession | None:
        for live in reversed(list(self._live_sessions.values())):
            if live.record.role == role:
                return live
        return None

    def _find_live_session_by_conversation_participant(
        self,
        conversation_id: str,
        participant_id: str,
        feature_scope_id: str | None | object = _UNSET,
    ) -> LiveGodSession | None:
        for live in reversed(list(self._live_sessions.values())):
            if (
                live.record.conversation_id == conversation_id
                and live.record.participant_id == participant_id
                and (feature_scope_id is _UNSET or live.record.feature_scope_id == feature_scope_id)
            ):
                return live
        return None

    def _find_live_session_by_conversation_role(
        self,
        conversation_id: str,
        role: str,
    ) -> LiveGodSession | None:
        for live in reversed(list(self._live_sessions.values())):
            if live.record.conversation_id == conversation_id and live.record.role == role:
                return live
        return None

    def _assert_init_session_identity(
        self,
        conversation_id: str,
        participant_id: str,
    ) -> None:
        live = self._find_live_session_by_conversation_role(
            conversation_id,
            INIT_GOD_ROLE,
        )
        if live is not None and live.record.participant_id != participant_id:
            raise RuntimeError(
                "Cannot reuse init GOD identity: existing init GOD identity "
                "does not match requested participant_id"
            )
        try:
            record = self._registry.find_by_conversation_role(
                conversation_id,
                INIT_GOD_ROLE,
            )
        except KeyError:
            return
        if record.participant_id != participant_id:
            raise RuntimeError(
                "Cannot reuse init GOD identity: existing init GOD identity "
                "does not match requested participant_id"
            )

    def _assert_session_shape_matches(
        self,
        live: LiveGodSession,
        agent: AgentDescriptor,
        worktree: Path,
    ) -> None:
        if (
            not self._session_identity_matches(live, live.record.role, agent)
            or live.worktree != worktree
        ):
            self._raise_session_shape_mismatch(live)

    def _session_identity_matches(
        self,
        live: LiveGodSession,
        role: str,
        agent: AgentDescriptor,
        *,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        worktree: Path | None = None,
        feature_scope_id: str | None = None,
    ) -> bool:
        return (
            live.record.role == role
            and live.record.agent_name == agent.name
            and live.record.runtime == _runtime_value(agent.runtime)
            and self._record_peer_metadata_matches(
                live.record,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            )
        )

    def _raise_session_shape_mismatch(self, live: LiveGodSession) -> None:
        raise RuntimeError(
            f"Cannot reuse role='{live.record.role}': existing live session does "
            "not match requested agent/worktree"
        )

    def _assert_record_shape_matches(
        self,
        record: GodSessionRecord,
        role: str,
        agent: AgentDescriptor,
        *,
        model: str | None = None,
        prompt_fingerprint: str | None = None,
        worktree: Path | None = None,
        feature_scope_id: str | None = None,
    ) -> None:
        if (
            record.role != role
            or record.agent_name != agent.name
            or record.runtime != _runtime_value(agent.runtime)
            or not self._record_peer_metadata_matches(
                record,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            )
        ):
            raise RuntimeError(
                "Cannot reuse conversation participant "
                f"'{record.conversation_id}:{record.participant_id}': "
                "existing registered session does not match requested role/agent"
            )

    def _record_peer_metadata_matches(
        self,
        record: GodSessionRecord,
        *,
        model: str | None,
        prompt_fingerprint: str | None,
        worktree: Path | None,
        feature_scope_id: str | None,
    ) -> bool:
        compares_peer_metadata = any(
            value is not None
            for value in (
                model,
                prompt_fingerprint,
                feature_scope_id,
                record.model,
                record.prompt_fingerprint,
                record.worktree,
                record.feature_scope_id,
            )
        )
        expected_worktree = (
            str(worktree) if compares_peer_metadata and worktree is not None else None
        )
        return (
            _compatible_optional(record.model, model)
            and _compatible_optional(record.prompt_fingerprint, prompt_fingerprint)
            and _compatible_optional(record.worktree, expected_worktree)
            and _compatible_optional(record.feature_scope_id, feature_scope_id)
        )

    def _record_peer_metadata_can_migrate(
        self,
        record: GodSessionRecord,
        *,
        model: str | None,
        prompt_fingerprint: str | None,
        worktree: Path | None,
        feature_scope_id: str | None,
    ) -> bool:
        expected_worktree = str(worktree) if worktree is not None else None
        pairs = (
            (record.model, model),
            (record.prompt_fingerprint, prompt_fingerprint),
            (record.worktree, expected_worktree),
            (record.feature_scope_id, feature_scope_id),
        )
        if any(
            existing is not None and expected is not None and existing != expected
            for existing, expected in pairs
        ):
            return False
        return any(existing is None and expected is not None for existing, expected in pairs)

    def _persist_provider_binding_from_message(
        self,
        live: LiveGodSession,
        message: object,
    ) -> None:
        provider_session_id = _provider_session_id_from_message(
            live.record,
            message,
        )
        if provider_session_id is None:
            return
        self._raise_if_cross_room_provider_thread(
            provider_session_id,
            god_session_id=live.record.god_session_id,
        )
        if (
            live.record.provider_session_id == provider_session_id
            and live.record.provider_session_kind == "codex_app_server_thread"
            and live.record.provider_binding_status == "active"
            and live.record.provider_binding_failure_reason is None
        ):
            return
        record = self._registry.update_provider_binding(
            live.record.god_session_id,
            provider_session_id=provider_session_id,
            provider_session_kind="codex_app_server_thread",
            provider_binding_status="active",
            provider_binding_failure_reason=None,
        )
        self._live_sessions[live.record.god_session_id] = LiveGodSession(
            record=record,
            session=live.session,
            worktree=live.worktree,
        )

    def _raise_if_cross_room_provider_thread(
        self,
        provider_session_id: str,
        *,
        god_session_id: str,
    ) -> None:
        for record in self._registry.list():
            if record.god_session_id == god_session_id:
                continue
            if (
                _active_provider_binding_id(record, "codex_app_server_thread")
                == provider_session_id
            ):
                _raise_provider_binding("provider_session_binding_cross_room")


def _runtime_value(runtime: RuntimeKey) -> str:
    return runtime.value if isinstance(runtime, AgentRuntime) else str(runtime)


def _conversation_session_pending_key(
    *,
    conversation_id: str,
    participant_id: str,
    role: str,
    agent: AgentDescriptor,
    worktree: Path,
    model: str | None,
    prompt_fingerprint: str | None,
    feature_scope_id: str | None,
) -> tuple[str, str, str | None, str, str, str, str | None, str | None, str]:
    return (
        conversation_id,
        participant_id,
        feature_scope_id,
        role,
        agent.name,
        _runtime_value(agent.runtime),
        model,
        prompt_fingerprint,
        str(worktree),
    )


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


def _assert_launcher_supports_persistent_sessions(
    launcher: object,
    runtime: str,
) -> None:
    if getattr(launcher, "supports_persistent_sessions", False) is True and (
        callable(getattr(launcher, "spawn_persistent_session", None))
        or callable(getattr(launcher, "build_persistent_command", None))
    ):
        return
    raise RuntimeError(
        f"agent runtime '{runtime}' does not support xmuse persistent sessions; "
        "use one-shot execution/review fallback"
    )


def build_conversation_session_identity(
    *,
    conversation_id: str,
    participant_id: str,
    feature_scope_id: str | None = None,
) -> tuple[str, str]:
    short_conv = conversation_id.replace("conv_", "")[:12]
    address_scope_suffix, inbox_scope_suffix = _feature_scope_identity_suffixes(feature_scope_id)
    return (
        f"@conv_{short_conv}:{participant_id}{address_scope_suffix}",
        f"inbox-{conversation_id}-{participant_id}{inbox_scope_suffix}",
    )


def _feature_scope_identity_suffixes(feature_scope_id: str | None) -> tuple[str, str]:
    if feature_scope_id is None:
        return "", ""
    cleaned = feature_scope_id.strip()
    if not cleaned:
        return "", ""
    fragment = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in cleaned
    ).strip("-")
    digest = sha256(cleaned.encode("utf-8")).hexdigest()[:10]
    suffix = f"feature-{(fragment or 'scope')[:48]}-{digest}"
    return f":{suffix}", f"-{suffix}"


def _compatible_optional(existing: str | None, expected: str | None) -> bool:
    if existing is None and expected is None:
        return True
    if existing is None or expected is None:
        return False
    return existing == expected


def _merged_peer_metadata(
    record: GodSessionRecord,
    *,
    model: str | None,
    prompt_fingerprint: str | None,
    worktree: Path | None,
    feature_scope_id: str | None,
) -> dict[str, str | None]:
    return {
        "model": model if model is not None else record.model,
        "prompt_fingerprint": (
            prompt_fingerprint if prompt_fingerprint is not None else record.prompt_fingerprint
        ),
        "worktree": str(worktree) if worktree is not None else record.worktree,
        "feature_scope_id": (
            feature_scope_id if feature_scope_id is not None else record.feature_scope_id
        ),
    }


def _build_persistent_command(
    launcher: object,
    role: str,
    worktree: Path,
    *,
    model: str | None = None,
    provider_session_id: str | None = None,
) -> list[str]:
    builder = getattr(launcher, "build_persistent_command", None)
    if callable(builder):
        kwargs: dict[str, str] = {}
        if provider_session_id and _builder_accepts_keyword(
            builder,
            "provider_session_id",
        ):
            kwargs["provider_session_id"] = provider_session_id
        if model and _builder_accepts_keyword(builder, "model"):
            kwargs["model"] = model
        return list(builder(role, worktree, **kwargs))
    raise RuntimeError("persistent launcher is missing build_persistent_command")


async def _spawn_persistent_session(
    launcher: object,
    *,
    role: str,
    worktree: Path,
    model: str | None = None,
    provider_session_id: str | None = None,
    db_path: Path | None = None,
) -> AgentSession:
    factory = getattr(launcher, "spawn_persistent_session", None)
    if callable(factory):
        kwargs: dict[str, object] = {
            "role": role,
            "worktree": worktree,
        }
        if model and _builder_accepts_keyword(factory, "model"):
            kwargs["model"] = model
        if provider_session_id and _builder_accepts_keyword(
            factory,
            "provider_session_id",
        ):
            kwargs["provider_session_id"] = provider_session_id
        if db_path is not None and _builder_accepts_keyword(factory, "db_path"):
            kwargs["db_path"] = db_path
        session = factory(**kwargs)
        if isawaitable(session):
            session = await session
        return session

    command = _build_persistent_command(
        launcher,
        role,
        worktree,
        model=model,
        provider_session_id=provider_session_id,
    )
    env_builder = getattr(launcher, "build_env", None)
    if not callable(env_builder):
        raise RuntimeError("persistent launcher is missing build_env")
    env = env_builder(role)
    if env is not None and not isinstance(env, dict):
        raise RuntimeError("persistent launcher build_env must return a dict or None")
    return await LocalSession.spawn(command, env=env)


def _builder_accepts_keyword(builder: object, keyword: str) -> bool:
    if not callable(builder):
        return False
    try:
        parameters = signature(builder).parameters
    except (TypeError, ValueError):
        return False
    if keyword in parameters:
        return True
    return any(parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values())


def _session_pid(session: object) -> int | None:
    pid = getattr(session, "pid", None)
    if isinstance(pid, int) and not isinstance(pid, bool):
        return pid
    return None


def _active_provider_session_id(record: GodSessionRecord) -> str | None:
    if record.provider_binding_status != "active":
        return None
    if record.provider_session_kind != "codex_app_server_thread":
        return None
    return _clean_provider_session_id(record.provider_session_id)


def _active_provider_binding_id(
    record: GodSessionRecord,
    provider_session_kind: str,
) -> str | None:
    if record.provider_binding_status != "active":
        return None
    if record.provider_session_kind != provider_session_kind:
        return None
    return _clean_provider_session_id(record.provider_session_id)


def _live_provider_session_id(session: object) -> str | None:
    return _clean_provider_session_id(getattr(session, "provider_session_id", None))


def _clean_provider_session_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in {"last", "--last", "latest", "--latest"}:
        return None
    return stripped


def _raise_provider_binding(prefix: str) -> Never:
    raise RuntimeError(prefix)


def _provider_session_id_from_message(
    record: GodSessionRecord,
    message: object,
) -> str | None:
    if record.runtime != AgentRuntime.CODEX.value:
        return None
    artifacts = getattr(message, "artifacts", None)
    if not isinstance(artifacts, dict):
        return None
    return _clean_provider_session_id(artifacts.get("provider_session_id"))
