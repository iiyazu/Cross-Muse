#!/usr/bin/env python3
"""Build deterministic, locally installable xmuse release bundles."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from xmuse.install_contracts import MAX_MANIFEST_BYTES

BUNDLE_SCHEMA = "xmuse_install_bundle/v1"
SUPPORTED_PLATFORM = "linux-x86_64"
PYTHON_ABI = f"cp{sys.version_info.major}{sys.version_info.minor}"


class BundleBuildError(RuntimeError):
    """Stable build failure for unsafe or incomplete bundle inputs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BundleInput:
    source: Path
    archive_path: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_path(value: str) -> str:
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise BundleBuildError("bundle_path_invalid")
    return value


def _tree_inputs(source: Path, archive_root: str) -> list[BundleInput]:
    root = source.expanduser().resolve()
    if not root.is_dir():
        raise BundleBuildError("bundle_input_directory_missing")
    entries: list[BundleInput] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise BundleBuildError("bundle_input_symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise BundleBuildError("bundle_input_file_invalid")
        relative = path.relative_to(root).as_posix()
        entries.append(BundleInput(path, _safe_archive_path(f"{archive_root}/{relative}")))
    return entries


def _file_input(source: Path, archive_path: str) -> BundleInput:
    path = source.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise BundleBuildError("bundle_input_file_missing")
    return BundleInput(path, _safe_archive_path(archive_path))


def _wheel_inputs(wheel: Path, wheelhouse: Path, archive_root: str) -> list[BundleInput]:
    entries = _tree_inputs(wheelhouse, archive_root)
    selected = _file_input(wheel, f"{archive_root}/{wheel.name}")
    by_path = {entry.archive_path: entry for entry in entries}
    by_path[selected.archive_path] = selected
    if any(not name.endswith(".whl") for name in by_path):
        raise BundleBuildError("bundle_wheelhouse_file_invalid")
    return [by_path[name] for name in sorted(by_path)]


def _manifest_files(entries: Iterable[BundleInput]) -> list[dict[str, Any]]:
    return [
        {
            "path": entry.archive_path,
            "sha256": _sha256(entry.source),
            "size": entry.source.stat().st_size,
        }
        for entry in entries
    ]


def _write_deterministic_archive(
    output: Path,
    manifest: dict[str, Any],
    entries: Sequence[BundleInput],
) -> None:
    destination = output.expanduser().resolve()
    if not destination.name.endswith(".tar.gz"):
        raise BundleBuildError("bundle_output_format_unsupported")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(entries, key=lambda item: item.archive_path)
    names = [entry.archive_path for entry in ordered]
    if len(names) != len(set(names)):
        raise BundleBuildError("bundle_archive_path_duplicate")
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise BundleBuildError("bundle_manifest_too_large")
    temporary_output = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent) as raw_tar:
            with tarfile.open(fileobj=raw_tar, mode="w") as archive:
                manifest_info = tarfile.TarInfo("manifest.json")
                manifest_info.size = len(manifest_bytes)
                manifest_info.mode = 0o644
                manifest_info.mtime = 0
                manifest_info.uid = manifest_info.gid = 0
                manifest_info.uname = manifest_info.gname = ""
                archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
                for entry in ordered:
                    info = tarfile.TarInfo(entry.archive_path)
                    info.size = entry.source.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with entry.source.open("rb") as handle:
                        archive.addfile(info, handle)
            raw_tar.flush()
            raw_tar.seek(0)
            with temporary_output.open("wb") as output_handle:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=output_handle,
                    mtime=0,
                ) as zipped:
                    while chunk := raw_tar.read(1024 * 1024):
                        zipped.write(chunk)
        os.replace(temporary_output, destination)
    finally:
        temporary_output.unlink(missing_ok=True)


def build_base_bundle(
    *,
    output: Path,
    version: str,
    source_commit: str,
    xmuse_wheel: Path,
    wheelhouse: Path,
    frontend_standalone: Path,
    frontend_static: Path,
    frontend_public: Path | None = None,
    dependency_site_packages: Path | None = None,
) -> dict[str, Any]:
    wheel_entries = _wheel_inputs(xmuse_wheel, wheelhouse, "payload/python/wheelhouse")
    frontend_entries = _tree_inputs(
        frontend_standalone,
        "share/xmuse/frontend/.next/standalone",
    )
    if not any(entry.archive_path.endswith("/server.js") for entry in frontend_entries):
        raise BundleBuildError("bundle_frontend_server_missing")
    static_entries = _tree_inputs(frontend_static, "share/xmuse/frontend/.next/static")
    public_entries = (
        _tree_inputs(frontend_public, "share/xmuse/frontend/public")
        if frontend_public is not None and frontend_public.exists()
        else []
    )
    dependency_entries = (
        _tree_inputs(dependency_site_packages, "payload/python/site-packages")
        if dependency_site_packages is not None
        else []
    )
    entries = [
        *wheel_entries,
        *dependency_entries,
        *frontend_entries,
        *static_entries,
        *public_entries,
    ]
    manifest = {
        "schema_version": BUNDLE_SCHEMA,
        "bundle_kind": "base",
        "version": version,
        "platform": SUPPORTED_PLATFORM,
        "python_abi": PYTHON_ABI,
        "source_commit": source_commit,
        "files": _manifest_files(entries),
        "base": {
            "xmuse_wheel": f"payload/python/wheelhouse/{xmuse_wheel.name}",
            "frontend_dir": "share/xmuse/frontend",
            **(
                {"dependency_site_packages": "payload/python/site-packages"}
                if dependency_entries
                else {}
            ),
        },
    }
    _write_deterministic_archive(output, manifest, entries)
    return manifest


def build_memory_bundle(
    *,
    output: Path,
    version: str,
    source_commit: str,
    memoryos_wheel: Path,
    wheelhouse: Path,
    model_cache: Path,
    capability_manifest: Path,
    dependency_site_packages: Path | None = None,
) -> dict[str, Any]:
    wheel_entries = _wheel_inputs(memoryos_wheel, wheelhouse, "payload/memoryos/wheelhouse")
    model_entries = _tree_inputs(model_cache, "payload/memoryos/model-cache")
    capability_entry = _file_input(
        capability_manifest,
        "payload/memoryos/capability.json",
    )
    try:
        capability = json.loads(capability_entry.source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleBuildError("bundle_memoryos_capability_invalid") from exc
    if (
        not isinstance(capability, dict)
        or capability.get("schema_version") != "xmuse_memoryos_bundle_capability/v1"
        or capability.get("profile") != "full-local"
        or capability.get("fastembed_model") != "BAAI/bge-small-en-v1.5"
        or capability.get("hybrid") != {"bm25": True, "fastembed": True, "rrf": True}
    ):
        raise BundleBuildError("bundle_memoryos_capability_invalid")
    dependency_entries = (
        _tree_inputs(dependency_site_packages, "payload/memoryos/site-packages")
        if dependency_site_packages is not None
        else []
    )
    entries = [*wheel_entries, *dependency_entries, *model_entries, capability_entry]
    manifest = {
        "schema_version": BUNDLE_SCHEMA,
        "bundle_kind": "memoryos",
        "version": version,
        "platform": SUPPORTED_PLATFORM,
        "python_abi": PYTHON_ABI,
        "source_commit": source_commit,
        "files": _manifest_files(entries),
        "memory": {
            "memoryos_wheel": f"payload/memoryos/wheelhouse/{memoryos_wheel.name}",
            **(
                {"dependency_site_packages": "payload/memoryos/site-packages"}
                if dependency_entries
                else {}
            ),
            "capability_manifest": capability_entry.archive_path,
            "model_cache_dir": "payload/memoryos/model-cache",
        },
    }
    _write_deterministic_archive(output, manifest, entries)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="kind", required=True)
    for kind in ("base", "memoryos"):
        command = subparsers.add_parser(kind)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--version", required=True)
        command.add_argument("--source-commit", required=True)
        command.add_argument("--wheel", type=Path, required=True)
        command.add_argument("--wheelhouse", type=Path, required=True)
        if kind == "base":
            command.add_argument("--frontend-standalone", type=Path, required=True)
            command.add_argument("--frontend-static", type=Path, required=True)
            command.add_argument("--frontend-public", type=Path)
            command.add_argument("--dependency-site-packages", type=Path)
        else:
            command.add_argument("--model-cache", type=Path, required=True)
            command.add_argument("--capability-manifest", type=Path, required=True)
            command.add_argument("--dependency-site-packages", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.kind == "base":
            manifest = build_base_bundle(
                output=args.output,
                version=args.version,
                source_commit=args.source_commit,
                xmuse_wheel=args.wheel,
                wheelhouse=args.wheelhouse,
                frontend_standalone=args.frontend_standalone,
                frontend_static=args.frontend_static,
                frontend_public=args.frontend_public,
                dependency_site_packages=args.dependency_site_packages,
            )
        else:
            manifest = build_memory_bundle(
                output=args.output,
                version=args.version,
                source_commit=args.source_commit,
                memoryos_wheel=args.wheel,
                wheelhouse=args.wheelhouse,
                model_cache=args.model_cache,
                capability_manifest=args.capability_manifest,
                dependency_site_packages=args.dependency_site_packages,
            )
    except BundleBuildError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "built",
                "schema_version": manifest["schema_version"],
                "bundle_kind": manifest["bundle_kind"],
                "version": manifest["version"],
                "sha256": _sha256(args.output.expanduser().resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
