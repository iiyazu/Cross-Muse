from __future__ import annotations

import signal
import sqlite3
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from tests.xmuse.test_workroom_cli import FakeRuntime
from xmuse import workroom
from xmuse_core.chat.memoryos_supervisor import (
    memoryos_incident_guard,
    read_memoryos_status,
    write_memoryos_status,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_memory_delivery_store import RoomMemoryDeliveryStore
from xmuse_core.chat.room_memory_rebuild_store import RoomMemoryRebuildActionStore


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    return executable


def _fixture(
    tmp_path: Path,
    *,
    expected_guard: str | None = None,
) -> tuple[
    FakeRuntime,
    workroom.WorkroomDependencies,
    workroom.WorkroomPaths,
    dict[str, object],
    workroom.MemoryOSRuntimeControl,
    RoomMemoryRebuildActionStore,
]:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    runtime = FakeRuntime(repo)
    dependencies = runtime.dependencies()
    paths = workroom.WorkroomPaths.resolve(root, repo)
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

    conversation_id = RoomTestStore(root / "chat.db").create_conversation("rebuild").id
    RoomMemoryDeliveryStore(root / "chat.db").ensure_binding(conversation_id=conversation_id)
    RoomKernelStore(root / "chat.db").post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="durable source",
        client_request_id="source",
    )
    with sqlite3.connect(root / "chat.db") as conn:
        conn.execute(
            """update room_memory_bindings
               set session_state = 'bound', session_id = 'old-session',
                   attachment_state = 'attached', attachment_id = 'old-attachment'"""
        )
        conn.execute(
            """update room_memory_outbox
               set state = 'delivered', delivered_at = '2026-07-12T00:00:00Z'"""
        )

    write_memoryos_status(
        root,
        enabled=True,
        state="degraded",
        code="memoryos_crash_loop",
        generation="generation-one",
        consecutive_restart_count=6,
    )
    status = read_memoryos_status(root)
    assert status is not None
    guard = expected_guard or memoryos_incident_guard(status)
    store = RoomMemoryRebuildActionStore(root / "chat.db")
    action, created = store.reserve(
        client_action_id="rebuild-one",
        request_fingerprint="fingerprint-one",
        incident_guard=guard,
        runtime_generation="generation-one",
        before_state="degraded",
        before_code="memoryos_crash_loop",
    )
    assert created is True and action["phase"] == "requested"
    paths.memoryos_derived_dir.mkdir(mode=0o700, parents=True)
    (paths.memoryos_derived_dir / "sentinel").write_bytes(b"derived-only")
    return runtime, dependencies, paths, manifest, control, store


def _reconcile(
    control: workroom.MemoryOSRuntimeControl,
    *,
    manifest: dict[str, object],
    paths: workroom.WorkroomPaths,
    dependencies: workroom.WorkroomDependencies,
    store: RoomMemoryRebuildActionStore,
) -> dict[str, object] | None:
    return workroom.reconcile_memoryos_rebuild_action(
        control,
        manifest=manifest,
        paths=paths,
        deps=dependencies,
        action_store=store,
    )


def test_changed_guard_is_rejected_before_process_or_cache_mutation(tmp_path: Path) -> None:
    runtime, dependencies, paths, manifest, control, store = _fixture(
        tmp_path, expected_guard="memoryos_incident_" + "0" * 32
    )

    result = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )

    assert result is not None
    assert result["status"] == "rejected"
    assert result["reason_code"] == "memoryos_rebuild_incident_changed"
    assert (paths.memoryos_derived_dir / "sentinel").read_bytes() == b"derived-only"
    assert runtime.group_signals == []
    assert runtime.specs == []


def test_unverifiable_live_identity_never_authorizes_stop_or_cache_clear(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control, store = _fixture(tmp_path)
    process = runtime.spawn(
        workroom.ProcessSpec(
            service="memoryos",
            command=(str(control.executable),),
            cwd=paths.memoryos_derived_dir,
            env={
                "XMUSE_ROOT": str(paths.xmuse_root),
                "XMUSE_WORKROOM_GENERATION": "generation-one",
                "XMUSE_WORKROOM_SERVICE": "memoryos",
            },
            log_path=paths.xmuse_root / "logs" / "memoryos.log",
        )
    )
    control.process = process
    control.record = {
        "service": "memoryos",
        "pid": process.pid,
        "pgid": process.pid,
        "start_identity": f"linux-proc-starttime:{process.pid}",
        "generation": "generation-one",
    }
    services = manifest["services"]
    assert isinstance(services, dict)
    services["memoryos"] = dict(control.record)
    workroom._atomic_write_manifest(paths.manifest, manifest)
    runtime.identities.pop(process.pid)

    result = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )

    assert result is not None
    assert result["status"] in {"requested", "failed"}
    assert (paths.memoryos_derived_dir / "sentinel").exists()
    assert runtime.group_signals == []
    assert len(runtime.specs) == 1


def test_exact_live_identity_runs_every_durable_phase_and_restarts_same_generation(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control, store = _fixture(tmp_path)
    workroom.reconcile_memoryos_runtime(control, manifest=manifest, paths=paths, deps=dependencies)
    assert control.process is not None and control.record is not None
    # Re-publish the rebuildable incident after the healthy bootstrap probe.
    write_memoryos_status(
        paths.xmuse_root,
        enabled=True,
        state="degraded",
        code="memoryos_crash_loop",
        generation="generation-one",
        pid=control.process.pid,
        start_identity=str(control.record["start_identity"]),
        consecutive_restart_count=6,
    )
    current = read_memoryos_status(paths.xmuse_root)
    assert current is not None
    # The action was reserved before the live identity existed; update only its
    # opaque guard to model the API's exact live-topology reservation.
    with sqlite3.connect(paths.xmuse_root / "chat.db") as conn:
        conn.execute(
            """update room_memory_rebuild_actions set incident_guard = ?
               where client_action_id = 'rebuild-one'""",
            (memoryos_incident_guard(current),),
        )

    phases = ["requested"]
    for _ in range(12):
        result = _reconcile(
            control,
            manifest=manifest,
            paths=paths,
            dependencies=dependencies,
            store=store,
        )
        assert result is not None
        phase = str(result["phase"])
        if phase != phases[-1]:
            phases.append(phase)
        if phase == "replaying":
            with sqlite3.connect(paths.xmuse_root / "chat.db") as conn:
                conn.execute(
                    """update room_memory_bindings
                       set session_state = 'bound', session_id = 'new-session',
                           attachment_state = 'attached', attachment_id = 'new-attachment'"""
                )
                conn.execute(
                    """update room_memory_outbox
                       set state = 'delivered', delivered_at = '2026-07-12T00:01:00Z'"""
                )
        if result["status"] == "applied":
            break

    assert phases == [
        "requested",
        "stopping",
        "stopped",
        "cache_cleared",
        "authority_reset",
        "restarting",
        "replaying",
        "complete",
    ]
    applied = store.get("rebuild-one")
    assert applied is not None
    assert applied["status"] == "applied"
    assert applied["result"]["cache_cleared"] is True
    assert not (paths.memoryos_derived_dir / "sentinel").exists()
    assert runtime.group_signals[0] == (201, signal.SIGTERM)
    memory_specs = [spec for spec in runtime.specs if spec.service == "memoryos"]
    assert len(memory_specs) == 2
    assert {spec.env["XMUSE_WORKROOM_GENERATION"] for spec in memory_specs} == {"generation-one"}
    assert {spec.env["MEMORYOS_API_KEY"] for spec in memory_specs} == {"generation-memory-key"}


def test_replaying_action_is_idempotently_finished_after_manager_resume(
    tmp_path: Path,
) -> None:
    _runtime, dependencies, paths, manifest, control, store = _fixture(tmp_path)
    store.advance(client_action_id="rebuild-one", expected_phase="requested", phase="stopping")
    store.advance(client_action_id="rebuild-one", expected_phase="stopping", phase="stopped")
    store.advance(
        client_action_id="rebuild-one",
        expected_phase="stopped",
        phase="cache_cleared",
        result={"cache_cleared": True},
    )
    store.reset_authority(client_action_id="rebuild-one")
    store.advance(
        client_action_id="rebuild-one",
        expected_phase="authority_reset",
        phase="restarting",
    )
    store.advance(
        client_action_id="rebuild-one",
        expected_phase="restarting",
        phase="replaying",
    )
    with sqlite3.connect(paths.xmuse_root / "chat.db") as conn:
        conn.execute(
            """update room_memory_bindings
               set session_state = 'bound', session_id = 'new-session',
                   attachment_state = 'attached', attachment_id = 'new-attachment'"""
        )
        conn.execute("update room_memory_outbox set state = 'delivered'")
    workroom.reconcile_memoryos_runtime(control, manifest=manifest, paths=paths, deps=dependencies)

    first = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )
    replay = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )

    assert first is not None and first["status"] == "applied"
    assert replay is None
    assert store.get("rebuild-one") == first


def test_partial_rebuild_resumes_safely_across_workroom_generation(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, _old_control, store = _fixture(tmp_path)
    store.advance(client_action_id="rebuild-one", expected_phase="requested", phase="stopping")
    store.advance(client_action_id="rebuild-one", expected_phase="stopping", phase="stopped")
    store.advance(
        client_action_id="rebuild-one",
        expected_phase="stopped",
        phase="cache_cleared",
        result={"cache_cleared": True},
    )
    manifest["generation"] = "generation-two"
    workroom._atomic_write_manifest(paths.manifest, manifest)
    control = workroom.MemoryOSRuntimeControl(
        executable=_executable(tmp_path),
        api_key="new-generation-key",
        url="http://127.0.0.1:8301",
    )
    workroom.reconcile_memoryos_runtime(control, manifest=manifest, paths=paths, deps=dependencies)

    resumed = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )

    assert resumed is not None and resumed["phase"] == "authority_reset"
    assert runtime.group_signals == [(201, signal.SIGTERM)]
    with sqlite3.connect(paths.xmuse_root / "chat.db") as conn:
        assert (
            conn.execute(
                "select count(*) from room_memory_bindings where session_state = 'unbound'"
            ).fetchone()[0]
            > 0
        )
        assert (
            conn.execute(
                "select count(*) from room_memory_outbox where state = 'pending'"
            ).fetchone()[0]
            > 0
        )


def test_cache_clear_reproves_empty_port_and_blocks_spawn_on_unsafe_cache(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control, store = _fixture(tmp_path)
    store.advance(client_action_id="rebuild-one", expected_phase="requested", phase="stopping")
    store.advance(client_action_id="rebuild-one", expected_phase="stopping", phase="stopped")
    sentinel = paths.memoryos_derived_dir / "sentinel"
    sentinel.unlink()
    paths.memoryos_derived_dir.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "preserve").write_bytes(b"authority")
    paths.memoryos_derived_dir.symlink_to(outside, target_is_directory=True)

    blocked = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )
    runtime_status = workroom.reconcile_memoryos_runtime(
        control, manifest=manifest, paths=paths, deps=dependencies
    )

    assert blocked is not None and blocked["status"] == "requested"
    assert blocked["phase"] == "stopped"
    assert runtime_status["code"] == "memoryos_derived_cache_unsafe"
    assert (outside / "preserve").read_bytes() == b"authority"
    assert runtime.specs == []


def test_cache_clear_does_not_cross_an_unknown_port_owner(tmp_path: Path) -> None:
    runtime, dependencies, paths, manifest, control, store = _fixture(tmp_path)
    store.advance(client_action_id="rebuild-one", expected_phase="requested", phase="stopping")
    store.advance(client_action_id="rebuild-one", expected_phase="stopping", phase="stopped")
    dependencies.port_available = lambda _host, _port: False

    blocked = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )

    assert blocked is not None and blocked["status"] == "requested"
    assert blocked["phase"] == "stopped"
    assert (paths.memoryos_derived_dir / "sentinel").read_bytes() == b"derived-only"
    assert runtime.group_signals == []
    assert runtime.specs == []


def test_stopping_workroom_generation_wins_without_advancing_rebuild(
    tmp_path: Path,
) -> None:
    runtime, dependencies, paths, manifest, control, store = _fixture(tmp_path)
    manifest["state"] = "stopping"
    workroom._atomic_write_manifest(paths.manifest, manifest)

    result = _reconcile(
        control,
        manifest=manifest,
        paths=paths,
        dependencies=dependencies,
        store=store,
    )

    assert result is None or result["phase"] == "requested"
    pending = store.get("rebuild-one")
    assert pending is not None and pending["phase"] == "requested"
    assert (paths.memoryos_derived_dir / "sentinel").exists()
    assert runtime.group_signals == []
    assert runtime.specs == []
