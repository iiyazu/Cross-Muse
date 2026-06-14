"""CLI for writing a redacted xmuse release-readiness report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.release_readiness_capture import capture_release_readiness
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "artifacts",
        help="Directory containing release gate JSON artifacts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "report.json",
        help="Path for the redacted release-readiness report.",
    )
    args = parser.parse_args(argv)
    report = capture_release_readiness(
        artifacts_dir=args.artifacts_dir,
        output_path=args.output,
    )
    print(json.dumps({"decision": report["decision"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
