from __future__ import annotations

from pathlib import Path

from xmuse_core.runtime.root_contract import (
    DATA_LOCK_NAME,
    DATA_OPERATION_JOURNAL_NAME,
    WORKROOM_LIFECYCLE_LOCK_NAME,
    WORKROOM_MANIFEST_NAME,
    RuntimeRootPaths,
    file_lock,
)


def test_runtime_root_paths_are_fixed_and_respect_xmuse_root(tmp_path: Path, monkeypatch) -> None:
    configured = tmp_path / "configured" / ".." / "authority"
    monkeypatch.setenv("XMUSE_ROOT", str(configured))

    paths = RuntimeRootPaths.resolve(tmp_path / "ignored", fallback=tmp_path / "fallback")

    assert paths.root == configured.resolve()
    assert paths.manifest == paths.root / WORKROOM_MANIFEST_NAME
    assert paths.lifecycle_lock == paths.root / WORKROOM_LIFECYCLE_LOCK_NAME
    assert paths.data_lock == paths.root / DATA_LOCK_NAME
    assert paths.data_operation_journal == paths.root / DATA_OPERATION_JOURNAL_NAME
    assert paths.chat_db == paths.root / "chat.db"
    assert paths.god_sessions == paths.root / "god_sessions.json"
    assert paths.god_sessions_lock == paths.root / "god_sessions.json.lock"
    assert paths.room_runner_pid == paths.root / "workroom_room_runner.pid.json"
    assert paths.room_mcp_pid == paths.root / "workroom_room_mcp.pid.json"
    assert paths.room_runner_status == paths.root / "room-runner-status.json"
    assert paths.memoryos_status == paths.root / "memoryos-status.json"
    assert paths.memoryos_derived == paths.root / "runtime" / "memoryos-derived"


def test_file_lock_creates_only_the_requested_lock_file(tmp_path: Path) -> None:
    lock = tmp_path / "nested" / WORKROOM_LIFECYCLE_LOCK_NAME

    with file_lock(lock):
        assert lock.is_file()
        assert set(tmp_path.rglob("*")) == {lock.parent, lock}

    assert lock.read_text(encoding="utf-8") == ""
