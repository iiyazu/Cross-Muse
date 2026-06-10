from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _imports_module(path: Path, module_name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module_name or node.module.startswith(f"{module_name}."):
                return True
    return False


def test_ray_imports_stay_isolated_to_ray_agent_adapter() -> None:
    production_paths = [
        path
        for root in (PROJECT_ROOT / "src" / "xmuse_core", PROJECT_ROOT / "xmuse")
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and "history" not in path.parts
    ]

    ray_importers = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in production_paths
        if _imports_module(path, "ray")
    )

    assert ray_importers == ["src/xmuse_core/agents/ray_god_actor.py"]


def test_native_runtime_modules_do_not_import_ray_actor_adapter() -> None:
    native_entrypoints = [
        PROJECT_ROOT / "xmuse" / "platform_runner.py",
        PROJECT_ROOT / "src" / "xmuse_core" / "platform",
        PROJECT_ROOT / "src" / "xmuse_core" / "structuring",
    ]
    checked_paths = [
        path
        for entrypoint in native_entrypoints
        for path in ([entrypoint] if entrypoint.is_file() else entrypoint.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]

    ray_actor_importers = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in checked_paths
        if _imports_module(path, "xmuse_core.agents.ray_god_actor")
    )

    assert ray_actor_importers == []
