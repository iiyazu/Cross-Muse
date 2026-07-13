"""Room Runner ownership for native Codex reconciliation and bridge actions."""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.chat.participant_session_identity import (
    participant_session_prompt_fingerprint,
)
from xmuse_core.chat.participant_store import INIT_GOD_ROLE, Participant, ParticipantStore
from xmuse_core.chat.room_codex_bridge import (
    HoldState,
    RoomCodexBridgeError,
    RoomCodexBridgeStore,
    opaque_guard,
)
from xmuse_core.chat.room_codex_projection_cache import (
    RoomCodexProjectionCache,
    RoomCodexProjectionCacheError,
)
from xmuse_core.chat.room_database import RoomDatabase

_ROOM_SESSION_SCOPE = "room_v1"
_PROVIDER_SESSION_KIND = "codex_app_server_thread"
_NATIVE_STATE_METHODS = frozenset(
    {
        "thread/goal/updated",
        "thread/goal/cleared",
        "thread/settings/updated",
        "turn/started",
        "turn/completed",
    }
)
_MAX_PARALLEL_RECONCILES = 4
_RECONCILE_TIMEOUT_S = 5.0


class _SnapshotGuards(TypedDict):
    session: str
    goal: str | None
    settings: str | None
    turn: str | None


class RoomCodexNativeRuntime:
    def __init__(
        self,
        db_path: Path | str,
        session_layer: GodSessionLayer,
        *,
        worktree: Path | str,
        runner_generation: str,
        projection_cache: RoomCodexProjectionCache | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._sessions = session_layer
        self._worktree = Path(worktree)
        self._runner_generation = runner_generation
        self._projection_cache = projection_cache
        self._projection_cache_error: str | None = None
        self._participants = ParticipantStore(self._db_path)
        self._bridge = RoomCodexBridgeStore(self._db_path)
        self._capabilities: dict[str, dict[str, object]] = {}
        self._capability_session_guards: dict[str, str] = {}
        self._watchers: dict[str, tuple[str, object, asyncio.Task[None]]] = {}

    def accepts_delivery(self, participant_id: str) -> bool:
        return self._bridge.participant_accepts_delivery(participant_id)

    def initialize_projection_cache(self) -> None:
        if self._projection_cache is None:
            return
        try:
            self._projection_cache.initialize()
            self._projection_cache_error = None
        except RoomCodexProjectionCacheError as exc:
            self._projection_cache_error = exc.code

    async def reconcile_all(self) -> None:
        semaphore = asyncio.Semaphore(_MAX_PARALLEL_RECONCILES)

        async def reconcile_one(participant: Participant) -> None:
            try:
                async with semaphore:
                    await asyncio.wait_for(
                        self.reconcile_participant(participant),
                        timeout=_RECONCILE_TIMEOUT_S,
                    )
            except asyncio.CancelledError:
                raise
            except RoomCodexBridgeError as exc:
                if exc.code == "codex_native_action_pending":
                    return
                self._mark_native_unavailable(participant)
            except Exception:
                self._mark_native_unavailable(participant)

        await asyncio.gather(*(reconcile_one(item) for item in self._active_participants()))

    async def reconcile_participant(
        self, participant: Participant, *, force: bool = False
    ) -> dict[str, object]:
        if not force and self._bridge.participant_has_unfinished_action(
            participant.participant_id
        ):
            raise RoomCodexBridgeError("codex_native_action_pending")
        record = await self._ensure_session(participant)
        self._ensure_watcher(participant, record)
        snapshot = await self._sessions.native_snapshot(record.god_session_id)
        guards = _snapshot_guards(snapshot)
        session_guard = guards["session"]
        hold = self._bridge.get_hold(participant.participant_id)
        if hold is None or hold.get("session_guard") != session_guard:
            self._bridge.begin_reconcile(
                conversation_id=participant.conversation_id,
                participant_id=participant.participant_id,
                session_guard=session_guard,
            )
        if self._capability_session_guards.get(participant.participant_id) != session_guard:
            capabilities = await self._sessions.discover_native_capabilities(
                record.god_session_id
            )
            self._capabilities[participant.participant_id] = capabilities
            self._capability_session_guards[participant.participant_id] = session_guard
        self._apply_snapshot(participant, snapshot)
        self._replace_cached_current(
            participant,
            snapshot=snapshot,
            capabilities=self._capabilities[participant.participant_id],
        )
        return snapshot

    async def pump_action_once(self) -> bool:
        action = self._bridge.claim_next_action(
            runner_generation=self._runner_generation
        )
        if action is None:
            return False
        await self.execute_claimed_action(action)
        return True

    async def execute_claimed_action(self, action: Mapping[str, object]) -> None:
        action_id = str(action["action_id"])
        participant: Participant | None = None
        try:
            participant = self._participants.get(str(action["participant_id"]))
            record = await self._ensure_session(participant)
            before = await self._sessions.native_snapshot(record.god_session_id)
            _assert_action_guards(action, before)
            _assert_action_policy(self._db_path, action, before)
            self._bridge.begin_reconcile(
                conversation_id=participant.conversation_id,
                participant_id=participant.participant_id,
                session_guard=_snapshot_guards(before)["session"],
                reason_code="codex_native_action_applying",
            )
            safe_request = action.get("safe_request")
            if not isinstance(safe_request, dict):
                raise RoomCodexBridgeError("codex_native_request_shape_invalid")
            result = await self._sessions.invoke_native(
                record.god_session_id,
                str(action["capability_id"]),
                safe_request,
                resolved_review_target=_resolved_review_target(
                    str(action["capability_id"]), safe_request, self._worktree
                ),
            )
            after = await self._sessions.native_snapshot(record.god_session_id)
            self._apply_snapshot(participant, after)
            self._bridge.complete_action(
                action_id=action_id,
                runner_generation=self._runner_generation,
                status="applied",
                reason_code=None,
                ack_summary=result.safe_ack,
            )
        except Exception as exc:
            code = _reason_code(exc)
            self._bridge.complete_action(
                action_id=action_id,
                runner_generation=self._runner_generation,
                status="rejected" if code.endswith("_conflict") else "failed",
                reason_code=code,
            )
            if participant is not None:
                try:
                    await self.reconcile_participant(participant, force=True)
                except asyncio.CancelledError:
                    raise
                except RoomCodexBridgeError as exc:
                    if exc.code != "codex_native_action_pending":
                        self._mark_native_unavailable(participant)
                except Exception:
                    self._mark_native_unavailable(participant)

    def capabilities_for_participant(self, participant_id: str) -> dict[str, object] | None:
        value = self._capabilities.get(participant_id)
        return dict(value) if value is not None else None

    @property
    def projection_cache_error(self) -> str | None:
        return self._projection_cache_error

    async def shutdown(self) -> None:
        watchers = list(self._watchers.values())
        self._watchers.clear()
        for _session_id, stream, task in watchers:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            task.cancel()
        if watchers:
            await asyncio.gather(*(item[2] for item in watchers), return_exceptions=True)

    async def _ensure_session(self, participant: Participant) -> GodSessionRecord:
        proposed = participant_session_prompt_fingerprint(participant)
        fingerprint = self._sessions.prompt_fingerprint_for_resume(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            feature_scope_id=_ROOM_SESSION_SCOPE,
            proposed_fingerprint=proposed,
        )
        await self._sessions.ensure_conversation_session(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            role=participant.role,
            agent=AgentDescriptor(
                name=participant.display_name,
                runtime=AgentRuntime.CODEX,
                capabilities=[participant.role],
            ),
            worktree=self._worktree,
            model=participant.model,
            prompt_fingerprint=fingerprint,
            feature_scope_id=_ROOM_SESSION_SCOPE,
        )
        return self._sessions.require_live_provider_session_binding(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            runtime=AgentRuntime.CODEX,
            provider_session_kind=_PROVIDER_SESSION_KIND,
            feature_scope_id=_ROOM_SESSION_SCOPE,
        )

    def _apply_snapshot(
        self, participant: Participant, snapshot: Mapping[str, object]
    ) -> None:
        guards = _snapshot_guards(snapshot)
        goal = snapshot.get("goal")
        goal_active = isinstance(goal, Mapping) and goal.get("status") == "active"
        state: HoldState = (
            "goal_active"
            if goal_active
            else "turn_active"
            if snapshot.get("active_turn") is True
            else "accepting"
        )
        self._bridge.apply_native_snapshot(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            expected_session_guard=guards["session"],
            state=state,
            goal_guard=guards.get("goal"),
            settings_guard=guards.get("settings"),
            active_turn_guard=guards.get("turn"),
            reason_code=None if state == "accepting" else f"codex_native_{state}",
        )

    def _active_participants(self) -> list[Participant]:
        with RoomDatabase(self._db_path).connect(readonly=True) as conn:
            conversation_ids = [
                str(row[0])
                for row in conn.execute("select id from conversations order by created_at, id")
            ]
        return [
            participant
            for conversation_id in conversation_ids
            for participant in self._participants.list_by_conversation(conversation_id)
            if participant.status == "active"
            and participant.role != INIT_GOD_ROLE
            and participant.cli_kind == "codex"
        ]

    def _ensure_watcher(
        self, participant: Participant, record: GodSessionRecord
    ) -> None:
        prior = self._watchers.get(participant.participant_id)
        if prior is not None and prior[0] == record.god_session_id and not prior[2].done():
            return
        if prior is not None:
            close = getattr(prior[1], "close", None)
            if callable(close):
                close()
            prior[2].cancel()
        stream = self._sessions.subscribe_native_events(record.god_session_id)
        task = asyncio.create_task(
            self._watch_native_events(participant, stream),
            name=f"room-codex-native-events:{participant.participant_id}",
        )
        self._watchers[participant.participant_id] = (
            record.god_session_id,
            stream,
            task,
        )

    async def _watch_native_events(self, participant: Participant, stream: object) -> None:
        receive = getattr(stream, "receive", None)
        if not callable(receive):
            return
        try:
            while True:
                event = await receive()
                if not isinstance(event, dict):
                    continue
                self._append_cached_event(participant, event)
                if event.get("method") not in _NATIVE_STATE_METHODS:
                    continue
                hold = self._bridge.get_hold(participant.participant_id)
                if hold is not None and isinstance(hold.get("session_guard"), str):
                    self._bridge.begin_reconcile(
                        conversation_id=participant.conversation_id,
                        participant_id=participant.participant_id,
                        session_guard=str(hold["session_guard"]),
                        reason_code="codex_native_event_pending",
                    )
                await asyncio.sleep(0)
                try:
                    await self.reconcile_participant(participant)
                except asyncio.CancelledError:
                    raise
                except RoomCodexBridgeError as exc:
                    if exc.code != "codex_native_action_pending":
                        self._mark_native_unavailable(participant)
                except Exception:
                    self._mark_native_unavailable(participant)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._mark_native_unavailable(participant)

    def _replace_cached_current(
        self,
        participant: Participant,
        *,
        snapshot: Mapping[str, object],
        capabilities: Mapping[str, object],
    ) -> None:
        if self._projection_cache is None:
            return
        try:
            self._projection_cache.replace_current(
                conversation_id=participant.conversation_id,
                participant_id=participant.participant_id,
                snapshot=snapshot,
                capabilities=capabilities,
                history_partial=True,
            )
            self._projection_cache_error = None
        except RoomCodexProjectionCacheError as exc:
            self._projection_cache_error = exc.code

    def _append_cached_event(
        self, participant: Participant, event: Mapping[str, object]
    ) -> None:
        if self._projection_cache is None:
            return
        try:
            self._projection_cache.append_notification(
                conversation_id=participant.conversation_id,
                participant_id=participant.participant_id,
                notification=event,
            )
            self._projection_cache_error = None
        except RoomCodexProjectionCacheError as exc:
            self._projection_cache_error = exc.code

    def _mark_native_unavailable(self, participant: Participant) -> None:
        fallback_guard = opaque_guard(
            "room-codex-native-unavailable",
            participant.participant_id,
            participant_session_prompt_fingerprint(participant),
        )
        hold = self._bridge.get_hold(participant.participant_id)
        if hold is not None and hold.get("state") == "native_unavailable":
            return
        session_guard = (
            str(hold["session_guard"])
            if hold is not None and isinstance(hold.get("session_guard"), str)
            else fallback_guard
        )
        self._bridge.begin_reconcile(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            session_guard=session_guard,
            reason_code="codex_native_unavailable",
        )
        self._bridge.apply_native_snapshot(
            conversation_id=participant.conversation_id,
            participant_id=participant.participant_id,
            expected_session_guard=session_guard,
            state="native_unavailable",
            goal_guard=None,
            settings_guard=None,
            active_turn_guard=None,
            reason_code="codex_native_unavailable",
        )


async def run_room_codex_native_loop(
    runtime: RoomCodexNativeRuntime,
    *,
    stop: asyncio.Event,
    started: asyncio.Event | None = None,
    idle_wait_s: float = 0.25,
    reconcile_interval_s: float = 1.0,
) -> None:
    runtime.initialize_projection_cache()
    runtime._bridge.fence_interrupted_actions()
    await runtime.reconcile_all()
    if started is not None:
        started.set()
    active: set[asyncio.Task[None]] = set()
    loop = asyncio.get_running_loop()
    next_reconcile = loop.time() + reconcile_interval_s
    try:
        while not stop.is_set():
            for task in tuple(active):
                if task.done():
                    active.remove(task)
                    task.result()
            while len(active) < _MAX_PARALLEL_RECONCILES:
                action = runtime._bridge.claim_next_action(
                    runner_generation=runtime._runner_generation
                )
                if action is None:
                    break
                active.add(
                    asyncio.create_task(
                        runtime.execute_claimed_action(action),
                        name=f"room-codex-native-action:{action['participant_id']}",
                    )
                )
            if loop.time() >= next_reconcile:
                await runtime.reconcile_all()
                next_reconcile = loop.time() + reconcile_interval_s
            waiters: set[asyncio.Task[object]] = set(active)
            stop_wait = asyncio.create_task(stop.wait(), name="room-codex-native-stop")
            waiters.add(stop_wait)
            try:
                await asyncio.wait(
                    waiters,
                    timeout=idle_wait_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                if not stop_wait.done():
                    stop_wait.cancel()
                await asyncio.gather(stop_wait, return_exceptions=True)
    finally:
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)


def _snapshot_guards(snapshot: Mapping[str, object]) -> _SnapshotGuards:
    raw = snapshot.get("guards")
    if not isinstance(raw, Mapping):
        raise RoomCodexBridgeError("codex_native_snapshot_guard_invalid")
    values: dict[str, str | None] = {}
    for key in ("session", "goal", "settings", "turn"):
        value = raw.get(key)
        if value is not None and (
            not isinstance(value, str) or not value.startswith("sha256:")
        ):
            raise RoomCodexBridgeError("codex_native_snapshot_guard_invalid")
        values[key] = value
    session = values["session"]
    if session is None:
        raise RoomCodexBridgeError("codex_native_snapshot_guard_invalid")
    return {
        "session": session,
        "goal": values["goal"],
        "settings": values["settings"],
        "turn": values["turn"],
    }


def _assert_action_guards(
    action: Mapping[str, object], snapshot: Mapping[str, object]
) -> None:
    guards = _snapshot_guards(snapshot)
    for action_key, guard_key in (
        ("expected_session_guard", "session"),
        ("expected_goal_guard", "goal"),
        ("expected_settings_guard", "settings"),
        ("expected_turn_guard", "turn"),
    ):
        expected = action.get(action_key)
        if expected is not None and expected != guards.get(guard_key):
            raise RoomCodexBridgeError(f"codex_native_{guard_key}_guard_conflict")


def _assert_action_policy(
    db_path: Path, action: Mapping[str, object], snapshot: Mapping[str, object]
) -> None:
    capability = action.get("capability_id")
    participant_id = action.get("participant_id")
    if capability in {"goal_set", "turn_steer", "turn_interrupt"}:
        with RoomDatabase(db_path).connect(readonly=True) as conn:
            active = conn.execute(
                """select 1 from room_observation_attempts
                   where participant_id = ? and (
                       state in ('claimed','delivering','cancel_requested','cancel_pending')
                       or provider_phase in ('ensure_started','cleanup_pending')
                       or recovery_state in ('fenced','cleanup_pending')
                   ) limit 1""",
                (participant_id,),
            ).fetchone()
        if active is not None:
            code = (
                "codex_native_delivery_conflict"
                if capability == "goal_set"
                else "codex_native_room_turn_conflict"
            )
            raise RoomCodexBridgeError(code)
    if capability == "goal_clear":
        goal = snapshot.get("goal")
        status = goal.get("status") if isinstance(goal, Mapping) else None
        if status not in {"paused", "blocked", "usageLimited", "budgetLimited", "complete"}:
            raise RoomCodexBridgeError("codex_native_goal_clear_conflict")
        if snapshot.get("active_turn") is True:
            raise RoomCodexBridgeError("codex_native_turn_guard_conflict")


def _resolved_review_target(
    capability_id: str,
    request: Mapping[str, object],
    worktree: Path,
) -> dict[str, object] | None:
    if capability_id != "review_start":
        return None
    target = request.get("target")
    if target == "uncommitted":
        return {"type": "uncommittedChanges"}
    if target == "base":
        branch = _resolve_review_base(worktree)
        if branch is not None:
            return {"type": "baseBranch", "branch": branch}
    if target == "commit":
        sha = _git_output(worktree, "rev-parse", "--verify", "HEAD^{commit}")
        if sha is not None and re.fullmatch(r"[0-9a-f]{40,64}", sha):
            title = _git_output(worktree, "log", "-1", "--format=%s")
            return {
                "type": "commit",
                "sha": sha,
                "title": title[:200] if title is not None else None,
            }
    raise RoomCodexBridgeError("codex_native_review_target_unresolved")


def _resolve_review_base(worktree: Path) -> str | None:
    remote_head = _git_output(
        worktree,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
    )
    if remote_head is not None and re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", remote_head):
        return remote_head
    for branch, ref in (
        ("origin/main", "refs/remotes/origin/main"),
        ("main", "refs/heads/main"),
        ("master", "refs/heads/master"),
    ):
        if _git_status(worktree, "show-ref", "--verify", "--quiet", ref):
            return branch
    return None


def _git_output(worktree: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=worktree,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value and len(value.encode("utf-8")) <= 512 else None


def _git_status(worktree: Path, *arguments: str) -> bool:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=worktree,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _reason_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else "codex_native_action_failed"


__all__ = [
    "RoomCodexNativeRuntime",
    "run_room_codex_native_loop",
]
