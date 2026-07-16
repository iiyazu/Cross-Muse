from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

INSTALL_BUNDLE_SCHEMA = "xmuse_install_bundle/v1"
INSTALL_PLATFORM = "linux-x86_64"
INSTALL_PYTHON_ABI = f"cp{sys.version_info.major}{sys.version_info.minor}"
INSTALL_RECEIPT_SCHEMA = "xmuse_install_receipt/v1"
MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class InstallError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BundleFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class BundleManifest:
    bundle_kind: Literal["base", "memoryos"]
    version: str
    files: tuple[BundleFile, ...]
    xmuse_wheel: str | None = None
    frontend_dir: str | None = None
    dependency_site_packages: str | None = None
    memoryos_wheel: str | None = None
    memoryos_dependency_site_packages: str | None = None
    capability_manifest: str | None = None
    model_cache_dir: str | None = None


def safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise InstallError("invalid_manifest", "bundle path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InstallError("invalid_manifest", "bundle path must be a normalized relative path")
    return path.as_posix()


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise InstallError("invalid_manifest", f"{field} must be an object")
    return cast(dict[str, Any], value)


def parse_manifest(raw: bytes) -> BundleManifest:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("invalid_manifest", "manifest is not valid JSON") from exc
    data = _mapping(payload, "manifest")
    if data.get("schema_version") != INSTALL_BUNDLE_SCHEMA:
        raise InstallError("unsupported_schema", "bundle manifest schema is not supported")
    if data.get("platform") != INSTALL_PLATFORM:
        raise InstallError("unsupported_platform", "bundle platform is not supported")
    if data.get("python_abi") != INSTALL_PYTHON_ABI:
        raise InstallError(
            "unsupported_python_abi",
            f"bundle requires {INSTALL_PYTHON_ABI}",
        )
    kind = data.get("bundle_kind")
    if kind not in {"base", "memoryos"}:
        raise InstallError("invalid_manifest", "bundle_kind must be base or memoryos")
    version = data.get("version")
    if (
        not isinstance(version, str)
        or not version
        or len(version) > 128
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-"
            for char in version
        )
    ):
        raise InstallError("invalid_manifest", "version is invalid")

    raw_files = data.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise InstallError("invalid_manifest", "files must be a non-empty array")
    files: list[BundleFile] = []
    seen: set[str] = set()
    for item in raw_files:
        entry = _mapping(item, "files item")
        path = safe_relative_path(entry.get("path"))
        digest = entry.get("sha256")
        size = entry.get("size")
        if path == MANIFEST_NAME or path in seen:
            raise InstallError("invalid_manifest", "files contains a duplicate or reserved path")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise InstallError("invalid_manifest", "file sha256 is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise InstallError("invalid_manifest", "file size is invalid")
        seen.add(path)
        files.append(BundleFile(path=path, sha256=digest, size=size))

    def optional_path(section_name: str, field: str) -> str | None:
        section = _mapping(data.get(section_name), section_name)
        value = safe_relative_path(section.get(field))
        if value not in seen:
            raise InstallError("invalid_manifest", f"{section_name}.{field} is not listed in files")
        return value

    def directory_path(section_name: str, field: str) -> str:
        section = _mapping(data.get(section_name), section_name)
        value = safe_relative_path(section.get(field))
        if not any(path.startswith(f"{value}/") for path in seen):
            raise InstallError("invalid_manifest", f"{section_name}.{field} is empty")
        return value

    if kind == "base":
        base = _mapping(data.get("base"), "base")
        wheel = safe_relative_path(base.get("xmuse_wheel"))
        frontend = safe_relative_path(base.get("frontend_dir"))
        if wheel not in seen or not any(
            path == frontend or path.startswith(f"{frontend}/") for path in seen
        ):
            raise InstallError("invalid_manifest", "base payload references missing files")
        dependency_site_packages = base.get("dependency_site_packages")
        dependency_root = None
        if dependency_site_packages is not None:
            dependency_root = safe_relative_path(dependency_site_packages)
            if not any(path.startswith(f"{dependency_root}/") for path in seen):
                raise InstallError(
                    "invalid_manifest",
                    "base dependency payload is empty",
                )
        return BundleManifest(
            bundle_kind="base",
            version=version,
            files=tuple(files),
            xmuse_wheel=wheel,
            frontend_dir=frontend,
            dependency_site_packages=dependency_root,
        )

    memory = _mapping(data.get("memory"), "memory")
    dependency_site_packages = memory.get("dependency_site_packages")
    dependency_root = None
    if dependency_site_packages is not None:
        dependency_root = safe_relative_path(dependency_site_packages)
        if not any(path.startswith(f"{dependency_root}/") for path in seen):
            raise InstallError("invalid_manifest", "memory dependency payload is empty")
    return BundleManifest(
        bundle_kind="memoryos",
        version=version,
        files=tuple(files),
        memoryos_wheel=optional_path("memory", "memoryos_wheel"),
        memoryos_dependency_site_packages=dependency_root,
        capability_manifest=optional_path("memory", "capability_manifest"),
        model_cache_dir=directory_path("memory", "model_cache_dir"),
    )


def platform_is_supported() -> bool:
    return (
        os.name == "posix"
        and platform.system() == "Linux"
        and platform.machine()
        in {
            "x86_64",
            "AMD64",
        }
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
