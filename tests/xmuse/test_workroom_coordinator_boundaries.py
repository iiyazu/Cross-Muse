from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

import pytest

from xmuse import workroom
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomPaths
from xmuse.workroom_inspection import WorkroomStatusInspection

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKROOM = REPO_ROOT / "xmuse" / "workroom.py"
COORDINATORS = (
    REPO_ROOT / "xmuse" / "workroom_inspection.py",
    REPO_ROOT / "xmuse" / "workroom_services.py",
    REPO_ROOT / "xmuse" / "workroom_memoryos_runtime.py",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _imported_capabilities(tree: ast.AST, module: str) -> set[str]:
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent is not None else node.attr
    return None


def _called_capabilities(tree: ast.AST) -> set[str]:
    return {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := _dotted_name(node.func)) is not None
    }


def test_workroom_composes_coordinators_without_reclaiming_leaf_authority() -> None:
    tree = _tree(WORKROOM)
    modules = _imported_modules(tree)
    calls = _called_capabilities(tree)

    assert {
        "xmuse.workroom_inspection",
        "xmuse.workroom_services",
        "xmuse.workroom_memoryos_runtime",
    }.issubset(modules)
    assert {
        "inspect_workroom_status",
        "inspect_workroom_doctor",
        "WorkroomServicesCoordinator",
        "MemoryOSRuntimeCoordinator.create",
    }.issubset(calls)
    assert {
        "signal",
        "xmuse_core.chat.memoryos_supervisor",
        "xmuse_core.chat.room_memory_rebuild_store",
        "xmuse_core.chat.room_runtime_supervisor",
    }.isdisjoint(modules)


@pytest.mark.parametrize("coordinator", COORDINATORS, ids=lambda path: path.stem)
def test_coordinators_do_not_reverse_import_workroom(coordinator: Path) -> None:
    assert "xmuse.workroom" not in _imported_modules(_tree(coordinator))


def test_inspection_has_only_read_side_process_and_manifest_capabilities() -> None:
    tree = _tree(COORDINATORS[0])
    modules = _imported_modules(tree)
    calls = _called_capabilities(tree)

    assert {"signal", "subprocess"}.isdisjoint(modules)
    assert _imported_capabilities(tree, "xmuse.workroom_manifest").isdisjoint(
        {
            "atomic_write_manifest",
            "update_manifest",
            "write_if_generation_current",
        }
    )
    assert {
        "spawn_process",
        "stop_service_record",
        "stop_spawned_processes",
        "atomic_write_manifest",
        "write_if_generation_current",
        "deps.spawn",
        "deps.signal_pid",
        "deps.signal_group",
        "deps.stop_runtime",
        "os.kill",
        "os.killpg",
    }.isdisjoint(calls)


def test_public_status_and_doctor_delegate_to_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = cast(WorkroomPaths, object())
    deps = cast(WorkroomDependencies, object())
    status_calls: list[tuple[WorkroomPaths, WorkroomDependencies]] = []
    doctor_calls: list[tuple[WorkroomPaths, WorkroomDependencies]] = []
    emitted: list[dict[str, object]] = []

    def inspect_status(
        received_paths: WorkroomPaths,
        received_deps: WorkroomDependencies,
    ) -> WorkroomStatusInspection:
        status_calls.append((received_paths, received_deps))
        return WorkroomStatusInspection(
            exit_code=0,
            projection={
                "schema_version": "xmuse_workroom_status/v2",
                "state": "ready",
                "services": [],
            },
            manifest_generation="generation-compat",
        )

    def inspect_doctor(
        received_paths: WorkroomPaths,
        received_deps: WorkroomDependencies,
    ) -> tuple[int, dict[str, object]]:
        doctor_calls.append((received_paths, received_deps))
        return 0, {
            "schema_version": "xmuse_workroom_doctor/v1",
            "state": "ready",
            "checks": [],
            "blocker_count": 0,
            "warning_count": 0,
        }

    monkeypatch.setattr(workroom, "inspect_workroom_status", inspect_status)
    monkeypatch.setattr(workroom, "inspect_workroom_doctor", inspect_doctor)
    monkeypatch.setattr(workroom, "_emit", emitted.append)

    status_code, status = workroom.workroom_status(paths, deps, emit=False)
    doctor_code = workroom.doctor_workroom(paths, deps)

    assert (status_code, status["state"]) == (0, "ready")
    assert doctor_code == 0
    assert status_calls == [(paths, deps)]
    assert doctor_calls == [(paths, deps)]
    assert emitted[0]["schema_version"] == "xmuse_workroom_doctor/v1"
