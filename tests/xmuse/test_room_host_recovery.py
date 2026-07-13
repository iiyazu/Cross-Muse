from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import xmuse_core.chat.room_host as rh
from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_kernel import RoomKernelStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _room(path: Path, count: int = 1):
    db, registry = path / "chat.db", path / "god_sessions.json"
    cid = RoomTestStore(db).create_conversation("room").id
    ps, sessions = ParticipantStore(db), {}
    for i in range(count):
        p = ps.add(
            conversation_id=cid, role=f"r{i}", display_name=f"P{i}", cli_kind="codex", model="gpt-5"
        )
        sessions[p.participant_id] = GodSessionRegistry(registry).create(
            p.role, p.display_name, "codex", f"a{i}", f"i{i}", cid, p.participant_id
        )
    return db, registry, cid, ps.list_by_conversation(cid), sessions


def _post(db, cid, key="h"):
    return RoomKernelStore(db).post_human_activity(
        conversation_id=cid, human_id="human", content=key, client_request_id=key
    )


def _service_complete(db, registry, cid, person, session, delivery, now=NOW):
    return RoomApplicationService(db, registry).submit_participant_outcome(
        conversation_id=cid,
        participant_id=person.participant_id,
        god_session_id=session.god_session_id,
        observation_id=delivery.observation["observation_id"],
        lease_token=delivery.observation["lease_token"],
        client_request_id=delivery.outcome_client_request_id,
        outcome_type="noop",
        outcome_payload={},
        now=now,
    )


class _Return:
    def __init__(self, result=None, error=None, complete=False, release=None):
        self.result, self.error, self.complete, self.release = result, error, complete, release
        self.deliveries = []

    async def deliver(self, delivery, *, timeout_s):
        self.deliveries.append(delivery)
        if self.complete:
            _service_complete(self.db, self.registry, self.cid, self.person, self.session, delivery)
        if self.release is not None:
            await self.release.wait()
        if self.error:
            raise self.error
        return self.result or rh.RoomTransportResult("finished")


def _host(db, transport, now=NOW, **kwargs):
    policy = rh.RoomHostPolicy(
        delivery_timeout_s=0.01, cleanup_grace_s=0.01, lease_ttl_s=3, **kwargs
    )
    return rh.RoomParticipantHost(db, transport, policy=policy, clock=lambda: now)


def _counts(db, cid):
    return (
        sqlite3.connect(db)
        .execute(
            "select (select count(*) from room_activities where conversation_id=?),"
            " (select count(*) from messages where conversation_id=?)",
            (cid, cid),
        )
        .fetchone()
    )


def test_failure_matrix_has_no_synthetic_truth_and_completion_wins(tmp_path):
    cases = [
        (rh.RoomTransportResult("finished"), None),
        (rh.RoomTransportResult("failed", "bad"), None),
        (None, ValueError("boom")),
    ]
    for i, (result, error) in enumerate(cases):
        db, registry, cid, people, sessions = _room(tmp_path / f"c{i}")
        _post(db, cid, str(i))
        t = _Return(result, error)
        out = asyncio.run(_host(db, t).pump_once(conversation_id=cid)).deliveries[0]
        assert out.state == ("incomplete" if i == 0 else "failed")
        expected = ["durable_outcome_missing", "bad", "transport_exception"][i]
        assert out.reason == expected and _counts(db, cid) == (1, 1)
    db, registry, cid, people, sessions = _room(tmp_path / "complete")
    _post(db, cid, "complete")
    t = _Return(error=RuntimeError("late"))
    t.db, t.registry, t.cid, t.person, t.session = (
        db,
        registry,
        cid,
        people[0],
        sessions[people[0].participant_id],
    )
    t.complete = True
    out = asyncio.run(_host(db, t).pump_once(conversation_id=cid)).deliveries[0]
    assert out.state == "completed" and out.reason is None
    db, registry, cid, people, sessions = _room(tmp_path / "rotate")
    _post(db, cid, "rotate")

    class Rotate(_Return):
        async def deliver(self, delivery, *, timeout_s):
            RoomKernelStore(db).claim_next_observation(
                conversation_id=cid,
                participant_id=people[0].participant_id,
                lease_owner="other",
                lease_ttl_s=3,
                now=NOW + timedelta(seconds=4),
            )
            return rh.RoomTransportResult("finished")

    out = asyncio.run(_host(db, Rotate()).pump_once(conversation_id=cid)).deliveries[0]
    assert out.state == "lease_lost" and out.reason == "lease_lost"


def test_timeout_cleanup_is_bounded_completion_wins_and_late_errors_are_consumed(tmp_path):
    async def run(mode, path):
        db, registry, cid, people, sessions = _room(path)
        _post(db, cid, mode)
        release = asyncio.Event()

        class T:
            async def deliver(self, delivery, *, timeout_s):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if mode in {"complete", "pending_complete"}:
                        _service_complete(
                            db,
                            registry,
                            cid,
                            people[0],
                            sessions[people[0].participant_id],
                            delivery,
                        )
                    if mode in {"late", "pending_complete"}:
                        await release.wait()
                    return rh.RoomTransportResult("finished")

        out = (await _host(db, T()).pump_once(conversation_id=cid)).deliveries[0]
        expected = {
            "settled": "delivery_timeout",
            "complete": "completed",
            "pending_complete": "completed",
            "late": "cleanup_timeout",
        }[mode]
        assert (out.reason if mode in {"settled", "late"} else out.state) == expected
        await asyncio.sleep(0, result=release.set())

    for mode in ("settled", "complete", "late", "pending_complete"):
        asyncio.run(run(mode, tmp_path / mode))


def test_cleanup_timeout_holds_global_slot_until_transport_really_stops(tmp_path):
    async def run():
        db, _registry, first_cid, _people, _sessions = _room(tmp_path)
        second_cid = RoomTestStore(db).create_conversation("second-room").id
        ParticipantStore(db).add(
            conversation_id=second_cid,
            role="second",
            display_name="Second",
            cli_kind="codex",
            model="gpt-5",
        )
        _post(db, first_cid, "first")
        _post(db, second_cid, "second")
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release_first = asyncio.Event()

        class T:
            async def deliver(self, delivery, *, timeout_s):
                if delivery.conversation_id == first_cid:
                    first_started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        await release_first.wait()
                else:
                    second_started.set()
                return rh.RoomTransportResult("finished")

        host = _host(db, T(), max_batch_size=1)
        first_pump = asyncio.create_task(host.pump_once(conversation_id=first_cid))
        await first_started.wait()
        first = await first_pump
        assert first.deliveries[0].reason == "cleanup_timeout"

        second_pump = asyncio.create_task(host.pump_once(conversation_id=second_cid))
        for _ in range(5):
            await asyncio.sleep(0)
        assert not second_started.is_set()
        assert RoomKernelStore(db).list_observations(second_cid)[0]["status"] == "pending"

        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=1)
        second = await second_pump
        assert len(second.deliveries) == 1
        assert not host._retained_tasks
        assert host._delivery_slots._value == 1

    asyncio.run(run())


def test_host_cancellation_cleans_all_deliveries_before_reraise(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path, 2)
    _post(db, cid)
    cancelled, release, counts = asyncio.Event(), asyncio.Event(), [0, 0]
    barrier = asyncio.Barrier(2)

    class T:
        async def deliver(self, delivery, *, timeout_s):
            counts[0] += 1
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    counts[1] += 1
                    if counts[1] <= 2:
                        await barrier.wait()
                        cancelled.set()
            return rh.RoomTransportResult("finished")

    async def run():
        host = _host(db, T())
        task = asyncio.create_task(host.pump_once(conversation_id=cid))
        await cancelled.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert counts == [2, 2]
        release.set()
        while host._retained_tasks:
            await asyncio.sleep(0)
        assert host._delivery_slots._value == host._policy.max_batch_size

    asyncio.run(run())
    assert all(o["status"] == "claimed" for o in RoomKernelStore(db).list_observations(cid))


def test_restart_reclaims_once_fences_stale_token_and_stops_after_commit(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path)
    _post(db, cid)
    clock = [NOW]
    first = _Return(rh.RoomTransportResult("failed", "bad"))
    out1 = asyncio.run(_host(db, first, clock[0]).pump_once(conversation_id=cid)).deliveries[0]
    old = first.deliveries[0].observation
    clock[0] = NOW + timedelta(seconds=1)
    pre = _Return()
    assert not asyncio.run(_host(db, pre, clock[0]).pump_once(conversation_id=cid)).deliveries
    clock[0] = NOW + timedelta(seconds=4)
    post = _Return()
    out2 = asyncio.run(_host(db, post, clock[0]).pump_once(conversation_id=cid)).deliveries[0]
    new = post.deliveries[0].observation
    assert out1.attempt_count == 1 and out2.attempt_count == 2
    assert old["lease_token"] != new["lease_token"]
    with pytest.raises(RoomApplicationError, match="room_observation_lease_lost"):
        _service_complete(
            db,
            registry,
            cid,
            people[0],
            sessions[people[0].participant_id],
            first.deliveries[0],
            clock[0],
        )
    _service_complete(
        db,
        registry,
        cid,
        people[0],
        sessions[people[0].participant_id],
        post.deliveries[0],
        clock[0],
    )
    assert not asyncio.run(_host(db, _Return(), clock[0]).pump_once(conversation_id=cid)).deliveries


def test_attempt_cap_and_cooldown_are_stable(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path / "cap")
    _post(db, cid)
    clock = NOW
    for _ in range(2):
        asyncio.run(
            _host(
                db, _Return(rh.RoomTransportResult("failed")), clock, max_attempts_per_observation=2
            ).pump_once(conversation_id=cid)
        )
        clock += timedelta(seconds=4)
    final = asyncio.run(
        _host(db, _Return(), clock, max_attempts_per_observation=2).pump_once(conversation_id=cid)
    )
    assert not final.deliveries
    assert not final.deferrals
    assert RoomKernelStore(db).list_observations(cid)[0]["control_state"] == "exhausted"
    capped = _host(
        db,
        _Return(),
        clock,
        max_attempts_per_observation=2,
    )
    assert capped.list_claimable_conversation_ids() == []
    recoverable = _host(
        db,
        _Return(),
        clock,
        max_attempts_per_observation=3,
    )
    assert recoverable.list_claimable_conversation_ids() == [cid]
    ParticipantStore(db).update_status(people[0].participant_id, "stopped")
    assert recoverable.list_claimable_conversation_ids() == []
    ParticipantStore(db).update_status(people[0].participant_id, "active")
    assert recoverable.list_claimable_conversation_ids() == [cid]
    db, registry, cid, people, sessions = _room(tmp_path / "cooldown")
    _post(db, cid)
    claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=cid, participant_id=people[0].participant_id, lease_owner="x", now=NOW
    )
    delivery = SimpleNamespace(observation=claim["observation"], outcome_client_request_id="done")
    _service_complete(db, registry, cid, people[0], sessions[people[0].participant_id], delivery)
    _post(db, cid, "next")
    before = asyncio.run(
        _host(db, _Return(), NOW + timedelta(seconds=1)).pump_once(conversation_id=cid)
    )
    assert before.deferrals[0].reason == "cooldown" and (
        before.deferrals[0].retry_at == "2026-01-01T00:00:02Z"
    )
    assert asyncio.run(
        _host(db, _Return(), NOW + timedelta(seconds=2)).pump_once(conversation_id=cid)
    ).deliveries


def test_exhausted_infrastructure_frontier_does_not_starve_later_human_root(tmp_path):
    db, _registry, cid, people, _sessions = _room(tmp_path)
    participant_id = people[0].participant_id
    stamp = NOW.isoformat().replace("+00:00", "Z")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, actor_participant_id, causation_id, correlation_id,
                visibility, audience_json, payload_json, materialized_message_id,
                causal_depth, materialized_proposal_id, delivery_mode, created_at)
               values ('old-infrastructure', ?, 1, 'execution.failed', 'infrastructure',
                       'infrastructure:execution-harness', null, 'old-cause',
                       'old-correlation', 'room', '{}', '{}', null, 0, null,
                       'active', ?)""",
            (cid, stamp),
        )
        conn.execute(
            """insert into room_observations
               (observation_id, conversation_id, activity_id, participant_id,
                priority, delivery_mode, status, attempt_count, control_state,
                created_at, updated_at)
               values ('old-exhausted', ?, 'old-infrastructure', ?, 0, 'active',
                       'pending', 3, 'exhausted', ?, ?)""",
            (cid, participant_id, stamp, stamp),
        )
        conn.execute(
            """insert or ignore into room_participant_cursors
               (conversation_id, participant_id, last_acknowledged_seq, updated_at)
               values (?, ?, 0, ?)""",
            (cid, participant_id, stamp),
        )

    posted = _post(db, cid, "later-human")
    transport = _Return()
    result = asyncio.run(_host(db, transport).pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    assert len(transport.deliveries) == 1
    delivered = transport.deliveries[0]
    assert delivered.source_activity["activity_id"] == posted["activity"]["activity_id"]
    assert delivered.source_activity["actor_kind"] == "human"
    assert delivered.observation["attempt_count"] == 1
    observations = {
        item["observation_id"]: item for item in RoomKernelStore(db).list_observations(cid)
    }
    assert observations["old-exhausted"]["control_state"] == "exhausted"
    assert observations[posted["observations"][0]["observation_id"]]["status"] == "claimed"


def test_claim_race_defers_without_transport(tmp_path, monkeypatch):
    db, registry, cid, people, sessions = _room(tmp_path)
    _post(db, cid)
    original, raced = RoomKernelStore.claim_next_observation_batch, [False]

    def race(self, **kwargs):
        if not raced[0]:
            raced[0] = True
            original(self, **{**kwargs, "lease_owner": "competitor"})
        return original(self, **kwargs)

    monkeypatch.setattr(RoomKernelStore, "claim_next_observation_batch", race)
    t = _Return()
    result = asyncio.run(_host(db, t).pump_once(conversation_id=cid))
    assert not t.deliveries and result.deferrals[0].reason == "claim_race"
    assert result.deferrals[0].retry_at is None
