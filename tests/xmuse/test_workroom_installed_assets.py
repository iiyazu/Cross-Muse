from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from xmuse.workroom_contracts import WorkroomDependencies, WorkroomError, WorkroomPaths
from xmuse.workroom_services import WorkroomServicesCoordinator


def _write_frontend_assets(root: Path) -> None:
    standalone = root / "frontend" / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("// server\n", encoding="utf-8")
    static = root / "frontend" / ".next" / "static"
    static.mkdir(parents=True)
    (static / "app.js").write_text("static\n", encoding="utf-8")


def _dependencies(repo_root: Path, assets_root: Path | None) -> WorkroomDependencies:
    return WorkroomDependencies(
        repo_root=repo_root,
        assets_root=assets_root,
        environ={"PATH": "/usr/bin"},
        which=lambda name: f"/usr/bin/{name}" if name in {"node", "codex"} else None,
        port_available=lambda _host, _port: True,
    )


def test_source_layout_remains_the_two_argument_default(tmp_path: Path) -> None:
    repository = tmp_path / "source repo"
    _write_frontend_assets(repository)

    paths = WorkroomPaths.resolve(tmp_path / "runtime", repository)
    coordinator = WorkroomServicesCoordinator(paths, _dependencies(repository, None))

    assert paths.assets_root == repository.resolve()
    assert paths.repo_root == repository.resolve()
    assert paths.frontend_dir == repository.resolve() / "frontend"
    assert coordinator.preflight() == "/usr/bin/node"


def test_installed_assets_are_independent_from_execution_source(tmp_path: Path) -> None:
    repository = tmp_path / "execution source"
    repository.mkdir()
    assets = tmp_path / "installed assets with spaces"
    _write_frontend_assets(assets)
    dependencies = _dependencies(repository, assets)

    paths = WorkroomPaths.resolve(
        tmp_path / "runtime",
        dependencies.repo_root,
        dependencies.assets_root,
    )
    coordinator = WorkroomServicesCoordinator(paths, dependencies)

    assert paths.repo_root == repository.resolve()
    assert paths.assets_root == assets.resolve()
    assert paths.standalone_server == (
        assets.resolve() / "frontend" / ".next" / "standalone" / "server.js"
    )
    assert coordinator.preflight() == "/usr/bin/node"


def test_environment_can_select_installed_assets(tmp_path: Path) -> None:
    repository = tmp_path / "execution"
    repository.mkdir()
    assets = tmp_path / "assets"
    _write_frontend_assets(assets)

    dependencies = WorkroomDependencies(
        repo_root=repository,
        environ={"XMUSE_ASSETS_ROOT": str(assets)},
    )

    assert dependencies.assets_root == assets.resolve()


def test_installed_venv_detects_version_sibling_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "execution"
    repository.mkdir()
    version = tmp_path / "versions" / "0.3.0"
    installed = version / "share" / "xmuse"
    _write_frontend_assets(installed)
    monkeypatch.setattr(sys, "prefix", str(version / ".venv"))

    dependencies = WorkroomDependencies(repo_root=repository, environ={})

    assert dependencies.assets_root == installed.resolve()


@pytest.mark.parametrize(
    ("missing", "expected_code"),
    [
        ("server", "standalone_build_missing"),
        ("static", "static_assets_missing"),
    ],
)
def test_installed_asset_missing_errors_remain_stable(
    tmp_path: Path,
    missing: str,
    expected_code: str,
) -> None:
    repository = tmp_path / "execution"
    repository.mkdir()
    assets = tmp_path / "assets"
    _write_frontend_assets(assets)
    if missing == "server":
        (assets / "frontend" / ".next" / "standalone" / "server.js").unlink()
    else:
        static = assets / "frontend" / ".next" / "static"
        for child in static.iterdir():
            child.unlink()
        static.rmdir()
    paths = WorkroomPaths.resolve(tmp_path / "runtime", repository, assets)

    with pytest.raises(WorkroomError) as raised:
        WorkroomServicesCoordinator(paths, _dependencies(repository, assets)).preflight()

    assert raised.value.code == expected_code
    assert "frontend/.next" not in str(raised.value)


def test_frontend_symlink_escape_fails_closed(tmp_path: Path) -> None:
    repository = tmp_path / "execution"
    repository.mkdir()
    assets = tmp_path / "assets"
    assets.mkdir()
    outside = tmp_path / "outside"
    _write_frontend_assets(outside)
    os.symlink(outside / "frontend", assets / "frontend", target_is_directory=True)
    paths = WorkroomPaths.resolve(tmp_path / "runtime", repository, assets)

    with pytest.raises(WorkroomError) as raised:
        WorkroomServicesCoordinator(paths, _dependencies(repository, assets)).preflight()

    assert raised.value.code == "frontend_assets_unsafe"


def test_standalone_destination_symlink_escape_fails_closed(tmp_path: Path) -> None:
    repository = tmp_path / "execution"
    repository.mkdir()
    assets = tmp_path / "assets"
    _write_frontend_assets(assets)
    outside = tmp_path / "outside"
    outside.mkdir()
    standalone = assets / "frontend" / ".next" / "standalone"
    os.symlink(outside, standalone / ".next", target_is_directory=True)
    paths = WorkroomPaths.resolve(tmp_path / "runtime", repository, assets)

    with pytest.raises(WorkroomError) as raised:
        WorkroomServicesCoordinator(paths, _dependencies(repository, assets)).preflight()

    assert raised.value.code == "frontend_assets_unsafe"


def test_chat_api_cwd_is_not_derived_from_installed_assets(tmp_path: Path) -> None:
    repository = tmp_path / "package runtime"
    repository.mkdir()
    assets = tmp_path / "assets"
    _write_frontend_assets(assets)
    paths = WorkroomPaths.resolve(tmp_path / "runtime", repository, assets)

    assert paths.repo_root == repository.resolve()
    assert paths.repo_root != paths.assets_root


def test_missing_service_cwd_fails_before_spawn(tmp_path: Path) -> None:
    repository = tmp_path / "missing runtime"
    assets = tmp_path / "assets"
    _write_frontend_assets(assets)
    paths = WorkroomPaths.resolve(tmp_path / "runtime", repository, assets)

    with pytest.raises(WorkroomError) as raised:
        WorkroomServicesCoordinator(paths, _dependencies(repository, assets)).preflight()

    assert raised.value.code == "service_cwd_missing"
