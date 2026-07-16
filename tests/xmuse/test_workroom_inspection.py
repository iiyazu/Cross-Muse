from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from xmuse import workroom_inspection
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomError, WorkroomPaths
from xmuse.workroom_processes import ProcessIdentity
from xmuse_core.chat.memoryos_supervisor import write_memoryos_status
from xmuse_core.chat.room_runtime import (
    ROOM_RUNNER_PROOF_BOUNDARY,
    ROOM_RUNNER_READINESS_KEYS,
)

STAMP = "2026-07-16T12:00:00Z"
GENERATION = "generation-inspection"


class InspectionRuntime:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.identities: dict[int, ProcessIdentity] = {}
        self.unavailable_ports: set[int] = set()

    def identity(self, pid: int) -> ProcessIdentity | None:
        return self.identities.get(pid)

    def dependencies(self) -> WorkroomDependencies:
        return WorkroomDependencies(
            repo_root=self.repo_root,
            inspect_process=self.identity,
            http_ready=lambda _url: True,
            http_json=lambda _url: {
                "status": "ok",
                "surface": "room",
                "endpoints": {"mcp_room": "/mcp/room"},
            },
            which=lambda command: f"/safe/bin/{command}",
            port_available=lambda _host, port: port not in self.unavailable_ports,
            now=lambda: STAMP,
            current_pid=lambda: 99,
        )

    def add_identity(self, pid: int, service: str | None = None) -> str:
        start_identity = f"linux-proc-starttime:{pid}"
        environment = (
            {
                "XMUSE_ROOT": str(self.runtime_root),
                "XMUSE_WORKROOM_GENERATION": GENERATION,
                "XMUSE_WORKROOM_SERVICE": service,
            }
            if service is not None
            else {}
        )
        self.identities[pid] = ProcessIdentity(
            start_identity=start_identity,
            pgid=pid,
            environment=environment,
        )
        return start_identity

    runtime_root: Path


@pytest.fixture
def inspection_runtime(tmp_path: Path) -> tuple[InspectionRuntime, WorkroomPaths]:
    repo = tmp_path / "repo"
    standalone = repo / "frontend" / ".next" / "standalone"
    static = repo / "frontend" / ".next" / "static"
    standalone.mkdir(parents=True)
    static.mkdir(parents=True)
    (standalone / "server.js").write_text("// fixture\n", encoding="utf-8")
    runtime = InspectionRuntime(repo)
    runtime.runtime_root = (tmp_path / "runtime").resolve()
    runtime.runtime_root.mkdir()
    runtime.add_identity(99)
    return runtime, WorkroomPaths.resolve(runtime.runtime_root, repo)


def _service_record(runtime: InspectionRuntime, name: str, pid: int, port: int) -> dict[str, Any]:
    return {
        "service": name,
        "pid": pid,
        "pgid": pid,
        "start_identity": runtime.add_identity(pid, name),
        "generation": GENERATION,
        "port": port,
        "url": f"http://127.0.0.1:{port}/health",
        "log_path": f"/private/{name}.log",
    }


def _seed_ready_runtime(runtime: InspectionRuntime, paths: WorkroomPaths) -> None:
    services = {
        "frontend": _service_record(runtime, "frontend", 301, 3000),
        "chat_api": _service_record(runtime, "chat_api", 302, 8201),
        "memoryos": _service_record(runtime, "memoryos", 303, 8301),
    }
    manager_identity = runtime.add_identity(300)
    runner_identity = runtime.add_identity(401, "room_runner")
    mcp_identity = runtime.add_identity(402, "room_mcp")
    manifest = {
        "schema_version": workroom_inspection.MANIFEST_SCHEMA_VERSION,
        "generation": GENERATION,
        "state": "ready",
        "manager": {"pid": 300, "start_identity": manager_identity},
        "services": services,
        "supervised": {
            "room_runner_pid_file": str(paths.runner_pid_file),
            "room_mcp_pid_file": str(paths.mcp_pid_file),
            "room_runner_status_file": str(paths.room_runner_status_file),
        },
        "features": {"memoryos": True},
        "secret_canary": "never-project-this",
    }
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    paths.runner_pid_file.write_text(
        json.dumps(
            {
                "pid": 401,
                "generation": GENERATION,
                "start_identity": runner_identity,
                "command": ["python", "runner", "--mcp-port", "8100"],
            }
        ),
        encoding="utf-8",
    )
    paths.mcp_pid_file.write_text(
        json.dumps(
            {
                "pid": 402,
                "generation": GENERATION,
                "start_identity": mcp_identity,
                "command": ["python", "mcp", "--port", "8100"],
            }
        ),
        encoding="utf-8",
    )
    paths.room_runner_status_file.write_text(
        json.dumps(
            {
                "schema_version": "room_runner_status/v2",
                "generation": GENERATION,
                "pid": 401,
                "start_identity": runner_identity,
                "boot_id": "boot-inspection",
                "state": "ready",
                "started_at": STAMP,
                "updated_at": STAMP,
                "heartbeat_at": STAMP,
                "mcp": {"surface": "room", "path": "/mcp/room", "port": 8100},
                "readiness": {key: True for key in ROOM_RUNNER_READINESS_KEYS},
                "host": {
                    "state": "healthy",
                    "code": "ready",
                    "active_delivery_count": 0,
                    "retained_cleanup_count": 0,
                },
                "error": None,
                "proof_boundary": ROOM_RUNNER_PROOF_BOUNDARY,
            }
        ),
        encoding="utf-8",
    )
    write_memoryos_status(
        paths.xmuse_root,
        enabled=True,
        state="ready",
        code="ready",
        generation=GENERATION,
        pid=303,
        start_identity=services["memoryos"]["start_identity"],
        started_at=STAMP,
        heartbeat_at=STAMP,
        profile="full-local",
    )


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_inspection_module_does_not_import_lifecycle_coordinator() -> None:
    source_path = Path(workroom_inspection.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert "xmuse.workroom" not in imported


def test_ready_status_is_read_only_and_projects_only_safe_evidence(
    inspection_runtime: tuple[InspectionRuntime, WorkroomPaths],
) -> None:
    runtime, paths = inspection_runtime
    _seed_ready_runtime(runtime, paths)
    before = _file_snapshot(paths.xmuse_root)

    result = workroom_inspection.inspect_workroom_status(paths, runtime.dependencies())

    assert result.exit_code == 0
    assert result.manifest_generation == GENERATION
    assert result.projection["schema_version"] == "xmuse_workroom_status/v2"
    assert result.projection["state"] == "ready"
    assert [item["service"] for item in result.projection["services"]] == [
        "frontend",
        "chat_api",
        "room_runner",
        "room_mcp",
        "memoryos",
    ]
    memory = result.projection["services"][-1]
    assert memory["state"] == "ready"
    assert memory["profile"] == "full-local"
    assert result.projection["services"][3]["surface"] == "room"
    encoded = json.dumps(result.projection, sort_keys=True)
    assert GENERATION not in encoded
    assert str(paths.xmuse_root) not in encoded
    assert "/private/" not in encoded
    assert "never-project-this" not in encoded
    assert all(
        key not in encoded for key in ("start_identity", '"pid"', "boot_id", "log_path", '"url"')
    )
    assert _file_snapshot(paths.xmuse_root) == before


def test_stopped_and_invalid_manifest_status(
    inspection_runtime: tuple[InspectionRuntime, WorkroomPaths],
) -> None:
    runtime, paths = inspection_runtime
    stopped = workroom_inspection.inspect_workroom_status(paths, runtime.dependencies())
    assert stopped == workroom_inspection.WorkroomStatusInspection(
        exit_code=1,
        projection={
            "schema_version": "xmuse_workroom_status/v2",
            "state": "stopped",
            "services": [],
        },
    )

    paths.manifest.write_text('{"schema_version":"future"}', encoding="utf-8")
    with pytest.raises(WorkroomError) as exc_info:
        workroom_inspection.inspect_workroom_status(paths, runtime.dependencies())
    assert exc_info.value.code == "invalid_manifest"


def test_doctor_is_read_only_and_uses_safe_details(
    inspection_runtime: tuple[InspectionRuntime, WorkroomPaths],
) -> None:
    runtime, paths = inspection_runtime
    before = _file_snapshot(paths.xmuse_root)

    exit_code, projection = workroom_inspection.inspect_workroom_doctor(
        paths, runtime.dependencies()
    )

    assert exit_code == 0
    assert projection["schema_version"] == "xmuse_workroom_doctor/v1"
    assert projection["state"] == "ready"
    assert projection["blocker_count"] == 0
    details = {check["name"]: check["detail"] for check in projection["checks"]}
    assert details["node"] == "available"
    assert details["codex"] == "available"
    assert details["process_identity"] == "available"
    assert details["manifest"] == "valid"
    encoded = json.dumps(projection, sort_keys=True)
    assert str(paths.repo_root) not in encoded
    assert str(paths.xmuse_root) not in encoded
    assert "linux-proc-starttime" not in encoded
    assert _file_snapshot(paths.xmuse_root) == before


def test_doctor_accepts_a_port_only_when_the_live_owner_is_generation_scoped(
    inspection_runtime: tuple[InspectionRuntime, WorkroomPaths],
) -> None:
    runtime, paths = inspection_runtime
    runtime.unavailable_ports = {3000, 8201}
    services = {
        "frontend": _service_record(runtime, "frontend", 301, 3000),
        "chat_api": _service_record(runtime, "chat_api", 302, 8201),
    }
    paths.manifest.write_text(
        json.dumps(
            {
                "schema_version": workroom_inspection.MANIFEST_SCHEMA_VERSION,
                "generation": GENERATION,
                "state": "ready",
                "manager": {"pid": 99, "start_identity": runtime.identities[99].start_identity},
                "services": services,
            }
        ),
        encoding="utf-8",
    )
    exit_code, projection = workroom_inspection.inspect_workroom_doctor(
        paths, runtime.dependencies()
    )
    assert exit_code == 0
    assert projection["state"] == "ready"

    runtime.identities[302] = ProcessIdentity(
        start_identity=services["chat_api"]["start_identity"],
        pgid=302,
        environment={
            "XMUSE_ROOT": str(paths.xmuse_root),
            "XMUSE_WORKROOM_GENERATION": "different-generation",
            "XMUSE_WORKROOM_SERVICE": "chat_api",
        },
    )
    exit_code, projection = workroom_inspection.inspect_workroom_doctor(
        paths, runtime.dependencies()
    )
    assert exit_code == 1
    assert projection["state"] == "blocked"
    blocked = {check["name"] for check in projection["checks"] if check["status"] == "blocker"}
    assert blocked == {"chat_api_port"}
