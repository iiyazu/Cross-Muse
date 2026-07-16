from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_execution_store import RoomExecutionStore
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore


def _room(tmp_path: Path, count: int = 3):
    db, registry = tmp_path / "chat.db", tmp_path / "god_sessions.json"
    conversation = RoomTestStore(db).create_conversation("room")
    ps, sessions = ParticipantStore(db), {}
    for i in range(count):
        p = ps.add(
            conversation_id=conversation.id,
            role=f"r{i}",
            display_name=f"P{i}",
            cli_kind="codex",
            model="gpt-5",
        )
        sessions[p.participant_id] = GodSessionRegistry(registry).create(
            p.role, p.display_name, "codex", f"a{i}", f"i{i}", conversation.id, p.participant_id
        )
    return db, registry, conversation.id, ps.list_by_conversation(conversation.id), sessions


class _Transport:
    def __init__(self, db=None, registry=None, sessions=None, complete=frozenset()):
        self.db, self.registry, self.sessions, self.complete = db, registry, sessions, complete
        self.deliveries: list[RoomObservationDelivery] = []

    async def deliver(self, delivery, *, timeout_s):
        self.deliveries.append(delivery)
        if delivery.participant.participant_id in self.complete:
            p = delivery.participant
            RoomApplicationService(self.db, self.registry).submit_participant_outcome(
                conversation_id=delivery.conversation_id,
                participant_id=p.participant_id,
                god_session_id=self.sessions[p.participant_id].god_session_id,
                observation_id=delivery.observation["observation_id"],
                lease_token=delivery.observation["lease_token"],
                client_request_id=delivery.outcome_client_request_id,
                outcome_type="noop",
                outcome_payload={},
            )
        return RoomTransportResult("finished")


class _UnavailableMemoryRuntime:
    def __init__(self) -> None:
        self.receipts = []
        self.binds = []

    async def recall(self, _request):
        raise OSError("sidecar stopped")

    def record_recall_receipt(self, **kwargs):
        self.receipts.append(kwargs)

    def bind_context_receipt(self, **kwargs):
        self.binds.append(kwargs)

    async def pump_once(self):
        return False


def test_public_contract_types_and_policy_validation():
    assert RoomHostPolicy().lease_ttl_s > 185
    assert RoomObservationDelivery.__dataclass_fields__["participant"].type == "Participant"
    with pytest.raises(ValueError):
        RoomHostPolicy(delivery_timeout_s=True)
    with pytest.raises(ValueError):
        RoomHostPolicy(lease_ttl_s=185)


def test_core_selects_oldest_frontier_then_priority_and_bounds_context(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path)
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=cid,
        human_id="h",
        content="one",
        client_request_id="1",
        mentions=[people[1].participant_id],
    )
    kernel.post_human_activity(
        conversation_id=cid, human_id="h", content="two", client_request_id="2"
    )
    transport = _Transport()
    policy = RoomHostPolicy(max_batch_size=2, context_activity_limit=1, participant_cooldown_s=0)
    result = asyncio.run(
        RoomParticipantHost(db, transport, policy=policy).pump_once(conversation_id=cid)
    )
    expected = [people[1].participant_id] + sorted(
        p.participant_id for p in people if p is not people[1]
    )[:1]
    assert [d.participant.participant_id for d in transport.deliveries] == expected
    assert len(transport.deliveries[0].recent_activities) == 1
    assert transport.deliveries[0].source_activity["seq"] == 1
    delivered = {d.participant.participant_id for d in transport.deliveries}
    assert any(
        d.reason == "batch_budget" and d.participant_id not in delivered for d in result.deferrals
    )
    second = asyncio.run(
        RoomParticipantHost(db, _Transport(), policy=policy).pump_once(conversation_id=cid)
    )
    assert len(second.deliveries) == 2
    assert all(item.attempt_count == 2 for item in second.deliveries)
    assert not [d for d in second.deferrals if d.reason == "lease_active"]


def test_core_normal_delivery_requires_durable_outcome(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path, 2)
    RoomKernelStore(db).post_human_activity(
        conversation_id=cid, human_id="h", content="hello", client_request_id="h"
    )
    transport = _Transport(db, registry, sessions, {people[0].participant_id})
    result = asyncio.run(
        RoomParticipantHost(
            db, transport, policy=RoomHostPolicy(participant_cooldown_s=0)
        ).pump_once(conversation_id=cid)
    )
    states = {item.participant_id: item for item in result.deliveries}
    assert states[people[0].participant_id].state == "completed"
    assert states[people[1].participant_id].state == "incomplete"
    assert states[people[1].participant_id].reason == "durable_outcome_missing"


def test_native_delivery_gate_prevents_claim_and_filters_fully_held_room(tmp_path):
    db, _registry, cid, people, _sessions = _room(tmp_path, 2)
    RoomKernelStore(db).post_human_activity(
        conversation_id=cid, human_id="h", content="hello", client_request_id="held"
    )
    accepting = {people[0].participant_id}
    transport = _Transport(
        db,
        _registry,
        _sessions,
        {people[0].participant_id},
    )
    host = RoomParticipantHost(
        db,
        transport,
        policy=RoomHostPolicy(participant_cooldown_s=0),
        delivery_gate=lambda participant_id: participant_id in accepting,
    )

    assert host.list_claimable_conversation_ids() == [cid]
    result = asyncio.run(host.pump_once(conversation_id=cid))
    assert [item.participant.participant_id for item in transport.deliveries] == [
        people[0].participant_id
    ]
    assert [(item.participant_id, item.reason) for item in result.deferrals] == [
        (people[1].participant_id, "native_hold")
    ]
    accepting.clear()
    accepting.add(people[0].participant_id)
    assert host.list_claimable_conversation_ids() == []
    accepting.add(people[1].participant_id)
    assert host.list_claimable_conversation_ids() == [cid]
    accepting.clear()
    assert host.list_claimable_conversation_ids() == []


def test_memory_sidecar_failure_is_attention_and_room_still_completes(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path, 1)
    RoomKernelStore(db).post_human_activity(
        conversation_id=cid,
        human_id="h",
        content="continue without derived memory",
        client_request_id="memory-unavailable-root",
    )
    transport = _Transport(db, registry, sessions, {people[0].participant_id})
    memory = _UnavailableMemoryRuntime()
    host = RoomParticipantHost(
        db,
        transport,
        memory_runtime=memory,
        policy=RoomHostPolicy(participant_cooldown_s=0),
    )

    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert result.deliveries[0].state == "completed"
    assert transport.deliveries[0].memory_evidence.status == "error"
    assert len(memory.receipts) == 1
    assert memory.receipts[0]["evidence"].status == "error"
    assert host.runtime_health_snapshot()["state"] == "attention"
    assert host.runtime_health_snapshot()["code"] == "room_memory_degraded"


def test_host_delivers_one_authoritative_peer_batch_followup_budget(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path, 2)
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=cid,
        human_id="h",
        content="answer once",
        client_request_id="human-root",
    )
    claims = {
        person.participant_id: kernel.claim_next_observation(
            conversation_id=cid,
            participant_id=person.participant_id,
            lease_owner=f"root-{person.participant_id}",
        )
        for person in people
    }
    for person in people:
        claim = claims[person.participant_id]
        assert claim is not None
        RoomApplicationService(db, registry).submit_participant_outcome(
            conversation_id=cid,
            participant_id=person.participant_id,
            god_session_id=sessions[person.participant_id].god_session_id,
            observation_id=claim["observation"]["observation_id"],
            lease_token=claim["observation"]["lease_token"],
            client_request_id=f"root-response-{person.participant_id}",
            outcome_type="respond",
            outcome_payload={"content": f"response from {person.role}"},
        )
    transport = _Transport()

    asyncio.run(
        RoomParticipantHost(
            db,
            transport,
            policy=RoomHostPolicy(participant_cooldown_s=0),
        ).pump_once(conversation_id=cid)
    )

    assert transport.deliveries
    assert all("respond" in delivery.allowed_outcomes for delivery in transport.deliveries)
    assert all(
        delivery.outcome_policy_reason == "peer_batch_followup_available"
        for delivery in transport.deliveries
    )
    assert all(
        delivery.batch is not None and delivery.batch["phase"] == "peer"
        for delivery in transport.deliveries
    )


def test_host_claims_one_peer_batch_per_participant_after_root_barrier(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path, 3)
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=cid,
        human_id="human",
        content="Compare independent evidence",
        client_request_id="human-root-batch",
    )
    for person in people:
        claim = kernel.claim_next_observation_batch(
            conversation_id=cid,
            participant_id=person.participant_id,
            lease_owner=f"root-{person.participant_id}",
        )
        assert claim is not None
        assert claim["batch"]["phase"] == "root"
        RoomApplicationService(db, registry).submit_participant_outcome(
            conversation_id=cid,
            participant_id=person.participant_id,
            god_session_id=sessions[person.participant_id].god_session_id,
            observation_id=claim["observation"]["observation_id"],
            lease_token=claim["observation"]["lease_token"],
            client_request_id=f"root-response-{person.participant_id}",
            outcome_type="respond",
            outcome_payload={"content": f"evidence from {person.display_name}"},
        )

    transport = _Transport()
    asyncio.run(
        RoomParticipantHost(
            db,
            transport,
            policy=RoomHostPolicy(
                participant_cooldown_s=0,
                max_batch_size=3,
            ),
            execution_store=RoomExecutionStore(db),
        ).pump_once(conversation_id=cid)
    )

    assert len(transport.deliveries) == 3
    batches = [delivery.batch for delivery in transport.deliveries]
    assert all(batch is not None for batch in batches)
    assert {batch["phase"] for batch in batches if batch is not None} == {"peer"}
    assert {batch["member_count"] for batch in batches if batch is not None} == {2}
    assert all(delivery.human_root is not None for delivery in transport.deliveries)
    assert all(
        delivery.context_coverage is not None
        and delivery.context_coverage["causal_ancestry_omitted_count"] == 0
        for delivery in transport.deliveries
    )
    assert all(not delivery.execution_review_materials for delivery in transport.deliveries)


def test_host_loads_exact_execution_material_for_current_peer_batch(tmp_path):
    db, registry, cid, people, sessions = _room(tmp_path, 2)
    author, reviewer = people
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=cid,
        human_id="human",
        content="Propose and review one exact patch",
        client_request_id="human-execution-root",
    )
    author_claim = kernel.claim_next_observation_batch(
        conversation_id=cid,
        participant_id=author.participant_id,
        lease_owner="author-root",
    )
    reviewer_claim = kernel.claim_next_observation_batch(
        conversation_id=cid,
        participant_id=reviewer.participant_id,
        lease_owner="reviewer-root",
    )
    assert author_claim is not None and reviewer_claim is not None
    path = "src/xmuse_core/example.py"
    unified_diff = (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n+++ b/{path}\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    proposal = RoomApplicationService(db, registry).submit_participant_outcome(
        conversation_id=cid,
        participant_id=author.participant_id,
        god_session_id=sessions[author.participant_id].god_session_id,
        observation_id=author_claim["observation"]["observation_id"],
        lease_token=author_claim["observation"]["lease_token"],
        client_request_id="author-execution-proposal",
        outcome_type="propose",
        outcome_payload={
            "proposal_type": "execution_patch",
            "content": "ignored raw proposal text",
            "references": [],
            "execution_patch": {
                "schema_version": "room_execution_patch/v1",
                "base_head": "a" * 40,
                "summary": "Change the example",
                "unified_diff": unified_diff,
                "allowed_files": [path],
            },
        },
        observation_batch_id=author_claim["batch"]["batch_id"],
    )
    RoomApplicationService(db, registry).submit_participant_outcome(
        conversation_id=cid,
        participant_id=reviewer.participant_id,
        god_session_id=sessions[reviewer.participant_id].god_session_id,
        observation_id=reviewer_claim["observation"]["observation_id"],
        lease_token=reviewer_claim["observation"]["lease_token"],
        client_request_id="reviewer-root-noop",
        outcome_type="noop",
        outcome_payload={},
        observation_batch_id=reviewer_claim["batch"]["batch_id"],
    )
    transport = _Transport()

    asyncio.run(
        RoomParticipantHost(
            db,
            transport,
            policy=RoomHostPolicy(participant_cooldown_s=0),
            execution_store=RoomExecutionStore(db),
        ).pump_once(conversation_id=cid)
    )

    assert len(transport.deliveries) == 1
    delivery = transport.deliveries[0]
    assert delivery.participant.participant_id == reviewer.participant_id
    assert delivery.batch is not None and delivery.batch["phase"] == "peer"
    assert len(delivery.execution_review_materials) == 1
    material = delivery.execution_review_materials[0]
    assert material["candidate_id"] == proposal["execution_candidate"]["candidate_id"]
    assert material["proposal_id"] == proposal["produced_proposal"]["id"]
    assert material["proposal_activity_id"] == proposal["produced_activity"]["activity_id"]
    assert material["unified_diff"] == unified_diff


def test_host_wide_provider_cap_is_fair_across_rooms_and_claims_lazily(tmp_path):
    async def run():
        db = tmp_path / "chat.db"
        room_ids = []
        for room_index in range(2):
            conversation_id = RoomTestStore(db).create_conversation(f"room-{room_index}").id
            room_ids.append(conversation_id)
            participants = ParticipantStore(db)
            for participant_index in range(3):
                participants.add(
                    conversation_id=conversation_id,
                    role=f"r{participant_index}",
                    display_name=f"P{room_index}-{participant_index}",
                    cli_kind="codex",
                    model="gpt-5",
                )
            RoomKernelStore(db).post_human_activity(
                conversation_id=conversation_id,
                human_id="human",
                content="start",
                client_request_id=f"start-{room_index}",
            )

        class BlockingTransport:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.started_by_room: dict[str, int] = {}
                self.changed = asyncio.Event()
                self.release = asyncio.Event()

            async def deliver(self, delivery, *, timeout_s):
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.started_by_room[delivery.conversation_id] = (
                    self.started_by_room.get(delivery.conversation_id, 0) + 1
                )
                self.changed.set()
                try:
                    await self.release.wait()
                finally:
                    self.active -= 1
                    self.changed.set()
                return RoomTransportResult("finished")

        transport = BlockingTransport()
        cap = 3
        host = RoomParticipantHost(
            db,
            transport,
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.1,
                lease_ttl_s=3,
                participant_cooldown_s=0,
                max_batch_size=cap,
            ),
        )
        pumps = [
            asyncio.create_task(host.pump_once(conversation_id=conversation_id))
            for conversation_id in room_ids
        ]

        async def wait_for_fair_first_wave():
            while transport.active < cap or set(transport.started_by_room) != set(room_ids):
                transport.changed.clear()
                await transport.changed.wait()

        results = None
        try:
            await asyncio.wait_for(wait_for_fair_first_wave(), timeout=1)
            observations = [
                observation
                for conversation_id in room_ids
                for observation in RoomKernelStore(db).list_observations(conversation_id)
            ]
            assert sum(item["status"] == "claimed" for item in observations) == cap
            assert sum(item["status"] == "pending" for item in observations) == cap
        finally:
            transport.release.set()
            results = await asyncio.gather(*pumps)

        assert transport.max_active <= cap
        assert transport.active == 0
        assert set(transport.started_by_room) == set(room_ids)
        assert [len(result.deliveries) for result in results] == [3, 3]

    asyncio.run(run())
