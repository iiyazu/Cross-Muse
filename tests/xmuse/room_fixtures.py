"""Small Room-native data builders shared by surviving backend tests."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.chat.room_database import (
    COMPAT_CHAT_SCHEMA_ID,
    COMPAT_CHAT_SCHEMA_VERSION,
    RoomDatabase,
)


def _stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class TestConversation:
    id: str
    title: str
    created_at: str


@dataclass(frozen=True)
class TestMessage:
    id: str
    conversation_id: str
    author: str
    role: str
    content: str
    created_at: str


class RoomTestStore:
    """Build only current Room authority; it is not a production store."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        RoomDatabase(self.path).initialize()

    def create_conversation(self, title: str) -> TestConversation:
        conversation = TestConversation(f"conv_{uuid.uuid4().hex}", title, _stamp())
        with RoomDatabase(self.path).connect() as conn:
            conn.execute(
                "insert into conversations(id, title, created_at) values (?, ?, ?)",
                (conversation.id, conversation.title, conversation.created_at),
            )
        return conversation

    def list_conversations(self) -> list[TestConversation]:
        with RoomDatabase(self.path).connect(readonly=True) as conn:
            rows = conn.execute(
                "select id, title, created_at from conversations order by created_at, id"
            ).fetchall()
        return [TestConversation(row["id"], row["title"], row["created_at"]) for row in rows]

    def add_message(
        self,
        conversation_id: str,
        author: str,
        role: str,
        content: str,
    ) -> TestMessage:
        message = TestMessage(
            f"msg_{uuid.uuid4().hex}",
            conversation_id,
            author,
            role,
            content,
            _stamp(),
        )
        with RoomDatabase(self.path).connect() as conn:
            conn.execute(
                """insert into messages(
                       id, conversation_id, author, role, content, created_at,
                       envelope_type, envelope_json, mentions_json, reply_to_message_id
                   ) values (?, ?, ?, ?, ?, ?, 'message', '{}', '[]', null)""",
                (
                    message.id,
                    message.conversation_id,
                    message.author,
                    message.role,
                    message.content,
                    message.created_at,
                ),
            )
        return message

    def list_messages(self, conversation_id: str) -> list[TestMessage]:
        with RoomDatabase(self.path).connect(readonly=True) as conn:
            rows = conn.execute(
                """select id, conversation_id, author, role, content, created_at
                   from messages where conversation_id = ? order by rowid""",
                (conversation_id,),
            ).fetchall()
        return [
            TestMessage(
                row["id"],
                row["conversation_id"],
                row["author"],
                row["role"],
                row["content"],
                row["created_at"],
            )
            for row in rows
        ]

    def list_frontend_events(self, conversation_id: str) -> list[dict[str, object]]:
        with RoomDatabase(self.path).connect(readonly=True) as conn:
            rows = conn.execute(
                "select * from chat_frontend_events where conversation_id = ? order by seq",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class CompatDataTestStore(RoomTestStore):
    """Materialize the narrow historical data variant accepted by xmuse-data."""

    def __init__(self, path: Path | str) -> None:
        super().__init__(path)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """create table if not exists role_templates (
                       id text primary key, slug text not null, display_name text not null,
                       prompt text not null, cli_kind text not null, default_model text not null,
                       predefined integer not null, created_at text not null,
                       updated_at text not null
                   )"""
            )
            conn.execute(
                """create table if not exists schema_migrations (
                       version integer primary key, applied_at text not null
                   )"""
            )
            conn.execute(
                """insert into chat_schema_meta(schema_id, version, updated_at)
                   values (?, ?, ?)
                   on conflict(schema_id) do update set version = excluded.version,
                                                        updated_at = excluded.updated_at""",
                (COMPAT_CHAT_SCHEMA_ID, COMPAT_CHAT_SCHEMA_VERSION, _stamp()),
            )
            conn.execute(
                "insert or ignore into schema_migrations(version, applied_at) values (?, ?)",
                (COMPAT_CHAT_SCHEMA_VERSION, _stamp()),
            )
