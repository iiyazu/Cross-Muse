from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scripts.export_xmuse import export_xmuse_project

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_export_xmuse_project_copies_manifest_roots_and_pyproject(tmp_path: Path) -> None:
    destination = tmp_path / "xmuse-export"

    result = export_xmuse_project(PROJECT_ROOT, destination)

    assert result.destination == destination
    assert result.copied_roots == [
        "xmuse",
        "src/xmuse_core",
        "docs/xmuse",
        "scripts/export_xmuse.py",
        "tests/xmuse",
        "tests/fixtures/xmuse",
    ]
    pyproject = tomllib.loads((destination / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "xmuse"
    assert set(pyproject["project"]["scripts"]) == {
        "xmuse-chat-api",
        "xmuse-mcp-server",
        "xmuse-platform-runner",
        "xmuse-tui",
    }
    assert (destination / "xmuse" / "chat_api.py").exists()
    assert (destination / "src" / "xmuse_core" / "__init__.py").exists()
    assert (destination / "scripts" / "export_xmuse.py").exists()
    assert (destination / "tests" / "xmuse" / "test_split_export_contract.py").exists()


def test_export_xmuse_project_does_not_add_local_memoryos_uv_source(tmp_path: Path) -> None:
    destination = tmp_path / "xmuse-export"

    export_xmuse_project(PROJECT_ROOT, destination)

    pyproject = tomllib.loads((destination / "pyproject.toml").read_text(encoding="utf-8"))
    assert "uv" not in pyproject.get("tool", {}) or "sources" not in pyproject["tool"]["uv"]
    assert not any(
        dependency.startswith("memoryos-lite")
        for dependency in pyproject["project"]["dependencies"]
    )


def test_export_xmuse_project_excludes_runtime_state(tmp_path: Path) -> None:
    destination = tmp_path / "xmuse-export"

    result = export_xmuse_project(PROJECT_ROOT, destination)

    assert result.excluded_count > 0
    assert (destination / "xmuse" / "contracts" / "master_dispatch_template.json").exists()
    assert (destination / "xmuse" / "contracts" / "slave_dispatch_template.json").exists()
    assert not (destination / "xmuse" / "master_state.json").exists()
    assert not (destination / "xmuse" / "feature_lanes.json").exists()
    assert not (destination / "xmuse" / "chat.db").exists()
    assert not (destination / "xmuse" / "history").exists()
    assert not (destination / "xmuse" / "lane_graphs").exists()
    assert not (destination / "xmuse" / "work").exists()


def test_export_xmuse_project_rejects_existing_nonempty_destination(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "xmuse-export"
    destination.mkdir()
    (destination / "keep.txt").write_text("do not delete", encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_xmuse_project(PROJECT_ROOT, destination)

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "do not delete"


def test_export_xmuse_project_force_replaces_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "xmuse-export"
    destination.mkdir()
    (destination / "old.txt").write_text("replace me", encoding="utf-8")

    export_xmuse_project(PROJECT_ROOT, destination, force=True)

    assert not (destination / "old.txt").exists()
    assert (destination / "pyproject.toml").exists()
