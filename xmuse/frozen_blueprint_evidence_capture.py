"""CLI for writing frozen blueprint replay evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.frozen_blueprint_evidence_capture import (
    capture_frozen_blueprint_evidence,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--blueprint",
        type=Path,
        required=True,
        help="Path to a mission_blueprint.v1 JSON artifact.",
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
        / "frozen-blueprint-production-evidence.json",
        help="Path for the xmuse.production_evidence.v1 frozen blueprint artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_frozen_blueprint_evidence(
        run_id=args.run_id,
        stage_id=args.stage_id,
        blueprint_artifact=args.blueprint,
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
