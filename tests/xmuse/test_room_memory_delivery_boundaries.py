from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_memory_binding_store import RoomMemoryBindingStore
from xmuse_core.chat.room_memory_document_outbox_store import (
    RoomMemoryDocumentOutboxStore,
)
from xmuse_core.chat.room_memory_message_outbox_store import (
    RoomMemoryMessageOutboxStore,
)
from xmuse_core.chat.room_memory_ports import (
    RoomMemoryBindingSessionAttachmentPort,
    RoomMemoryDocumentOutboxPort,
    RoomMemoryMessageOutboxPort,
)

_RESPONSE_DIGEST = "sha256:" + "b" * 64


def _bind_session_and_archives(
    store: RoomMemoryBindingStore,
    conversation_id: str,
    *,
    now: datetime,
) -> None:
    room = store.ensure_binding(conversation_id=conversation_id, now=now)
    creating = store.reserve_session_create(
        binding_id=room["binding_id"],
        client_request_id="create-session",
        expected_revision=room["revision"],
        now=now,
    )
    store.complete_session_create(
        binding_id=room["binding_id"],
        client_request_id="create-session",
        expected_revision=creating["revision"],
        session_id="memory-session",
        now=now,
    )
    for binding in store.list_pending_bindings():
        if binding["conversation_id"] != conversation_id:
            continue
        attaching = store.reserve_attachment(
            binding_id=binding["binding_id"],
            client_request_id=f"attach-{binding['scope_type']}",
            expected_revision=binding["revision"],
            now=now,
        )
        store.complete_attachment(
            binding_id=binding["binding_id"],
            client_request_id=f"attach-{binding['scope_type']}",
            expected_revision=attaching["revision"],
            attachment_id=f"attachment-{binding['scope_type']}",
            now=now,
        )


def test_split_stores_satisfy_frozen_ports_without_cross_domain_methods(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    RoomTestStore(db).create_conversation("narrow memory stores")
    binding = RoomMemoryBindingStore(db)
    message = RoomMemoryMessageOutboxStore(db)
    document = RoomMemoryDocumentOutboxStore(db)

    binding_port: RoomMemoryBindingSessionAttachmentPort = binding
    message_port: RoomMemoryMessageOutboxPort = message
    document_port: RoomMemoryDocumentOutboxPort = document

    assert binding_port is binding
    assert message_port is message
    assert document_port is document
    assert not hasattr(binding, "claim_next_outbox")
    assert not hasattr(binding, "claim_next_message_outbox")
    assert not hasattr(message, "claim_next_outbox")
    assert not hasattr(message, "reserve_session_create")
    assert not hasattr(document, "claim_next_message_outbox")
    assert not hasattr(document, "reserve_attachment")


def test_split_message_and_document_stores_preserve_delivery_semantics(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("split delivery").id
    now = datetime(2026, 7, 16, tzinfo=UTC)
    _bind_session_and_archives(RoomMemoryBindingStore(db), conversation_id, now=now)
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Deliver through both narrow outboxes.",
        client_request_id="split-outbox-source",
    )

    message_store = RoomMemoryMessageOutboxStore(db)
    message_claim = message_store.claim_next_message_outbox(worker_id="message-worker", now=now)
    assert message_claim is not None
    assert message_claim["message_request"]["role"] == "user"
    message_result = message_store.complete_message_delivery(
        message_outbox_id=message_claim["outbox"]["message_outbox_id"],
        delivery_id=message_claim["delivery"]["delivery_id"],
        lease_token=message_claim["delivery"]["lease_token"],
        status="delivered",
        request_digest=message_claim["delivery"]["request_digest"],
        response_digest=_RESPONSE_DIGEST,
        memoryos_message_id="memory-message",
        memoryos_session_id="memory-session",
        now=now,
    )
    assert message_result["state"] == "delivered"

    document_store = RoomMemoryDocumentOutboxStore(db)
    document_claim = document_store.claim_next_outbox(worker_id="document-worker", now=now)
    assert document_claim is not None
    document_result = document_store.complete_delivery(
        outbox_id=document_claim["outbox"]["outbox_id"],
        delivery_id=document_claim["delivery"]["delivery_id"],
        lease_token=document_claim["delivery"]["lease_token"],
        status="delivered",
        request_digest=document_claim["delivery"]["request_digest"],
        response_digest=_RESPONSE_DIGEST,
        now=now,
    )
    assert document_result["state"] == "delivered"
