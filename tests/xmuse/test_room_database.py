from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse_core.chat import room_database
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import (
    COMPAT_CHAT_SCHEMA_ID,
    ROOM_REQUIRED_COLUMNS,
    ROOM_SCHEMA_ID,
    ROOM_SCHEMA_VERSION,
    RoomDatabase,
    RoomDatabaseError,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_operations import RoomRuntimeOperatorActionStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore

FORBIDDEN_COMPAT_TABLES = {
    "acceptance_spines",
    "bootstrap_applications",
    "bootstrap_drafts",
    "bootstrap_proposals",
    "chat_inbox_items",
    "chat_streams",
    "chat_turn_budgets",
    "groupchat_chains",
    "groupchat_decisions",
    "groupchat_worklist",
    "peer_forks",
    "resolutions",
    "role_templates",
    "schema_migrations",
}


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {
            str(row[0])
            for row in conn.execute(
                "select name from sqlite_schema where type = 'table' and name not like 'sqlite_%'"
            )
        }


def _initialize_room_database_process(path: str, start: Any) -> None:
    start.wait(timeout=10)
    RoomDatabase(path).initialize()


def test_fresh_room_database_has_only_room_authority_dependencies(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"

    RoomDatabase(path).initialize()

    tables = _tables(path)
    assert set(ROOM_REQUIRED_COLUMNS) <= tables
    assert not tables & FORBIDDEN_COMPAT_TABLES
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "select version from chat_schema_meta where schema_id = ?",
            (ROOM_SCHEMA_ID,),
        ).fetchone() == (ROOM_SCHEMA_VERSION,)
        assert (
            conn.execute(
                "select 1 from chat_schema_meta where schema_id = ?",
                (COMPAT_CHAT_SCHEMA_ID,),
            ).fetchone()
            is None
        )


def test_room_connections_apply_write_and_readonly_policy(tmp_path: Path) -> None:
    database = RoomDatabase(tmp_path / "chat.db")
    database.initialize()

    with database.connect() as conn:
        assert conn.execute("pragma foreign_keys").fetchone()[0] == 1
        assert conn.execute("pragma busy_timeout").fetchone()[0] == 30_000
        assert conn.execute("pragma query_only").fetchone()[0] == 0
    with database.connect(readonly=True) as conn:
        assert conn.execute("pragma foreign_keys").fetchone()[0] == 1
        assert conn.execute("pragma busy_timeout").fetchone()[0] == 30_000
        assert conn.execute("pragma query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("insert into conversations values ('forbidden', 'x', 'now')")


def test_repeated_room_initialization_does_not_rewrite_schema_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "chat.db"
    database = RoomDatabase(path)
    database.initialize()
    with sqlite3.connect(path) as conn:
        marker_before = conn.execute(
            "select version, updated_at from chat_schema_meta where schema_id = ?",
            (ROOM_SCHEMA_ID,),
        ).fetchone()

    monkeypatch.setattr(room_database, "_utc_now", lambda: "2999-01-01T00:00:00Z")
    database.initialize()

    with sqlite3.connect(path) as conn:
        marker_after = conn.execute(
            "select version, updated_at from chat_schema_meta where schema_id = ?",
            (ROOM_SCHEMA_ID,),
        ).fetchone()
    assert marker_after == marker_before


def test_two_processes_concurrently_initialize_one_current_room_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    context = get_context("spawn")
    start = context.Event()
    processes = [
        context.Process(
            target=_initialize_room_database_process,
            args=(str(path), start),
        )
        for _index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)

    assert [process.exitcode for process in processes] == [0, 0]
    assert set(ROOM_REQUIRED_COLUMNS) <= _tables(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "select schema_id, version from chat_schema_meta order by schema_id"
        ).fetchall() == [(ROOM_SCHEMA_ID, ROOM_SCHEMA_VERSION)]


def test_read_connection_waits_through_a_transient_exclusive_lock(
    tmp_path: Path,
) -> None:
    database = RoomDatabase(tmp_path / "chat.db")
    database.initialize()
    lock = sqlite3.connect(database.path, isolation_level=None)
    lock.execute("begin exclusive")

    def read_count() -> int:
        with database.connect(readonly=True) as conn:
            return int(conn.execute("select count(*) from conversations").fetchone()[0])

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(read_count)
            time.sleep(0.05)
            assert not reading.done()
            lock.execute("commit")
            assert reading.result(timeout=2) == 0
    finally:
        if lock.in_transaction:
            lock.execute("rollback")
        lock.close()


def test_readonly_and_stores_do_not_create_a_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    RoomKernelStore(path)
    RoomObservationControlStore(path)
    RoomAttemptSkillDecisionStore(path)
    RoomRuntimeOperatorActionStore(path)
    ParticipantStore(path)
    assert not path.exists()

    with pytest.raises(RoomDatabaseError, match="room_database_missing"):
        RoomDatabase(path).connect(readonly=True)
    assert not path.exists()


@pytest.mark.parametrize(
    "stage",
    [
        "_create_room_core_schema_conn",
        "create_room_kernel_schema",
        "create_room_execution_schema",
        "create_room_memory_schema",
        "create_room_operations_schema",
        "_validate_room_schema",
        "_utc_now",
    ],
)
def test_room_schema_initialization_rolls_back_every_stage_before_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    path = tmp_path / "chat.db"

    def fail_schema_stage(*_args: object) -> None:
        raise RuntimeError("injected_schema_failure")

    monkeypatch.setattr(room_database, stage, fail_schema_stage)
    with pytest.raises(RuntimeError, match="injected_schema_failure"):
        RoomDatabase(path).initialize()

    assert _tables(path) == set()
    with sqlite3.connect(path) as conn:
        assert conn.execute("pragma schema_version").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("schema_id", "expected_error"),
    [
        (ROOM_SCHEMA_ID, "room_schema_version_unsupported"),
        (COMPAT_CHAT_SCHEMA_ID, "chat_schema_version_unsupported:999>1"),
    ],
)
def test_known_future_marker_fails_closed_with_schema_specific_error(
    tmp_path: Path,
    schema_id: str,
    expected_error: str,
) -> None:
    path = tmp_path / "chat.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "create table chat_schema_meta (schema_id text primary key, "
            "version integer not null, updated_at text not null)"
        )
        conn.execute(
            "insert into chat_schema_meta values (?, 999, 'now')",
            (schema_id,),
        )

    with pytest.raises(RoomDatabaseError) as exc_info:
        RoomDatabase(path).initialize()

    assert str(exc_info.value) == expected_error
    assert "room_activities" not in _tables(path)


def test_offline_compat_data_marker_and_rows_survive_room_reopen(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    RoomDatabase(path).initialize()
    chat = CompatDataTestStore(path)
    conversation = chat.create_conversation("preserved")
    chat.add_message(conversation.id, "human", "human", "keep me")
    compat_tables = _tables(path) & FORBIDDEN_COMPAT_TABLES
    assert compat_tables == {"role_templates", "schema_migrations"}

    RoomDatabase(path).initialize()

    assert compat_tables <= _tables(path)
    assert CompatDataTestStore(path).list_messages(conversation.id)[0].content == "keep me"


def test_legacy_full_database_gets_additive_room_setup_table_before_marker(
    tmp_path: Path,
) -> None:
    path = tmp_path / "chat.db"
    CompatDataTestStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("delete from chat_schema_meta where schema_id = ?", (ROOM_SCHEMA_ID,))
        conn.execute("drop table room_setup_requests")

    RoomDatabase(path).initialize()

    assert "room_setup_requests" in _tables(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "select version from chat_schema_meta where schema_id = ?", (ROOM_SCHEMA_ID,)
        ).fetchone() == (ROOM_SCHEMA_VERSION,)
