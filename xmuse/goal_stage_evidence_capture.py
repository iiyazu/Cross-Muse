"""CLI for converting goal-stage runner results into replay evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.goal_stage_evidence_capture import (
    capture_goal_stage_evidence,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        required=True,
        help="Stable overnight run id that produced the goal-stage results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "goal-stage-production-evidence.json",
        help="Path for the generated xmuse.production_evidence.v1 artifact.",
    )
    parser.add_argument(
        "--stage-result",
        type=Path,
        action="append",
        default=[],
        help="Goal stage runner result.json to index. May be repeated.",
    )
    args = parser.parse_args(argv)
    evidence = capture_goal_stage_evidence(
        run_id=args.run_id,
        output_path=args.output,
        stage_results=tuple(args.stage_result),
    )
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "proof_level": evidence["proof_level"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
