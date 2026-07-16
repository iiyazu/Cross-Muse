#!/usr/bin/env python3
"""Command-line surface for the local xmuse Workroom."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse.workroom import (
    DEFAULT_XMUSE_ROOT,
    doctor_workroom,
    start_workroom,
    stop_workroom,
    workroom_status,
)
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomPaths
from xmuse.workroom_launcher import (
    WorkroomLaunchDependencies,
    WorkroomLaunchRequest,
    launch_workroom,
)


def _add_start_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)
    parser.add_argument("--readiness-timeout-s", type=float, default=30.0)
    parser.add_argument("--stop-timeout-s", type=float, default=20.0)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="read-only Agent workspace and exact-patch target (defaults to xmuse)",
    )
    parser.add_argument(
        "--execution-profile",
        help="fixed server gate profile; required for a non-default workspace",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="enable the optional source-backed MemoryOS archive sidecar",
    )
    parser.add_argument(
        "--memoryos-executable",
        type=Path,
        help="absolute or relative path to the MemoryOS executable (requires --memory)",
    )
    parser.add_argument(
        "--memory-profile",
        choices=("archive-only", "full-local"),
        default=None,
        help=(
            "MemoryOS capability profile (default: full-local; archive-only is compatibility mode)"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="start and supervise the local Workroom")
    _add_start_options(start)

    launch = subparsers.add_parser("launch", help="start the Workroom in the background")
    _add_start_options(launch)
    launch.add_argument("--no-open", action="store_true", help="do not open the browser")

    status = subparsers.add_parser("status", help="inspect the managed Workroom")
    status.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)

    stop = subparsers.add_parser("stop", help="stop the managed Workroom")
    stop.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)
    stop.add_argument("--timeout-s", type=float, default=20.0)

    doctor = subparsers.add_parser("doctor", help="check local Workroom prerequisites")
    doctor.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    dependencies: WorkroomDependencies | None = None,
    launch_dependencies: WorkroomLaunchDependencies | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    deps = dependencies or WorkroomDependencies()
    paths = WorkroomPaths.resolve(args.root, deps.repo_root, deps.assets_root)
    if args.command == "start":
        if args.readiness_timeout_s <= 0 or args.stop_timeout_s <= 0:
            build_parser().error("timeouts must be positive")
        if bool(args.memory) != (args.memoryos_executable is not None):
            build_parser().error("--memory and --memoryos-executable must be provided together")
        if args.memory_profile is not None and not args.memory:
            build_parser().error("--memory-profile requires --memory")
        resolved_memory_profile = args.memory_profile or (
            "full-local" if args.memory else "archive-only"
        )
        return start_workroom(
            paths,
            deps,
            readiness_timeout_s=args.readiness_timeout_s,
            stop_timeout_s=args.stop_timeout_s,
            execution_workspace=args.workspace,
            execution_profile_id=args.execution_profile,
            memory_enabled=bool(args.memory),
            memoryos_executable=args.memoryos_executable,
            memory_profile=resolved_memory_profile,
        )
    if args.command == "launch":
        if args.readiness_timeout_s <= 0 or args.stop_timeout_s <= 0:
            build_parser().error("timeouts must be positive")
        if args.memoryos_executable is not None and not args.memory:
            build_parser().error("--memoryos-executable requires --memory")
        if args.memory_profile is not None and not args.memory:
            build_parser().error("--memory-profile requires --memory")
        exit_code, payload = launch_workroom(
            paths,
            deps,
            WorkroomLaunchRequest(
                root=args.root,
                readiness_timeout_s=args.readiness_timeout_s,
                stop_timeout_s=args.stop_timeout_s,
                workspace=args.workspace,
                execution_profile=args.execution_profile,
                memory=bool(args.memory),
                memoryos_executable=args.memoryos_executable,
                memory_profile=args.memory_profile,
                open_browser=not args.no_open,
            ),
            dependencies=launch_dependencies,
        )
        print(json.dumps(payload, sort_keys=True))
        return exit_code
    if args.command == "status":
        return workroom_status(paths, deps)[0]
    if args.command == "stop":
        if args.timeout_s <= 0:
            build_parser().error("--timeout-s must be positive")
        return stop_workroom(paths, deps, timeout_s=args.timeout_s)
    if args.command == "doctor":
        return doctor_workroom(paths, deps)
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
