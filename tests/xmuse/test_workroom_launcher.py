from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from xmuse import workroom_cli, workroom_launcher
from xmuse.memoryos_companion import MemoryOSCompanionError
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomPaths
from xmuse.workroom_launcher import (
    ManagedMemoryOSError,
    WorkroomLaunchDependencies,
    WorkroomLaunchRequest,
    _prepare_managed_memoryos_cache,
    launch_workroom,
)


@dataclass
class FakeManager:
    return_code: int | None = None
    terminated: bool = False
    killed: bool = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        assert self.return_code is not None
        return self.return_code


class LaunchFixture:
    def __init__(self, states: Sequence[str]) -> None:
        self.states = list(states)
        self.status_index = 0
        self.clock = 0.0
        self.manager = FakeManager()
        self.spawned: list[tuple[str, ...]] = []
        self.opened: list[str] = []
        self.managed_memoryos: Path | None = None
        self.prepared_memoryos: list[tuple[Path, Path]] = []

    def status(
        self,
        _paths: WorkroomPaths,
        _dependencies: WorkroomDependencies,
    ) -> tuple[int, Mapping[str, object]]:
        index = min(self.status_index, len(self.states) - 1)
        self.status_index += 1
        state = self.states[index]
        return (0 if state == "ready" else 1), {"state": state}

    def spawn(self, argv: Sequence[str]) -> FakeManager:
        self.spawned.append(tuple(argv))
        return self.manager

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def open_browser(self, url: str) -> bool:
        self.opened.append(url)
        return True

    def dependencies(self) -> WorkroomLaunchDependencies:
        return WorkroomLaunchDependencies(
            spawn_manager=self.spawn,
            status=self.status,
            open_browser=self.open_browser,
            resolve_managed_memoryos=lambda: self.managed_memoryos,
            prepare_managed_memoryos_cache=lambda executable, root: self.prepared_memoryos.append(
                (executable, root)
            ),
            sleep=self.sleep,
            monotonic=lambda: self.clock,
            python_executable="/opt/xmuse/bin/python",
        )


def _paths(tmp_path: Path) -> WorkroomPaths:
    return WorkroomPaths.resolve(tmp_path / "root", tmp_path / "repo")


def _request(tmp_path: Path, **changes: object) -> WorkroomLaunchRequest:
    values: dict[str, object] = {
        "root": tmp_path / "root",
        "readiness_timeout_s": 3.0,
        "stop_timeout_s": 2.0,
    }
    values.update(changes)
    return WorkroomLaunchRequest(**values)  # type: ignore[arg-type]


def test_launch_forwards_all_start_arguments_and_opens_after_ready(tmp_path: Path) -> None:
    fixture = LaunchFixture(["stopped", "degraded", "ready"])
    memoryos = tmp_path / "explicit-memoryos"
    memoryos.write_text("executable", encoding="utf-8")
    memoryos.chmod(0o700)
    fixture.managed_memoryos = tmp_path / "managed-memoryos"
    request = _request(
        tmp_path,
        workspace=tmp_path / "workspace",
        execution_profile="python-uv/v1",
        memory=True,
        memoryos_executable=memoryos,
        memory_profile="full-local",
    )

    exit_code, payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        request,
        dependencies=fixture.dependencies(),
    )

    assert exit_code == 0
    assert payload["state"] == "ready"
    assert payload["already_running"] is False
    assert fixture.opened == ["http://127.0.0.1:3000"]
    assert fixture.spawned == [
        (
            "/opt/xmuse/bin/python",
            "-m",
            "xmuse.workroom_cli",
            "start",
            "--root",
            str(tmp_path / "root"),
            "--readiness-timeout-s",
            "3.0",
            "--stop-timeout-s",
            "2.0",
            "--workspace",
            str(tmp_path / "workspace"),
            "--execution-profile",
            "python-uv/v1",
            "--memory",
            "--memoryos-executable",
            str(memoryos),
            "--memory-profile",
            "full-local",
        )
    ]


def test_ready_second_launch_does_not_spawn_and_no_open_is_respected(tmp_path: Path) -> None:
    fixture = LaunchFixture(["ready"])

    exit_code, payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        _request(tmp_path, open_browser=False),
        dependencies=fixture.dependencies(),
    )

    assert exit_code == 0
    assert payload["already_running"] is True
    assert payload["browser_opened"] is None
    assert fixture.spawned == []
    assert fixture.opened == []


def test_existing_degraded_workroom_is_not_replaced(tmp_path: Path) -> None:
    fixture = LaunchFixture(["degraded"])

    exit_code, payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        _request(tmp_path),
        dependencies=fixture.dependencies(),
    )

    assert exit_code == 1
    assert payload["error"] == {
        "code": "workroom_not_launchable",
        "message": "the existing Workroom is degraded; inspect status before launch",
    }
    assert fixture.spawned == []


def test_timeout_stops_only_the_created_manager(tmp_path: Path) -> None:
    fixture = LaunchFixture(["stopped", "degraded"])

    exit_code, payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        _request(tmp_path, readiness_timeout_s=0.2),
        dependencies=fixture.dependencies(),
    )

    assert exit_code == 1
    assert payload["error"] == {
        "code": "launch_readiness_timeout",
        "message": "the Workroom did not become ready in time",
    }
    assert fixture.manager.terminated is True
    assert fixture.manager.killed is False
    assert len(fixture.spawned) == 1


def test_managed_memoryos_is_used_only_without_explicit_path(tmp_path: Path) -> None:
    fixture = LaunchFixture(["stopped", "ready"])
    managed = tmp_path / "managed-memoryos"
    managed.write_text("executable", encoding="utf-8")
    managed.chmod(0o700)
    fixture.managed_memoryos = managed

    exit_code, _payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        _request(tmp_path, memory=True, open_browser=False),
        dependencies=fixture.dependencies(),
    )

    assert exit_code == 0
    assert fixture.spawned[0][-2:] == ("--memoryos-executable", str(managed))
    assert fixture.prepared_memoryos == [(managed, tmp_path / "root")]


def test_missing_managed_memoryos_returns_stable_error_without_spawn(tmp_path: Path) -> None:
    fixture = LaunchFixture(["stopped"])

    exit_code, payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        _request(tmp_path, memory=True),
        dependencies=fixture.dependencies(),
    )

    assert exit_code == 1
    assert payload["error"] == {
        "code": "memoryos_executable_required",
        "message": "--memory requires an explicit or managed MemoryOS executable",
    }
    assert fixture.spawned == []


def test_invalid_managed_memoryos_returns_stable_error_without_spawn(tmp_path: Path) -> None:
    fixture = LaunchFixture(["stopped"])

    def invalid_companion() -> Path | None:
        raise MemoryOSCompanionError("memoryos_companion_manifest_invalid")

    dependencies = replace(
        fixture.dependencies(),
        resolve_managed_memoryos=invalid_companion,
    )

    exit_code, payload = launch_workroom(
        _paths(tmp_path),
        WorkroomDependencies(),
        _request(tmp_path, memory=True),
        dependencies=dependencies,
    )

    assert exit_code == 1
    assert payload["error"] == {
        "code": "memoryos_companion_manifest_invalid",
        "message": "the managed MemoryOS companion is invalid",
    }
    assert fixture.spawned == []


def test_default_managed_memoryos_resolver_uses_active_install_layout(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    executable = tmp_path / "active" / "memoryos" / ".venv" / "bin" / "memoryos"
    executable.parent.mkdir(parents=True)
    executable.write_text("executable", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setattr(workroom_launcher.sys, "prefix", str(tmp_path / "active" / ".venv"))  # type: ignore[attr-defined]

    assert workroom_launcher._managed_memoryos_executable() == executable


def test_managed_memoryos_cache_is_staged_into_runtime_root(tmp_path: Path) -> None:
    executable = tmp_path / "active" / "memoryos" / ".venv" / "bin" / "memoryos"
    executable.parent.mkdir(parents=True)
    executable.write_text("executable", encoding="utf-8")
    model = tmp_path / "active" / "memoryos" / "payload" / "memoryos" / "model-cache" / "model.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")

    _prepare_managed_memoryos_cache(executable, tmp_path / "root")

    staged = tmp_path / "root" / "runtime" / "fastembed-cache" / "model.onnx"
    assert staged.read_bytes() == b"model"


def test_managed_memoryos_cache_rejects_symlink(tmp_path: Path) -> None:
    executable = tmp_path / "active" / "memoryos" / ".venv" / "bin" / "memoryos"
    executable.parent.mkdir(parents=True)
    executable.write_text("executable", encoding="utf-8")
    cache = tmp_path / "active" / "memoryos" / "payload" / "memoryos" / "model-cache"
    cache.mkdir(parents=True)
    (cache / "escape").symlink_to(tmp_path / "outside")

    with pytest.raises(ManagedMemoryOSError, match="managed_memoryos_cache_invalid"):
        _prepare_managed_memoryos_cache(executable, tmp_path / "root")


def test_cli_no_open_and_forwarding_use_launch_contract(
    tmp_path: Path,
    capsys: object,
) -> None:
    fixture = LaunchFixture(["stopped", "ready"])

    exit_code = workroom_cli.run_cli(
        [
            "launch",
            "--root",
            str(tmp_path / "root"),
            "--workspace",
            str(tmp_path / "workspace"),
            "--execution-profile",
            "docs/v1",
            "--readiness-timeout-s",
            "4",
            "--stop-timeout-s",
            "5",
            "--no-open",
        ],
        dependencies=WorkroomDependencies(repo_root=tmp_path / "repo"),
        launch_dependencies=fixture.dependencies(),
    )

    assert exit_code == 0
    assert fixture.opened == []
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["command"] == "launch"
    argv = fixture.spawned[0]
    assert argv[argv.index("--workspace") + 1] == str(tmp_path / "workspace")
    assert argv[argv.index("--execution-profile") + 1] == "docs/v1"
    assert argv[argv.index("--readiness-timeout-s") + 1] == "4.0"
    assert argv[argv.index("--stop-timeout-s") + 1] == "5.0"


def test_cli_ready_auto_launch_does_not_discover_or_stage_companion(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = LaunchFixture(["ready"])
    monkeypatch.setattr(
        workroom_cli,
        "discover_managed_companion",
        lambda: pytest.fail("ready launch must not inspect the companion"),
    )
    monkeypatch.setattr(
        workroom_cli,
        "_prepare_managed_memoryos_cache",
        lambda *_args: pytest.fail("ready launch must not rewrite the model cache"),
    )

    exit_code = workroom_cli.run_cli(
        ["launch", "--root", str(tmp_path / "root"), "--no-open"],
        dependencies=WorkroomDependencies(repo_root=tmp_path / "repo"),
        launch_dependencies=fixture.dependencies(),
    )

    assert exit_code == 0
    assert fixture.spawned == []
    assert json.loads(capsys.readouterr().out)["already_running"] is True  # type: ignore[attr-defined]
