"""CLI for driving the xmuse overnight operator supervisor snapshot."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.overnight_operator_supervisor import (
    OvernightSimulationConfig,
    OvernightSimulationFailure,
    OvernightSupervisor,
    OvernightSupervisorConfig,
    OvernightSupervisorStage,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    supervisor = _load_supervisor(args)

    if args.command == "start-stage":
        supervisor.start_stage(args.stage_id)
        result = {"status": "ok", "stage_id": args.stage_id}
    elif args.command == "heartbeat":
        heartbeat = supervisor.record_heartbeat(note=args.note)
        result = {"status": "ok", "heartbeat": heartbeat}
    elif args.command == "checkpoint":
        checkpoint = supervisor.record_checkpoint(
            stage_id=args.stage_id,
            summary=args.summary,
            validation=args.test_result,
            commands=args.command_ref,
            source_refs=args.source_ref,
            target_refs=args.target_ref,
            artifacts=args.artifact,
            owner=args.owner,
            next_action=args.next_action,
        )
        result = {"status": "ok", "checkpoint": checkpoint}
    elif args.command == "self-review":
        review = supervisor.record_self_review(
            stage_id=args.stage_id,
            summary=args.summary,
            findings=args.finding,
            decision=args.decision,
            minutes_since_previous_review=args.minutes_since_previous_review,
            commands=args.command_ref,
            test_results=args.test_result,
            source_refs=args.source_ref,
            target_refs=args.target_ref,
            artifacts=args.artifact,
            owner=args.owner,
            next_action=args.next_action,
        )
        result = {"status": "ok", "self_review": review}
    elif args.command == "complete-stage":
        supervisor.complete_stage(args.stage_id, summary=args.summary)
        result = {"status": "ok", "stage_id": args.stage_id}
    elif args.command == "manual-gap":
        gap = supervisor.manual_gap(
            stage_id=args.stage_id,
            reason=args.reason,
            attempted_command=args.attempted_command,
            next_action=args.next_action,
            owner=args.owner,
            source_refs=args.source_ref,
            target_refs=args.target_ref,
            artifacts=args.artifact,
        )
        result = {"status": "manual_gap", "manual_gap": gap}
    elif args.command == "blocked-fallback":
        fallback = supervisor.fallback_blocked_stage(
            stage_id=args.stage_id,
            reason=args.reason,
            failure_class=args.failure_class,
            retryable=args.retryable,
            attempted_command=args.attempted_command,
            next_action=args.next_action,
            owner=args.owner,
            configured=not args.unconfigured_optional,
            required=not args.optional,
            source_refs=args.source_ref,
            target_refs=args.target_ref,
            artifacts=args.artifact,
            start_next=not args.no_start_next,
        )
        result = {"status": fallback["status"], "fallback": fallback}
    elif args.command == "classify-failure":
        failure = supervisor.classify_failure(
            stage_id=args.stage_id,
            failure_class=args.failure_class,
            reason=args.reason,
            retryable=args.retryable,
        )
        result = {"status": "ok", "failure": failure}
    elif args.command == "import-stage-result":
        stage_result = supervisor.import_goal_stage_result(
            args.result_path,
            start_next=not args.no_start_next,
            owner=args.owner,
        )
        result = {"status": stage_result["status"], "stage_result": stage_result}
    elif args.command == "simulate":
        simulation = supervisor.simulate_virtual_soak(
            OvernightSimulationConfig(
                total_minutes=args.total_minutes,
                heartbeat_interval_minutes=args.heartbeat_interval_minutes,
                self_review_interval_minutes=args.self_review_interval_minutes,
                checkpoint_interval_minutes=args.checkpoint_interval_minutes,
                max_heartbeat_gap_minutes=args.max_heartbeat_gap_minutes,
                max_self_review_gap_minutes=args.max_self_review_gap_minutes,
                failures=_parse_simulation_failures(args.failure_json),
            )
        )
        result = {
            "status": "ok" if simulation["slo_status"] == "ok" else "not_evaluated",
            "simulation": simulation,
        }
    elif args.command == "next-stage":
        stage_id = supervisor.move_to_next_high_value_stage()
        result = {
            "status": "ok" if stage_id is not None else "not_evaluated",
            "stage_id": stage_id,
        }
    elif args.command == "snapshot":
        result = {"status": "ok", "snapshot": supervisor.snapshot()}
    else:  # pragma: no cover - argparse prevents this.
        raise SystemExit(f"unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"ok", "manual_gap", "blocked"} else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        required=True,
        help="Stable overnight run id used for the durable supervisor snapshot.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "overnight_supervisor",
        help="Directory for supervisor snapshots and production evidence artifacts.",
    )
    parser.add_argument(
        "--xmuse-root",
        type=Path,
        default=DEFAULT_XMUSE_ROOT,
        help=(
            "Runtime root used for durable lane recovery artifact scans; defaults "
            "to XMUSE_ROOT or the package runtime root."
        ),
    )
    parser.add_argument(
        "--stage",
        action="append",
        default=[],
        metavar="STAGE_ID=OBJECTIVE",
        help="Declare a supervisor stage. May be repeated.",
    )
    parser.add_argument(
        "--stage-priority",
        action="append",
        default=[],
        metavar="STAGE_ID=INT",
        help="Set a supervisor stage priority. Higher values run first when ready.",
    )
    parser.add_argument(
        "--stage-depends-on",
        action="append",
        default=[],
        metavar="STAGE_ID=DEP1,DEP2",
        help="Declare stage dependencies for high-value fallback selection.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the existing supervisor snapshot instead of starting a new one.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start-stage", help="Mark a stage as running.")
    start.add_argument("stage_id")

    heartbeat = subparsers.add_parser(
        "heartbeat",
        help="Record a supervisor heartbeat for the current stage.",
    )
    heartbeat.add_argument("--note", required=True)

    checkpoint = subparsers.add_parser(
        "checkpoint",
        help="Record a checkpoint and production evidence envelope.",
    )
    checkpoint.add_argument("stage_id")
    checkpoint.add_argument("--summary", required=True)
    checkpoint.add_argument("--command", dest="command_ref", action="append", default=[])
    checkpoint.add_argument("--test-result", action="append", default=[])
    checkpoint.add_argument("--source-ref", action="append", default=[])
    checkpoint.add_argument("--target-ref", action="append", default=[])
    checkpoint.add_argument("--artifact", action="append", default=[])
    checkpoint.add_argument("--owner", default="codex")
    checkpoint.add_argument("--next-action", default=None)

    self_review = subparsers.add_parser(
        "self-review",
        help="Record a periodic self-review checkpoint and evidence envelope.",
    )
    self_review.add_argument("stage_id")
    self_review.add_argument("--summary", required=True)
    self_review.add_argument("--finding", action="append", default=[])
    self_review.add_argument(
        "--decision",
        choices=["continue", "retry", "manual_gap", "blocked", "patch_forward"],
        required=True,
    )
    self_review.add_argument("--minutes-since-previous-review", type=int, default=None)
    self_review.add_argument(
        "--command",
        dest="command_ref",
        action="append",
        default=[],
    )
    self_review.add_argument("--test-result", action="append", default=[])
    self_review.add_argument("--source-ref", action="append", default=[])
    self_review.add_argument("--target-ref", action="append", default=[])
    self_review.add_argument("--artifact", action="append", default=[])
    self_review.add_argument("--owner", default="codex")
    self_review.add_argument("--next-action", default=None)

    complete = subparsers.add_parser("complete-stage", help="Mark a stage as ok.")
    complete.add_argument("stage_id")
    complete.add_argument("--summary", required=True)

    manual_gap = subparsers.add_parser(
        "manual-gap",
        help="Mark a stage as manual_gap and write a gap artifact.",
    )
    manual_gap.add_argument("stage_id")
    manual_gap.add_argument("--reason", required=True)
    manual_gap.add_argument("--attempted-command", default=None)
    manual_gap.add_argument("--next-action", default=None)
    manual_gap.add_argument("--owner", default="operator")
    manual_gap.add_argument("--source-ref", action="append", default=[])
    manual_gap.add_argument("--target-ref", action="append", default=[])
    manual_gap.add_argument("--artifact", action="append", default=[])

    blocked_fallback = subparsers.add_parser(
        "blocked-fallback",
        help="Record a configured blocker and continue to the next pending stage.",
    )
    blocked_fallback.add_argument("stage_id")
    blocked_fallback.add_argument("--reason", required=True)
    blocked_fallback.add_argument("--failure-class", required=True)
    blocked_fallback.add_argument("--retryable", action="store_true")
    blocked_fallback.add_argument("--attempted-command", default=None)
    blocked_fallback.add_argument("--next-action", default=None)
    blocked_fallback.add_argument("--owner", default="codex")
    blocked_fallback.add_argument(
        "--unconfigured-optional",
        action="store_true",
        help="Record the fallback as manual_gap instead of configured blocked.",
    )
    blocked_fallback.add_argument(
        "--optional",
        action="store_true",
        help="Mark the missing evidence as not required in the envelope.",
    )
    blocked_fallback.add_argument(
        "--no-start-next",
        action="store_true",
        help="Record the fallback without starting the next pending stage.",
    )
    blocked_fallback.add_argument("--source-ref", action="append", default=[])
    blocked_fallback.add_argument("--target-ref", action="append", default=[])
    blocked_fallback.add_argument("--artifact", action="append", default=[])

    classify_failure = subparsers.add_parser(
        "classify-failure",
        help="Record a retryable or terminal failure classification.",
    )
    classify_failure.add_argument("stage_id")
    classify_failure.add_argument("--failure-class", required=True)
    classify_failure.add_argument("--reason", required=True)
    classify_failure.add_argument("--retryable", action="store_true")

    import_stage_result = subparsers.add_parser(
        "import-stage-result",
        help="Import a goal-stage runner result.json into the supervisor snapshot.",
    )
    import_stage_result.add_argument("result_path", type=Path)
    import_stage_result.add_argument("--owner", default="codex")
    import_stage_result.add_argument(
        "--no-start-next",
        action="store_true",
        help="Do not start the next pending stage when the result is blocked.",
    )

    simulate = subparsers.add_parser(
        "simulate",
        help="Run a deterministic virtual-time overnight supervisor soak.",
    )
    simulate.add_argument("--total-minutes", type=int, required=True)
    simulate.add_argument("--heartbeat-interval-minutes", type=int, default=15)
    simulate.add_argument("--self-review-interval-minutes", type=int, default=60)
    simulate.add_argument("--checkpoint-interval-minutes", type=int, default=120)
    simulate.add_argument("--max-heartbeat-gap-minutes", type=int, default=15)
    simulate.add_argument("--max-self-review-gap-minutes", type=int, default=60)
    simulate.add_argument(
        "--failure-json",
        action="append",
        default=[],
        help=(
            "JSON object with minute, stage_id, reason, failure_class, and optional "
            "retryable, attempted_command, configured, required, source_refs, "
            "target_refs."
        ),
    )

    subparsers.add_parser(
        "next-stage",
        help="Start the next pending stage after a checkpoint or manual gap.",
    )
    subparsers.add_parser("snapshot", help="Print the current supervisor snapshot.")
    return parser


def _load_supervisor(args: argparse.Namespace) -> OvernightSupervisor:
    stages = _parse_stages(
        args.stage,
        priority_values=args.stage_priority,
        dependency_values=args.stage_depends_on,
    )
    config = OvernightSupervisorConfig(
        run_id=args.run_id,
        artifact_dir=args.artifact_dir,
        stages=stages,
        xmuse_root=args.xmuse_root,
    )
    if args.resume:
        snapshot_path = args.artifact_dir / f"overnight-supervisor-{args.run_id}.json"
        if not snapshot_path.exists():
            raise SystemExit(
                f"cannot resume missing supervisor snapshot: {snapshot_path}"
            )
        return OvernightSupervisor.resume(config)
    if not stages:
        raise SystemExit("--stage is required when starting a new supervisor snapshot")
    return OvernightSupervisor(config)


def _parse_stages(
    values: list[str],
    *,
    priority_values: list[str] | None = None,
    dependency_values: list[str] | None = None,
) -> list[OvernightSupervisorStage]:
    priorities = _parse_stage_priorities(priority_values or [])
    dependencies = _parse_stage_dependencies(dependency_values or [])
    stages: list[OvernightSupervisorStage] = []
    for value in values:
        if "=" not in value:
            raise SystemExit("--stage must use STAGE_ID=OBJECTIVE")
        stage_id, objective = value.split("=", 1)
        stage_id = stage_id.strip()
        objective = objective.strip()
        if not stage_id or not objective:
            raise SystemExit("--stage requires non-empty STAGE_ID and OBJECTIVE")
        stages.append(
            OvernightSupervisorStage(
                stage_id=stage_id,
                objective=objective,
                priority=priorities.get(stage_id, 0),
                depends_on=tuple(dependencies.get(stage_id, ())),
            )
        )
    return stages


def _parse_stage_priorities(values: list[str]) -> dict[str, int]:
    priorities: dict[str, int] = {}
    for value in values:
        stage_id, raw_priority = _split_stage_metadata(
            value,
            option_name="--stage-priority",
        )
        try:
            priority = int(raw_priority)
        except ValueError as exc:
            raise SystemExit("--stage-priority requires integer priority") from exc
        priorities[stage_id] = priority
    return priorities


def _parse_stage_dependencies(values: list[str]) -> dict[str, list[str]]:
    dependencies: dict[str, list[str]] = {}
    for value in values:
        stage_id, raw_dependencies = _split_stage_metadata(
            value,
            option_name="--stage-depends-on",
        )
        dependencies[stage_id] = [
            item.strip() for item in raw_dependencies.split(",") if item.strip()
        ]
    return dependencies


def _split_stage_metadata(value: str, *, option_name: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"{option_name} must use STAGE_ID=VALUE")
    stage_id, raw_value = value.split("=", 1)
    stage_id = stage_id.strip()
    raw_value = raw_value.strip()
    if not stage_id or not raw_value:
        raise SystemExit(f"{option_name} requires non-empty STAGE_ID and VALUE")
    return stage_id, raw_value


def _parse_simulation_failures(values: list[str]) -> list[OvernightSimulationFailure]:
    failures: list[OvernightSimulationFailure] = []
    for value in values:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise SystemExit("--failure-json must be a JSON object")
        try:
            failures.append(
                OvernightSimulationFailure(
                    minute=int(payload["minute"]),
                    stage_id=str(payload["stage_id"]),
                    reason=str(payload["reason"]),
                    failure_class=str(payload["failure_class"]),
                    retryable=bool(payload.get("retryable", False)),
                    attempted_command=_optional_str(payload.get("attempted_command")),
                    configured=bool(payload.get("configured", True)),
                    required=bool(payload.get("required", True)),
                    source_refs=tuple(_string_list(payload.get("source_refs"))),
                    target_refs=tuple(_string_list(payload.get("target_refs"))),
                )
            )
        except KeyError as exc:
            raise SystemExit(f"--failure-json missing required key: {exc.args[0]}") from exc
    return failures


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


if __name__ == "__main__":
    raise SystemExit(main())
