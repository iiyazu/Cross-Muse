"""CLI for writing feature lineage replay evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.feature_lineage_evidence_capture import (
    capture_feature_lineage_evidence,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--contract",
        action="append",
        default=[],
        type=Path,
        help="Path to a serialized FeatureOwnerExecutionContract JSON artifact.",
    )
    parser.add_argument(
        "--stage-id",
        default="S3",
        help="Goal stage id for the production evidence envelope.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "feature-lineage-production-evidence.json",
        help="Path for the xmuse.production_evidence.v1 feature lineage artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_feature_lineage_evidence(
        run_id=args.run_id,
        stage_id=args.stage_id,
        contract_artifacts=args.contract,
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
