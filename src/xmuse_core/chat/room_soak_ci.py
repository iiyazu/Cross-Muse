"""Deterministic multi-Room Kernel/Host soak used by the ordinary CI profile.

The simulator deliberately drives the production Room setup, kernel, participant
identity, Skill decision, Host semaphore, and fair runtime loop.  Its returned
evidence is aggregate-only: internal Room, participant, activity, observation, and
provider-binding identifiers never cross this module's result boundary.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.room_api_models import RoomConversationCreate
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_runtime import run_room_participant_host_loop
from xmuse_core.chat.room_setup import RoomSetupService

CI_SOAK_EVIDENCE_SCHEMA = "room_soak_ci_evidence/v1"
CI_SOAK_PROFILE_ID = "ci-sim"
CI_SOAK_ROOM_COUNT = 12
CI_SOAK_AGENT_COUNT = 4
CI_SOAK_TURN_COUNT = 20
CI_SOAK_MAX_ACTIVE_DELIVERIES = 4

_EXPECTED_POSTS = CI_SOAK_ROOM_COUNT * CI_SOAK_TURN_COUNT
_EXPECTED_ROOT_ATTEMPTS = _EXPECTED_POSTS * CI_SOAK_AGENT_COUNT
_EXPECTED_PEER_ATTEMPTS = _EXPECTED_POSTS * (CI_SOAK_AGENT_COUNT - 1)
_EXPECTED_ATTEMPTS = _EXPECTED_ROOT_ATTEMPTS + _EXPECTED_PEER_ATTEMPTS


@dataclass
class _PostMeter:
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: int = 0
    maximum: int = 0

    def enter(self) -> None:
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self) -> None:
        with self.lock:
            self.active -= 1


@dataclass
class _DeliveryEvidence:
    post_ns: dict[str, int]
    first_claim_ns: dict[str, int] = field(default_factory=dict)
    first_outcome_ns: dict[str, int] = field(default_factory=dict)
    settled_ns: dict[str, int] = field(default_factory=dict)
    first_claim_index_by_room: dict[str, int] = field(default_factory=dict)
    outcomes_by_correlation: dict[str, int] = field(default_factory=dict)
    delivery_count: int = 0
    outcome_count: int = 0
    active_deliveries: int = 0
    max_active_deliveries: int = 0


class _ScriptedRoomTransport:
    """Submit one deterministic root response and otherwise durable noops."""

    def __init__(
        self,
        *,
        db_path: Path,
        registry_path: Path,
        session_ids: Mapping[str, str],
        evidence: _DeliveryEvidence,
    ) -> None:
        self._db_path = db_path
        self._application = RoomApplicationService(db_path, registry_path)
        self._session_ids = dict(session_ids)
        self._evidence = evidence

    async def deliver(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> RoomTransportResult:
        del timeout_s
        correlation_id = str(delivery.source_activity["correlation_id"])
        batch = delivery.batch or {}
        phase = str(batch.get("phase") or "root")
        now_ns = time.perf_counter_ns()
        evidence = self._evidence
        evidence.delivery_count += 1
        evidence.first_claim_ns.setdefault(correlation_id, now_ns)
        evidence.first_claim_index_by_room.setdefault(
            delivery.conversation_id,
            evidence.delivery_count,
        )
        evidence.active_deliveries += 1
        evidence.max_active_deliveries = max(
            evidence.max_active_deliveries,
            evidence.active_deliveries,
        )
        try:
            # Keep all acquired Host permits observably in flight without replacing
            # the real Host semaphore or its production claim path.
            await asyncio.sleep(0.001)
            responds = phase == "root" and delivery.participant.role == "architect"
            outcome_type = "respond" if responds else "noop"
            outcome_payload = (
                {"content": "Deterministic CI participant response."} if responds else {}
            )
            self._application.submit_participant_outcome(
                conversation_id=delivery.conversation_id,
                participant_id=delivery.participant.participant_id,
                god_session_id=self._session_ids[delivery.participant.participant_id],
                observation_id=str(delivery.observation["observation_id"]),
                lease_token=str(delivery.observation["lease_token"]),
                client_request_id=delivery.outcome_client_request_id,
                outcome_type=outcome_type,
                outcome_payload=outcome_payload,
                observation_batch_id=(str(batch["batch_id"]) if batch.get("batch_id") else None),
            )
            completed_ns = time.perf_counter_ns()
            evidence.first_outcome_ns.setdefault(correlation_id, completed_ns)
            evidence.outcome_count += 1
            correlation_outcomes = evidence.outcomes_by_correlation.get(correlation_id, 0) + 1
            evidence.outcomes_by_correlation[correlation_id] = correlation_outcomes
            if correlation_outcomes == (CI_SOAK_AGENT_COUNT + CI_SOAK_AGENT_COUNT - 1):
                evidence.settled_ns.setdefault(correlation_id, completed_ns)
            return RoomTransportResult("finished")
        finally:
            evidence.active_deliveries -= 1


def run_ci_sim(*, runtime_root: Path) -> Mapping[str, Any]:
    """Run the fixed production-path ``ci-sim`` profile and return safe evidence."""

    root = Path(runtime_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "chat.db"
    registry_path = root / "god_sessions.json"
    if db_path.exists() or registry_path.exists():
        raise ValueError("room_soak_runtime_root_not_empty")
    return asyncio.run(_run_ci_sim(root, db_path=db_path, registry_path=registry_path))


async def _run_ci_sim(
    root: Path,
    *,
    db_path: Path,
    registry_path: Path,
) -> dict[str, Any]:
    RoomDatabase(db_path).initialize()
    rooms, session_ids = _create_rooms_and_sessions(root, registry_path=registry_path)
    post_meter = _PostMeter()
    post_ns = await _post_all_turns(
        db_path,
        rooms=rooms,
        meter=post_meter,
    )
    queued_before_host = _count_unsettled_correlations(db_path)
    evidence = _DeliveryEvidence(post_ns=post_ns)
    transport = _ScriptedRoomTransport(
        db_path=db_path,
        registry_path=registry_path,
        session_ids=session_ids,
        evidence=evidence,
    )
    host = RoomParticipantHost(
        db_path,
        transport,
        policy=RoomHostPolicy(
            delivery_timeout_s=30.0,
            cleanup_grace_s=1.0,
            lease_ttl_s=40.0,
            participant_cooldown_s=0,
            max_attempts_per_observation=1,
            max_batch_size=CI_SOAK_MAX_ACTIVE_DELIVERIES,
        ),
    )
    stop = asyncio.Event()
    loop_task = asyncio.create_task(
        run_room_participant_host_loop(
            host,
            stop=stop,
            max_concurrent_rooms=CI_SOAK_MAX_ACTIVE_DELIVERIES,
            idle_wait_s=0.001,
        ),
        name="xmuse-ci-soak-room-loop",
    )
    try:
        await _wait_until_settled(evidence, loop_task=loop_task, timeout_s=300.0)
    finally:
        stop.set()
        try:
            await asyncio.wait_for(loop_task, timeout=5.0)
        finally:
            await host.shutdown()

    return _collect_evidence(
        db_path,
        evidence=evidence,
        post_meter=post_meter,
        queued_before_host=queued_before_host,
    )


def _create_rooms_and_sessions(
    root: Path,
    *,
    registry_path: Path,
) -> tuple[list[str], dict[str, str]]:
    setup = RoomSetupService(root)
    registry = GodSessionRegistry(registry_path)
    room_ids: list[str] = []
    session_ids: dict[str, str] = {}
    for room_index in range(CI_SOAK_ROOM_COUNT):
        room = setup.create_conversation(
            RoomConversationCreate(
                title=f"CI soak room {room_index + 1}",
                client_request_id=f"ci-soak-room-{room_index + 1}",
                roster_template_id="builtin.development",
            )
        )
        conversation_id = str(room["id"])
        participants = room["participants"]
        if not isinstance(participants, list) or len(participants) != CI_SOAK_AGENT_COUNT:
            raise RuntimeError("room_soak_roster_contract_mismatch")
        room_ids.append(conversation_id)
        for participant_index, raw_participant in enumerate(participants):
            if not isinstance(raw_participant, dict):
                raise RuntimeError("room_soak_roster_contract_mismatch")
            participant_id = str(raw_participant["participant_id"])
            session = registry.create(
                str(raw_participant["role"]),
                str(raw_participant["display_name"]),
                "codex",
                f"ci-soak-session-{room_index}-{participant_index}",
                f"ci-soak-inbox-{room_index}-{participant_index}",
                conversation_id,
                participant_id,
                model=str(raw_participant["model"]),
            )
            session_ids[participant_id] = session.god_session_id
    return room_ids, session_ids


async def _post_all_turns(
    db_path: Path,
    *,
    rooms: list[str],
    meter: _PostMeter,
) -> dict[str, int]:
    loop = asyncio.get_running_loop()
    post_ns: dict[str, int] = {}
    with ThreadPoolExecutor(
        max_workers=CI_SOAK_ROOM_COUNT,
        thread_name_prefix="xmuse-ci-soak-post",
    ) as executor:
        for turn_index in range(CI_SOAK_TURN_COUNT):
            barrier = threading.Barrier(CI_SOAK_ROOM_COUNT)
            futures = [
                loop.run_in_executor(
                    executor,
                    _post_one_turn,
                    db_path,
                    conversation_id,
                    room_index,
                    turn_index,
                    barrier,
                    meter,
                )
                for room_index, conversation_id in enumerate(rooms)
            ]
            for correlation_id, started_ns in await asyncio.gather(*futures):
                post_ns[correlation_id] = started_ns
    return post_ns


def _post_one_turn(
    db_path: Path,
    conversation_id: str,
    room_index: int,
    turn_index: int,
    barrier: threading.Barrier,
    meter: _PostMeter,
) -> tuple[str, int]:
    meter.enter()
    try:
        barrier.wait(timeout=10.0)
        started_ns = time.perf_counter_ns()
        result = RoomKernelStore(db_path).post_human_activity(
            conversation_id=conversation_id,
            human_id="ci-soak-human",
            content=f"Deterministic CI turn {turn_index + 1}.",
            client_request_id=f"ci-soak-post-{room_index}-{turn_index}",
        )
        return str(result["activity"]["correlation_id"]), started_ns
    finally:
        meter.leave()


async def _wait_until_settled(
    evidence: _DeliveryEvidence,
    *,
    loop_task: asyncio.Task[None],
    timeout_s: float,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while evidence.outcome_count < _EXPECTED_ATTEMPTS:
        if loop_task.done():
            loop_task.result()
            raise RuntimeError("room_soak_host_loop_stopped")
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("room_soak_ci_timeout")
        await asyncio.sleep(0.01)


def _collect_evidence(
    db_path: Path,
    *,
    evidence: _DeliveryEvidence,
    post_meter: _PostMeter,
    queued_before_host: int,
) -> dict[str, Any]:
    with _connect_readonly(db_path) as conn:
        counts = {
            "human_posts": _scalar(
                conn,
                """select count(*) from room_activities
                   where actor_kind = 'human' and activity_type = 'message.posted'""",
            ),
            "correlations": _scalar(
                conn,
                """select count(distinct correlation_id) from room_activities
                   where actor_kind = 'human' and activity_type = 'message.posted'""",
            ),
            "attempts": _scalar(conn, "select count(*) from room_observation_attempts"),
            "outcomes": _scalar(
                conn,
                "select count(*) from room_observation_attempts where state = 'completed'",
            ),
            "root_attempts": _scalar(
                conn,
                """select count(*) from room_observation_attempts t
                   join room_observation_batches b on b.batch_id = t.batch_id
                   where b.phase = 'root'""",
            ),
            "peer_attempts": _scalar(
                conn,
                """select count(*) from room_observation_attempts t
                   join room_observation_batches b on b.batch_id = t.batch_id
                   where b.phase = 'peer'""",
            ),
            "respond": _scalar(
                conn,
                """select count(*) from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                   where t.state = 'completed' and o.outcome_type = 'respond'""",
            ),
            "noop": _scalar(
                conn,
                """select count(*) from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                   where t.state = 'completed' and o.outcome_type = 'noop'""",
            ),
            "other_outcomes": _scalar(
                conn,
                """select count(*) from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                   where t.state = 'completed'
                     and o.outcome_type not in ('respond','noop')""",
            ),
            "skill_decisions": _scalar(
                conn,
                "select count(*) from room_attempt_skill_decisions",
            ),
            "settled_correlations": _settled_correlation_count(conn),
        }
        violations = {
            "duplicate_outcome": _duplicate_outcome_count(conn),
            "cross_room_identity": _cross_room_identity_count(conn),
            "cross_room_causality": _cross_room_causality_count(conn),
            "unsettled_correlation": _count_unsettled_correlations_conn(conn),
        }
        residual = {
            "live_leases": _scalar(
                conn,
                "select count(*) from room_observations where status = 'claimed'",
            ),
            "cleanup_pending": _scalar(
                conn,
                """select count(*) from room_observation_attempts
                   where provider_phase = 'cleanup_pending'""",
            ),
            "recovery_pending": _scalar(
                conn,
                """select count(*) from room_observation_attempts
                   where recovery_state in ('fenced','cleanup_pending')""",
            ),
            "exhausted": _scalar(
                conn,
                "select count(*) from room_observations where control_state = 'exhausted'",
            ),
            "incomplete_attempts": _scalar(
                conn,
                "select count(*) from room_observation_attempts where state <> 'completed'",
            ),
        }
        integrity = str(conn.execute("pragma integrity_check").fetchone()[0])

    latency_samples = _latency_samples(evidence)
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    return {
        "schema_version": CI_SOAK_EVIDENCE_SCHEMA,
        "profile_id": CI_SOAK_PROFILE_ID,
        "configuration": {
            "room_count": CI_SOAK_ROOM_COUNT,
            "agents_per_room": CI_SOAK_AGENT_COUNT,
            "human_turns_per_room": CI_SOAK_TURN_COUNT,
            "max_concurrent_provider_deliveries": CI_SOAK_MAX_ACTIVE_DELIVERIES,
        },
        "counts": counts,
        "concurrency": {
            "max_active_deliveries": evidence.max_active_deliveries,
            "rooms_first_claimed": len(evidence.first_claim_index_by_room),
            "attempts_until_all_rooms_first_claimed": max(
                evidence.first_claim_index_by_room.values(), default=0
            ),
            "max_active_posts": post_meter.maximum,
            "queued_correlations_before_host": queued_before_host,
        },
        "latency_samples_ms": latency_samples,
        "violations": violations,
        "residual": residual,
        "storage": {
            "database_bytes": db_path.stat().st_size,
            "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
            "sqlite_integrity": integrity,
        },
    }


def _latency_samples(evidence: _DeliveryEvidence) -> dict[str, list[dict[str, int | float]]]:
    def samples(targets: Mapping[str, int]) -> list[dict[str, int | float]]:
        # Preserve workload chronology so the result builder can compare the
        # first and second halves of the soak.  Sorting by latency here would
        # manufacture an apparent slowdown even when the runtime is stable.
        ordered_correlations = sorted(
            evidence.post_ns,
            key=lambda correlation_id: (
                evidence.post_ns[correlation_id],
                correlation_id,
            ),
        )
        included = [
            correlation_id for correlation_id in ordered_correlations if correlation_id in targets
        ]
        return [
            {
                "ordinal": ordinal,
                "latency_ms": round(
                    (targets[correlation_id] - evidence.post_ns[correlation_id]) / 1_000_000,
                    3,
                ),
            }
            for ordinal, correlation_id in enumerate(included, 1)
        ]

    return {
        "post_to_claim": samples(evidence.first_claim_ns),
        "post_to_outcome": samples(evidence.first_outcome_ns),
        "post_to_settled": samples(evidence.settled_ns),
    }


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def _count_unsettled_correlations(db_path: Path) -> int:
    with _connect_readonly(db_path) as conn:
        return _count_unsettled_correlations_conn(conn)


def _count_unsettled_correlations_conn(conn: sqlite3.Connection) -> int:
    return _scalar(
        conn,
        """select count(*) from (
               select root.correlation_id
               from room_activities root
               where root.actor_kind = 'human'
                 and root.activity_type = 'message.posted'
                 and exists (
                     select 1 from room_observations o
                     join room_activities a on a.activity_id = o.activity_id
                     where a.correlation_id = root.correlation_id
                       and o.delivery_mode = 'active'
                       and o.status <> 'completed'
                       and o.control_state not in ('cancelled','exhausted')
                 )
               group by root.correlation_id
           )""",
    )


def _settled_correlation_count(conn: sqlite3.Connection) -> int:
    return _scalar(
        conn,
        """select count(*) from (
               select root.correlation_id
               from room_activities root
               where root.actor_kind = 'human'
                 and root.activity_type = 'message.posted'
                 and not exists (
                     select 1 from room_observations o
                     join room_activities a on a.activity_id = o.activity_id
                     where a.correlation_id = root.correlation_id
                       and o.delivery_mode = 'active'
                       and o.status <> 'completed'
                       and o.control_state not in ('cancelled','exhausted')
                 )
               group by root.correlation_id
           )""",
    )


def _duplicate_outcome_count(conn: sqlite3.Connection) -> int:
    return _scalar(
        conn,
        """select coalesce(sum(outcome_count - 1), 0) from (
               select b.conversation_id, b.participant_id, b.correlation_id, b.phase,
                      count(*) as outcome_count
               from room_observation_attempts t
               join room_observation_batches b on b.batch_id = t.batch_id
               where t.state = 'completed'
               group by b.conversation_id, b.participant_id, b.correlation_id, b.phase
               having count(*) > 1
           )""",
    )


def _cross_room_identity_count(conn: sqlite3.Connection) -> int:
    return _scalar(
        conn,
        """select count(*) from (
               select t.attempt_id as authority_ref
               from room_observation_attempts t
               join room_observations o on o.observation_id = t.observation_id
               join participants p on p.participant_id = t.participant_id
               where t.conversation_id <> o.conversation_id
                  or t.participant_id <> o.participant_id
                  or p.conversation_id <> t.conversation_id
               union all
               select a.activity_id as authority_ref
               from room_activities a
               left join participants p on p.participant_id = a.actor_participant_id
               where a.actor_kind = 'participant'
                 and (p.participant_id is null
                      or p.conversation_id <> a.conversation_id)
           )""",
    )


def _cross_room_causality_count(conn: sqlite3.Connection) -> int:
    return _scalar(
        conn,
        """select count(*) from room_activities child
           left join room_activities parent on parent.activity_id = child.causation_id
           where child.actor_kind = 'participant'
             and (parent.activity_id is null
                  or parent.conversation_id <> child.conversation_id
                  or parent.correlation_id <> child.correlation_id)""",
    )


__all__ = [
    "CI_SOAK_AGENT_COUNT",
    "CI_SOAK_EVIDENCE_SCHEMA",
    "CI_SOAK_MAX_ACTIVE_DELIVERIES",
    "CI_SOAK_PROFILE_ID",
    "CI_SOAK_ROOM_COUNT",
    "CI_SOAK_TURN_COUNT",
    "run_ci_sim",
]
