from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from scripts import build_install_bundle
from scripts.build_install_bundle import BundleBuildError, build_base_bundle, build_memory_bundle
from xmuse.install_contracts import INSTALL_PYTHON_ABI


def _write(path: Path, content: bytes = b"fixture") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _manifest(bundle: Path) -> dict[str, object]:
    with tarfile.open(bundle, "r:gz") as archive:
        member = archive.extractfile("manifest.json")
        assert member is not None
        return json.loads(member.read())


def test_base_bundle_is_deterministic_and_source_complete(tmp_path: Path) -> None:
    wheel = _write(tmp_path / "xmuse-0.2.0-py3-none-any.whl")
    dependency = _write(tmp_path / "wheelhouse" / "fastapi-1-py3-none-any.whl", b"dep")
    server = _write(tmp_path / "standalone" / "server.js", b"server")
    static = _write(tmp_path / "static" / "app.js", b"app")
    frozen_dependency = _write(
        tmp_path / "site-packages" / "pydantic" / "__init__.py",
        b"frozen",
    )
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    for output in (first, second):
        build_base_bundle(
            output=output,
            version="0.3.0",
            source_commit="abc123",
            xmuse_wheel=wheel,
            wheelhouse=dependency.parent,
            frontend_standalone=server.parent,
            frontend_static=static.parent,
            dependency_site_packages=frozen_dependency.parents[1],
        )

    first_digest = hashlib.sha256(first.read_bytes()).digest()
    second_digest = hashlib.sha256(second.read_bytes()).digest()
    assert first_digest == second_digest
    manifest = _manifest(first)
    assert manifest["schema_version"] == "xmuse_install_bundle/v1"
    assert manifest["bundle_kind"] == "base"
    assert manifest["platform"] == "linux-x86_64"
    assert manifest["python_abi"] == INSTALL_PYTHON_ABI
    paths = {item["path"] for item in manifest["files"]}  # type: ignore[index]
    assert paths == {
        "share/xmuse/frontend/.next/standalone/server.js",
        "share/xmuse/frontend/.next/static/app.js",
        "payload/python/wheelhouse/fastapi-1-py3-none-any.whl",
        "payload/python/wheelhouse/xmuse-0.2.0-py3-none-any.whl",
        "payload/python/site-packages/pydantic/__init__.py",
    }
    assert manifest["base"]["dependency_site_packages"] == (  # type: ignore[index]
        "payload/python/site-packages"
    )


def test_memory_bundle_freezes_capability_and_model_cache(tmp_path: Path) -> None:
    wheel = _write(tmp_path / "memoryos_lite-0.2.0-py3-none-any.whl")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    model = _write(tmp_path / "models" / "model.onnx", b"model")
    frozen_dependency = _write(
        tmp_path / "site-packages" / "fastembed" / "__init__.py",
        b"frozen",
    )
    capability = _write(
        tmp_path / "capability.json",
        json.dumps(
            {
                "schema_version": "xmuse_memoryos_bundle_capability/v1",
                "profile": "full-local",
                "fastembed_model": "BAAI/bge-small-en-v1.5",
                "hybrid": {"bm25": True, "fastembed": True, "rrf": True},
            }
        ).encode(),
    )
    output = tmp_path / "memory.tar.gz"

    build_memory_bundle(
        output=output,
        version="0.2.0",
        source_commit="memory-sha",
        memoryos_wheel=wheel,
        wheelhouse=wheelhouse,
        model_cache=model.parent,
        capability_manifest=capability,
        dependency_site_packages=frozen_dependency.parents[1],
    )

    manifest = _manifest(output)
    assert manifest["bundle_kind"] == "memoryos"
    assert manifest["memory"] == {
        "memoryos_wheel": "payload/memoryos/wheelhouse/memoryos_lite-0.2.0-py3-none-any.whl",
        "dependency_site_packages": "payload/memoryos/site-packages",
        "capability_manifest": "payload/memoryos/capability.json",
        "model_cache_dir": "payload/memoryos/model-cache",
    }


def test_builder_rejects_symlinks_and_non_gzip_output(tmp_path: Path) -> None:
    wheel = _write(tmp_path / "xmuse.whl")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    frontend = tmp_path / "frontend"
    _write(frontend / "server.js")
    (frontend / "escape").symlink_to(tmp_path / "outside")

    with pytest.raises(BundleBuildError, match="bundle_input_symlink"):
        build_base_bundle(
            output=tmp_path / "bundle.tar.gz",
            version="0.3.0",
            source_commit="sha",
            xmuse_wheel=wheel,
            wheelhouse=wheelhouse,
            frontend_standalone=frontend,
            frontend_static=frontend,
        )

    (frontend / "escape").unlink()
    with pytest.raises(BundleBuildError, match="bundle_output_format_unsupported"):
        build_base_bundle(
            output=tmp_path / "bundle.tar.zst",
            version="0.3.0",
            source_commit="sha",
            xmuse_wheel=wheel,
            wheelhouse=wheelhouse,
            frontend_standalone=frontend,
            frontend_static=frontend,
        )


def test_gzip_header_does_not_embed_output_name(tmp_path: Path) -> None:
    wheel = _write(tmp_path / "xmuse.whl")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    frontend = tmp_path / "frontend"
    _write(frontend / "server.js")
    output = tmp_path / "candidate-name.tar.gz"
    build_base_bundle(
        output=output,
        version="0.3.0",
        source_commit="sha",
        xmuse_wheel=wheel,
        wheelhouse=wheelhouse,
        frontend_standalone=frontend,
        frontend_static=frontend,
    )
    with output.open("rb") as handle:
        with gzip.GzipFile(fileobj=handle) as archive:
            assert archive.read(8)
    assert b"candidate-name" not in output.read_bytes()[:256]


def test_builder_rejects_manifest_above_installer_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _write(tmp_path / "xmuse.whl")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    frontend = tmp_path / "frontend"
    _write(frontend / "server.js")
    monkeypatch.setattr(build_install_bundle, "MAX_MANIFEST_BYTES", 1)

    with pytest.raises(BundleBuildError, match="bundle_manifest_too_large"):
        build_base_bundle(
            output=tmp_path / "bundle.tar.gz",
            version="0.3.0",
            source_commit="sha",
            xmuse_wheel=wheel,
            wheelhouse=wheelhouse,
            frontend_standalone=frontend,
            frontend_static=frontend,
        )
