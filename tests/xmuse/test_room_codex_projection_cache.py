from __future__ import annotations

import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import xmuse_core.chat.room_codex_projection_cache as cache_module
from xmuse_core.chat.room_codex_projection_cache import (
    EVENT_CACHE_SCHEMA,
    MAX_EVENT_BYTES,
    RoomCodexProjectionCache,
    RoomCodexProjectionCacheError,
    sanitize_native_notification,
)

GUARD = "sha256:" + "a" * 64


def _snapshot(*, objective: str = "private provider text") -> dict[str, object]:
    return {
        "schema_version": "room_codex_native_snapshot/v1",
        "source": "codex_app_server",
        "observed_at": "2026-07-13T00:00:00Z",
        "goal": {
            "objective": objective,
            "status": "active",
            "token_budget": 100_000,
            "tokens_used": 12,
            "time_used_seconds": 4,
        },
        "settings": {"model": "gpt-5.6", "effort": "max"},
        "active_turn": True,
        "guards": {"session": GUARD, "goal": GUARD, "settings": GUARD, "turn": GUARD},
    }


def _capabilities(*, private_description: str = "private provider text") -> dict[str, object]:
    return {
        "schema_version": "room_codex_native_capabilities/v1",
        "source": "codex_app_server",
        "capabilities": [
            {
                "capability_id": "goal_get",
                "native_source": "thread/goal/get",
                "availability": "available",
                "disabled_reason": None,
                "session_guard": GUARD,
                "unexpected": private_description,
            }
        ],
        "models": [
            {
                "id": "gpt-5.6",
                "model": "gpt-5.6",
                "display_name": private_description,
                "description": private_description,
                "is_default": True,
                "default_effort": "high",
                "efforts": ["medium", "high", "max"],
            }
        ],
    }


def _append(cache: RoomCodexProjectionCache, index: int) -> dict[str, object]:
    event = cache.append_notification(
        conversation_id="room-one",
        participant_id="participant-one",
        notification={
            "method": "turn/completed",
            "params": {
                "threadId": f"private-thread-{index}",
                "turn": {"id": f"private-turn-{index}", "status": "completed"},
            },
        },
        observed_at="2026-07-13T00:00:00Z",
    )
    assert event is not None
    return event


def test_private_database_and_runtime_modes_and_safe_current_projection(tmp_path: Path) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    secret = "sk-private-provider-token-and-/home/iiyatu/workspace"

    current = cache.replace_current(
        conversation_id="room-one",
        participant_id="participant-one",
        snapshot=_snapshot(objective=secret),
        capabilities=_capabilities(private_description=secret),
    )

    assert stat.S_IMODE(cache.path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache.path.stat().st_mode) == 0o600
    assert current["native_snapshot"] == {
        "schema_version": "room_codex_native_snapshot/v1",
        "source": "codex_app_server",
        "goal": {
            "status": "active",
            "objective": "[redacted][path]",
            "token_budget": 100_000,
            "tokens_used": 12,
            "time_used_seconds": 4,
        },
        "settings": {"model": "gpt-5.6", "effort": "max"},
        "active_turn": True,
        "guards": {"session": GUARD, "goal": GUARD, "settings": GUARD, "turn": GUARD},
    }
    encoded = cache.path.read_bytes()
    assert secret.encode() not in encoded
    assert b"private provider text" not in encoded


@pytest.mark.parametrize(
    "notification",
    [
        {
            "method": "item/reasoning/textDelta",
            "params": {"delta": "raw hidden reasoning", "turnId": "private-turn"},
        },
        {
            "method": "item/agentMessage/delta",
            "params": {"delta": "raw provider output", "turnId": "private-turn"},
        },
        {
            "method": "item/mcpToolCall/progress",
            "params": {"arguments": {"token": "private-token"}, "result": "private-result"},
        },
        {"method": "future/private", "params": {"path": "/home/private"}},
    ],
)
def test_raw_or_unknown_notifications_fail_closed(notification: dict[str, object]) -> None:
    assert sanitize_native_notification(notification) is None


def test_completed_agent_message_is_bounded_and_redacted_but_delta_is_not_stored() -> None:
    event = sanitize_native_notification(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "private-item",
                    "type": "agentMessage",
                    "text": "Done with sk-private-token at /home/iiyatu/project/file.py",
                    "status": "completed",
                }
            },
        }
    )

    assert event == {
        "kind": "item_completed",
        "item_type": "agentMessage",
        "status": "completed",
        "text": "Done with [redacted] at [path]",
    }


def test_allowlist_rebuilds_events_without_native_ids_output_paths_or_mcp_data(
    tmp_path: Path,
) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    canaries = [
        "private-thread-id",
        "private-turn-id",
        "private-item-id",
        "sk-private-token",
        "/home/iiyatu/private.py",
        "provider stdout and result",
        "private mcp arguments",
        "visible plan text",
    ]
    notifications = [
        {
            "method": "thread/goal/updated",
            "params": {
                "threadId": canaries[0],
                "turnId": canaries[1],
                "goal": {"objective": canaries[5], "status": "active"},
            },
        },
        {
            "method": "turn/plan/updated",
            "params": {
                "threadId": canaries[0],
                "turnId": canaries[1],
                "plan": [
                    {"step": canaries[-1], "status": "inProgress"},
                    {"step": "/home/private", "status": "completed"},
                ],
            },
        },
        {
            "method": "turn/diff/updated",
            "params": {
                "threadId": canaries[0],
                "turnId": canaries[1],
                "diff": (
                    f"diff --git a/{canaries[4]} b/{canaries[4]}\n"
                    "--- a/private.py\n+++ b/private.py\n-old\n+new\n"
                ),
            },
        },
        {
            "method": "item/completed",
            "params": {
                "threadId": canaries[0],
                "turnId": canaries[1],
                "item": {
                    "id": canaries[2],
                    "type": "mcpToolCall",
                    "status": "completed",
                    "server": "private-server",
                    "tool": "private-tool",
                    "arguments": {"value": canaries[6], "token": canaries[3]},
                    "result": canaries[5],
                    "durationMs": 25,
                },
            },
        },
        {
            "method": "item/completed",
            "params": {
                "threadId": canaries[0],
                "turnId": canaries[1],
                "item": {
                    "id": canaries[2],
                    "type": "commandExecution",
                    "status": "completed",
                    "command": f"cat {canaries[4]}",
                    "cwd": "/home/iiyatu",
                    "aggregatedOutput": canaries[5],
                    "durationMs": 8,
                    "exitCode": 0,
                },
            },
        },
    ]
    for notification in notifications:
        assert (
            cache.append_notification(
                conversation_id="room-one",
                participant_id="participant-one",
                notification=notification,
            )
            is not None
        )

    page = cache.read_conversation("room-one")
    assert [event["kind"] for event in page["events"]] == [
        "goal_updated",
        "plan_updated",
        "diff_updated",
        "item_completed",
        "item_completed",
    ]
    assert page["events"][0]["status"] == "active"
    assert "objective" not in page["events"][0]
    assert page["events"][1]["status_counts"] == {"completed": 1, "in_progress": 1}
    assert page["events"][1]["steps"] == [
        {"step": "visible plan text", "status": "in_progress"},
        {"step": "[path]", "status": "completed"},
    ]
    assert page["events"][2]["file_count"] == 1
    assert page["events"][3]["item_type"] == "mcpToolCall"
    assert "arguments" not in page["events"][3]
    disk = cache.path.read_bytes()
    for canary in canaries[:-1]:
        assert canary.encode() not in disk


def test_oldest_first_count_trimming_records_omission_and_independent_sequence(
    tmp_path: Path,
) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    for index in range(501):
        _append(cache, index)
    cache.append_notification(
        conversation_id="room-one",
        participant_id="participant-two",
        notification={"method": "thread/goal/cleared", "params": {"threadId": "private"}},
    )

    page = cache.read_conversation("room-one")
    first = next(
        item for item in page["participants"] if item["participant_id"] == "participant-one"
    )
    second = next(
        item for item in page["participants"] if item["participant_id"] == "participant-two"
    )
    assert first["omitted_count"] == 1
    assert first["history_partial"] is True
    assert second["omitted_count"] == 0
    with sqlite3.connect(cache.path) as conn:
        row = conn.execute(
            """select count(*), min(participant_seq), max(participant_seq)
               from native_events where participant_id = 'participant-one'"""
        ).fetchone()
    assert row == (500, 2, 501)


def test_oldest_first_byte_trimming_uses_utf8_serialized_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_module, "MAX_EVENT_BYTES_PER_PARTICIPANT", 100)
    cache = RoomCodexProjectionCache(tmp_path)
    for index in range(5):
        _append(cache, index)

    with sqlite3.connect(cache.path) as conn:
        retained_count, retained_bytes = conn.execute(
            """select count(*), coalesce(sum(serialized_bytes), 0)
               from native_events where participant_id = 'participant-one'"""
        ).fetchone()
        omitted = conn.execute(
            """select omitted_count from participant_projection
               where participant_id = 'participant-one'"""
        ).fetchone()[0]
    assert 0 < retained_count < 5
    assert retained_bytes <= 100
    assert omitted == 5 - retained_count


def test_paginated_read_uses_cache_sequence_not_room_or_participant_sequence(
    tmp_path: Path,
) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    for index in range(5):
        _append(cache, index)

    latest = cache.read_conversation("room-one", limit=2)
    assert [event["participant_seq"] for event in latest["events"]] == [4, 5]
    assert latest["has_older"] is True
    assert latest["has_newer"] is False
    older = cache.read_conversation(
        "room-one", limit=2, before_event_seq=latest["next_before_event_seq"]
    )
    assert [event["participant_seq"] for event in older["events"]] == [2, 3]
    newer = cache.read_conversation(
        "room-one", limit=2, after_event_seq=older["next_after_event_seq"]
    )
    assert [event["participant_seq"] for event in newer["events"]] == [4, 5]
    with pytest.raises(RoomCodexProjectionCacheError) as raised:
        cache.read_conversation("room-one", before_event_seq=1, after_event_seq=1)
    assert raised.value.code == "codex_projection_cursor_conflict"


def test_missing_cache_is_an_honest_unavailable_partial_projection(tmp_path: Path) -> None:
    page = RoomCodexProjectionCache(tmp_path).read_conversation("room-one")
    assert page == {
        "schema_version": EVENT_CACHE_SCHEMA,
        "source": "codex_app_server_projection_cache",
        "projection_available": False,
        "proof_boundary": "codex_projection_not_room_or_native_authority",
        "conversation_id": "room-one",
        "participants": [],
        "events": [],
        "latest_event_seq": 0,
        "has_older": False,
        "has_newer": False,
        "next_before_event_seq": None,
        "next_after_event_seq": None,
    }
    assert not (tmp_path / "runtime").exists()


def test_deleted_cache_is_privately_rebuilt_and_marks_history_partial(tmp_path: Path) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    _append(cache, 1)
    cache.path.unlink()

    rebuilt = _append(cache, 2)
    page = cache.read_conversation("room-one")

    assert stat.S_IMODE(cache.path.stat().st_mode) == 0o600
    assert rebuilt["event_seq"] == 1
    assert rebuilt["participant_seq"] == 1
    assert page["participants"][0]["history_partial"] is True


def test_runtime_or_database_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    os.symlink(target, tmp_path / "runtime")
    with pytest.raises(RoomCodexProjectionCacheError) as runtime_error:
        RoomCodexProjectionCache(tmp_path).initialize()
    assert runtime_error.value.code == "codex_projection_runtime_symlink_rejected"
    with pytest.raises(RoomCodexProjectionCacheError) as runtime_read_error:
        RoomCodexProjectionCache(tmp_path).read_conversation("room-one")
    assert runtime_read_error.value.code == "codex_projection_runtime_symlink_rejected"

    root = tmp_path / "second"
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    outside = tmp_path / "outside.sqlite3"
    outside.touch()
    os.symlink(outside, runtime / "room-codex-projection.sqlite3")
    with pytest.raises(RoomCodexProjectionCacheError) as database_error:
        RoomCodexProjectionCache(root).initialize()
    assert database_error.value.code == "codex_projection_database_unsafe"


def test_future_schema_rejected_before_other_tables_are_created(tmp_path: Path) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    cache.path.parent.mkdir(parents=True)
    with sqlite3.connect(cache.path) as conn:
        conn.execute(
            "create table projection_meta(schema_version text primary key, created_at text)"
        )
        conn.execute("insert into projection_meta values ('room_codex_event_projection/v99', 'x')")
    with pytest.raises(RoomCodexProjectionCacheError) as raised:
        cache.initialize()
    assert raised.value.code == "codex_projection_schema_unsupported"
    with sqlite3.connect(cache.path) as conn:
        names = {
            row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")
        }
    assert "native_events" not in names


def test_concurrent_writers_keep_unique_participant_and_cache_sequences(tmp_path: Path) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: _append(cache, index), range(40)))
    with sqlite3.connect(cache.path) as conn:
        participant_sequences = [
            row[0]
            for row in conn.execute(
                """select participant_seq from native_events
                   where participant_id = 'participant-one' order by participant_seq"""
            )
        ]
        cache_sequences = [row[0] for row in conn.execute("select cache_seq from native_events")]
    assert participant_sequences == list(range(1, 41))
    assert len(cache_sequences) == len(set(cache_sequences)) == 40


def test_event_payload_has_hard_database_and_encoder_bound(tmp_path: Path) -> None:
    cache = RoomCodexProjectionCache(tmp_path)
    _append(cache, 1)
    with sqlite3.connect(cache.path) as conn:
        maximum = conn.execute("select max(serialized_bytes) from native_events").fetchone()[0]
        encoded = conn.execute("select payload_json from native_events").fetchone()[0]
    assert maximum == len(encoded.encode("utf-8"))
    assert maximum <= MAX_EVENT_BYTES
