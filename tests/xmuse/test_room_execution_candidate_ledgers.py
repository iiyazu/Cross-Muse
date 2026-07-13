from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_candidates import (
    insert_execution_candidate_conn,
    prepare_execution_candidate_conn,
)
from xmuse_core.chat.room_execution_common import (
    RoomExecutionStoreError,
    digest,
    json_value,
    require_digest,
    timestamp,
)
from xmuse_core.chat.room_execution_contracts import normalize_execution_patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEAVES = (
    PROJECT_ROOT / "src/xmuse_core/chat/room_execution_common.py",
    PROJECT_ROOT / "src/xmuse_core/chat/room_execution_candidates.py",
)
PATCH_PATH = "src/xmuse_core/example.py"
PATCH = (
    f"diff --git a/{PATCH_PATH} b/{PATCH_PATH}\n"
    "index 1111111..2222222 100644\n"
    f"--- a/{PATCH_PATH}\n+++ b/{PATCH_PATH}\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)


def test_execution_candidate_leaves_have_no_connection_or_transaction_owner() -> None:
    forbidden_imports = {
        "xmuse_core.chat.room_database",
        "xmuse_core.chat.room_execution_store",
        "xmuse_core.chat.room_execution_controller",
    }
    forbidden_calls = {"commit", "rollback", "connect", "close"}
    for path in LEAVES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not imports & forbidden_imports
        assert not calls & forbidden_calls
        assert "begin immediate" not in source.lower()


def test_execution_common_keeps_canonical_values_and_stable_errors() -> None:
    instant = datetime(2026, 7, 13, 1, 2, 3, 456789, tzinfo=UTC)
    assert timestamp(instant) == "2026-07-13T01:02:03.456789Z"
    assert json_value({"b": 2, "a": "值"}) == '{"a":"值","b":2}'
    assert digest({"a": 1}).startswith("sha256:")
    with pytest.raises(RoomExecutionStoreError) as exc_info:
        require_digest("not-a-digest", "room_execution_candidate_digest_invalid")
    assert exc_info.value.code == "room_execution_candidate_digest_invalid"


def test_candidate_conn_primitives_remain_inside_the_caller_transaction(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("candidate leaf").id
    participants = ParticipantStore(db)
    author = participants.add(
        conversation_id=conversation_id,
        role="architect",
        display_name="Architect",
        cli_kind="codex",
        model="gpt-5.4",
    )
    participants.add(
        conversation_id=conversation_id,
        role="review",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5.4",
    )
    patch = normalize_execution_patch(
        {
            "schema_version": "room_execution_patch/v1",
            "base_head": "a" * 40,
            "summary": "Change the example",
            "unified_diff": PATCH,
            "allowed_files": [PATCH_PATH],
        }
    )
    with RoomDatabase(db).connect() as conn:
        conn.execute("begin immediate")
        prepared = prepare_execution_candidate_conn(
            conn,
            conversation_id=conversation_id,
            author_participant_id=author.participant_id,
            source_observation_id="observation-not-yet-inserted",
            source_batch_id=None,
            source_attempt_id="attempt-not-yet-inserted",
            source_activity_id="activity-not-yet-inserted",
            source_correlation_id="correlation",
            proposal_id="proposal-not-yet-inserted",
            patch=patch,
            direct_human_root=True,
            stamp="2026-07-13T01:02:03.456789Z",
        )
        # Candidate foreign keys intentionally point at rows that the caller's larger
        # outcome transaction has not inserted yet, so only preparation writes policy.
        assert conn.in_transaction
        assert prepared["author_participant_id"] == author.participant_id
        assert prepared["members"][0]["participant_id"] != author.participant_id
        conn.rollback()

    with RoomDatabase(db).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_execution_policies").fetchone()[0] == 0
        assert conn.execute("select count(*) from room_execution_candidates").fetchone()[0] == 0

    # Keep the insert primitive imported and type-checked without manufacturing invalid
    # authority rows in this leaf-focused transaction test.
    assert callable(insert_execution_candidate_conn)
