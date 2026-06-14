"""CLI for writing deliberation transcript replay evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.deliberation_transcript_evidence_capture import (
    capture_deliberation_transcript_evidence,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--transcript",
        type=Path,
        required=True,
        help="Path to an xmuse.operator_transcript.v1 JSON artifact.",
    )
    parser.add_argument(
        "--god-runtime",
        type=Path,
        default=None,
        help=(
            "xmuse.god_runtime_continuity.v1 JSON artifact. Omitting it keeps "
            "the production evidence blocked/manual_gap."
        ),
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
        / "deliberation-transcript-production-evidence.json",
        help="Path for the xmuse.production_evidence.v1 deliberation transcript artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_deliberation_transcript_evidence(
        run_id=args.run_id,
        stage_id=args.stage_id,
        transcript_artifact=args.transcript,
        god_runtime_artifact=args.god_runtime,
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
