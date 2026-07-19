from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from xmuse_core.chat import room_kernel
from xmuse_core.runtime.paths import default_xmuse_root

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = PROJECT_ROOT / "src" / "xmuse_core"
APP_ROOT = PROJECT_ROOT / "xmuse"
LOCAL_IMPORT_ROOTS = ("xmuse_core", "xmuse", "scripts")

DEFAULT_ENTRYPOINT_IMPORTS = (
    ("xmuse.chat_api", "chat_api"),
    ("xmuse.room_runner", "room_runner"),
    ("xmuse.room_mcp_server", "room_mcp_server"),
    ("xmuse.workroom_cli", "workroom"),
    ("xmuse.data_cli", "data_cli"),
)


def _python_files(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def _imports_prefix(path: Path, prefix: str) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for name in _imports(path))


def _local_module_exists(module_name: str) -> bool:
    parts = module_name.split(".")
    base = PROJECT_ROOT / "src" if parts[0] == "xmuse_core" else PROJECT_ROOT
    path = base.joinpath(*parts)
    return path.with_suffix(".py").is_file() or path.is_dir()


def test_core_does_not_depend_on_application_layer() -> None:
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _python_files(CORE_ROOT)
        if _imports_prefix(path, "xmuse")
    ]

    assert offenders == []


def test_core_does_not_import_memoryos_lite_directly() -> None:
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in _python_files(CORE_ROOT)
        if _imports_prefix(path, "memoryos_lite")
    ]

    assert offenders == []


def test_room_runner_entrypoint_does_not_own_memoryos_adapter_or_stores() -> None:
    """Keep optional memory implementation details behind one app composition port."""

    runner = APP_ROOT / "room_runner.py"
    forbidden = (
        "xmuse.memoryos_adapter",
        "xmuse_core.chat.room_memory_delivery_store",
        "xmuse_core.chat.room_memory_recall_store",
        "xmuse_core.chat.room_execution_store",
    )

    assert [prefix for prefix in forbidden if _imports_prefix(runner, prefix)] == []


def test_room_runner_lifecycle_does_not_wire_provider_object_graph() -> None:
    runner = APP_ROOT / "room_runner.py"
    wiring_modules = (
        "xmuse_core.agents.god_session_layer",
        "xmuse_core.chat.room_agent_stream",
        "xmuse_core.chat.room_codex_projection_cache",
        "xmuse_core.chat.room_codex_transport",
        "xmuse_core.chat.room_host",
    )

    assert [prefix for prefix in wiring_modules if _imports_prefix(runner, prefix)] == []


def test_room_delivery_surfaces_depend_on_execution_review_ports() -> None:
    """Room delivery must not acquire the privileged execution ledger surface."""

    guarded = (
        CORE_ROOT / "chat" / "room_host.py",
        CORE_ROOT / "chat" / "room_codex_transport.py",
    )

    privileged_surfaces = (
        "xmuse_core.chat.room_execution_store",
        "xmuse_core.chat.room_execution_controller_store",
        "xmuse_core.chat.room_execution_operator_store",
        "xmuse_core.chat.room_execution_runtime_store",
    )
    assert [
        f"{path.relative_to(PROJECT_ROOT).as_posix()}: {surface}"
        for path in guarded
        for surface in privileged_surfaces
        if _imports_prefix(path, surface)
    ] == []


def test_outcome_transition_plan_is_frozen_and_normalized_without_room_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider input is staged before, and independently of, a Room transaction."""

    def no_database_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("outcome normalization must not open Room authority")

    monkeypatch.setattr(room_kernel, "RoomDatabase", no_database_access)
    payload = {"content": "  ready  ", "mentioned_participant_ids": ["p2"]}
    plan = room_kernel.normalize_outcome_transition_plan(
        conversation_id="conversation",
        participant_id="p1",
        caller_identity="god:session:p1",
        observation_id="observation",
        lease_token="lease",
        client_request_id="request",
        outcome_type="respond",
        outcome_payload=payload,
        observation_batch_id=None,
        reply_to_activity_id=None,
        proposal_assessments=None,
        memory_candidates=None,
        max_causal_depth=4,
    )

    payload["content"] = "changed after normalization"
    assert plan.normalized_payload == {"content": "ready", "mentioned_participant_ids": ["p2"]}
    with pytest.raises(FrozenInstanceError):
        plan.outcome_type = "noop"  # type: ignore[misc]


def test_execution_conn_helpers_leave_transaction_ownership_to_their_caller() -> None:
    """Leaf helpers participate in the enclosing durable outcome/review transaction."""

    targets = {
        CORE_ROOT / "chat" / "room_execution_events.py": {"record_execution_event_conn"},
        CORE_ROOT / "chat" / "room_execution_candidates.py": {
            "review_material_for_batch_conn",
            "bind_review_material_receipt_conn",
        },
    }
    violations: list[str] = []
    for path, helper_names in targets.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in helper_names:
                continue
            if any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in {"commit", "rollback"}
                for call in ast.walk(node)
            ):
                violations.append(f"{path.name}: {node.name}")

    assert violations == []


def test_execution_ledger_views_do_not_own_transactions_or_actions() -> None:
    views = CORE_ROOT / "chat" / "room_execution_views.py"
    forbidden = (
        "xmuse_core.chat.room_database",
        "xmuse_core.chat.room_execution_actions",
        "xmuse_core.chat.room_execution_promotion",
    )

    assert [prefix for prefix in forbidden if _imports_prefix(views, prefix)] == []
    tree = ast.parse(views.read_text(encoding="utf-8"), filename=str(views))
    transaction_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback"}
    }
    assert transaction_calls == set()


def test_execution_ledger_reader_does_not_own_commands() -> None:
    reader = CORE_ROOT / "chat" / "room_execution_read_store.py"
    forbidden = (
        "xmuse_core.chat.room_execution_actions",
        "xmuse_core.chat.room_execution_promotion",
        "xmuse_core.chat.room_execution_review_store",
    )

    assert [prefix for prefix in forbidden if _imports_prefix(reader, prefix)] == []
    tree = ast.parse(reader.read_text(encoding="utf-8"), filename=str(reader))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback"}
        for node in ast.walk(tree)
    )


def test_chat_api_composes_separate_execution_read_and_operator_stores() -> None:
    api = APP_ROOT / "chat_api.py"

    assert _imports_prefix(api, "xmuse_core.chat.room_execution_read_store")
    assert _imports_prefix(api, "xmuse_core.chat.room_execution_operator_store")
    assert not _imports_prefix(api, "xmuse_core.chat.room_execution_store")


def test_execution_controller_entrypoint_uses_controller_capability_store() -> None:
    entrypoint = APP_ROOT / "room_execution_controller.py"

    assert _imports_prefix(entrypoint, "xmuse_core.chat.room_execution_controller_store")
    assert not _imports_prefix(entrypoint, "xmuse_core.chat.room_execution_store")


def test_execution_runtime_uses_reconciler_capability_store() -> None:
    runtime = APP_ROOT / "chat_api_execution_runtime.py"

    assert _imports_prefix(runtime, "xmuse_core.chat.room_execution_runtime_store")
    assert not _imports_prefix(runtime, "xmuse_core.chat.room_execution_store")


def test_execution_capability_stores_do_not_construct_a_wide_execution_ledger() -> None:
    """Each execution capability owns only its narrow transaction seam."""

    stores = (
        CORE_ROOT / "chat" / "room_execution_controller_store.py",
        CORE_ROOT / "chat" / "room_execution_operator_store.py",
        CORE_ROOT / "chat" / "room_execution_runtime_store.py",
    )
    for store in stores:
        source = store.read_text(encoding="utf-8")
        assert "from xmuse_core.chat.room_execution_store import" not in source
        assert "RoomExecutionStore(" not in source
        assert "import _ExecutionLedger" not in source
        assert "_ExecutionLedger(" not in source


def test_production_execution_surface_has_no_aggregate_store_module() -> None:
    """Aggregate fixture wiring belongs in tests, never the shipped package."""

    aggregate = CORE_ROOT / "chat" / "room_execution_store.py"
    assert not aggregate.exists()
    production_roots = (CORE_ROOT, APP_ROOT, PROJECT_ROOT / "scripts")
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for root in production_roots
        for path in _python_files(root)
        if "room_execution_store" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_execution_event_helper_uses_caller_owned_transaction() -> None:
    events = CORE_ROOT / "chat" / "room_execution_events.py"

    tree = ast.parse(events.read_text(encoding="utf-8"), filename=str(events))
    assert not any(
        isinstance(node, ast.Name) and node.id == "RoomDatabase" for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback"}
        for node in ast.walk(tree)
    )


def test_workroom_lifecycle_does_not_own_cli_parsing() -> None:
    lifecycle = APP_ROOT / "workroom.py"
    tree = ast.parse(lifecycle.read_text(encoding="utf-8"), filename=str(lifecycle))
    forbidden_functions = {"build_parser", "run_cli", "main"}

    assert not _imports_prefix(lifecycle, "argparse")
    assert [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in forbidden_functions
    ] == []


def test_surviving_local_imports_resolve() -> None:
    missing: list[str] = []
    roots = (CORE_ROOT, APP_ROOT, PROJECT_ROOT / "scripts", PROJECT_ROOT / "tests" / "xmuse")
    for root in roots:
        for path in _python_files(root):
            for module_name in _imports(path):
                if module_name.startswith(LOCAL_IMPORT_ROOTS) and not _local_module_exists(
                    module_name
                ):
                    missing.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}: {module_name}")

    assert missing == []


def test_room_database_initialization_loads_only_schema_leaves(tmp_path: Path) -> None:
    script = r"""
import json
import sys
from pathlib import Path

from xmuse_core.chat.room_database import RoomDatabase

RoomDatabase(Path(sys.argv[1])).initialize()
forbidden_exact = {
    "xmuse_core.chat.room_controls",
    "xmuse_core.chat.room_execution_store",
    "xmuse_core.chat.room_kernel",
    "xmuse_core.chat.room_operations",
    "xmuse_core.chat.room_skill_decisions",
}
forbidden = sorted(
    name
    for name in sys.modules
    if name in forbidden_exact
    or (name.startswith("xmuse_core.chat.room_") and name.endswith("_store"))
)
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "chat.db")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )

    assert json.loads(result.stdout) == []


def test_runtime_namespace_boundary_stays_explicit() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert not (APP_ROOT / "__init__.py").exists()
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "xmuse",
        "src/xmuse_core",
    ]


def test_read_surfaces_do_not_import_execution_orchestration() -> None:
    guarded = (APP_ROOT / "room_mcp_server.py",)
    forbidden = (
        "xmuse_core.platform.agent_spawner",
        "xmuse_core.platform.orchestrator",
        "xmuse_core.platform.execution.executor",
        "xmuse_core.platform.execution.merger",
    )
    violations = [
        f"{path.name}: {prefix}"
        for path in guarded
        for prefix in forbidden
        if _imports_prefix(path, prefix)
    ]

    assert violations == []


@pytest.mark.parametrize(
    ("module_name", "surface"),
    DEFAULT_ENTRYPOINT_IMPORTS,
    ids=[module_name for module_name, _surface in DEFAULT_ENTRYPOINT_IMPORTS],
)
def test_default_entrypoint_imports_stay_room_only(
    module_name: str,
    surface: str,
    tmp_path: Path,
) -> None:
    """Exercise each public entrypoint in an isolated interpreter.

    Constructing the lightweight public surface catches lazy composition imports while
    avoiding process startup, network listeners, or mutations outside the fresh root.
    """

    script = r"""
import importlib
import json
import sys
from pathlib import Path

module_name, surface, raw_root = sys.argv[1:]
module = importlib.import_module(module_name)
root = Path(raw_root)

if surface == "chat_api":
    module.create_app(
        root,
        workroom_runtime_inspector=lambda *_args: {
            "state": "stopped",
            "ready": False,
            "code": "room_runtime_stopped",
        },
    )
elif surface == "room_mcp_server":
    module.create_app(root)
elif surface == "room_runner":
    module.main_arg_parser()
elif surface in {"workroom", "data_cli"}:
    module.build_parser()
else:
    raise AssertionError(f"unknown entrypoint surface: {surface}")

forbidden_prefixes = (
    "xmuse.compat",
    "xmuse_core.platform",
    "xmuse_core.structuring",
    "xmuse_core.self_evolution",
    "xmuse_core.gates",
    "xmuse_core.sidecar",
    "xmuse_core.integrations.a2a",
    "xmuse_core.integrations.memoryos",
    "a2a",
    "memoryos_lite",
)
forbidden_exact = {
    "xmuse_core.chat.store",
    "xmuse_core.chat.groupchat_worklist",
    "xmuse_core.chat.groupchat_decisions",
    "xmuse_core.chat.groupchat_critic_verdicts",
    "xmuse_core.chat.review_trigger_verdicts",
    "xmuse_core.chat.peer_scheduler",
}
forbidden_stems = (
    "xmuse_core.chat.acceptance",
    "xmuse_core.chat.bootstrap",
    "xmuse_core.chat.inbox",
    "xmuse_core.chat.frontend_projection",
)
forbidden = sorted(
    name
    for name in sys.modules
    if name in forbidden_exact
    or any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
    or any(name.startswith(stem) for stem in forbidden_stems)
)
print(
    json.dumps(
        {
            "entrypoint_loaded": module_name in sys.modules,
            "forbidden": forbidden,
        }
    )
)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            module_name,
            surface,
            str(tmp_path / "fresh-root"),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "entrypoint_loaded": True,
        "forbidden": [],
    }


def test_xmuse_root_environment_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured_root = tmp_path / "runtime"
    monkeypatch.setenv("XMUSE_ROOT", str(configured_root))

    assert default_xmuse_root(PROJECT_ROOT / "xmuse") == configured_root.resolve()
