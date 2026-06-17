from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.agents.session import LocalSession
from xmuse_core.chat.participant_store import INIT_GOD_ROLE


@dataclass
class LiveGodSession:
    record: GodSessionRecord
    session: LocalSession
    worktree: Path


RuntimeKey = AgentRuntime | str
_UNSET = object()


class GodSessionLayer:
    def __init__(self, registry_path: Path, launchers: dict[RuntimeKey, object]) -> None:
        self._registry = GodSessionRegistry(registry_path)
        self._launchers = launchers
        self._live_sessions: dict[str, LiveGodSession] = {}

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
        command = _build_persistent_command(launcher, role, worktree)
        env = launcher.build_env(role)
        session = await LocalSession.spawn(command, env=env)
        if live is not None:
            self._live_sessions[live.record.god_session_id] = LiveGodSession(
                record=live.record,
                session=session,
                worktree=worktree,
            )
            return live.record
        record = self._registry.create(
            role=role,
            agent_name=agent.name,
            runtime=runtime,
            session_address=f"@{role}",
            session_inbox_id=f"inbox-{role}",
        )
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
            command = _build_persistent_command(launcher, role, worktree)
            env = launcher.build_env(role)
            session = await LocalSession.spawn(command, env=env)
            self._live_sessions[live.record.god_session_id] = LiveGodSession(
                record=live.record,
                session=session,
                worktree=worktree,
            )
            return live.record

        try:
            record = self._registry.find_by_conversation_participant(
                conversation_id,
                participant_id,
                feature_scope_id=feature_scope_id,
            )
        except KeyError:
            record = self._legacy_record_for_scope_migration(
                conversation_id=conversation_id,
                participant_id=participant_id,
                role=role,
                agent=agent,
                model=model,
                prompt_fingerprint=prompt_fingerprint,
                worktree=worktree,
                feature_scope_id=feature_scope_id,
            )
            if record is None:
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
        command = _build_persistent_command(launcher, role, worktree)
        env = launcher.build_env(role)
        session = await LocalSession.spawn(command, env=env)
        self._live_sessions[record.god_session_id] = LiveGodSession(
            record=record,
            session=session,
            worktree=worktree,
        )
        return record

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

    def _legacy_record_for_scope_migration(
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

    async def receive_message(self, god_session_id: str):
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
        return await live.session.receive()

    async def abort_session(self, god_session_id: str) -> None:
        live = self._live_sessions.get(god_session_id)
        if live is None:
            return
        await live.session.abort()
        self._live_sessions.pop(god_session_id, None)

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
                and (
                    feature_scope_id is _UNSET
                    or live.record.feature_scope_id == feature_scope_id
                )
            ):
                return live
        return None

    def _find_live_session_by_conversation_role(
        self,
        conversation_id: str,
        role: str,
    ) -> LiveGodSession | None:
        for live in reversed(list(self._live_sessions.values())):
            if (
                live.record.conversation_id == conversation_id
                and live.record.role == role
            ):
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
            str(worktree)
            if compares_peer_metadata and worktree is not None
            else None
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


def _assert_launcher_supports_persistent_sessions(
    launcher: object,
    runtime: str,
) -> None:
    if (
        getattr(launcher, "supports_persistent_sessions", False) is True
        and callable(getattr(launcher, "build_persistent_command", None))
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
    address_scope_suffix, inbox_scope_suffix = _feature_scope_identity_suffixes(
        feature_scope_id
    )
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
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in cleaned
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
            prompt_fingerprint
            if prompt_fingerprint is not None
            else record.prompt_fingerprint
        ),
        "worktree": str(worktree) if worktree is not None else record.worktree,
        "feature_scope_id": (
            feature_scope_id
            if feature_scope_id is not None
            else record.feature_scope_id
        ),
    }


def _build_persistent_command(
    launcher: object,
    role: str,
    worktree: Path,
) -> list[str]:
    builder = getattr(launcher, "build_persistent_command", None)
    if callable(builder):
        return list(builder(role, worktree))
    raise RuntimeError("persistent launcher is missing build_persistent_command")
