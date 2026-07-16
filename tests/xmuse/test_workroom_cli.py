from __future__ import annotations

import json
import signal
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

from xmuse import workroom, workroom_processes


@dataclass
class FakeProcess:
    pid: int
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class ImmediateShutdown:
    def __init__(self) -> None:
        self.installed = False
        self.restored = False

    def install(self) -> None:
        self.installed = True

    def requested(self) -> bool:
        return True

    def restore(self) -> None:
        self.restored = True


class FakeRuntime:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.current_pid = 91
        self.identities: dict[int, workroom.ProcessIdentity] = {
            self.current_pid: workroom.ProcessIdentity(
                start_identity="linux-proc-starttime:manager",
                pgid=self.current_pid,
            )
        }
        self.processes: dict[int, FakeProcess] = {}
        self.specs: list[workroom.ProcessSpec] = []
        self.group_signals: list[tuple[int, int]] = []
        self.pid_signals: list[tuple[int, int]] = []
        self.runtime_stops: list[tuple[Path, str]] = []
        self.clock = 0.0
        self.ready = True
        self.room_mcp_ready = True
        self.shutdown = ImmediateShutdown()
        self.spawn_forbidden = False
        self.publish_spawn_identity = True

    def spawn(self, spec: workroom.ProcessSpec) -> FakeProcess:
        if self.spawn_forbidden:
            raise AssertionError("doctor/status must not spawn a process")
        pid = 201 + len(self.specs)
        process = FakeProcess(pid)
        self.specs.append(spec)
        self.processes[pid] = process
        if self.publish_spawn_identity:
            self.identities[pid] = workroom.ProcessIdentity(
                start_identity=f"linux-proc-starttime:{pid}",
                pgid=pid,
                environment=dict(spec.env),
            )
        return process

    def inspect(self, pid: int) -> workroom.ProcessIdentity | None:
        return self.identities.get(pid)

    def send_group_signal(self, pgid: int, signum: int) -> None:
        self.group_signals.append((pgid, signum))
        self.identities.pop(pgid, None)
        if pgid in self.processes:
            self.processes[pgid].returncode = -signum

    def send_pid_signal(self, pid: int, signum: int) -> None:
        self.pid_signals.append((pid, signum))
        self.identities.pop(pid, None)

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def stop_runtime(self, root: Path, generation: str) -> dict[str, object]:
        self.runtime_stops.append((root, generation))
        return {"state": "stopped"}

    def dependencies(self) -> workroom.WorkroomDependencies:
        return workroom.WorkroomDependencies(
            repo_root=self.repo_root,
            environ={"PATH": "/usr/bin", "KEEP": "yes"},
            spawn=self.spawn,
            inspect_process=self.inspect,
            port_available=lambda _host, _port: True,
            http_ready=lambda _url: self.ready,
            http_json=lambda url: (
                {
                    "status": "ok",
                    "capabilities": {
                        "hybrid": {"lexical": True, "semantic": True, "rrf": True},
                        "message_ingest": True,
                        "agentic_advisory": True,
                        "paging": True,
                    },
                }
                if "8301" in url
                else (
                    {
                        "status": "ok",
                        "surface": "room",
                        "endpoints": {"mcp_room": "/mcp/room"},
                    }
                    if self.room_mcp_ready
                    else None
                )
            ),
            which=lambda name: f"/usr/bin/{name}" if name in {"node", "codex"} else None,
            signal_pid=self.send_pid_signal,
            signal_group=self.send_group_signal,
            stop_runtime=self.stop_runtime,
            sleep=self.sleep,
            monotonic=lambda: self.clock,
            now=lambda: "2026-07-11T00:00:00Z",
            generation_factory=lambda: "generation-one",
            token_factory=lambda: "super-secret-operator-token",
            current_pid=lambda: self.current_pid,
            shutdown_controller_factory=lambda: self.shutdown,
        )


@pytest.fixture
def built_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    frontend = repo_root / "frontend"
    standalone = frontend / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("// standalone\n", encoding="utf-8")
    static = frontend / ".next" / "static" / "chunks"
    static.mkdir(parents=True)
    (static / "app.js").write_text("static asset\n", encoding="utf-8")
    public = frontend / "public"
    public.mkdir()
    (public / "icon.txt").write_text("public asset\n", encoding="utf-8")
    return repo_root


def _output_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]


def _ready_manifest(
    runtime: FakeRuntime,
    runtime_root: Path,
    *,
    generation: str = "generation-one",
) -> dict[str, object]:
    services: dict[str, object] = {}
    for name, pid, port, url in (
        ("chat_api", 301, 8201, "http://127.0.0.1:8201/health"),
        ("frontend", 302, 3000, "http://127.0.0.1:3000"),
    ):
        environment = {
            "XMUSE_ROOT": str(runtime_root.resolve()),
            "XMUSE_WORKROOM_GENERATION": generation,
            "XMUSE_WORKROOM_SERVICE": name,
        }
        runtime.identities[pid] = workroom.ProcessIdentity(
            start_identity=f"linux-proc-starttime:{pid}",
            pgid=pid,
            environment=environment,
        )
        services[name] = {
            "service": name,
            "pid": pid,
            "pgid": pid,
            "start_identity": f"linux-proc-starttime:{pid}",
            "generation": generation,
            "port": port,
            "url": url,
        }
    return {
        "schema_version": workroom.SCHEMA_VERSION,
        "generation": generation,
        "state": "ready",
        "version": "0.1.0",
        "started_at": "2026-07-11T00:00:00Z",
        "updated_at": "2026-07-11T00:00:00Z",
        "repo_root": str(runtime.repo_root),
        "xmuse_root": str(runtime_root.resolve()),
        "manager": {
            "pid": runtime.current_pid,
            "start_identity": "linux-proc-starttime:manager",
        },
        "services": services,
    }


def _seed_room_runtime(
    runtime: FakeRuntime,
    runtime_root: Path,
    manifest: dict[str, object],
) -> None:
    generation = str(manifest["generation"])
    runner_pid = 401
    mcp_pid = 402
    for name, pid in (("room_runner", runner_pid), ("room_mcp", mcp_pid)):
        runtime.identities[pid] = workroom.ProcessIdentity(
            start_identity=f"linux-proc-starttime:{pid}",
            pgid=pid,
            environment={
                "XMUSE_ROOT": str(runtime_root.resolve()),
                "XMUSE_WORKROOM_GENERATION": generation,
                "XMUSE_WORKROOM_SERVICE": name,
            },
        )
    (runtime_root / "workroom_room_runner.pid.json").write_text(
        json.dumps(
            {
                "pid": runner_pid,
                "generation": generation,
                "start_identity": f"linux-proc-starttime:{runner_pid}",
                "command": ["python", "xmuse/room_runner.py", "--mcp-port", "8100"],
            }
        ),
        encoding="utf-8",
    )
    (runtime_root / "workroom_room_mcp.pid.json").write_text(
        json.dumps(
            {
                "pid": mcp_pid,
                "generation": generation,
                "start_identity": f"linux-proc-starttime:{mcp_pid}",
                "command": [
                    "python",
                    "xmuse/room_mcp_server.py",
                    "--port",
                    "8100",
                    "--surface",
                    "room",
                ],
            }
        ),
        encoding="utf-8",
    )
    (runtime_root / "room-runner-status.json").write_text(
        json.dumps(
            {
                "schema_version": "room_runner_status/v1",
                "generation": generation,
                "xmuse_root": str(runtime_root.resolve()),
                "pid": runner_pid,
                "start_identity": f"linux-proc-starttime:{runner_pid}",
                "boot_id": "boot-one",
                "state": "ready",
                "started_at": "2026-07-11T00:00:00Z",
                "updated_at": "2026-07-11T00:00:00Z",
                "heartbeat_at": "2026-07-11T00:00:00Z",
                "mcp": {"surface": "room", "path": "/mcp/room", "port": 8100},
                "readiness": {
                    "chat_db": True,
                    "skill_catalog": True,
                    "mcp_health": True,
                    "mcp_tools": True,
                    "persistent_launcher": True,
                    "host_loop": True,
                },
                "error": None,
                "proof_boundary": ("room_runner_status_not_room_or_provider_outcome_authority"),
            }
        ),
        encoding="utf-8",
    )


def test_project_registers_workroom_entrypoint() -> None:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["scripts"]["xmuse-workroom"] == "xmuse.workroom:main"


def test_port_probe_treats_connection_refusal_as_available(monkeypatch) -> None:
    monkeypatch.setattr(
        workroom_processes.socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionRefusedError()),
    )

    assert workroom._port_available("127.0.0.1", 8201) is True


def test_start_refuses_an_incomplete_data_operation(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    (runtime_root / workroom.DATA_OPERATION_JOURNAL_NAME).write_text(
        '{"schema_version":"xmuse_data_operation/v1"}\n',
        encoding="utf-8",
    )
    runtime = FakeRuntime(built_repo)

    exit_code = workroom.run_cli(
        ["start", "--root", str(runtime_root)],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    payload = _output_lines(capsys)[-1]
    assert payload["error"]["code"] == "data_operation_incomplete"


def test_start_requires_codex_before_spawning_services(
    tmp_path: Path,
    built_repo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    dependencies = runtime.dependencies()
    dependencies.which = lambda name: "/usr/bin/node" if name == "node" else None

    exit_code = workroom.run_cli(
        ["start", "--root", str(tmp_path / "runtime")],
        dependencies=dependencies,
    )

    assert exit_code == 1
    assert runtime.processes == {}
    payload = _output_lines(capsys)[0]
    assert payload["error"]["code"] == "codex_missing"
    assert runtime.specs == []


def test_port_probe_treats_a_listener_as_occupied(monkeypatch) -> None:
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        workroom_processes.socket,
        "create_connection",
        lambda *_args, **_kwargs: Connection(),
    )

    assert workroom._port_available("127.0.0.1", 8201) is False


def test_start_runs_api_then_standalone_and_keeps_token_out_of_manifest(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime = FakeRuntime(built_repo)

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(runtime_root),
            "--readiness-timeout-s",
            "1",
            "--stop-timeout-s",
            "1",
        ],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 0
    assert [spec.service for spec in runtime.specs] == ["chat_api", "frontend"]
    api, frontend = runtime.specs
    assert api.command == (sys.executable, "-m", "xmuse.chat_api")
    assert frontend.command == (
        "/usr/bin/node",
        str(built_repo / "frontend" / ".next" / "standalone" / "server.js"),
    )
    assert frontend.cwd == built_repo / "frontend" / ".next" / "standalone"
    for spec in runtime.specs:
        assert spec.env["XMUSE_ROOT"] == str(runtime_root.resolve())
        assert spec.env["XMUSE_WORKROOM_MANAGED"] == "1"
        assert spec.env["XMUSE_WORKROOM_GENERATION"] == "generation-one"
        assert spec.env["XMUSE_OPERATOR_TOKEN"] == "super-secret-operator-token"
        assert spec.env["XMUSE_WORKROOM_SERVICE"] == spec.service
    assert api.env["XMUSE_WORKSPACE_ROOT"] == str(built_repo.resolve())
    assert api.env["XMUSE_EXECUTION_PROFILE_ID"] == "xmuse-monorepo/v2"
    assert "XMUSE_WORKSPACE_ROOT" not in frontend.env
    assert "XMUSE_EXECUTION_PROFILE_ID" not in frontend.env
    assert "XMUSE_OPERATOR_TOKEN" not in runtime.dependencies().environ
    assert frontend.env["XMUSE_CHAT_API_BASE_URL"] == ("http://127.0.0.1:8201/api/chat")
    assert (frontend.cwd / ".next" / "static" / "chunks" / "app.js").is_file()
    assert (frontend.cwd / "public" / "icon.txt").is_file()
    assert runtime.group_signals == [
        (202, signal.SIGTERM),
        (201, signal.SIGTERM),
    ]
    assert runtime.runtime_stops == [(runtime_root.resolve(), "generation-one")]
    assert runtime.shutdown.installed is True
    assert runtime.shutdown.restored is True

    manifest_text = (runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8")
    assert "super-secret-operator-token" not in manifest_text
    manifest = json.loads(manifest_text)
    assert manifest["schema_version"] == workroom.SCHEMA_VERSION
    assert manifest["generation"] == "generation-one"
    assert manifest["state"] == "stopped"
    assert manifest["manager"]["start_identity"] == "linux-proc-starttime:manager"
    assert manifest["services"]["chat_api"]["start_identity"] == ("linux-proc-starttime:201")
    assert manifest["execution"] == {
        "workspace_root": str(built_repo.resolve()),
        "gate_profile": {
            "schema_version": "room_execution_gate_profile/v1",
            "profile_id": "xmuse-monorepo/v2",
            "revision": 2,
            "gate_ids": [
                "patch_diff_check",
                "backend_ruff",
                "backend_mypy",
                "backend_pytest",
                "frontend_typecheck",
                "frontend_lint",
                "frontend_vitest",
                "frontend_build",
            ],
        },
    }
    output = _output_lines(capsys)
    assert [item["state"] for item in output] == ["ready", "stopped"]
    assert "super-secret-operator-token" not in json.dumps(output)


def test_non_default_workspace_requires_explicit_fixed_profile_before_spawn(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    runtime = FakeRuntime(built_repo)

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(tmp_path / "runtime"),
            "--workspace",
            str(workspace),
        ],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    assert runtime.specs == []
    assert _output_lines(capsys)[-1]["error"]["code"] == "execution_profile_required"


def test_explicit_workspace_and_profile_reach_only_server_side_runtime(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    runtime_root = tmp_path / "runtime"
    runtime = FakeRuntime(built_repo)

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(runtime_root),
            "--workspace",
            str(workspace),
            "--execution-profile",
            "python-uv/v1",
            "--readiness-timeout-s",
            "1",
            "--stop-timeout-s",
            "1",
        ],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 0
    api, frontend = runtime.specs
    assert api.env["XMUSE_WORKSPACE_ROOT"] == str(workspace.resolve())
    assert api.env["XMUSE_EXECUTION_PROFILE_ID"] == "python-uv/v1"
    assert "XMUSE_WORKSPACE_ROOT" not in frontend.env
    assert "XMUSE_EXECUTION_PROFILE_ID" not in frontend.env
    manifest = json.loads((runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["execution"]["workspace_root"] == str(workspace.resolve())
    assert manifest["execution"]["gate_profile"]["profile_id"] == "python-uv/v1"
    output = _output_lines(capsys)
    assert output[0]["execution_profile"]["profile_id"] == "python-uv/v1"
    assert str(workspace.resolve()) not in json.dumps(output)


def test_unknown_execution_profile_is_rejected_before_spawn(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(tmp_path / "runtime"),
            "--execution-profile",
            "repository-owned-command/v1",
        ],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    assert runtime.specs == []
    assert _output_lines(capsys)[-1]["error"]["code"] == ("room_execution_gate_profile_unknown")


def test_start_cleans_api_when_readiness_fails_without_spawning_frontend(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.ready = False
    runtime_root = tmp_path / "runtime"

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(runtime_root),
            "--readiness-timeout-s",
            "0.2",
            "--stop-timeout-s",
            "0.2",
        ],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    assert [spec.service for spec in runtime.specs] == ["chat_api"]
    assert runtime.group_signals == [(201, signal.SIGTERM)]
    manifest = json.loads((runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["state"] == "failed"
    assert manifest["failure"]["code"] == "readiness_timeout"
    assert _output_lines(capsys)[0]["error"]["code"] == "readiness_timeout"


def test_memory_opt_in_uses_isolated_sidecar_env_and_server_only_chat_api_key(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    dependencies = runtime.dependencies()
    dependencies.memory_key_factory = lambda: "memory-server-secret"
    dependencies.environ = {
        **dependencies.environ,
        "OPENAI_API_KEY": "provider-secret",
        "HTTP_PROXY": "http://proxy.invalid",
    }
    runtime_root = tmp_path / "runtime"

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(runtime_root),
            "--memory",
            "--memoryos-executable",
            str(executable),
            "--readiness-timeout-s",
            "1",
            "--stop-timeout-s",
            "1",
        ],
        dependencies=dependencies,
    )

    assert exit_code == 0
    assert [spec.service for spec in runtime.specs] == [
        "memoryos",
        "chat_api",
        "frontend",
    ]
    memory, chat_api, frontend = runtime.specs
    assert memory.command == (
        str(executable.resolve()),
        "api",
        "--host",
        "127.0.0.1",
        "--port",
        "8301",
    )
    assert memory.cwd == runtime_root.resolve() / "runtime" / "memoryos-derived"
    assert memory.env["MEMORYOS_API_KEY"] == "memory-server-secret"
    assert memory.env["DATA_DIR"] == str(memory.cwd)
    assert "OPENAI_API_KEY" not in memory.env
    assert "HTTP_PROXY" not in memory.env
    assert "XMUSE_OPERATOR_TOKEN" not in memory.env
    assert chat_api.env["XMUSE_MEMORYOS_URL"] == "http://127.0.0.1:8301"
    assert chat_api.env["XMUSE_MEMORYOS_API_KEY"] == "memory-server-secret"
    assert "XMUSE_MEMORYOS_URL" not in frontend.env
    assert "XMUSE_MEMORYOS_API_KEY" not in frontend.env
    assert runtime.group_signals == [
        (203, signal.SIGTERM),
        (202, signal.SIGTERM),
        (201, signal.SIGTERM),
    ]
    manifest_text = (runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8")
    assert "memory-server-secret" not in manifest_text
    assert "http://127.0.0.1:8301" not in manifest_text
    assert "memory-server-secret" not in json.dumps(_output_lines(capsys))


def test_memory_unknown_port_degrades_but_still_hands_fixed_capability_to_chat_api(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    dependencies = runtime.dependencies()
    dependencies.memory_key_factory = lambda: "memory-server-secret"
    dependencies.port_available = lambda _host, port: (
        False if port == workroom.MEMORYOS_PORT else True
    )

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(tmp_path / "runtime"),
            "--memory",
            "--memoryos-executable",
            str(executable),
        ],
        dependencies=dependencies,
    )

    assert exit_code == 0
    assert [spec.service for spec in runtime.specs] == ["chat_api", "frontend"]
    assert runtime.specs[0].env["XMUSE_MEMORYOS_URL"] == "http://127.0.0.1:8301"
    assert runtime.specs[0].env["XMUSE_MEMORYOS_API_KEY"] == "memory-server-secret"
    assert "XMUSE_MEMORYOS_API_KEY" not in runtime.specs[1].env
    assert [item["state"] for item in _output_lines(capsys)] == ["ready", "stopped"]


def test_memory_sidecar_exit_is_optional_and_does_not_fail_workroom(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DelayedShutdown(ImmediateShutdown):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def requested(self) -> bool:
            self.calls += 1
            return self.calls >= 3

    runtime = FakeRuntime(built_repo)
    runtime.shutdown = DelayedShutdown()
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)
    dependencies = runtime.dependencies()
    original_sleep = dependencies.sleep

    def sleep(seconds: float) -> None:
        original_sleep(seconds)
        if len(runtime.specs) == 3:
            memory = runtime.processes[201]
            memory.returncode = 7
            runtime.identities.pop(201, None)

    dependencies.sleep = sleep

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(tmp_path / "runtime"),
            "--memory",
            "--memoryos-executable",
            str(executable),
        ],
        dependencies=dependencies,
    )

    assert exit_code == 0
    assert [item["state"] for item in _output_lines(capsys)] == ["ready", "stopped"]


def test_start_cleans_a_spawned_child_when_identity_registration_times_out(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.publish_spawn_identity = False
    runtime_root = tmp_path / "runtime"

    exit_code = workroom.run_cli(
        [
            "start",
            "--root",
            str(runtime_root),
            "--readiness-timeout-s",
            "1",
            "--stop-timeout-s",
            "1",
        ],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    assert [spec.service for spec in runtime.specs] == ["chat_api"]
    assert runtime.group_signals == [(201, signal.SIGTERM)]
    manifest = json.loads((runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["state"] == "failed"
    assert manifest["failure"]["code"] == "process_identity_timeout"
    assert _output_lines(capsys)[0]["error"]["code"] == "process_identity_timeout"


def test_start_converts_spawn_oserror_into_a_failed_manifest(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    dependencies = runtime.dependencies()
    dependencies.spawn = lambda _spec: (_ for _ in ()).throw(OSError("spawn failed"))
    runtime_root = tmp_path / "runtime"

    exit_code = workroom.run_cli(
        ["start", "--root", str(runtime_root)],
        dependencies=dependencies,
    )

    assert exit_code == 1
    manifest = json.loads((runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["state"] == "failed"
    assert manifest["failure"] == {"code": "start_failed", "message": "spawn failed"}
    assert _output_lines(capsys)[0]["error"]["code"] == "start_failed"


def test_duplicate_start_is_rejected_before_any_spawn(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    exit_code = workroom.run_cli(
        ["start", "--root", str(runtime_root)],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    assert _output_lines(capsys)[0]["error"]["code"] == "already_running"


def test_start_reclaims_stale_manifest_generation_before_spawning_new_services(
    built_repo: Path,
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    stale = _ready_manifest(runtime, runtime_root, generation="generation-old")
    stale["manager"]["start_identity"] = "linux-proc-starttime:old-manager"
    runtime.identities.pop(301)
    runtime.identities.pop(302)
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, stale)
    dependencies = runtime.dependencies()
    events: list[tuple[str, str]] = []
    original_spawn = dependencies.spawn
    original_stop = dependencies.stop_runtime

    def stop_runtime(root: Path, generation: str):
        events.append(("stop", generation))
        return original_stop(root, generation)

    def spawn(spec: workroom.ProcessSpec):
        events.append(("spawn", spec.service))
        return original_spawn(spec)

    dependencies.stop_runtime = stop_runtime
    dependencies.spawn = spawn

    assert (
        workroom.start_workroom(
            workroom.WorkroomPaths.resolve(runtime_root, built_repo),
            dependencies,
            readiness_timeout_s=1.0,
            stop_timeout_s=1.0,
        )
        == 0
    )

    assert events[0] == ("stop", "generation-old")
    assert events[1] == ("spawn", "chat_api")


def test_status_requires_generation_scoped_live_processes(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    assert (
        workroom.run_cli(
            ["status", "--root", str(runtime_root)],
            dependencies=runtime.dependencies(),
        )
        == 0
    )
    payload = _output_lines(capsys)[0]
    assert payload["state"] == "ready"
    assert all(item["ready"] for item in payload["services"])

    runtime.identities[301].environment["XMUSE_WORKROOM_GENERATION"] = "older-generation"
    assert (
        workroom.run_cli(
            ["status", "--root", str(runtime_root)],
            dependencies=runtime.dependencies(),
        )
        == 1
    )
    payload = _output_lines(capsys)[0]
    assert payload["state"] == "degraded"
    assert (
        next(item for item in payload["services"] if item["service"] == "chat_api")["live"] is False
    )


def test_status_includes_generation_scoped_room_runner_and_room_mcp(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    assert (
        workroom.run_cli(
            ["status", "--root", str(runtime_root)],
            dependencies=runtime.dependencies(),
        )
        == 0
    )
    payload = _output_lines(capsys)[0]
    assert [item["service"] for item in payload["services"]] == [
        "frontend",
        "chat_api",
        "room_runner",
        "room_mcp",
        "memoryos",
    ]
    memory = payload["services"][-1]
    assert memory["state"] == "disabled"
    assert memory["code"] == "memoryos_disabled"
    assert all(item["ready"] for item in payload["services"])
    runner = next(item for item in payload["services"] if item["service"] == "room_runner")
    assert runner["code"] == "ready"
    assert runner["host"] == {
        "state": "unknown",
        "code": "room_runner_host_health_unknown",
        "active_delivery_count": 0,
        "retained_cleanup_count": 0,
    }


def test_memory_degraded_status_does_not_change_required_workroom_readiness(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    manifest["features"] = {"memoryos": True}
    services = manifest["services"]
    assert isinstance(services, dict)
    services["memoryos"] = {
        "service": "memoryos",
        "pid": 403,
        "pgid": 403,
        "start_identity": "linux-proc-starttime:403",
        "generation": "generation-one",
        "port": 8301,
    }
    runtime.identities[403] = workroom.ProcessIdentity(
        start_identity="linux-proc-starttime:403",
        pgid=403,
        environment={
            "XMUSE_ROOT": str(runtime_root.resolve()),
            "XMUSE_WORKROOM_GENERATION": "generation-one",
            "XMUSE_WORKROOM_SERVICE": "memoryos",
        },
    )
    workroom.write_memoryos_status(
        runtime_root,
        enabled=True,
        state="ready",
        code="ready",
        generation="generation-one",
        pid=403,
        start_identity="linux-proc-starttime:403",
        started_at="2026-07-11T00:00:00Z",
        heartbeat_at="2026-07-11T00:00:00Z",
    )
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)
    dependencies = runtime.dependencies()
    dependencies.http_ready = lambda url: False if "127.0.0.1:8301" in url else True

    assert workroom.run_cli(["status", "--root", str(runtime_root)], dependencies=dependencies) == 0
    payload = _output_lines(capsys)[0]
    assert payload["state"] == "ready"
    memory = payload["services"][-1]
    assert memory["service"] == "memoryos"
    assert memory["state"] == "degraded"
    assert memory["code"] == "memoryos_health_unavailable"
    assert memory["ready"] is False
    assert {"pid", "port", "url", "generation", "start_identity"}.isdisjoint(memory)


def test_status_reports_v2_blocked_host_as_degraded(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    status_path = runtime_root / "room-runner-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["schema_version"] = "room_runner_status/v2"
    status.pop("xmuse_root")
    status["host"] = {
        "state": "blocked",
        "code": "room_skill_catalog_drift",
        "active_delivery_count": 1,
        "retained_cleanup_count": 0,
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    assert (
        workroom.run_cli(
            ["status", "--root", str(runtime_root)],
            dependencies=runtime.dependencies(),
        )
        == 1
    )

    payload = _output_lines(capsys)[0]
    runner = next(item for item in payload["services"] if item["service"] == "room_runner")
    assert payload["state"] == "degraded"
    assert runner["live"] is True
    assert runner["ready"] is False
    assert runner["code"] == "room_runner_host_blocked"
    assert runner["host"] == status["host"]


def test_status_honors_manifest_custom_runner_status_path(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    default_status = runtime_root / "room-runner-status.json"
    custom_status = runtime_root / "receipts" / "custom-room-runner-status.json"
    custom_status.parent.mkdir()
    custom_status.write_bytes(default_status.read_bytes())
    default_status.unlink()
    manifest["supervised"] = {"room_runner_status_file": str(custom_status)}
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    assert (
        workroom.run_cli(
            ["status", "--root", str(runtime_root)],
            dependencies=runtime.dependencies(),
        )
        == 0
    )

    payload = _output_lines(capsys)[0]
    runner = next(item for item in payload["services"] if item["service"] == "room_runner")
    assert runner["ready"] is True
    assert runner["host"]["state"] == "unknown"


def test_status_reports_live_stale_room_runner_as_degraded_without_signalling(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    _seed_room_runtime(runtime, runtime_root, manifest)
    status_path = runtime_root / "room-runner-status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["heartbeat_at"] = "2026-07-10T23:59:39Z"
    status_path.write_text(json.dumps(status), encoding="utf-8")
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    assert (
        workroom.run_cli(
            ["status", "--root", str(runtime_root)],
            dependencies=runtime.dependencies(),
        )
        == 1
    )

    payload = _output_lines(capsys)[0]
    runner = next(item for item in payload["services"] if item["service"] == "room_runner")
    assert payload["state"] == "degraded"
    assert runner["live"] is True
    assert runner["ready"] is False
    assert runtime.group_signals == []


def test_stop_reconciles_orphaned_services_in_frontend_then_api_order(
    built_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = FakeRuntime(built_repo)
    runtime.spawn_forbidden = True
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    manifest = _ready_manifest(runtime, runtime_root)
    runtime.identities.pop(runtime.current_pid)
    workroom._atomic_write_manifest(runtime_root / workroom.MANIFEST_NAME, manifest)

    exit_code = workroom.run_cli(
        ["stop", "--root", str(runtime_root), "--timeout-s", "0.2"],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 0
    assert runtime.group_signals == [
        (302, signal.SIGTERM),
        (301, signal.SIGTERM),
    ]
    stopped = json.loads((runtime_root / workroom.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert stopped["state"] == "stopped"
    assert _output_lines(capsys)[0]["stopped_services"] == ["frontend", "chat_api"]


def test_doctor_is_read_only_and_reports_missing_build(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runtime = FakeRuntime(repo_root)
    runtime.spawn_forbidden = True

    exit_code = workroom.run_cli(
        ["doctor", "--root", str(tmp_path / "runtime")],
        dependencies=runtime.dependencies(),
    )

    assert exit_code == 1
    payload = _output_lines(capsys)[0]
    assert payload["state"] == "blocked"
    blocker_names = {item["name"] for item in payload["checks"] if item["status"] == "blocker"}
    assert blocker_names == {"standalone_build", "static_assets"}
    assert not (tmp_path / "runtime").exists()
