from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_memory_binding_conn import ensure_room_memory_bindings_conn
from xmuse_core.chat.room_memory_common import RoomMemoryStoreError
from xmuse_core.chat.room_memory_delivery_store import (
    RoomMemoryDeliveryStore,
    queue_candidate_delivery_conn,
)

_RESPONSE_DIGEST = "sha256:" + "a" * 64


def _bind_session_and_archives(
    store: RoomMemoryDeliveryStore,
    conversation_id: str,
    *,
    now: datetime,
) -> None:
    room = store.ensure_binding(conversation_id=conversation_id, now=now)
    reserved = store.reserve_session_create(
        binding_id=room["binding_id"],
        client_request_id="session-create",
        expected_revision=room["revision"],
        now=now,
    )
    store.complete_session_create(
        binding_id=room["binding_id"],
        client_request_id="session-create",
        expected_revision=reserved["revision"],
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


def test_connection_helpers_require_a_caller_owned_transaction(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("transaction guard").id

    with RoomDatabase(db).connect() as conn:
        with pytest.raises(RoomMemoryStoreError) as binding_error:
            ensure_room_memory_bindings_conn(
                conn,
                conversation_id=conversation_id,
                stamp="2026-07-12T00:00:00.000000Z",
            )
        assert binding_error.value.code == "room_memory_binding_transaction_required"

        with pytest.raises(RoomMemoryStoreError) as delivery_error:
            queue_candidate_delivery_conn(
                conn,
                candidate=cast(sqlite3.Row, {}),
                stamp="2026-07-12T00:00:00.000000Z",
            )
        assert delivery_error.value.code == "room_memory_delivery_transaction_required"

    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "select count(*) from room_memory_bindings where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
            == 0
        )


def test_schema_reopen_backfills_all_bindings_without_rewriting_them(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("legacy Room").id

    RoomDatabase(db).initialize()
    with sqlite3.connect(db) as conn:
        first = conn.execute(
            """select binding_id, scope_type, scope_key, archive_id, revision
               from room_memory_bindings where conversation_id = ? order by scope_type""",
            (conversation_id,),
        ).fetchall()
    RoomDatabase(db).initialize()
    with sqlite3.connect(db) as conn:
        replay = conn.execute(
            """select binding_id, scope_type, scope_key, archive_id, revision
               from room_memory_bindings where conversation_id = ? order by scope_type""",
            (conversation_id,),
        ).fetchall()

    assert replay == first
    assert [row[1] for row in first] == ["local_user", "project", "room"]
    assert all(row[4] == 0 for row in first)


def test_session_and_attachment_reservations_replay_and_share_one_session(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("binding replay").id
    store = RoomMemoryDeliveryStore(db)
    now = datetime(2026, 7, 12, tzinfo=UTC)
    room = store.ensure_binding(conversation_id=conversation_id, now=now)

    creating = store.reserve_session_create(
        binding_id=room["binding_id"],
        client_request_id="session-request",
        expected_revision=room["revision"],
        now=now,
    )
    assert (
        store.reserve_session_create(
            binding_id=room["binding_id"],
            client_request_id="session-request",
            expected_revision=room["revision"],
            now=now,
        )
        == creating
    )
    with pytest.raises(RoomMemoryStoreError) as competing:
        store.reserve_session_create(
            binding_id=room["binding_id"],
            client_request_id="competing-request",
            expected_revision=room["revision"],
            now=now,
        )
    assert competing.value.code == "room_memory_session_guard_mismatch"

    store.complete_session_create(
        binding_id=room["binding_id"],
        client_request_id="session-request",
        expected_revision=creating["revision"],
        session_id="shared-session",
        now=now,
    )
    with sqlite3.connect(db) as conn:
        session_rows = conn.execute(
            """select scope_type, session_id, session_state
               from room_memory_bindings where conversation_id = ? order by scope_type""",
            (conversation_id,),
        ).fetchall()
    assert session_rows == [
        ("local_user", "shared-session", "bound"),
        ("project", "shared-session", "bound"),
        ("room", "shared-session", "bound"),
    ]

    project = store.get_binding_internal(conversation_id, scope_type="project")
    assert project is not None
    attaching = store.reserve_attachment(
        binding_id=project["binding_id"],
        client_request_id="attach-project",
        expected_revision=project["revision"],
        now=now,
    )
    assert (
        store.reserve_attachment(
            binding_id=project["binding_id"],
            client_request_id="attach-project",
            expected_revision=project["revision"],
            now=now,
        )
        == attaching
    )
    completed = store.complete_attachment(
        binding_id=project["binding_id"],
        client_request_id="attach-project",
        expected_revision=attaching["revision"],
        attachment_id="project-attachment",
        now=now,
    )
    assert completed["attachment_state"] == "attached"


def test_expired_delivery_is_reclaimed_and_late_ack_is_fenced(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("delivery fencing").id
    start = datetime(2026, 7, 12, tzinfo=UTC)
    store = RoomMemoryDeliveryStore(db)
    _bind_session_and_archives(store, conversation_id, now=start)
    root = RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="archive this source",
        client_request_id="source-activity",
    )

    first = store.claim_next_outbox(worker_id="memory-worker-1", lease_ttl_s=5, now=start)
    assert first is not None
    second = store.claim_next_outbox(
        worker_id="memory-worker-2", lease_ttl_s=5, now=start + timedelta(seconds=5)
    )
    assert second is not None
    assert second["outbox"]["outbox_id"] == first["outbox"]["outbox_id"]
    assert second["delivery"]["attempt_number"] == 2
    assert second["document_request"]["document_id"] == (
        f"xmuse-room-activity-{root['activity']['activity_id']}"
    )

    with pytest.raises(RoomMemoryStoreError) as late:
        store.complete_delivery(
            outbox_id=first["outbox"]["outbox_id"],
            delivery_id=first["delivery"]["delivery_id"],
            lease_token=first["delivery"]["lease_token"],
            status="delivered",
            request_digest=first["delivery"]["request_digest"],
            response_digest=_RESPONSE_DIGEST,
            now=start + timedelta(seconds=5),
        )
    assert late.value.code == "room_memory_delivery_lease_lost"

    arguments = {
        "outbox_id": second["outbox"]["outbox_id"],
        "delivery_id": second["delivery"]["delivery_id"],
        "lease_token": second["delivery"]["lease_token"],
        "status": "delivered",
        "request_digest": second["delivery"]["request_digest"],
        "response_digest": _RESPONSE_DIGEST,
        "now": start + timedelta(seconds=5),
    }
    completed = store.complete_delivery(**arguments)
    assert store.complete_delivery(**arguments) == completed
    with sqlite3.connect(db) as conn:
        first_attempt = conn.execute(
            """select state, reason_code from room_memory_deliveries
               where delivery_id = ?""",
            (first["delivery"]["delivery_id"],),
        ).fetchone()
    assert first_attempt == ("failed", "memory_delivery_lease_expired")
