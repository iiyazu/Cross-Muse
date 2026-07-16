from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from xmuse.install_contracts import (
    INSTALL_PLATFORM,
    INSTALL_RECEIPT_SCHEMA,
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    BundleManifest,
    InstallError,
    parse_manifest,
    platform_is_supported,
    safe_relative_path,
    sha256_file,
)

DEFAULT_PREFIX = Path("~/.local/share/xmuse")


def _prefix(value: str | None) -> Path:
    raw = value if value is not None else str(DEFAULT_PREFIX)
    return Path(raw).expanduser().resolve(strict=False)


def _json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _open_bundle(path: Path) -> tarfile.TarFile:
    name = path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        try:
            return tarfile.open(path, mode="r:gz")
        except (OSError, tarfile.TarError) as exc:
            raise InstallError("invalid_archive", "bundle archive cannot be read") from exc
    if name.endswith((".tar.zst", ".tzst")):
        raise InstallError(
            "unsupported_archive",
            "tar.zst is unavailable in this Python runtime; use the tar.gz bundle",
        )
    raise InstallError("unsupported_archive", "bundle must be a local tar.gz or tar.zst file")


def _validated_members(
    archive: tarfile.TarFile,
) -> tuple[BundleManifest, dict[str, tarfile.TarInfo]]:
    members: dict[str, tarfile.TarInfo] = {}
    directories: set[str] = set()
    for member in archive.getmembers():
        name = safe_relative_path(member.name.rstrip("/"))
        if name in members or name in directories:
            raise InstallError("invalid_archive", "bundle contains duplicate paths")
        if member.isdir():
            directories.add(name)
            continue
        if not member.isfile() or member.issym() or member.islnk():
            raise InstallError("unsafe_archive", "bundle contains a non-regular file")
        members[name] = member
    manifest_member = members.get(MANIFEST_NAME)
    if manifest_member is None or manifest_member.size > MAX_MANIFEST_BYTES:
        raise InstallError("invalid_manifest", "bundle manifest is missing or too large")
    source = archive.extractfile(manifest_member)
    if source is None:
        raise InstallError("invalid_manifest", "bundle manifest cannot be read")
    manifest = parse_manifest(source.read())
    expected = {item.path for item in manifest.files} | {MANIFEST_NAME}
    if set(members) != expected:
        raise InstallError("invalid_archive", "archive files do not exactly match manifest")
    for item in manifest.files:
        if members[item.path].size != item.size:
            raise InstallError("digest_mismatch", "bundle file size does not match manifest")
    return manifest, members


def _extract_verified(bundle: Path, destination: Path) -> BundleManifest:
    if not bundle.is_file():
        raise InstallError("bundle_not_found", "bundle file does not exist")
    with _open_bundle(bundle) as archive:
        manifest, members = _validated_members(archive)
        destination.mkdir(mode=0o700, parents=True)
        for item in manifest.files:
            target = destination.joinpath(*item.path.split("/"))
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = archive.extractfile(members[item.path])
            if source is None:
                raise InstallError("invalid_archive", "bundle file cannot be read")
            with target.open("xb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, 0o600)
            if sha256_file(target) != item.sha256:
                raise InstallError("digest_mismatch", "bundle file digest does not match manifest")
        (destination / MANIFEST_NAME).write_bytes(
            archive.extractfile(members[MANIFEST_NAME]).read()  # type: ignore[union-attr]
        )
    return manifest


def _create_venv(
    root: Path,
    wheel: str,
    wheelhouse: Path,
    dependency_site_packages: Path | None = None,
) -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(root / ".venv")],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        python = root / ".venv" / "bin" / "python"
        if dependency_site_packages is not None:
            python_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
            target = root / ".venv" / "lib" / python_dir / "site-packages"
            shutil.copytree(dependency_site_packages, target, dirs_exist_ok=True)
        command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--disable-pip-version-check",
            "--find-links",
            str(wheelhouse),
        ]
        if dependency_site_packages is not None:
            command.append("--no-deps")
        command.append(str(root / wheel))
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        shutil.rmtree(root / ".venv", ignore_errors=True)
        raise InstallError("offline_install_failed", "offline wheel installation failed") from exc


def _relocate_venv(staging: Path, destination: Path) -> None:
    """Rewrite generated console-script prefixes before the staged tree is promoted."""

    source_prefix = str(staging).encode()
    destination_prefix = str(destination).encode()
    bin_dir = staging / ".venv" / "bin"
    try:
        for path in bin_dir.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_size > 1024 * 1024:
                raise InstallError(
                    "offline_install_failed",
                    "generated environment entrypoint is unexpectedly large",
                )
            content = path.read_bytes()
            if source_prefix in content:
                path.write_bytes(content.replace(source_prefix, destination_prefix))
    except OSError as exc:
        raise InstallError(
            "offline_install_failed",
            "generated environment entrypoints cannot be finalized",
        ) from exc


def _write_receipt(root: Path, manifest: BundleManifest) -> None:
    receipt = {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "bundle_kind": manifest.bundle_kind,
        "version": manifest.version,
        "platform": INSTALL_PLATFORM,
    }
    temporary = root / f".install-receipt-{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, root / "install-receipt.json")


def _activate(prefix: Path, version: str) -> None:
    versions = _versions_dir(prefix, create=False)
    version_dir = versions / version
    if not version_dir.is_dir():
        raise InstallError("version_not_found", "installed version does not exist")
    prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = prefix / f".active-{uuid.uuid4().hex}"
    os.symlink(Path("versions") / version, temporary)
    os.replace(temporary, prefix / "active")


def install_base(bundle: Path, prefix: Path) -> dict[str, Any]:
    if not platform_is_supported():
        raise InstallError("unsupported_platform", "installation requires Linux x86_64")
    versions = _versions_dir(prefix, create=True)
    staging = versions / f".install-{uuid.uuid4().hex}"
    try:
        manifest = _extract_verified(bundle, staging)
        if manifest.bundle_kind != "base" or manifest.xmuse_wheel is None:
            raise InstallError("wrong_bundle_kind", "install requires a base bundle")
        destination = versions / manifest.version
        if destination.exists():
            raise InstallError("version_exists", "installed version already exists")
        wheelhouse = staging / Path(manifest.xmuse_wheel).parent
        dependency_site_packages = (
            staging / manifest.dependency_site_packages
            if manifest.dependency_site_packages is not None
            else None
        )
        _create_venv(
            staging,
            manifest.xmuse_wheel,
            wheelhouse,
            dependency_site_packages,
        )
        if manifest.frontend_dir is None:
            raise InstallError("invalid_manifest", "base frontend directory is missing")
        installed_frontend = staging / "share" / "xmuse" / "frontend"
        bundled_frontend = staging / manifest.frontend_dir
        if bundled_frontend != installed_frontend:
            shutil.copytree(bundled_frontend, installed_frontend)
        _write_receipt(staging, manifest)
        _relocate_venv(staging, destination)
        os.replace(staging, destination)
        try:
            _activate(prefix, manifest.version)
        except (InstallError, OSError):
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return {"status": "installed", "version": manifest.version, "active": True}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _active_version(prefix: Path) -> tuple[str, Path]:
    active = prefix / "active"
    if not active.is_symlink():
        raise InstallError("active_version_missing", "no active xmuse version is installed")
    target = os.readlink(active)
    expected_parent = Path("versions")
    relative = Path(target)
    if relative.parent != expected_parent or not relative.name:
        raise InstallError("invalid_installation", "active installation receipt is invalid")
    try:
        resolved = active.resolve(strict=True)
        versions = _versions_dir(prefix, create=False).resolve(strict=True)
    except OSError as exc:
        raise InstallError(
            "invalid_installation", "active installation cannot be resolved"
        ) from exc
    if resolved.parent != versions:
        raise InstallError("invalid_installation", "active installation escapes the prefix")
    return relative.name, resolved


def install_memory(bundle: Path, prefix: Path) -> dict[str, Any]:
    if not platform_is_supported():
        raise InstallError("unsupported_platform", "installation requires Linux x86_64")
    active_version, active_dir = _active_version(prefix)
    staging = active_dir / f".memoryos-{uuid.uuid4().hex}"
    destination = active_dir / "memoryos"
    try:
        manifest = _extract_verified(bundle, staging)
        if manifest.bundle_kind != "memoryos" or manifest.memoryos_wheel is None:
            raise InstallError("wrong_bundle_kind", "install-memory requires a memoryos bundle")
        if destination.exists():
            raise InstallError("memoryos_exists", "MemoryOS is already installed")
        wheelhouse = staging / Path(manifest.memoryos_wheel).parent
        dependency_site_packages = (
            staging / manifest.memoryos_dependency_site_packages
            if manifest.memoryos_dependency_site_packages is not None
            else None
        )
        _create_venv(
            staging,
            manifest.memoryos_wheel,
            wheelhouse,
            dependency_site_packages,
        )
        _validate_memory_capability(staging, manifest, run_probe=False)
        _write_receipt(staging, manifest)
        _relocate_venv(staging, destination)
        os.replace(staging, destination)
        return {
            "status": "installed",
            "version": active_version,
            "memoryos_version": manifest.version,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _load_manifest(root: Path) -> BundleManifest:
    try:
        return parse_manifest((root / MANIFEST_NAME).read_bytes())
    except OSError as exc:
        raise InstallError("invalid_installation", "installed manifest cannot be read") from exc


def _versions_dir(prefix: Path, *, create: bool) -> Path:
    versions = prefix / "versions"
    if create:
        prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
        versions.mkdir(mode=0o700, exist_ok=True)
    if versions.is_symlink() or not versions.is_dir():
        raise InstallError("invalid_installation", "versions directory is invalid")
    return versions


def _verify_receipt(root: Path, manifest: BundleManifest) -> None:
    try:
        receipt = json.loads((root / "install-receipt.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("invalid_installation", "installation receipt is invalid") from exc
    expected = {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "bundle_kind": manifest.bundle_kind,
        "version": manifest.version,
        "platform": INSTALL_PLATFORM,
    }
    if receipt != expected:
        raise InstallError("invalid_installation", "installation receipt is inconsistent")


def _verify_payload(root: Path, manifest: BundleManifest) -> None:
    resolved_root = root.resolve(strict=True)
    for item in manifest.files:
        path = root.joinpath(*item.path.split("/"))
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise InstallError("invalid_installation", "installed payload is incomplete") from exc
        if (
            not resolved.is_relative_to(resolved_root)
            or resolved != path.absolute()
            or not path.is_file()
            or path.is_symlink()
        ):
            raise InstallError("invalid_installation", "installed payload is incomplete")
        if path.stat().st_size != item.size or sha256_file(path) != item.sha256:
            raise InstallError("invalid_installation", "installed payload failed integrity check")


def _validate_memory_capability(
    root: Path,
    manifest: BundleManifest,
    *,
    run_probe: bool,
) -> None:
    if manifest.capability_manifest is None or manifest.model_cache_dir is None:
        raise InstallError("invalid_installation", "MemoryOS capability proof is incomplete")
    capability_path = root / manifest.capability_manifest
    model_cache = root / manifest.model_cache_dir
    try:
        capability = json.loads(capability_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(
            "invalid_installation",
            "MemoryOS capability manifest is invalid",
        ) from exc
    expected_hybrid = {"bm25": True, "fastembed": True, "rrf": True}
    if (
        not isinstance(capability, dict)
        or capability.get("schema_version") != "xmuse_memoryos_bundle_capability/v1"
        or capability.get("profile") != "full-local"
        or capability.get("fastembed_model") != "BAAI/bge-small-en-v1.5"
        or capability.get("hybrid") != expected_hybrid
        or not model_cache.is_dir()
        or model_cache.is_symlink()
    ):
        raise InstallError("invalid_installation", "MemoryOS full-local capability is invalid")
    for path in model_cache.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise InstallError("invalid_installation", "MemoryOS model cache is unsafe")
    if not run_probe:
        return
    python = root / ".venv" / "bin" / "python"
    proof = (
        "from fastembed import TextEmbedding\n"
        "import sys\n"
        "model=TextEmbedding(model_name='BAAI/bge-small-en-v1.5',cache_dir=sys.argv[1])\n"
        "assert len(next(model.embed(['xmuse install proof']))) == 384\n"
    )
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(root)),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "MEMORYOS_FASTEMBED_OFFLINE": "1",
        "FASTEMBED_CACHE_PATH": str(model_cache),
    }
    try:
        result = subprocess.run(
            [str(python), "-c", proof, str(model_cache)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallError("memoryos_capability_unavailable", "MemoryOS proof failed") from exc
    if result.returncode != 0:
        raise InstallError("memoryos_capability_unavailable", "MemoryOS proof failed")


def verify(prefix: Path) -> dict[str, Any]:
    version, root = _active_version(prefix)
    manifest = _load_manifest(root)
    if manifest.bundle_kind != "base" or manifest.version != version:
        raise InstallError("invalid_installation", "active base manifest is inconsistent")
    _verify_receipt(root, manifest)
    _verify_payload(root, manifest)
    commands = {
        name: shutil.which(name) is not None for name in ("uv", "node", "git", "bwrap", "codex")
    }
    memory_status = "not_installed"
    memory_root = root / "memoryos"
    if memory_root.exists():
        memory_manifest = _load_manifest(memory_root)
        if memory_manifest.bundle_kind != "memoryos":
            raise InstallError("invalid_installation", "MemoryOS manifest is inconsistent")
        _verify_receipt(memory_root, memory_manifest)
        _verify_payload(memory_root, memory_manifest)
        _validate_memory_capability(memory_root, memory_manifest, run_probe=True)
        memory_status = "ready"
    return {
        "status": "ok" if all(commands.values()) else "attention",
        "version": version,
        "platform": INSTALL_PLATFORM,
        "prerequisites": commands,
        "memoryos": memory_status,
    }


def uninstall(prefix: Path, version: str) -> dict[str, Any]:
    try:
        active_version, _ = _active_version(prefix)
    except InstallError as exc:
        if exc.code != "active_version_missing":
            raise
        active_version = None
    if version == active_version:
        raise InstallError("active_version", "cannot uninstall the active version")
    destination = prefix / "versions" / version
    if not destination.is_dir() or destination.is_symlink():
        raise InstallError("version_not_found", "installed version does not exist")
    shutil.rmtree(destination)
    return {"status": "uninstalled", "version": version}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xmuse-setup")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("install", "install-memory"):
        child = subparsers.add_parser(command)
        child.add_argument("--bundle", required=True)
        child.add_argument("--prefix")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--prefix")
    for command in ("activate", "uninstall"):
        child = subparsers.add_parser(command)
        child.add_argument("version")
        child.add_argument("--prefix")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    prefix = _prefix(args.prefix)
    try:
        if args.command == "install":
            result = install_base(Path(args.bundle).expanduser(), prefix)
        elif args.command == "install-memory":
            result = install_memory(Path(args.bundle).expanduser(), prefix)
        elif args.command == "verify":
            result = verify(prefix)
        elif args.command == "activate":
            _activate(prefix, args.version)
            result = {"status": "activated", "version": args.version}
        else:
            result = uninstall(prefix, args.version)
    except InstallError as exc:
        _json({"status": "error", "reason_code": exc.code, "message": str(exc)})
        return 1
    except OSError:
        _json(
            {
                "status": "error",
                "reason_code": "filesystem_error",
                "message": "installation filesystem operation failed",
            }
        )
        return 1
    _json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
