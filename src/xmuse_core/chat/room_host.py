"""Transport-neutral participant-owned room observation host."""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Literal, Protocol

from xmuse_core.chat.participant_store import INIT_GOD_ROLE, Participant, ParticipantStore
from xmuse_core.chat.room_context_selection import (
    memory_excluded_activity_ids,
    select_room_context,
)
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_execution_store import RoomExecutionStore, RoomExecutionStoreError
from xmuse_core.chat.room_kernel import OUTCOME_ORDER, RoomKernelStore
from xmuse_core.chat.room_memory_runtime import (
    ROOM_MEMORY_RECALL_TIMEOUT_S,
    RoomMemoryEvidence,
    RoomMemoryRecallInput,
    RoomMemoryRuntime,
    disabled_memory_evidence,
)
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog
from xmuse_core.skills.models import RoomSkillActivation


def _positive_real(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}_invalid")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name}_invalid")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name}_invalid")
    return value


@dataclass(frozen=True)
class RoomHostPolicy:
    delivery_timeout_s: float = 180.0
    cleanup_grace_s: float = 5.0
    lease_ttl_s: float = 240.0
    participant_cooldown_s: float = 2.0
    max_attempts_per_observation: int = 3
    max_batch_size: int = 4
    context_activity_limit: int = 8
    max_activity_payload_chars: int = 4000

    def __post_init__(self) -> None:
        for name in ("delivery_timeout_s", "cleanup_grace_s", "lease_ttl_s"):
            _positive_real(getattr(self, name), name)
        if (
            isinstance(self.participant_cooldown_s, bool)
            or not isinstance(self.participant_cooldown_s, (int, float))
            or not math.isfinite(float(self.participant_cooldown_s))
            or (self.participant_cooldown_s < 0)
        ):
            raise ValueError("participant_cooldown_s_invalid")
        for name in (
            "max_attempts_per_observation",
            "max_batch_size",
            "context_activity_limit",
            "max_activity_payload_chars",
        ):
            _positive_int(getattr(self, name), name)
        if self.lease_ttl_s <= self.delivery_timeout_s + self.cleanup_grace_s:
            raise ValueError("lease_ttl_s_too_short")


_DEFAULT_ROOM_HOST_POLICY = RoomHostPolicy()
_RUNNER_RECOVERY_FINALIZE_RACES = frozenset(
    {
        "room_attempt_generation_lost",
        "room_runner_recovery_cancel_pending",
        "room_runner_recovery_cleanup_unproven",
        "room_runner_recovery_not_finalizable",
    }
)


@dataclass(frozen=True)
class RoomObservationDelivery:
    conversation_id: str
    participant: Participant
    observation: dict[str, Any]
    source_activity: dict[str, Any]
    recent_activities: tuple[dict[str, Any], ...]
    active_participants: tuple[dict[str, Any], ...]
    transport_request_id: str
    outcome_client_request_id: str
    attempt_id: str | None = None
    skill_activation: RoomSkillActivation | None = None
    allowed_outcomes: tuple[str, ...] = OUTCOME_ORDER
    outcome_policy_reason: str = "unrestricted"
    batch: dict[str, Any] | None = None
    human_root: dict[str, Any] | None = None
    causal_ancestry: tuple[dict[str, Any], ...] = ()
    context_coverage: dict[str, Any] | None = None
    execution_review_materials: tuple[dict[str, Any], ...] = ()
    memory_evidence: RoomMemoryEvidence = field(default_factory=disabled_memory_evidence)


@dataclass(frozen=True)
class RoomTransportResult:
    status: Literal["finished", "failed"]
    reason: str | None = None
    diagnostic_text: str | None = None


@dataclass(frozen=True)
class RoomCancelReconcileResult:
    status: Literal["settled", "pending"]
    reason: str | None = None


class RoomObservationTransport(Protocol):
    async def deliver(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> RoomTransportResult: ...


@dataclass(frozen=True)
class RoomHostDeliveryOutcome:
    participant_id: str
    observation_id: str
    attempt_count: int
    state: Literal["completed", "incomplete", "failed", "lease_lost", "cancelled", "cancel_pending"]
    reason: str | None
    retryable: bool
    retry_at: str | None
    outcome_type: str | None
    transport_status: str | None
    diagnostic_text: str | None


@dataclass(frozen=True)
class RoomHostDeferral:
    participant_id: str
    observation_id: str
    reason: Literal[
        "lease_active",
        "cooldown",
        "attempts_exhausted",
        "batch_budget",
        "claim_race",
        "native_hold",
    ]
    retryable: bool
    retry_at: str | None


@dataclass(frozen=True)
class RoomHostBatchOutcome:
    conversation_id: str
    deliveries: tuple[RoomHostDeliveryOutcome, ...]
    deferrals: tuple[RoomHostDeferral, ...]


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class _DeliveryPermit:
    """Own one host-wide provider turn slot until its transport has stopped."""

    def __init__(self, semaphore: asyncio.Semaphore) -> None:
        self._semaphore = semaphore
        self._started = False
        self._released = False

    def mark_started(self) -> None:
        self._started = True

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._semaphore.release()

    def release_if_unstarted(self, _task: asyncio.Task[Any]) -> None:
        # A task cancelled before its first step never enters its coroutine's
        # ``finally`` block, so its creator remains responsible for the permit.
        if not self._started:
            self.release()


@dataclass(frozen=True)
class _ActiveDelivery:
    observation_id: str
    attempt_id: str
    participant_id: str
    control_seq: int
    task: asyncio.Task[RoomHostDeliveryOutcome]


class RoomParticipantHost:
    def __init__(
        self,
        db_path: Path | str,
        transport: RoomObservationTransport,
        *,
        policy: RoomHostPolicy = _DEFAULT_ROOM_HOST_POLICY,
        clock: Callable[[], datetime] | None = None,
        control_store: RoomObservationControlStore | None = None,
        skill_catalog: SkillCatalog | None = None,
        skill_decision_store: RoomAttemptSkillDecisionStore | None = None,
        execution_store: RoomExecutionStore | None = None,
        memory_runtime: RoomMemoryRuntime | None = None,
        runner_generation: str | None = None,
        runner_boot_id: str | None = None,
        delivery_gate: Callable[[str], bool] | None = None,
    ) -> None:
        if (runner_generation is None) != (runner_boot_id is None):
            raise ValueError("room_runner_identity_pair_required")
        if runner_generation is not None and (
            not isinstance(runner_generation, str)
            or not runner_generation.strip()
            or not isinstance(runner_boot_id, str)
            or not runner_boot_id.strip()
        ):
            raise ValueError("room_runner_identity_invalid")
        self._db_path = Path(db_path)
        self._transport = transport
        self._policy = policy
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._boot_uuid = uuid.uuid4().hex
        self._delivery_slots = asyncio.Semaphore(policy.max_batch_size)
        self._controls = control_store or RoomObservationControlStore(self._db_path)
        self._skill_catalog = skill_catalog or SkillCatalog.load_bundled()
        self._skill_decisions = skill_decision_store or RoomAttemptSkillDecisionStore(self._db_path)
        self._execution_store = execution_store
        self._memory_runtime = memory_runtime
        self._memory_recall_attention_reason: str | None = None
        self._memory_outbox_attention_reason: str | None = None
        self._skill_runtime_unhealthy_reason: str | None = None
        self._active_deliveries: dict[str, _ActiveDelivery] = {}
        self._retained_tasks: set[asyncio.Task[Any]] = set()
        self._retained_permits: dict[asyncio.Task[Any], _DeliveryPermit] = {}
        self._retained_controls: dict[asyncio.Task[Any], tuple[str, str]] = {}
        self._runner_generation = runner_generation
        self._runner_boot_id = runner_boot_id
        self._delivery_gate = delivery_gate

    def runtime_health_snapshot(self) -> dict[str, Any]:
        """Return a bounded operational snapshot without Room or provider authority."""

        unhealthy_reason = self._skill_runtime_unhealthy_reason
        if unhealthy_reason is not None:
            code = (
                unhealthy_reason
                if isinstance(unhealthy_reason, str)
                and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", unhealthy_reason) is not None
                else "room_host_skill_runtime_unhealthy"
            )
            state = "blocked"
        elif self._retained_tasks:
            state = "attention"
            code = "room_transport_cleanup_pending"
        elif (
            self._memory_recall_attention_reason is not None
            or self._memory_outbox_attention_reason is not None
        ):
            state = "attention"
            code = "room_memory_degraded"
        else:
            state = "healthy"
            code = "ready"
        return {
            "state": state,
            "code": code,
            "active_delivery_count": len(self._active_deliveries),
            "retained_cleanup_count": len(self._retained_tasks),
        }

    def set_memory_runtime_attention(self, reason_code: str | None) -> None:
        """Publish optional derived-index health without blocking Room delivery."""

        self._memory_outbox_attention_reason = reason_code

    async def shutdown(self) -> None:
        """Cancel and drain transport tasks retained after timeout cleanup."""

        tasks = tuple(self._retained_tasks)
        for task in tasks:
            task.cancel()
        if not tasks:
            return
        done, _pending = await asyncio.wait(
            tasks,
            timeout=self._policy.cleanup_grace_s,
        )
        for task in done:
            self._retain_done(task)

    def list_claimable_conversation_ids(self) -> list[str]:
        """Return rooms that have a dispatchable durable participant frontier."""

        if self._skill_runtime_unhealthy_reason is not None:
            return []
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("room_host_clock_timezone_required")
        self._controls.reconcile_attempt_limit(self._policy.max_attempts_per_observation)
        kernel = RoomKernelStore(self._db_path)
        if self._delivery_gate is None:
            return kernel.list_claimable_conversation_ids(
                max_attempts_per_observation=self._policy.max_attempts_per_observation,
                now=now,
            )
        frontiers = kernel.list_claimable_room_participants(
            max_attempts_per_observation=self._policy.max_attempts_per_observation,
            now=now,
        )
        return list(
            dict.fromkeys(
                conversation_id
                for conversation_id, participant_id in frontiers
                if self._delivery_gate(participant_id)
            )
        )

    def fence_prior_runner_attempts(self) -> dict[str, Any] | None:
        """Fence attempts owned by prior boots before this Host may claim work.

        Compatibility Hosts have no process boot identity and retain the lease-expiry
        behavior they had before the isolated Room Runner existed.
        """

        if self._runner_generation is None or self._runner_boot_id is None:
            return None
        return self._controls.fence_prior_runner_attempts(
            current_runner_generation=self._runner_generation,
            current_runner_boot_id=self._runner_boot_id,
            base_attempt_limit=self._policy.max_attempts_per_observation,
            now=self._clock(),
        )

    async def reconcile_runner_recoveries(self) -> None:
        """Prove provider cleanup before reopening attempts fenced at startup."""

        if self._runner_generation is None or self._runner_boot_id is None:
            return
        retained_observations = {
            observation_id for observation_id, _attempt_id in self._retained_controls.values()
        }
        for pending in self._controls.list_pending_runner_recoveries():
            # Cancel/retry controls own their own state machine. In particular, a
            # cancelled observation must never be reopened as crash recovery.
            if pending.get("control_state", "active") not in {"active", "exhausted"}:
                continue
            observation_id = str(pending.get("observation_id") or "")
            current_attempt = pending.get("reconcile_binding") or {}
            attempt_id = str(current_attempt.get("attempt_id") or "")
            if (
                not observation_id
                or not attempt_id
                or observation_id in self._active_deliveries
                or observation_id in retained_observations
            ):
                continue
            if current_attempt.get("provider_phase") == "cleanup_succeeded":
                self._finalize_runner_recovery(
                    observation_id=observation_id,
                    attempt_id=attempt_id,
                )
                continue

            reconcile = getattr(self._transport, "reconcile_cancel", None)
            if not callable(reconcile):
                self._mark_runner_recovery_cleanup(
                    observation_id=observation_id,
                    attempt_id=attempt_id,
                    succeeded=False,
                    reason_code="room_runner_recovery_reconcile_unavailable",
                )
                continue
            participants = ParticipantStore(self._db_path).list_by_conversation(
                str(pending.get("conversation_id") or "")
            )
            participant = next(
                (
                    item
                    for item in participants
                    if item.participant_id == pending.get("participant_id")
                ),
                None,
            )
            if participant is None:
                self._mark_runner_recovery_cleanup(
                    observation_id=observation_id,
                    attempt_id=attempt_id,
                    succeeded=False,
                    reason_code="room_runner_recovery_participant_missing",
                )
                continue
            try:
                reconciled = await reconcile(
                    conversation_id=str(pending["conversation_id"]),
                    participant=participant,
                    attempt=current_attempt,
                    timeout_s=self._policy.cleanup_grace_s,
                )
            except Exception:
                reconciled = RoomCancelReconcileResult(
                    "pending", "room_runner_recovery_reconcile_exception"
                )
            if not isinstance(reconciled, RoomCancelReconcileResult):
                reconciled = RoomCancelReconcileResult(
                    "pending", "room_runner_recovery_reconcile_invalid"
                )
            succeeded = reconciled.status == "settled"
            reason_code = reconciled.reason or f"room_runner_recovery_reconcile_{reconciled.status}"
            if not self._mark_runner_recovery_cleanup(
                observation_id=observation_id,
                attempt_id=attempt_id,
                succeeded=succeeded,
                reason_code=reason_code,
            ):
                continue
            if succeeded:
                self._finalize_runner_recovery(
                    observation_id=observation_id,
                    attempt_id=attempt_id,
                )

    def _finalize_runner_recovery(self, *, observation_id: str, attempt_id: str) -> bool:
        try:
            self._controls.finalize_runner_recovery(
                observation_id=observation_id,
                attempt_id=attempt_id,
                base_attempt_limit=self._policy.max_attempts_per_observation,
                now=self._clock(),
            )
        except RoomControlError as exc:
            if exc.code not in _RUNNER_RECOVERY_FINALIZE_RACES:
                raise
            return False
        return True

    def _mark_runner_recovery_cleanup(
        self,
        *,
        observation_id: str,
        attempt_id: str,
        succeeded: bool,
        reason_code: str,
    ) -> bool:
        try:
            self._controls.mark_provider_cleanup(
                observation_id=observation_id,
                attempt_id=attempt_id,
                delivery_generation=attempt_id,
                succeeded=succeeded,
                reason_code=reason_code,
                now=self._clock(),
            )
        except RoomControlError as exc:
            if exc.code != "room_attempt_generation_lost":
                raise
            return False
        return True

    async def reconcile_controls(self) -> None:
        """Apply durable cancel commands to delivery tasks owned by this Host."""

        retained_observations = {
            observation_id for observation_id, _attempt_id in self._retained_controls.values()
        }
        for pending in self._controls.list_pending_cancels():
            observation_id = str(pending["observation_id"])
            current_attempt = pending.get("reconcile_binding") or {}
            attempt_id = str(current_attempt.get("attempt_id") or "")
            control_seq = int(pending["control_seq"])
            active = self._active_deliveries.get(observation_id)
            if active is not None and active.attempt_id == attempt_id:
                if not active.task.done():
                    active.task.cancel()
                continue
            if observation_id in retained_observations:
                continue
            if not attempt_id:
                continue
            provider_phase = current_attempt.get("provider_phase", "not_started")
            if provider_phase in {"not_started", "cleanup_succeeded"}:
                try:
                    self._controls.mark_cancelled(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        expected_control_seq=control_seq,
                        reason_code=(
                            current_attempt.get("provider_cleanup_reason")
                            or "runner_reconciled_without_provider_start"
                        ),
                        now=self._clock(),
                    )
                except RoomControlError as exc:
                    if exc.code != "room_attempt_generation_lost":
                        raise
                continue
            if pending["control_state"] == "cancel_requested":
                try:
                    pending = self._controls.mark_cancel_pending(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        expected_control_seq=control_seq,
                        now=self._clock(),
                    ) | {"reconcile_binding": current_attempt}
                except RoomControlError as exc:
                    if exc.code != "room_attempt_generation_lost":
                        raise
                    continue
            reconcile = getattr(self._transport, "reconcile_cancel", None)
            if not callable(reconcile):
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        delivery_generation=attempt_id,
                        succeeded=False,
                        reason_code="room_cancel_reconcile_unavailable",
                        now=self._clock(),
                    )
                continue
            participants = ParticipantStore(self._db_path).list_by_conversation(
                str(pending["conversation_id"])
            )
            participant = next(
                (item for item in participants if item.participant_id == pending["participant_id"]),
                None,
            )
            if participant is None:
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        delivery_generation=attempt_id,
                        succeeded=False,
                        reason_code="room_cancel_participant_missing",
                        now=self._clock(),
                    )
                continue
            try:
                reconciled = await reconcile(
                    conversation_id=pending["conversation_id"],
                    participant=participant,
                    attempt=current_attempt,
                    timeout_s=self._policy.cleanup_grace_s,
                )
            except Exception:
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        delivery_generation=attempt_id,
                        succeeded=False,
                        reason_code="room_cancel_reconcile_exception",
                        now=self._clock(),
                    )
                continue
            if not isinstance(reconciled, RoomCancelReconcileResult):
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        delivery_generation=attempt_id,
                        succeeded=False,
                        reason_code="room_cancel_reconcile_invalid",
                        now=self._clock(),
                    )
                continue
            self._controls.mark_provider_cleanup(
                observation_id=observation_id,
                attempt_id=attempt_id,
                delivery_generation=attempt_id,
                succeeded=reconciled.status == "settled",
                reason_code=reconciled.reason or f"room_cancel_reconcile_{reconciled.status}",
                now=self._clock(),
            )
            if reconciled.status != "settled":
                continue
            latest = self._controls.projection(observation_id)
            try:
                self._controls.mark_cancelled(
                    observation_id=observation_id,
                    attempt_id=attempt_id,
                    expected_control_seq=int(latest["control_seq"]),
                    reason_code=reconciled.reason or "runner_reconciled_provider_abort",
                    now=self._clock(),
                )
            except RoomControlError as exc:
                if exc.code != "room_attempt_generation_lost":
                    raise
        for pending in self._controls.list_pending_provider_cleanups():
            observation_id = str(pending["observation_id"])
            current_attempt = pending.get("reconcile_binding") or {}
            attempt_id = str(current_attempt.get("attempt_id") or "")
            if (
                not attempt_id
                or observation_id in self._active_deliveries
                or observation_id in retained_observations
            ):
                continue
            if (
                current_attempt.get("state") == "failed"
                and current_attempt.get("provider_phase") == "ensure_started"
                and not current_attempt.get("god_session_id")
                and not current_attempt.get("provider_session_id")
            ):
                # The transport marks ensure_started before spawning Codex and
                # now guarantees failed startup is fully reaped. With no bound
                # identity there is no exact provider generation to recover or
                # abort; creating one during cleanup would fabricate a session.
                with suppress(RoomControlError):
                    self._controls.mark_provider_cleanup(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        delivery_generation=attempt_id,
                        succeeded=True,
                        reason_code="room_provider_start_failed_before_binding",
                        now=self._clock(),
                    )
                continue
            reconcile = getattr(self._transport, "reconcile_cancel", None)
            if not callable(reconcile):
                continue
            participants = ParticipantStore(self._db_path).list_by_conversation(
                str(pending["conversation_id"])
            )
            participant = next(
                (item for item in participants if item.participant_id == pending["participant_id"]),
                None,
            )
            if participant is None:
                continue
            try:
                reconciled = await reconcile(
                    conversation_id=pending["conversation_id"],
                    participant=participant,
                    attempt=current_attempt,
                    timeout_s=self._policy.cleanup_grace_s,
                )
            except Exception:
                continue
            if not isinstance(reconciled, RoomCancelReconcileResult):
                continue
            with suppress(RoomControlError):
                self._controls.mark_provider_cleanup(
                    observation_id=observation_id,
                    attempt_id=attempt_id,
                    delivery_generation=attempt_id,
                    succeeded=reconciled.status == "settled",
                    reason_code=(
                        reconciled.reason or f"room_cleanup_reconcile_{reconciled.status}"
                    ),
                    now=self._clock(),
                )

    async def pump_once(self, *, conversation_id: str) -> RoomHostBatchOutcome:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("room_host_clock_timezone_required")
        participants = ParticipantStore(self._db_path).list_by_conversation(conversation_id)
        active = [
            p
            for p in participants
            if p.status == "active" and p.cli_kind == "codex" and p.role != INIT_GOD_ROLE
        ]
        kernel = RoomKernelStore(self._db_path)
        observations = kernel.list_observations(conversation_id)
        activities = {a["activity_id"]: a for a in kernel.list_activities(conversation_id)}
        active_ids = {participant.participant_id for participant in active}
        root_blocked_correlations = {
            str(activity["correlation_id"])
            for observation in observations
            if observation["participant_id"] in active_ids
            and observation["delivery_mode"] == "active"
            and observation["status"] != "completed"
            and observation.get("control_state", "active") not in {"cancelled", "exhausted"}
            and (activity := activities[observation["activity_id"]])["actor_kind"] == "human"
            and activity["activity_type"] == "message.posted"
        }
        cursors = {
            c["participant_id"]: int(c["last_acknowledged_seq"])
            for c in kernel.list_participant_cursors(conversation_id)
        }
        candidates: list[tuple[int, int, str, Any, dict[str, Any], dict[str, Any]]] = []
        for participant in active:
            unresolved = [
                o
                for o in observations
                if o["participant_id"] == participant.participant_id
                and o["delivery_mode"] == "active"
                and o["status"] != "completed"
                and o.get("control_state", "active") in {"active", "exhausted"}
                and (
                    activities[o["activity_id"]]["actor_kind"] == "human"
                    or str(activities[o["activity_id"]]["correlation_id"])
                    not in root_blocked_correlations
                )
                and (
                    activities[o["activity_id"]]["seq"] > cursors.get(participant.participant_id, 0)
                    or int(o.get("manual_retry_budget", 0)) > 0
                )
            ]
            if not unresolved:
                continue
            observation = min(
                unresolved,
                key=lambda o: (
                    activities[o["activity_id"]]["seq"],
                    o["created_at"],
                    o["observation_id"],
                ),
            )
            activity = activities[observation["activity_id"]]
            mentions = activity.get("payload", {}).get("mentions", [])
            boosted = participant.participant_id in mentions or (
                f"@participant:{participant.participant_id}" in mentions
            )
            priority = max(int(observation["priority"]), 100 if boosted else 0)
            candidates.append(
                (
                    int(activity["seq"]),
                    -priority,
                    participant.participant_id,
                    participant,
                    observation,
                    activity,
                )
            )
        candidates.sort(key=lambda item: item[:3])

        owner = f"room-host:{self._boot_uuid}:{uuid.uuid4().hex}"
        delivery_tasks: list[asyncio.Task[RoomHostDeliveryOutcome]] = []
        setup_outcomes: list[RoomHostDeliveryOutcome] = []
        deferrals: list[RoomHostDeferral] = []
        try:
            for _, _, participant_id, participant, candidate, _activity in candidates:
                if self._skill_runtime_unhealthy_reason is not None:
                    break
                if self._delivery_gate is not None and not self._delivery_gate(participant_id):
                    deferrals.append(
                        self._defer(participant_id, candidate, "native_hold", True, None)
                    )
                    continue
                if candidate.get("control_state") == "exhausted":
                    deferrals.append(
                        self._defer(
                            participant_id,
                            candidate,
                            "attempts_exhausted",
                            False,
                            None,
                        )
                    )
                    continue
                if len(delivery_tasks) >= self._policy.max_batch_size:
                    deferrals.append(
                        self._defer(participant_id, candidate, "batch_budget", True, None)
                    )
                    continue
                raw_expires_at = candidate.get("expires_at")
                expires = _when(raw_expires_at)
                if candidate["status"] == "claimed" and expires is not None and expires > now:
                    deferrals.append(
                        self._defer(
                            participant_id,
                            candidate,
                            "lease_active",
                            True,
                            raw_expires_at,
                        )
                    )
                    continue
                completed_at = [
                    parsed
                    for o in observations
                    if o["participant_id"] == participant_id
                    and o["status"] == "completed"
                    and (parsed := _when(o.get("completed_at"))) is not None
                ]
                if completed_at:
                    latest = max(completed_at)
                    retry_at_dt = latest + timedelta(seconds=self._policy.participant_cooldown_s)
                    retry_at = retry_at_dt.isoformat().replace("+00:00", "Z")
                    if retry_at_dt > now:
                        deferrals.append(
                            self._defer(participant_id, candidate, "cooldown", True, retry_at)
                        )
                        continue
                effective_attempt_limit = self._policy.max_attempts_per_observation + int(
                    candidate.get("manual_retry_budget", 0)
                )
                if int(candidate["attempt_count"]) >= effective_attempt_limit:
                    try:
                        self._controls.mark_exhausted(
                            observation_id=candidate["observation_id"],
                            base_attempt_limit=self._policy.max_attempts_per_observation,
                            now=now,
                        )
                    except RoomControlError as exc:
                        if exc.code not in {
                            "room_observation_attempt_live",
                            "room_observation_not_exhausted",
                        }:
                            raise
                    deferrals.append(
                        self._defer(
                            participant_id,
                            candidate,
                            "attempts_exhausted",
                            False,
                            None,
                        )
                    )
                    continue

                # Waiting rooms hold no durable lease. The shared permit is
                # acquired first, then transferred to exactly one delivery.
                await self._delivery_slots.acquire()
                permit = _DeliveryPermit(self._delivery_slots)
                transferred = False
                try:
                    claim_now = self._clock()
                    if claim_now.tzinfo is None:
                        raise ValueError("room_host_clock_timezone_required")
                    runner_identity: dict[str, str] = {}
                    if self._runner_generation is not None and self._runner_boot_id is not None:
                        runner_identity = {
                            "runner_generation": self._runner_generation,
                            "runner_boot_id": self._runner_boot_id,
                        }
                    claimed = kernel.claim_next_observation_batch(
                        conversation_id=conversation_id,
                        participant_id=participant_id,
                        lease_owner=owner,
                        lease_ttl_s=self._policy.lease_ttl_s,
                        base_attempt_limit=self._policy.max_attempts_per_observation,
                        now=claim_now,
                        **runner_identity,
                    )
                    if claimed is None:
                        deferrals.append(
                            self._defer(
                                participant_id,
                                candidate,
                                "claim_race",
                                True,
                                raw_expires_at,
                            )
                        )
                        continue
                    observation = claimed["observation"]
                    attempt = claimed["attempt"]
                    source = claimed["activity"]
                    batch = claimed.get("batch")
                    try:
                        decision = self._skill_decisions.bind_for_attempt(
                            attempt_id=attempt["attempt_id"],
                            catalog=self._skill_catalog,
                            now=claim_now,
                        )
                        activation = self._skill_catalog.materialize(decision.selection)
                        self._skill_decisions.assert_activation(
                            attempt_id=attempt["attempt_id"],
                            activation=activation,
                        )
                    except Exception as exc:
                        code = str(getattr(exc, "code", "room_skill_catalog_invalid"))
                        if code == "room_skill_catalog_drift":
                            self._skill_runtime_unhealthy_reason = code
                        setup_outcomes.append(
                            self._fail_unstarted_setup(
                                observation=observation,
                                attempt_id=attempt["attempt_id"],
                                reason_code=code,
                                now=claim_now,
                            )
                        )
                        if self._skill_runtime_unhealthy_reason is not None:
                            break
                        continue
                    try:
                        outcome_policy = kernel.get_outcome_policy(observation["observation_id"])
                    except Exception:
                        setup_outcomes.append(
                            self._fail_unstarted_setup(
                                observation=observation,
                                attempt_id=attempt["attempt_id"],
                                reason_code="room_outcome_policy_unavailable",
                                now=claim_now,
                            )
                        )
                        continue
                    active_meta = tuple(
                        {
                            "participant_id": p.participant_id,
                            "display_name": p.display_name,
                            "role": p.role,
                            "persona_snapshot": (
                                p.persona_snapshot.model_dump(mode="json")
                                if p.persona_snapshot is not None
                                else None
                            ),
                            "persona_snapshot_sha256": p.persona_snapshot_sha256,
                        }
                        for p in active
                    )
                    participant_directory = {p.participant_id: p for p in participants}
                    batch_members = (
                        list(batch.get("members", []))
                        if isinstance(batch, dict)
                        else [{"ordinal": 0, "observation": observation, "activity": source}]
                    )
                    member_activities = [
                        member["activity"]
                        for member in batch_members
                        if isinstance(member, dict) and isinstance(member.get("activity"), dict)
                    ]
                    selected_context = select_room_context(
                        source_activity=source,
                        member_activities=member_activities,
                        activities=activities,
                        batch=batch if isinstance(batch, dict) else None,
                        batch_members=batch_members,
                        participant_directory=participant_directory,
                        fallback_observation=observation,
                        recent_activity_limit=self._policy.context_activity_limit,
                        max_payload_chars=self._policy.max_activity_payload_chars,
                    )
                    batch_delivery = selected_context.batch
                    execution_review_materials = self._execution_review_materials(
                        batch=batch_delivery,
                        batch_members=batch_members,
                        participant_id=participant.participant_id,
                        attempt_id=str(attempt["attempt_id"]),
                    )
                    delivery = RoomObservationDelivery(
                        conversation_id=conversation_id,
                        participant=participant,
                        observation=observation,
                        source_activity=selected_context.source_activity,
                        recent_activities=selected_context.recent_activities,
                        active_participants=active_meta,
                        transport_request_id=(
                            "room-observation:"
                            f"{observation['observation_id']}:"
                            f"{observation['lease_token']}"
                        ),
                        outcome_client_request_id=(f"room-outcome:{observation['observation_id']}"),
                        attempt_id=attempt["attempt_id"],
                        skill_activation=activation,
                        allowed_outcomes=tuple(outcome_policy["allowed_outcomes"]),
                        outcome_policy_reason=str(outcome_policy["reason"]),
                        batch=batch_delivery,
                        human_root=selected_context.human_root,
                        causal_ancestry=selected_context.causal_ancestry,
                        context_coverage=selected_context.coverage,
                        execution_review_materials=execution_review_materials,
                    )
                    try:
                        self._controls.bind_delivery(
                            observation_id=observation["observation_id"],
                            attempt_id=attempt["attempt_id"],
                            lease_token=observation["lease_token"],
                            delivery_task_id=delivery.transport_request_id,
                            provider_session_generation=attempt["attempt_id"],
                            now=claim_now,
                        )
                    except Exception as exc:
                        setup_outcomes.append(
                            self._fail_unstarted_setup(
                                observation=observation,
                                attempt_id=attempt["attempt_id"],
                                reason_code=str(getattr(exc, "code", "room_skill_binding_lost")),
                                now=claim_now,
                            )
                        )
                        continue
                    delivery_task = asyncio.create_task(
                        self._deliver(
                            kernel,
                            observation,
                            attempt["attempt_id"],
                            delivery,
                            permit,
                        ),
                        name=f"room-host:{delivery.transport_request_id}",
                    )
                    delivery_task.add_done_callback(permit.release_if_unstarted)
                    active_delivery = _ActiveDelivery(
                        observation_id=observation["observation_id"],
                        attempt_id=attempt["attempt_id"],
                        participant_id=participant_id,
                        control_seq=int(observation.get("control_seq", 0)),
                        task=delivery_task,
                    )
                    self._active_deliveries[observation["observation_id"]] = active_delivery
                    delivery_task.add_done_callback(
                        partial(
                            self._active_delivery_done,
                            str(observation["observation_id"]),
                        )
                    )
                    delivery_tasks.append(delivery_task)
                    transferred = True
                finally:
                    if not transferred:
                        permit.release()

                # Immediate semaphore acquisitions do not yield. Give peer
                # rooms and this room's delivery a turn between candidates.
                await asyncio.sleep(0)
            results = await asyncio.gather(*delivery_tasks)
        except BaseException:
            for delivery_task in delivery_tasks:
                delivery_task.cancel()
            if delivery_tasks:
                await asyncio.gather(*delivery_tasks, return_exceptions=True)
            raise
        return RoomHostBatchOutcome(
            conversation_id,
            tuple(setup_outcomes) + tuple(results),
            tuple(deferrals),
        )

    def _fail_unstarted_setup(
        self,
        *,
        observation: dict[str, Any],
        attempt_id: str,
        reason_code: str,
        now: datetime,
    ) -> RoomHostDeliveryOutcome:
        state: Literal["failed", "lease_lost"] = "failed"
        retryable = True
        retry_at: str | None = now.isoformat().replace("+00:00", "Z")
        try:
            projection = self._controls.fail_unstarted_attempt(
                observation_id=observation["observation_id"],
                attempt_id=attempt_id,
                expected_lease_token=observation["lease_token"],
                reason_code=reason_code,
                base_attempt_limit=self._policy.max_attempts_per_observation,
                now=now,
            )
            retryable = projection.get("control_state") != "exhausted"
            if not retryable:
                retry_at = None
        except RoomControlError:
            state = "lease_lost"
            retryable = False
            retry_at = None
        return RoomHostDeliveryOutcome(
            participant_id=observation["participant_id"],
            observation_id=observation["observation_id"],
            attempt_count=int(observation.get("attempt_count", 1)),
            state=state,
            reason=reason_code,
            retryable=retryable,
            retry_at=retry_at,
            outcome_type=None,
            transport_status=None,
            diagnostic_text=None,
        )

    def _execution_review_materials(
        self,
        *,
        batch: dict[str, Any],
        batch_members: list[dict[str, Any]],
        participant_id: str,
        attempt_id: str,
    ) -> tuple[dict[str, Any], ...]:
        """Load exact patch bytes only for execution proposals in this peer batch.

        Room activities deliberately contain only safe candidate references.  A
        missing, stale, oversized, or corrupt execution candidate therefore removes
        voting eligibility without preventing the participant from observing the
        ordinary Room batch.
        """

        store = self._execution_store
        batch_id = batch.get("batch_id")
        if (
            store is None
            or batch.get("phase") != "peer"
            or not isinstance(batch_id, str)
            or not batch_id
        ):
            return ()
        materials: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for member in batch_members:
            if not isinstance(member, dict):
                continue
            activity = member.get("activity")
            if (
                not isinstance(activity, dict)
                or activity.get("activity_type") != "proposal.created"
            ):
                continue
            payload = activity.get("payload")
            candidate = (
                payload.get("execution_candidate_ref") if isinstance(payload, dict) else None
            )
            candidate_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
            proposal_activity_id = activity.get("activity_id")
            if (
                not isinstance(candidate_id, str)
                or not candidate_id
                or not isinstance(proposal_activity_id, str)
                or not proposal_activity_id
                or (candidate_id, proposal_activity_id) in seen
            ):
                continue
            try:
                material = store.get_review_material_for_batch(
                    candidate_id=candidate_id,
                    proposal_activity_id=proposal_activity_id,
                    observation_batch_id=batch_id,
                    participant_id=participant_id,
                    attempt_id=attempt_id,
                )
            except RoomExecutionStoreError:
                continue
            materials.append(material)
            seen.add((candidate_id, proposal_activity_id))
        return tuple(materials)

    @staticmethod
    def _defer(
        participant_id: str,
        observation: dict[str, Any],
        reason: Literal[
            "lease_active",
            "cooldown",
            "attempts_exhausted",
            "batch_budget",
            "claim_race",
            "native_hold",
        ],
        retryable: bool,
        retry_at: str | None,
    ) -> RoomHostDeferral:
        return RoomHostDeferral(
            participant_id, observation["observation_id"], reason, retryable, retry_at
        )

    def _active_delivery_done(
        self,
        observation_id: str,
        task: asyncio.Task[RoomHostDeliveryOutcome],
    ) -> None:
        current = self._active_deliveries.get(observation_id)
        if current is not None and current.task is task:
            self._active_deliveries.pop(observation_id, None)

    async def _deliver(
        self,
        kernel: RoomKernelStore,
        observation: dict[str, Any],
        attempt_id: str,
        delivery: RoomObservationDelivery,
        permit: _DeliveryPermit,
    ) -> RoomHostDeliveryOutcome:
        permit.mark_started()
        release_permit_on_exit = True
        try:
            delivery = await self._with_memory_evidence(delivery)
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(
                self._transport.deliver(delivery, timeout_s=self._policy.delivery_timeout_s),
                name=delivery.transport_request_id,
            )
            deadline = loop.time() + self._policy.delivery_timeout_s
            transport_status: str | None
            reason: str | None
            diagnostic: str | None
            timed_out = False
            try:
                done, _ = await asyncio.wait({task}, timeout=max(0.0, deadline - loop.time()))
                if done:
                    transport_status, reason, diagnostic = self._task_result(task)
                else:
                    task.cancel()
                    timed_out = True
                    settled, interrupted = await self._cleanup_transport_task(
                        task,
                        loop.time() + self._policy.cleanup_grace_s,
                        permit,
                    )
                    if not settled:
                        release_permit_on_exit = False
                    if interrupted:
                        raise asyncio.CancelledError
                    transport_status, reason, diagnostic = (
                        None,
                        ("delivery_timeout" if settled else "cleanup_timeout"),
                        None,
                    )
            except asyncio.CancelledError:
                if timed_out:
                    raise
                control = self._controls.projection(observation["observation_id"])
                operator_cancel = control["control_state"] in {
                    "cancel_requested",
                    "cancel_pending",
                }
                task.cancel()
                settled, _interrupted = await self._cleanup_transport_task(
                    task,
                    loop.time() + self._policy.cleanup_grace_s,
                    permit,
                    control=(observation["observation_id"], attempt_id)
                    if operator_cancel
                    else None,
                )
                if not settled:
                    release_permit_on_exit = False
                if not operator_cancel:
                    raise
                current_control = self._controls.reconcile_state(observation["observation_id"])
                if current_control["control_state"] == "cancel_requested":
                    try:
                        self._controls.mark_cancel_pending(
                            observation_id=observation["observation_id"],
                            attempt_id=attempt_id,
                            expected_control_seq=int(current_control["control_seq"]),
                            now=self._clock(),
                        )
                    except RoomControlError as exc:
                        if exc.code != "room_attempt_generation_lost":
                            raise
                    current_control = self._controls.reconcile_state(observation["observation_id"])
                binding = current_control.get("reconcile_binding") or {}
                cleanup_proven = binding.get("provider_phase", "not_started") in {
                    "not_started",
                    "cleanup_succeeded",
                }
                if settled and cleanup_proven and current_control["control_state"] != "cancelled":
                    try:
                        updated_control = self._controls.mark_cancelled(
                            observation_id=observation["observation_id"],
                            attempt_id=attempt_id,
                            expected_control_seq=int(current_control["control_seq"]),
                            reason_code=(
                                binding.get("provider_cleanup_reason") or "operator_cancelled"
                            ),
                            now=self._clock(),
                        )
                    except RoomControlError as exc:
                        if exc.code != "room_attempt_generation_lost":
                            raise
                        updated_control = self._controls.projection(observation["observation_id"])
                else:
                    updated_control = self._controls.projection(observation["observation_id"])
                cancel_state: Literal["cancelled", "cancel_pending"] = (
                    "cancelled"
                    if updated_control["control_state"] == "cancelled"
                    else "cancel_pending"
                )
                return RoomHostDeliveryOutcome(
                    delivery.participant.participant_id,
                    observation["observation_id"],
                    int(updated_control["attempt_count"]),
                    cancel_state,
                    (
                        "operator_cancelled"
                        if cancel_state == "cancelled"
                        else "transport_cancel_pending"
                    ),
                    False,
                    None,
                    None,
                    None,
                    None,
                )
            if not timed_out and reason is None:
                reason = (
                    "durable_outcome_missing"
                    if transport_status == "finished"
                    else "transport_failed"
                )
            current = kernel.get_observation(observation["observation_id"])
            retry_at = current.get("expires_at")
            if current["status"] == "completed":
                return RoomHostDeliveryOutcome(
                    delivery.participant.participant_id,
                    current["observation_id"],
                    int(current["attempt_count"]),
                    "completed",
                    None,
                    False,
                    None,
                    current.get("outcome_type"),
                    transport_status,
                    diagnostic,
                )
            if current.get("lease_token") != observation.get("lease_token"):
                return RoomHostDeliveryOutcome(
                    delivery.participant.participant_id,
                    current["observation_id"],
                    int(current["attempt_count"]),
                    "lease_lost",
                    "lease_lost",
                    True,
                    retry_at,
                    current.get("outcome_type"),
                    transport_status,
                    diagnostic,
                )
            state: Literal["incomplete", "failed"] = (
                "incomplete" if transport_status == "finished" else "failed"
            )
            try:
                self._controls.finish_attempt(
                    observation_id=current["observation_id"],
                    attempt_id=attempt_id,
                    reason_code=reason or "transport_failed",
                    base_attempt_limit=self._policy.max_attempts_per_observation,
                    now=self._clock(),
                )
            except RoomControlError as exc:
                if exc.code != "room_attempt_generation_lost":
                    raise
            return RoomHostDeliveryOutcome(
                delivery.participant.participant_id,
                current["observation_id"],
                int(current["attempt_count"]),
                state,
                reason,
                True,
                retry_at,
                current.get("outcome_type"),
                transport_status,
                diagnostic,
            )
        finally:
            if release_permit_on_exit:
                permit.release()

    async def _with_memory_evidence(
        self, delivery: RoomObservationDelivery
    ) -> RoomObservationDelivery:
        runtime = self._memory_runtime
        if runtime is None or delivery.attempt_id is None:
            return delivery
        source = delivery.source_activity
        correlation_id = str(source.get("correlation_id") or "")
        causal_ids = self._memory_excluded_activity_ids(delivery)
        task = self._memory_retrieval_task(delivery)
        try:
            async with asyncio.timeout(ROOM_MEMORY_RECALL_TIMEOUT_S):
                evidence = await runtime.recall(
                    RoomMemoryRecallInput(
                        conversation_id=delivery.conversation_id,
                        attempt_id=delivery.attempt_id,
                        correlation_id=correlation_id,
                        task=task,
                        causal_activity_ids=causal_ids,
                    )
                )
        except TimeoutError:
            evidence = RoomMemoryEvidence(
                status="timeout",
                reason_code="room_memory_timeout",
                schema_version="memoryos_v3_context/v1",
                latency_ms=int(ROOM_MEMORY_RECALL_TIMEOUT_S * 1000),
                evidence_sha256="sha256:" + "0" * 64,
            )
        except Exception:
            evidence = RoomMemoryEvidence(
                status="error",
                reason_code="room_memory_unavailable",
                schema_version="memoryos_v3_context/v1",
                latency_ms=0,
                evidence_sha256="sha256:" + "0" * 64,
            )
        try:
            runtime.record_recall_receipt(
                attempt_id=delivery.attempt_id,
                evidence=evidence,
            )
        except Exception:
            # Memory receipt failure is diagnostic only.  It must not consume or
            # wedge the durable Room observation.
            evidence = RoomMemoryEvidence(
                status="error",
                reason_code="room_memory_receipt_failed",
                schema_version=evidence.schema_version,
                latency_ms=evidence.latency_ms,
                evidence_sha256=evidence.evidence_sha256,
            )
        if evidence.degraded:
            self._memory_recall_attention_reason = evidence.reason_code
        else:
            self._memory_recall_attention_reason = None
        return replace(delivery, memory_evidence=evidence)

    @staticmethod
    def _memory_excluded_activity_ids(
        delivery: RoomObservationDelivery,
    ) -> tuple[str, ...]:
        return memory_excluded_activity_ids(
            source_activity=delivery.source_activity,
            human_root=delivery.human_root,
            causal_ancestry=delivery.causal_ancestry,
            recent_activities=delivery.recent_activities,
            batch=delivery.batch,
        )

    @staticmethod
    def _memory_retrieval_task(delivery: RoomObservationDelivery) -> str:
        root = delivery.human_root or delivery.source_activity
        payload = root.get("payload") if isinstance(root, Mapping) else None
        if isinstance(payload, Mapping):
            for key in ("content", "text", "summary"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:2000]
        return "Recall source-backed Room context relevant to this observation."

    @staticmethod
    def _task_result(
        task: asyncio.Task[RoomTransportResult],
    ) -> tuple[str | None, str | None, str | None]:
        try:
            result = task.result()
        except asyncio.CancelledError:
            return None, "transport_cancelled", None
        except Exception as exc:
            return None, "transport_exception", f"{type(exc).__name__}: {exc}"
        return result.status, result.reason, result.diagnostic_text

    async def _cleanup_transport_task(
        self,
        task: asyncio.Task[RoomTransportResult],
        deadline: float,
        permit: _DeliveryPermit,
        control: tuple[str, str] | None = None,
    ) -> tuple[bool, bool]:
        interrupted = False
        try:
            done, _ = await asyncio.wait(
                {task}, timeout=max(0.0, deadline - asyncio.get_running_loop().time())
            )
        except asyncio.CancelledError:
            interrupted = True
            try:
                done, _ = await asyncio.wait(
                    {task},
                    timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
                )
            except asyncio.CancelledError:
                done = set()
        if done:
            self._task_result(task)
            return True, interrupted
        self._retained_tasks.add(task)
        self._retained_permits[task] = permit
        if control is not None:
            self._retained_controls[task] = control
        task.add_done_callback(self._retain_done)
        return False, interrupted

    def _retain_done(self, task: asyncio.Task[RoomTransportResult]) -> None:
        self._task_result(task)
        self._retained_tasks.discard(task)
        permit = self._retained_permits.pop(task, None)
        if permit is not None:
            permit.release()
        control = self._retained_controls.pop(task, None)
        if control is not None:
            observation_id, attempt_id = control
            try:
                projection = self._controls.reconcile_state(observation_id)
                binding = projection.get("reconcile_binding") or {}
                if projection["control_state"] in {
                    "cancel_requested",
                    "cancel_pending",
                } and binding.get("provider_phase", "not_started") in {
                    "not_started",
                    "cleanup_succeeded",
                }:
                    self._controls.mark_cancelled(
                        observation_id=observation_id,
                        attempt_id=attempt_id,
                        expected_control_seq=int(projection["control_seq"]),
                        reason_code=(
                            binding.get("provider_cleanup_reason")
                            or "retained_transport_cleanup_confirmed"
                        ),
                        now=self._clock(),
                    )
            except RoomControlError:
                # A newer control generation or committed outcome owns the state.
                pass
