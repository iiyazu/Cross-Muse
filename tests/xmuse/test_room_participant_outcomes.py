from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_identity import verify_room_participant_identity
from xmuse_core.chat.room_kernel import RoomKernelStore


def table_count(conn, table: str) -> int:
    return conn.execute(f"select count(*) from {table}").fetchone()[0]


def assert_tables_absent(conn, *tables: str) -> None:
    present = {
        row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")
    }
    assert present.isdisjoint(tables)


def room(tmp_path: Path, count: int = 3):
    db, registry_path = tmp_path / "chat.db", tmp_path / "god_sessions.json"
    conversation_id = RoomTestStore(db).create_conversation("room").id
    participants = ParticipantStore(db)
    records = []
    for index in range(count):
        participant = participants.add(
            conversation_id=conversation_id,
            role=f"arbitrary-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        session = GodSessionRegistry(registry_path).create(
            participant.role,
            participant.display_name,
            "codex",
            f"addr-{index}",
            f"inbox-{index}",
            conversation_id,
            participant.participant_id,
        )
        records.append((participant, session))
    return db, registry_path, conversation_id, records


def root_and_claims(tmp_path: Path):
    db, registry, conversation_id, records = room(tmp_path)
    root = RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="hello",
        client_request_id="human-1",
    )
    claims = {}
    for participant, _ in records:
        claims[participant.participant_id] = RoomKernelStore(db).claim_next_observation(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            lease_owner=f"lease-{participant.participant_id}",
        )
    return db, registry, conversation_id, records, root, claims


def submit(db, registry, conversation_id, participant, session, claim, request, **kwargs):
    service_kwargs = {}
    if "max_causal_depth" in kwargs:
        service_kwargs["max_causal_depth"] = kwargs.pop("max_causal_depth")
    return RoomApplicationService(db, registry, **service_kwargs).submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        god_session_id=session.god_session_id,
        observation_id=claim["observation"]["observation_id"],
        lease_token=claim["observation"]["lease_token"],
        client_request_id=request,
        **kwargs,
    )


@pytest.mark.parametrize("responders", [0, 1, 2, 3])
def test_flexible_participant_responses_have_no_role_order(tmp_path, responders):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    order = list(reversed(records))
    for index, (participant, session) in enumerate(order):
        outcome = "respond" if index < responders else "noop"
        submit(
            db,
            registry,
            conversation_id,
            participant,
            session,
            claims[participant.participant_id],
            f"request-{index}",
            outcome_type=outcome,
            outcome_payload={"content": f"reply-{index}"} if outcome == "respond" else {},
        )
    store = RoomKernelStore(db)
    observations = store.list_observations(conversation_id)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from room_activities").fetchone()[0] == 1 + responders
        assert (
            conn.execute("select count(*) from messages where role = 'assistant'").fetchone()[0]
            == responders
        )
        assert (
            conn.execute(
                "select count(*) from room_observations where produced_activity_id is not null"
            ).fetchone()[0]
            == responders
        )
        assert (
            conn.execute(
                "select count(*) from room_observations where status = 'completed'"
            ).fetchone()[0]
            == 3
        )
    assert all(
        item["produced_activity_id"] is not None
        for item in observations
        if item["outcome_type"] == "respond"
    )


def test_mentions_only_prioritize_and_unmentioned_can_respond(tmp_path):
    db, registry, conversation_id, records = room(tmp_path)
    first, second, third = records
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="please consider this",
        client_request_id="mention-source",
        mentions=[second[0].participant_id],
    )
    claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=third[0].participant_id,
        lease_owner="third",
    )
    result = submit(
        db,
        registry,
        conversation_id,
        third[0],
        third[1],
        claim,
        "r",
        outcome_type="respond",
        outcome_payload={"content": "one", "mentioned_participant_ids": [first[0].participant_id]},
    )
    priorities = {
        item["participant_id"]: item["priority"] for item in result["downstream_observations"]
    }
    assert priorities[first[0].participant_id] == 100
    assert priorities[second[0].participant_id] == 0


def test_untargeted_peer_batch_allows_one_bounded_followup(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    actor, peer, observer = records
    submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        claims[actor[0].participant_id],
        "actor-root-response",
        outcome_type="respond",
        outcome_payload={"content": "actor answered the human"},
    )
    submit(
        db,
        registry,
        conversation_id,
        peer[0],
        peer[1],
        claims[peer[0].participant_id],
        "peer-root-response",
        outcome_type="respond",
        outcome_payload={"content": "peer answered the human"},
    )
    submit(
        db,
        registry,
        conversation_id,
        observer[0],
        observer[1],
        claims[observer[0].participant_id],
        "observer-root-noop",
        outcome_type="noop",
        outcome_payload={},
    )
    kernel = RoomKernelStore(db)
    peer_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=actor[0].participant_id,
        lease_owner="actor-peer-observation",
    )
    assert peer_claim is not None
    assert peer_claim["activity"]["activity_type"] == "message.responded"
    policy = kernel.get_outcome_policy(peer_claim["observation"]["observation_id"])
    assert policy == {
        "schema_version": "room_outcome_policy/v1",
        "allowed_outcomes": ["respond", "handoff", "propose", "defer", "noop"],
        "respond_available": True,
        "reason": "peer_batch_followup_available",
        "observation_phase": "peer",
    }
    completed = submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        peer_claim,
        "actor-peer-followup",
        outcome_type="respond",
        outcome_payload={"content": "actor synthesizes the peer contribution"},
    )
    assert completed["observation"]["outcome_type"] == "respond"
    assert completed["produced_activity"]["payload"]["context_only"] is True
    assert completed["downstream_observations"] == []


@pytest.mark.parametrize("directed_outcome", ["mention", "handoff"])
def test_directed_peer_speech_prioritizes_baton_without_reopening_budget(
    tmp_path, directed_outcome
):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    actor, peer, observer = records
    submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        claims[actor[0].participant_id],
        "actor-root-response",
        outcome_type="respond",
        outcome_payload={"content": "actor answered the human"},
    )
    if directed_outcome == "mention":
        peer_type = "respond"
        peer_payload = {
            "content": "peer explicitly asks actor",
            "mentioned_participant_ids": [actor[0].participant_id],
        }
    else:
        peer_type = "handoff"
        peer_payload = {
            "content": "peer hands work to actor",
            "target_participant_ids": [actor[0].participant_id],
        }
    submit(
        db,
        registry,
        conversation_id,
        peer[0],
        peer[1],
        claims[peer[0].participant_id],
        f"peer-{directed_outcome}",
        outcome_type=peer_type,
        outcome_payload=peer_payload,
    )
    submit(
        db,
        registry,
        conversation_id,
        observer[0],
        observer[1],
        claims[observer[0].participant_id],
        "observer-root-noop",
        outcome_type="noop",
        outcome_payload={},
    )
    kernel = RoomKernelStore(db)
    directed_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=actor[0].participant_id,
        lease_owner=f"actor-{directed_outcome}",
    )
    assert directed_claim is not None
    policy = kernel.get_outcome_policy(directed_claim["observation"]["observation_id"])
    assert policy["respond_available"] is True
    assert policy["reason"] == "peer_batch_followup_available"
    result = submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        directed_claim,
        f"actor-{directed_outcome}-response",
        outcome_type="respond",
        outcome_payload={"content": "actor handles the directed follow-up"},
    )
    assert result["produced_activity"]["activity_type"] == "message.responded"


def test_proposal_remains_available_in_peer_batch(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    actor, peer, observer = records
    submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        claims[actor[0].participant_id],
        "actor-root-response",
        outcome_type="respond",
        outcome_payload={"content": "actor answered the human"},
    )
    submit(
        db,
        registry,
        conversation_id,
        peer[0],
        peer[1],
        claims[peer[0].participant_id],
        "peer-root-response",
        outcome_type="respond",
        outcome_payload={"content": "peer identifies a concrete defect"},
    )
    submit(
        db,
        registry,
        conversation_id,
        observer[0],
        observer[1],
        claims[observer[0].participant_id],
        "observer-root-noop",
        outcome_type="noop",
        outcome_payload={},
    )
    kernel = RoomKernelStore(db)
    peer_claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=actor[0].participant_id,
        lease_owner="actor-proposal",
    )
    assert peer_claim is not None
    policy = kernel.get_outcome_policy(peer_claim["observation"]["observation_id"])
    assert "respond" in policy["allowed_outcomes"]
    assert "propose" in policy["allowed_outcomes"]
    result = submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        peer_claim,
        "actor-fix-proposal",
        outcome_type="propose",
        outcome_payload={
            "proposal_type": "repair",
            "content": "fix the echo at the durable outcome boundary",
        },
    )
    assert result["produced_activity"]["activity_type"] == "proposal.created"


def test_concurrent_responses_share_frontier_causation_and_unique_seq(tmp_path):
    db, registry, conversation_id, records, root, claims = root_and_claims(tmp_path)

    def run(item):
        participant, session = item
        return submit(
            db,
            registry,
            conversation_id,
            participant,
            session,
            claims[participant.participant_id],
            f"r-{participant.participant_id}",
            outcome_type="respond",
            outcome_payload={"content": participant.role},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, records[:2]))
    activities = [item["produced_activity"] for item in results]
    assert len({item["seq"] for item in activities}) == 2
    assert all(item["causation_id"] == root["activity"]["activity_id"] for item in activities)
    assert all(item["correlation_id"] == root["activity"]["correlation_id"] for item in activities)
    downstream_pairs = [
        (observation["activity_id"], observation["participant_id"])
        for result in results
        for observation in result["downstream_observations"]
    ]
    assert len(downstream_pairs) == len(set(downstream_pairs))
    assert {item["actor_participant_id"] for item in activities} == {
        r[0].participant_id for r in records[:2]
    }
    assert {item["actor_identity"] for item in activities} == {
        f"god:{session.god_session_id}:{participant.participant_id}"
        for participant, session in records[:2]
    }
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute("select count(*) from messages where role = 'assistant'").fetchone()[0]
            == 2
        )
        for activity in activities:
            assert (
                conn.execute(
                    "select count(*) from room_observations where activity_id = ?",
                    (activity["activity_id"],),
                ).fetchone()[0]
                == len(records) - 1
            )


def test_noop_and_defer_materialize_nothing(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    for index, (participant, session) in enumerate(records[:2]):
        result = submit(
            db,
            registry,
            conversation_id,
            participant,
            session,
            claims[participant.participant_id],
            f"r-{index}",
            outcome_type="defer" if index else "noop",
            outcome_payload={"wake_condition": "later"} if index else {},
        )
        assert result["produced_activity"] is None
        assert result["produced_message"] is None
        assert result["produced_proposal"] is None
        assert result["downstream_observations"] == []
        assert result["observation"]["status"] == "completed"
        assert result["cursor"]["last_acknowledged_seq"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from room_activities").fetchone()[0] == 1
        assert conn.execute("select count(*) from messages").fetchone()[0] == 1
        assert conn.execute("select count(*) from proposals").fetchone()[0] == 0


def test_handoff_priorities_every_other_participant(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    actor, target, other = records
    result = submit(
        db,
        registry,
        conversation_id,
        actor[0],
        actor[1],
        claims[actor[0].participant_id],
        "handoff",
        outcome_type="handoff",
        outcome_payload={
            "content": "take this",
            "target_participant_ids": [target[0].participant_id],
        },
    )
    assert result["produced_message"]["envelope_type"] == "room_handoff"
    assert result["produced_message"]["envelope_json"] == {
        "type": "room_handoff",
        "participant_id": actor[0].participant_id,
        "participant_role": actor[0].role,
        "display_name": actor[0].display_name,
        "proof_boundary": "identity_bound_room_outcome",
    }
    assert {
        item["participant_id"]: item["priority"] for item in result["downstream_observations"]
    } == {target[0].participant_id: 100, other[0].participant_id: 0}
    with sqlite3.connect(db) as conn:
        assert_tables_absent(
            conn,
            "chat_inbox_items",
            "groupchat_worklist",
            "chat_turn_budgets",
            "acceptance_spines",
            "groupchat_decisions",
            "groupchat_invocations",
        )
        assert table_count(conn, "chat_frontend_events") == 5
    assert result["produced_activity"]["activity_type"] == "room.handoff"
    assert {item["priority"] for item in result["downstream_observations"]} == {0, 100}


def test_any_persona_can_propose_without_acceptance_spine(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    result = submit(
        db,
        registry,
        conversation_id,
        records[2][0],
        records[2][1],
        claims[records[2][0].participant_id],
        "proposal",
        outcome_type="propose",
        outcome_payload={"proposal_type": "idea", "content": "do it"},
    )
    assert result["produced_message"] is None
    assert result["produced_proposal"]["status"] == "open"
    assert result["produced_activity"]["activity_type"] == "proposal.created"
    assert {item["priority"] for item in result["downstream_observations"]} == {0}
    with sqlite3.connect(db) as conn:
        assert_tables_absent(
            conn,
            "chat_inbox_items",
            "groupchat_worklist",
            "chat_turn_budgets",
            "acceptance_spines",
            "groupchat_decisions",
            "groupchat_invocations",
        )
        assert table_count(conn, "chat_frontend_events") == 5


def test_hop_guard_retains_activity_without_downstream(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    result = submit(
        db,
        registry,
        conversation_id,
        records[0][0],
        records[0][1],
        claims[records[0][0].participant_id],
        "hop",
        outcome_type="respond",
        max_causal_depth=1,
        outcome_payload={"content": "edge"},
    )
    assert result["produced_activity"]["causal_depth"] == 1
    assert result["downstream_observations"] == []


def test_exact_replay_and_conflict(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    args = dict(outcome_type="respond", outcome_payload={"content": "same"})
    first = submit(
        db,
        registry,
        conversation_id,
        records[0][0],
        records[0][1],
        claims[records[0][0].participant_id],
        "same",
        **args,
    )
    with sqlite3.connect(db) as conn:
        before = {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in (
                "messages",
                "room_activities",
                "room_observations",
                "proposals",
                "chat_request_log",
                "chat_frontend_events",
            )
        }
        assert_tables_absent(
            conn,
            "chat_inbox_items",
            "groupchat_worklist",
            "chat_turn_budgets",
            "acceptance_spines",
            "groupchat_decisions",
            "groupchat_invocations",
        )
    assert (
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            records[0][1],
            claims[records[0][0].participant_id],
            "same",
            **args,
        )
        == first
    )
    with sqlite3.connect(db) as conn:
        after = {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0] for table in before
        }
    assert after == before
    with pytest.raises(RoomApplicationError, match="room_observation_idempotency_conflict"):
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            records[0][1],
            claims[records[0][0].participant_id],
            "same",
            outcome_type="respond",
            outcome_payload={"content": "changed"},
        )
    with pytest.raises(RoomApplicationError, match="room_observation_already_completed"):
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            records[0][1],
            claims[records[0][0].participant_id],
            "other-request",
            outcome_type="noop",
            outcome_payload={},
        )


def test_handoff_replay_survives_stopped_actor_and_target(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    actor, target, _ = records
    payload = {
        "content": "take this",
        "target_participant_ids": [target[0].participant_id],
    }
    first = submit(
        db,
        registry,
        conversation_id,
        actor[0],
        records[0][1],
        claims[actor[0].participant_id],
        "handoff-replay",
        outcome_type="handoff",
        outcome_payload=payload,
    )
    second_source = RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human-2",
        content="independent",
        client_request_id="human-2",
    )
    second_claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=actor[0].participant_id,
        lease_owner="second-lease",
    )
    assert second_claim["observation"]["activity_id"] == second_source["activity"]["activity_id"]
    participants = ParticipantStore(db)
    participants.update_status(actor[0].participant_id, "stopped")
    participants.update_status(target[0].participant_id, "stopped")
    assert (
        submit(
            db,
            registry,
            conversation_id,
            actor[0],
            records[0][1],
            claims[actor[0].participant_id],
            "handoff-replay",
            outcome_type="handoff",
            outcome_payload=payload,
        )
        == first
    )
    with pytest.raises(RoomApplicationError, match="room_participant_not_active"):
        submit(
            db,
            registry,
            conversation_id,
            actor[0],
            records[0][1],
            second_claim,
            "new-stopped-request",
            outcome_type="noop",
            outcome_payload={},
        )
    assert (
        RoomKernelStore(db).get_observation(second_claim["observation"]["observation_id"])[
            "lease_token"
        ]
        == second_claim["observation"]["lease_token"]
    )


@pytest.mark.parametrize(
    ("outcome_type", "payload", "code"),
    [
        (
            "respond",
            {"content": "x", "mentioned_participant_ids": None},
            "room_mentioned_participant_ids_invalid",
        ),
        (
            "respond",
            {"content": "x", "mentioned_participant_ids": [{}]},
            "room_mentioned_participant_ids_invalid",
        ),
        (
            "respond",
            {"content": "x", "mentioned_participant_ids": ["a", "a"]},
            "room_mentioned_participant_ids_invalid",
        ),
        ("invalid", {}, "room_observation_outcome_invalid"),
    ],
)
def test_invalid_shapes_and_payload_authority_are_stable(tmp_path, outcome_type, payload, code):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    with pytest.raises(RoomApplicationError, match=code):
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            records[0][1],
            claims[records[0][0].participant_id],
            f"invalid-{code}",
            outcome_type=outcome_type,
            outcome_payload=payload,
        )
    with pytest.raises(RoomApplicationError, match="room_outcome_target_invalid"):
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            records[0][1],
            claims[records[0][0].participant_id],
            "self-target",
            outcome_type="handoff",
            outcome_payload={
                "content": "x",
                "target_participant_ids": [records[0][0].participant_id],
            },
        )
    with pytest.raises(RoomApplicationError, match="room_outcome_target_invalid"):
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            records[0][1],
            claims[records[0][0].participant_id],
            "unknown-target",
            outcome_type="handoff",
            outcome_payload={"content": "x", "target_participant_ids": ["missing"]},
        )
    if outcome_type == "invalid":
        return
    trusted = submit(
        db,
        registry,
        conversation_id,
        records[0][0],
        records[0][1],
        claims[records[0][0].participant_id],
        f"trusted-{code}",
        outcome_type="respond",
        max_causal_depth=1,
        outcome_payload={"content": "trusted"},
    )
    assert trusted["produced_activity"]["actor_identity"] == (
        f"god:{records[0][1].god_session_id}:{records[0][0].participant_id}"
    )
    assert trusted["produced_message"]["author"] == records[0][0].participant_id
    assert trusted["produced_activity"]["causal_depth"] == 1
    assert trusted["downstream_observations"] == []


def test_unknown_nested_outcome_authority_fields_reject_without_writes(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    participant, session = records[0]
    claim = claims[participant.participant_id]
    tables = ("messages", "room_activities", "room_observations", "chat_request_log")
    with sqlite3.connect(db) as conn:
        before = {table: table_count(conn, table) for table in tables}
    with pytest.raises(RoomApplicationError, match="room_observation_payload_invalid"):
        submit(
            db,
            registry,
            conversation_id,
            participant,
            session,
            claim,
            "unknown-fields",
            outcome_type="respond",
            outcome_payload={
                "content": "rejected",
                "author": "caller",
                "role": "observer",
                "caller_identity": "fake",
                "max_causal_depth": 99,
                "budget": 1,
            },
        )
    with sqlite3.connect(db) as conn:
        after = {table: table_count(conn, table) for table in tables}
    assert after == before
    observation = RoomKernelStore(db).get_observation(claim["observation"]["observation_id"])
    assert observation["status"] == "claimed"
    assert observation["lease_token"] == claim["observation"]["lease_token"]


def test_lifecycle_failure_rolls_back_and_retry_keeps_lease(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    actor, session = records[0]
    claim = claims[actor.participant_id]
    store = RoomKernelStore(db)
    original = RoomKernelStore._insert_lifecycle_request_log_conn

    def fail(*args, **kwargs):
        raise RuntimeError("injected lifecycle failure")

    RoomKernelStore._insert_lifecycle_request_log_conn = fail
    try:
        with pytest.raises(RuntimeError, match="injected lifecycle failure"):
            submit(
                db,
                registry,
                conversation_id,
                actor,
                session,
                claim,
                "rollback",
                outcome_type="respond",
                outcome_payload={"content": "retry"},
            )
    finally:
        RoomKernelStore._insert_lifecycle_request_log_conn = original
    observation = store.get_observation(claim["observation"]["observation_id"])
    assert observation["status"] == "claimed"
    assert observation["lease_token"] == claim["observation"]["lease_token"]
    assert observation["produced_activity_id"] is None
    assert observation["produced_message_id"] is None
    assert observation["produced_proposal_id"] is None
    assert (
        store.get_participant_cursor(conversation_id, actor.participant_id)["last_acknowledged_seq"]
        == 0
    )
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from room_observations").fetchone()[0] == 3
        assert conn.execute("select count(*) from room_activities").fetchone()[0] == 1
        assert conn.execute("select count(*) from messages").fetchone()[0] == 1
        assert (
            conn.execute(
                "select count(*) from chat_request_log where client_request_id = 'rollback'"
            ).fetchone()[0]
            == 0
        )
    result = submit(
        db,
        registry,
        conversation_id,
        actor,
        session,
        claim,
        "rollback",
        outcome_type="respond",
        outcome_payload={"content": "retry"},
    )
    assert result["produced_message"]["content"] == "retry"
    assert (
        result["observation"]["produced_activity_id"] == result["produced_activity"]["activity_id"]
    )
    assert result["cursor"]["last_acknowledged_seq"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from room_observations").fetchone()[0] == 5
        assert (
            conn.execute("select count(*) from messages where role = 'assistant'").fetchone()[0]
            == 1
        )


def test_registry_spoofing_cannot_close_observation(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)

    def counts():
        with sqlite3.connect(db) as conn:
            return tuple(
                conn.execute(f"select count(*) from {table}").fetchone()[0]
                for table in ("messages", "room_activities", "proposals", "chat_request_log")
            )

    baseline = counts()
    for label, participant, session, expected in (
        ("wrong", records[0][0], records[1][1], "session_participant_mismatch"),
        ("unknown", records[0][0], "missing-session", "unknown_god_session"),
    ):
        with pytest.raises(RoomApplicationError, match=expected):
            if isinstance(session, str):
                RoomApplicationService(db, registry).submit_participant_outcome(
                    conversation_id=conversation_id,
                    participant_id=participant.participant_id,
                    god_session_id=session,
                    observation_id=claims[records[0][0].participant_id]["observation"][
                        "observation_id"
                    ],
                    lease_token=claims[records[0][0].participant_id]["observation"]["lease_token"],
                    client_request_id=label,
                    outcome_type="respond",
                    outcome_payload={"content": "no"},
                )
            else:
                submit(
                    db,
                    registry,
                    conversation_id,
                    participant,
                    session,
                    claims[records[0][0].participant_id],
                    label,
                    outcome_type="respond",
                    outcome_payload={"content": "no"},
                )
        assert counts() == baseline
    other_conversation = RoomTestStore(db).create_conversation("other-room").id
    other_participant = ParticipantStore(db).add(
        conversation_id=other_conversation,
        role="other-agent",
        display_name="Other Agent",
        cli_kind="codex",
        model="gpt-5",
    )
    other_session = GodSessionRegistry(registry).create(
        other_participant.role,
        other_participant.display_name,
        "codex",
        "other-address",
        "other-inbox",
        other_conversation,
        other_participant.participant_id,
    )
    with pytest.raises(RoomApplicationError, match="session_participant_mismatch"):
        submit(
            db,
            registry,
            conversation_id,
            records[0][0],
            other_session,
            claims[records[0][0].participant_id],
            "other-conversation",
            outcome_type="respond",
            outcome_payload={"content": "no"},
        )
    assert counts() == baseline
    assert (
        RoomKernelStore(db).get_observation(
            claims[records[0][0].participant_id]["observation"]["observation_id"]
        )["status"]
        == "claimed"
    )


def test_room_identity_preserves_membership_role_and_caller_authority(tmp_path):
    db, registry, conversation_id, records = room(tmp_path, count=1)
    participant, session = records[0]
    participants = ParticipantStore(db)

    identity = verify_room_participant_identity(
        participants,
        registry_path=registry,
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        god_session_id=session.god_session_id,
        required_role=participant.role,
    )
    assert identity.participant == participant
    assert identity.caller_identity == (
        f"god:{session.god_session_id}:{participant.participant_id}"
    )

    missing_participant_session = GodSessionRegistry(registry).create(
        "missing-role",
        "Missing Agent",
        "codex",
        "missing-address",
        "missing-inbox",
        conversation_id,
        "missing-participant",
    )
    with pytest.raises(RoomApplicationError) as unknown:
        verify_room_participant_identity(
            participants,
            registry_path=registry,
            conversation_id=conversation_id,
            participant_id="missing-participant",
            god_session_id=missing_participant_session.god_session_id,
        )
    assert unknown.value.code == "unknown_participant"
    assert unknown.value.message == "missing-participant"
    assert unknown.value.details == {}

    with pytest.raises(RoomApplicationError) as forbidden:
        verify_room_participant_identity(
            participants,
            registry_path=registry,
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            god_session_id=session.god_session_id,
            required_role="reviewer",
        )
    assert forbidden.value.code == "participant_role_forbidden"
    assert forbidden.value.message == "participant role must be reviewer"
    assert forbidden.value.details == {
        "participant_id": participant.participant_id,
        "participant_role": participant.role,
        "required_role": "reviewer",
    }


def test_static_application_boundary():
    source = Path("src/xmuse_core/chat/room_application.py").read_text()
    error_source = Path("src/xmuse_core/chat/room_errors.py").read_text()
    identity_source = Path("src/xmuse_core/chat/room_identity.py").read_text()
    kernel_source = Path("src/xmuse_core/chat/room_kernel.py").read_text()
    forbidden = (
        "PeerChatScheduler",
        "ImmediateTurnRouter",
        "peer_service_authority",
        "peer_types",
        "platform",
        "structuring",
        "dashboard",
        "self_evolution",
        "A2A",
    )
    room_boundary = source + error_source + identity_source
    assert not any(item in room_boundary for item in forbidden)
    assert not any(item in kernel_source for item in forbidden)


def test_visible_completion_outcomes_and_depth_constructor_validation(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    kernel = RoomKernelStore(db)
    for outcome in ("respond", "handoff", "propose"):
        with pytest.raises(ValueError, match="room_observation_outcome_invalid"):
            kernel.complete_observation(
                conversation_id=conversation_id,
                participant_id=records[0][0].participant_id,
                caller_identity=f"god:{records[0][1].god_session_id}:{records[0][0].participant_id}",
                observation_id=claims[records[0][0].participant_id]["observation"][
                    "observation_id"
                ],
                lease_token=claims[records[0][0].participant_id]["observation"]["lease_token"],
                client_request_id=f"complete-{outcome}",
                outcome_type=outcome,
                outcome_payload={},
            )
    for value in (True, 0, -1, 1.5, "1"):
        with pytest.raises(ValueError, match="room_max_causal_depth_invalid"):
            RoomApplicationService(db, registry, max_causal_depth=value)
