from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse.data_backup import backup_data, verify_backup, verify_staged_database_copy
from xmuse.data_contracts import (
    BACKUP_MANIFEST_NAME,
    COMMAND_SCHEMA,
    OPERATION_JOURNAL_NAME,
    SESSION_NAME,
    DataError,
)
from xmuse.data_mutation import (
    DataMutationError,
    finish_operation,
    new_operation,
    recover_existing_operation,
    update_operation,
)
from xmuse.data_restore import restore_data
from xmuse_core.runtime.root_contract import CHAT_DB_NAME


def _root(path: Path) -> tuple[Path, str]:
    path.mkdir()
    conversation = CompatDataTestStore(path / CHAT_DB_NAME).create_conversation(
        "Backup module room"
    )
    return path, conversation.id


def test_backup_and_verify_publish_the_existing_wire_contract(tmp_path: Path) -> None:
    root, conversation_id = _root(tmp_path / "source")
    destination = tmp_path / "backup"

    result = backup_data(root, destination)
    manifest, backup_db, sessions, records = verify_backup(destination)

    assert result == {
        "schema_version": COMMAND_SCHEMA,
        "command": "backup",
        "state": "succeeded",
        "backup": str(destination),
        "backup_id": manifest["backup_id"],
        "rooms": 1,
        "source_journal_mode": result["source_journal_mode"],
    }
    assert {item.name for item in destination.iterdir()} == {
        BACKUP_MANIFEST_NAME,
        CHAT_DB_NAME,
        SESSION_NAME,
    }
    assert sessions == {"sessions": []}
    assert records == []
    with sqlite3.connect(backup_db) as connection:
        assert connection.execute(
            "select title from conversations where id = ?", (conversation_id,)
        ).fetchone() == ("Backup module room",)


def test_verify_backup_rejects_the_operator_supplied_directory_symlink(
    tmp_path: Path,
) -> None:
    root, _conversation_id = _root(tmp_path / "source")
    destination = tmp_path / "backup"
    backup_data(root, destination)
    alias = tmp_path / "backup-alias"
    alias.symlink_to(destination, target_is_directory=True)

    with pytest.raises(DataError) as raised:
        verify_backup(alias)

    assert raised.value.code == "backup_manifest_invalid"


def test_staged_copy_is_reproved_after_the_initial_backup_verification(
    tmp_path: Path,
) -> None:
    root, _conversation_id = _root(tmp_path / "source")
    destination = tmp_path / "backup"
    backup_data(root, destination)
    manifest, backup_db, _sessions, _records = verify_backup(destination)
    staged = tmp_path / "staged.db"
    staged.write_bytes(backup_db.read_bytes())
    staged.write_bytes(staged.read_bytes() + b"tampered")

    with pytest.raises(DataError) as raised:
        verify_staged_database_copy(staged, manifest)

    assert raised.value.code == "backup_checksum_mismatch"


def test_restore_uses_two_runtime_guards_and_publishes_fenced_authority(
    tmp_path: Path,
) -> None:
    source, conversation_id = _root(tmp_path / "source")
    backup = tmp_path / "backup"
    backup_data(source, backup)
    target = tmp_path / "target"
    guard_calls: list[Path] = []

    result = restore_data(
        target,
        backup,
        replace=False,
        runtime_guard=lambda root: guard_calls.append(root),
    )

    assert guard_calls == [target.resolve(), target.resolve()]
    assert result["schema_version"] == COMMAND_SCHEMA
    assert result["command"] == "restore"
    assert result["state"] == "succeeded"
    assert result["session_count"] == 0
    assert not (target / OPERATION_JOURNAL_NAME).exists()
    assert not list(target.glob(".xmuse-data-stage-*"))
    assert not list(target.glob(".xmuse-data-rollback-*"))
    with sqlite3.connect(target / CHAT_DB_NAME) as connection:
        assert connection.execute(
            "select title from conversations where id = ?", (conversation_id,)
        ).fetchone() == ("Backup module room",)
        assert connection.execute("pragma integrity_check").fetchone() == ("ok",)
    assert json.loads((target / SESSION_NAME).read_text(encoding="utf-8")) == {"sessions": []}


def test_committed_journal_recovery_keeps_installed_bytes_and_cleans_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    installed = b"installed authority"
    (root / CHAT_DB_NAME).write_bytes(installed)
    payload, staging, rollback = new_operation(
        root,
        kind="compact",
        install_names=(CHAT_DB_NAME,),
    )
    (rollback / CHAT_DB_NAME).write_bytes(b"old authority")
    (staging / "unfinished").write_text("staging", encoding="utf-8")
    update_operation(root, payload, "committed")

    assert recover_existing_operation(root) == payload["operation_id"]
    assert (root / CHAT_DB_NAME).read_bytes() == installed
    assert not (root / OPERATION_JOURNAL_NAME).exists()
    assert not staging.exists()
    assert not rollback.exists()


def test_finish_operation_never_follows_a_symlinked_journal_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    payload, staging, _rollback = new_operation(
        root,
        kind="compact",
        install_names=(CHAT_DB_NAME,),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    os.rmdir(staging)
    staging.symlink_to(outside, target_is_directory=True)

    with pytest.raises(DataMutationError, match="unsafe data operation directory"):
        finish_operation(root, payload)

    assert sentinel.read_bytes() == b"preserve"
