from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.closure_reconciler import capture_closure_object
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
    parser.add_argument(
        "--closure-object-output",
        type=Path,
        default=None,
        help=(
            "Optional output path for a ClosureObject reconciled from the "
            "review-chain proof, review closure, candidate, and recovery refs."
        ),
    )
    parser.add_argument(
        "--previous-closure-object",
        type=Path,
        default=None,
        help="Optional previous ClosureObject artifact used for freshness checks.",
    )
    parser.add_argument("--closure-generation", type=int, default=1)
    args = parser.parse_args(argv)
    proof = capture_god_room_review_chain_proof(
        root=args.xmuse_root,
        review_closure_artifact=args.god_room_review_closure,
        output_path=args.output,
    )
    closure_output = None
    closure_phase = None
    if args.closure_object_output is not None:
        closure = capture_closure_object(
            root=args.xmuse_root,
            graph_id=str(proof.get("graph_id") or ""),
            lane_id=str(proof.get("terminal_lane_id") or proof.get("lane_id") or ""),
            generation=args.closure_generation,
            previous_closure=args.previous_closure_object,
            recovery_artifact=_recovery_artifact_ref(proof),
            execution_candidates=_candidate_artifact_refs(proof),
            review_closure=args.god_room_review_closure,
            release_handoff=args.output,
            output_path=args.closure_object_output,
        )
        closure_output = str(args.closure_object_output)
        closure_phase = closure.status.phase
    print(
        json.dumps(
            {
                "schema_version": proof["schema_version"],
                "output": str(args.output),
                "closure_object_output": closure_output,
                "closure_object_phase": closure_phase,
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


def _candidate_artifact_refs(proof: dict[str, object]) -> list[str]:
    lineage = proof.get("candidate_lineage")
    if not isinstance(lineage, dict):
        return []
    refs = lineage.get("candidate_artifact_refs")
    if not isinstance(refs, list):
        return []
    return [ref for ref in refs if isinstance(ref, str) and ref.strip()]


def _recovery_artifact_ref(proof: dict[str, object]) -> str | None:
    lineage = proof.get("runner_recovery_proof_lineage")
    if not isinstance(lineage, dict):
        return None
    ref = lineage.get("artifact_ref")
    if not isinstance(ref, str):
        return None
    return ref.strip() or None


if __name__ == "__main__":
    raise SystemExit(main())
