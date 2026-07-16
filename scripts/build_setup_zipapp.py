"""Build the stdlib-only xmuse setup bootstrap as a deterministic zipapp."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from collections.abc import Sequence
from pathlib import Path

FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _entry(name: str, content: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info, content


def build_setup_zipapp(*, output: Path, repository: Path) -> str:
    repository = repository.expanduser().resolve(strict=True)
    sources = {
        "__main__.py": (b"from xmuse.setup_cli import main\nraise SystemExit(main())\n"),
        "xmuse/__init__.py": b"",
        "xmuse/install_contracts.py": (repository / "xmuse/install_contracts.py").read_bytes(),
        "xmuse/setup_cli.py": (repository / "xmuse/setup_cli.py").read_bytes(),
    }
    destination = output.expanduser().resolve()
    if destination.suffix != ".pyz":
        raise ValueError("setup_zipapp_output_must_be_pyz")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, content in sorted(sources.items()):
                info, payload = _entry(name, content)
                archive.writestr(info, payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        digest = build_setup_zipapp(output=args.output, repository=args.repository)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason_code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "built", "sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
