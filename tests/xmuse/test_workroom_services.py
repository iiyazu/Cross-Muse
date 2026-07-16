from __future__ import annotations

import json
import shutil
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from xmuse.workroom_contracts import (
    WorkroomDependencies,
    WorkroomError,
    WorkroomPaths,
)
from xmuse.workroom_processes import ProcessIdentity, ProcessSpec
from xmuse.workroom_services import WorkroomServicesCoordinator


@dataclass
class FakeProcess:
    pid: int
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class ServiceHarness:
    def __init__(self, repo_root: Path, runtime_root: Path) -> None:
        self.repo_root = repo_root
        self.runtime_root = runtime_root.resolve()
        self.clock = 0.0
        self.specs: list[ProcessSpec] = []
        self.processes: dict[int, FakeProcess] = {}
        self.identities: dict[int, ProcessIdentity] = {}
        self.group_signals: list[tuple[int, int]] = []
        self.pid_signals: list[tuple[int, int]] = []
        self.ready = lambda _url: True
        self.publish_identity = True
        self.keep_service_after_signal = False
        self.keep_manager_after_term = False
        self.reuse_manager_after_term = False

    def spawn(self, spec: ProcessSpec) -> FakeProcess:
        pid = 100 + len(self.specs)
        process = FakeProcess(pid)
        self.specs.append(spec)
        self.processes[pid] = process
        if self.publish_identity:
            self.identities[pid] = ProcessIdentity(
                start_identity=f"linux-proc-starttime:{pid}",
                pgid=pid,
                environment=dict(spec.env),
            )
        return process

    def inspect(self, pid: int) -> ProcessIdentity | None:
        return self.identities.get(pid)

    def signal_group(self, pgid: int, signum: int) -> None:
        self.group_signals.append((pgid, signum))
        if self.keep_service_after_signal:
            return
        self.identities.pop(pgid, None)
        process = self.processes.get(pgid)
        if process is not None:
            process.returncode = -signum

    def signal_pid(self, pid: int, signum: int) -> None:
        self.pid_signals.append((pid, signum))
        if signum == signal.SIGTERM and self.reuse_manager_after_term:
            self.identities[pid] = ProcessIdentity(
                start_identity="linux-proc-starttime:replacement",
                pgid=pid,
            )
            return
        if signum == signal.SIGTERM and self.keep_manager_after_term:
            return
        self.identities.pop(pid, None)

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def dependencies(self) -> WorkroomDependencies:
        return WorkroomDependencies(
            repo_root=self.repo_root,
            environ={"PATH": "/usr/bin", "KEEP": "yes"},
            spawn=self.spawn,
            inspect_process=self.inspect,
            port_available=lambda _host, _port: True,
            http_ready=lambda url: self.ready(url),
            which=lambda name: f"/usr/bin/{name}" if name in {"node", "codex"} else None,
            signal_pid=self.signal_pid,
            signal_group=self.signal_group,
            sleep=self.sleep,
            monotonic=lambda: self.clock,
        )


@pytest.fixture
def service_setup(tmp_path: Path) -> tuple[WorkroomPaths, ServiceHarness]:
    repo_root = tmp_path / "repo"
    frontend = repo_root / "frontend"
    standalone = frontend / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("// server\n", encoding="utf-8")
    static = frontend / ".next" / "static" / "chunks"
    static.mkdir(parents=True)
    (static / "app.js").write_text("static\n", encoding="utf-8")
    public = frontend / "public"
    public.mkdir()
    (public / "icon.txt").write_text("public\n", encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    paths = WorkroomPaths.resolve(runtime_root, repo_root)
    return paths, ServiceHarness(repo_root, runtime_root)


def _start(
    coordinator: WorkroomServicesCoordinator,
    records: list[tuple[str, dict[str, object]]],
    *,
    node: str = "/usr/bin/node",
):
    return coordinator.start(
        node=node,
        generation="generation-one",
        operator_token="operator-secret",
        execution_workspace=Path("/workspace").resolve(),
        execution_profile_id="xmuse-monorepo/v2",
        readiness_timeout_s=0.2,
        record_service=lambda name, record: records.append((name, record)),
        memoryos_url="http://127.0.0.1:8301",
        memoryos_api_key="memory-secret",
        cleanup_timeout_s=0.2,
    )


def test_preflight_sync_and_start_keep_capabilities_server_side(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())

    node = coordinator.preflight()
    coordinator.sync_assets()
    records: list[tuple[str, dict[str, object]]] = []
    runtime = _start(coordinator, records, node=node)

    assert [spec.service for spec in harness.specs] == ["chat_api", "frontend"]
    chat_api, frontend = harness.specs
    assert chat_api.command == (sys.executable, "-m", "xmuse.chat_api")
    assert chat_api.cwd == paths.repo_root
    assert frontend.command == (node, str(paths.standalone_server))
    assert frontend.cwd == paths.standalone_dir
    assert (paths.static_destination / "chunks" / "app.js").read_text() == "static\n"
    assert (paths.public_destination / "icon.txt").read_text() == "public\n"
    assert chat_api.env["XMUSE_MEMORYOS_API_KEY"] == "memory-secret"
    assert chat_api.env["XMUSE_WORKSPACE_ROOT"] == str(Path("/workspace").resolve())
    assert "XMUSE_MEMORYOS_API_KEY" not in frontend.env
    assert "XMUSE_WORKSPACE_ROOT" not in frontend.env
    assert all(spec.env["XMUSE_OPERATOR_TOKEN"] == "operator-secret" for spec in harness.specs)
    assert [name for name, _record in records] == ["chat_api", "frontend"]
    assert runtime.processes_by_name() == {
        "chat_api": harness.processes[100],
        "frontend": harness.processes[101],
    }
    serialized_records = json.dumps(records)
    assert "operator-secret" not in serialized_records
    assert "memory-secret" not in serialized_records


def test_chat_api_readiness_failure_cleans_partial_start_before_frontend(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    harness.ready = lambda _url: False
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())
    records: list[tuple[str, dict[str, object]]] = []

    with pytest.raises(WorkroomError) as raised:
        _start(coordinator, records)

    assert raised.value.code == "readiness_timeout"
    assert [spec.service for spec in harness.specs] == ["chat_api"]
    assert harness.group_signals == [(100, signal.SIGTERM)]
    assert [name for name, _record in records] == ["chat_api"]


def test_frontend_readiness_failure_cleans_required_services_in_reverse_order(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    harness.ready = lambda url: url.endswith("/health")
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())
    records: list[tuple[str, dict[str, object]]] = []

    with pytest.raises(WorkroomError) as raised:
        _start(coordinator, records)

    assert raised.value.code == "readiness_timeout"
    assert [spec.service for spec in harness.specs] == ["chat_api", "frontend"]
    assert harness.group_signals == [
        (101, signal.SIGTERM),
        (100, signal.SIGTERM),
    ]


def test_partial_start_reports_cleanup_failure_when_identity_fenced_stop_times_out(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    harness.ready = lambda _url: False
    harness.keep_service_after_signal = True
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())

    with pytest.raises(WorkroomError) as raised:
        _start(coordinator, [])

    assert raised.value.code == "partial_start_cleanup_failed"
    assert harness.group_signals == [
        (100, signal.SIGTERM),
        (100, signal.SIGKILL),
    ]
    assert harness.identities[100].start_identity == "linux-proc-starttime:100"


def test_identity_failure_cleans_only_the_known_spawned_child(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    harness.publish_identity = False
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())

    with pytest.raises(WorkroomError) as raised:
        _start(coordinator, [])

    assert raised.value.code == "process_identity_timeout"
    assert harness.group_signals == [(100, signal.SIGTERM)]


def test_stop_is_reverse_ordered_and_generation_scoped(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())
    records: list[tuple[str, dict[str, object]]] = []
    _start(coordinator, records)
    manifest = {
        "generation": "generation-one",
        "services": dict(records),
    }

    assert coordinator.stop(manifest, timeout_s=0.2) == ["frontend", "chat_api"]
    assert harness.group_signals == [
        (101, signal.SIGTERM),
        (100, signal.SIGTERM),
    ]

    harness.group_signals.clear()
    coordinator_two = WorkroomServicesCoordinator(paths, harness.dependencies())
    records_two: list[tuple[str, dict[str, object]]] = []
    _start(coordinator_two, records_two)
    wrong_generation = {
        "generation": "new-generation",
        "services": dict(records_two),
    }
    assert coordinator_two.stop(wrong_generation, timeout_s=0.2) == [
        "frontend",
        "chat_api",
    ]
    assert harness.group_signals == []


def test_manager_stop_escalates_only_while_exact_identity_remains_live(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    harness.keep_manager_after_term = True
    harness.identities[77] = ProcessIdentity(
        start_identity="linux-proc-starttime:manager",
        pgid=77,
    )
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())

    assert coordinator.stop_manager(
        {"pid": 77, "start_identity": "linux-proc-starttime:manager"},
        timeout_s=0.1,
    )
    assert harness.pid_signals == [(77, signal.SIGTERM), (77, signal.SIGKILL)]


def test_manager_stop_never_kills_reused_pid(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
) -> None:
    paths, harness = service_setup
    harness.reuse_manager_after_term = True
    harness.identities[77] = ProcessIdentity(
        start_identity="linux-proc-starttime:manager",
        pgid=77,
    )
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())

    assert coordinator.stop_manager(
        {"pid": 77, "start_identity": "linux-proc-starttime:manager"},
        timeout_s=0.1,
    )
    assert harness.pid_signals == [(77, signal.SIGTERM)]
    assert harness.identities[77].start_identity == "linux-proc-starttime:replacement"


def _write_data_journal(paths: WorkroomPaths) -> None:
    paths.data_operation_journal.parent.mkdir(parents=True, exist_ok=True)
    paths.data_operation_journal.write_text("{}", encoding="utf-8")


@pytest.mark.parametrize(
    ("prepare", "code"),
    [
        (_write_data_journal, "data_operation_incomplete"),
        (lambda paths: paths.standalone_server.unlink(), "standalone_build_missing"),
        (lambda paths: shutil.rmtree(paths.static_source), "static_assets_missing"),
    ],
)
def test_preflight_fails_before_spawn(
    service_setup: tuple[WorkroomPaths, ServiceHarness],
    prepare,
    code: str,
) -> None:
    paths, harness = service_setup
    prepare(paths)
    coordinator = WorkroomServicesCoordinator(paths, harness.dependencies())

    with pytest.raises(WorkroomError) as raised:
        coordinator.preflight()

    assert raised.value.code == code
    assert harness.specs == []
