"""CLI for writing overnight supervisor replay evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.overnight_supervisor_evidence_capture import (
    capture_overnight_supervisor_evidence,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Path to an xmuse.overnight_supervisor.v1 snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "supervisor-production-evidence.json",
        help="Path for the xmuse.production_evidence.v1 supervisor artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_overnight_supervisor_evidence(
        snapshot_path=args.snapshot,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "proof_level": artifact["proof_level"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if artifact["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
