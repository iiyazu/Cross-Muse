from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from xmuse_core.chat import room_runtime_supervisor as supervisor
from xmuse_core.chat.room_operations import runtime_recoverability


class _Process:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def _config(tmp_path, **overrides) -> supervisor.RoomRuntimeSupervisorConfig:
    values = {
        "repo_root": tmp_path / "repo",
        "xmuse_root": tmp_path,
        "execution_worktree": tmp_path / "worktree",
        "generation": "generation-one",
        "mcp_port": 8199,
    }
    values.update(overrides)
    return supervisor.RoomRuntimeSupervisorConfig(**values)


def test_room_runtime_commands_are_room_only_and_preserve_delivery_contract(tmp_path) -> None:
    config = _config(tmp_path)

    runner = supervisor.room_runner_command(config)
    mcp = supervisor.room_mcp_command(config)

    assert runner[1] == "xmuse/room_runner.py"
    assert "platform_runner.py" not in runner
    assert runner[runner.index("--generation") + 1] == "generation-one"
    assert runner[runner.index("--delivery-timeout-s") + 1] == "180.0"
    assert "--max-hours" not in runner
    assert mcp[-2:] == ["--surface", "room"]


def test_inspection_passes_supported_time_and_requires_both_services(tmp_path, monkeypatch) -> None:
    inventory = {
        "services": [
            {"service": "room_runner", "pids": [101]},
            {"service": "room_mcp", "pids": [102]},
        ]
    }
    captured = {}
    monkeypatch.setattr(supervisor, "discover_xmuse_runtime_processes", lambda **_kwargs: inventory)
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda pid: f"identity-{pid}")

    def assess(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "ready": True,
            "code": "ready",
            "state": "ready",
            "status": {"boot_id": "boot-one"},
        }

    monkeypatch.setattr(supervisor, "assess_room_runner_status", assess)
    now = datetime(2026, 7, 11, tzinfo=UTC)

    result = supervisor.inspect_room_runtime(
        _config(tmp_path),
        now=now,
        http_health=lambda _url: {
            "status": "ok",
            "surface": "room",
            "endpoints": {"mcp_room": "/mcp/room"},
        },
    )

    assert result["ready"] is True
    assert result["state"] == "ready"
    assert result["boot_id"] == "boot-one"
    assert captured["now"] is now
    assert captured["expected_pid"] == 101
    assert captured["expected_start_identity"] == "identity-101"


def test_live_stale_runner_is_degraded_without_replacement(tmp_path, monkeypatch) -> None:
    stale = {
        "schema_version": supervisor.ROOM_RUNTIME_SCHEMA,
        "state": "degraded",
        "code": "heartbeat_stale",
        "ready": False,
        "services": {
            "room_runner": {
                "live": True,
                "ready": False,
                "pids": [101],
            },
            "room_mcp": {"live": True, "ready": True, "pids": [102]},
        },
    }
    monkeypatch.setattr(supervisor, "inspect_room_runtime", lambda *_a, **_k: stale)
    monkeypatch.setattr(
        supervisor,
        "_room_transport_pids",
        lambda _config: pytest.fail("live stale runner must retain its transports"),
    )

    result = supervisor.ensure_room_runtime(
        _config(tmp_path),
        popen=lambda *_a, **_k: pytest.fail("must not spawn over a live stale runner"),
    )

    assert result["state"] == "degraded"
    assert result["source"] == "live_process_degraded"


@pytest.mark.parametrize("receipt_state", ["starting", "stopping"])
def test_inspection_preserves_transitional_state_as_not_recoverable(
    tmp_path, monkeypatch, receipt_state
) -> None:
    monkeypatch.setattr(
        supervisor,
        "discover_xmuse_runtime_processes",
        lambda **_kwargs: {
            "services": [
                {"service": "room_runner", "pids": [101]},
                {"service": "room_mcp", "pids": [102]},
            ]
        },
    )
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda _pid: "identity")
    monkeypatch.setattr(
        supervisor,
        "assess_room_runner_status",
        lambda *_args, **_kwargs: {
            "ready": False,
            "code": "room_runner_state_not_ready",
            "state": receipt_state,
            "status": {"boot_id": "boot-one"},
            "host": {
                "state": "healthy",
                "code": "room_host_healthy",
                "active_delivery_count": 0,
                "retained_cleanup_count": 0,
            },
        },
    )

    runtime = supervisor.inspect_room_runtime(
        _config(tmp_path),
        http_health=lambda _url: {
            "status": "ok",
            "surface": "room",
            "endpoints": {"mcp_room": "/mcp/room"},
        },
    )

    assert runtime["state"] == receipt_state
    assert runtime_recoverability(runtime)["available"] is False


def test_confirmed_dead_runner_cleans_generation_scoped_orphan_transport(
    tmp_path,
    monkeypatch,
) -> None:
    stopped = {
        "ready": False,
        "state": "stopped",
        "services": {
            "room_runner": {"live": False, "ready": False, "pids": []},
            "room_mcp": {"live": False, "ready": False, "pids": []},
        },
    }
    monkeypatch.setattr(supervisor, "inspect_room_runtime", lambda *_a, **_k: stopped)
    monkeypatch.setattr(supervisor, "_room_transport_pids", lambda _config: [501])
    identity = {501: "identity-501"}
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda pid: identity.get(pid))
    monkeypatch.setattr(supervisor.os, "getpgid", lambda pid: pid)
    signals = []

    def signal_group(pid: int, signum: int) -> None:
        signals.append((pid, signum))
        identity.pop(pid, None)

    with pytest.raises(RuntimeError, match="stop after cleanup"):
        supervisor.ensure_room_runtime(
            _config(tmp_path),
            signal_group=signal_group,
            popen=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("stop after cleanup")),
        )

    assert [pid for pid, _signal in signals] == [501]


def test_successful_start_writes_fenced_pid_receipts_for_both_services(
    tmp_path,
    monkeypatch,
) -> None:
    stopped = {
        "ready": False,
        "state": "stopped",
        "services": {
            "room_runner": {"live": False, "ready": False, "pids": []},
            "room_mcp": {"live": False, "ready": False, "pids": []},
        },
    }
    ready = {
        "schema_version": supervisor.ROOM_RUNTIME_SCHEMA,
        "ready": True,
        "state": "ready",
        "code": "ready",
        "services": {
            "room_runner": {"live": True, "ready": True, "pids": [202]},
            "room_mcp": {"live": True, "ready": True, "pids": [201]},
        },
    }
    inspections = iter((stopped, ready))
    monkeypatch.setattr(supervisor, "inspect_room_runtime", lambda *_a, **_k: next(inspections))
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda pid: f"identity-{pid}")
    monkeypatch.setattr(
        supervisor,
        "assess_room_runner_status",
        lambda *_a, **_k: {"ready": True, "code": "ready"},
    )
    processes = iter((_Process(201), _Process(202)))
    child_environments = []
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "server-secret")
    monkeypatch.setenv("NEXT_PUBLIC_XMUSE_OPERATOR_TOKEN", "public-secret")
    monkeypatch.setenv("NEXT_PUBLIC_SESSION_TOKEN", "another-secret")
    monkeypatch.setenv("NEXT_PUBLIC_APP_NAME", "xmuse")
    monkeypatch.setenv("XMUSE_MEMORYOS_URL", "http://127.0.0.1:8301")
    monkeypatch.setenv("XMUSE_MEMORYOS_API_KEY", "memory-server-secret")

    def popen(*_args, **kwargs):
        child_environments.append(kwargs["env"])
        return next(processes)

    result = supervisor.ensure_room_runtime(
        _config(tmp_path),
        popen=popen,
        http_health=lambda _url: {
            "status": "ok",
            "surface": "room",
            "endpoints": {"mcp_room": "/mcp/room"},
        },
    )

    assert result["ready"] is True
    runner_receipt = json.loads(
        (tmp_path / "workroom_room_runner.pid.json").read_text(encoding="utf-8")
    )
    mcp_receipt = json.loads((tmp_path / "workroom_room_mcp.pid.json").read_text(encoding="utf-8"))
    assert runner_receipt["start_identity"] == "identity-202"
    assert mcp_receipt["start_identity"] == "identity-201"
    assert mcp_receipt["command"][-2:] == ["--surface", "room"]
    assert len(child_environments) == 2
    assert all("XMUSE_OPERATOR_TOKEN" not in env for env in child_environments)
    assert all("NEXT_PUBLIC_XMUSE_OPERATOR_TOKEN" not in env for env in child_environments)
    assert all("NEXT_PUBLIC_SESSION_TOKEN" not in env for env in child_environments)
    assert all(env["NEXT_PUBLIC_APP_NAME"] == "xmuse" for env in child_environments)
    mcp_environment, runner_environment = child_environments
    assert "XMUSE_MEMORYOS_URL" not in mcp_environment
    assert "XMUSE_MEMORYOS_API_KEY" not in mcp_environment
    assert runner_environment["XMUSE_MEMORYOS_URL"] == "http://127.0.0.1:8301"
    assert runner_environment["XMUSE_MEMORYOS_API_KEY"] == "memory-server-secret"


def test_failed_start_cleans_both_new_process_groups_and_pid_files(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config(tmp_path, startup_wait_s=0.1)
    stopped = {
        "ready": False,
        "state": "stopped",
        "services": {
            "room_runner": {"live": False, "ready": False, "pids": []},
            "room_mcp": {"live": False, "ready": False, "pids": []},
        },
    }
    monkeypatch.setattr(supervisor, "inspect_room_runtime", lambda *_a, **_k: stopped)
    identities = {301: "identity-301", 302: "identity-302"}
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda pid: identities.get(pid))
    monkeypatch.setattr(supervisor.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        supervisor,
        "assess_room_runner_status",
        lambda *_a, **_k: {"ready": False, "code": "status_missing"},
    )
    processes = {301: _Process(301), 302: _Process(302)}
    spawned = iter((processes[301], processes[302]))
    clock = [0.0]
    signals = []

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    def signal_group(pid: int, signum: int) -> None:
        signals.append((pid, signum))
        identities.pop(pid, None)
        processes[pid].returncode = -signum

    with pytest.raises(supervisor.RoomRuntimeStartError) as raised:
        supervisor.ensure_room_runtime(
            config,
            popen=lambda *_a, **_k: next(spawned),
            signal_group=signal_group,
            sleep=sleep,
            monotonic=lambda: clock[0],
            http_health=lambda _url: {
                "status": "ok",
                "surface": "room",
                "endpoints": {"mcp_room": "/mcp/room"},
            },
        )

    assert raised.value.code == "room_runner_readiness_timeout"
    assert [pid for pid, _signal in signals] == [302, 301]
    assert not (tmp_path / "workroom_room_runner.pid.json").exists()
    assert not (tmp_path / "workroom_room_mcp.pid.json").exists()


def test_stop_fences_pid_reuse_before_signalling(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        supervisor,
        "discover_xmuse_runtime_processes",
        lambda **_kwargs: {"services": [{"service": "room_runner", "pids": [401]}]},
    )
    reads = iter(("old-identity", "new-identity", "new-identity"))
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda _pid: next(reads))
    signals = []

    result = supervisor.stop_room_runtime(
        _config(tmp_path),
        signal_process=lambda pid, signum: signals.append((pid, signum)),
        signal_group=lambda pid, signum: signals.append((pid, signum)),
        sleep=lambda _seconds: None,
    )

    assert result["state"] == "stopped"
    assert signals == []


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "failed", "surface": "room", "endpoints": {"mcp_room": "/mcp/room"}},
        {"status": "ok", "surface": "compat", "endpoints": {"mcp_room": "/mcp/room"}},
        {"status": "ok", "surface": "room", "endpoints": {}},
    ],
)
def test_room_mcp_health_validator_rejects_non_ready_contract(payload) -> None:
    assert supervisor.room_mcp_health_ready(payload) is False
