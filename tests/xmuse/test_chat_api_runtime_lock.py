from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from xmuse import chat_api_runtime


def test_ensure_workroom_runtime_serializes_config_discovery_and_start(
    tmp_path,
    monkeypatch,
) -> None:
    state_lock = threading.Lock()
    start_barrier = threading.Barrier(3)
    runtime_ready = threading.Event()
    state = {
        "ensure_calls": 0,
        "inspect_calls": 0,
    }

    def fake_port(_base_dir):
        return 8117

    def fake_inspect(config):
        assert config.xmuse_root == tmp_path
        with state_lock:
            state["inspect_calls"] += 1
        ready = runtime_ready.is_set()
        return {
            "schema_version": "workroom_room_runtime/v1",
            "state": "ready" if ready else "stopped",
            "ready": ready,
            "source": "existing_process" if ready else "receipt",
        }

    def fake_ensure(config):
        assert config.xmuse_root == tmp_path
        assert config.execution_worktree == tmp_path / "repo"
        with state_lock:
            state["ensure_calls"] += 1
        runtime_ready.set()
        return {
            "schema_version": "workroom_room_runtime/v1",
            "state": "ready",
            "ready": True,
            "source": "started_process",
        }

    monkeypatch.setattr(chat_api_runtime, "_workroom_mcp_port", fake_port)
    monkeypatch.setattr(chat_api_runtime, "inspect_room_runtime", fake_inspect)
    monkeypatch.setattr(chat_api_runtime, "ensure_room_runtime", fake_ensure)

    def ensure():
        start_barrier.wait(timeout=2)
        return chat_api_runtime.ensure_workroom_room_runtime(
            tmp_path,
            tmp_path / "repo",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(ensure) for _ in range(2)]
        start_barrier.wait(timeout=2)
        results = [future.result(timeout=2) for future in futures]

    assert state["ensure_calls"] == 1
    assert state["inspect_calls"] >= 3
    assert {result["source"] for result in results} == {
        "started_process",
        "existing_process",
    }
    assert (tmp_path / chat_api_runtime._WORKROOM_RUNTIME_START_LOCK_NAME).is_file()


def test_ready_workroom_runtime_fast_path_never_takes_start_lock(tmp_path, monkeypatch) -> None:
    ready = {
        "schema_version": "workroom_room_runtime/v1",
        "state": "ready",
        "ready": True,
        "source": "existing_process",
    }
    monkeypatch.setattr(chat_api_runtime, "inspect_room_runtime", lambda _config: ready)
    monkeypatch.setattr(
        chat_api_runtime,
        "ensure_room_runtime",
        lambda _config: (_ for _ in ()).throw(AssertionError("ready runtime must not ensure")),
    )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _index: chat_api_runtime.ensure_workroom_room_runtime(
                    tmp_path, tmp_path / "repo"
                ),
                range(4),
            )
        )

    assert results == [ready] * 4
    assert not (tmp_path / chat_api_runtime._WORKROOM_RUNTIME_START_LOCK_NAME).exists()
