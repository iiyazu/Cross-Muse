from __future__ import annotations

import asyncio
import sqlite3

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore


def test_chat_api_room_closes_through_independent_agent_outcomes_and_projection(
    tmp_path,
) -> None:
    runtime_calls = []

    def runtime_stub(base_dir, execution_root):
        runtime_calls.append((base_dir, execution_root))
        return {"state": "test-runtime-stub"}

    client = TestClient(create_app(tmp_path, workroom_runtime_starter=runtime_stub))
    created = client.post(
        "/api/chat/conversations",
        json={
            "title": "Natural room product closure",
            "initial_participants": [
                {
                    "role": "architect",
                    "display_name": "Architect",
                    "provider_id": "codex",
                    "profile_id": "god",
                    "cli_kind": "codex",
                    "model": "gpt-5.4",
                },
                {
                    "role": "review",
                    "display_name": "Reviewer",
                    "provider_id": "codex",
                    "profile_id": "review",
                    "cli_kind": "codex",
                    "model": "gpt-5.4",
                },
            ],
        },
    )
    assert created.status_code == 201
    conversation = created.json()
    conversation_id = conversation["id"]
    participants = {
        participant["role"]: participant for participant in conversation["participants"]
    }
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    participant_records = {
        item.participant_id: item
        for item in ParticipantStore(tmp_path / "chat.db").list_by_conversation(conversation_id)
    }
    sessions = {}
    for participant in participants.values():
        record = participant_records[participant["participant_id"]]
        session = registry.create(
            role=record.role,
            agent_name=record.display_name,
            runtime="codex",
            session_address=f"@{record.role}-{record.participant_id}",
            session_inbox_id=f"room-{record.participant_id}",
            conversation_id=conversation_id,
            participant_id=record.participant_id,
            model=record.model,
        )
        sessions[record.participant_id] = session.god_session_id
    before_events = client.get(
        f"/api/chat/conversations/{conversation_id}/events?after_seq=0&limit=100"
    ).json()

    posted = client.post(
        f"/api/chat/threads/{conversation_id}/messages",
        json={
            "message": "请各自判断是否需要回应，不要由中心路由替你们决定。",
            "client_request_id": "room-product-closure-human",
        },
    )

    assert posted.status_code == 201
    assert posted.json()["runtime"]["state"] == "test-runtime-stub"
    assert len(runtime_calls) == 1
    kernel = RoomKernelStore(tmp_path / "chat.db")
    root_activity = kernel.list_activities(conversation_id)[0]
    root_observations = [
        observation
        for observation in kernel.list_observations(conversation_id)
        if observation["activity_id"] == root_activity["activity_id"]
    ]
    assert root_activity["materialized_message_id"] == posted.json()["message"]["id"]
    assert {item["participant_id"] for item in root_observations} == {
        participant["participant_id"] for participant in participants.values()
    }
    assert {item["status"] for item in root_observations} == {"pending"}

    class OutcomeTransport:
        def __init__(self) -> None:
            self.outcomes: dict[str, str] = {}

        async def deliver(
            self,
            delivery: RoomObservationDelivery,
            *,
            timeout_s: float,
        ) -> RoomTransportResult:
            participant = delivery.participant
            outcome_type = "respond" if participant.role == "architect" else "noop"
            payload = (
                {"content": "我独立判断后认为需要回应：这个房间已经走通。"}
                if outcome_type == "respond"
                else {}
            )
            RoomApplicationService(
                tmp_path / "chat.db",
                tmp_path / "god_sessions.json",
            ).submit_participant_outcome(
                conversation_id=delivery.conversation_id,
                participant_id=participant.participant_id,
                god_session_id=sessions[participant.participant_id],
                observation_id=delivery.observation["observation_id"],
                lease_token=delivery.observation["lease_token"],
                client_request_id=delivery.outcome_client_request_id,
                outcome_type=outcome_type,
                outcome_payload=payload,
            )
            self.outcomes[participant.participant_id] = outcome_type
            return RoomTransportResult("finished")

    transport = OutcomeTransport()

    async def run_room_to_idle():
        host = RoomParticipantHost(
            tmp_path / "chat.db",
            transport,
            policy=RoomHostPolicy(
                max_batch_size=2,
                participant_cooldown_s=0,
            ),
        )
        batches = []
        for _ in range(4):
            batch = await host.pump_once(conversation_id=conversation_id)
            batches.append(batch)
            if not batch.deliveries:
                break
        await host.shutdown()
        return batches

    host_results = asyncio.run(run_room_to_idle())

    assert transport.outcomes == {
        participants["architect"]["participant_id"]: "respond",
        participants["review"]["participant_id"]: "noop",
    }
    deliveries = [item for batch in host_results for item in batch.deliveries]
    assert len(deliveries) == 3
    assert {item.state for item in deliveries} == {"completed"}
    assert {item.outcome_type for item in deliveries} == {"respond", "noop"}
    assert {item["status"] for item in kernel.list_observations(conversation_id)} == {"completed"}

    projected_response = client.get(f"/api/chat/conversations/{conversation_id}/room-projection")
    assert projected_response.status_code == 200
    projection = projected_response.json()
    assert projection["schema_version"] == "room_chat_projection/v3"
    replies = [
        item
        for item in projection["timeline_items"]
        if item.get("proof_boundary") == "identity_bound_room_outcome"
    ]
    assert len(replies) == 1
    reply = replies[0]
    architect = participants["architect"]
    assert reply["content"] == "我独立判断后认为需要回应：这个房间已经走通。"
    assert reply["actor"]["participant_id"] == architect["participant_id"]
    assert reply["actor"]["role"] == "architect"
    assert reply["actor"]["display_name"] == architect["display_name"]
    assert participants["review"]["participant_id"] not in {
        message["actor"]["participant_id"] for message in replies
    }

    assert projection["status"] == "settled"
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        tables = {
            row[0] for row in conn.execute("select name from sqlite_schema where type = 'table'")
        }
    assert not {"groupchat_worklist", "chat_inbox_items"} & tables
    after_events = client.get(
        f"/api/chat/conversations/{conversation_id}/events"
        f"?after_seq={before_events['latest_seq']}&limit=100"
    ).json()
    assert after_events["latest_seq"] > before_events["latest_seq"]
    assert {
        event["payload"]["change"]
        for event in after_events["events"]
        if event["payload"].get("kind") == "room_projection_changed"
    } == {
        "human.posted",
        "observation.claimed",
        "observation.completed",
    }
    telemetry = client.get(f"/api/chat/conversations/{conversation_id}/live-telemetry?after_seq=0")
    assert telemetry.status_code == 404
