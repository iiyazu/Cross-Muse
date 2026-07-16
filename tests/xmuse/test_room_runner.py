from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xmuse import room_runner, room_runner_composition, room_runner_memory
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_store import RoomExecutionStore
from xmuse_core.chat.room_host import RoomParticipantHost, RoomTransportResult
from xmuse_core.chat.room_runtime import (
    ROOM_RUNNER_PROOF_BOUNDARY,
    ROOM_RUNNER_READINESS_KEYS,
    ROOM_RUNNER_STATUS_SCHEMA,
    RoomRunnerStatusError,
    assess_room_runner_status,
    read_process_start_identity,
    read_room_runner_status,
    write_room_runner_status,
)
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog


def _readiness(value: bool = True) -> dict[str, bool]:
    return {key: value for key in ROOM_RUNNER_READINESS_KEYS}


def _host(
    state: str = "healthy",
    code: str = "ready",
    *,
    active: int = 0,
    retained: int = 0,
) -> dict[str, Any]:
    return {
        "state": state,
        "code": code,
        "active_delivery_count": active,
        "retained_cleanup_count": retained,
    }


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def test_process_identity_treats_linux_zombie_as_not_live(monkeypatch) -> None:
    state = ["Z"]

    def fake_stat(_path: Path, *, encoding: str) -> str:
        assert encoding == "utf-8"
        fields = [state[0], *("0" for _ in range(18)), "12345"]
        return f"42 (xmuse room runner) {' '.join(fields)}"

    monkeypatch.setattr(Path, "read_text", fake_stat)

    assert read_process_start_identity(42) is None
    state[0] = "S"
    assert read_process_start_identity(42) == "linux-proc-starttime:12345"


def test_status_write_read_assess_round_trip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    identity = read_process_start_identity(os.getpid())
    assert identity is not None

    written = write_room_runner_status(
        tmp_path,
        generation="generation-1",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-1",
        state="ready",
        started_at=_stamp(now - timedelta(seconds=1)),
        mcp_port=8100,
        readiness=_readiness(),
        host=_host(),
        now=now,
    )

    assert read_room_runner_status(tmp_path) == written
    assert written["schema_version"] == ROOM_RUNNER_STATUS_SCHEMA
    assert written["proof_boundary"] == ROOM_RUNNER_PROOF_BOUNDARY
    assert written["mcp"] == {"surface": "room", "path": "/mcp/room", "port": 8100}
    assert written["host"] == _host()
    assessment = assess_room_runner_status(
        tmp_path,
        expected_generation="generation-1",
        expected_pid=os.getpid(),
        expected_start_identity=identity,
        now=now,
    )
    assert assessment["ready"] is True
    assert assessment["code"] == "ready"
    assert assessment["host"] == _host()


def test_status_assessment_accepts_exact_v1_as_unknown_host(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    payload = write_room_runner_status(
        tmp_path,
        generation="generation-v1",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-v1",
        state="ready",
        started_at=_stamp(now - timedelta(seconds=1)),
        mcp_port=8100,
        readiness=_readiness(),
        host=_host(),
        now=now,
    )
    payload["schema_version"] = "room_runner_status/v1"
    payload["xmuse_root"] = str(tmp_path)
    payload.pop("host")
    (tmp_path / "room-runner-status.json").write_text(json.dumps(payload), encoding="utf-8")

    assessment = assess_room_runner_status(
        tmp_path,
        expected_generation="generation-v1",
        expected_pid=os.getpid(),
        expected_start_identity=identity,
        now=now,
    )

    assert assessment["ready"] is True
    assert assessment["code"] == "ready"
    assert assessment["host"] == {
        "state": "unknown",
        "code": "room_runner_host_health_unknown",
        "active_delivery_count": 0,
        "retained_cleanup_count": 0,
    }
    assert "host" not in assessment["status"]
    assert assessment["status"]["xmuse_root"] == str(tmp_path)


def test_v2_status_omits_local_workspace_path(tmp_path: Path) -> None:
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    payload = write_room_runner_status(
        tmp_path,
        generation="generation-safe-receipt",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-safe-receipt",
        state="ready",
        started_at=_stamp(datetime.now(UTC)),
        mcp_port=8100,
        readiness=_readiness(),
        host=_host(),
    )

    assert payload["schema_version"] == ROOM_RUNNER_STATUS_SCHEMA
    assert "xmuse_root" not in payload
    assert str(tmp_path) not in json.dumps(payload, sort_keys=True)


@pytest.mark.parametrize(
    ("host", "ready", "code"),
    [
        (_host("attention", "room_transport_cleanup_pending", retained=1), True, "ready"),
        (_host("attention", "room_memory_degraded"), True, "ready"),
        (_host("blocked", "room_skill_catalog_drift"), False, "room_runner_host_blocked"),
    ],
)
def test_status_assessment_applies_v2_host_health(
    tmp_path: Path,
    host: dict[str, Any],
    ready: bool,
    code: str,
) -> None:
    now = datetime.now(UTC)
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    write_room_runner_status(
        tmp_path,
        generation="generation-host",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-host",
        state="ready",
        started_at=_stamp(now - timedelta(seconds=1)),
        mcp_port=8100,
        readiness=_readiness(),
        host=host,
        now=now,
    )

    assessment = assess_room_runner_status(
        tmp_path,
        expected_generation="generation-host",
        now=now,
    )

    assert assessment["ready"] is ready
    assert assessment["code"] == code
    assert assessment["host"] == host


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"provider_output": "secret"}),
        lambda payload: payload.update({"schema_version": "room_runner_status/v1"}),
        lambda payload: payload.pop("host"),
        lambda payload: payload["host"].update({"lease_token": "secret"}),
        lambda payload: payload["host"].update({"active_delivery_count": True}),
        lambda payload: payload["host"].update({"retained_cleanup_count": 2**31}),
        lambda payload: payload["host"].update({"state": "unknown"}),
        lambda payload: payload["host"].update(
            {"state": "healthy", "code": "room_skill_catalog_drift"}
        ),
    ],
)
def test_status_assessment_rejects_forged_v2_host_fields(
    tmp_path: Path,
    mutate,
) -> None:
    now = datetime.now(UTC)
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    payload = write_room_runner_status(
        tmp_path,
        generation="generation-forged-host",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-forged-host",
        state="ready",
        started_at=_stamp(now - timedelta(seconds=1)),
        mcp_port=8100,
        readiness=_readiness(),
        host=_host(),
        now=now,
    )
    mutate(payload)
    (tmp_path / "room-runner-status.json").write_text(json.dumps(payload), encoding="utf-8")

    assessment = assess_room_runner_status(
        tmp_path,
        expected_generation="generation-forged-host",
        now=now,
    )

    assert assessment["ready"] is False
    assert assessment["code"] in {
        "room_runner_status_invalid_shape",
        "room_runner_host_invalid",
    }


def test_status_assessment_rejects_stale_forged_and_wrong_generation(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    write_room_runner_status(
        tmp_path,
        generation="generation-1",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-1",
        state="ready",
        started_at=_stamp(now - timedelta(seconds=40)),
        mcp_port=8100,
        readiness=_readiness(),
        host=_host(),
        now=now - timedelta(seconds=30),
    )
    assert (
        assess_room_runner_status(
            tmp_path,
            expected_generation="generation-1",
            now=now,
        )["code"]
        == "room_runner_heartbeat_stale"
    )
    assert (
        assess_room_runner_status(
            tmp_path,
            expected_generation="generation-2",
            now=now - timedelta(seconds=30),
        )["code"]
        == "room_runner_generation_mismatch"
    )
    forged = assess_room_runner_status(
        tmp_path,
        expected_generation="generation-1",
        now=now - timedelta(seconds=30),
        process_identity_reader=lambda _pid: "linux-proc-starttime:forged",
    )
    assert forged["ready"] is False
    assert forged["code"] == "room_runner_process_identity_mismatch"


def test_status_assessment_rejects_custom_path_symlink(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    write_room_runner_status(
        tmp_path,
        generation="generation-symlink",
        pid=os.getpid(),
        start_identity=identity,
        boot_id="boot-symlink",
        state="ready",
        started_at=_stamp(now - timedelta(seconds=1)),
        mcp_port=8100,
        readiness=_readiness(),
        host=_host(),
        now=now,
    )
    custom_path = tmp_path / "custom-status.json"
    custom_path.symlink_to(tmp_path / "room-runner-status.json")

    assessment = assess_room_runner_status(
        tmp_path,
        expected_generation="generation-symlink",
        status_path=custom_path,
        now=now,
    )

    assert assessment["ready"] is False
    assert assessment["code"] == "room_runner_status_symlink_rejected"


def test_status_refuses_ready_without_every_readiness_proof(tmp_path: Path) -> None:
    identity = read_process_start_identity(os.getpid())
    assert identity is not None
    incomplete = _readiness()
    incomplete["mcp_tools"] = False

    with pytest.raises(RoomRunnerStatusError) as exc_info:
        write_room_runner_status(
            tmp_path,
            generation="generation-1",
            pid=os.getpid(),
            start_identity=identity,
            boot_id="boot-1",
            state="ready",
            started_at=_stamp(datetime.now(UTC)),
            mcp_port=8100,
            readiness=incomplete,
            host=_host(),
        )

    assert exc_info.value.code == "room_runner_ready_invalid"


def test_process_lock_rejects_second_runner_for_same_root(tmp_path: Path) -> None:
    with room_runner._room_runner_lock(tmp_path, generation="generation-1"):
        with pytest.raises(room_runner.RoomRunnerError) as exc_info:
            with room_runner._room_runner_lock(tmp_path, generation="generation-2"):
                raise AssertionError("second lock must not be acquired")
    assert exc_info.value.code == "room_runner_already_running"


def test_runtime_composition_shares_one_execution_store_across_host_and_transport(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    RoomDatabase(db_path).initialize()
    execution_store = RoomExecutionStore(db_path)
    memory_runtime, memory_enabled = room_runner_memory.compose_room_runner_memory(
        db_path,
        worker_id="memory-composition-test",
        environ={},
    )

    composition = room_runner_composition.compose_room_runtime(
        root=tmp_path,
        worktree=tmp_path,
        launchers={},
        controls=RoomObservationControlStore(db_path),
        skill_decisions=RoomAttemptSkillDecisionStore(db_path),
        skill_catalog=SkillCatalog.load_bundled(),
        execution_store=execution_store,
        max_concurrent_rooms=1,
        delivery_timeout_s=10,
        cleanup_grace_s=1,
        runner_generation="generation-execution-store",
        runner_boot_id="boot-execution-store",
        memory_runtime=memory_runtime,
        memory_enabled=memory_enabled,
    )

    assert composition.host._execution_store is execution_store
    assert composition.host._transport._execution_store is execution_store


def test_memory_runtime_composition_is_opt_in_and_api_key_repr_is_redacted(
    tmp_path: Path,
) -> None:
    from xmuse.memoryos_runtime_adapter import (
        DisabledRoomMemoryRuntime,
        MemoryOSRoomMemoryRuntime,
    )

    db_path = tmp_path / "chat.db"
    RoomDatabase(db_path).initialize()

    disabled, enabled = room_runner_memory.compose_room_runner_memory(
        db_path,
        worker_id="memory-worker-disabled",
        environ={},
    )
    assert enabled is False
    assert isinstance(disabled, DisabledRoomMemoryRuntime)

    active, enabled = room_runner_memory.compose_room_runner_memory(
        db_path,
        worker_id="memory-worker-enabled",
        environ={
            "XMUSE_MEMORYOS_URL": "http://127.0.0.1:8301",
            "XMUSE_MEMORYOS_API_KEY": "memory-server-secret",
        },
    )
    assert enabled is True
    assert isinstance(active, MemoryOSRoomMemoryRuntime)
    assert "memory-server-secret" not in repr(active)
    assert "memory-server-secret" not in repr(active._delivery_pump._client)


def test_memory_pump_failure_only_marks_host_attention(tmp_path: Path) -> None:
    class FailingMemoryRuntime:
        async def pump_once(self):
            stop.set()
            raise OSError("sidecar stopped")

    class UnusedTransport:
        async def deliver(self, _delivery, *, timeout_s):
            del timeout_s
            return RoomTransportResult("failed", "unused")

    stop = asyncio.Event()
    host = RoomParticipantHost(tmp_path / "chat.db", UnusedTransport())

    asyncio.run(
        room_runner_memory.run_room_memory_pump(
            FailingMemoryRuntime(),  # type: ignore[arg-type]
            report_attention=host.set_memory_runtime_attention,
            stop=stop,
        )
    )

    assert host.runtime_health_snapshot()["state"] == "attention"
    assert host.runtime_health_snapshot()["code"] == "room_memory_degraded"


def test_room_codex_home_copies_only_auth_and_retains_session_state(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "ambient-codex"
    source_home.mkdir()
    source_auth = source_home / "auth.json"
    source_auth.write_bytes(b'{"token":"first-test-token"}')
    (source_home / "config.toml").write_text(
        '[mcp_servers.node_repl]\ncommand = "node"\n',
        encoding="utf-8",
    )
    (source_home / "plugins").mkdir()
    (source_home / "skills").mkdir()

    root = tmp_path / "xmuse-root"
    isolated_home = room_runner._prepare_room_codex_home(
        root,
        source_home=source_home,
    )

    assert isolated_home == root / "runtime" / "room-codex-home"
    assert {path.name for path in isolated_home.iterdir()} == {"auth.json"}
    assert stat.S_IMODE(isolated_home.stat().st_mode) == 0o700
    assert stat.S_IMODE((isolated_home / "auth.json").stat().st_mode) == 0o600
    assert (isolated_home / "auth.json").read_bytes() == source_auth.read_bytes()

    session_state = isolated_home / "sessions" / "room-thread.jsonl"
    session_state.parent.mkdir()
    session_state.write_text("persistent-room-thread", encoding="utf-8")
    source_auth.write_bytes(b'{"token":"second-test-token"}')
    room_runner._prepare_room_codex_home(root, source_home=source_home)

    assert (isolated_home / "auth.json").read_bytes() == source_auth.read_bytes()
    assert session_state.read_text(encoding="utf-8") == "persistent-room-thread"
    assert not (isolated_home / "config.toml").exists()
    assert not (isolated_home / "plugins").exists()
    assert not (isolated_home / "skills").exists()


def test_room_runner_reaches_ready_and_stops_without_control_plane_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ambient_home = tmp_path / "ambient-codex"
    ambient_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(ambient_home))
    startup_fenced = False
    original_fence = RoomParticipantHost.fence_prior_runner_attempts
    original_write_status = room_runner._write_status

    def fence_before_ready(host) -> dict[str, Any] | None:
        nonlocal startup_fenced
        result = original_fence(host)
        startup_fenced = True
        return result

    def assert_fence_precedes_ready(*args, **kwargs) -> None:
        if kwargs.get("state") == "ready":
            assert startup_fenced
        original_write_status(*args, **kwargs)

    monkeypatch.setattr(
        RoomParticipantHost,
        "fence_prior_runner_attempts",
        fence_before_ready,
    )
    monkeypatch.setattr(room_runner, "_write_status", assert_fence_precedes_ready)

    async def scenario() -> None:
        root = tmp_path / "runtime"
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        stop = asyncio.Event()
        task = asyncio.create_task(
            room_runner.run_room_runner(
                xmuse_root=root,
                generation="generation-live",
                mcp_port=18100,
                max_concurrent_rooms=2,
                delivery_timeout_s=1.0,
                cleanup_grace_s=0.1,
                worktree=worktree,
                shutdown=stop,
                mcp_probe=lambda _host, _port: (True, True),
                executable_resolver=lambda _command: "/usr/bin/codex",
            )
        )
        deadline = asyncio.get_running_loop().time() + 5
        while True:
            if task.done():
                task.result()
            status = read_room_runner_status(root)
            if status is not None and status["state"] == "ready":
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("Room Runner did not become ready")
            await asyncio.sleep(0.01)

        assessment = assess_room_runner_status(
            root,
            expected_generation="generation-live",
            expected_pid=os.getpid(),
        )
        assert assessment["ready"] is True
        assert startup_fenced is True
        assert status["readiness"] == _readiness()
        assert status["host"] == _host()
        stop.set()
        await asyncio.wait_for(task, timeout=5)
        stopped = read_room_runner_status(root)
        assert stopped is not None
        assert stopped["state"] == "stopped"
        assert stopped["error"] is None
        assert not (root / "feature_lanes.json").exists()
        assert not (root / "platform-runner-writer-lease.json").exists()

    asyncio.run(scenario())


def test_heartbeat_samples_fresh_host_health_each_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(room_runner, "ROOM_RUNNER_HEARTBEAT_INTERVAL_S", 0.001)
    written_hosts: list[dict[str, Any]] = []
    stop = asyncio.Event()

    def snapshot() -> dict[str, Any]:
        return _host(
            "attention",
            "room_transport_cleanup_pending",
            retained=len(written_hosts) + 1,
        )

    def capture_status(*args, **kwargs) -> None:
        del args
        written_hosts.append(dict(kwargs["host"]))
        if len(written_hosts) == 2:
            stop.set()

    monkeypatch.setattr(room_runner, "_write_status", capture_status)

    asyncio.run(
        room_runner._heartbeat_loop(
            tmp_path,
            generation="generation-heartbeat-host",
            process_identity="linux-proc-starttime:1",
            boot_id="boot-heartbeat-host",
            started_at="2026-07-11T00:00:00Z",
            mcp_port=8100,
            readiness=_readiness(),
            receipt_state={"state": "ready", "error_code": None},
            host_health_snapshot=snapshot,
            stop=stop,
        )
    )

    assert [item["retained_cleanup_count"] for item in written_hosts] == [1, 2]


def test_heartbeat_write_failure_stops_runner_and_publishes_failed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ambient_home = tmp_path / "ambient-codex"
    ambient_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(ambient_home))
    monkeypatch.setattr(room_runner, "ROOM_RUNNER_HEARTBEAT_INTERVAL_S", 0.01)
    original_write_status = room_runner._write_status
    writes = 0

    def flaky_write_status(*args, **kwargs) -> None:
        nonlocal writes
        writes += 1
        if writes == 3:
            raise room_runner.RoomRunnerError("room_runner_status_write_failed")
        original_write_status(*args, **kwargs)

    monkeypatch.setattr(room_runner, "_write_status", flaky_write_status)
    root = tmp_path / "xmuse-root"
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        asyncio.run(
            room_runner.run_room_runner(
                xmuse_root=root,
                generation="generation-heartbeat-failure",
                worktree=worktree,
                mcp_probe=lambda _host, _port: (True, True),
                executable_resolver=lambda _command: "/usr/bin/codex",
            )
        )

    assert exc_info.value.code == "room_runner_status_write_failed"
    status = read_room_runner_status(root)
    assert status is not None
    assert status["state"] == "failed"
    assert status["error"] == {"code": "room_runner_status_write_failed"}


def test_missing_codex_executable_publishes_failed_not_ready_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        asyncio.run(
            room_runner.run_room_runner(
                xmuse_root=root,
                generation="generation-missing-codex",
                worktree=worktree,
                mcp_probe=lambda _host, _port: (True, True),
                executable_resolver=lambda _command: None,
            )
        )

    assert exc_info.value.code == "room_runner_codex_executable_unavailable"
    status = read_room_runner_status(root)
    assert status is not None
    assert status["state"] == "failed"
    assert status["readiness"]["persistent_launcher"] is False
    assert status["error"] == {"code": "room_runner_codex_executable_unavailable"}


def test_startup_failure_publishes_failed_not_ready_receipt(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "chat.db").write_bytes(b"not a sqlite database")
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        asyncio.run(
            room_runner.run_room_runner(
                xmuse_root=root,
                generation="generation-failed",
                worktree=worktree,
                mcp_probe=lambda _host, _port: (True, True),
            )
        )

    assert exc_info.value.code == "room_runner_chat_db_unavailable"
    status = read_room_runner_status(root)
    assert status is not None
    assert status["state"] == "failed"
    assert status["error"] == {"code": "room_runner_chat_db_unavailable"}
    assert status["readiness"]["chat_db"] is False
    assert (
        assess_room_runner_status(
            root,
            expected_generation="generation-failed",
        )["ready"]
        is False
    )


def test_room_mcp_probe_requires_room_health_and_exact_outcome_tool(monkeypatch) -> None:
    class _Response:
        def __init__(self, payload: Any) -> None:
            self._raw = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return self._raw[:limit]

    def urlopen(request, *, timeout: float):
        del timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/health"):
            return _Response(
                {
                    "status": "ok",
                    "surface": "room",
                    "endpoints": {"mcp_room": "/mcp/room"},
                }
            )
        return _Response(
            {
                "jsonrpc": "2.0",
                "id": "room-runner-readiness",
                "result": {"tools": [{"name": "chat_room_submit_outcome"}]},
            }
        )

    monkeypatch.setattr(room_runner.urllib.request, "urlopen", urlopen)
    assert room_runner._probe_room_mcp_once("127.0.0.1", 8100) == (True, True)


def test_cli_has_no_artificial_runtime_deadline(monkeypatch) -> None:
    monkeypatch.delenv("XMUSE_WORKROOM_GENERATION", raising=False)
    args = room_runner.main_arg_parser().parse_args([])

    assert args.delivery_timeout_s == 180.0
    assert args.cleanup_grace_s == 8.0
    assert not hasattr(args, "max_hours")


def test_importing_room_runner_does_not_load_control_plane_modules() -> None:
    script = """
import json
import sys
import xmuse.room_runner
forbidden = sorted(
    name for name in sys.modules
    if name.startswith('xmuse.compat')
    or name.startswith('xmuse_core.platform')
    or name.startswith('xmuse_core.structuring')
    or name.startswith('xmuse_core.self_evolution')
    or name == 'xmuse_core.chat.compat_api_models'
    or name.startswith('xmuse_core.integrations.a2a')
    or name.startswith('a2a')
)
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )

    assert json.loads(result.stdout) == []
