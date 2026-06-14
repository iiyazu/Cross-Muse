from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.memoryos_live_release_gate import (
    capture_memoryos_live_release_gate,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-memoryos-live-gate-capture",
        description="CLI for writing a MemoryOS Lite live release gate artifact.",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="Path to an xmuse.memoryos_lite_trace.v1 JSON artifact.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "artifacts"
        / "live-memoryos.json",
        help="Path for the release gate JSON artifact.",
    )
    args = parser.parse_args(argv)
    gate = capture_memoryos_live_release_gate(
        artifact_path=args.artifact,
        output_path=args.output,
    )
    print(json.dumps({"status": gate["status"], "output": str(args.output)}, sort_keys=True))
    return 0 if gate["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
