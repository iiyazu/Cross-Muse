from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path("docs/xmuse/split-export-manifest.json")
SOURCE_ASSET_PATTERNS = [
    "xmuse/contracts/*.json",
]


@dataclass(frozen=True)
class XmuseExportResult:
    destination: Path
    manifest_path: Path
    copied_roots: list[str]
    excluded_count: int


def _load_manifest(repo_root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    path = manifest_path or repo_root / DEFAULT_MANIFEST
    if not path.is_absolute():
        path = repo_root / path
    return json.loads(path.read_text(encoding="utf-8"))


def _is_runtime_state(path: str, patterns: list[str]) -> bool:
    if any(fnmatch.fnmatch(path, pattern) for pattern in SOURCE_ASSET_PATTERNS):
        return False
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.endswith("/**") and path == pattern[:-3]:
            return True
        if "/**/" in pattern and fnmatch.fnmatch(path, pattern.replace("/**/", "/")):
            return True
    return False


def _prepare_destination(repo_root: Path, destination: Path, *, force: bool) -> Path:
    destination = destination.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()

    if destination == repo_root:
        raise ValueError("destination must not be the source repository root")

    if destination.exists():
        if any(destination.iterdir()):
            if not force:
                raise FileExistsError(
                    f"destination already exists and is not empty: {destination}"
                )
            shutil.rmtree(destination)
        else:
            destination.rmdir()

    destination.mkdir(parents=True)
    return destination


def _write_export_pyproject(template: Path, destination: Path, repo_root: Path) -> None:
    _ = repo_root
    text = template.read_text(encoding="utf-8").rstrip()
    (destination / "pyproject.toml").write_text(text + "\n", encoding="utf-8")


def export_xmuse_project(
    repo_root: str | Path,
    destination: str | Path,
    *,
    manifest_path: str | Path | None = None,
    force: bool = False,
) -> XmuseExportResult:
    """Export xmuse source roots into a standalone project directory."""

    repo_root = Path(repo_root).expanduser().resolve()
    manifest_arg = Path(manifest_path) if manifest_path is not None else None
    manifest = _load_manifest(repo_root, manifest_arg)
    manifest_file = manifest_arg or repo_root / DEFAULT_MANIFEST
    if not manifest_file.is_absolute():
        manifest_file = repo_root / manifest_file

    copy_roots = list(manifest["copy_roots"])
    runtime_patterns = list(manifest["runtime_state_patterns"])
    destination = _prepare_destination(repo_root, Path(destination), force=force)
    excluded_count = 0

    def ignore_runtime(src: str, names: list[str]) -> list[str]:
        nonlocal excluded_count
        ignored: list[str] = []
        src_path = Path(src)
        for name in names:
            rel = (src_path / name).resolve().relative_to(repo_root).as_posix()
            if _is_runtime_state(rel, runtime_patterns) or name in {
                "__pycache__",
                ".pytest_cache",
            }:
                ignored.append(name)
        excluded_count += len(ignored)
        return ignored

    for rel in copy_roots:
        source = repo_root / rel
        target = destination / rel
        if not source.exists():
            raise FileNotFoundError(f"manifest copy root does not exist: {rel}")
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignore_runtime)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    template_rel = manifest["package_metadata_template"]
    template = repo_root / template_rel
    if not template.exists():
        raise FileNotFoundError(f"package metadata template does not exist: {template_rel}")
    _write_export_pyproject(template, destination, repo_root)

    missing_required = [
        rel
        for rel in manifest["required_package_files"]
        if not (destination / rel).exists()
    ]
    if missing_required:
        raise FileNotFoundError(
            "export missing required package files: " + ", ".join(missing_required)
        )

    return XmuseExportResult(
        destination=destination,
        manifest_path=manifest_file,
        copied_roots=copy_roots,
        excluded_count=excluded_count,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export xmuse into a standalone tree")
    parser.add_argument(
        "destination",
        type=Path,
        help="Destination directory for the exported xmuse project",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Source MemoryOS repository root",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override split export manifest path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing non-empty destination directory",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    result = export_xmuse_project(
        args.repo_root,
        args.destination,
        manifest_path=args.manifest,
        force=args.force,
    )
    payload = asdict(result)
    payload["destination"] = str(result.destination)
    payload["manifest_path"] = str(result.manifest_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
