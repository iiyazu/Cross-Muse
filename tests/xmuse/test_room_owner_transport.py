"""Owner clones ensure/metadata plus writer-aware transport routing."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse import room_runner, room_runner_composition, room_runner_memory
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_acp_transport import (
    CLAUDE_ACP_WORKSPACE_WRITE_PROFILE,
    OPENCODE_ACP_WORKSPACE_WRITE_PROFILE,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_review_store import RoomExecutionReviewStore
from xmuse_core.chat.room_host import (
    LongTurnPolicy,
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomTransportResult,
)
from xmuse_core.chat.room_owner_clones import (
    OWNER_ID_RE,
    OwnerClone,
    OwnerCloneError,
    OwnerCloneManager,
)
from xmuse_core.chat.room_owner_transport import (
    OWNER_PREPARE_FAILED,
    WORKSPACE_WRITE_UNAVAILABLE,
    OwnerWorkspaceWriteSettings,
    RoomOwnerTransportRouter,
    build_owner_acp_transport_factory,
    is_workspace_write_participant,
    owner_id_for_participant,
)
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.chat.room_transport_router import RoutingRoomObservationTransport
from xmuse_core.skills.catalog import SkillCatalog

_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
}


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _init_source(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    (path / "a.txt").write_text("hello\n")
    _git("add", "a.txt", cwd=path)
    _git("commit", "-m", "initial", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path).strip()


def _conversation_id(tmp_path: Path, name: str) -> str:
    return RoomTestStore(tmp_path / f"{name}.db").create_conversation(name).id


def _participant(
    tmp_path: Path,
    name: str,
    *,
    cli_kind: str,
    workspace_access: str = "read_only",
) -> Participant:
    path = tmp_path / f"{name}.db"
    conversation_id = RoomTestStore(path).create_conversation(name).id
    return ParticipantStore(path).add(
        conversation_id=conversation_id,
        role="research",
        display_name="Researcher",
        cli_kind=cli_kind,  # type: ignore[arg-type]
        model="test-model",
        workspace_access=workspace_access,  # type: ignore[arg-type]
    )


def _delivery(participant: Participant) -> RoomObservationDelivery:
    return RoomObservationDelivery(
        conversation_id=participant.conversation_id,
        participant=participant,
        observation={"observation_id": "observation-1"},
        source_activity={"activity_id": "activity-1"},
        recent_activities=(),
        active_participants=(),
        transport_request_id="room-observation:request-1",
        outcome_client_request_id="room-outcome:request-1",
    )


class _RecordingTransport:
    def __init__(self) -> None:
        self.deliveries: list[RoomObservationDelivery] = []
        self.reconcile_calls: list[dict[str, Any]] = []
        self.reset_calls: list[tuple[RoomObservationDelivery, float]] = []

    async def deliver(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> RoomTransportResult:
        self.deliveries.append(delivery)
        return RoomTransportResult("finished")

    async def reconcile_cancel(self, **kwargs: Any) -> RoomCancelReconcileResult:
        self.reconcile_calls.append(kwargs)
        return RoomCancelReconcileResult("settled", "fake_reconciled")

    async def reset_after_missing_outcome(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> bool:
        self.reset_calls.append((delivery, timeout_s))
        return False


# ---------------------------------------------------------------------------
# Owner id
# ---------------------------------------------------------------------------


def test_owner_id_matches_constrained_pattern(tmp_path: Path) -> None:
    participant = _participant(tmp_path, "owner-id", cli_kind="claude")
    owner_id = owner_id_for_participant(participant.conversation_id, participant.participant_id)
    assert OWNER_ID_RE.fullmatch(owner_id) is not None
    assert owner_id.startswith("p-")
    assert is_workspace_write_participant(participant) is False


def test_is_workspace_write_participant_only_for_writers(tmp_path: Path) -> None:
    writer = _participant(
        tmp_path, "writer-kind", cli_kind="claude", workspace_access="workspace_write"
    )
    assert is_workspace_write_participant(writer) is True
    reader = _participant(tmp_path, "reader-kind", cli_kind="claude")
    assert is_workspace_write_participant(reader) is False


# ---------------------------------------------------------------------------
# ensure / metadata
# ---------------------------------------------------------------------------


class TestOwnerCloneEnsure:
    def test_ensure_creates_once_then_reuses(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        head = _init_source(source)
        manager = OwnerCloneManager(tmp_path / "clones")
        calls: list[Path] = []

        first = manager.ensure(source, "alice", prepare=calls.append)
        assert first.owner_id == "alice"
        assert first.branch == "owner/alice"
        assert first.base_commit == head
        assert calls == [first.path]

        second = manager.ensure(source, "alice", prepare=calls.append)
        assert second == first
        assert calls == [first.path], "reuse must not run prepare again"

    def test_ensure_reuse_runs_no_git_in_clone(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        manager = OwnerCloneManager(tmp_path / "clones")
        clone = manager.ensure(source, "alice")
        sentinel = tmp_path / "pwned"
        script = tmp_path / "evil.sh"
        script.write_text(f"#!/bin/sh\ntouch {sentinel}\nexit 0\n")
        script.chmod(0o755)
        with (clone.path / ".git" / "config").open("a", encoding="utf-8") as handle:
            handle.write(f"\n[core]\n\tfsmonitor = {script}\n")
        assert not sentinel.exists()

        reused = manager.ensure(source, "alice")

        assert reused == clone
        assert not sentinel.exists(), "reuse must not run git inside the clone"

    def test_ensure_rejects_missing_metadata(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        manager = OwnerCloneManager(tmp_path / "clones")
        manager.create(source, "alice")
        (tmp_path / "clones" / ".meta" / "alice.json").unlink()
        with pytest.raises(OwnerCloneError) as exc_info:
            manager.ensure(source, "alice")
        assert exc_info.value.code == "owner_clone_metadata_invalid"

    def test_ensure_rejects_corrupt_metadata(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        manager = OwnerCloneManager(tmp_path / "clones")
        manager.create(source, "alice")
        meta = tmp_path / "clones" / ".meta" / "alice.json"
        meta.write_text("{not json")
        with pytest.raises(OwnerCloneError) as exc_info:
            manager.ensure(source, "alice")
        assert exc_info.value.code == "owner_clone_metadata_invalid"
        meta.write_text('{"owner_id": "mallory", "branch": "owner/alice", "base_commit": "abc"}')
        with pytest.raises(OwnerCloneError) as exc_info:
            manager.ensure(source, "alice")
        assert exc_info.value.code == "owner_clone_metadata_invalid"

    def test_failing_prepare_removes_clone(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        manager = OwnerCloneManager(tmp_path / "clones")

        def _boom(path: Path) -> None:
            raise RuntimeError("deps exploded")

        with pytest.raises(OwnerCloneError) as exc_info:
            manager.ensure(source, "alice", prepare=_boom)
        assert exc_info.value.code == "owner_clone_prepare_failed"
        assert not (tmp_path / "clones" / "alice").exists()
        assert not (tmp_path / "clones" / ".meta" / "alice.json").exists()

    def test_remove_clears_metadata(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        manager = OwnerCloneManager(tmp_path / "clones")
        manager.ensure(source, "alice")
        manager.remove("alice")
        assert not (tmp_path / "clones" / ".meta" / "alice.json").exists()
        # Removing again is tolerated.
        manager.remove("alice")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _settings(
    tmp_path: Path,
    source: Path,
    *,
    claude_argv: tuple[str, ...] | None = ("claude-stub",),
    opencode_argv: tuple[str, ...] | None = None,
    prepare_command: tuple[str, ...] | None = None,
) -> OwnerWorkspaceWriteSettings:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return OwnerWorkspaceWriteSettings(
        clones_root=tmp_path / "owner-clones",
        source_repo=source,
        xmuse_root=tmp_path,
        home=home,
        room_mcp_url="http://127.0.0.1:8100/mcp/room",
        bwrap=tmp_path / "bwrap",
        claude_agent_argv=claude_argv,
        opencode_argv=opencode_argv,
        opencode_default_model="test-model" if opencode_argv else None,
        prepare_command=prepare_command,
    )


def _router(
    wrapped: RoutingRoomObservationTransport,
    *,
    settings: OwnerWorkspaceWriteSettings | None,
    manager: OwnerCloneManager | None = None,
    factory: Any = None,
) -> RoomOwnerTransportRouter:
    return RoomOwnerTransportRouter(
        dict(wrapped._routes),
        settings=settings,
        clone_manager=manager,
        transport_factory=factory,
    )


class TestRoomOwnerTransportRouter:
    async def test_writer_delivery_uses_dedicated_transport(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        settings = _settings(tmp_path, source)
        wrapped = RoutingRoomObservationTransport({"claude": _RecordingTransport()})
        dedicated = _RecordingTransport()
        seen: list[tuple[Participant, OwnerClone]] = []

        def _factory(participant: Participant, clone: OwnerClone) -> _RecordingTransport:
            seen.append((participant, clone))
            return dedicated

        router = _router(
            wrapped,
            settings=settings,
            factory=_factory,
        )
        writer = _participant(
            tmp_path, "writer", cli_kind="claude", workspace_access="workspace_write"
        )
        delivery = _delivery(writer)

        result = await router.deliver(delivery, timeout_s=5.0)
        assert result == RoomTransportResult("finished")
        assert dedicated.deliveries == [delivery]
        assert wrapped._routes["claude"].deliveries == []
        assert len(seen) == 1
        participant, clone = seen[0]
        assert participant == writer
        assert clone.path == settings.clones_root / owner_id_for_participant(
            writer.conversation_id, writer.participant_id
        )
        assert clone.path.is_dir()

        # A second delivery reuses the same dedicated transport.
        second = _delivery(writer)
        await router.deliver(second, timeout_s=5.0)
        assert dedicated.deliveries == [delivery, second]
        assert len(seen) == 1

    async def test_read_only_delivery_uses_wrapped_router(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        settings = _settings(tmp_path, source)
        claude = _RecordingTransport()
        wrapped = RoutingRoomObservationTransport({"claude": claude})

        def _boom(participant: Participant, clone: OwnerClone) -> Any:
            raise AssertionError("factory must not run for read-only deliveries")

        router = _router(wrapped, settings=settings, factory=_boom)
        reader = _participant(tmp_path, "reader", cli_kind="claude")
        delivery = _delivery(reader)

        result = await router.deliver(delivery, timeout_s=5.0)
        assert result == RoomTransportResult("finished")
        assert claude.deliveries == [delivery]

    async def test_writer_fails_closed_without_settings(self, tmp_path: Path) -> None:
        wrapped = RoutingRoomObservationTransport({"claude": _RecordingTransport()})
        router = _router(wrapped, settings=None, factory=None)
        writer = _participant(
            tmp_path, "writer-closed", cli_kind="claude", workspace_access="workspace_write"
        )
        result = await router.deliver(_delivery(writer), timeout_s=5.0)
        assert result == RoomTransportResult("failed", WORKSPACE_WRITE_UNAVAILABLE)

    async def test_writer_fails_closed_when_provider_disabled(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        # No claude argv: the default factory cannot build a writer config.
        settings = _settings(tmp_path, source, claude_argv=None)
        factory = build_owner_acp_transport_factory(
            settings, registry_path=tmp_path / "god_sessions.json"
        )
        wrapped = RoutingRoomObservationTransport({"claude": _RecordingTransport()})
        router = _router(
            wrapped,
            settings=settings,
            factory=factory,  # type: ignore[arg-type]
        )
        writer = _participant(
            tmp_path, "writer-off", cli_kind="claude", workspace_access="workspace_write"
        )
        result = await router.deliver(_delivery(writer), timeout_s=5.0)
        assert result == RoomTransportResult("failed", WORKSPACE_WRITE_UNAVAILABLE)

    async def test_prepare_failure_fails_delivery_and_removes_clone(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        settings = _settings(tmp_path, source, prepare_command=("false",))
        wrapped = RoutingRoomObservationTransport({"claude": _RecordingTransport()})
        router = _router(
            wrapped,
            settings=settings,
            factory=lambda participant, clone: _RecordingTransport(),
        )
        writer = _participant(
            tmp_path, "writer-prep", cli_kind="claude", workspace_access="workspace_write"
        )
        result = await router.deliver(_delivery(writer), timeout_s=5.0)
        assert result.status == "failed"
        assert result.reason == OWNER_PREPARE_FAILED
        owner_id = owner_id_for_participant(writer.conversation_id, writer.participant_id)
        assert not (settings.clones_root / owner_id).exists()
        assert not (settings.clones_root / ".meta" / f"{owner_id}.json").exists()

    async def test_reconcile_and_reset_follow_writer_choice(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        settings = _settings(tmp_path, source)
        claude = _RecordingTransport()
        wrapped = RoutingRoomObservationTransport({"claude": claude})
        dedicated = _RecordingTransport()
        router = _router(wrapped, settings=settings, factory=lambda participant, clone: dedicated)
        writer = _participant(
            tmp_path, "writer-hook", cli_kind="claude", workspace_access="workspace_write"
        )
        reader = _participant(tmp_path, "reader-hook", cli_kind="claude")
        attempt = {"attempt_id": "attempt-1", "provider_phase": "bound"}

        # No dedicated transport yet (e.g. after a runner restart): reset keeps the
        # host's reopen decision, and reconcile rebuilds the transport over the
        # reused clone instead of staying pending forever.
        assert await router.reset_after_missing_outcome(_delivery(writer), timeout_s=1.0) is True
        rebuilt = await router.reconcile_cancel(
            conversation_id=writer.conversation_id,
            participant=writer,
            attempt=attempt,
            timeout_s=1.0,
        )
        assert rebuilt == RoomCancelReconcileResult("settled", "fake_reconciled")

        await router.deliver(_delivery(writer), timeout_s=5.0)
        settled = await router.reconcile_cancel(
            conversation_id=writer.conversation_id,
            participant=writer,
            attempt=attempt,
            timeout_s=1.0,
        )
        assert settled == RoomCancelReconcileResult("settled", "fake_reconciled")
        assert dedicated.reconcile_calls and not claude.reconcile_calls
        assert (await router.reset_after_missing_outcome(_delivery(writer), timeout_s=1.0)) is False
        assert dedicated.reset_calls and not claude.reset_calls

        # Read-only participants keep the wrapped routes.
        await router.reconcile_cancel(
            conversation_id=reader.conversation_id,
            participant=reader,
            attempt=attempt,
            timeout_s=1.0,
        )
        await router.reset_after_missing_outcome(_delivery(reader), timeout_s=1.0)
        assert claude.reconcile_calls and claude.reset_calls


class TestOwnerAcpConfig:
    def test_writer_config_uses_clone_workspace_and_profile(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        _init_source(source)
        settings = _settings(tmp_path, source, opencode_argv=(str(tmp_path / "opencode"), "acp"))
        factory = build_owner_acp_transport_factory(
            settings, registry_path=tmp_path / "god_sessions.json"
        )
        manager = OwnerCloneManager(settings.clones_root)
        writer = _participant(
            tmp_path, "writer-cfg", cli_kind="claude", workspace_access="workspace_write"
        )
        clone = manager.ensure(
            source, owner_id_for_participant(writer.conversation_id, writer.participant_id)
        )
        transport = factory(writer, clone)
        assert transport is not None
        config = transport._config  # type: ignore[union-attr]
        assert config.workspace == clone.path
        assert config.profile is CLAUDE_ACP_WORKSPACE_WRITE_PROFILE
        assert config.command[0] == str(settings.bwrap)
        assert "--chdir" in config.command
        assert str(clone.path) in config.command
        assert config.room_mcp_url == "http://127.0.0.1:8100/mcp/room"

        opencode_writer = _participant(
            tmp_path, "owriter-cfg", cli_kind="opencode", workspace_access="workspace_write"
        )
        opencode_clone = manager.ensure(
            source,
            owner_id_for_participant(
                opencode_writer.conversation_id, opencode_writer.participant_id
            ),
        )
        opencode_transport = factory(opencode_writer, opencode_clone)
        assert opencode_transport is not None
        opencode_config = opencode_transport._config  # type: ignore[union-attr]
        assert opencode_config.profile is OPENCODE_ACP_WORKSPACE_WRITE_PROFILE
        assert opencode_config.default_model == "test-model"


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def _compose(
    tmp_path: Path,
    name: str,
    *,
    owner_settings: OwnerWorkspaceWriteSettings | None = None,
    owner_factory: Any = None,
) -> Any:
    db_path = tmp_path / f"{name}.db"
    RoomDatabase(db_path).initialize()
    memory = room_runner_memory.compose_room_runner_memory(
        db_path,
        worker_id=f"memory-{name}",
        environ={},
    )
    return room_runner_composition.compose_room_runtime(
        root=tmp_path,
        worktree=tmp_path,
        launchers={},
        controls=RoomObservationControlStore(db_path),
        skill_decisions=RoomAttemptSkillDecisionStore(db_path),
        skill_catalog=SkillCatalog.load_bundled(),
        execution_store=RoomExecutionReviewStore(db_path),
        max_concurrent_rooms=1,
        delivery_timeout_s=10,
        cleanup_grace_s=1,
        runner_generation=f"generation-{name}",
        runner_boot_id=f"boot-{name}",
        memory_recall=memory.recall,
        memory_context_receipts=memory.context_receipts,
        memory_delivery_pump=memory.delivery_pump,
        owner_settings=owner_settings,
        owner_transport_factory=owner_factory,
    )


def test_composition_host_selector_matches_only_writers(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _init_source(source)
    settings = _settings(tmp_path, source)
    composition = _compose(
        tmp_path,
        "owner-selector",
        owner_settings=settings,
        owner_factory=lambda participant, clone: _RecordingTransport(),
    )
    assert isinstance(composition.host._transport, RoomOwnerTransportRouter)
    assert set(composition.host._transport._routes) == {"codex"}
    assert isinstance(composition.host._long_turn_policy, LongTurnPolicy)

    selector = composition.host._long_turn_selector
    assert selector is not None
    writer = _participant(
        tmp_path, "selector-writer", cli_kind="claude", workspace_access="workspace_write"
    )
    assert selector(writer) is True
    assert selector(_participant(tmp_path, "selector-reader", cli_kind="claude")) is False
    assert (
        selector(
            _participant(tmp_path, "selector-codex", cli_kind="codex"),
        )
        is False
    )


def test_composition_without_owner_settings_still_selects_writers(tmp_path: Path) -> None:
    composition = _compose(tmp_path, "owner-selector-off")
    selector = composition.host._long_turn_selector
    assert selector is not None
    writer = _participant(
        tmp_path,
        "selector-writer-off",
        cli_kind="opencode",
        workspace_access="workspace_write",
    )
    assert selector(writer) is True


# ---------------------------------------------------------------------------
# Runner settings builder
# ---------------------------------------------------------------------------


class TestOwnerRunnerSettings:
    def test_missing_bwrap_disables_owner_settings(self, tmp_path: Path) -> None:
        settings = room_runner._owner_workspace_write_settings(
            root=tmp_path,
            worktree=tmp_path,
            room_mcp_url="http://127.0.0.1:8100/mcp/room",
            claude_acp_command=("npx", "-y", "@agentclientprotocol/claude-agent-acp"),
            opencode_enabled=False,
            environ={"XMUSE_OPENCODE_BWRAP": "/nonexistent/bwrap"},
        )
        assert settings is None

    def test_builds_settings_with_claude_only(self, tmp_path: Path) -> None:
        bwrap = tmp_path / "bwrap"
        bwrap.write_text("#!/bin/sh\n")
        settings = room_runner._owner_workspace_write_settings(
            root=tmp_path,
            worktree=tmp_path,
            room_mcp_url="http://127.0.0.1:8100/mcp/room",
            claude_acp_command=("npx", "-y", "@agentclientprotocol/claude-agent-acp"),
            opencode_enabled=False,
            environ={"XMUSE_OPENCODE_BWRAP": str(bwrap), "HOME": str(tmp_path)},
        )
        assert settings is not None
        assert settings.clones_root == tmp_path / "runtime" / "owner-clones"
        assert settings.source_repo == tmp_path
        assert settings.claude_agent_argv == ("npx", "-y", "@agentclientprotocol/claude-agent-acp")
        assert settings.opencode_argv is None
        assert settings.prepare_command is None
        assert settings.prepare_timeout_s == 900.0

    def test_rejects_invalid_prepare_env(self, tmp_path: Path) -> None:
        bwrap = tmp_path / "bwrap"
        bwrap.write_text("#!/bin/sh\n")
        base = {
            "XMUSE_OPENCODE_BWRAP": str(bwrap),
            "HOME": str(tmp_path),
        }
        with pytest.raises(room_runner.RoomRunnerError) as exc_info:
            room_runner._owner_workspace_write_settings(
                root=tmp_path,
                worktree=tmp_path,
                room_mcp_url="http://127.0.0.1:8100/mcp/room",
                claude_acp_command=None,
                opencode_enabled=False,
                environ={**base, "XMUSE_OWNER_PREPARE_COMMAND": "'unclosed"},
            )
        assert exc_info.value.code == "room_runner_owner_prepare_command_invalid"
        with pytest.raises(room_runner.RoomRunnerError) as exc_info:
            room_runner._owner_workspace_write_settings(
                root=tmp_path,
                worktree=tmp_path,
                room_mcp_url="http://127.0.0.1:8100/mcp/room",
                claude_acp_command=None,
                opencode_enabled=False,
                environ={**base, "XMUSE_OWNER_PREPARE_TIMEOUT_S": "nope"},
            )
        assert exc_info.value.code == "room_runner_owner_prepare_timeout_invalid"
