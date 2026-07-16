from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from xmuse import setup_cli
from xmuse.install_contracts import (
    INSTALL_BUNDLE_SCHEMA,
    INSTALL_PYTHON_ABI,
    InstallError,
)


def _bundle(
    tmp_path: Path,
    *,
    kind: str = "base",
    version: str = "0.3.0",
    files: dict[str, bytes] | None = None,
    frontend_dir: str = "frontend",
    frozen_dependencies: bool = False,
) -> Path:
    if files is None:
        files = (
            {
                "wheelhouse/xmuse-0.3.0-py3-none-any.whl": b"wheel",
                "wheelhouse/dependency.whl": b"dependency",
                f"{frontend_dir}/server.js": b"server",
            }
            if kind == "base"
            else {
                "wheelhouse/memoryos-0.2.0-py3-none-any.whl": b"memory-wheel",
                "models/model.bin": b"model",
                "capability.json": json.dumps(
                    {
                        "schema_version": "xmuse_memoryos_bundle_capability/v1",
                        "profile": "full-local",
                        "fastembed_model": "BAAI/bge-small-en-v1.5",
                        "hybrid": {"bm25": True, "fastembed": True, "rrf": True},
                    }
                ).encode(),
            }
        )
    if frozen_dependencies:
        dependency_root = (
            "payload/python/site-packages" if kind == "base" else "payload/memoryos/site-packages"
        )
        files[f"{dependency_root}/frozen_dependency.py"] = b"frozen = True\n"
    manifest: dict[str, object] = {
        "schema_version": INSTALL_BUNDLE_SCHEMA,
        "bundle_kind": kind,
        "version": version,
        "platform": "linux-x86_64",
        "python_abi": INSTALL_PYTHON_ABI,
        "files": [
            {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            for name, content in files.items()
        ],
    }
    if kind == "base":
        manifest["base"] = {
            "xmuse_wheel": "wheelhouse/xmuse-0.3.0-py3-none-any.whl",
            "frontend_dir": frontend_dir,
            **(
                {"dependency_site_packages": "payload/python/site-packages"}
                if frozen_dependencies
                else {}
            ),
        }
    else:
        manifest["memory"] = {
            "memoryos_wheel": "wheelhouse/memoryos-0.2.0-py3-none-any.whl",
            "capability_manifest": "capability.json",
            "model_cache_dir": "models",
            **(
                {"dependency_site_packages": "payload/memoryos/site-packages"}
                if frozen_dependencies
                else {}
            ),
        }
    path = tmp_path / f"{kind}-{version}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        encoded = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


@pytest.fixture
def fake_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    def create(
        root: Path,
        wheel: str,
        wheelhouse: Path,
        dependency_site_packages: Path | None = None,
    ) -> None:
        assert (root / wheel).is_file()
        assert wheelhouse.is_dir()
        if dependency_site_packages is not None:
            assert dependency_site_packages.is_dir()
        executable = root / ".venv" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.write_text("installed", encoding="utf-8")

    monkeypatch.setattr(setup_cli, "_create_venv", create)


def test_install_is_atomic_and_activates_version(tmp_path: Path, fake_venv: None) -> None:
    prefix = tmp_path / "installed"
    result = setup_cli.install_base(_bundle(tmp_path), prefix)

    assert result == {"status": "installed", "version": "0.3.0", "active": True}
    assert os.readlink(prefix / "active") == "versions/0.3.0"
    assert (prefix / "active" / "frontend" / "server.js").read_bytes() == b"server"
    assert (
        prefix / "active" / "share" / "xmuse" / "frontend" / "server.js"
    ).read_bytes() == b"server"
    assert not list((prefix / "versions").glob(".install-*"))


def test_install_accepts_digest_verified_frozen_dependencies(
    tmp_path: Path, fake_venv: None
) -> None:
    prefix = tmp_path / "installed"
    setup_cli.install_base(_bundle(tmp_path, frozen_dependencies=True), prefix)
    setup_cli.install_memory(
        _bundle(
            tmp_path,
            kind="memoryos",
            version="0.2.0",
            frozen_dependencies=True,
        ),
        prefix,
    )

    assert (prefix / "active" / "memoryos" / "capability.json").is_file()


def test_venv_entrypoints_are_relocated_before_promotion(tmp_path: Path) -> None:
    staging = tmp_path / ".install-random"
    destination = tmp_path / "0.3.0"
    entrypoint = staging / ".venv" / "bin" / "xmuse-workroom"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_bytes(f"#!{staging}/.venv/bin/python\n".encode())
    interpreter = entrypoint.parent / "python"
    interpreter.symlink_to("/usr/bin/python3")

    setup_cli._relocate_venv(staging, destination)

    assert entrypoint.read_bytes() == f"#!{destination}/.venv/bin/python\n".encode()
    assert interpreter.is_symlink()


def test_install_rejects_other_python_abi(tmp_path: Path, fake_venv: None) -> None:
    bundle = _bundle(tmp_path)
    incompatible = tmp_path / "incompatible.tar.gz"
    with tarfile.open(bundle, "r:gz") as source, tarfile.open(incompatible, "w:gz") as target:
        for member in source.getmembers():
            stream = source.extractfile(member)
            content = stream.read() if stream is not None else b""
            if member.name == "manifest.json":
                payload = json.loads(content)
                payload["python_abi"] = "cp999"
                content = json.dumps(payload).encode()
                member.size = len(content)
            target.addfile(member, io.BytesIO(content))

    with pytest.raises(InstallError) as raised:
        setup_cli.install_base(incompatible, tmp_path / "installed")
    assert raised.value.code == "unsupported_python_abi"


def test_install_direct_share_frontend_layout_does_not_duplicate_payload(
    tmp_path: Path, fake_venv: None
) -> None:
    prefix = tmp_path / "installed"
    bundle = _bundle(tmp_path, frontend_dir="share/xmuse/frontend")

    setup_cli.install_base(bundle, prefix)

    assert (prefix / "active" / "share" / "xmuse" / "frontend" / "server.js").is_file()
    assert not (prefix / "active" / "payload").exists()


def test_failed_install_does_not_change_active(tmp_path: Path, fake_venv: None) -> None:
    prefix = tmp_path / "installed"
    setup_cli.install_base(_bundle(tmp_path), prefix)
    source_bundle = _bundle(tmp_path, version="0.3.1")
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(source_bundle, "r:gz") as source, tarfile.open(bad, "w:gz") as target:
        for member in source.getmembers():
            stream = source.extractfile(member)
            content = stream.read() if stream is not None else b""
            if member.name.endswith("xmuse-0.3.0-py3-none-any.whl"):
                content = b"wrong"
                member.size = len(content)
            target.addfile(member, io.BytesIO(content))

    with pytest.raises(InstallError):
        setup_cli.install_base(bad, prefix)

    assert os.readlink(prefix / "active") == "versions/0.3.0"
    assert not (prefix / "versions" / "0.3.1").exists()


def test_activation_failure_removes_promoted_version(
    tmp_path: Path, fake_venv: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "installed"

    def fail_activate(_prefix: Path, _version: str) -> None:
        raise OSError("simulated activation failure")

    monkeypatch.setattr(setup_cli, "_activate", fail_activate)
    with pytest.raises(OSError):
        setup_cli.install_base(_bundle(tmp_path), prefix)

    assert not (prefix / "versions" / "0.3.0").exists()


def test_archive_rejects_symlink_member(tmp_path: Path, fake_venv: None) -> None:
    bundle = _bundle(tmp_path)
    replacement = tmp_path / "unsafe.tar.gz"
    with tarfile.open(bundle, "r:gz") as source, tarfile.open(replacement, "w:gz") as target:
        for member in source.getmembers():
            stream = source.extractfile(member) if member.isfile() else None
            target.addfile(member, stream)
        link = tarfile.TarInfo("payload-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        target.addfile(link)

    with pytest.raises(InstallError, match="non-regular") as raised:
        setup_cli.install_base(replacement, tmp_path / "prefix")
    assert raised.value.code == "unsafe_archive"


def test_install_rejects_symlinked_versions_directory(tmp_path: Path, fake_venv: None) -> None:
    prefix = tmp_path / "installed"
    outside = tmp_path / "outside"
    outside.mkdir()
    prefix.mkdir()
    (prefix / "versions").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InstallError) as raised:
        setup_cli.install_base(_bundle(tmp_path), prefix)
    assert raised.value.code == "invalid_installation"
    assert not list(outside.iterdir())


def test_install_memory_is_scoped_to_active_version(tmp_path: Path, fake_venv: None) -> None:
    prefix = tmp_path / "installed"
    setup_cli.install_base(_bundle(tmp_path), prefix)

    result = setup_cli.install_memory(_bundle(tmp_path, kind="memoryos", version="0.2.0"), prefix)

    assert result["version"] == "0.3.0"
    assert result["memoryos_version"] == "0.2.0"
    assert (prefix / "active" / "memoryos" / "capability.json").is_file()


def test_uninstall_rejects_active_and_removes_inactive(tmp_path: Path, fake_venv: None) -> None:
    prefix = tmp_path / "installed"
    setup_cli.install_base(_bundle(tmp_path, version="0.3.0"), prefix)
    setup_cli.install_base(_bundle(tmp_path, version="0.3.1"), prefix)

    with pytest.raises(InstallError) as raised:
        setup_cli.uninstall(prefix, "0.3.1")
    assert raised.value.code == "active_version"

    setup_cli._activate(prefix, "0.3.0")
    assert setup_cli.uninstall(prefix, "0.3.1")["status"] == "uninstalled"
    assert not (prefix / "versions" / "0.3.1").exists()


def test_verify_reports_safe_state_without_prefix(
    tmp_path: Path, fake_venv: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "secret-user-name" / "installed"
    setup_cli.install_base(_bundle(tmp_path), prefix)
    monkeypatch.setattr(setup_cli.shutil, "which", lambda _name: "/bin/tool")

    result = setup_cli.verify(prefix)

    assert result["status"] == "ok"
    assert result["memoryos"] == "not_installed"
    assert str(prefix) not in json.dumps(result)


def test_verify_rejects_tampered_install_receipt(tmp_path: Path, fake_venv: None) -> None:
    prefix = tmp_path / "installed"
    setup_cli.install_base(_bundle(tmp_path), prefix)
    (prefix / "active" / "install-receipt.json").write_text("{}", encoding="utf-8")

    with pytest.raises(InstallError) as raised:
        setup_cli.verify(prefix)
    assert raised.value.code == "invalid_installation"


def test_cli_returns_stable_error_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = setup_cli.main(["verify", "--prefix", str(tmp_path / "missing")])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_code"] == "active_version_missing"
    assert str(tmp_path) not in payload["message"]


def test_tar_zst_fails_closed(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.tar.zst"
    bundle.write_bytes(b"not-zstd")
    with pytest.raises(InstallError) as raised:
        setup_cli.install_base(bundle, tmp_path / "prefix")
    assert raised.value.code == "unsupported_archive"
