from xmuse_core.runtime.processes import (
    PROCESS_SERVICE_METADATA,
    _classify_runtime_process,
)


def test_execution_controller_is_a_writer_capable_runtime_process() -> None:
    assert (
        _classify_runtime_process(
            [
                "/usr/bin/python",
                "-m",
                "xmuse.room_execution_controller",
                "--xmuse-root",
                "/tmp/xmuse",
                "--worktree",
                "/tmp/repo",
                "--run-id",
                "execution_run_1",
            ]
        )
        == "execution_controller"
    )
    assert PROCESS_SERVICE_METADATA["execution_controller"]["writer_capable"] is True


def test_memoryos_sidecar_is_discovered_as_a_derived_index_process() -> None:
    assert (
        _classify_runtime_process(
            [
                "/opt/memoryos/bin/memoryos",
                "api",
                "--host",
                "127.0.0.1",
                "--port",
                "8301",
            ]
        )
        == "memoryos"
    )
    assert PROCESS_SERVICE_METADATA["memoryos"] == {
        "label": "memoryos_archive_sidecar",
        "category": "derived_index",
        "writer_capable": False,
        "duplicate_severity": "degraded",
        "subject": "xmuse MemoryOS archive sidecar",
    }
