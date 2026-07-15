from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import xmuse_core.chat.room_codex_native_runtime as native_runtime_module
from tests.xmuse.room_fixtures import (
    RoomTestStore,
)
from tests.xmuse.room_fixtures import (
    TestConversation as RoomFixtureConversation,
)
from xmuse_core.agents.codex_native_adapter import NativeInvokeResult
from xmuse_core.agents.codex_native_contract import NativeInvocation
from xmuse_core.agents.room_codex_scopes import ROOM_NATIVE_SESSION_SCOPE
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_codex_bridge import (
    RoomCodexBridgeError,
    RoomCodexBridgeStore,
    opaque_guard,
)
from xmuse_core.chat.room_codex_native_runtime import (
    RoomCodexNativeRuntime,
    _assert_action_policy,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore


def _room(path: Path) -> tuple[RoomFixtureConversation, Participant]:
    conversation = RoomTestStore(path).create_conversation("Native Room")
    participant = ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="reviewer",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-test",
    )
    return conversation, participant


def _attempt(path: Path) -> tuple[str, str]:
    conversation, participant = _room(path)
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="review",
        client_request_id="human-1",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="host",
        lease_ttl_s=120,
    )
    assert claim is not None
    observation_id = str(claim["observation"]["observation_id"])
    attempt = RoomObservationControlStore(path).record_claim(
        observation_id,
        base_attempt_limit=3,
    )
    return participant.participant_id, str(attempt["attempt_id"])


@pytest.mark.parametrize(
    ("state", "provider_phase", "recovery_state"),
    [
        ("delivering", "not_started", "none"),
        ("failed", "cleanup_pending", "none"),
        ("expired", "cleanup_succeeded", "cleanup_pending"),
    ],
)
def test_goal_set_rejects_live_delivery_and_unfinished_cleanup(
    tmp_path: Path,
    state: str,
    provider_phase: str,
    recovery_state: str,
) -> None:
    path = tmp_path / "chat.db"
    participant_id, attempt_id = _attempt(path)
    with RoomDatabase(path).connect() as conn:
        conn.execute("begin immediate")
        conn.execute(
            """update room_observation_attempts
               set state = ?, provider_phase = ?, recovery_state = ?
               where attempt_id = ?""",
            (state, provider_phase, recovery_state, attempt_id),
        )
        conn.commit()

    with pytest.raises(RoomCodexBridgeError) as error:
        _assert_action_policy(
            path,
            {"capability_id": "goal_set", "participant_id": participant_id},
            {"goal": None, "active_turn": False},
        )

    assert error.value.code == "codex_native_delivery_conflict"


def test_completed_bound_attempt_does_not_permanently_block_future_goal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    participant_id, attempt_id = _attempt(path)
    participant = ParticipantStore(path).get(participant_id)
    with RoomDatabase(path).connect() as conn:
        conn.execute("begin immediate")
        conn.execute(
            """update room_observation_attempts
               set state = 'completed', provider_phase = 'bound', finished_at = 'now'
               where attempt_id = ?""",
            (attempt_id,),
        )
        conn.commit()

    _assert_action_policy(
        path,
        {"capability_id": "goal_set", "participant_id": participant_id},
        {"goal": None, "active_turn": False},
    )
    store = RoomCodexBridgeStore(path)
    session = opaque_guard(participant_id, "session")
    goal = opaque_guard(participant_id, "goal")
    settings = opaque_guard(participant_id, "settings")
    store.begin_reconcile(
        conversation_id=participant.conversation_id,
        participant_id=participant_id,
        session_guard=session,
    )
    store.apply_native_snapshot(
        conversation_id=participant.conversation_id,
        participant_id=participant_id,
        expected_session_guard=session,
        state="accepting",
        goal_guard=goal,
        settings_guard=settings,
        active_turn_guard=None,
    )

    action, created = store.request_action(
        conversation_id=participant.conversation_id,
        participant_id=participant_id,
        capability_id="goal_set",
        safe_request={"objective": "continue safely", "token_budget": 10_000},
        client_action_id="goal-after-completion",
        expected_session_guard=session,
        expected_goal_guard=goal,
        expected_settings_guard=settings,
        confirmed_pending_observations=True,
    )

    assert created is True
    assert action["status"] == "requested"
    assert (
        store.room_participant_work_counts(participant.conversation_id)[participant_id][
            "active_attempt_count"
        ]
        == 0
    )


class _NeverEventStream:
    def __init__(self) -> None:
        self.closed = False

    async def receive(self) -> dict[str, object]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.closed = True


class _QueueEventStream(_NeverEventStream):
    def __init__(self) -> None:
        super().__init__()
        self.queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def receive(self) -> dict[str, object]:
        return await self.queue.get()


class _FailingNativeSessionLayer:
    def __init__(self, snapshot: dict[str, object], *, replace_on_force: bool = True) -> None:
        self.snapshot = snapshot
        self.stream = _NeverEventStream()
        self.ensure_force_rebind: list[bool] = []
        self.ensure_scopes: list[object] = []
        self.incarnation = 1
        self.replace_on_force = replace_on_force

    def prompt_fingerprint_for_resume(self, **kwargs: object) -> str:
        return str(kwargs["proposed_fingerprint"])

    async def ensure_conversation_session(self, **kwargs: object) -> object:
        force_rebind = kwargs.get("force_rebind") is True
        self.ensure_force_rebind.append(force_rebind)
        self.ensure_scopes.append(kwargs.get("feature_scope_id"))
        if force_rebind and self.replace_on_force:
            self.incarnation += 1
            self.stream = _NeverEventStream()
        return object()

    def require_live_provider_session_binding(self, **_kwargs: object) -> object:
        return SimpleNamespace(god_session_id="god-session")

    async def native_snapshot(self, _god_session_id: str) -> dict[str, object]:
        return self.snapshot

    async def discover_native_capabilities(self, _god_session_id: str) -> dict[str, object]:
        return {"schema_version": "room_codex_native_capabilities/v1", "capabilities": []}

    def subscribe_native_events(self, _god_session_id: str) -> object:
        return self.stream

    def native_session_incarnation(self, _god_session_id: str) -> int:
        return self.incarnation

    async def invoke_native(self, *_args: object, **_kwargs: object) -> object:
        raise RoomCodexBridgeError("codex_native_runtime_test_failure")


class _SuccessfulNativeSessionLayer(_FailingNativeSessionLayer):
    def __init__(self, snapshot: dict[str, object]) -> None:
        super().__init__(snapshot)
        self.invoke_count = 0
        self.fail_next_snapshot = False
        self.fail_post_invoke_snapshot = False

    async def native_snapshot(self, god_session_id: str) -> dict[str, object]:
        if self.fail_next_snapshot:
            self.fail_next_snapshot = False
            raise RuntimeError("private provider session ended")
        if self.fail_post_invoke_snapshot and self.invoke_count > 0:
            raise RuntimeError("private post snapshot failure")
        return await super().native_snapshot(god_session_id)

    async def invoke_native(self, *_args: object, **_kwargs: object) -> object:
        self.invoke_count += 1
        return NativeInvokeResult(
            NativeInvocation("goal_get", "thread/goal/read", {}),
            {"acknowledged": True},
        )


class _GoalRecoverySessionLayer(_FailingNativeSessionLayer):
    def __init__(self, snapshot: dict[str, object]) -> None:
        super().__init__(snapshot)
        self.invocations: list[tuple[str, dict[str, object]]] = []

    async def invoke_native(
        self,
        _god_session_id: str,
        capability_id: str,
        safe_request: dict[str, object],
        **_kwargs: object,
    ) -> NativeInvokeResult:
        self.invocations.append((capability_id, dict(safe_request)))
        if capability_id == "goal_set":
            self.snapshot["goal"] = {
                "objective": safe_request["objective"],
                "status": "active",
                "token_budget": safe_request["token_budget"],
                "tokens_used": 0,
                "time_used_seconds": 0,
            }
        elif capability_id == "goal_pause":
            goal = self.snapshot.get("goal")
            assert isinstance(goal, dict)
            goal["status"] = "paused"
        else:
            raise AssertionError(f"unexpected recovery capability: {capability_id}")
        guards = self.snapshot["guards"]
        assert isinstance(guards, dict)
        guards["goal"] = opaque_guard("recovered-goal", str(len(self.invocations)), capability_id)
        return NativeInvokeResult(
            NativeInvocation(capability_id, "thread/goal/set", {}),
            {"acknowledged": True},
        )


class _BlockingNativeSessionLayer(_FailingNativeSessionLayer):
    def __init__(self, snapshot: dict[str, object]) -> None:
        super().__init__(snapshot)
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.ensure_count = 0
        self.active_ensures = 0
        self.max_active_ensures = 0
        self.cancelled_ensures = 0

    async def ensure_conversation_session(self, **kwargs: object) -> object:
        self.ensure_force_rebind.append(kwargs.get("force_rebind") is True)
        self.ensure_scopes.append(kwargs.get("feature_scope_id"))
        self.ensure_count += 1
        self.active_ensures += 1
        self.max_active_ensures = max(self.max_active_ensures, self.active_ensures)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled_ensures += 1
            raise
        finally:
            self.active_ensures -= 1
        return object()


class _DeadRecoverySessionLayer(_FailingNativeSessionLayer):
    async def ensure_conversation_session(self, **kwargs: object) -> object:
        result = await super().ensure_conversation_session(**kwargs)
        if kwargs.get("force_rebind") is True:
            raise RuntimeError("private dead session could not be replaced")
        return result


def _accepting_snapshot(session: str | None = None) -> dict[str, object]:
    return {
        "goal": None,
        "settings": {"model": "gpt-test", "effort": "medium"},
        "active_turn": False,
        "guards": {
            "session": session or opaque_guard("session"),
            "goal": opaque_guard("goal"),
            "settings": opaque_guard("settings"),
            "turn": None,
        },
    }


def _seed_applied_goal_intent(
    path: Path,
    participant: Participant,
    *,
    desired_state: str = "active",
) -> tuple[RoomCodexBridgeStore, str]:
    bridge = RoomCodexBridgeStore(path)
    old_session = opaque_guard("old-native-session")
    goal_guard = opaque_guard("old-native-goal")
    settings_guard = opaque_guard("old-native-settings")
    bridge.begin_reconcile(
        conversation_id=participant.conversation_id,
        participant_id=participant.participant_id,
        session_guard=old_session,
    )
    bridge.apply_native_snapshot(
        conversation_id=participant.conversation_id,
        participant_id=participant.participant_id,
        expected_session_guard=old_session,
        state="accepting",
        goal_guard=goal_guard,
        settings_guard=settings_guard,
        active_turn_guard=None,
    )
    action, _ = bridge.request_action(
        conversation_id=participant.conversation_id,
        participant_id=participant.participant_id,
        capability_id="goal_set",
        safe_request={"objective": "Continue the durable work", "token_budget": 20_000},
        client_action_id="goal-set-authority",
        expected_session_guard=old_session,
        expected_goal_guard=goal_guard,
        expected_settings_guard=settings_guard,
    )
    claimed = bridge.claim_next_action(runner_generation="runner-old")
    assert claimed is not None and claimed["action_id"] == action["action_id"]
    bridge.complete_action(
        action_id=str(action["action_id"]),
        runner_generation="runner-old",
        status="applied",
        reason_code=None,
        ack_summary={"native_method": "thread/goal/set", "acknowledged": True},
    )
    bridge.apply_native_snapshot(
        conversation_id=participant.conversation_id,
        participant_id=participant.participant_id,
        expected_session_guard=old_session,
        state="goal_active",
        goal_guard=goal_guard,
        settings_guard=settings_guard,
        active_turn_guard=None,
    )
    if desired_state == "paused":
        pause, _ = bridge.request_action(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            capability_id="goal_pause",
            safe_request={},
            client_action_id="goal-pause-authority",
            expected_session_guard=old_session,
            expected_goal_guard=goal_guard,
        )
        claimed_pause = bridge.claim_next_action(runner_generation="runner-old")
        assert claimed_pause is not None and claimed_pause["action_id"] == pause["action_id"]
        bridge.complete_action(
            action_id=str(pause["action_id"]),
            runner_generation="runner-old",
            status="applied",
            reason_code=None,
            ack_summary={"native_method": "thread/goal/set", "acknowledged": True},
        )
        bridge.apply_native_snapshot(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            expected_session_guard=old_session,
            state="accepting",
            goal_guard=goal_guard,
            settings_guard=settings_guard,
            active_turn_guard=None,
        )
        bridge.observe_goal_snapshot(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            session_guard=old_session,
            status="paused",
        )
    return bridge, old_session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("desired_state", "expected_capabilities", "expected_status"),
    [
        ("active", ["goal_set"], "active"),
        ("paused", ["goal_set", "goal_pause"], "paused"),
    ],
)
async def test_reconcile_restores_durable_goal_intent_on_replacement_session(
    tmp_path: Path,
    desired_state: str,
    expected_capabilities: list[str],
    expected_status: str,
) -> None:
    path = tmp_path / "chat.db"
    _conversation, participant = _room(path)
    bridge, _old_session = _seed_applied_goal_intent(path, participant, desired_state=desired_state)
    new_session = opaque_guard("replacement-native-session")
    layer = _GoalRecoverySessionLayer(_accepting_snapshot(new_session))
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-new",
    )
    try:
        snapshot = await runtime.reconcile_participant(participant)
        goal = snapshot.get("goal")
        assert isinstance(goal, dict) and goal["status"] == expected_status
        assert [item[0] for item in layer.invocations] == expected_capabilities
        recovery = bridge.list_goal_recoveries(participant.participant_id)
        assert len(recovery) == 1 and recovery[0]["phase"] == "applied"
        intent = bridge.get_goal_intent(participant.participant_id)
        assert intent is not None and intent["observed_status"] == expected_status

        await runtime.reconcile_participant(participant)
        assert [item[0] for item in layer.invocations] == expected_capabilities
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_reconcile_never_replays_unknown_goal_recovery_dispatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    _conversation, participant = _room(path)
    bridge, _old_session = _seed_applied_goal_intent(path, participant)
    intent = bridge.get_goal_intent(participant.participant_id)
    assert intent is not None
    new_session = opaque_guard("replacement-native-session")
    recovery = bridge.begin_goal_recovery(
        conversation_id=participant.conversation_id,
        participant_id=participant.participant_id,
        intent_revision=int(intent["revision"]),
        target_session_guard=new_session,
    )
    bridge.advance_goal_recovery(
        recovery_id=str(recovery["recovery_id"]),
        phase="goal_dispatching",
    )
    layer = _GoalRecoverySessionLayer(_accepting_snapshot(new_session))
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-new",
    )
    try:
        with pytest.raises(RoomCodexBridgeError) as error:
            await runtime.reconcile_participant(participant)
        assert error.value.code == "codex_native_goal_recovery_result_unknown"
        assert layer.invocations == []
        assert bridge.list_goal_recoveries(participant.participant_id)[0]["phase"] == (
            "result_unknown"
        )
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_reconcile_observation_timeout_keeps_participant_singleflight_alive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "chat.db"
    _conversation, participant = _room(path)
    layer = _BlockingNativeSessionLayer(_accepting_snapshot())
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    monkeypatch.setattr(native_runtime_module, "_RECONCILE_TIMEOUT_S", 0.01)
    try:
        await runtime.reconcile_all()
        task = runtime._reconcile_tasks[participant.participant_id]
        assert task.done() is False
        assert layer.cancelled_ensures == 0

        await runtime.reconcile_all()

        assert runtime._reconcile_tasks[participant.participant_id] is task
        assert layer.ensure_count == 1
        assert layer.cancelled_ensures == 0
        layer.release.set()
        await asyncio.wait_for(task, timeout=1)
    finally:
        layer.release.set()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_reconcile_uses_one_persistent_four_slot_semaphore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "chat.db"
    conversation, _participant = _room(path)
    participants = ParticipantStore(path)
    for index in range(4):
        participants.add(
            conversation_id=conversation.id,
            role=f"specialist-{index}",
            display_name=f"Specialist {index}",
            cli_kind="codex",
            model="gpt-test",
        )
    layer = _BlockingNativeSessionLayer(_accepting_snapshot())
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    monkeypatch.setattr(native_runtime_module, "_RECONCILE_TIMEOUT_S", 0.01)
    try:
        await runtime.reconcile_all()
        assert layer.ensure_count == 4
        assert layer.max_active_ensures == 4

        await runtime.reconcile_all()
        assert layer.ensure_count == 4
        assert layer.max_active_ensures == 4

        layer.release.set()
        await asyncio.wait_for(
            asyncio.gather(*runtime._reconcile_tasks.values()),
            timeout=1,
        )
        assert layer.ensure_count == 5
        assert layer.max_active_ensures == 4
    finally:
        layer.release.set()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_native_unavailable_backoff_skips_dead_session_ensure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    conversation, participant = _room(path)
    session = opaque_guard("session")
    layer = _DeadRecoverySessionLayer(_accepting_snapshot(session))
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    bridge = RoomCodexBridgeStore(path)
    try:
        await runtime.reconcile_all()
        bridge.begin_reconcile(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            session_guard=session,
            reason_code="codex_native_unavailable",
        )
        bridge.apply_native_snapshot(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            expected_session_guard=session,
            state="native_unavailable",
            goal_guard=None,
            settings_guard=None,
            active_turn_guard=None,
            reason_code="codex_native_unavailable",
        )

        await runtime.reconcile_all()
        assert layer.ensure_force_rebind == [False, True]
        assert set(layer.ensure_scopes) == {ROOM_NATIVE_SESSION_SCOPE}

        await runtime.reconcile_all()
        assert layer.ensure_force_rebind == [False, True]
        hold = bridge.get_hold(participant.participant_id)
        assert hold is not None and hold["state"] == "native_unavailable"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_stopped_participant_reconcile_and_watcher_are_retired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "chat.db"
    _conversation, participant = _room(path)
    layer = _BlockingNativeSessionLayer(_accepting_snapshot())
    layer.release.set()
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    monkeypatch.setattr(native_runtime_module, "_RECONCILE_TIMEOUT_S", 0.01)
    try:
        await runtime.reconcile_all()
        prior_stream = layer.stream
        layer.release.clear()
        await runtime.reconcile_all()
        task = runtime._reconcile_tasks[participant.participant_id]
        assert task.done() is False

        ParticipantStore(path).update_status(participant.participant_id, "stopped")
        await runtime.reconcile_all()

        assert task.cancelled() is True
        assert layer.cancelled_ensures == 1
        assert prior_stream.closed is True
        assert participant.participant_id not in runtime._reconcile_tasks
        assert participant.participant_id not in runtime._watchers
    finally:
        layer.release.set()
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_and_joins_background_reconcile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "chat.db"
    _conversation, participant = _room(path)
    layer = _BlockingNativeSessionLayer(_accepting_snapshot())
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    monkeypatch.setattr(native_runtime_module, "_RECONCILE_TIMEOUT_S", 0.01)
    await runtime.reconcile_all()
    task = runtime._reconcile_tasks[participant.participant_id]

    await runtime.shutdown()

    assert task.cancelled() is True
    assert layer.cancelled_ensures == 1
    assert runtime._reconcile_tasks == {}
    assert runtime._watchers == {}


@pytest.mark.asyncio
async def test_failed_native_action_restores_hold_from_observed_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    conversation, participant = _room(path)
    session = opaque_guard("session")
    goal = opaque_guard("goal")
    settings = opaque_guard("settings")
    snapshot: dict[str, object] = {
        "goal": None,
        "settings": {"model": "gpt-test", "effort": "medium"},
        "active_turn": False,
        "guards": {
            "session": session,
            "goal": goal,
            "settings": settings,
            "turn": None,
        },
    }
    layer = _FailingNativeSessionLayer(snapshot)
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    try:
        await runtime.reconcile_all()
        bridge = RoomCodexBridgeStore(path)
        action, created = bridge.request_action(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            capability_id="goal_get",
            safe_request={},
            client_action_id="action-1",
            expected_session_guard=session,
            expected_goal_guard=goal,
            expected_settings_guard=settings,
        )
        assert created is True

        assert await runtime.pump_action_once() is True

        hold = bridge.get_hold(participant.participant_id)
        assert hold is not None and hold["state"] == "accepting"
        with RoomDatabase(path).connect(readonly=True) as conn:
            row = conn.execute(
                """select status, reason_code, execution_stage, failure_stage
                   from room_codex_bridge_actions where action_id = ?""",
                (action["action_id"],),
            ).fetchone()
        assert tuple(row) == (
            "failed",
            "codex_native_action_result_unknown",
            "completed",
            "dispatching",
        )
    finally:
        await runtime.shutdown()
    assert layer.stream.closed is True


@pytest.mark.asyncio
async def test_action_rebinds_once_before_dispatch_and_invokes_provider_exactly_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    conversation, participant = _room(path)
    session = opaque_guard("session")
    goal = opaque_guard("goal")
    settings = opaque_guard("settings")
    layer = _SuccessfulNativeSessionLayer(
        {
            "goal": None,
            "settings": {"model": "gpt-test", "effort": "medium"},
            "active_turn": False,
            "guards": {
                "session": session,
                "goal": goal,
                "settings": settings,
                "turn": None,
            },
        }
    )
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    bridge = RoomCodexBridgeStore(path)
    try:
        await runtime.reconcile_all()
        action, _created = bridge.request_action(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            capability_id="goal_get",
            safe_request={},
            client_action_id="action-rebind",
            expected_session_guard=session,
            expected_goal_guard=goal,
            expected_settings_guard=settings,
        )
        layer.fail_next_snapshot = True

        assert await runtime.pump_action_once() is True

        with RoomDatabase(path).connect(readonly=True) as conn:
            row = conn.execute(
                """select status, execution_stage, failure_stage
                   from room_codex_bridge_actions where action_id = ?""",
                (action["action_id"],),
            ).fetchone()
        assert tuple(row) == ("applied", "completed", None)
        assert layer.ensure_force_rebind[-2:] == [False, True]
        assert layer.invoke_count == 1
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_provider_ack_is_durable_before_best_effort_post_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    conversation, participant = _room(path)
    session = opaque_guard("session")
    goal = opaque_guard("goal")
    settings = opaque_guard("settings")
    layer = _SuccessfulNativeSessionLayer(
        {
            "goal": None,
            "settings": {"model": "gpt-test", "effort": "medium"},
            "active_turn": False,
            "guards": {
                "session": session,
                "goal": goal,
                "settings": settings,
                "turn": None,
            },
        }
    )
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    bridge = RoomCodexBridgeStore(path)
    try:
        await runtime.reconcile_all()
        action, _created = bridge.request_action(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            capability_id="goal_get",
            safe_request={},
            client_action_id="action-post-snapshot",
            expected_session_guard=session,
            expected_goal_guard=goal,
            expected_settings_guard=settings,
        )
        layer.fail_post_invoke_snapshot = True

        assert await runtime.pump_action_once() is True

        with RoomDatabase(path).connect(readonly=True) as conn:
            row = conn.execute(
                """select status, execution_stage, reason_code, ack_summary_json
                   from room_codex_bridge_actions where action_id = ?""",
                (action["action_id"],),
            ).fetchone()
        assert tuple(row) == (
            "applied",
            "completed",
            None,
            '{"acknowledged":true}',
        )
        assert layer.invoke_count == 1
        hold = bridge.get_hold(participant.participant_id)
        assert hold is not None and hold["state"] == "native_unavailable"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_native_unavailable_rebinds_dead_session_and_replaces_watcher(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    conversation, participant = _room(path)
    session = opaque_guard("session")
    layer = _FailingNativeSessionLayer(
        {
            "goal": None,
            "settings": {"model": "gpt-test", "effort": "medium"},
            "active_turn": False,
            "guards": {
                "session": session,
                "goal": opaque_guard("goal"),
                "settings": opaque_guard("settings"),
                "turn": None,
            },
        }
    )
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    bridge = RoomCodexBridgeStore(path)
    try:
        await runtime.reconcile_all()
        prior_stream = layer.stream
        bridge.begin_reconcile(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            session_guard=session,
            reason_code="codex_native_unavailable",
        )
        bridge.apply_native_snapshot(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            expected_session_guard=session,
            state="native_unavailable",
            goal_guard=None,
            settings_guard=None,
            active_turn_guard=None,
            reason_code="codex_native_unavailable",
        )

        await runtime.reconcile_all()

        hold = bridge.get_hold(participant.participant_id)
        assert hold is not None and hold["state"] == "accepting"
        assert layer.ensure_force_rebind == [False, True]
        assert prior_stream.closed is True
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_late_rebind_does_not_replace_watcher_for_same_incarnation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    conversation, participant = _room(path)
    session = opaque_guard("session")
    layer = _FailingNativeSessionLayer(
        {
            "goal": None,
            "settings": {"model": "gpt-test", "effort": "medium"},
            "active_turn": False,
            "guards": {
                "session": session,
                "goal": opaque_guard("goal"),
                "settings": opaque_guard("settings"),
                "turn": None,
            },
        },
        replace_on_force=False,
    )
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    bridge = RoomCodexBridgeStore(path)
    try:
        await runtime.reconcile_all()
        prior_stream = layer.stream
        bridge.begin_reconcile(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            session_guard=session,
            reason_code="codex_native_unavailable",
        )
        bridge.apply_native_snapshot(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            expected_session_guard=session,
            state="native_unavailable",
            goal_guard=None,
            settings_guard=None,
            active_turn_guard=None,
            reason_code="codex_native_unavailable",
        )

        await runtime.reconcile_all()

        assert layer.ensure_force_rebind == [False, True]
        assert prior_stream.closed is False
        assert runtime._watchers[participant.participant_id][1] is prior_stream
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_native_turn_event_closes_delivery_hold_before_next_room_claim(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    _conversation, participant = _room(path)
    session = opaque_guard("session")
    layer = _FailingNativeSessionLayer(
        {
            "goal": None,
            "settings": {"model": "gpt-test", "effort": "medium"},
            "active_turn": False,
            "guards": {
                "session": session,
                "goal": opaque_guard("goal"),
                "settings": opaque_guard("settings"),
                "turn": None,
            },
        }
    )
    layer.stream = _QueueEventStream()
    runtime = RoomCodexNativeRuntime(
        path,
        layer,  # type: ignore[arg-type]
        worktree=tmp_path,
        runner_generation="runner-1",
    )
    bridge = RoomCodexBridgeStore(path)
    try:
        await runtime.reconcile_all()
        assert runtime.accepts_delivery(participant.participant_id) is True
        layer.snapshot = {
            **layer.snapshot,
            "active_turn": True,
            "guards": {
                **dict(layer.snapshot["guards"]),  # type: ignore[arg-type]
                "turn": opaque_guard("turn-active"),
            },
        }
        await layer.stream.queue.put(
            {
                "method": "turn/started",
                "params": {"turn": {"id": "private-turn", "status": "inProgress"}},
            }
        )
        for _ in range(100):
            hold = bridge.get_hold(participant.participant_id)
            if hold is not None and hold["state"] == "turn_active":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("native event did not close the durable delivery hold")
        assert runtime.accepts_delivery(participant.participant_id) is False
    finally:
        await runtime.shutdown()
