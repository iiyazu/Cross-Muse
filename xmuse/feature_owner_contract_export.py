"""CLI for exporting feature-owner execution contracts from graph-set authority."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.structuring.feature_owner_contract_export import (
    export_feature_owner_contracts_from_graph_set,
)

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph-set",
        required=True,
        type=Path,
        help="Path to an authoritative graph-set JSON artifact.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "feature-contracts",
        help="Directory for exported FeatureOwnerExecutionContract JSON artifacts.",
    )
    parser.add_argument(
        "--feature-id",
        action="append",
        default=[],
        help="Feature id to export. May be repeated. Defaults to all graph-set features.",
    )
    parser.add_argument(
        "--allowed-file",
        action="append",
        default=[],
        help=(
            "Allowed file fallback when graph-set lanes do not include "
            "expected_touched_areas. May be repeated."
        ),
    )
    parser.add_argument(
        "--memory-ref",
        action="append",
        default=[],
        help="Memory ref to attach to every exported contract. May be repeated.",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        default=[],
        help="Required check command for exported contracts. May be repeated.",
    )
    parser.add_argument("--review-profile", default="internal-adversarial")
    parser.add_argument(
        "--patch-forward-policy",
        default="review_failures_spawn_patch_forward_lane",
    )
    parser.add_argument(
        "--rollback-constraint",
        action="append",
        default=["do not mutate feature_lanes.json"],
        help="Rollback constraint for exported contracts. May be repeated.",
    )
    args = parser.parse_args(argv)

    paths = export_feature_owner_contracts_from_graph_set(
        graph_set_artifact=args.graph_set,
        output_dir=args.output_dir,
        feature_ids=args.feature_id,
        allowed_files=args.allowed_file,
        memory_refs=args.memory_ref,
        required_checks=args.required_check,
        review_profile=args.review_profile,
        patch_forward_policy=args.patch_forward_policy,
        rollback_constraints=args.rollback_constraint,
    )
    print(
        json.dumps(
            {
                "contract_count": len(paths),
                "outputs": [str(path) for path in paths],
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
