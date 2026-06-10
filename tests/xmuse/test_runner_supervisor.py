from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from xmuse_core.platform.runner_supervisor import (
    RunnerStartError,
    RunnerSupervisorConfig,
    read_pid_file,
    runner_command,
    runner_status,
    start_runner,
    write_pid_file,
)


def test_pid_file_round_trips_process_metadata(tmp_path: Path) -> None:
    pid_file = tmp_path / "runner.pid.json"

    write_pid_file(
        pid_file,
        pid=1234,
        command=["uv", "run", "python", "xmuse/platform_runner.py"],
        log_path=tmp_path / "runner.log",
    )

    assert read_pid_file(pid_file) == {
        "pid": 1234,
        "command": ["uv", "run", "python", "xmuse/platform_runner.py"],
        "log_path": str(tmp_path / "runner.log"),
    }


def test_start_runner_refuses_duplicate_runner_by_default(tmp_path: Path) -> None:
    config = RunnerSupervisorConfig(repo_root=tmp_path, pid_file=tmp_path / "runner.pid.json")

    with pytest.raises(RunnerStartError, match="runner already running"):
        start_runner(
            config,
            discover_processes=lambda: ([111], [222]),
            popen=lambda *_args, **_kwargs: pytest.fail("must not start duplicate"),
        )


def test_start_runner_replace_terminates_duplicates_and_starts_detached(
    tmp_path: Path,
) -> None:
    config = RunnerSupervisorConfig(repo_root=tmp_path, pid_file=tmp_path / "runner.pid.json")
    terminated: list[tuple[int, signal.Signals]] = []
    popen_calls: list[dict] = []

    class FakeProcess:
        pid = 333

    def fake_popen(command, **kwargs):
        popen_calls.append({"command": command, "kwargs": kwargs})
        return FakeProcess()

    discoveries = iter([([111, 112], [222]), ([], [222])])

    result = start_runner(
        config,
        replace=True,
        discover_processes=lambda: next(discoveries),
        terminate_process=lambda pid, sig: terminated.append((pid, signal.Signals(sig))),
        sleep=lambda _seconds: None,
        popen=fake_popen,
    )

    assert result["pid"] == 333
    assert terminated == [(111, signal.SIGTERM), (112, signal.SIGTERM)]
    assert popen_calls[0]["kwargs"]["start_new_session"] is True
    assert popen_calls[0]["kwargs"]["cwd"] == tmp_path
    assert read_pid_file(config.pid_file)["pid"] == 333


def test_start_runner_replace_fails_if_duplicate_runner_does_not_exit(
    tmp_path: Path,
) -> None:
    config = RunnerSupervisorConfig(repo_root=tmp_path, pid_file=tmp_path / "runner.pid.json")

    with pytest.raises(RunnerStartError, match="existing runner did not stop"):
        start_runner(
            config,
            replace=True,
            discover_processes=lambda: ([111], [222]),
            terminate_process=lambda _pid, _sig: None,
            sleep=lambda _seconds: None,
            stop_timeout_s=0.01,
            popen=lambda *_args, **_kwargs: pytest.fail("must not start duplicate"),
        )


def test_runner_command_can_enable_persistent_execute_god(tmp_path: Path) -> None:
    config = RunnerSupervisorConfig(
        repo_root=tmp_path,
        pid_file=tmp_path / "runner.pid.json",
        persistent_execute_god=True,
    )

    command = runner_command(config)

    assert "--persistent-review-god" in command
    assert "--persistent-execute-god" in command


def test_runner_command_keeps_persistent_execute_god_off_by_default(tmp_path: Path) -> None:
    config = RunnerSupervisorConfig(
        repo_root=tmp_path,
        pid_file=tmp_path / "runner.pid.json",
    )

    command = runner_command(config)

    assert "--persistent-review-god" in command
    assert "--persistent-execute-god" not in command


def test_runner_status_reports_process_counts_and_pid_file(tmp_path: Path) -> None:
    lanes_path = tmp_path / "xmuse" / "feature_lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    pid_file = tmp_path / "xmuse" / "runner.pid.json"
    write_pid_file(pid_file, pid=444, command=["runner"], log_path=tmp_path / "runner.log")

    status = runner_status(
        RunnerSupervisorConfig(repo_root=tmp_path, pid_file=pid_file, lanes_path=lanes_path),
        runner_pids=[444],
        mcp_pids=[555],
        live_pids={444, 555},
    )

    assert status["pid_file"]["pid"] == 444
    assert status["health"]["processes"]["runner_count"] == 1
    assert status["health"]["processes"]["mcp_count"] == 1


def test_runner_status_exposes_coordinator_dead_letters_and_degraded_incidents(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "xmuse"
    lanes_path = xmuse_root / "feature_lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    incidents_path = xmuse_root / "coordinator_incidents.jsonl"
    incidents_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "dead_letter",
                        "component": "blueprint_automation",
                        "operation": "tick",
                        "runner_id": "runner-1",
                        "created_at": 100.0,
                        "error_type": "RuntimeError",
                        "error": "planning failed",
                        "details": {"worker_id": "platform-runner"},
                    }
                ),
                json.dumps(
                    {
                        "kind": "degraded",
                        "component": "chat_driver",
                        "operation": "tick",
                        "runner_id": "runner-1",
                        "created_at": 101.0,
                        "error_type": "ValueError",
                        "error": "chat unavailable",
                        "details": {},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status = runner_status(
        RunnerSupervisorConfig(repo_root=tmp_path, pid_file=xmuse_root / "runner.pid.json"),
        runner_pids=[1],
        mcp_pids=[555],
        live_pids={1, 555},
    )

    assert status["health"]["coordinator"]["counts"] == {
        "dead_letter": 1,
        "degraded": 1,
        "lifecycle": 0,
    }
    assert status["health"]["coordinator"]["active_runner_ids"] == ["runner-1"]
    assert status["health"]["coordinator"]["active_counts"] == {
        "dead_letter": 1,
        "degraded": 1,
        "lifecycle": 0,
    }
    assert status["health"]["coordinator"]["latest_dead_letters"][0]["error"] == (
        "planning failed"
    )
    assert status["health"]["coordinator"]["latest_degraded"][0]["component"] == (
        "chat_driver"
    )


def test_runner_status_tolerates_unreadable_coordinator_incident_path(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "xmuse"
    lanes_path = xmuse_root / "feature_lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    (xmuse_root / "coordinator_incidents.jsonl").mkdir()

    status = runner_status(
        RunnerSupervisorConfig(repo_root=tmp_path, pid_file=xmuse_root / "runner.pid.json"),
        runner_pids=[444],
        mcp_pids=[555],
        live_pids={444, 555},
    )

    assert status["health"]["coordinator"]["counts"] == {
        "dead_letter": 0,
        "degraded": 0,
        "lifecycle": 0,
    }
    assert status["health"]["coordinator"]["read_error"]["type"] == "IsADirectoryError"
