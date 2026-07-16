from __future__ import annotations

import json
from pathlib import Path

from tests.xmuse.test_workroom_cli import FakeRuntime
from xmuse import workroom
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomPaths
from xmuse_core.chat.memoryos_supervisor import read_memoryos_status


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    return executable


def _runtime_control(
    tmp_path: Path,
) -> tuple[
    FakeRuntime,
    WorkroomDependencies,
    WorkroomPaths,
    dict[str, object],
    workroom.MemoryOSRuntimeControl,
]:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "runtime-root"
    root.mkdir()
    runtime = FakeRuntime(repo)
    dependencies = runtime.dependencies()
    paths = WorkroomPaths.resolve(root, repo)
    manifest: dict[str, object] = {
        "schema_version": workroom.SCHEMA_VERSION,
        "generation": "generation-one",
        "state": "ready",
        "started_at": "2026-07-12T00:00:00Z",
        "updated_at": "2026-07-12T00:00:00Z",
        "services": {},
        "features": {"memoryos": True},
    }
    workroom._atomic_write_manifest(paths.manifest, manifest)
    control = workroom.MemoryOSRuntimeControl(
        executable=_executable(tmp_path),
        api_key="generation-memory-key",
        url="http://127.0.0.1:8301",
    )
    return runtime, dependencies, paths, manifest, control


def test_confirmed_dead_child_recovers_once_and_resets_after_sixty_healthy_seconds(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control = _runtime_control(tmp_path)

    first_status = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert first_status["state"] == "ready"
    assert [spec.service for spec in runtime.specs] == ["memoryos"]
    first = runtime.processes[201]
    first.returncode = 9
    runtime.identities.pop(201)

    recovering = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert recovering["state"] == "recovering"
    assert recovering["consecutive_restart_count"] == 1
    assert control.next_retry_monotonic == 1.0
    assert len(runtime.specs) == 1

    runtime.sleep(0.9)
    workroom.reconcile_memoryos_runtime(control, manifest=manifest, paths=paths, deps=dependencies)
    assert len(runtime.specs) == 1
    runtime.sleep(0.1)
    restarted = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert restarted["state"] == "ready"
    assert restarted["consecutive_restart_count"] == 1
    assert len(runtime.specs) == 2
    assert {spec.env["MEMORYOS_API_KEY"] for spec in runtime.specs} == {"generation-memory-key"}
    assert {spec.env["DATA_DIR"] for spec in runtime.specs} == {str(paths.memoryos_derived_dir)}

    runtime.sleep(60.0)
    stable = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert stable["state"] == "ready"
    assert stable["consecutive_restart_count"] == 0


def test_spawn_failures_follow_backoff_and_become_a_rebuildable_crash_loop(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control = _runtime_control(tmp_path)
    attempts: list[workroom.ProcessSpec] = []

    def fail_spawn(spec: workroom.ProcessSpec):
        attempts.append(spec)
        raise OSError("injected spawn failure")

    dependencies.spawn = fail_spawn
    expected_delays = [1, 2, 4, 8, 16, 30]
    for count, delay in enumerate(expected_delays, start=1):
        before = runtime.clock
        status = workroom.reconcile_memoryos_runtime(
            control, manifest=manifest, paths=paths, deps=dependencies
        )
        assert status["consecutive_restart_count"] == count
        assert control.next_retry_monotonic == before + delay
        assert status["code"] == ("memoryos_crash_loop" if count == 6 else "memoryos_spawn_failed")
        if count < len(expected_delays):
            runtime.sleep(delay)
    assert len(attempts) == 6
    assert all(spec.env["MEMORYOS_API_KEY"] == "generation-memory-key" for spec in attempts)


def test_unsafe_derived_cache_is_actionable_without_spawning(tmp_path: Path) -> None:
    runtime, dependencies, paths, manifest, control = _runtime_control(tmp_path)
    paths.memoryos_derived_dir.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.memoryos_derived_dir.symlink_to(outside, target_is_directory=True)

    status = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )

    assert status["state"] == "recovering"
    assert status["code"] == "memoryos_derived_cache_unsafe"
    assert runtime.specs == []


def test_live_unhealthy_or_unverifiable_child_is_never_replaced(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control = _runtime_control(tmp_path)
    workroom.reconcile_memoryos_runtime(control, manifest=manifest, paths=paths, deps=dependencies)
    assert len(runtime.specs) == 1

    runtime.ready = False
    unhealthy = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert unhealthy["code"] == "memoryos_health_unavailable"
    assert len(runtime.specs) == 1
    assert runtime.group_signals == []

    runtime.identities.pop(201)
    unknown = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert unknown["code"] == "memoryos_process_identity_unavailable"
    assert len(runtime.specs) == 1
    assert runtime.group_signals == []


def test_untracked_manifest_identity_never_authorizes_a_replacement(tmp_path: Path) -> None:
    runtime, dependencies, paths, manifest, control = _runtime_control(tmp_path)
    services = manifest["services"]
    assert isinstance(services, dict)
    services["memoryos"] = {
        "service": "memoryos",
        "pid": 777,
        "start_identity": "linux-proc-starttime:original",
        "generation": "generation-one",
    }
    runtime.identities[777] = workroom.ProcessIdentity(
        start_identity="linux-proc-starttime:reused",
        pgid=777,
        environment={
            "XMUSE_ROOT": str(paths.xmuse_root),
            "XMUSE_WORKROOM_GENERATION": "generation-one",
            "XMUSE_WORKROOM_SERVICE": "memoryos",
        },
    )
    workroom._atomic_write_manifest(paths.manifest, manifest)

    status = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert status["code"] == "memoryos_process_identity_mismatch"
    assert runtime.specs == []
    assert runtime.group_signals == []


def test_stop_manifest_state_wins_over_a_due_retry(tmp_path: Path) -> None:
    runtime, dependencies, paths, manifest, control = _runtime_control(tmp_path)
    attempts: list[workroom.ProcessSpec] = []

    def fail_spawn(spec: workroom.ProcessSpec):
        attempts.append(spec)
        raise OSError("first spawn fails")

    dependencies.spawn = fail_spawn
    workroom.reconcile_memoryos_runtime(control, manifest=manifest, paths=paths, deps=dependencies)
    runtime.sleep(1.0)
    manifest["state"] = "stopping"
    workroom._atomic_write_manifest(paths.manifest, manifest)

    stopped = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )
    assert stopped["state"] == "stopped"
    assert stopped["code"] == "memoryos_reconcile_not_current"
    assert len(attempts) == 1
    assert read_memoryos_status(paths.xmuse_root) is not None


def test_initial_spawn_failure_still_hands_fixed_capability_to_chat_api(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    standalone = repo / "frontend" / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("// built\n", encoding="utf-8")
    static = repo / "frontend" / ".next" / "static"
    static.mkdir(parents=True)
    (static / "chunk.js").write_text("built\n", encoding="utf-8")
    runtime = FakeRuntime(repo)
    dependencies = runtime.dependencies()
    dependencies.memory_key_factory = lambda: "generation-memory-key"
    original_spawn = dependencies.spawn

    def spawn(spec: workroom.ProcessSpec):
        if spec.service == "memoryos":
            raise OSError("injected first-spawn failure")
        return original_spawn(spec)

    dependencies.spawn = spawn
    paths = WorkroomPaths.resolve(tmp_path / "root", repo)
    assert (
        workroom.start_workroom(
            paths,
            dependencies,
            readiness_timeout_s=1.0,
            stop_timeout_s=1.0,
            memory_enabled=True,
            memoryos_executable=_executable(tmp_path),
        )
        == 0
    )

    assert [spec.service for spec in runtime.specs] == ["chat_api", "frontend"]
    chat, frontend = runtime.specs
    assert chat.env["XMUSE_MEMORYOS_URL"] == "http://127.0.0.1:8301"
    assert chat.env["XMUSE_MEMORYOS_API_KEY"] == "generation-memory-key"
    assert "XMUSE_MEMORYOS_API_KEY" not in frontend.env
    assert "generation-memory-key" not in json.dumps(
        json.loads(paths.manifest.read_text(encoding="utf-8"))
    )
    receipt = read_memoryos_status(paths.xmuse_root)
    assert receipt is not None
    assert receipt["state"] == "stopped"
