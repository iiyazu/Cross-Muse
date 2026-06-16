from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.god_room_review_chain_proof import (
    capture_god_room_review_chain_proof,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-god-room-review-chain-proof-capture",
        description=(
            "Write xmuse.god_room_lane_review_chain_proof.v1 without "
            "upgrading local review evidence into server truth."
        ),
    )
    parser.add_argument("--xmuse-root", type=Path, default=DEFAULT_XMUSE_ROOT)
    parser.add_argument(
        "--god-room-review-closure",
        type=Path,
        required=True,
        help="Path to xmuse.god_room_lane_review_closure.v1.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "god-room-review-chain-proof.json",
    )
    args = parser.parse_args(argv)
    proof = capture_god_room_review_chain_proof(
        root=args.xmuse_root,
        review_closure_artifact=args.god_room_review_closure,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "schema_version": proof["schema_version"],
                "output": str(args.output),
                "status": proof["status"],
                "proof_level": proof["proof_level"],
                "review_closure_artifact_gate_ready": proof[
                    "release_evidence_handoff"
                ]["review_closure_artifact_gate_ready"],
                "forbidden_claims": proof["forbidden_claims"],
            },
            sort_keys=True,
        )
    )
    return 0 if proof["status"] != "manual_gap" else 2


if __name__ == "__main__":
    raise SystemExit(main())
