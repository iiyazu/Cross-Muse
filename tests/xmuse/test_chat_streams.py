from __future__ import annotations

import sqlite3
from pathlib import Path

from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter
from xmuse_core.chat import stream_store as stream_store_module
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import ChatStreamStore, PeerTurnLatencyTraceStore


def test_chat_stream_store_accumulates_active_delta(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Streaming")
    streams = ChatStreamStore(tmp_path / "chat.db")

    stream = streams.start_or_reset(
        conversation_id=conv.id,
        author="architect-god",
        role="assistant",
        request_id="inbox-1",
        source_inbox_item_id="inbox-1",
    )
    streams.append_delta(stream.id, "hello")
    streams.append_delta(stream.id, " world")

    active = streams.list_active(conv.id)

    assert len(active) == 1
    assert active[0].id == "stream_inbox-1"
    assert active[0].content == "hello world"

    streams.finish(stream.id)

    assert streams.list_active(conv.id) == []


def test_chat_stream_store_records_first_delta_at_once(tmp_path: Path, monkeypatch) -> None:
    clock_values = iter(
        [
            "2026-06-04T00:00:00Z",
            "2026-06-04T00:00:01Z",
            "2026-06-04T00:00:02Z",
        ]
    )
    monkeypatch.setattr(stream_store_module, "_utc_now", lambda: next(clock_values))
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Streaming latency")
    streams = ChatStreamStore(tmp_path / "chat.db")

    stream = streams.start_or_reset(
        conversation_id=conv.id,
        author="architect-god",
        role="assistant",
        request_id="inbox-1",
        source_inbox_item_id="inbox-1",
    )
    first = streams.append_delta(stream.id, "hello")
    second = streams.append_delta(stream.id, " world")

    assert first.first_delta_at == "2026-06-04T00:00:01Z"
    assert second.first_delta_at == "2026-06-04T00:00:01Z"
    assert second.updated_at == "2026-06-04T00:00:02Z"


def test_peer_latency_trace_store_migrates_old_schema_supporting_context(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Old trace schema")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            create table peer_turn_latency_traces (
                id text primary key,
                conversation_id text not null references conversations(id),
                inbox_item_id text not null,
                god_session_id text,
                participant_id text,
                target_role text,
                provider_session_id text,
                provider_session_kind text,
                provider_binding_status text,
                provider_binding_failure_reason text,
                message_created_at text not null,
                inbox_claimed_at text,
                delivery_started_at real not null,
                provider_turn_started_at real not null,
                first_delta_at real,
                writeback_at real not null,
                total_latency_ms integer not null,
                delivery_mode text not null,
                degraded_reason text,
                stage_timings_json text not null default '{}'
            )
            """
        )

    traces = PeerTurnLatencyTraceStore(db)
    traces.record(
        conversation_id=conv.id,
        inbox_item_id="inbox-old-schema",
        participant_id="participant-old-schema",
        target_role="architect",
        message_created_at="2026-06-28T00:00:00Z",
        inbox_claimed_at=None,
        delivery_started_at=1.0,
        provider_turn_started_at=1.1,
        first_delta_at=None,
        writeback_at=2.0,
        total_latency_ms=1000,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
        supporting_context={
            "memoryos_sidecar": {
                "status": "attached",
                "source_refs": ["memoryos:sidecar"],
            }
        },
    )

    [trace] = traces.list_recent(conv.id)
    assert trace["supporting_context"] == {
        "memoryos_sidecar": {
            "status": "attached",
            "source_refs": ["memoryos:sidecar"],
        }
    }


def test_tui_adapter_projects_active_stream_as_temporary_message(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Streaming")
    chat.add_message(conv.id, "human", "human", "@architect hihi")
    streams = ChatStreamStore(tmp_path / "chat.db")
    stream = streams.start_or_reset(
        conversation_id=conv.id,
        author="architect-god",
        role="assistant",
        request_id="inbox-1",
    )
    streams.append_delta(stream.id, "hi")

    adapter = XmuseAdapter(tmp_path)
    messages, error = adapter.poll_messages(conv.id)

    assert error is None
    assert [message["content"] for message in messages] == ["@architect hihi", "hi"]
    assert messages[-1]["id"] == "stream_inbox-1"
    assert messages[-1]["envelope_type"] == "stream"

    streams.append_delta(stream.id, " there")
    messages, error = adapter.poll_messages(conv.id)

    assert error is None
    assert len(messages) == 1
    assert messages[0]["id"] == "stream_inbox-1"
    assert messages[0]["content"] == "hi there"


def test_tui_adapter_hides_active_stream_after_matching_final_message(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Streaming final")
    chat.add_message(
        conv.id,
        "architect-god",
        "assistant",
        "final answer",
        envelope_type="peer_reply",
        envelope_json={"source_inbox_item_id": "inbox-1"},
    )
    streams = ChatStreamStore(tmp_path / "chat.db")
    stream = streams.start_or_reset(
        conversation_id=conv.id,
        author="architect-god",
        role="assistant",
        request_id="inbox-1",
        source_inbox_item_id="inbox-1",
    )
    streams.append_delta(stream.id, "final answer")

    messages, error = XmuseAdapter(tmp_path).poll_messages(conv.id)

    assert error is None
    assert [message["content"] for message in messages] == ["final answer"]
    assert all(message["envelope_type"] != "stream" for message in messages)
