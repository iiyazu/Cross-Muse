from __future__ import annotations

import sqlite3

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_kernel import RoomKernelStore


def _room(tmp_path, count: int = 3):
    path = tmp_path / "chat.db"
    conversation = RoomTestStore(path).create_conversation("batched room")
    participants = ParticipantStore(path)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(count)
    ]
    return path, conversation.id, members


def _complete(kernel, conversation_id, participant, claim, request, outcome, payload=None, **extra):
    return kernel.submit_participant_outcome(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        caller_identity=f"god:session:{participant.participant_id}",
        observation_id=claim["observation"]["observation_id"],
        observation_batch_id=claim["batch"]["batch_id"],
        lease_token=claim["observation"]["lease_token"],
        client_request_id=request,
        outcome_type=outcome,
        outcome_payload=payload or {},
        **extra,
    )


def _root_claims(kernel, conversation_id, members):
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="work together",
        client_request_id="human-root",
    )
    return [
        kernel.claim_next_observation_batch(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            lease_owner=f"root-{index}",
        )
        for index, participant in enumerate(members)
    ]


def test_peer_batch_waits_for_root_barrier_and_completes_once_with_reply(tmp_path):
    path, conversation_id, members = _room(tmp_path)
    kernel = RoomKernelStore(path)
    claims = _root_claims(kernel, conversation_id, members)
    assert all(claim and claim["batch"]["phase"] == "root" for claim in claims)

    _complete(kernel, conversation_id, members[0], claims[0], "root-0", "respond", {"content": "A"})
    _complete(kernel, conversation_id, members[1], claims[1], "root-1", "respond", {"content": "B"})
    assert (
        kernel.claim_next_observation_batch(
            conversation_id=conversation_id,
            participant_id=members[0].participant_id,
            lease_owner="peer-before-barrier",
        )
        is None
    )
    _complete(kernel, conversation_id, members[2], claims[2], "root-2", "respond", {"content": "C"})

    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="peer-after-barrier",
    )
    assert peer is not None
    assert peer["batch"]["phase"] == "peer"
    assert peer["batch"]["member_count"] == 2
    assert peer["attempt"]["batch_id"] == peer["batch"]["batch_id"]
    reply_target = peer["batch"]["members"][1]["activity"]["activity_id"]
    completed = _complete(
        kernel,
        conversation_id,
        members[0],
        peer,
        "peer-response",
        "respond",
        {"content": "synthesized follow-up"},
        reply_to_activity_id=reply_target,
    )

    assert completed["produced_activity"]["causation_id"] == reply_target
    assert completed["produced_activity"]["payload"]["context_only"] is True
    assert (
        completed["produced_message"]["reply_to_message_id"]
        == peer["batch"]["members"][1]["activity"]["materialized_message_id"]
    )
    assert completed["downstream_observations"] == []
    member_ids = [item["observation"]["observation_id"] for item in peer["batch"]["members"]]
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                f"select count(*) from room_observations where observation_id in "
                f"({','.join('?' for _ in member_ids)}) and status = 'completed'",
                member_ids,
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "select count(*) from room_observation_attempts where batch_id = ?",
                (peer["batch"]["batch_id"],),
            ).fetchone()[0]
            == 1
        )
    assert completed["cursor"]["last_acknowledged_seq"] == peer["batch"]["cutoff_seq"]


def test_batch_cancel_retry_canonicalizes_member_and_reuses_immutable_membership(tmp_path):
    path, conversation_id, members = _room(tmp_path)
    kernel = RoomKernelStore(path)
    claims = _root_claims(kernel, conversation_id, members)
    for index, (participant, claim) in enumerate(zip(members, claims, strict=True)):
        _complete(
            kernel,
            conversation_id,
            participant,
            claim,
            f"root-{index}",
            "respond",
            {"content": str(index)},
        )
    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="peer",
    )
    assert peer is not None and peer["batch"]["member_count"] == 2
    secondary_id = peer["batch"]["members"][1]["observation"]["observation_id"]
    primary_id = peer["observation"]["observation_id"]
    controls = RoomObservationControlStore(path)
    requested = controls.request_cancel(
        observation_id=secondary_id,
        client_action_id="cancel-batch",
        operator_identity="operator:local",
        expected_state="active",
        expected_attempt_count=1,
        expected_control_seq=0,
    )
    pending_cancels = controls.list_pending_cancels()
    assert len(pending_cancels) == 1
    assert pending_cancels[0]["observation_id"] == primary_id
    cancelled = controls.mark_cancelled(
        observation_id=secondary_id,
        attempt_id=peer["attempt"]["attempt_id"],
        expected_control_seq=requested["projection"]["control_seq"],
    )
    controls.request_retry(
        observation_id=secondary_id,
        client_action_id="retry-batch",
        operator_identity="operator:local",
        expected_state="cancelled",
        expected_attempt_count=1,
        expected_control_seq=cancelled["control_seq"],
    )
    rows = [kernel.get_observation(item) for item in (primary_id, secondary_id)]
    assert {(row["status"], row["control_state"], row["manual_retry_budget"]) for row in rows} == {
        ("pending", "active", 1)
    }
    retried = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="peer-retry",
    )
    assert retried is not None
    assert retried["batch"]["batch_id"] == peer["batch"]["batch_id"]
    assert retried["batch"]["digest"] == peer["batch"]["digest"]
    assert retried["attempt"]["attempt_number"] == 2
    with pytest.raises(ValueError, match="room_observation_lease_lost"):
        _complete(
            kernel,
            conversation_id,
            members[0],
            peer,
            "late-old-attempt",
            "noop",
        )


def test_peer_observation_budget_is_capped_at_sixteen_per_participant_correlation(tmp_path):
    path, conversation_id, members = _room(tmp_path, count=18)
    kernel = RoomKernelStore(path)
    claims = _root_claims(kernel, conversation_id, members)
    for index, (participant, claim) in enumerate(zip(members, claims, strict=True)):
        _complete(
            kernel,
            conversation_id,
            participant,
            claim,
            f"root-{index}",
            "respond",
            {"content": f"root response {index}"},
        )

    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="bounded-peer-batch",
    )
    assert peer is not None
    assert peer["batch"]["member_count"] == 16
    assert len(peer["batch"]["members"]) == 16
    with sqlite3.connect(path) as conn:
        active_peer_count = conn.execute(
            """select count(*) from room_observations o
               join room_activities a on a.activity_id = o.activity_id
               where o.participant_id = ? and a.correlation_id = ?
                 and a.actor_kind = 'participant' and o.delivery_mode = 'active'""",
            (
                members[0].participant_id,
                peer["batch"]["correlation_id"],
            ),
        ).fetchone()[0]
    assert active_peer_count == 16


def test_runner_boot_fence_canonicalizes_two_member_batch_once(tmp_path):
    path, conversation_id, members = _room(tmp_path)
    kernel = RoomKernelStore(path)
    claims = _root_claims(kernel, conversation_id, members)
    for index, (participant, claim) in enumerate(zip(members, claims, strict=True)):
        _complete(
            kernel,
            conversation_id,
            participant,
            claim,
            f"root-{index}",
            "respond",
            {"content": str(index)},
        )
    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="old-runner",
        runner_generation="generation-a",
        runner_boot_id="boot-a",
    )
    assert peer is not None and peer["batch"]["member_count"] == 2

    controls = RoomObservationControlStore(path)
    fenced = controls.fence_prior_runner_attempts(
        current_runner_generation="generation-a",
        current_runner_boot_id="boot-b",
        base_attempt_limit=3,
    )
    assert fenced["fenced_count"] == 1
    assert fenced["recovered_count"] == 1
    assert fenced["pending_count"] == 1
    member_ids = [item["observation"]["observation_id"] for item in peer["batch"]["members"]]
    observations = [kernel.get_observation(item) for item in member_ids]
    assert {(item["status"], item["control_state"]) for item in observations} == {
        ("pending", "active")
    }
    with sqlite3.connect(path) as conn:
        attempt = conn.execute(
            "select state, recovery_state from room_observation_attempts where attempt_id = ?",
            (peer["attempt"]["attempt_id"],),
        ).fetchone()
    assert attempt == ("expired", "recovered")
    recovered = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="new-runner",
        runner_generation="generation-a",
        runner_boot_id="boot-b",
    )
    assert recovered is not None
    assert recovered["batch"]["batch_id"] == peer["batch"]["batch_id"]
    assert recovered["attempt"]["attempt_number"] == 2


def test_offline_restore_fence_canonicalizes_two_member_batch_once(tmp_path):
    path, conversation_id, members = _room(tmp_path)
    kernel = RoomKernelStore(path)
    claims = _root_claims(kernel, conversation_id, members)
    for index, (participant, claim) in enumerate(zip(members, claims, strict=True)):
        _complete(
            kernel,
            conversation_id,
            participant,
            claim,
            f"root-{index}",
            "respond",
            {"content": str(index)},
        )
    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="pre-restore-runner",
    )
    assert peer is not None and peer["batch"]["member_count"] == 2

    restored = RoomObservationControlStore(path).fence_restored_runtime_generation(
        operation_id="restore-two-member-batch"
    )
    assert restored["affected_observation_count"] == 1
    assert restored["reopened_pending_count"] == 1
    observations = [
        kernel.get_observation(item["observation"]["observation_id"])
        for item in peer["batch"]["members"]
    ]
    assert {(item["status"], item["lease_token"]) for item in observations} == {("pending", None)}


def test_interleaved_human_root_holds_cursor_behind_later_batch_member(tmp_path):
    path, conversation_id, members = _room(tmp_path)
    kernel = RoomKernelStore(path)
    turn_one_claims = _root_claims(kernel, conversation_id, members)
    _complete(
        kernel,
        conversation_id,
        members[0],
        turn_one_claims[0],
        "turn-one-a",
        "respond",
        {"content": "A turn one"},
    )
    _complete(
        kernel,
        conversation_id,
        members[1],
        turn_one_claims[1],
        "turn-one-b",
        "respond",
        {"content": "B turn one"},
    )
    turn_two = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="second human turn",
        client_request_id="human-turn-two",
    )
    assert turn_two["activity"]["seq"] == 4
    _complete(
        kernel,
        conversation_id,
        members[2],
        turn_one_claims[2],
        "turn-one-c",
        "respond",
        {"content": "C turn one after turn two arrived"},
    )

    peer = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="interleaved-peer",
    )
    assert peer is not None
    assert [item["activity"]["seq"] for item in peer["batch"]["members"]] == [3, 5]
    peer_result = _complete(
        kernel,
        conversation_id,
        members[0],
        peer,
        "turn-one-peer-batch",
        "respond",
        {"content": "one bounded peer synthesis"},
    )
    assert peer_result["cursor"]["last_acknowledged_seq"] == 3
    assert peer_result["downstream_observations"] == []

    second_root = kernel.claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=members[0].participant_id,
        lease_owner="turn-two-root",
    )
    assert second_root is not None
    assert second_root["batch"]["phase"] == "root"
    assert second_root["activity"]["seq"] == 4
    second_result = _complete(
        kernel,
        conversation_id,
        members[0],
        second_root,
        "turn-two-a",
        "noop",
    )
    assert second_result["cursor"]["last_acknowledged_seq"] == 5
    assert (
        kernel.claim_next_observation_batch(
            conversation_id=conversation_id,
            participant_id=members[0].participant_id,
            lease_owner="no-third-wave",
        )
        is None
    )
    with sqlite3.connect(path) as conn:
        peer_output_id = peer_result["produced_activity"]["activity_id"]
        assert (
            conn.execute(
                "select count(*) from room_observations where activity_id = ?",
                (peer_output_id,),
            ).fetchone()[0]
            == 0
        )
