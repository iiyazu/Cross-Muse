from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.proof_contamination_audit import (
    capture_proof_contamination_audit,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-proof-contamination-audit",
        description="CLI for auditing release gate proof contamination.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "artifacts",
        help="Directory containing release gate JSON artifacts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "proof-contamination-audit.json",
        help="Path for the proof contamination audit JSON report.",
    )
    args = parser.parse_args(argv)
    audit = capture_proof_contamination_audit(
        artifacts_dir=args.artifacts_dir,
        output_path=args.output,
    )
    print(json.dumps({"decision": audit["decision"], "output": str(args.output)}, sort_keys=True))
    return 2 if audit["decision"] == "contaminated" else 0


if __name__ == "__main__":
    raise SystemExit(main())
