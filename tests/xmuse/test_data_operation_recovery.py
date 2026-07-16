from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse import data_cli, data_mutation, data_restore

_TARGET_NAMES = (
    data_cli.CHAT_DB_NAME,
    data_cli.SESSION_NAME,
    f"{data_cli.CHAT_DB_NAME}-wal",
    f"{data_cli.CHAT_DB_NAME}-shm",
)


def _seed_targets(root: Path, label: str) -> dict[str, bytes]:
    expected: dict[str, bytes] = {}
    for name in _TARGET_NAMES:
        value = f"{label}:{name}".encode()
        (root / name).write_bytes(value)
        expected[name] = value
    return expected


def _assert_targets(root: Path, expected: dict[str, bytes]) -> None:
    assert {name: (root / name).read_bytes() for name in _TARGET_NAMES} == expected


def _assert_operation_cleaned(root: Path, payload: dict[str, object]) -> None:
    assert not (root / data_cli.OPERATION_JOURNAL_NAME).exists()
    assert not (root / str(payload["staging_dir"])).exists()
    assert not (root / str(payload["rollback_dir"])).exists()


def test_restore_commit_failure_restores_every_original_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    originals = _seed_targets(root, "original")
    payload, staging, rollback = data_mutation.new_operation(
        root,
        kind="restore",
        install_names=(data_cli.CHAT_DB_NAME, data_cli.SESSION_NAME),
    )
    (staging / data_cli.CHAT_DB_NAME).write_bytes(b"replacement database")
    (staging / data_cli.SESSION_NAME).write_text('{"sessions":[]}\n', encoding="utf-8")

    def fail_installed_validation(_path: Path, *, require_current: bool) -> dict[str, object]:
        assert require_current is True
        raise data_cli.DataError("injected_commit_failure", "injected after install")

    monkeypatch.setattr(data_restore, "inspect_database", fail_installed_validation)

    with pytest.raises(data_cli.DataError) as raised:
        data_restore.commit_restore(root, payload, staging, rollback)

    assert raised.value.code == "injected_commit_failure"
    _assert_targets(root, originals)
    _assert_operation_cleaned(root, payload)


def test_successful_restore_discards_stale_wal_and_shm_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    _seed_targets(root, "stale")
    payload, staging, rollback = data_mutation.new_operation(
        root,
        kind="restore",
        install_names=(data_cli.CHAT_DB_NAME, data_cli.SESSION_NAME),
    )
    conversation = CompatDataTestStore(staging / data_cli.CHAT_DB_NAME).create_conversation(
        "restored authority"
    )
    (staging / data_cli.SESSION_NAME).write_text('{"sessions":[]}\n', encoding="utf-8")

    data_restore.commit_restore(root, payload, staging, rollback)

    assert not (root / f"{data_cli.CHAT_DB_NAME}-wal").exists()
    assert not (root / f"{data_cli.CHAT_DB_NAME}-shm").exists()
    with sqlite3.connect(root / data_cli.CHAT_DB_NAME) as conn:
        assert conn.execute("select id, title from conversations").fetchall() == [
            (conversation.id, "restored authority")
        ]
        assert conn.execute("pragma integrity_check").fetchone() == ("ok",)
    _assert_operation_cleaned(root, payload)


def test_committed_journal_finalizes_without_restoring_rollback_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    installed = _seed_targets(root, "installed")
    payload, staging, rollback = data_mutation.new_operation(
        root,
        kind="restore",
        install_names=(data_cli.CHAT_DB_NAME, data_cli.SESSION_NAME),
    )
    for name in _TARGET_NAMES:
        (rollback / name).write_bytes(f"prior:{name}".encode())
    (staging / "unfinished").write_text("staging", encoding="utf-8")
    data_mutation.update_operation(root, payload, "committed")

    recovered = data_mutation.recover_existing_operation(root)

    assert recovered == payload["operation_id"]
    _assert_targets(root, installed)
    _assert_operation_cleaned(root, payload)


def test_moving_old_journal_rolls_back_a_partially_moved_target_set(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    originals = _seed_targets(root, "original")
    payload, _staging, rollback = data_mutation.new_operation(
        root,
        kind="restore",
        install_names=(data_cli.CHAT_DB_NAME, data_cli.SESSION_NAME),
    )
    for name in (data_cli.CHAT_DB_NAME, f"{data_cli.CHAT_DB_NAME}-wal"):
        os.replace(root / name, rollback / name)
    data_mutation.update_operation(root, payload, "moving_old")

    recovered = data_mutation.recover_existing_operation(root)

    assert recovered == payload["operation_id"]
    _assert_targets(root, originals)
    _assert_operation_cleaned(root, payload)


def test_installed_journal_removes_new_targets_and_restores_all_old_targets(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    originals = _seed_targets(root, "original")
    payload, _staging, rollback = data_mutation.new_operation(
        root,
        kind="restore",
        install_names=(data_cli.CHAT_DB_NAME, data_cli.SESSION_NAME),
    )
    for name in _TARGET_NAMES:
        os.replace(root / name, rollback / name)
    (root / data_cli.CHAT_DB_NAME).write_bytes(b"installed database")
    (root / data_cli.SESSION_NAME).write_bytes(b"installed sessions")
    data_mutation.update_operation(root, payload, "installed")

    recovered = data_mutation.recover_existing_operation(root)

    assert recovered == payload["operation_id"]
    _assert_targets(root, originals)
    _assert_operation_cleaned(root, payload)


def test_recovery_rejects_a_journal_operation_id_that_can_escape_the_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / data_cli.CHAT_DB_NAME
    sentinel.write_bytes(b"outside authority")
    payload = {
        "schema_version": data_cli.OPERATION_SCHEMA,
        "operation_id": "../../outside",
        "phase": "installed",
        "staging_dir": "outside",
        "rollback_dir": "outside",
        "targets": [{"name": data_cli.CHAT_DB_NAME, "had_original": True}],
    }

    with pytest.raises(data_mutation.DataMutationError, match="operation ID is invalid"):
        data_mutation.rollback_operation(root, payload)

    assert sentinel.read_bytes() == b"outside authority"
