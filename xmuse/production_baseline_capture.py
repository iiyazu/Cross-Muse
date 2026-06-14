from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.production_baseline_capture import capture_production_baseline
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-production-baseline-capture",
        description="CLI for writing the S0 production baseline evidence artifact.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to inspect.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "production-baseline.json",
        help="Path for the generated production baseline JSON artifact.",
    )
    args = parser.parse_args(argv)
    report = capture_production_baseline(
        repo_root=args.repo_root,
        output_path=args.output,
        env=dict(os.environ),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
