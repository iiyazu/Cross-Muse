from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.runtime.sqlite_connection import ClosingConnection


def _closed(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("select 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_with_block_commits_then_closes(tmp_path: Path) -> None:
    path = tmp_path / "data.db"
    with sqlite3.connect(path, factory=ClosingConnection) as conn:
        conn.execute("create table items(value text)")
        conn.execute("insert into items values('kept')")

    assert _closed(conn)
    with sqlite3.connect(path, factory=ClosingConnection) as reader:
        assert reader.execute("select value from items").fetchall() == [("kept",)]


def test_with_block_rolls_back_then_closes_on_error(tmp_path: Path) -> None:
    path = tmp_path / "data.db"
    with sqlite3.connect(path, factory=ClosingConnection) as conn:
        conn.execute("create table items(value text)")

    with pytest.raises(RuntimeError):
        with sqlite3.connect(path, factory=ClosingConnection) as conn:
            conn.execute("insert into items values('discarded')")
            raise RuntimeError("abort")

    assert _closed(conn)
    with sqlite3.connect(path, factory=ClosingConnection) as reader:
        assert reader.execute("select count(*) from items").fetchone() == (0,)


@pytest.mark.parametrize("readonly", [False, True])
def test_room_database_connections_close_with_their_block(tmp_path: Path, readonly: bool) -> None:
    database = RoomDatabase(tmp_path / "chat.db")
    database.initialize()

    with database.connect(readonly=readonly) as conn:
        conn.execute("select count(*) from conversations").fetchone()

    assert _closed(conn)
