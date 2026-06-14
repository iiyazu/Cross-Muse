from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from xmuse_core.chat.god_room_runtime import (
    GodRoomEventV1,
    GodRoomParticipant,
    GodRoomReplayResult,
    replay_god_room_turns,
)


class GodRoomStoreError(ValueError):
    pass


class GodRoomMembershipError(GodRoomStoreError):
    pass


class GodRoomEventConflictError(GodRoomStoreError):
    pass


@dataclass(frozen=True)
class GodRoomAppendResult:
    status: Literal["created", "duplicate"]
    event: GodRoomEventV1


@dataclass
class GodRoomSnapshot:
    room_id: str
    conversation_id: str
    participants: list[GodRoomParticipant]
    events: list[GodRoomEventV1]


class GodRoomEventStore:
    """Durable SQLite store for replayable GOD room event streams."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def ensure_room(
        self,
        *,
        room_id: str,
        conversation_id: str,
        participants: list[GodRoomParticipant] | tuple[GodRoomParticipant, ...] = (),
    ) -> GodRoomSnapshot:
        room_id = _require_non_empty(room_id, "room_id")
        conversation_id = _require_non_empty(conversation_id, "conversation_id")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select conversation_id from god_rooms where room_id = ?",
                (room_id,),
            ).fetchone()
            if row is not None and row["conversation_id"] != conversation_id:
                raise GodRoomMembershipError(
                    f"room {room_id} belongs to conversation {row['conversation_id']}, "
                    f"not {conversation_id}"
                )
            if row is None:
                conn.execute(
                    """
                    insert into god_rooms (room_id, conversation_id, created_at)
                    values (?, ?, ?)
                    """,
                    (room_id, conversation_id, now),
                )
            for participant in participants:
                self._insert_participant(
                    conn,
                    room_id=room_id,
                    participant=participant,
                    created_at=now,
                )
            conn.commit()
        return self.load_room(room_id)

    def append_event(self, event: GodRoomEventV1) -> GodRoomAppendResult:
        event_json = _event_json(event)
        idempotency_key = event.idempotency_key()
        with self._connect() as conn:
            conn.execute("begin immediate")
            room = conn.execute(
                "select conversation_id from god_rooms where room_id = ?",
                (event.room_id,),
            ).fetchone()
            if room is None:
                raise GodRoomMembershipError(f"room {event.room_id} does not exist")
            if room["conversation_id"] != event.conversation_id:
                raise GodRoomMembershipError(
                    f"room {event.room_id} belongs to conversation "
                    f"{room['conversation_id']}, not {event.conversation_id}"
                )
            participants = self._participants_by_id(conn, event.room_id)
            participant = participants.get(event.participant_id)
            if participant is None:
                raise GodRoomMembershipError(
                    f"participant {event.participant_id} is not in room {event.room_id}"
                )
            if participant.god_id != event.god_id:
                raise GodRoomMembershipError(
                    f"participant {event.participant_id} is bound to "
                    f"{participant.god_id}, not {event.god_id}"
                )
            for target_id in event.target_participant_ids:
                if target_id not in participants:
                    raise GodRoomMembershipError(
                        f"target participant {target_id} is not in room {event.room_id}"
                    )

            existing_event_id = conn.execute(
                """
                select event_json, stable_json from god_room_events
                where room_id = ? and event_id = ?
                """,
                (event.room_id, event.event_id),
            ).fetchone()
            if existing_event_id is not None:
                if existing_event_id["stable_json"] == event.stable_json():
                    conn.commit()
                    return GodRoomAppendResult(
                        status="duplicate",
                        event=_event_from_json(existing_event_id["event_json"]),
                    )
                raise GodRoomEventConflictError(
                    f"event_id {event.event_id} already exists with different content"
                )

            existing_idempotency = conn.execute(
                """
                select event_json from god_room_events
                where room_id = ? and idempotency_key = ?
                """,
                (event.room_id, idempotency_key),
            ).fetchone()
            if existing_idempotency is not None:
                conn.commit()
                return GodRoomAppendResult(
                    status="duplicate",
                    event=_event_from_json(existing_idempotency["event_json"]),
                )

            conn.execute(
                """
                insert into god_room_events (
                    room_id, event_id, idempotency_key, stable_json, event_json,
                    created_at
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.room_id,
                    event.event_id,
                    idempotency_key,
                    event.stable_json(),
                    event_json,
                    _utc_now(),
                ),
            )
            conn.commit()
        return GodRoomAppendResult(status="created", event=event)

    def load_room(self, room_id: str) -> GodRoomSnapshot:
        room_id = _require_non_empty(room_id, "room_id")
        with self._connect() as conn:
            room = conn.execute(
                "select room_id, conversation_id from god_rooms where room_id = ?",
                (room_id,),
            ).fetchone()
            if room is None:
                raise GodRoomMembershipError(f"room {room_id} does not exist")
            participant_rows = conn.execute(
                """
                select participant_json from god_room_participants
                where room_id = ?
                order by rowid asc
                """,
                (room_id,),
            ).fetchall()
            event_rows = conn.execute(
                """
                select event_json from god_room_events
                where room_id = ?
                order by sequence_id asc
                """,
                (room_id,),
            ).fetchall()
        return GodRoomSnapshot(
            room_id=room["room_id"],
            conversation_id=room["conversation_id"],
            participants=[
                GodRoomParticipant.model_validate(
                    json.loads(row["participant_json"])
                )
                for row in participant_rows
            ],
            events=[_event_from_json(row["event_json"]) for row in event_rows],
        )

    def replay_room(self, room_id: str) -> GodRoomReplayResult:
        snapshot = self.load_room(room_id)
        return replay_god_room_turns(
            participants=list(snapshot.participants),
            events=list(snapshot.events),
        )

    def build_room_snapshot_artifact(self, room_id: str) -> dict[str, object]:
        snapshot = self.load_room(room_id)
        replay = replay_god_room_turns(
            participants=snapshot.participants,
            events=snapshot.events,
        )
        return {
            "schema_version": "xmuse.god_room_snapshot.v1",
            "generated_at": _utc_now(),
            "source_authority": "god_room_event_store",
            "room_id": snapshot.room_id,
            "conversation_id": snapshot.conversation_id,
            "participants": [
                participant.model_dump(mode="json")
                for participant in snapshot.participants
            ],
            "events": [event.model_dump(mode="json") for event in snapshot.events],
            "replay": replay.model_dump(mode="json"),
        }

    def write_room_snapshot(
        self,
        room_id: str,
        output_path: str | Path,
    ) -> dict[str, object]:
        artifact = self.build_room_snapshot_artifact(room_id)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return artifact

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists god_rooms (
                    room_id text primary key,
                    conversation_id text not null,
                    created_at text not null
                );

                create table if not exists god_room_participants (
                    room_id text not null,
                    participant_id text not null,
                    participant_json text not null,
                    created_at text not null,
                    primary key (room_id, participant_id),
                    foreign key (room_id) references god_rooms(room_id)
                );

                create table if not exists god_room_events (
                    sequence_id integer primary key autoincrement,
                    room_id text not null,
                    event_id text not null,
                    idempotency_key text not null,
                    stable_json text not null,
                    event_json text not null,
                    created_at text not null,
                    unique (room_id, event_id),
                    unique (room_id, idempotency_key),
                    foreign key (room_id) references god_rooms(room_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _insert_participant(
        self,
        conn: sqlite3.Connection,
        *,
        room_id: str,
        participant: GodRoomParticipant,
        created_at: str,
    ) -> None:
        participant_json = _participant_json(participant)
        row = conn.execute(
            """
            select participant_json from god_room_participants
            where room_id = ? and participant_id = ?
            """,
            (room_id, participant.participant_id),
        ).fetchone()
        if row is not None:
            if row["participant_json"] != participant_json:
                raise GodRoomMembershipError(
                    f"participant {participant.participant_id} already exists with "
                    "different binding"
                )
            return
        conn.execute(
            """
            insert into god_room_participants (
                room_id, participant_id, participant_json, created_at
            )
            values (?, ?, ?, ?)
            """,
            (room_id, participant.participant_id, participant_json, created_at),
        )

    def _participants_by_id(
        self,
        conn: sqlite3.Connection,
        room_id: str,
    ) -> dict[str, GodRoomParticipant]:
        rows = conn.execute(
            """
            select participant_json from god_room_participants
            where room_id = ?
            """,
            (room_id,),
        ).fetchall()
        participants = [
            GodRoomParticipant.model_validate(json.loads(row["participant_json"]))
            for row in rows
        ]
        return {participant.participant_id: participant for participant in participants}


def _event_json(event: GodRoomEventV1) -> str:
    return json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def _participant_json(participant: GodRoomParticipant) -> str:
    return json.dumps(
        participant.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )


def _event_from_json(value: str) -> GodRoomEventV1:
    return GodRoomEventV1.model_validate(json.loads(value))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_non_empty(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must be non-empty")
    return value


__all__ = [
    "GodRoomAppendResult",
    "GodRoomEventConflictError",
    "GodRoomEventStore",
    "GodRoomMembershipError",
    "GodRoomSnapshot",
    "GodRoomStoreError",
]
