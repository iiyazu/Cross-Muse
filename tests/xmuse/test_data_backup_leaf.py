from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse.data_backup import (
    DataBackupError,
    manifest_file,
    normalize_artifact_database,
    online_backup,
    verify_manifest_file,
)


def test_online_backup_is_consistent_and_normalized(tmp_path: Path) -> None:
    source = tmp_path / "chat.db"
    with sqlite3.connect(source) as conn:
        conn.execute("pragma journal_mode = wal")
        conn.execute("create table facts(id integer primary key, value text)")
        conn.executemany("insert into facts(value) values (?)", [("a",), ("b",)])
    destination = tmp_path / "backup.db"

    assert online_backup(source, destination) == "wal"
    normalize_artifact_database(destination)

    with sqlite3.connect(destination) as conn:
        assert conn.execute("select value from facts order by id").fetchall() == [("a",), ("b",)]
        assert conn.execute("pragma journal_mode").fetchone()[0] == "delete"
    assert not destination.with_name("backup.db-wal").exists()
    assert not destination.with_name("backup.db-shm").exists()


def test_manifest_file_verification_fails_closed_on_name_checksum_and_symlink(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    artifact = backup / "chat.db"
    artifact.write_bytes(b"authority")
    entry = manifest_file(artifact)

    assert verify_manifest_file(backup, entry, "chat.db") == artifact
    with pytest.raises(DataBackupError) as wrong_name:
        verify_manifest_file(backup, entry, "other.db")
    assert wrong_name.value.code == "backup_manifest_invalid"

    artifact.write_bytes(b"changed")
    with pytest.raises(DataBackupError) as changed:
        verify_manifest_file(backup, entry, "chat.db")
    assert changed.value.code == "backup_checksum_mismatch"

    artifact.unlink()
    target = tmp_path / "outside.db"
    target.write_bytes(b"authority")
    artifact.symlink_to(target)
    with pytest.raises(DataBackupError) as symlink:
        verify_manifest_file(backup, manifest_file(target) | {"name": "chat.db"}, "chat.db")
    assert symlink.value.code == "backup_manifest_invalid"
