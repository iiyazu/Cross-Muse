"""Static, non-authoritative dependency evidence for xmuse architecture reviews.

The report deliberately uses source syntax instead of importing project modules: it is safe
to run against a fresh checkout and it cannot initialise a runtime.  It is an internal tool;
the JSON is evidence for CI and review rather than a product API.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

SCHEMA_VERSION = "xmuse_architecture_dependency_report/v1"


@dataclass(frozen=True)
class _ModuleSource:
    name: str
    path: Path
    layer: Literal["core", "application", "script"]


def _module_name_for_path(root: Path, path: Path, package: str) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join((package, *parts))


def _discover_modules(project_root: Path) -> dict[str, _ModuleSource]:
    specifications = (
        (project_root / "src" / "xmuse_core", "xmuse_core", "core"),
        (project_root / "xmuse", "xmuse", "application"),
        (project_root / "scripts", "scripts", "script"),
    )
    modules: dict[str, _ModuleSource] = {}
    for root, package, layer in specifications:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            name = _module_name_for_path(root, path, package)
            modules[name] = _ModuleSource(
                name=name,
                path=path,
                layer=cast(Literal["core", "application", "script"], layer),
            )
    return modules


def _resolve_from_import(
    *,
    module_name: str,
    node: ast.ImportFrom,
    alias_name: str,
    known_modules: Mapping[str, _ModuleSource],
) -> str | None:
    if node.level:
        package_parts = module_name.split(".")[:-1]
        ascend = max(node.level - 1, 0)
        if ascend > len(package_parts):
            return None
        prefix_parts = package_parts[: len(package_parts) - ascend]
        module_parts = node.module.split(".") if node.module else []
        base = ".".join((*prefix_parts, *module_parts))
    else:
        base = node.module or ""

    candidates = (f"{base}.{alias_name}" if base else alias_name, base)
    return next((candidate for candidate in candidates if candidate in known_modules), None)


def _imports_for_module(
    source: _ModuleSource, known_modules: Mapping[str, _ModuleSource]
) -> set[str]:
    tree = ast.parse(source.path.read_text(encoding="utf-8"), filename=str(source.path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in known_modules:
                    imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                resolved = _resolve_from_import(
                    module_name=source.name,
                    node=node,
                    alias_name=alias.name,
                    known_modules=known_modules,
                )
                if resolved is not None:
                    imported.add(resolved)
    return imported


def _strongly_connected_components(graph: Mapping[str, set[str]]) -> list[list[str]]:
    """Tarjan SCCs, returning only cycles in stable order."""

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(name: str) -> None:
        nonlocal index
        indices[name] = index
        lowlinks[name] = index
        index += 1
        stack.append(name)
        on_stack.add(name)
        for target in sorted(graph[name]):
            if target not in indices:
                visit(target)
                lowlinks[name] = min(lowlinks[name], lowlinks[target])
            elif target in on_stack:
                lowlinks[name] = min(lowlinks[name], indices[target])
        if lowlinks[name] != indices[name]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == name:
                break
        if len(component) > 1 or name in graph[name]:
            components.append(sorted(component))

    for name in sorted(graph):
        if name not in indices:
            visit(name)
    return sorted(components)


def _is_read_model(module_name: str) -> bool:
    leaf = module_name.rsplit(".", 1)[-1]
    return "projection" in leaf or leaf.endswith("_read_store") or leaf.endswith("_views")


def _is_privileged_read_dependency(module_name: str) -> bool:
    leaf = module_name.rsplit(".", 1)[-1]
    return "supervisor" in leaf or leaf.endswith("_cli") or "operator_store" in leaf


def _adapter_debts(modules: Mapping[str, _ModuleSource]) -> list[dict[str, str]]:
    """Find narrow-named stores that construct a wider store or ledger implementation.

    This is intentionally evidence, not an allowlist-backed exception mechanism.  A private
    member is still reported because it is the concrete authority hidden behind a narrow port.
    """

    debts: list[dict[str, str]] = []
    for name, source in modules.items():
        if not name.startswith("xmuse_core."):
            continue
        tree = ast.parse(source.path.read_text(encoding="utf-8"), filename=str(source.path))
        imported_authorities: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            for alias in node.names:
                if alias.name.endswith(("Store", "Ledger")):
                    imported_authorities.add(alias.asname or alias.name)
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            if not class_node.name.endswith("Store") or class_node.name in imported_authorities:
                continue
            for call in (node for node in ast.walk(class_node) if isinstance(node, ast.Call)):
                if isinstance(call.func, ast.Name) and call.func.id in imported_authorities:
                    debts.append(
                        {
                            "module": name,
                            "adapter": class_node.name,
                            "concrete_store": call.func.id,
                        }
                    )
    return sorted(debts, key=lambda item: (item["module"], item["adapter"], item["concrete_store"]))


def build_report(project_root: Path) -> dict[str, Any]:
    """Build a JSON-serialisable report without importing project code."""

    root = project_root.resolve()
    modules = _discover_modules(root)
    graph = {name: _imports_for_module(source, modules) for name, source in modules.items()}
    cycles = _strongly_connected_components(graph)
    incoming: dict[str, int] = defaultdict(int)
    for targets in graph.values():
        for target in targets:
            incoming[target] += 1

    core_to_app = sorted(
        (
            {"source": source, "target": target}
            for source, targets in graph.items()
            if modules[source].layer == "core"
            for target in targets
            if target == "xmuse" or target.startswith("xmuse.")
        ),
        key=lambda item: (item["source"], item["target"]),
    )
    core_to_memoryos: list[dict[str, str]] = []
    for source, targets in graph.items():
        if modules[source].layer != "core":
            continue
        for target in targets:
            if target == "memoryos_lite" or target.startswith("memoryos_lite."):
                core_to_memoryos.append({"source": source, "target": target})
    core_to_memoryos.sort(key=lambda item: (item["source"], item["target"]))
    # memoryos_lite is normally external and therefore absent from the local graph.  Scan the
    # parsed syntax separately so the boundary remains visible in a source-only report.
    for module_source in modules.values():
        if module_source.layer != "core":
            continue
        tree = ast.parse(
            module_source.path.read_text(encoding="utf-8"), filename=str(module_source.path)
        )
        names = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        for imported in names:
            if imported == "memoryos_lite" or imported.startswith("memoryos_lite."):
                entry = {"source": module_source.name, "target": imported}
                if entry not in core_to_memoryos:
                    core_to_memoryos.append(entry)
    core_to_memoryos.sort(key=lambda item: (item["source"], item["target"]))

    read_model_violations = sorted(
        (
            {"source": source, "target": target}
            for source, targets in graph.items()
            if _is_read_model(source)
            for target in targets
            if _is_privileged_read_dependency(target)
        ),
        key=lambda item: (item["source"], item["target"]),
    )
    adapter_debts = _adapter_debts(modules)
    cross_layer_edges = sorted(
        (
            {
                "source": source,
                "source_layer": modules[source].layer,
                "target": target,
                "target_layer": modules[target].layer,
            }
            for source, targets in graph.items()
            for target in targets
            if modules[source].layer != modules[target].layer
        ),
        key=lambda item: (item["source"], item["target"]),
    )
    fanout = [
        {"module": name, "outgoing_edges": outgoing_edges, "incoming_edges": incoming_edges}
        for name, outgoing_edges, incoming_edges in sorted(
            ((name, len(targets), incoming[name]) for name, targets in graph.items()),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    hard_violations = {
        "import_cycles": cycles,
        "core_to_application": core_to_app,
        "core_to_memoryos_lite": core_to_memoryos,
        "read_model_to_privileged": read_model_violations,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_boundary": "static_source_dependency_evidence_not_runtime_authority",
        "scope": "repository_source_tree",
        "summary": {
            "module_count": len(modules),
            "edge_count": sum(len(targets) for targets in graph.values()),
            "cycle_count": len(cycles),
            "hard_violation_count": (
                len(cycles) + len(core_to_app) + len(core_to_memoryos) + len(read_model_violations)
            ),
            "capability_debt_count": len(adapter_debts),
        },
        "hard_violations": hard_violations,
        "capability_debts": adapter_debts,
        "cross_layer_edges": cross_layer_edges,
        "fanout_evidence": fanout,
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Return stable codes for report hard-gate failures.

    Capability debts remain explicit evidence until the owning refactor removes them; they are
    never hidden by a path-specific suppression.  This keeps G0 mergeable while making G3's
    concrete target observable.
    """

    if report.get("schema_version") != SCHEMA_VERSION:
        return ["architecture_report_schema_invalid"]
    violations = report.get("hard_violations")
    if not isinstance(violations, Mapping):
        return ["architecture_report_hard_violations_invalid"]
    codes: list[str] = []
    for field, code in (
        ("import_cycles", "architecture_import_cycle"),
        ("core_to_application", "architecture_core_to_application"),
        ("core_to_memoryos_lite", "architecture_core_to_memoryos_lite"),
        ("read_model_to_privileged", "architecture_read_model_privileged"),
    ):
        if violations.get(field):
            codes.append(code)
    return codes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build xmuse static dependency evidence")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = build_report(args.project_root)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.write_text(encoded, encoding="utf-8")
    return 0 if not validate_report(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
