from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import pytest

from xmuse.data_contracts import DataError
from xmuse.data_runtime_guard import ProcessDiscovery, assert_runtime_stopped, runtime_probe
from xmuse.workroom_contracts import WorkroomError
from xmuse.workroom_inspection import WorkroomStatusInspection


def _stopped() -> dict[str, Any]:
    return {
        "managed": {"state": "stopped", "manager_live": False, "services": []},
        "inventory": {"services": []},
        "global_inventory": {"services": []},
    }


def test_runtime_probe_reads_scoped_and_global_process_evidence(tmp_path: Path) -> None:
    calls: list[Path | None] = []

    def inspect(_paths: object, _deps: object) -> WorkroomStatusInspection:
        return WorkroomStatusInspection(
            1,
            {"state": "stopped", "manager_live": False, "services": []},
        )

    def discover(
        _proc_root: Path = Path("/proc"),
        *,
        xmuse_root: Path | None = None,
        workroom_generation: str | None = None,
    ) -> dict[str, Any]:
        del workroom_generation
        calls.append(xmuse_root)
        return {"services": []}

    root = tmp_path / "root"
    evidence = runtime_probe(
        root,
        inspector=inspect,
        discover=cast(ProcessDiscovery, discover),
    )

    assert evidence["managed"]["state"] == "stopped"
    assert calls == [root.resolve(), None]
    assert not root.exists()


def test_runtime_probe_maps_invalid_manifest_to_unverifiable_evidence(tmp_path: Path) -> None:
    def invalid(_paths: object, _deps: object) -> WorkroomStatusInspection:
        raise WorkroomError("invalid_manifest", "private manifest path")

    evidence = runtime_probe(
        tmp_path,
        inspector=invalid,
        discover=lambda *_args, **_kwargs: {"services": []},
    )
    assert evidence["managed"] == {
        "schema_version": "xmuse_workroom_status/v2",
        "state": "error",
        "manager_live": False,
        "services": [],
    }
    with pytest.raises(DataError) as exc_info:
        assert_runtime_stopped(tmp_path, probe=lambda _root: evidence)
    assert exc_info.value.code == "workroom_state_unverifiable"


@pytest.mark.parametrize(
    "service",
    [
        "execution_controller",
        "room_runner",
        "room_mcp",
        "runner",
        "mcp",
        "chat_api",
        "dashboard_api",
        "memoryos",
    ],
)
def test_global_authority_services_fail_closed(service: str, tmp_path: Path) -> None:
    evidence = _stopped()
    evidence["global_inventory"] = {"services": [{"service": service, "pids": [22, 11, 22]}]}
    with pytest.raises(DataError) as exc_info:
        assert_runtime_stopped(tmp_path, probe=lambda _root: evidence)
    assert exc_info.value.code == "workroom_running"
    assert exc_info.value.details == {"pids": [11, 22]}


def test_transport_only_global_processes_do_not_claim_data_authority(tmp_path: Path) -> None:
    evidence = _stopped()
    evidence["global_inventory"] = {
        "services": [
            {"service": "codex_app_server", "pids": [31]},
            {"service": "codex_worker", "pids": [32]},
        ]
    }
    assert_runtime_stopped(tmp_path, probe=lambda _root: evidence)


def test_runtime_guard_module_has_no_lifecycle_or_mutation_capability() -> None:
    module = Path(__file__).resolve().parents[2] / "xmuse" / "data_runtime_guard.py"
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "xmuse.workroom" not in imports
    assert {"signal", "subprocess"}.isdisjoint(imports)
    assert {"kill", "killpg", "spawn", "signal_pid", "signal_group"}.isdisjoint(called_attributes)
