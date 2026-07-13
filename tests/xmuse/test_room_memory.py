from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from tests.xmuse.test_room_participant_outcomes import root_and_claims, submit
from xmuse_core.chat.room_api_models import RoomConversationCreate
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_memory_common import RoomMemoryStoreError
from xmuse_core.chat.room_memory_contracts import (
    RoomMemoryContractError,
    normalize_memory_candidates,
)
from xmuse_core.chat.room_memory_delivery_store import RoomMemoryDeliveryStore
from xmuse_core.chat.room_memory_governance_store import RoomMemoryGovernanceStore
from xmuse_core.chat.room_memory_recall_store import RoomMemoryRecallStore
from xmuse_core.chat.room_setup import RoomSetupService

DIGEST = "sha256:" + "1" * 64


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _candidate(kind: str, content: str, activity_id: str) -> dict[str, object]:
    return {
        "kind": kind,
        "content": content,
        "source_activity_ids": [activity_id],
    }


def _setup_memory_session(store: RoomMemoryDeliveryStore, conversation_id: str) -> None:
    bindings = store.list_pending_bindings()
    room = next(
        item
        for item in bindings
        if item["conversation_id"] == conversation_id and item["scope_type"] == "room"
    )
    room = store.reserve_session_create(
        binding_id=room["binding_id"],
        client_request_id=f"session-{conversation_id}",
        expected_revision=room["revision"],
    )
    store.complete_session_create(
        binding_id=room["binding_id"],
        client_request_id=f"session-{conversation_id}",
        expected_revision=room["revision"],
        session_id=f"session-{conversation_id}",
    )
    for binding in store.list_pending_bindings():
        if binding["conversation_id"] != conversation_id:
            continue
        reserved = store.reserve_attachment(
            binding_id=binding["binding_id"],
            client_request_id=f"attach-{binding['binding_id']}",
            expected_revision=binding["revision"],
        )
        store.complete_attachment(
            binding_id=reserved["binding_id"],
            client_request_id=f"attach-{binding['binding_id']}",
            expected_revision=reserved["revision"],
            attachment_id=f"attachment-{binding['scope_type']}-{conversation_id}",
        )


def _deliver_all(store: RoomMemoryDeliveryStore) -> None:
    while claim := store.claim_next_outbox(worker_id="memory-worker"):
        store.complete_delivery(
            outbox_id=claim["outbox"]["outbox_id"],
            delivery_id=claim["delivery"]["delivery_id"],
            lease_token=claim["delivery"]["lease_token"],
            status="delivered",
            request_digest=claim["delivery"]["request_digest"],
            response_digest=DIGEST,
        )


def test_memory_candidate_contract_is_strict_and_bounded() -> None:
    activity_id = "activity_1"
    assert (
        normalize_memory_candidates(
            [_candidate("room_fact", "SQLite is authoritative.", activity_id)]
        )[0].kind
        == "room_fact"
    )
    with pytest.raises(RoomMemoryContractError):
        normalize_memory_candidates(
            [_candidate("room_fact", str(index), activity_id) for index in range(4)]
        )
    with pytest.raises(RoomMemoryContractError):
        normalize_memory_candidates([_candidate("room_fact", "x" * 4097, activity_id)])
    with pytest.raises(RoomMemoryContractError):
        normalize_memory_candidates([_candidate("invented", "not allowed", activity_id)])


def test_room_setup_prebuilds_bindings_for_pre_turn_pump_and_first_recall(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    RoomDatabase(db).initialize()
    result = RoomSetupService(tmp_path).create_conversation(
        RoomConversationCreate(
            title="Memory-ready Room",
            client_request_id="memory-ready-room",
        )
    )
    conversation_id = str(result["id"])
    participants = result["participants"]
    assert isinstance(participants, list)
    participant_id = str(participants[0]["participant_id"])
    delivery = RoomMemoryDeliveryStore(db)
    recall_store = RoomMemoryRecallStore(db)

    bindings = [
        item
        for item in delivery.list_pending_bindings()
        if item["conversation_id"] == conversation_id
    ]
    assert {item["scope_type"] for item in bindings} == {
        "local_user",
        "project",
        "room",
    }
    assert all(item["session_state"] == "unbound" for item in bindings)
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "select count(*) from room_memory_outbox where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )

    # This models the sidecar pump completing all setup before the first Human
    # turn.  It only advances durable chat.db state and performs no external I/O.
    _setup_memory_session(delivery, conversation_id)
    assert not [
        item
        for item in delivery.list_pending_bindings()
        if item["conversation_id"] == conversation_id
    ]
    root = RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="first turn",
        client_request_id="first-turn",
    )
    claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant_id,
        lease_owner="first-turn-worker",
    )
    assert claim is not None
    recall = recall_store.build_recall_request(
        conversation_id=conversation_id,
        attempt_id=claim["attempt"]["attempt_id"],
        correlation_id=root["activity"]["correlation_id"],
        causal_activity_ids=[root["activity"]["activity_id"]],
    )
    assert recall["session_id"] == f"session-{conversation_id}"
    assert len(recall["archive_ids"]) == 3


def test_schema_reopen_idempotently_backfills_existing_room_bindings(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("pre-memory Room").id
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "select count(*) from room_memory_bindings where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )

    RoomDatabase(db).initialize()
    with sqlite3.connect(db) as conn:
        first = conn.execute(
            """select binding_id, scope_type, session_state, attachment_state
               from room_memory_bindings where conversation_id = ? order by scope_type""",
            (conversation_id,),
        ).fetchall()
    RoomDatabase(db).initialize()
    with sqlite3.connect(db) as conn:
        replay = conn.execute(
            """select binding_id, scope_type, session_state, attachment_state
               from room_memory_bindings where conversation_id = ? order by scope_type""",
            (conversation_id,),
        ).fetchall()
    assert replay == first
    assert [(scope, session, attachment) for _, scope, session, attachment in first] == [
        ("local_user", "unbound", "pending"),
        ("project", "unbound", "pending"),
        ("room", "unbound", "pending"),
    ]
    assert all(str(binding_id).startswith("memory_binding_") for binding_id, *_ in first)


def test_visible_activity_outbox_trigger_backfill_and_idempotency(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("memory").id
    root = RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="visible root",
        client_request_id="root",
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind,
                actor_identity, causation_id, correlation_id, visibility,
                audience_json, payload_json, delivery_mode, created_at)
               values ('visible-shadow', ?, 2, 'test.visible', 'infrastructure',
                       'test', ?, ?, 'room', '{}', '{}', 'shadow', ?)""",
            (
                conversation_id,
                root["activity"]["activity_id"],
                root["activity"]["correlation_id"],
                root["activity"]["created_at"],
            ),
        )
        assert conn.execute("select count(*) from room_memory_outbox").fetchone()[0] == 2
        conn.execute(
            "delete from room_memory_outbox where activity_id = ?",
            (root["activity"]["activity_id"],),
        )
    RoomDatabase(db).initialize()
    RoomDatabase(db).initialize()
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "select activity_id, document_id from room_memory_outbox order by activity_id"
        ).fetchall()
    assert rows == [
        (
            root["activity"]["activity_id"],
            f"xmuse-room-activity-{root['activity']['activity_id']}",
        ),
        ("visible-shadow", "xmuse-room-activity-visible-shadow"),
    ]


def test_candidate_authority_source_guards_approval_and_no_content_spread(
    tmp_path: Path,
) -> None:
    db, registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    author = records[0]
    root_activity = root["activity"]["activity_id"]
    result = submit(
        db,
        registry,
        conversation_id,
        author[0],
        author[1],
        claims[author[0].participant_id],
        "memory-candidates",
        outcome_type="noop",
        outcome_payload={},
        memory_candidates=[
            _candidate("room_fact", "UNIQUE_AUTO_MEMORY", root_activity),
            _candidate("user_preference", "UNIQUE_PENDING_MEMORY", root_activity),
        ],
    )
    assert all("content" not in item for item in result["memory_candidates"])
    governance = RoomMemoryGovernanceStore(db)
    delivery = RoomMemoryDeliveryStore(db)
    candidates = governance.list_candidates(conversation_id)
    automatic = next(item for item in candidates if item["kind"] == "room_fact")
    pending = next(item for item in candidates if item["kind"] == "user_preference")
    assert (automatic["approval_state"], automatic["publish_state"]) == (
        "approved",
        "queued",
    )
    assert (pending["approval_state"], pending["publish_state"]) == (
        "pending",
        "not_queued",
    )
    assert governance.count_candidates(conversation_id) == 2
    assert governance.count_candidates(conversation_id, approval_state="pending") == 1
    with sqlite3.connect(db) as conn:
        values = conn.execute(
            """select 'candidate', content from room_memory_candidates
               union all select 'activity', payload_json from room_activities
               union all select 'observation', coalesce(outcome_payload_json, '')
                 from room_observations
               union all select 'request', result_json from chat_request_log
               union all select 'event', payload_json from chat_frontend_events
               union all select 'action', result_json from room_memory_candidate_actions"""
        ).fetchall()
    for marker in ("UNIQUE_AUTO_MEMORY", "UNIQUE_PENDING_MEMORY"):
        assert [(source, marker in value) for source, value in values].count(
            ("candidate", True)
        ) == 1
        assert all(source == "candidate" for source, value in values if marker in value)

    approved = governance.resolve_candidate(
        candidate_id=pending["candidate_id"],
        decision="approve",
        client_action_id="approve",
        operator_identity="operator",
        expected_candidate_digest=pending["candidate_digest"],
        expected_revision=pending["revision"],
    )
    replay = governance.resolve_candidate(
        candidate_id=pending["candidate_id"],
        decision="approve",
        client_action_id="approve",
        operator_identity="operator",
        expected_candidate_digest=pending["candidate_digest"],
        expected_revision=pending["revision"],
    )
    assert replay == approved
    assert (
        len(
            [
                item
                for item in delivery.list_outbox(conversation_id)
                if item["candidate_id"] == pending["candidate_id"]
            ]
        )
        == 1
    )
    with sqlite3.connect(db) as conn:
        leaked = conn.execute(
            """select count(*) from room_memory_candidate_actions
               where result_json like '%UNIQUE_PENDING_MEMORY%'"""
        ).fetchone()[0]
    assert leaked == 0


def test_candidate_unrelated_source_and_transaction_failure_roll_back(tmp_path, monkeypatch):
    db, registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    unrelated = RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="later root",
        client_request_id="later-root",
    )
    author = records[0]
    with pytest.raises(RoomApplicationError) as source_error:
        submit(
            db,
            registry,
            conversation_id,
            author[0],
            author[1],
            claims[author[0].participant_id],
            "bad-source",
            outcome_type="noop",
            outcome_payload={},
            memory_candidates=[
                _candidate("room_fact", "must roll back", unrelated["activity"]["activity_id"])
            ],
        )
    assert source_error.value.code == "room_memory_candidate_source_forbidden"

    original = RoomKernelStore._insert_lifecycle_request_log_conn

    def fail(*args, **kwargs):
        raise RuntimeError("forced rollback")

    monkeypatch.setattr(RoomKernelStore, "_insert_lifecycle_request_log_conn", fail)
    with pytest.raises(RuntimeError, match="forced rollback"):
        RoomApplicationService(db, registry).submit_participant_outcome(
            conversation_id=conversation_id,
            participant_id=author[0].participant_id,
            god_session_id=author[1].god_session_id,
            observation_id=claims[author[0].participant_id]["observation"]["observation_id"],
            lease_token=claims[author[0].participant_id]["observation"]["lease_token"],
            client_request_id="rollback",
            outcome_type="noop",
            outcome_payload={},
            memory_candidates=[
                _candidate("room_fact", "rollback marker", root["activity"]["activity_id"])
            ],
        )
    monkeypatch.setattr(RoomKernelStore, "_insert_lifecycle_request_log_conn", original)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from room_memory_candidates").fetchone()[0] == 0
        assert (
            conn.execute(
                "select count(*) from room_memory_outbox where candidate_id is not null"
            ).fetchone()[0]
            == 0
        )


def test_recall_receipt_two_phase_and_false_text_fail_closed(tmp_path: Path) -> None:
    db, _registry, conversation_id, records, root, claims = root_and_claims(tmp_path)
    delivery = RoomMemoryDeliveryStore(db)
    recall_store = RoomMemoryRecallStore(db)
    attempt_id = claims[records[0][0].participant_id]["attempt"]["attempt_id"]
    activity_id = root["activity"]["activity_id"]
    with pytest.raises(RoomMemoryStoreError) as unavailable:
        recall_store.build_recall_request(
            conversation_id=conversation_id,
            attempt_id=attempt_id,
            correlation_id=root["activity"]["correlation_id"],
            causal_activity_ids=[activity_id],
        )
    assert unavailable.value.code == "room_memory_recall_unavailable"
    _setup_memory_session(delivery, conversation_id)
    request = recall_store.build_recall_request(
        conversation_id=conversation_id,
        attempt_id=attempt_id,
        correlation_id=root["activity"]["correlation_id"],
        causal_activity_ids=[activity_id],
    )
    assert request["build_context_request"]["include_global_core"] is False
    with pytest.raises(RoomMemoryStoreError) as forged:
        recall_store.record_attempt_memory_receipt(
            attempt_id=attempt_id,
            status="ok",
            schema_version="metadata.v3_context/v1",
            latency_ms=5,
            items=[
                {
                    "item_id": "item_forged",
                    "document_id": f"xmuse-room-activity-{activity_id}",
                    "source_activity_ids": [activity_id],
                    "content_sha256": _sha("forged"),
                    "text": "forged",
                }
            ],
            evidence_sha256=DIGEST,
        )
    assert forged.value.code == "room_memory_recall_source_rejected"
    receipt = recall_store.record_attempt_memory_receipt(
        attempt_id=attempt_id,
        status="ok",
        schema_version="metadata.v3_context/v1",
        latency_ms=5,
        items=[
            {
                "item_id": "item_valid",
                "document_id": f"xmuse-room-activity-{activity_id}",
                "source_activity_ids": [activity_id],
                "content_sha256": _sha("ell"),
                "text": "ell",
            }
        ],
        evidence_sha256=DIGEST,
    )
    assert receipt["context_payload_sha256"] is None
    assert all("text" not in item for item in receipt["item_refs"])
    bound = recall_store.bind_attempt_memory_context(
        attempt_id=attempt_id,
        evidence_sha256=DIGEST,
        context_payload_sha256="sha256:" + "2" * 64,
    )
    assert bound["context_submitted_at"] is not None


def test_outbox_claim_uses_real_archive_contract_and_ack_replays(tmp_path: Path) -> None:
    db, _registry, conversation_id, _records, root, _claims = root_and_claims(tmp_path)
    delivery = RoomMemoryDeliveryStore(db)
    _setup_memory_session(delivery, conversation_id)
    claim = delivery.claim_next_outbox(worker_id="worker")
    assert claim is not None
    request = claim["document_request"]
    assert request["document_id"] == (f"xmuse-room-activity-{root['activity']['activity_id']}")
    assert request["source_refs"][0]["source_type"] == "document"
    assert request["source_refs"][0]["source_id"] == root["activity"]["activity_id"]
    arguments = {
        "outbox_id": claim["outbox"]["outbox_id"],
        "delivery_id": claim["delivery"]["delivery_id"],
        "lease_token": claim["delivery"]["lease_token"],
        "status": "delivered",
        "request_digest": claim["delivery"]["request_digest"],
        "response_digest": DIGEST,
    }
    completed = delivery.complete_delivery(**arguments)
    assert delivery.complete_delivery(**arguments) == completed


def test_uncertain_binding_reopens_only_after_durable_backoff(tmp_path: Path) -> None:
    db, _registry, conversation_id, _records, _root, _claims = root_and_claims(tmp_path)
    delivery = RoomMemoryDeliveryStore(db)
    start = datetime(2026, 7, 12, tzinfo=UTC)
    room = next(
        item
        for item in delivery.list_pending_bindings()
        if item["conversation_id"] == conversation_id and item["scope_type"] == "room"
    )
    creating = delivery.reserve_session_create(
        binding_id=room["binding_id"],
        client_request_id="uncertain-session-1",
        expected_revision=room["revision"],
        now=start,
    )
    uncertain = delivery.complete_session_create(
        binding_id=room["binding_id"],
        client_request_id="uncertain-session-1",
        expected_revision=creating["revision"],
        session_id=None,
        uncertain=True,
        now=start,
    )
    assert uncertain["session_retry_count"] == 1
    assert uncertain["session_retry_not_before"] == "2026-07-12T00:00:01.000000Z"
    with pytest.raises(RoomMemoryStoreError) as early:
        delivery.reopen_uncertain_binding(
            binding_id=room["binding_id"],
            expected_revision=uncertain["revision"],
            now=start,
        )
    assert early.value.code == "room_memory_binding_retry_not_ready"
    reopened = delivery.reopen_uncertain_binding(
        binding_id=room["binding_id"],
        expected_revision=uncertain["revision"],
        now=start + timedelta(seconds=1),
    )
    assert reopened["session_state"] == "unbound"
    assert reopened["session_retry_count"] == 1
    assert reopened["session_retry_not_before"] is None
    with sqlite3.connect(db) as conn:
        session_fields = conn.execute(
            "select session_id, session_request_id from room_memory_bindings where binding_id = ?",
            (room["binding_id"],),
        ).fetchone()
    assert session_fields == (None, None)
    with pytest.raises(RoomMemoryStoreError) as stale:
        delivery.reopen_uncertain_binding(
            binding_id=room["binding_id"],
            expected_revision=uncertain["revision"],
            now=start + timedelta(seconds=1),
        )
    assert stale.value.code == "room_memory_binding_reopen_guard_mismatch"

    creating_again = delivery.reserve_session_create(
        binding_id=room["binding_id"],
        client_request_id="uncertain-session-2",
        expected_revision=reopened["revision"],
        now=start + timedelta(seconds=1),
    )
    bound = delivery.complete_session_create(
        binding_id=room["binding_id"],
        client_request_id="uncertain-session-2",
        expected_revision=creating_again["revision"],
        session_id="memory-session",
        now=start + timedelta(seconds=1),
    )
    pending_attachment = delivery.reserve_attachment(
        binding_id=room["binding_id"],
        client_request_id="uncertain-attachment",
        expected_revision=bound["revision"],
        now=start + timedelta(seconds=1),
    )
    attachment_uncertain = delivery.complete_attachment(
        binding_id=room["binding_id"],
        client_request_id="uncertain-attachment",
        expected_revision=pending_attachment["revision"],
        attachment_id=None,
        uncertain=True,
        now=start + timedelta(seconds=1),
    )
    attachment_reopened = delivery.reopen_uncertain_binding(
        binding_id=room["binding_id"],
        expected_revision=attachment_uncertain["revision"],
        now=start + timedelta(seconds=2),
    )
    assert attachment_reopened["attachment_state"] == "pending"
    assert attachment_reopened["attachment_retry_count"] == 1
    with sqlite3.connect(db) as conn:
        attachment_fields = conn.execute(
            "select attachment_id, attachment_request_id from room_memory_bindings "
            "where binding_id = ?",
            (room["binding_id"],),
        ).fetchone()
    assert attachment_fields == (None, None)


def test_failed_outbox_retry_is_durable_bounded_and_never_reopens_conflict(
    tmp_path: Path,
) -> None:
    db, _registry, conversation_id, _records, _root, _claims = root_and_claims(tmp_path)
    delivery = RoomMemoryDeliveryStore(db)
    _setup_memory_session(delivery, conversation_id)
    start = datetime(2026, 7, 12, tzinfo=UTC)
    first = delivery.claim_next_outbox(worker_id="worker", now=start)
    assert first is not None
    failed = delivery.complete_delivery(
        outbox_id=first["outbox"]["outbox_id"],
        delivery_id=first["delivery"]["delivery_id"],
        lease_token=first["delivery"]["lease_token"],
        status="failed",
        request_digest=first["delivery"]["request_digest"],
        reason_code="memoryos_unavailable",
        now=start,
    )
    assert failed["next_attempt_at"] == "2026-07-12T00:00:01.000000Z"
    assert delivery.requeue_retryable_failed_outbox(now=start, limit=1) == []
    reopened = delivery.requeue_retryable_failed_outbox(now=start + timedelta(seconds=1), limit=1)
    assert [item["outbox_id"] for item in reopened] == [first["outbox"]["outbox_id"]]

    second = delivery.claim_next_outbox(worker_id="worker", now=start + timedelta(seconds=1))
    assert second is not None
    assert second["outbox"]["outbox_id"] == first["outbox"]["outbox_id"]
    conflict = delivery.complete_delivery(
        outbox_id=second["outbox"]["outbox_id"],
        delivery_id=second["delivery"]["delivery_id"],
        lease_token=second["delivery"]["lease_token"],
        status="conflict",
        request_digest=second["delivery"]["request_digest"],
        reason_code="memoryos_document_conflict",
        now=start + timedelta(seconds=1),
    )
    assert conflict["state"] == "conflict"
    assert delivery.requeue_retryable_failed_outbox(now=start + timedelta(days=1), limit=100) == []
    with sqlite3.connect(db) as conn:
        attempts = conn.execute(
            "select count(*) from room_memory_deliveries where outbox_id = ?",
            (first["outbox"]["outbox_id"],),
        ).fetchone()[0]
    assert attempts == 2


@pytest.mark.parametrize(
    ("kind", "target_scope", "cross_room"),
    [
        ("room_fact", "room", False),
        ("room_decision", "room", False),
        ("user_preference", "local_user", True),
        ("project_rule", "project", True),
    ],
)
def test_candidate_recall_scope_chunk_and_source_proof_are_strict(
    tmp_path: Path,
    kind: str,
    target_scope: str,
    cross_room: bool,
) -> None:
    db, registry, first_room, records, root, claims = root_and_claims(tmp_path)
    author = records[0]
    content = f"{kind}:" + "0123456789" * 300
    chunk = content[701:1901]
    assert len(chunk) == 1200
    result = submit(
        db,
        registry,
        first_room,
        author[0],
        author[1],
        claims[author[0].participant_id],
        f"candidate-{kind}",
        outcome_type="noop",
        outcome_payload={},
        memory_candidates=[_candidate(kind, content, root["activity"]["activity_id"])],
    )
    candidate_ref = result["memory_candidates"][0]
    second_room = RoomTestStore(db).create_conversation("second room").id
    RoomKernelStore(db).post_human_activity(
        conversation_id=second_room,
        human_id="human",
        content="new room",
        client_request_id="second-root",
    )
    governance = RoomMemoryGovernanceStore(db)
    delivery = RoomMemoryDeliveryStore(db)
    recall_store = RoomMemoryRecallStore(db)
    document_id = f"xmuse-room-memory-candidate-{candidate_ref['candidate_id']}"
    pending = governance.get_candidate(candidate_ref["candidate_id"])
    assert pending is not None
    if pending["approval_state"] == "pending":
        governance.resolve_candidate(
            candidate_id=pending["candidate_id"],
            decision="approve",
            client_action_id=f"approve-{kind}",
            operator_identity="operator",
            expected_candidate_digest=pending["candidate_digest"],
            expected_revision=pending["revision"],
        )
    _setup_memory_session(delivery, first_room)
    _setup_memory_session(delivery, second_room)
    _deliver_all(delivery)
    recall_room = second_room if cross_room else first_room
    resolved = recall_store.resolve_recall_source(
        conversation_id=recall_room,
        document_id=document_id,
        source_activity_ids=candidate_ref["source_activity_ids"],
        content_sha256=_sha(chunk),
        item_text=chunk,
    )
    assert resolved["source_type"] == ("shared_candidate" if cross_room else "room_candidate")
    assert resolved["target_scope"] == target_scope
    assert resolved["item_content_sha256"] == _sha(chunk)
    assert resolved["authority_content_sha256"] == _sha(content)

    if not cross_room:
        with pytest.raises(RoomMemoryStoreError):
            recall_store.resolve_recall_source(
                conversation_id=second_room,
                document_id=document_id,
                source_activity_ids=candidate_ref["source_activity_ids"],
                content_sha256=_sha(chunk),
                item_text=chunk,
            )
    for forged in (
        {
            "document_id": f"{document_id}-forged",
            "source_activity_ids": candidate_ref["source_activity_ids"],
            "content_sha256": _sha(chunk),
            "item_text": chunk,
        },
        {
            "document_id": document_id,
            "source_activity_ids": ["activity-forged"],
            "content_sha256": _sha(chunk),
            "item_text": chunk,
        },
        {
            "document_id": document_id,
            "source_activity_ids": candidate_ref["source_activity_ids"],
            "content_sha256": _sha("forged candidate chunk"),
            "item_text": "forged candidate chunk",
        },
        {
            "document_id": document_id,
            "source_activity_ids": candidate_ref["source_activity_ids"],
            "content_sha256": candidate_ref["content_sha256"],
            "item_text": chunk,
        },
    ):
        with pytest.raises(RoomMemoryStoreError):
            recall_store.resolve_recall_source(conversation_id=recall_room, **forged)
