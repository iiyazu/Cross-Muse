"""CLI for writing an xmuse release evidence pack."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack
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
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "evidence-pack.json",
        help="Path for the release evidence pack JSON report.",
    )
    parser.add_argument(
        "--readiness-output",
        type=Path,
        default=None,
        help="Optional path for the nested release-readiness report.",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=None,
        help="Optional path for the nested proof-contamination audit report.",
    )
    args = parser.parse_args(argv)
    pack = capture_release_evidence_pack(
        artifacts_dir=args.artifacts_dir,
        output_path=args.output,
        readiness_output=args.readiness_output,
        audit_output=args.audit_output,
    )
    print(json.dumps({"decision": pack["decision"], "output": str(args.output)}, sort_keys=True))
    return 2 if pack["decision"] == "contaminated" else 0


if __name__ == "__main__":
    raise SystemExit(main())
