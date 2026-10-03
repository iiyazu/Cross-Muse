"""workspace_write participant attribute: storage, setup, and projection hiding."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from hashlib import sha256
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_session_identity import (
    participant_session_prompt_fingerprint,
)
from xmuse_core.chat.participant_store import (
    ParticipantStore,
    prepare_participant,
    provider_id_for_cli_kind,
)
from xmuse_core.chat.room_api_models import ParticipantInit, RoomConversationCreate
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_projection import (
    build_room_chat_projection,
    build_room_list_projection,
)
from xmuse_core.chat.room_setup import (
    RoomSetupError,
    RoomSetupService,
    _request_fingerprint,
)
from xmuse_core.chat.roster_templates import (
    RosterRoleBinding,
    RosterTemplate,
    WorkroomRosterTemplateStore,
    builtin_workroom_catalog,
    template_to_participant_inits,
    validate_roster_template,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "chat.db"
    RoomTestStore(path)
    return path


@pytest.fixture()
def conv_id(db_path: Path) -> str:
    return RoomTestStore(db_path).create_conversation("writer-conv").id


def _raw_workspace_access(db_path: Path, participant_id: str) -> object:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "select workspace_access from participants where participant_id = ?",
            (participant_id,),
        ).fetchone()
    assert row is not None
    return row["workspace_access"]


class TestWorkspaceAccessStorage:
    def test_default_is_read_only(self, db_path: Path, conv_id: str) -> None:
        stored = ParticipantStore(db_path).add(
            conversation_id=conv_id,
            role="review",
            display_name="Reviewer",
            cli_kind="codex",
            model="gpt-5.4",
        )
        assert stored.workspace_access == "read_only"
        assert ParticipantStore(db_path).get(stored.participant_id).workspace_access == (
            "read_only"
        )

    def test_writer_round_trip(self, db_path: Path, conv_id: str) -> None:
        stored = ParticipantStore(db_path).add(
            conversation_id=conv_id,
            role="research",
            display_name="Researcher",
            cli_kind="claude",
            model="claude-opus-4-6",
            workspace_access="workspace_write",
        )
        assert stored.workspace_access == "workspace_write"
        fetched = ParticipantStore(db_path).get(stored.participant_id)
        assert fetched.workspace_access == "workspace_write"

    def test_read_only_rows_store_null(self, db_path: Path, conv_id: str) -> None:
        stored = ParticipantStore(db_path).add(
            conversation_id=conv_id,
            role="review",
            display_name="Reviewer",
            cli_kind="codex",
            model="gpt-5.4",
        )
        assert _raw_workspace_access(db_path, stored.participant_id) is None

    def test_writer_rows_store_value(self, db_path: Path, conv_id: str) -> None:
        stored = ParticipantStore(db_path).add(
            conversation_id=conv_id,
            role="research",
            display_name="Researcher",
            cli_kind="claude",
            model="claude-opus-4-6",
            workspace_access="workspace_write",
        )
        assert _raw_workspace_access(db_path, stored.participant_id) == "workspace_write"

    def test_old_database_without_column_migrates_to_read_only(self, tmp_path: Path) -> None:
        path = tmp_path / "old-chat.db"
        with sqlite3.connect(path) as conn:
            conn.execute(
                """create table conversations (
                       id text primary key, title text not null, created_at text not null
                   )"""
            )
            conn.execute(
                """create table participants (
                       participant_id text primary key,
                       conversation_id text not null references conversations(id),
                       role text not null,
                       display_name text not null,
                       cli_kind text not null,
                       model text not null,
                       role_template_id text,
                       status text not null,
                       last_seen_at text,
                       persona_snapshot_json text,
                       persona_snapshot_sha256 text,
                       created_at text not null
                   )"""
            )
            conn.execute(
                "insert into conversations(id, title, created_at) values (?, ?, ?)",
                ("conv_old", "old", "2026-01-01T00:00:00Z"),
            )
            conn.execute(
                """insert into participants(
                       participant_id, conversation_id, role, display_name, cli_kind,
                       model, role_template_id, status, last_seen_at,
                       persona_snapshot_json, persona_snapshot_sha256, created_at
                   ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "part_old",
                    "conv_old",
                    "review",
                    "Reviewer",
                    "codex",
                    "gpt-5.4",
                    None,
                    "active",
                    None,
                    None,
                    None,
                    "2026-01-01T00:00:00Z",
                ),
            )
        RoomDatabase(path).initialize()
        fetched = ParticipantStore(path).get("part_old")
        assert fetched.workspace_access == "read_only"


class TestWorkspaceAccessSetup:
    @staticmethod
    def _service(tmp_path: Path) -> RoomSetupService:
        RoomDatabase(tmp_path / "chat.db").initialize()
        return RoomSetupService(tmp_path)

    def test_accepted_for_claude_and_opencode(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        result = service.create_conversation(
            RoomConversationCreate(
                title="writers",
                client_request_id="writers-1",
                initial_participants=[
                    ParticipantInit(
                        role="research",
                        cli_kind="claude",
                        model="m",
                        workspace_access="workspace_write",
                    ),
                    ParticipantInit(
                        role="review",
                        cli_kind="opencode",
                        model="m",
                        workspace_access="workspace_write",
                    ),
                ],
            )
        )
        participants = result["participants"]
        assert isinstance(participants, list) and len(participants) == 2
        assert ParticipantStore(tmp_path / "chat.db").list_by_conversation(str(result["id"]))[
            0
        ].workspace_access == ("workspace_write")

    @pytest.mark.parametrize("cli_kind", ["codex", "antigravity"])
    def test_rejected_for_other_kinds(self, tmp_path: Path, cli_kind: str) -> None:
        service = self._service(tmp_path)
        with pytest.raises(RoomSetupError) as exc_info:
            service.create_conversation(
                RoomConversationCreate(
                    title="writers",
                    client_request_id=f"writers-{cli_kind}",
                    initial_participants=[
                        ParticipantInit(
                            role="review",
                            cli_kind=cli_kind,  # type: ignore[arg-type]
                            model="m",
                            workspace_access="workspace_write",
                        ),
                    ],
                )
            )
        assert exc_info.value.code == "room_participant_workspace_access_unsupported"

    def test_roster_binding_passes_through(self, tmp_path: Path) -> None:
        catalog = builtin_workroom_catalog()
        template = RosterTemplate(
            template_id="custom.writers",
            display_name="Writers",
            description="Claude writer plus codex reviewer.",
            roles=(
                RosterRoleBinding(
                    role_id="product_lead",
                    provider_profile_ref="claude.default",
                    workspace_access="workspace_write",
                ),
                RosterRoleBinding(
                    role_id="reviewer",
                    provider_profile_ref="codex.review",
                ),
            ),
        )
        validated = validate_roster_template(template, catalog=catalog)
        assert validated.roles[0].workspace_access == "workspace_write"
        assert validated.roles[1].workspace_access is None
        inits = template_to_participant_inits(validated, catalog=catalog)
        assert inits[0].workspace_access == "workspace_write"
        assert inits[1].workspace_access is None

        stored = WorkroomRosterTemplateStore(tmp_path / "workroom_roster_templates.json").save(
            template, catalog=catalog
        )
        assert stored.roles[0].workspace_access == "workspace_write"
        service = self._service(tmp_path)
        result = service.create_conversation(
            RoomConversationCreate(
                title="roster writers",
                client_request_id="roster-writers-1",
                roster_template_id="custom.writers",
            )
        )
        assert isinstance(result["participants"], list) and len(result["participants"]) == 2
        fetched = ParticipantStore(tmp_path / "chat.db").list_by_conversation(str(result["id"]))
        assert [item.workspace_access for item in fetched] == ["workspace_write", "read_only"]

    def test_read_only_request_fingerprint_is_stable(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        request = RoomConversationCreate(
            title="stable",
            client_request_id="stable-1",
            initial_participants=[
                ParticipantInit(role="review", cli_kind="codex", model="gpt-5.4"),
            ],
        )
        specs = [
            service._normalize_participant(item)
            for item in service._requested_participants(request)[0]
        ]
        fingerprint = _request_fingerprint(
            title=request.title,
            roster_template_id=None,
            specs=specs,
            collaboration=None,
        )
        legacy_payload = {
            "title": "stable",
            "roster_template_id": None,
            "participants": [
                {
                    "role": "review",
                    "display_name": "Review",
                    "model": "gpt-5.4",
                    "role_template_id": None,
                    "persona_snapshot": None,
                    "provider_id": str(provider_id_for_cli_kind("codex")),
                    "cli_kind": "codex",
                }
            ],
        }
        expected = hashlib.sha256(
            json.dumps(
                legacy_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        assert fingerprint == expected

        writer_request = RoomConversationCreate(
            title="stable",
            client_request_id="stable-2",
            initial_participants=[
                ParticipantInit(
                    role="research",
                    cli_kind="claude",
                    model="m",
                    workspace_access="workspace_write",
                ),
            ],
        )
        writer_specs = [
            service._normalize_participant(item)
            for item in service._requested_participants(writer_request)[0]
        ]
        writer_fingerprint = _request_fingerprint(
            title=writer_request.title,
            roster_template_id=None,
            specs=writer_specs,
            collaboration=None,
        )
        assert writer_fingerprint != fingerprint

    def test_session_prompt_fingerprint_ignores_workspace_access(self, conv_id: str) -> None:
        reader = prepare_participant(
            conversation_id=conv_id,
            role="research",
            display_name="Researcher",
            cli_kind="claude",
            model="m",
        )
        writer = prepare_participant(
            conversation_id=conv_id,
            role="research",
            display_name="Researcher",
            cli_kind="claude",
            model="m",
            workspace_access="workspace_write",
        )
        assert participant_session_prompt_fingerprint(writer) == (
            participant_session_prompt_fingerprint(reader)
        )

    def test_setup_response_hides_field_for_read_only(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        result = service.create_conversation(
            RoomConversationCreate(
                title="mixed",
                client_request_id="mixed-1",
                initial_participants=[
                    ParticipantInit(role="review", cli_kind="codex", model="gpt-5.4"),
                    ParticipantInit(
                        role="research",
                        cli_kind="claude",
                        model="m",
                        workspace_access="workspace_write",
                    ),
                ],
            )
        )
        participants = result["participants"]
        assert isinstance(participants, list)
        by_role = {item["role"]: item for item in participants}
        assert "workspace_access" not in by_role["review"]
        assert by_role["research"]["workspace_access"] == "workspace_write"

    def test_projections_hide_workspace_access(self, tmp_path: Path) -> None:
        service = self._service(tmp_path)
        result = service.create_conversation(
            RoomConversationCreate(
                title="projected",
                client_request_id="projected-1",
                initial_participants=[
                    ParticipantInit(role="review", cli_kind="codex", model="gpt-5.4"),
                    ParticipantInit(
                        role="research",
                        cli_kind="claude",
                        model="m",
                        workspace_access="workspace_write",
                    ),
                ],
            )
        )
        conversation_id = str(result["id"])
        chat = build_room_chat_projection(conversation_id, tmp_path)
        assert chat["participants"], "expected projected participants"
        for participant in chat["participants"]:
            assert "workspace_access" not in participant
            assert "model" not in participant
        listing = build_room_list_projection(tmp_path)
        for room in listing["rooms"]:
            for participant in room.get("participants", []):
                assert "workspace_access" not in participant


def test_read_only_setup_result_matches_pre_change_shape(tmp_path: Path) -> None:
    """A read-only setup stores and returns exactly the pre-change participant shape."""

    RoomDatabase(tmp_path / "chat.db").initialize()
    service = RoomSetupService(tmp_path)
    result = service.create_conversation(
        RoomConversationCreate(
            title="shape",
            client_request_id="shape-1",
            initial_participants=[
                ParticipantInit(role="review", cli_kind="codex", model="gpt-5.4"),
            ],
        )
    )
    participants = result["participants"]
    assert isinstance(participants, list)
    dumped = participants[0]
    assert set(dumped) == {
        "participant_id",
        "conversation_id",
        "role",
        "display_name",
        "provider_id",
        "profile_id",
        "cli_kind",
        "model",
        "role_template_id",
        "persona_snapshot",
        "persona_snapshot_sha256",
        "status",
        "last_seen_at",
        "created_at",
    }
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from participants").fetchone()
    assert row["workspace_access"] is None
    assert sha256(str(row["cli_kind"]).encode()).hexdigest() is not None
