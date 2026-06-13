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
    parser.add_argument(
        "--replay-output",
        type=Path,
        default=None,
        help="Optional path for the nested overnight replay bundle report.",
    )
    parser.add_argument(
        "--run-id",
        default="release-evidence-pack",
        help="Stable overnight run id to place in the nested replay bundle.",
    )
    parser.add_argument(
        "--section-artifact",
        action="append",
        default=[],
        metavar="SECTION=PATH",
        help=(
            "Attach an xmuse.production_evidence.v1 artifact for a required "
            "overnight replay section. May be repeated."
        ),
    )
    parser.add_argument(
        "--goal-stage-result",
        type=Path,
        action="append",
        default=[],
        help=(
            "Goal stage runner result.json to convert into the replay bundle's "
            "stage_evidence section. May be repeated."
        ),
    )
    parser.add_argument(
        "--goal-stage-evidence-output",
        type=Path,
        default=None,
        help=(
            "Optional path for the goal-stage production evidence generated "
            "from --goal-stage-result inputs."
        ),
    )
    parser.add_argument(
        "--supervisor-snapshot",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.overnight_supervisor.v1 snapshot to convert into "
            "the replay bundle's supervisor section."
        ),
    )
    parser.add_argument(
        "--supervisor-evidence-output",
        type=Path,
        default=None,
        help=(
            "Optional path for the supervisor production evidence generated "
            "from --supervisor-snapshot."
        ),
    )
    parser.add_argument(
        "--deliberation-transcript",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.operator_transcript.v1 artifact to convert into "
            "the replay bundle's deliberation_transcript section."
        ),
    )
    parser.add_argument(
        "--god-runtime",
        type=Path,
        default=None,
        help=(
            "xmuse.god_runtime_continuity.v1 artifact to validate alongside "
            "--deliberation-transcript. Omitting it keeps that replay evidence "
            "blocked/manual_gap."
        ),
    )
    parser.add_argument(
        "--deliberation-transcript-evidence-output",
        type=Path,
        default=None,
        help=(
            "Optional path for the deliberation transcript production evidence "
            "generated from --deliberation-transcript."
        ),
    )
    parser.add_argument(
        "--frozen-blueprint",
        type=Path,
        default=None,
        help=(
            "Optional mission_blueprint.v1 artifact to convert into the replay "
            "bundle's frozen_blueprint section."
        ),
    )
    parser.add_argument(
        "--frozen-blueprint-evidence-output",
        type=Path,
        default=None,
        help=(
            "Optional path for the frozen blueprint production evidence "
            "generated from --frozen-blueprint."
        ),
    )
    parser.add_argument(
        "--feature-contract",
        type=Path,
        action="append",
        default=[],
        help=(
            "Feature owner execution contract JSON to convert into the replay "
            "bundle's feature_lineage section. May be repeated."
        ),
    )
    parser.add_argument(
        "--feature-lineage-evidence-output",
        type=Path,
        default=None,
        help=(
            "Optional path for the feature lineage production evidence "
            "generated from --feature-contract inputs."
        ),
    )
    parser.add_argument(
        "--memoryos-governance-plan",
        type=Path,
        action="append",
        default=[],
        help=(
            "MemoryOS governed write plan JSON to convert into the replay "
            "bundle's memory_governance section. May be repeated."
        ),
    )
    parser.add_argument(
        "--memoryos-writeback-event",
        type=Path,
        action="append",
        default=[],
        help=(
            "MemoryOS writeback event JSON to convert into the replay "
            "bundle's memory_governance section. May be repeated."
        ),
    )
    parser.add_argument(
        "--memoryos-governance-evidence-output",
        type=Path,
        default=None,
        help=(
            "Optional path for the MemoryOS governance production evidence "
            "generated from MemoryOS plan/writeback inputs."
        ),
    )
    parser.add_argument(
        "--memoryos-live-trace",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.memoryos_lite_trace.v1 artifact to convert into "
            "artifacts-dir/live-memoryos.json before release readiness."
        ),
    )
    parser.add_argument(
        "--real-provider-runtime",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.real_provider_runtime.v1 artifact to convert into "
            "artifacts-dir/real-provider-runtime.json before release readiness."
        ),
    )
    parser.add_argument(
        "--natural-deliberation-transcript",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.operator_transcript.v1 artifact to convert into "
            "artifacts-dir/natural-deliberation.json before release readiness."
        ),
    )
    parser.add_argument(
        "--natural-deliberation-god-runtime",
        type=Path,
        default=None,
        help=(
            "Required with --natural-deliberation-transcript; validates selected "
            "GOD runtime continuity for the natural deliberation release gate."
        ),
    )
    parser.add_argument(
        "--github-server-truth",
        type=Path,
        default=None,
        help=(
            "Optional github_server_side_truth_capture.v1 snapshot to convert "
            "into artifacts-dir/github-server-truth.json before release readiness."
        ),
    )
    parser.add_argument(
        "--github-base-branch",
        default="main",
        help="Base branch name to record in the generated GitHub server truth gate.",
    )
    parser.add_argument(
        "--github-expected-head-sha",
        default=None,
        help=(
            "Expected current PR head SHA. A mismatch keeps the generated GitHub "
            "server truth gate as manual_gap."
        ),
    )
    parser.add_argument(
        "--internal-review-artifact",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.internal_review.v1 artifact to convert into "
            "artifacts-dir/internal-review.json before release readiness."
        ),
    )
    parser.add_argument(
        "--internal-review-expected-head-sha",
        default=None,
        help=(
            "Expected current head SHA that --internal-review-artifact must cover. "
            "When supplied without --internal-review-artifact, writes a blocked "
            "internal-review manual_gap gate."
        ),
    )
    parser.add_argument(
        "--production-baseline",
        type=Path,
        default=None,
        help=(
            "Optional xmuse.production_baseline.v1 S0 truth-map artifact to attach "
            "to the release evidence pack handoff."
        ),
    )
    parser.add_argument(
        "--tombstoned-source-ref",
        action="append",
        default=[],
        help="Source ref that must be excluded from active replay refs.",
    )
    args = parser.parse_args(argv)
    pack = capture_release_evidence_pack(
        artifacts_dir=args.artifacts_dir,
        output_path=args.output,
        run_id=args.run_id,
        readiness_output=args.readiness_output,
        audit_output=args.audit_output,
        replay_output=args.replay_output,
        section_artifacts=_section_artifacts(args.section_artifact),
        supervisor_snapshot=args.supervisor_snapshot,
        supervisor_evidence_output=args.supervisor_evidence_output,
        deliberation_transcript=args.deliberation_transcript,
        god_runtime_artifact=args.god_runtime,
        deliberation_transcript_evidence_output=(
            args.deliberation_transcript_evidence_output
        ),
        frozen_blueprint=args.frozen_blueprint,
        frozen_blueprint_evidence_output=args.frozen_blueprint_evidence_output,
        feature_contracts=tuple(args.feature_contract),
        feature_lineage_evidence_output=args.feature_lineage_evidence_output,
        memoryos_governance_plans=tuple(args.memoryos_governance_plan),
        memoryos_writeback_events=tuple(args.memoryos_writeback_event),
        memoryos_governance_evidence_output=args.memoryos_governance_evidence_output,
        memoryos_live_trace=args.memoryos_live_trace,
        real_provider_runtime=args.real_provider_runtime,
        natural_deliberation_transcript=args.natural_deliberation_transcript,
        natural_deliberation_god_runtime=args.natural_deliberation_god_runtime,
        github_server_truth=args.github_server_truth,
        github_base_branch=args.github_base_branch,
        github_expected_head_sha=args.github_expected_head_sha,
        internal_review_artifact=args.internal_review_artifact,
        internal_review_expected_head_sha=args.internal_review_expected_head_sha,
        production_baseline=args.production_baseline,
        goal_stage_results=tuple(args.goal_stage_result),
        goal_stage_evidence_output=args.goal_stage_evidence_output,
        tombstoned_source_refs=tuple(args.tombstoned_source_ref),
    )
    print(json.dumps({"decision": pack["decision"], "output": str(args.output)}, sort_keys=True))
    return 2 if pack["decision"] == "contaminated" else 0


def _section_artifacts(values: list[str]) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(
                "--section-artifact must use SECTION=PATH, for example "
                "supervisor=/tmp/supervisor.json"
            )
        section_id, path = value.split("=", 1)
        section_id = section_id.strip()
        path = path.strip()
        if not section_id or not path:
            raise SystemExit("--section-artifact requires non-empty SECTION and PATH")
        artifacts[section_id] = Path(path)
    return artifacts


if __name__ == "__main__":
    raise SystemExit(main())
