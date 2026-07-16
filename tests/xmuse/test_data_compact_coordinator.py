from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import CompatDataTestStore
from xmuse import data_compact
from xmuse.data_authority import database_evidence, inspect_database
from xmuse.data_contracts import DataError
from xmuse_core.runtime.root_contract import CHAT_DB_NAME, DATA_OPERATION_JOURNAL_NAME


def _build_root(root: Path) -> None:
    store = CompatDataTestStore(root / CHAT_DB_NAME)
    conversation = store.create_conversation("Compact authority")
    message_ids = [
        store.add_message(conversation.id, "Human", "human", f"temporary-{index}").id
        for index in range(32)
    ]
    with sqlite3.connect(root / CHAT_DB_NAME) as conn:
        conn.executemany(
            "delete from messages where id = ?",
            [(message_id,) for message_id in message_ids[::2]],
        )


def test_compact_preserves_authority_and_uses_lock_then_double_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    _build_root(root)
    before = database_evidence(root / CHAT_DB_NAME)
    events: list[str] = []

    @contextmanager
    def recording_lock(path: Path, *, exclusive: bool = True) -> Iterator[None]:
        del exclusive
        events.append(f"enter:{path.name}")
        try:
            yield
        finally:
            events.append(f"exit:{path.name}")

    monkeypatch.setattr(data_compact, "file_lock", recording_lock)
    result = data_compact.compact_data(
        root,
        runtime_guard=lambda _root: events.append("guard"),
    )

    assert result["state"] == "succeeded"
    assert database_evidence(root / CHAT_DB_NAME) == before
    assert events == [
        "enter:.xmuse-workroom.lifecycle.lock",
        "enter:.xmuse-data.lock",
        "guard",
        "guard",
        "exit:.xmuse-data.lock",
        "exit:.xmuse-workroom.lifecycle.lock",
    ]
    assert not (root / DATA_OPERATION_JOURNAL_NAME).exists()
    with sqlite3.connect(root / CHAT_DB_NAME) as conn:
        assert conn.execute("pragma integrity_check").fetchone()[0] == "ok"


def test_compact_guard_failure_does_not_start_an_operation(tmp_path: Path) -> None:
    root = tmp_path / "guarded"
    _build_root(root)
    before = database_evidence(root / CHAT_DB_NAME)

    def blocked(_root: Path) -> None:
        raise DataError("workroom_running", "runtime is live")

    with pytest.raises(DataError) as exc_info:
        data_compact.compact_data(root, runtime_guard=blocked)

    assert exc_info.value.code == "workroom_running"
    assert database_evidence(root / CHAT_DB_NAME) == before
    assert not (root / DATA_OPERATION_JOURNAL_NAME).exists()


def test_installed_integrity_failure_rolls_back_original_authority(tmp_path: Path) -> None:
    root = tmp_path / "rollback"
    _build_root(root)
    before = database_evidence(root / CHAT_DB_NAME)
    root_inspections = 0

    def fail_installed(path: Path, *, require_current: bool) -> dict[str, object]:
        nonlocal root_inspections
        if path == root / CHAT_DB_NAME:
            root_inspections += 1
            if root_inspections == 2:
                raise DataError("chat_db_corrupt", "installed proof failed")
        return inspect_database(path, require_current=require_current)

    with pytest.raises(DataError) as exc_info:
        data_compact.compact_data(
            root,
            runtime_guard=lambda _root: None,
            database_inspector=fail_installed,
        )

    assert exc_info.value.code == "chat_db_corrupt"
    assert database_evidence(root / CHAT_DB_NAME) == before
    assert not (root / DATA_OPERATION_JOURNAL_NAME).exists()


def test_evidence_mismatch_fails_before_promotion_and_cleans_journal(tmp_path: Path) -> None:
    root = tmp_path / "mismatch"
    _build_root(root)
    before = database_evidence(root / CHAT_DB_NAME)
    reads = 0

    def drift(path: Path) -> dict[str, object]:
        nonlocal reads
        reads += 1
        evidence = database_evidence(path)
        if reads == 2:
            return {**evidence, "rooms_sha256": "changed"}
        return evidence

    with pytest.raises(DataError) as exc_info:
        data_compact.compact_data(
            root,
            runtime_guard=lambda _root: None,
            evidence_reader=drift,
        )

    assert exc_info.value.code == "compact_failed"
    assert database_evidence(root / CHAT_DB_NAME) == before
    assert not (root / DATA_OPERATION_JOURNAL_NAME).exists()


def test_commit_failure_rolls_back_from_durable_journal_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime"
    staging = root / "stage"
    rollback = root / "rollback"
    staging.mkdir(parents=True)
    rollback.mkdir()
    (staging / CHAT_DB_NAME).write_bytes(b"candidate")
    in_memory = {"operation_id": "compact-" + "1" * 32, "phase": "old_moved"}
    durable = {"operation_id": in_memory["operation_id"], "phase": "moving_old"}
    rolled_back: list[dict[str, object]] = []

    monkeypatch.setattr(data_compact, "move_old_targets", lambda *_args: None)
    monkeypatch.setattr(data_compact.os, "replace", lambda *_args: None)

    def fail_update(_root: Path, payload: dict[str, object], phase: str) -> None:
        payload["phase"] = phase
        raise OSError("journal publish failed")

    monkeypatch.setattr(data_compact, "update_operation", fail_update)
    monkeypatch.setattr(data_compact, "read_operation", lambda _root: durable)
    monkeypatch.setattr(
        data_compact,
        "_rollback",
        lambda _root, payload: rolled_back.append(dict(payload)),
    )

    with pytest.raises(DataError) as exc_info:
        data_compact._commit_compact(
            root,
            in_memory,
            staging,
            rollback,
            database_inspector=lambda _path, require_current: {"require_current": require_current},
        )

    assert exc_info.value.code == "compact_failed"
    assert in_memory["phase"] == "installed"
    assert rolled_back == [durable]
