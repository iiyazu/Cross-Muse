from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_agent_stream import (
    MAX_PREVIEW_BYTES,
    RoomAgentStreamCache,
    RoomAgentStreamProjector,
    build_room_agent_stream_projection,
    sanitize_stream_preview,
)
from xmuse_core.chat.room_database import RoomDatabase


def test_stream_sanitizer_withholds_split_sensitive_suffix() -> None:
    partial, _ = sanitize_stream_preview("answer sk-secret", final=False)
    final, _ = sanitize_stream_preview(
        "answer sk-secretvalue /home/user/private.txt\nnext", final=True
    )

    assert partial == "answer "
    assert "secretvalue" not in final
    assert "/home/user" not in final
    assert final == "answer [redacted] [path]\nnext"


def test_stream_sanitizer_bounds_utf8() -> None:
    preview, truncated = sanitize_stream_preview("界" * MAX_PREVIEW_BYTES, final=True)

    assert truncated is True
    assert len(preview.encode()) <= MAX_PREVIEW_BYTES


def test_stream_cache_is_private_and_resets_epoch(tmp_path: Path) -> None:
    cache = RoomAgentStreamCache(tmp_path)
    cache.initialize_boot("opaque-one")
    cache.open_stream(
        stream_id="stream-1",
        conversation_id="room-1",
        participant_id="participant-1",
        observation_id="observation-1",
        attempt_id="attempt-1",
        started_at="2026-07-14T00:00:00.000Z",
    )
    cache.update_stream(
        "stream-1",
        state="streaming",
        content="safe preview",
        truncated=False,
    )

    first = cache.read_raw("room-1")
    assert first["epoch"] == "opaque-one"
    assert first["streams"][0]["content"] == "safe preview"
    assert os.stat(cache.path).st_mode & 0o077 == 0

    cache.initialize_boot("opaque-two")
    second = cache.read_raw("room-1")
    assert second["epoch"] == "opaque-two"
    assert second["streams"] == []


def test_stream_cache_prunes_closed_tombstones_and_advances_cursor(tmp_path: Path) -> None:
    cache = RoomAgentStreamCache(tmp_path)
    cache.initialize_boot("opaque")
    cache.open_stream(
        stream_id="stream-1",
        conversation_id="room-1",
        participant_id="participant-1",
        observation_id="observation-1",
        attempt_id="attempt-1",
        started_at="2026-07-14T00:00:00.000Z",
    )
    cache.update_stream("stream-1", state="resolved", content="done", truncated=False, closed=True)
    before = cache.read_raw("room-1")["stream_seq"]

    future = (datetime.now(UTC) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    assert cache.prune_tombstones(now=future) is True

    after = cache.read_raw("room-1")
    assert after["streams"] == []
    assert after["stream_seq"] == before + 1


def test_projector_coalesces_and_freezes_at_committing(tmp_path: Path) -> None:
    async def exercise() -> dict[str, object]:
        cache = RoomAgentStreamCache(tmp_path)
        projector = RoomAgentStreamProjector(cache, epoch="opaque")
        stream_id = await projector.open_stream(
            conversation_id="room-1",
            participant_id="participant-1",
            observation_id="observation-1",
            attempt_id="attempt-1",
        )
        assert stream_id is not None
        projector.feed_delta(stream_id, "first ")
        projector.feed_delta(stream_id, "second ")
        await asyncio.sleep(0.15)
        await projector.committing(stream_id)
        projector.feed_delta(stream_id, "diagnostic must not appear")
        await projector.resolve(stream_id)
        await asyncio.sleep(0.05)
        await projector.shutdown()
        return cache.read_raw("room-1")

    result = asyncio.run(exercise())
    stream = result["streams"][0]
    assert stream["state"] == "resolved"
    assert stream["content"] == "first second "
    assert "diagnostic" not in stream["content"]


def test_projector_does_not_write_unchanged_snapshots(tmp_path: Path) -> None:
    async def exercise() -> tuple[int, int, int]:
        cache = RoomAgentStreamCache(tmp_path)
        projector = RoomAgentStreamProjector(cache, epoch="opaque")
        stream_id = await projector.open_stream(
            conversation_id="room-1",
            participant_id="participant-1",
            observation_id="observation-1",
            attempt_id="attempt-1",
        )
        assert stream_id is not None
        await asyncio.sleep(0.25)
        after_open = cache.read_raw("room-1")["stream_seq"]
        projector.feed_delta(stream_id, "one ")
        await asyncio.sleep(0.2)
        after_delta = cache.read_raw("room-1")["stream_seq"]
        await asyncio.sleep(0.25)
        after_idle = cache.read_raw("room-1")["stream_seq"]
        await projector.shutdown()
        return after_open, after_delta, after_idle

    after_open, after_delta, after_idle = asyncio.run(exercise())
    assert after_open == 1
    assert after_delta == 2
    assert after_idle == after_delta


def test_projector_failure_best_effort_invalidates_open_streams(tmp_path: Path) -> None:
    class FailOnceCache(RoomAgentStreamCache):
        fail_next_update = False

        def update_stream(self, *args: object, **kwargs: object) -> None:
            if self.fail_next_update:
                self.fail_next_update = False
                raise OSError("injected writer failure")
            super().update_stream(*args, **kwargs)  # type: ignore[arg-type]

    async def exercise() -> tuple[bool, dict[str, object]]:
        cache = FailOnceCache(tmp_path)
        projector = RoomAgentStreamProjector(cache, epoch="opaque")
        stream_id = await projector.open_stream(
            conversation_id="room-1",
            participant_id="participant-1",
            observation_id="observation-1",
            attempt_id="attempt-1",
        )
        assert stream_id is not None
        await asyncio.sleep(0.05)
        cache.fail_next_update = True
        projector.feed_delta(stream_id, "visible prefix ")
        await asyncio.sleep(0.2)
        await projector.shutdown()
        return projector.failed, cache.read_raw("room-1")

    failed, result = asyncio.run(exercise())
    assert failed is True
    assert result["streams"][0]["state"] == "invalidated"
    assert result["streams"][0]["content"] == "visible prefix "


def test_projection_reproves_attempt_and_durable_resolution(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    room = RoomTestStore(db_path).create_conversation("Room")
    participant = ParticipantStore(db_path).add(
        conversation_id=room.id,
        role="review",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    with RoomDatabase(db_path).connect() as conn:
        conn.execute(
            """insert into room_activities(
                   activity_id, conversation_id, seq, activity_type, actor_kind,
                   actor_identity, actor_participant_id, causation_id, correlation_id,
                   visibility, audience_json, causal_depth, payload_json, delivery_mode,
                   created_at
                   ) values ('activity-1', ?, 1, 'message.posted', 'human', 'human', null,
                         'activity-1', 'correlation-1', 'room', '[]', 0, '{}', 'active',
                         '2026-07-14T00:00:00Z')""",
            (room.id,),
        )
        conn.execute(
            """insert into room_observations(
                   observation_id, conversation_id, activity_id, participant_id, priority,
                   delivery_mode, status, attempt_count, outcome_type, created_at, updated_at,
                   control_state, control_seq, manual_retry_budget
                   ) values ('observation-1', ?, 'activity-1', ?, 0, 'active',
                         'completed', 1, 'noop', '2026-07-14T00:00:00Z',
                         '2026-07-14T00:00:00Z', 'active', 0, 0)""",
            (room.id, participant.participant_id),
        )
        conn.execute(
            """insert into room_observation_attempts(
                   attempt_id, conversation_id, observation_id, participant_id,
                   attempt_number, effective_attempt_limit, delivery_generation,
                   lease_owner, lease_token_digest, state, provider_phase,
                   runner_generation, runner_boot_id, claimed_at, expires_at,
                   created_at, updated_at
               ) values ('attempt-1', ?, 'observation-1', ?, 1, 3, 1,
                         'runner', 'sha256:lease', 'completed', 'bound', 'generation', 'boot',
                         '2026-07-14T00:00:00Z', '2026-07-14T00:10:00Z',
                         '2026-07-14T00:00:00Z', '2026-07-14T00:00:00Z')""",
            (room.id, participant.participant_id),
        )
        conn.execute(
            "update room_observations set current_attempt_id = 'attempt-1' "
            "where observation_id = 'observation-1'"
        )

    cache = RoomAgentStreamCache(tmp_path)
    cache.initialize_boot("opaque")
    cache.open_stream(
        stream_id="stream-1",
        conversation_id=room.id,
        participant_id=participant.participant_id,
        observation_id="observation-1",
        attempt_id="attempt-1",
        started_at="2026-07-14T00:00:00.000Z",
    )
    cache.update_stream(
        "stream-1", state="resolved", content="preview", truncated=False, closed=True
    )

    projection = build_room_agent_stream_projection(tmp_path, room.id)
    assert projection["streams"][0]["state"] == "resolved"
    assert projection["streams"][0]["resolution"] == {
        "outcome_type": "noop",
        "produced_activity_id": None,
    }
    assert "attempt_id" not in projection["streams"][0]


def test_projection_invalidates_cancelled_and_expired_attempts(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    room = RoomTestStore(db_path).create_conversation("Room")
    participant = ParticipantStore(db_path).add(
        conversation_id=room.id,
        role="review",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    with RoomDatabase(db_path).connect() as conn:
        conn.execute(
            """insert into room_activities(
                   activity_id, conversation_id, seq, activity_type, actor_kind,
                   actor_identity, causation_id, correlation_id, visibility,
                   audience_json, causal_depth, payload_json, delivery_mode, created_at
               ) values ('activity-1', ?, 1, 'message.posted', 'human', 'human',
                         'activity-1', 'correlation-1', 'room', '[]', 0, '{}', 'active', ?)""",
            (room.id, future),
        )
        conn.execute(
            """insert into room_observations(
                   observation_id, conversation_id, activity_id, participant_id, priority,
                   delivery_mode, status, lease_owner, lease_token, acquired_at, expires_at,
                   attempt_count, created_at, updated_at, control_state, control_seq,
                   manual_retry_budget, current_attempt_id
               ) values ('observation-1', ?, 'activity-1', ?, 0, 'active', 'claimed',
                         'runner', 'lease', ?, ?, 1, ?, ?, 'active', 0, 0, 'attempt-1')""",
            (room.id, participant.participant_id, future, future, future, future),
        )
        conn.execute(
            """insert into room_observation_attempts(
                   attempt_id, conversation_id, observation_id, participant_id,
                   attempt_number, effective_attempt_limit, delivery_generation, state,
                   lease_owner, lease_token_digest, provider_phase, recovery_state,
                   claimed_at, expires_at, created_at, updated_at
               ) values ('attempt-1', ?, 'observation-1', ?, 1, 3, 1, 'delivering',
                         'runner', 'sha256:lease', 'bound', 'none', ?, ?, ?, ?)""",
            (room.id, participant.participant_id, future, future, future, future),
        )

    cache = RoomAgentStreamCache(tmp_path)
    cache.initialize_boot("opaque")
    cache.open_stream(
        stream_id="stream-1",
        conversation_id=room.id,
        participant_id=participant.participant_id,
        observation_id="observation-1",
        attempt_id="attempt-1",
        started_at=future,
    )
    assert build_room_agent_stream_projection(tmp_path, room.id)["streams"][0]["state"] == (
        "streaming"
    )

    with RoomDatabase(db_path).connect() as conn:
        conn.execute(
            "update room_observations set control_state = 'cancel_pending' "
            "where observation_id = 'observation-1'"
        )
    assert build_room_agent_stream_projection(tmp_path, room.id)["streams"][0]["state"] == (
        "invalidated"
    )

    with RoomDatabase(db_path).connect() as conn:
        conn.execute(
            "update room_observations set control_state = 'active', expires_at = ? "
            "where observation_id = 'observation-1'",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),),
        )
    assert build_room_agent_stream_projection(tmp_path, room.id)["streams"][0]["state"] == (
        "invalidated"
    )
