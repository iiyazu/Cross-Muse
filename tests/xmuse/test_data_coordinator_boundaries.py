from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from xmuse import data_cli

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_CLI = REPO_ROOT / "xmuse" / "data_cli.py"
DATA_AUTHORITY = REPO_ROOT / "xmuse" / "data_authority.py"
DATA_RESTORE = REPO_ROOT / "xmuse" / "data_restore.py"
DATA_COMPACT = REPO_ROOT / "xmuse" / "data_compact.py"
READ_SIDE = (
    REPO_ROOT / "xmuse" / "data_runtime_guard.py",
    REPO_ROOT / "xmuse" / "data_doctor.py",
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


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent is not None else node.attr
    return None


def _called_names(tree: ast.AST) -> set[str]:
    return {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := _dotted_name(node.func)) is not None
    }


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_data_cli_is_dispatch_and_thin_public_coordinator_wrappers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    modules = _imported_modules(_tree(DATA_CLI))
    assert {
        "xmuse.data_authority",
        "xmuse.data_inspection",
        "xmuse.data_mutation",
        "xmuse.workroom",
        "xmuse.workroom_process",
        "xmuse_core.runtime.processes",
    }.isdisjoint(modules)

    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def restore(*args: object, **kwargs: object) -> dict[str, Any]:
        calls.append(("restore", args, kwargs))
        return {"state": "succeeded"}

    def compact(*args: object, **kwargs: object) -> dict[str, Any]:
        calls.append(("compact", args, kwargs))
        return {"state": "succeeded"}

    monkeypatch.setattr(data_cli._data_restore, "restore_data", restore)
    monkeypatch.setattr(data_cli._data_compact, "compact_data", compact)
    root = tmp_path / "runtime"
    backup = tmp_path / "backup"

    assert data_cli.restore_data(root, backup, replace=True)["state"] == "succeeded"
    assert data_cli.compact_data(root)["state"] == "succeeded"
    assert calls == [
        (
            "restore",
            (root, backup),
            {"replace": True, "runtime_guard": data_cli._runtime_stopped},
        ),
        ("compact", (root,), {"runtime_guard": data_cli._runtime_stopped}),
    ]


def test_data_leaves_do_not_reverse_import_cli() -> None:
    leaves = {path for path in (REPO_ROOT / "xmuse").glob("data_*.py") if path != DATA_CLI}
    assert leaves
    for leaf in leaves:
        assert "xmuse.data_cli" not in _imported_modules(_tree(leaf)), leaf.name


@pytest.mark.parametrize("module", READ_SIDE, ids=lambda path: path.stem)
def test_runtime_read_side_has_no_write_signal_or_spawn_capability(module: Path) -> None:
    tree = _tree(module)
    assert {"signal", "subprocess", "xmuse.data_mutation", "xmuse.workroom"}.isdisjoint(
        _imported_modules(tree)
    )
    forbidden_calls = {
        "commit",
        "close",
        "mkdir",
        "open",
        "replace",
        "rename",
        "rmdir",
        "rmtree",
        "spawn",
        "unlink",
        "write_bytes",
        "write_text",
        "os.kill",
        "os.killpg",
    }
    calls = _called_names(tree)
    assert forbidden_calls.isdisjoint(calls)
    assert forbidden_calls.isdisjoint({name.rsplit(".", 1)[-1] for name in calls})


def test_authority_connection_api_cannot_own_transactions_or_schema_lifecycle() -> None:
    calls = _called_names(_tree(DATA_AUTHORITY))
    forbidden_leaf_calls = {
        "close",
        "commit",
        "initialize",
        "initialize_schema",
        "migrate",
        "run_migrations",
    }
    assert forbidden_leaf_calls.isdisjoint({name.rsplit(".", 1)[-1] for name in calls})


@pytest.mark.parametrize(
    ("module", "entrypoint"),
    ((DATA_RESTORE, "restore_data"), (DATA_COMPACT, "compact_data")),
)
def test_destructive_coordinators_use_explicit_leaf_capabilities_and_double_guard(
    module: Path,
    entrypoint: str,
) -> None:
    tree = _tree(module)
    imports = _imported_modules(tree)
    assert {"xmuse.data_cli", "xmuse.workroom", "xmuse_core.runtime.processes"}.isdisjoint(imports)
    assert not any(
        alias.name == "*"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )
    coordinator = _function(tree, entrypoint)
    guards = [
        node
        for node in ast.walk(coordinator)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "runtime_guard"
    ]
    assert len(guards) == 2
