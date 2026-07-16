from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_codex_transport import CodexRoomObservationTransport
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog, SkillCatalogDriftError


class _CaptureTransport:
    def __init__(self) -> None:
        self.deliveries: list[RoomObservationDelivery] = []

    async def deliver(self, delivery: RoomObservationDelivery, *, timeout_s: float):
        self.deliveries.append(delivery)
        return RoomTransportResult("finished")


class _GodLayer:
    def __init__(self, record: GodSessionRecord) -> None:
        self.record = record
        self.ensure_calls: list[dict[str, object]] = []
        self.send_calls: list[dict[str, object]] = []
        self.abort_calls: list[str] = []

    async def ensure_conversation_session(self, **kwargs):
        self.ensure_calls.append(kwargs)
        return self.record

    def require_live_provider_session_binding(self, **kwargs):
        return self.record

    async def send_message(self, god_session_id, message_type, prompt, context, request_id=None):
        self.send_calls.append(
            {
                "god_session_id": god_session_id,
                "message_type": message_type,
                "prompt": prompt,
                "context": context,
                "request_id": request_id,
            }
        )

    async def receive_message(self, god_session_id):
        return StdoutMessage(
            type="result",
            request_id=str(self.send_calls[-1]["request_id"]),
            runtime="codex-app-server",
            status="success",
        )

    async def abort_session(self, god_session_id):
        self.abort_calls.append(god_session_id)


def _participant(db: Path, conversation_id: str, role: str) -> Participant:
    return ParticipantStore(db).add(
        conversation_id=conversation_id,
        role=role,
        display_name=role.title(),
        cli_kind="codex",
        model="gpt-5",
    )


def _bound_delivery(
    tmp_path: Path,
    *,
    role: str = "review",
    content: str = "请审计并验证风险",
) -> tuple[
    Path,
    RoomObservationDelivery,
    RoomAttemptSkillDecisionStore,
    RoomObservationControlStore,
    GodSessionRecord,
    datetime,
]:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("skills").id
    participant = _participant(db, conversation_id, role)
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    record = registry.create(
        participant.role,
        participant.display_name,
        "codex",
        f"@{role}",
        f"inbox-{role}",
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    record = registry.update_provider_binding(
        record.god_session_id,
        provider_session_id="thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    now = datetime.now(UTC)
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content=content,
        client_request_id="human-1",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="host",
        lease_ttl_s=240,
        now=now,
    )
    assert claim is not None
    catalog = SkillCatalog.load_bundled()
    decisions = RoomAttemptSkillDecisionStore(db)
    decision = decisions.bind_for_attempt(
        attempt_id=claim["attempt"]["attempt_id"], catalog=catalog, now=now
    )
    activation = catalog.materialize(decision.selection)
    controls = RoomObservationControlStore(db)
    controls.bind_delivery(
        observation_id=claim["observation"]["observation_id"],
        attempt_id=claim["attempt"]["attempt_id"],
        lease_token=claim["observation"]["lease_token"],
        delivery_task_id="delivery-1",
        provider_session_generation=claim["attempt"]["attempt_id"],
        now=now,
    )
    source = claim["activity"]
    context = {
        "activity_id": source["activity_id"],
        "seq": source["seq"],
        "payload_preview": json.dumps(source["payload"], ensure_ascii=False),
    }
    return (
        db,
        RoomObservationDelivery(
            conversation_id=conversation_id,
            participant=participant,
            observation=claim["observation"],
            source_activity=context,
            recent_activities=(context,),
            active_participants=(
                {
                    "participant_id": participant.participant_id,
                    "display_name": participant.display_name,
                    "role": participant.role,
                },
            ),
            transport_request_id="delivery-1",
            outcome_client_request_id="outcome-1",
            attempt_id=claim["attempt"]["attempt_id"],
            skill_activation=activation,
        ),
        decisions,
        controls,
        record,
        now,
    )


def test_host_selects_participant_local_skill_before_transport(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("room").id
    _participant(db, conversation_id, "architect")
    _participant(db, conversation_id, "review")
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="请规划实现方案，并审计验证风险",
        client_request_id="human-1",
    )
    transport = _CaptureTransport()

    result = asyncio.run(
        RoomParticipantHost(
            db,
            transport,
            policy=RoomHostPolicy(participant_cooldown_s=0),
        ).pump_once(conversation_id=conversation_id)
    )

    assert len(result.deliveries) == len(transport.deliveries) == 2
    assert {
        item.participant.role: item.skill_activation.skill_id
        for item in transport.deliveries
        if item.skill_activation is not None
    } == {
        "architect": "implementation-planning",
        "review": "evidence-review",
    }
    store = RoomAttemptSkillDecisionStore(db)
    assert all(store.get(item.attempt_id or "") is not None for item in transport.deliveries)


def test_transport_asserts_ledger_before_provider_and_records_exact_envelope(
    tmp_path: Path,
) -> None:
    db, delivery, decisions, controls, record, now = _bound_delivery(tmp_path)
    assert delivery.skill_activation is not None
    layer = _GodLayer(record)

    invalid_deliveries = (
        replace(delivery, skill_activation=None),
        replace(
            delivery,
            skill_activation=replace(
                delivery.skill_activation,
                instructions=delivery.skill_activation.instructions + "tampered",
            ),
        ),
    )
    for invalid in invalid_deliveries:
        result = asyncio.run(
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
                skill_decision_store=decisions,
                clock=lambda: now,
            ).deliver(invalid, timeout_s=3)
        )
        assert result.reason == "room_skill_activation_mismatch"
    assert layer.ensure_calls == [] and layer.send_calls == []

    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,
            skill_decision_store=decisions,
            clock=lambda: now,
        ).deliver(delivery, timeout_s=3)
    )
    assert result.status == "finished"
    sent_context = json.loads(str(layer.send_calls[0]["context"]))
    activation = delivery.skill_activation
    assert sent_context["skills"] == {
        "current_activation": {
            "decision": "selected",
            "skill_id": activation.skill_id,
            "version": activation.version,
            "content_sha256": activation.content_sha256,
            "instructions_sha256": activation.instructions_sha256,
            "selection_reason": activation.selection_reason,
            "matched_terms": list(activation.matched_terms),
            "instructions": activation.instructions,
        },
        "scope": "current_observation_only",
        "supersedes_prior_activation": True,
        "authority": "guidance_only",
        "may_change_observation_eligibility": False,
        "may_author_room_speech": False,
    }
    receipt = decisions.get(delivery.attempt_id or "")
    assert receipt is not None and receipt.context_submitted_at is not None
    expected_digest = hashlib.sha256(str(layer.send_calls[0]["context"]).encode()).hexdigest()
    assert receipt.context_payload_sha256 == f"sha256:{expected_digest}"

    RoomApplicationService(db, tmp_path / "god_sessions.json").submit_participant_outcome(
        conversation_id=delivery.conversation_id,
        participant_id=delivery.participant.participant_id,
        god_session_id=record.god_session_id,
        observation_id=delivery.observation["observation_id"],
        lease_token=delivery.observation["lease_token"],
        client_request_id=delivery.outcome_client_request_id,
        outcome_type="noop",
        outcome_payload={},
    )
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=delivery.conversation_id,
        human_id="human",
        content="hello there",
        client_request_id="human-2",
    )
    second_claim = kernel.claim_next_observation(
        conversation_id=delivery.conversation_id,
        participant_id=delivery.participant.participant_id,
        lease_owner="host",
        lease_ttl_s=240,
        now=now,
    )
    assert second_claim is not None
    catalog = SkillCatalog.load_bundled()
    second_decision = decisions.bind_for_attempt(
        attempt_id=second_claim["attempt"]["attempt_id"],
        catalog=catalog,
        now=now,
    )
    second_activation = catalog.materialize(second_decision.selection)
    assert second_activation is None
    controls.bind_delivery(
        observation_id=second_claim["observation"]["observation_id"],
        attempt_id=second_claim["attempt"]["attempt_id"],
        lease_token=second_claim["observation"]["lease_token"],
        delivery_task_id="delivery-2",
        provider_session_generation=second_claim["attempt"]["attempt_id"],
        now=now,
    )
    second_source = second_claim["activity"]
    second_context = {
        "activity_id": second_source["activity_id"],
        "seq": second_source["seq"],
        "payload_preview": json.dumps(second_source["payload"], ensure_ascii=False),
    }
    second_delivery = replace(
        delivery,
        observation=second_claim["observation"],
        source_activity=second_context,
        recent_activities=(second_context,),
        transport_request_id="delivery-2",
        outcome_client_request_id="outcome-2",
        attempt_id=second_claim["attempt"]["attempt_id"],
        skill_activation=None,
    )
    second_result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,
            skill_decision_store=decisions,
            clock=lambda: now,
        ).deliver(second_delivery, timeout_s=3)
    )
    assert second_result.status == "finished"
    contexts = [json.loads(str(call["context"])) for call in layer.send_calls]
    assert [item["skills"]["current_activation"]["decision"] for item in contexts] == [
        "selected",
        "none",
    ]
    assert contexts[0]["god_session_id"] == contexts[1]["god_session_id"]
    assert decisions.get(second_delivery.attempt_id or "").context_submitted_at is not None  # type: ignore[union-attr]


def test_none_decision_rejects_activation_before_provider(tmp_path: Path) -> None:
    selected_root = tmp_path / "selected"
    _, selected, _, _, _, _ = _bound_delivery(selected_root)
    none_root = tmp_path / "none"
    _, none, decisions, controls, record, now = _bound_delivery(
        none_root,
        content="hello there",
    )
    assert none.skill_activation is None and selected.skill_activation is not None
    layer = _GodLayer(record)

    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=none_root,
            control_store=controls,
            skill_decision_store=decisions,
            clock=lambda: now,
        ).deliver(replace(none, skill_activation=selected.skill_activation), timeout_s=3)
    )

    assert result.reason == "room_skill_activation_mismatch"
    assert layer.ensure_calls == [] and layer.send_calls == []


def test_context_limit_bounds_provider_turn_and_drift_stops_new_claims(tmp_path: Path) -> None:
    bound_root = tmp_path / "bounded"
    _, delivery, decisions, controls, record, now = _bound_delivery(bound_root)
    layer = _GodLayer(record)
    oversized = replace(
        delivery,
        recent_activities=({"payload_preview": "审" * 30_000},),
    )
    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=bound_root,
            control_store=controls,
            skill_decision_store=decisions,
            clock=lambda: now,
        ).deliver(oversized, timeout_s=3)
    )
    assert result.status == "finished"
    assert len(layer.send_calls) == 1
    submitted = str(layer.send_calls[0]["context"])
    assert len(submitted.encode("utf-8")) <= 64 * 1024
    envelope = json.loads(submitted)
    assert envelope["room_context"]["coverage"]["bounded"] is True
    assert envelope["room_context"]["human_root"]
    assert envelope["room_context"]["primary_source"]

    class DriftingCatalog:
        def __init__(self) -> None:
            self.real = SkillCatalog.load_bundled()

        def select(self, **kwargs):
            return self.real.select(**kwargs)

        def materialize(self, decision):
            raise SkillCatalogDriftError("changed")

    drift_root = tmp_path / "drift"
    db = drift_root / "chat.db"
    first_room = RoomTestStore(db).create_conversation("first").id
    second_room = RoomTestStore(db).create_conversation("second").id
    for room_id in (first_room, second_room):
        _participant(db, room_id, "review")
        RoomKernelStore(db).post_human_activity(
            conversation_id=room_id,
            human_id="human",
            content="审计风险",
            client_request_id=f"human-{room_id}",
        )
    host = RoomParticipantHost(
        db,
        _CaptureTransport(),
        skill_catalog=DriftingCatalog(),  # type: ignore[arg-type]
        policy=RoomHostPolicy(participant_cooldown_s=0),
    )
    first = asyncio.run(host.pump_once(conversation_id=first_room))
    assert first.deliveries[0].reason == "room_skill_catalog_drift"
    assert host.list_claimable_conversation_ids() == []
    second_observation = RoomKernelStore(db).list_observations(second_room)[0]
    assert second_observation["status"] == "pending"
    assert second_observation["attempt_count"] == 0


def test_non_drift_setup_failure_releases_only_that_candidate_and_peer_runs(
    tmp_path: Path,
) -> None:
    class SetupError(RuntimeError):
        code = "room_skill_activation_mismatch"

    class OneRoleFailsCatalog:
        def __init__(self) -> None:
            self.real = SkillCatalog.load_bundled()

        def select(self, **kwargs):
            return self.real.select(**kwargs)

        def materialize(self, decision):
            if decision.skill_id == "implementation-planning":
                raise SetupError("bad activation")
            return self.real.materialize(decision)

    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("isolation").id
    _participant(db, conversation_id, "architect")
    _participant(db, conversation_id, "review")
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="请规划实现方案并审计验证风险",
        client_request_id="human-1",
    )
    transport = _CaptureTransport()
    result = asyncio.run(
        RoomParticipantHost(
            db,
            transport,
            skill_catalog=OneRoleFailsCatalog(),  # type: ignore[arg-type]
            policy=RoomHostPolicy(participant_cooldown_s=0),
        ).pump_once(conversation_id=conversation_id)
    )

    assert [item.participant.role for item in transport.deliveries] == ["review"]
    delivered_participant_id = transport.deliveries[0].participant.participant_id
    failed = next(
        item for item in result.deliveries if item.participant_id != delivered_participant_id
    )
    assert failed.state == "failed"
    assert failed.reason == "room_skill_activation_mismatch"
    architect = next(
        item
        for item in RoomKernelStore(db).list_observations(conversation_id)
        if item["participant_id"] == failed.participant_id
    )
    assert architect["status"] == "pending"
    assert architect["lease_token"] is None
