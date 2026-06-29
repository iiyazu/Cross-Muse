from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from scripts.export_xmuse import export_xmuse_project

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "docs" / "xmuse" / "split-export-manifest.json"
XMUSE_PYPROJECT_TEMPLATE = (
    PROJECT_ROOT / "docs" / "xmuse" / "xmuse-package.pyproject.toml"
)
SOURCE_PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _load_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _load_xmuse_pyproject() -> dict[str, object]:
    return tomllib.loads(XMUSE_PYPROJECT_TEMPLATE.read_text(encoding="utf-8"))


def test_template_pyproject_packages_cover_copy_roots() -> None:
    manifest = _load_manifest()
    template = _load_xmuse_pyproject()

    template_packages = set(template["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    copy_roots = set(manifest["copy_roots"])

    copy_root_packages = {
        r for r in copy_roots
        if (PROJECT_ROOT / r / "__init__.py").exists() or r.startswith("src/")
    }
    assert copy_root_packages.issubset(template_packages), (
        f"copy roots {copy_root_packages - template_packages} not in template packages"
    )


def test_template_entry_points_match_source_project() -> None:
    source = tomllib.loads(SOURCE_PYPROJECT.read_text(encoding="utf-8"))
    template = _load_xmuse_pyproject()

    source_scripts = set(source["project"]["scripts"])
    template_scripts = set(template["project"]["scripts"])

    assert source["project"]["name"] == "xmuse", "source project must be xmuse for this test"
    assert source_scripts == template_scripts, (
        f"Source scripts {source_scripts - template_scripts} "
        f"missing from template; template has "
        f"{template_scripts - source_scripts} not in source"
    )


def test_manifest_required_files_cover_template_entry_points() -> None:
    manifest = _load_manifest()
    template = _load_xmuse_pyproject()

    required_files = set(manifest["required_package_files"])
    template_scripts = dict(template["project"]["scripts"])

    for script_name, module_path in template_scripts.items():
        module = module_path.split(":")[0]
        entry_file = module.replace(".", "/") + ".py"
        if entry_file not in required_files:
            pytest.fail(
                f"Entry point {script_name} -> {module_path} "
                f"(file {entry_file}) "
                f"not in manifest required_package_files"
            )


def test_export_rejects_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        export_xmuse_project(
            PROJECT_ROOT / "nonexistent",
            tmp_path / "export",
        )


def test_export_rejects_empty_destination_not_allowed(tmp_path: Path) -> None:
    destination = tmp_path / "export"
    destination.mkdir()
    dest_file = destination / "stale.txt"
    dest_file.write_text("stale", encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_xmuse_project(PROJECT_ROOT, destination)


def test_export_rejects_self_destination(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="destination must not be the source"):
        export_xmuse_project(PROJECT_ROOT, PROJECT_ROOT)


def test_force_export_replaces_existing_empty_destination(tmp_path: Path) -> None:
    destination = tmp_path / "export"
    destination.mkdir()
    export_xmuse_project(PROJECT_ROOT, destination, force=True)
    assert (destination / "pyproject.toml").exists()


def test_split_export_manifest_declares_source_and_test_roots() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == "xmuse.split_export.v1"
    assert manifest["target_project"] == "xmuse"
    assert manifest["source_project"] == "xmuse"
    assert manifest["package_metadata_template"] == (
        "docs/xmuse/xmuse-package.pyproject.toml"
    )
    assert manifest["copy_roots"] == [
        "xmuse",
        "src/xmuse_core",
        "docs/xmuse",
        "scripts/export_xmuse.py",
        "tests/xmuse",
        "tests/fixtures/xmuse",
    ]


def test_split_export_manifest_no_longer_requires_memoryos_dependency() -> None:
    manifest = _load_manifest()

    notes = "\n".join(str(note) for note in manifest["notes"])
    post_export_checks = "\n".join(str(check) for check in manifest["post_export_checks"])
    assert "must depend on memoryos-lite" not in notes
    assert "/path/to/memoryOS" not in post_export_checks
    assert "must not depend on memoryos-lite" in notes
    assert "local ../memoryOS" in notes


def test_split_export_manifest_required_files_exist() -> None:
    manifest = _load_manifest()

    missing = [
        path
        for path in manifest["required_package_files"]
        if not (PROJECT_ROOT / path).exists()
    ]

    assert missing == []


def test_split_export_manifest_keeps_memoryos_roots_out_of_xmuse_copy_roots() -> None:
    manifest = _load_manifest()

    copy_roots = set(manifest["copy_roots"])
    memoryos_roots = set(manifest["memoryos_owned_roots"])

    assert copy_roots.isdisjoint(memoryos_roots)
    assert memoryos_roots == {"src/memoryos_lite", "tests/memoryos"}


def test_split_export_manifest_excludes_runtime_state_from_source_export() -> None:
    manifest = _load_manifest()

    runtime_patterns = set(manifest["runtime_state_patterns"])

    assert "xmuse/**/*.json" in runtime_patterns
    assert "xmuse/**/*.jsonl" in runtime_patterns
    assert "xmuse/**/*.db" in runtime_patterns
    assert "xmuse/lane_graphs/**" in runtime_patterns
    assert "xmuse/logs/**" in runtime_patterns
    assert "xmuse/history/**" in runtime_patterns
    assert "xmuse/work/**" in runtime_patterns


def test_xmuse_package_template_exports_xmuse_entrypoints_without_memoryos_dependency() -> None:
    pyproject = _load_xmuse_pyproject()
    source = tomllib.loads(SOURCE_PYPROJECT.read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "xmuse"
    assert pyproject["project"]["readme"] == "docs/xmuse/README.md"
    assert set(pyproject["project"]["scripts"]) == set(source["project"]["scripts"])

    dependencies = pyproject["project"]["dependencies"]
    assert not any(dep.startswith("memoryos-lite") for dep in dependencies)
    assert any(dep.startswith("a2a-sdk") for dep in dependencies)
    assert any(dep.startswith("ray[default]") for dep in dependencies)
    assert any(dep.startswith("textual") for dep in dependencies)


def test_project_pyproject_has_no_local_memoryos_source_or_dependency() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]
    assert not any(dep.startswith("memoryos-lite") for dep in dependencies)
    assert "uv" not in pyproject.get("tool", {}) or "sources" not in pyproject["tool"]["uv"]


def test_uv_lock_has_no_local_memoryos_source_or_dependency() -> None:
    lock_text = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")

    assert "memoryos-lite" not in lock_text
    assert "memoryos_lite" not in lock_text
    assert "../memoryOS" not in lock_text
    assert "/home/iiyatu/projects/python/memoryOS" not in lock_text


def test_xmuse_package_template_builds_both_xmuse_packages_and_excludes_state() -> None:
    pyproject = _load_xmuse_pyproject()

    assert pyproject["build-system"]["build-backend"] == "hatchling.build"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "xmuse",
        "src/xmuse_core",
    ]
    assert set(pyproject["tool"]["hatch"]["build"]["exclude"]) >= {
        "/xmuse/**/*.db",
        "/xmuse/**/*.sqlite3",
        "/xmuse/**/*.jsonl",
        "/xmuse/**/*.lock",
        "/xmuse/*.json",
        "/xmuse/approvals/**",
        "/xmuse/dispatch/**",
        "/xmuse/feature_plans/**",
        "/xmuse/history/**",
        "/xmuse/knowledge/**",
        "/xmuse/lane_graphs/**",
        "/xmuse/legacy/**",
        "/xmuse/logs/**",
        "/xmuse/master/**",
        "/xmuse/read_models/**",
        "/xmuse/reports/**",
        "/xmuse/self_evolution/**",
        "/xmuse/work/**",
    }


def test_project_pyproject_entrypoints_match_split_side() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    project_name = pyproject["project"]["name"]
    scripts = set(pyproject["project"]["scripts"])
    if project_name == "memoryos-lite":
        assert scripts == {"memoryos", "memoryos-lite"}
        assert not any(name.startswith("xmuse") for name in scripts)
    elif project_name == "xmuse":
        assert {
            "xmuse-chat-api",
            "xmuse-evidence-summary",
            "xmuse-mcp-server",
            "xmuse-platform-runner",
            "xmuse-tui",
            "xmuse-tui-terminal-demo",
        } <= scripts
        assert all(name.startswith("xmuse") for name in scripts)
        assert not any(name.startswith("memoryos") for name in scripts)
    else:
        raise AssertionError(f"unexpected split project name: {project_name}")
