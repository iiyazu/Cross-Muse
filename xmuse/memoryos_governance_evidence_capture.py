"""CLI for writing MemoryOS governance replay evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.memoryos_governance_evidence_capture import (
    capture_memoryos_governance_evidence,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--plan",
        action="append",
        default=[],
        type=Path,
        help="Path to a serialized MemoryOSGovernedWritePlan JSON artifact.",
    )
    parser.add_argument(
        "--writeback-event",
        action="append",
        default=[],
        type=Path,
        help="Path to a serialized MemoryOSWritebackEvent JSON artifact.",
    )
    parser.add_argument(
        "--stage-id",
        default="S5",
        help="Goal stage id for the production evidence envelope.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "memory-governance-production-evidence.json",
        help="Path for the xmuse.production_evidence.v1 MemoryOS governance artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_memoryos_governance_evidence(
        run_id=args.run_id,
        stage_id=args.stage_id,
        plan_artifacts=args.plan,
        writeback_event_artifacts=args.writeback_event,
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
