from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.natural_deliberation_release_gate import (
    capture_natural_deliberation_release_gate,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-natural-deliberation-gate-capture",
        description="CLI for writing a natural GOD deliberation release gate artifact.",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="Path to an xmuse.operator_transcript.v1 JSON artifact.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "artifacts"
        / "natural-deliberation.json",
        help="Path for the release gate JSON artifact.",
    )
    parser.add_argument(
        "--god-runtime",
        type=Path,
        default=None,
        help=(
            "xmuse.god_runtime_continuity.v1 JSON artifact. Omitting it keeps "
            "the production gate blocked/manual_gap."
        ),
    )
    args = parser.parse_args(argv)
    gate = capture_natural_deliberation_release_gate(
        artifact_path=args.artifact,
        output_path=args.output,
        god_runtime_path=args.god_runtime,
    )
    print(json.dumps({"status": gate["status"], "output": str(args.output)}, sort_keys=True))
    return 0 if gate["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
