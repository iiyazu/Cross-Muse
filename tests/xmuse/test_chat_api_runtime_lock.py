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
    first_ensure_entered = threading.Event()
    release_first_ensure = threading.Event()
    second_config_entered = threading.Event()
    state = {
        "ensure_calls": 0,
        "port_snapshots": [],
    }

    def fake_port(_base_dir):
        with state_lock:
            state["port_snapshots"].append(state["ensure_calls"])
            if len(state["port_snapshots"]) == 2:
                second_config_entered.set()
        return 8117

    def fake_ensure(config):
        assert config.xmuse_root == tmp_path
        assert config.execution_worktree == tmp_path / "repo"
        with state_lock:
            state["ensure_calls"] += 1
            call_number = state["ensure_calls"]
        if call_number == 1:
            first_ensure_entered.set()
            assert release_first_ensure.wait(timeout=2)
        return {
            "schema_version": "workroom_room_runtime/v1",
            "state": "ready",
            "ready": True,
            "source": "started_process" if call_number == 1 else "existing_process",
        }

    monkeypatch.setattr(chat_api_runtime, "_workroom_mcp_port", fake_port)
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
        assert first_ensure_entered.wait(timeout=2)
        assert not second_config_entered.wait(timeout=0.1)
        release_first_ensure.set()
        results = [future.result(timeout=2) for future in futures]

    assert state["ensure_calls"] == 2
    assert state["port_snapshots"] == [0, 1]
    assert {result["source"] for result in results} == {
        "started_process",
        "existing_process",
    }
    assert (tmp_path / chat_api_runtime._WORKROOM_RUNTIME_START_LOCK_NAME).is_file()
