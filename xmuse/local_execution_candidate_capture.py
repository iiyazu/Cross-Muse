"""CLI for writing local execution candidate evidence artifacts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.local_execution_candidate import (
    capture_local_execution_candidate,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--conversation-id")
    parser.add_argument("--lane-local-id")
    parser.add_argument("--graph-id")
    parser.add_argument("--graph-set-id")
    parser.add_argument("--feature-graph-id")
    parser.add_argument("--feature-graph-status-id")
    parser.add_argument("--feature-graph-status")
    parser.add_argument("--run-id")
    parser.add_argument("--worker-id")
    parser.add_argument("--command")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--output-ref", action="append", default=[])
    parser.add_argument("--changed-file-ref", action="append", default=[])
    parser.add_argument("--verification-ref", action="append", default=[])
    parser.add_argument("--manual-gap", action="append", default=[])
    parser.add_argument(
        "--proof-level",
        choices=("local_runtime_proof", "manual_gap"),
        default="local_runtime_proof",
    )
    parser.add_argument(
        "--status",
        choices=("candidate_only", "manual_gap"),
        default="candidate_only",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "reports" / "local-execution-candidate.json",
        help="Path for the generated xmuse.local_execution_candidate.v1 artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_local_execution_candidate(
        output_path=args.output,
        lane_id=args.lane_id,
        candidate_id=args.candidate_id,
        conversation_id=args.conversation_id,
        lane_local_id=args.lane_local_id,
        graph_id=args.graph_id,
        graph_set_id=args.graph_set_id,
        feature_graph_id=args.feature_graph_id,
        feature_graph_status_id=args.feature_graph_status_id,
        feature_graph_status=args.feature_graph_status,
        run_id=args.run_id,
        worker_id=args.worker_id,
        command=args.command,
        exit_code=args.exit_code,
        source_refs=args.source_ref,
        output_refs=args.output_ref,
        changed_file_refs=args.changed_file_ref,
        verification_refs=args.verification_ref,
        proof_level=args.proof_level,
        status=args.status,
        manual_gaps=args.manual_gap,
    )
    print(
        json.dumps(
            {
                "schema_version": artifact["schema_version"],
                "status": artifact["status"],
                "proof_level": artifact["proof_level"],
                "producer": artifact["producer"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if artifact["status"] == "candidate_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
