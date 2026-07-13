from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.xmuse.room_fixtures import (
    RoomTestStore,
)
from tests.xmuse.room_fixtures import (
    TestConversation as RoomFixtureConversation,
)
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
    assert store.room_participant_work_counts(participant.conversation_id)[participant_id][
        "active_attempt_count"
    ] == 0


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
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.stream = _NeverEventStream()

    def prompt_fingerprint_for_resume(self, **kwargs: object) -> str:
        return str(kwargs["proposed_fingerprint"])

    async def ensure_conversation_session(self, **_kwargs: object) -> object:
        return object()

    def require_live_provider_session_binding(self, **_kwargs: object) -> object:
        return SimpleNamespace(god_session_id="god-session")

    async def native_snapshot(self, _god_session_id: str) -> dict[str, object]:
        return self.snapshot

    async def discover_native_capabilities(self, _god_session_id: str) -> dict[str, object]:
        return {"schema_version": "room_codex_native_capabilities/v1", "capabilities": []}

    def subscribe_native_events(self, _god_session_id: str) -> object:
        return self.stream

    async def invoke_native(self, *_args: object, **_kwargs: object) -> object:
        raise RoomCodexBridgeError("codex_native_runtime_test_failure")


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
                "select status, reason_code from room_codex_bridge_actions where action_id = ?",
                (action["action_id"],),
            ).fetchone()
        assert tuple(row) == ("failed", "codex_native_runtime_test_failure")
    finally:
        await runtime.shutdown()
    assert layer.stream.closed is True


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
