from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse.data_inspection import (
    DataInspectionError,
    integrity_report,
    readonly_connection,
    schema_fingerprint,
    table_columns,
    table_order_fingerprints,
    unique_keys,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            create table items(id integer primary key, name text not null unique, payload blob);
            insert into items(name, payload) values ('alpha', x'0102'), ('beta', x'0304');
            """
        )


def test_readonly_inspection_never_mutates_database(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _database(path)
    before = path.read_bytes()

    with readonly_connection(path) as conn:
        assert table_columns(conn, "items") == {"id", "name", "payload"}
        assert {("id",), ("name",)} <= unique_keys(conn, "items")
        assert integrity_report(conn)["integrity"] == "ok"
        assert len(schema_fingerprint(conn)) == 64
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("insert into items(name) values ('forbidden')")

    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_readonly_connection_rejects_missing_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(DataInspectionError) as missing:
        with readonly_connection(tmp_path / "missing.db"):
            pass
    assert missing.value.code == "chat_db_missing"

    real = tmp_path / "real.db"
    _database(real)
    link = tmp_path / "chat.db"
    link.symlink_to(real)
    with pytest.raises(DataInspectionError) as unsafe:
        with readonly_connection(link):
            pass
    assert unsafe.value.code == "chat_db_missing"


def test_table_order_fingerprint_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    _database(path)
    first = table_order_fingerprints(path)
    assert first == table_order_fingerprints(path)

    with sqlite3.connect(path) as conn:
        conn.execute("update items set payload = x'ff' where name = 'beta'")
    assert table_order_fingerprints(path) != first
