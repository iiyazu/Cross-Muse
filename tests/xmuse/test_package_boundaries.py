from __future__ import annotations

import ast
import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

XMUSE_CORE = PROJECT_ROOT / "src" / "xmuse_core"
XMUSE_APP = PROJECT_ROOT / "xmuse"

# ── helpers ──────────────────────────────────────────────────────────

ALLOWED_XMUSE_CORE_MEMORYOS_IMPORTS: set[str] = set()


def _imports_module(path: Path, module_prefix: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == module_prefix
                or alias.name.startswith(f"{module_prefix}.")
                for alias in node.names
            ):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module_prefix or node.module.startswith(
                f"{module_prefix}."
            ):
                return True
    return False


def _imports_memoryos_lite(path: Path) -> bool:
    return _imports_module(path, "memoryos_lite")





def _build_type_checking_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            guard = node.test
            if (
                isinstance(guard, ast.Name) and guard.id == "TYPE_CHECKING"
            ) or (
                isinstance(guard, ast.Attribute)
                and isinstance(guard.value, ast.Name)
                and guard.value.id == "typing"
                and guard.attr == "TYPE_CHECKING"
            ):
                start = node.lineno
                end = node.end_lineno or start
                lines.update(range(start, end + 1))
    return lines


def _check_file_boundary(
    rel_path: str,
    forbidden_prefix: str,
    description: str,
) -> None:
    path = PROJECT_ROOT / rel_path
    if not path.exists():
        return
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tc_lines = _build_type_checking_lines(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        lineno = getattr(node, "lineno", 0)
        if lineno in tc_lines:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == forbidden_prefix or alias.name.startswith(
                    f"{forbidden_prefix}."
                ):
                    raise AssertionError(
                        f"{description}\n"
                        f"{rel_path} imports {alias.name} at line {node.lineno}"
                    )
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == forbidden_prefix or node.module.startswith(
                f"{forbidden_prefix}."
            ):
                raise AssertionError(
                    f"{description}\n"
                    f"{rel_path} imports {node.module} at line {node.lineno}"
                )


def _check_boundary(
    importer_dir: str,
    forbidden_prefix: str,
    forbidden_description: str,
    *,
    allowed: set[str] | None = None,
) -> None:
    root = PROJECT_ROOT / importer_dir
    violators: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if allowed and rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tc_lines = _build_type_checking_lines(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            lineno = getattr(node, "lineno", 0)
            if lineno in tc_lines:
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == forbidden_prefix or alias.name.startswith(
                        f"{forbidden_prefix}."
                    ):
                        violators.append(f"{rel}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == forbidden_prefix or node.module.startswith(
                    f"{forbidden_prefix}."
                ):
                    violators.append(f"{rel}:{node.lineno}")
    assert not violators, (
        f"{forbidden_description}\n"
        f"Files in {importer_dir}/ importing {forbidden_prefix}:\n"
        + "\n".join(violators)
    )


# ── memoryos-lite boundary ──────────────────────────────────────────

def test_xmuse_core_memoryos_lite_imports_stay_behind_adapter() -> None:
    importers = sorted(
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in XMUSE_CORE.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.name != "observability.py"
        and _imports_memoryos_lite(path)
    )

    assert importers == sorted(ALLOWED_XMUSE_CORE_MEMORYOS_IMPORTS)


# ── boundary: TUI → provider adapters ───────────────────────────────

def test_tui_does_not_import_provider_adapters_directly() -> None:
    _check_boundary(
        "xmuse/tui",
        "xmuse_core.providers",
        "TUI must not import provider runtime directly; use adapter layer.",
        allowed={
            "xmuse/tui/adapter/xmuse_adapter.py",
        },
    )


# ── boundary: Dashboard/MCP → execution write paths ─────────────────

def test_dashboard_api_does_not_import_execution_write_paths() -> None:
    _check_file_boundary(
        "xmuse/dashboard_api.py",
        "xmuse_core.platform.execution",
        "Dashboard API must not import execution write paths.",
    )


def test_dashboard_api_does_not_import_orchestrator() -> None:
    _check_file_boundary(
        "xmuse/dashboard_api.py",
        "xmuse_core.platform.orchestrator",
        "Dashboard API must not import orchestrator.",
    )


def test_dashboard_api_does_not_import_agent_spawner() -> None:
    _check_file_boundary(
        "xmuse/dashboard_api.py",
        "xmuse_core.platform.agent_spawner",
        "Dashboard API must not import agent spawner.",
    )


def test_mcp_server_does_not_import_execution_write_paths() -> None:
    _check_file_boundary(
        "xmuse/mcp_server.py",
        "xmuse_core.platform.execution",
        "MCP server must not import execution write paths.",
    )


def test_mcp_server_does_not_import_orchestrator() -> None:
    _check_file_boundary(
        "xmuse/mcp_server.py",
        "xmuse_core.platform.orchestrator",
        "MCP server must not import orchestrator.",
    )


def test_mcp_server_does_not_import_agent_spawner() -> None:
    _check_file_boundary(
        "xmuse/mcp_server.py",
        "xmuse_core.platform.agent_spawner",
        "MCP server must not import agent spawner.",
    )


def test_god_room_review_chain_proof_does_not_import_l10_aggregator() -> None:
    _check_file_boundary(
        "src/xmuse_core/platform/god_room_review_chain_proof.py",
        "xmuse_core.platform.release_evidence_candidates",
        "L9 review-chain proof must not depend on the L10 release aggregator.",
    )


def test_platform_runner_uses_public_recovery_dispatch_helper() -> None:
    path = PROJECT_ROOT / "xmuse/platform_runner.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "xmuse_core.platform.orchestrator_lane_flow"
        ):
            imported_names.extend(alias.name for alias in node.names)

    assert "_lane_recovery_dispatch_block_metadata" not in imported_names
    assert "build_lane_recovery_dispatch_block_metadata" in imported_names


# ── boundary: self_evolution → TUI ──────────────────────────────────

def test_self_evolution_does_not_import_tui() -> None:
    _check_boundary(
        "src/xmuse_core/self_evolution",
        "xmuse.tui",
        "Self-evolution must not import TUI modules.",
    )


# ── boundary: xmuse_core/app → dashboard ────────────────────────────

def test_xmuse_core_core_does_not_import_xmuse_app() -> None:
    _check_boundary(
        "src/xmuse_core",
        "xmuse.tui",
        "Core must not import TUI modules.",
    )


def test_xmuse_core_core_does_not_import_dashboard_api() -> None:
    _check_boundary(
        "src/xmuse_core",
        "xmuse.dashboard_api",
        "Core must not import dashboard API.",
    )


def test_xmuse_core_core_does_not_import_mcp_server() -> None:
    _check_boundary(
        "src/xmuse_core",
        "xmuse.mcp_server",
        "Core must not import MCP server.",
    )


# ── boundary: self_evolution → TUI (also check app-level) ───────────

def test_xmuse_app_does_not_import_platform_execution() -> None:
    _check_boundary(
        "xmuse",
        "xmuse_core.platform.execution",
        "Application layer (xmuse/) must not import execution write paths.",
        allowed={
            "xmuse/platform_runner.py",
            "xmuse/master_loop.py",
            "xmuse/slave_job_runner.py",
        },
    )


# ── boundary: providers → platform execution (TYPE_CHECKING only) ───

def test_providers_do_not_import_platform_execution_runtime() -> None:
    _check_boundary(
        "src/xmuse_core/providers",
        "xmuse_core.platform.execution",
        "Providers must not import platform execution runtime.",
    )


# ── XMUSE_ROOT / skill context (existing) ────────────────────────────

def test_xmuse_root_env_overrides_embedded_repo_default(monkeypatch, tmp_path: Path) -> None:
    from xmuse_core.runtime.paths import default_xmuse_root

    monkeypatch.setenv("XMUSE_ROOT", str(tmp_path / "external-xmuse"))

    assert default_xmuse_root(PROJECT_ROOT / "xmuse") == (
        tmp_path / "external-xmuse"
    ).resolve()


def test_skill_context_defaults_runtime_files_from_xmuse_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import xmuse_core.skills.base as skill_base

    monkeypatch.setenv("XMUSE_ROOT", str(tmp_path / "external-xmuse"))
    reloaded = importlib.reload(skill_base)

    context = reloaded.SkillContext(
        registry=None,
        session_manager=None,
        skill_registry=None,
    )

    assert context.feature_root == tmp_path / "external-xmuse" / "work" / "features"
    assert context.prompt_dir == tmp_path / "external-xmuse" / "prompts"
    assert context.lanes_path == tmp_path / "external-xmuse" / "feature_lanes.json"

    importlib.reload(skill_base)
