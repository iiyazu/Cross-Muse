from __future__ import annotations

import ast
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from tests.xmuse.test_workroom_cli import FakeRuntime
from xmuse import workroom_memoryos_runtime as memory_runtime
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomError, WorkroomPaths
from xmuse.workroom_manifest import atomic_write_manifest
from xmuse.workroom_memoryos import MemoryOSRuntimeControl
from xmuse.workroom_processes import ProcessIdentity
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


def _coordinator(
    tmp_path: Path,
    *,
    profile: str = "archive-only",
) -> tuple[FakeRuntime, MemoryOSRuntimeCoordinatorFixture]:
    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "runtime-root"
    root.mkdir()
    runtime = FakeRuntime(repo)
    dependencies = runtime.dependencies()
    paths = WorkroomPaths.resolve(root, repo)
    manifest: dict[str, object] = {
        "schema_version": "xmuse_workroom_runtime/v1",
        "generation": "generation-one",
        "state": "ready",
        "started_at": "2026-07-12T00:00:00Z",
        "updated_at": "2026-07-12T00:00:00Z",
        "services": {},
        "features": {"memoryos": True},
    }
    atomic_write_manifest(paths.manifest, manifest)
    control = MemoryOSRuntimeControl(
        executable=_executable(tmp_path),
        api_key="generation-memory-key",
        url="http://127.0.0.1:8301",
        profile=profile,  # type: ignore[arg-type]
    )
    coordinator = memory_runtime.MemoryOSRuntimeCoordinator(
        control=control,
        manifest=manifest,
        paths=paths,
        deps=dependencies,
    )
    return runtime, MemoryOSRuntimeCoordinatorFixture(
        dependencies=dependencies,
        paths=paths,
        manifest=manifest,
        control=control,
        coordinator=coordinator,
    )


class MemoryOSRuntimeCoordinatorFixture:
    def __init__(
        self,
        *,
        dependencies: WorkroomDependencies,
        paths: WorkroomPaths,
        manifest: dict[str, object],
        control: MemoryOSRuntimeControl,
        coordinator: memory_runtime.MemoryOSRuntimeCoordinator,
    ) -> None:
        self.dependencies = dependencies
        self.paths = paths
        self.manifest = manifest
        self.control = control
        self.coordinator = coordinator


def test_module_does_not_import_the_workroom_facade() -> None:
    tree = ast.parse(inspect.getsource(memory_runtime))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "xmuse.workroom" not in imports


def test_factory_maps_invalid_executable_to_stable_workroom_error(tmp_path: Path) -> None:
    _runtime, fixture = _coordinator(tmp_path)

    with pytest.raises(WorkroomError) as raised:
        memory_runtime.MemoryOSRuntimeCoordinator.create(
            executable=tmp_path / "missing-memoryos",
            profile="full-local",
            api_key="generation-memory-key",
            manifest=fixture.manifest,
            paths=fixture.paths,
            deps=fixture.dependencies,
        )

    assert raised.value.code == "memoryos_executable_invalid"


def test_factory_binding_and_coordinator_repr_never_disclose_key_or_control(
    tmp_path: Path,
) -> None:
    _runtime, fixture = _coordinator(tmp_path)
    coordinator = memory_runtime.MemoryOSRuntimeCoordinator.create(
        executable=_executable(tmp_path),
        profile="full-local",
        api_key="generation-memory-key",
        manifest=fixture.manifest,
        paths=fixture.paths,
        deps=fixture.dependencies,
    )

    binding = coordinator.chat_api_binding()
    rendered = f"{coordinator!r} {binding!r}"

    assert binding.url == "http://127.0.0.1:8301"
    assert binding.api_key == "generation-memory-key"
    assert binding.profile == "full-local"
    assert "generation-memory-key" not in rendered
    assert "control" not in rendered.lower()
    assert str(fixture.paths.xmuse_root) not in rendered
    RoomTestStore(fixture.paths.xmuse_root / "chat.db").create_conversation("factory-store")
    assert coordinator.reconcile_rebuild_action() is None


def test_disabled_and_stopped_receipts_return_only_safe_lifecycle_evidence(
    tmp_path: Path,
) -> None:
    _runtime, fixture = _coordinator(tmp_path)

    disabled = memory_runtime.record_memoryos_disabled(
        fixture.manifest,
        fixture.paths,
        fixture.dependencies,
    )
    stopped = memory_runtime.record_memoryos_stopped(
        fixture.manifest,
        fixture.paths,
        fixture.dependencies,
    )

    assert disabled["state"] == "disabled"
    assert stopped["state"] == "stopped"
    for status in (disabled, stopped):
        assert "generation" not in status
        assert "pid" not in status
        assert "start_identity" not in status
        assert str(fixture.paths.xmuse_root) not in json.dumps(status)


def test_recorded_memoryos_stop_signals_only_the_exact_generation_identity(
    tmp_path: Path,
) -> None:
    runtime, fixture = _coordinator(tmp_path)
    fixture.coordinator.reconcile()

    result = memory_runtime.stop_recorded_memoryos(
        fixture.manifest,
        fixture.paths,
        fixture.dependencies,
        timeout_s=1.0,
    )

    assert result["stopped"] is True
    assert result["code"] == "memoryos_stopped"
    assert result["status"]["state"] == "stopped"
    assert runtime.group_signals == [(201, 15)]
    assert "pid" not in result["status"]
    assert "start_identity" not in result["status"]


def test_recorded_memoryos_stop_fails_closed_for_pid_reuse(tmp_path: Path) -> None:
    runtime, fixture = _coordinator(tmp_path)
    fixture.coordinator.reconcile()
    original = runtime.identities[201]
    runtime.identities[201] = ProcessIdentity(
        start_identity="linux-proc-starttime:reused",
        pgid=201,
        environment=original.environment,
    )

    result = memory_runtime.stop_recorded_memoryos(
        fixture.manifest,
        fixture.paths,
        fixture.dependencies,
        timeout_s=1.0,
    )

    assert result == {
        "stopped": False,
        "code": "memoryos_process_identity_mismatch",
        "status": None,
    }
    assert runtime.group_signals == []
    receipt = read_memoryos_status(fixture.paths.xmuse_root)
    assert receipt is not None and receipt["state"] == "ready"


def test_recorded_memoryos_stop_fails_closed_for_scope_mismatch(tmp_path: Path) -> None:
    runtime, fixture = _coordinator(tmp_path)
    fixture.coordinator.reconcile()
    original = runtime.identities[201]
    runtime.identities[201] = ProcessIdentity(
        start_identity=original.start_identity,
        pgid=201,
        environment={**original.environment, "XMUSE_WORKROOM_SERVICE": "frontend"},
    )

    result = memory_runtime.stop_recorded_memoryos(
        fixture.manifest,
        fixture.paths,
        fixture.dependencies,
        timeout_s=1.0,
    )

    assert result["stopped"] is False
    assert result["code"] == "memoryos_process_identity_mismatch"
    assert runtime.group_signals == []


def test_confirmed_dead_child_uses_bounded_backoff_and_one_identity_bound_restart(
    tmp_path: Path,
) -> None:
    runtime, fixture = _coordinator(tmp_path)

    first = fixture.coordinator.reconcile()
    assert first["state"] == "ready"
    assert [spec.service for spec in runtime.specs] == ["memoryos"]
    process = runtime.processes[201]
    process.returncode = 9
    runtime.identities.pop(process.pid)

    recovering = fixture.coordinator.reconcile()
    assert recovering["state"] == "recovering"
    assert recovering["consecutive_restart_count"] == 1
    assert fixture.control.next_retry_monotonic == 1.0
    assert len(runtime.specs) == 1

    runtime.sleep(1.0)
    restarted = fixture.coordinator.reconcile()
    assert restarted["state"] == "ready"
    assert len(runtime.specs) == 2
    assert {spec.env["MEMORYOS_API_KEY"] for spec in runtime.specs} == {"generation-memory-key"}
    assert {spec.env["XMUSE_WORKROOM_GENERATION"] for spec in runtime.specs} == {"generation-one"}

    runtime.sleep(60.0)
    stable = fixture.coordinator.reconcile()
    assert stable["consecutive_restart_count"] == 0


def test_live_unhealthy_or_unverifiable_child_is_never_replaced_or_signalled(
    tmp_path: Path,
) -> None:
    runtime, fixture = _coordinator(tmp_path)
    fixture.coordinator.reconcile()
    runtime.ready = False

    unhealthy = fixture.coordinator.reconcile()
    assert unhealthy["code"] == "memoryos_health_unavailable"
    assert len(runtime.specs) == 1
    assert runtime.group_signals == []

    runtime.identities.pop(201)
    unknown = fixture.coordinator.reconcile()
    assert unknown["code"] == "memoryos_process_identity_unavailable"
    assert len(runtime.specs) == 1
    assert runtime.group_signals == []


def test_unknown_port_owner_is_degraded_without_spawn_or_signal(tmp_path: Path) -> None:
    runtime, fixture = _coordinator(tmp_path)
    fixture.dependencies.port_available = lambda _host, _port: False

    status = fixture.coordinator.reconcile()

    assert status["state"] == "degraded"
    assert status["code"] == "memoryos_port_in_use"
    assert fixture.control.next_retry_monotonic == 5.0
    assert runtime.specs == []
    assert runtime.group_signals == []


def test_full_local_requires_the_complete_hybrid_capability_proof(tmp_path: Path) -> None:
    runtime, fixture = _coordinator(tmp_path, profile="full-local")
    fixture.dependencies.http_json = lambda _url: {
        "status": "ok",
        "capabilities": {
            "hybrid": {"lexical": True, "semantic": False, "rrf": True},
            "message_ingest": True,
            "agentic_advisory": True,
            "paging": True,
        },
    }

    status = fixture.coordinator.reconcile()

    assert status["state"] == "degraded"
    assert status["code"] == "memoryos_full_local_capability_missing"
    assert len(runtime.specs) == 1
    assert runtime.group_signals == []


def test_generation_change_wins_over_due_recovery(tmp_path: Path) -> None:
    runtime, fixture = _coordinator(tmp_path)

    def fail_spawn(_spec: object) -> object:
        raise OSError("injected spawn failure")

    fixture.dependencies.spawn = fail_spawn  # type: ignore[assignment]
    fixture.coordinator.reconcile()
    runtime.sleep(1.0)
    current = json.loads(fixture.paths.manifest.read_text(encoding="utf-8"))
    current["generation"] = "generation-two"
    atomic_write_manifest(fixture.paths.manifest, current)

    stopped = fixture.coordinator.reconcile()

    assert stopped["state"] == "stopped"
    assert stopped["code"] == "memoryos_reconcile_not_current"


def test_safe_status_excludes_process_identity_key_and_paths(tmp_path: Path) -> None:
    _runtime, fixture = _coordinator(tmp_path)
    fixture.coordinator.reconcile()

    safe = fixture.coordinator.safe_status()
    encoded = json.dumps(safe, sort_keys=True)

    assert safe["state"] == "ready"
    assert "pid" not in safe
    assert "start_identity" not in safe
    assert "generation-memory-key" not in encoded
    assert str(fixture.paths.xmuse_root) not in encoded


def test_changed_rebuild_guard_is_rejected_before_cache_or_process_mutation(
    tmp_path: Path,
) -> None:
    runtime, fixture = _coordinator(tmp_path)
    conversation_id = (
        RoomTestStore(fixture.paths.xmuse_root / "chat.db").create_conversation("rebuild").id
    )
    RoomMemoryDeliveryStore(fixture.paths.xmuse_root / "chat.db").ensure_binding(
        conversation_id=conversation_id
    )
    RoomKernelStore(fixture.paths.xmuse_root / "chat.db").post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="durable source",
        client_request_id="source",
    )
    write_memoryos_status(
        fixture.paths.xmuse_root,
        enabled=True,
        state="degraded",
        code="memoryos_crash_loop",
        generation="generation-one",
        consecutive_restart_count=6,
    )
    store = RoomMemoryRebuildActionStore(fixture.paths.xmuse_root / "chat.db")
    action, created = store.reserve(
        client_action_id="rebuild-one",
        request_fingerprint="fingerprint-one",
        incident_guard="memoryos_incident_" + "0" * 32,
        runtime_generation="generation-one",
        before_state="degraded",
        before_code="memoryos_crash_loop",
    )
    assert created is True and action["phase"] == "requested"
    fixture.paths.memoryos_derived_dir.mkdir(mode=0o700, parents=True)
    sentinel = fixture.paths.memoryos_derived_dir / "sentinel"
    sentinel.write_bytes(b"derived-only")

    result = fixture.coordinator.reconcile_rebuild_action(store)

    assert result is not None
    assert result["status"] == "rejected"
    assert result["reason_code"] == "memoryos_rebuild_incident_changed"
    assert sentinel.read_bytes() == b"derived-only"
    assert runtime.specs == []
    assert runtime.group_signals == []


def test_replaying_rebuild_is_finished_idempotently_after_runtime_recovery(
    tmp_path: Path,
) -> None:
    _runtime, fixture = _coordinator(tmp_path)
    conversation_id = (
        RoomTestStore(fixture.paths.xmuse_root / "chat.db").create_conversation("replay").id
    )
    RoomMemoryDeliveryStore(fixture.paths.xmuse_root / "chat.db").ensure_binding(
        conversation_id=conversation_id
    )
    RoomKernelStore(fixture.paths.xmuse_root / "chat.db").post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="source",
        client_request_id="source",
    )
    write_memoryos_status(
        fixture.paths.xmuse_root,
        enabled=True,
        state="degraded",
        code="memoryos_crash_loop",
        generation="generation-one",
        consecutive_restart_count=6,
    )
    receipt = read_memoryos_status(fixture.paths.xmuse_root)
    assert receipt is not None
    store = RoomMemoryRebuildActionStore(fixture.paths.xmuse_root / "chat.db")
    store.reserve(
        client_action_id="rebuild-one",
        request_fingerprint="fingerprint-one",
        incident_guard=memoryos_incident_guard(receipt),
        runtime_generation="generation-one",
        before_state="degraded",
        before_code="memoryos_crash_loop",
    )
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
    with sqlite3.connect(fixture.paths.xmuse_root / "chat.db") as conn:
        conn.execute(
            """update room_memory_bindings
               set session_state = 'bound', session_id = 'new-session',
                   attachment_state = 'attached', attachment_id = 'new-attachment'"""
        )
        conn.execute("update room_memory_outbox set state = 'delivered'")
    fixture.coordinator.reconcile()

    first = fixture.coordinator.reconcile_rebuild_action(store)
    replay = fixture.coordinator.reconcile_rebuild_action(store)

    assert first is not None and first["status"] == "applied"
    assert replay is None
    assert store.get("rebuild-one") == first


def test_finalize_after_stop_clears_retry_without_signalling_a_live_unverified_child(
    tmp_path: Path,
) -> None:
    runtime, fixture = _coordinator(tmp_path)
    fixture.coordinator.reconcile()
    fixture.control.next_retry_monotonic = 10.0
    fixture.control.next_retry_at = "2026-07-12T00:00:10Z"
    runtime.identities.pop(201)

    fixture.coordinator.finalize_after_stop()

    receipt = read_memoryos_status(fixture.paths.xmuse_root)
    assert receipt is not None
    assert receipt["state"] == "stopped"
    assert fixture.control.next_retry_monotonic is None
    assert fixture.control.next_retry_at is None
    assert runtime.group_signals == []
