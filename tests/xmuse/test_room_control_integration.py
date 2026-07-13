from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.chat_api import create_app
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomHostPolicy,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

NOW = datetime(2026, 1, 1, tzinfo=UTC)
OPERATOR_HEADERS = {"X-XMuse-Operator-Token": "operator-secret"}


def _room(tmp_path, *, participant_count: int = 1):
    path = tmp_path / "chat.db"
    conversation = RoomTestStore(path).create_conversation("controlled room")
    participants = ParticipantStore(path)
    agents = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(participant_count)
    ]
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="alice",
        content="review independently",
        client_request_id="human-1",
    )
    return path, conversation.id, agents, kernel


def _claim(kernel, conversation_id, participant_id, *, owner="host-1", now=NOW):
    claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant_id,
        lease_owner=owner,
        lease_ttl_s=30,
        now=now,
    )
    assert claim is not None
    return claim


def _bind_skill_decision(path, attempt_id: str, *, now=NOW) -> None:
    RoomAttemptSkillDecisionStore(path).bind_for_attempt(
        attempt_id=attempt_id,
        catalog=SkillCatalog.load_bundled(),
        now=now,
    )


def _command_payload(projection, action, client_action_id):
    descriptor = projection["actions"][action]
    return {
        "client_action_id": client_action_id,
        "expected_state": descriptor["expected_state"],
        "expected_attempt_count": descriptor["expected_attempt_count"],
        "expected_control_seq": descriptor["expected_control_seq"],
    }


def test_operator_api_enforces_auth_guards_idempotency_and_pending_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    path, conversation_id, agents, kernel = _room(tmp_path)
    claim = _claim(kernel, conversation_id, agents[0].participant_id)
    observation_id = claim["observation"]["observation_id"]
    controls = RoomObservationControlStore(path)
    initial = controls.projection(observation_id)
    url = f"/api/chat/operator/room-observations/{observation_id}/cancel"
    client = TestClient(create_app(tmp_path, workroom_runtime_starter=lambda *_: {"state": "stub"}))

    body = _command_payload(initial, "cancel", "cancel-valid")
    assert client.post(url, json=body).status_code == 401
    guard_cases = (
        (
            {**body, "client_action_id": "bad-state", "expected_state": "cancelled"},
            "room_control_state_conflict",
        ),
        (
            {**body, "client_action_id": "bad-attempt", "expected_attempt_count": 2},
            "room_control_attempt_conflict",
        ),
        (
            {**body, "client_action_id": "bad-seq", "expected_control_seq": 1},
            "room_control_seq_conflict",
        ),
    )
    for invalid, code in guard_cases:
        response = client.post(url, json=invalid, headers=OPERATOR_HEADERS)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == code
    repeated_rejection = client.post(url, json=guard_cases[0][0], headers=OPERATOR_HEADERS)
    assert repeated_rejection.status_code == 409
    assert repeated_rejection.json()["detail"]["code"] == guard_cases[0][1]

    first = client.post(url, json=body, headers=OPERATOR_HEADERS)
    replay = client.post(url, json=body, headers=OPERATOR_HEADERS)
    assert first.status_code == replay.status_code == 200
    assert first.json()["event_cursor"] == replay.json()["event_cursor"]
    assert first.json()["room_observation_control"]["control_state"] == "cancel_requested"
    browser_payload = json.dumps(first.json())
    assert claim["attempt"]["attempt_id"] not in browser_payload
    assert "lease_owner" not in browser_payload
    assert "delivery_generation" not in browser_payload

    conflict = client.post(
        url,
        json={
            **body,
            "expected_state": "cancel_requested",
            "expected_control_seq": 1,
        },
        headers=OPERATOR_HEADERS,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "room_control_idempotency_conflict"

    pending = controls.mark_cancel_pending(
        observation_id=observation_id,
        attempt_id=claim["attempt"]["attempt_id"],
        expected_control_seq=1,
        now=NOW + timedelta(seconds=1),
    )
    retry_url = f"/api/chat/operator/room-observations/{observation_id}/retry"
    retry = client.post(
        retry_url,
        json=_command_payload(pending, "retry", "retry-too-early"),
        headers=OPERATOR_HEADERS,
    )
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "room_observation_not_retryable"
    missing = client.post(
        "/api/chat/operator/room-observations/missing/cancel",
        json=body,
        headers=OPERATOR_HEADERS,
    )
    assert missing.status_code == 404

    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "select count(*) from room_observation_controls where observation_id = ?",
                (observation_id,),
            ).fetchone()[0]
            == 5
        )
        assert (
            conn.execute(
                "select count(*) from room_observation_controls where observation_id = ? "
                "and status = 'rejected'",
                (observation_id,),
            ).fetchone()[0]
            == 4
        )
        assert (
            conn.execute(
                "select count(*) from chat_frontend_events where conversation_id = ? "
                "and json_extract(payload_json, '$.kind') = 'room_observation_control_changed'",
                (conversation_id,),
            ).fetchone()[0]
            == 2
        )


def test_completion_and_cancel_race_has_one_authoritative_winner(tmp_path, monkeypatch):
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "operator-secret")
    path, conversation_id, agents, kernel = _room(tmp_path)
    participant = agents[0]
    claim = _claim(kernel, conversation_id, participant.participant_id)
    observation = claim["observation"]
    controls = RoomObservationControlStore(path)
    projection = controls.projection(observation["observation_id"])
    client = TestClient(create_app(tmp_path, workroom_runtime_starter=lambda *_: {"state": "stub"}))
    barrier = Barrier(2)

    def cancel():
        barrier.wait()
        return client.post(
            projection["actions"]["cancel"].get("href")
            or f"/api/chat/operator/room-observations/{observation['observation_id']}/cancel",
            json=_command_payload(projection, "cancel", "cancel-race"),
            headers=OPERATOR_HEADERS,
        )

    def complete():
        barrier.wait()
        try:
            kernel.complete_observation(
                conversation_id=conversation_id,
                participant_id=participant.participant_id,
                caller_identity=f"god:session:{participant.participant_id}",
                observation_id=observation["observation_id"],
                lease_token=observation["lease_token"],
                client_request_id="outcome-race",
                outcome_type="noop",
                now=NOW + timedelta(seconds=1),
            )
        except ValueError as exc:
            return str(exc)
        return "completed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel_future = pool.submit(cancel)
        complete_future = pool.submit(complete)
        cancel_response = cancel_future.result(timeout=10)
        completion = complete_future.result(timeout=10)

    if completion == "completed":
        assert cancel_response.status_code == 409
        assert cancel_response.json()["detail"]["code"] == "room_observation_already_completed"
        assert kernel.get_observation(observation["observation_id"])["status"] == "completed"
    else:
        assert completion == "room_observation_lease_lost"
        assert cancel_response.status_code == 200
        final = controls.projection(observation["observation_id"])
        assert final["control_state"] == "cancel_requested"
        assert kernel.get_observation(observation["observation_id"])["lease_token"] is None


def test_host_cancel_targets_one_agent_and_fences_only_its_delivery(tmp_path):
    async def run():
        path, conversation_id, agents, kernel = _room(tmp_path, participant_count=2)
        started = asyncio.Event()
        release_other = asyncio.Event()
        cancelled = asyncio.Event()

        class BlockingTransport:
            def __init__(self):
                self.deliveries = {}
                self.cancelled_participants = set()

            async def deliver(self, delivery, *, timeout_s):
                participant_id = delivery.participant.participant_id
                self.deliveries[participant_id] = delivery
                if len(self.deliveries) == 2:
                    started.set()
                try:
                    await release_other.wait()
                except asyncio.CancelledError:
                    self.cancelled_participants.add(participant_id)
                    cancelled.set()
                    raise
                return RoomTransportResult("finished")

        transport = BlockingTransport()
        host = RoomParticipantHost(
            path,
            transport,
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
                participant_cooldown_s=0,
                max_batch_size=2,
            ),
            clock=lambda: NOW,
        )
        pump = asyncio.create_task(host.pump_once(conversation_id=conversation_id))
        await asyncio.wait_for(started.wait(), timeout=1)
        target, other = agents
        target_delivery = transport.deliveries[target.participant_id]
        controls = RoomObservationControlStore(path)
        controls.request_cancel(
            observation_id=target_delivery.observation["observation_id"],
            client_action_id="cancel-one",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(milliseconds=1),
        )
        await host.reconcile_controls()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        assert transport.cancelled_participants == {target.participant_id}
        release_other.set()
        result = await asyncio.wait_for(pump, timeout=2)

        outcomes = {item.participant_id: item for item in result.deliveries}
        assert outcomes[target.participant_id].state == "cancelled"
        assert outcomes[other.participant_id].state == "incomplete"
        target_final = controls.projection(target_delivery.observation["observation_id"])
        other_delivery = transport.deliveries[other.participant_id]
        other_final = controls.projection(other_delivery.observation["observation_id"])
        assert target_final["control_state"] == "cancelled"
        assert other_final["control_state"] == "active"
        with pytest.raises(ValueError, match="room_observation_lease_lost"):
            kernel.complete_observation(
                conversation_id=conversation_id,
                participant_id=target.participant_id,
                caller_identity=f"god:session:{target.participant_id}",
                observation_id=target_delivery.observation["observation_id"],
                lease_token=target_delivery.observation["lease_token"],
                client_request_id="late-after-cancel",
                outcome_type="noop",
                now=NOW + timedelta(seconds=1),
            )

    asyncio.run(run())


def test_live_host_cancel_requires_durable_provider_cleanup_proof(tmp_path):
    async def run():
        path, conversation_id, agents, _kernel = _room(tmp_path)
        controls = RoomObservationControlStore(path)
        started = asyncio.Event()

        class ProofTransport:
            cleanup_ok = False

            async def deliver(self, delivery, *, timeout_s):
                controls.mark_provider_ensure_started(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    now=NOW,
                )
                controls.bind_provider_session(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    god_session_id="god-proof",
                    provider_session_id="thread-proof",
                    now=NOW,
                )
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    controls.mark_provider_cleanup(
                        observation_id=delivery.observation["observation_id"],
                        attempt_id=delivery.attempt_id,
                        delivery_generation=delivery.attempt_id,
                        succeeded=False,
                        reason_code="abort_failed",
                        now=NOW + timedelta(seconds=1),
                    )
                    raise

            async def reconcile_cancel(self, **_kwargs):
                return RoomCancelReconcileResult(
                    "settled" if self.cleanup_ok else "pending",
                    "cleanup_confirmed" if self.cleanup_ok else "abort_failed",
                )

        transport = ProofTransport()
        host = RoomParticipantHost(
            path,
            transport,
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )
        pump = asyncio.create_task(host.pump_once(conversation_id=conversation_id))
        await asyncio.wait_for(started.wait(), timeout=1)
        observation = controls.projection(
            RoomKernelStore(path).list_observations(conversation_id)[0]["observation_id"]
        )
        controls.request_cancel(
            observation_id=observation["observation_id"],
            client_action_id="live-proof-cancel",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        await host.reconcile_controls()
        outcome = await asyncio.wait_for(pump, timeout=2)

        assert outcome.deliveries[0].state == "cancel_pending"
        assert (
            controls.projection(observation["observation_id"])["control_state"] == "cancel_pending"
        )
        transport.cleanup_ok = True
        await host.reconcile_controls()
        assert controls.projection(observation["observation_id"])["control_state"] == "cancelled"
        assert agents[0].participant_id == observation["participant_id"]

    asyncio.run(run())


def test_retained_transport_callback_cannot_claim_cleanup_success(tmp_path):
    async def run():
        path, conversation_id, _agents, _kernel = _room(tmp_path)
        controls = RoomObservationControlStore(path)
        started = asyncio.Event()
        release = asyncio.Event()

        class RetainedTransport:
            cleanup_ok = False

            async def deliver(self, delivery, *, timeout_s):
                controls.mark_provider_ensure_started(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    now=NOW,
                )
                controls.bind_provider_session(
                    observation_id=delivery.observation["observation_id"],
                    attempt_id=delivery.attempt_id,
                    delivery_generation=delivery.attempt_id,
                    god_session_id="god-retained",
                    provider_session_id="thread-retained",
                    now=NOW,
                )
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    controls.mark_provider_cleanup(
                        observation_id=delivery.observation["observation_id"],
                        attempt_id=delivery.attempt_id,
                        delivery_generation=delivery.attempt_id,
                        succeeded=False,
                        reason_code="retained_abort_unconfirmed",
                        now=NOW + timedelta(seconds=1),
                    )
                    await release.wait()
                return RoomTransportResult("finished")

            async def reconcile_cancel(self, **_kwargs):
                return RoomCancelReconcileResult(
                    "settled" if self.cleanup_ok else "pending",
                    "retained_cleanup_confirmed"
                    if self.cleanup_ok
                    else "retained_abort_unconfirmed",
                )

        transport = RetainedTransport()
        host = RoomParticipantHost(
            path,
            transport,
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.01,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )
        pump = asyncio.create_task(host.pump_once(conversation_id=conversation_id))
        await asyncio.wait_for(started.wait(), timeout=1)
        observation_id = RoomKernelStore(path).list_observations(conversation_id)[0][
            "observation_id"
        ]
        controls.request_cancel(
            observation_id=observation_id,
            client_action_id="retained-cancel",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        await host.reconcile_controls()
        outcome = await asyncio.wait_for(pump, timeout=2)
        assert outcome.deliveries[0].state == "cancel_pending"
        assert host._retained_tasks

        release.set()
        while host._retained_tasks:
            await asyncio.sleep(0)
        assert controls.projection(observation_id)["control_state"] == "cancel_pending"

        transport.cleanup_ok = True
        await host.reconcile_controls()
        assert controls.projection(observation_id)["control_state"] == "cancelled"

    asyncio.run(run())


def test_restart_reconciles_pending_cancel_and_old_generation_cannot_hurt_retry(tmp_path):
    async def run():
        path, conversation_id, agents, kernel = _room(tmp_path)
        participant = agents[0]
        first = _claim(kernel, conversation_id, participant.participant_id)
        observation_id = first["observation"]["observation_id"]
        attempt_id = first["attempt"]["attempt_id"]
        controls = RoomObservationControlStore(path)
        _bind_skill_decision(path, attempt_id)
        controls.bind_delivery(
            observation_id=observation_id,
            attempt_id=attempt_id,
            lease_token=first["observation"]["lease_token"],
            delivery_task_id="dead-runner-task",
            provider_session_generation="runner-generation-1",
            now=NOW,
        )
        requested = controls.request_cancel(
            observation_id=observation_id,
            client_action_id="cancel-before-crash",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        pending = controls.mark_cancel_pending(
            observation_id=observation_id,
            attempt_id=attempt_id,
            expected_control_seq=requested["projection"]["control_seq"],
            now=NOW + timedelta(seconds=2),
        )
        with pytest.raises(RoomControlError, match="room_observation_not_retryable"):
            controls.request_retry(
                observation_id=observation_id,
                client_action_id="retry-before-cleanup",
                operator_identity="operator:local",
                expected_state="cancel_pending",
                expected_attempt_count=1,
                expected_control_seq=pending["control_seq"],
                now=NOW + timedelta(seconds=3),
            )

        class UnusedTransport:
            async def deliver(self, delivery, *, timeout_s):
                raise AssertionError("restart reconciliation must not redeliver")

        restarted = RoomParticipantHost(
            path,
            UnusedTransport(),
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=4),
        )
        await restarted.reconcile_controls()
        cancelled = controls.projection(observation_id)
        assert cancelled["control_state"] == "cancelled"
        retried = controls.request_retry(
            observation_id=observation_id,
            client_action_id="retry-after-reconcile",
            operator_identity="operator:local",
            expected_state="cancelled",
            expected_attempt_count=1,
            expected_control_seq=cancelled["control_seq"],
            now=NOW + timedelta(seconds=5),
        )
        second = _claim(
            kernel,
            conversation_id,
            participant.participant_id,
            owner="host-2",
            now=NOW + timedelta(seconds=6),
        )
        assert second["attempt"]["attempt_id"] != attempt_id
        with pytest.raises(RoomControlError, match="room_attempt_generation_lost"):
            controls.mark_cancelled(
                observation_id=observation_id,
                attempt_id=attempt_id,
                expected_control_seq=retried["projection"]["control_seq"],
                now=NOW + timedelta(seconds=7),
            )
        current = controls.projection(observation_id)
        assert current["control_state"] == "active"
        assert current["current_attempt"]["attempt_number"] == second["attempt"]["attempt_number"]

    asyncio.run(run())


def test_host_exhaustion_and_manual_budget_allow_exactly_one_more_attempt(tmp_path):
    async def run():
        path, conversation_id, agents, _kernel = _room(tmp_path)

        class FailedTransport:
            def __init__(self):
                self.count = 0

            async def deliver(self, delivery, *, timeout_s):
                self.count += 1
                return RoomTransportResult("failed", "provider_failed")

        transport = FailedTransport()

        def host(now):
            return RoomParticipantHost(
                path,
                transport,
                policy=RoomHostPolicy(
                    delivery_timeout_s=2,
                    cleanup_grace_s=0.2,
                    lease_ttl_s=3,
                    participant_cooldown_s=0,
                    max_attempts_per_observation=1,
                ),
                clock=lambda: now,
            )

        first = await host(NOW).pump_once(conversation_id=conversation_id)
        observation_id = first.deliveries[0].observation_id
        controls = RoomObservationControlStore(path)
        exhausted = controls.projection(observation_id)
        assert exhausted["control_state"] == "exhausted"
        assert host(NOW + timedelta(seconds=1)).list_claimable_conversation_ids() == []
        retried = controls.request_retry(
            observation_id=observation_id,
            client_action_id="one-manual-attempt",
            operator_identity="operator:local",
            expected_state="exhausted",
            expected_attempt_count=1,
            expected_control_seq=exhausted["control_seq"],
            now=NOW + timedelta(seconds=1),
        )
        assert retried["projection"]["manual_retry_budget"] == 1
        second = await host(NOW + timedelta(seconds=2)).pump_once(conversation_id=conversation_id)
        assert second.deliveries[0].attempt_count == 2
        assert transport.count == 2
        final = controls.projection(observation_id)
        assert final["control_state"] == "exhausted"
        assert final["manual_retry_budget"] == 1
        with sqlite3.connect(path) as conn:
            limits = [
                row[0]
                for row in conn.execute(
                    "select effective_attempt_limit from room_observation_attempts "
                    "where observation_id = ? order by attempt_number",
                    (observation_id,),
                )
            ]
        assert limits == [1, 2]
        assert agents[0].participant_id == final["participant_id"]

    asyncio.run(run())
