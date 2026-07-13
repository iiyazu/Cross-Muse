"""Tests for durable Room participant identity storage."""

from __future__ import annotations

import sqlite3
from hashlib import sha256
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_session_identity import (
    participant_session_prompt_fingerprint,
)
from xmuse_core.chat.participant_store import (
    INIT_GOD_DISPLAY_NAME,
    INIT_GOD_ROLE,
    ParticipantStore,
    PersonaSnapshot,
    prepare_participant,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Fresh chat.db with all tables created and predefined templates seeded."""
    path = tmp_path / "chat.db"
    RoomTestStore(path)
    return path


@pytest.fixture()
def conv_id(db_path: Path) -> str:
    """A conversation id that satisfies the FK constraint on participants."""
    return RoomTestStore(db_path).create_conversation("test-conv").id


# ---------------------------------------------------------------------------
# ParticipantStore
# ---------------------------------------------------------------------------


class TestParticipantStore:
    def test_persona_snapshot_is_bounded_persisted_and_fingerprinted(
        self, db_path: Path, conv_id: str
    ) -> None:
        persona = PersonaSnapshot(
            role_description="Reviews durable evidence.",
            collaboration_focus="Find distinct proof gaps without repeating peers.",
        )
        stored = ParticipantStore(db_path).add(
            conversation_id=conv_id,
            role="review",
            display_name="Reviewer",
            cli_kind="codex",
            model="gpt-5.4",
            persona_snapshot=persona,
        )

        fetched = ParticipantStore(db_path).get(stored.participant_id)
        assert fetched.persona_snapshot == persona
        assert fetched.persona_snapshot_sha256 is not None
        assert fetched.persona_snapshot_sha256.startswith("sha256:")
        without_persona = prepare_participant(
            conversation_id=conv_id,
            role="review",
            display_name="Reviewer",
            cli_kind="codex",
            model="gpt-5.4",
        )
        assert participant_session_prompt_fingerprint(
            fetched
        ) != participant_session_prompt_fingerprint(without_persona)
        legacy_prompt = "\n".join(
            [
                "xmuse-room-session-v1",
                "role=review",
                "display_name=Reviewer",
                "cli_kind=codex",
                f"model={without_persona.model}",
            ]
        )
        assert participant_session_prompt_fingerprint(without_persona) == (
            f"sha256:{sha256(legacy_prompt.encode('utf-8')).hexdigest()}"
        )

        with pytest.raises(ValueError, match="persona_snapshot_too_large"):
            PersonaSnapshot(
                role_description="x" * 2048,
                collaboration_focus="review",
            )

    def test_add_returns_participant_with_correct_fields(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        p = store.add(
            conversation_id=conv_id,
            role="architect",
            display_name="Architect GOD",
            cli_kind="codex",
            model="gpt-5.5",
        )
        assert p.participant_id.startswith("part_")
        assert p.conversation_id == conv_id
        assert p.role == "architect"
        assert p.display_name == "Architect GOD"
        assert p.provider_id == "codex"
        assert p.profile_id == "god"
        assert p.cli_kind == "codex"
        assert p.model == "gpt-5.4"
        assert p.role_template_id is None
        assert p.status == "active"
        assert p.last_seen_at is None
        assert p.created_at

    def test_add_rejects_retired_a2a_participant(
        self,
        db_path: Path,
        conv_id: str,
    ) -> None:
        store = ParticipantStore(db_path)

        with pytest.raises(ValueError, match="support only cli_kind 'codex'"):
            store.add(
                conversation_id=conv_id,
                role="review",
                display_name="Remote A2A Review",
                cli_kind="a2a",  # type: ignore[arg-type]
                model="a2a-remote",
            )

    @pytest.mark.parametrize("cli_kind", ["a2a", "opencode"])
    def test_retired_participant_rows_are_readable_but_cannot_be_reactivated(
        self,
        db_path: Path,
        conv_id: str,
        cli_kind: str,
    ) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                insert into participants (
                    participant_id, conversation_id, role, display_name,
                    cli_kind, model, role_template_id, status,
                    last_seen_at, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"part_historical_{cli_kind}",
                    conv_id,
                    "review",
                    f"Historical {cli_kind}",
                    cli_kind,
                    "historical-model",
                    None,
                    "stopped",
                    None,
                    "2026-05-29T00:00:00Z",
                ),
            )

        store = ParticipantStore(db_path)
        historical = store.get(f"part_historical_{cli_kind}")
        assert historical.cli_kind == cli_kind
        assert historical.provider_id == cli_kind
        assert historical in store.list_by_conversation(conv_id)
        with pytest.raises(ValueError, match="support only cli_kind 'codex'"):
            store.update_status(historical.participant_id, "active")
        assert store.get(historical.participant_id).status == "stopped"

    def test_add_with_role_template_id(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        p = store.add(
            conversation_id=conv_id,
            role="review",
            display_name="Review GOD",
            cli_kind="codex",
            model="gpt-5.5",
            role_template_id="tmpl_abc123",
        )
        assert p.role_template_id == "tmpl_abc123"

    def test_get_returns_persisted_participant(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        added = store.add(
            conversation_id=conv_id,
            role="execute",
            display_name="Execute GOD",
            cli_kind="codex",
            model="gpt-4o",
        )
        fetched = store.get(added.participant_id)
        assert fetched.participant_id == added.participant_id
        assert fetched.role == "execute"
        assert fetched.cli_kind == "codex"

    def test_get_raises_key_error_for_unknown(self, db_path: Path) -> None:
        store = ParticipantStore(db_path)
        with pytest.raises(KeyError, match="unknown participant"):
            store.get("part_does_not_exist")

    def test_list_by_conversation_returns_only_matching(self, db_path: Path) -> None:
        chat = RoomTestStore(db_path)
        conv1 = chat.create_conversation("conv-1")
        conv2 = chat.create_conversation("conv-2")
        store = ParticipantStore(db_path)

        p1 = store.add(
            conversation_id=conv1.id,
            role="architect",
            display_name="A",
            cli_kind="codex",
            model="gpt-5.5",
        )
        p2 = store.add(
            conversation_id=conv1.id,
            role="review",
            display_name="R",
            cli_kind="codex",
            model="gpt-5.5",
        )
        store.add(
            conversation_id=conv2.id,
            role="execute",
            display_name="E",
            cli_kind="codex",
            model="gpt-4o",
        )

        result = store.list_by_conversation(conv1.id)
        ids = {p.participant_id for p in result}
        assert p1.participant_id in ids
        assert p2.participant_id in ids
        assert len(result) == 2

    def test_list_by_conversation_empty_when_none_added(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        assert store.list_by_conversation(conv_id) == []

    def test_update_status_to_stopped(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        p = store.add(
            conversation_id=conv_id,
            role="architect",
            display_name="A",
            cli_kind="codex",
            model="gpt-5.5",
        )
        updated = store.update_status(p.participant_id, "stopped")
        assert updated.status == "stopped"
        assert updated.last_seen_at is not None

    def test_update_status_with_explicit_last_seen_at(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        p = store.add(
            conversation_id=conv_id,
            role="architect",
            display_name="A",
            cli_kind="codex",
            model="gpt-5.5",
        )
        ts = "2026-05-28T10:00:00Z"
        updated = store.update_status(p.participant_id, "stopped", last_seen_at=ts)
        assert updated.last_seen_at == ts

    def test_update_status_back_to_active(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        p = store.add(
            conversation_id=conv_id,
            role="architect",
            display_name="A",
            cli_kind="codex",
            model="gpt-5.5",
        )
        store.update_status(p.participant_id, "stopped")
        updated = store.update_status(p.participant_id, "active")
        assert updated.status == "active"

    def test_delete_removes_participant(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)
        p = store.add(
            conversation_id=conv_id,
            role="architect",
            display_name="A",
            cli_kind="codex",
            model="gpt-5.5",
        )
        store.delete(p.participant_id)
        with pytest.raises(KeyError):
            store.get(p.participant_id)

    def test_delete_nonexistent_is_silent(self, db_path: Path) -> None:
        store = ParticipantStore(db_path)
        # Should not raise
        store.delete("part_nonexistent")

    def test_add_rejects_claude_cli_kind(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)

        with pytest.raises(ValueError, match="unsupported xmuse chat participant cli_kind"):
            store.add(
                conversation_id=conv_id,
                role="architect",
                display_name="Architect GOD",
                cli_kind="claude",
                model="sonnet",
            )

    def test_add_rejects_opencode_cli_kind(self, db_path: Path, conv_id: str) -> None:
        store = ParticipantStore(db_path)

        with pytest.raises(ValueError, match="support only cli_kind 'codex'"):
            store.add(
                conversation_id=conv_id,
                role="review",
                display_name="OpenCode Review",
                cli_kind="opencode",
                model="gpt-oss",
            )

    def test_ensure_init_god_reuses_same_participant_per_conversation(
        self,
        db_path: Path,
    ) -> None:
        chat = RoomTestStore(db_path)
        first_conv = chat.create_conversation("first")
        second_conv = chat.create_conversation("second")
        store = ParticipantStore(db_path)

        first = store.ensure_init_god(conversation_id=first_conv.id, model="gpt-5.5")
        second = store.ensure_init_god(conversation_id=first_conv.id, model="gpt-5.5")
        third = store.ensure_init_god(conversation_id=second_conv.id, model="gpt-5.5")

        assert first.participant_id == second.participant_id
        assert third.participant_id != first.participant_id
        assert first.role == INIT_GOD_ROLE
        assert first.display_name == INIT_GOD_DISPLAY_NAME
        assert len(store.list_by_conversation(first_conv.id)) == 1
        assert len(store.list_by_conversation(second_conv.id)) == 1

    def test_add_rejects_duplicate_init_god_for_same_conversation(
        self,
        db_path: Path,
        conv_id: str,
    ) -> None:
        store = ParticipantStore(db_path)
        store.add(
            conversation_id=conv_id,
            role=INIT_GOD_ROLE,
            display_name=INIT_GOD_DISPLAY_NAME,
            cli_kind="codex",
            model="gpt-5.5",
        )

        with pytest.raises(ValueError, match="duplicate init god participant"):
            store.add(
                conversation_id=conv_id,
                role=INIT_GOD_ROLE,
                display_name="other-init-god",
                cli_kind="codex",
                model="gpt-5.5",
            )

    def test_unknown_legacy_participant_cli_kind_is_rejected(
        self, db_path: Path, conv_id: str
    ) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                insert into participants (
                    participant_id, conversation_id, role, display_name,
                    cli_kind, model, role_template_id, status,
                    last_seen_at, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "part_legacy",
                    conv_id,
                    "architect",
                    "Architect GOD",
                    "claude",
                    "sonnet",
                    None,
                    "active",
                    None,
                    "2026-05-29T00:00:00Z",
                ),
            )

        with pytest.raises(ValueError, match="unsupported stored xmuse chat participant"):
            ParticipantStore(db_path).get("part_legacy")

    def test_legacy_codex_gpt54_participant_reads_as_gpt54(
        self, db_path: Path, conv_id: str
    ) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                insert into participants (
                    participant_id, conversation_id, role, display_name,
                    cli_kind, model, role_template_id, status,
                    last_seen_at, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "part_legacy_codex",
                    conv_id,
                    "architect",
                    "Architect GOD",
                    "codex",
                    "gpt-5.4",
                    None,
                    "active",
                    None,
                    "2026-05-29T00:00:00Z",
                ),
            )

        participant = ParticipantStore(db_path).get("part_legacy_codex")

        assert participant.cli_kind == "codex"
        assert participant.model == "gpt-5.4"

    def test_legacy_codex_gpt55_participant_reads_as_ordinary_model(
        self, db_path: Path, conv_id: str
    ) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                insert into participants (
                    participant_id, conversation_id, role, display_name,
                    cli_kind, model, role_template_id, status,
                    last_seen_at, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "part_legacy_codex_gpt55",
                    conv_id,
                    "review",
                    "Legacy Review",
                    "codex",
                    "gpt-5.5",
                    None,
                    "active",
                    None,
                    "2026-05-29T00:00:00Z",
                ),
            )

        participant = ParticipantStore(db_path).get("part_legacy_codex_gpt55")

        assert participant.cli_kind == "codex"
        assert participant.model == "gpt-5.4"
