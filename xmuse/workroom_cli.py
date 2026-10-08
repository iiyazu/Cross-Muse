#!/usr/bin/env python3
"""Command-line surface for the local xmuse Workroom."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from xmuse.memoryos_companion import MemoryOSCompanionError, discover_managed_companion
from xmuse.workroom import (
    DEFAULT_XMUSE_ROOT,
    doctor_workroom,
    start_workroom,
    stop_workroom,
    workroom_status,
)
from xmuse.workroom_contracts import WorkroomDependencies, WorkroomPaths
from xmuse.workroom_launcher import (
    ManagedMemoryOSError,
    WorkroomLaunchDependencies,
    WorkroomLaunchRequest,
    _prepare_managed_memoryos_cache,
    launch_workroom,
)
from xmuse.workroom_pair import PairDependencies, run_pair


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
    claude_flags = parser.add_mutually_exclusive_group()
    claude_flags.add_argument(
        "--claude",
        action="store_true",
        default=None,
        help="admit Claude Code Room participants (default: auto-detect)",
    )
    claude_flags.add_argument(
        "--no-claude",
        action="store_true",
        help="refuse Claude Code Room participants even when available",
    )
    antigravity_flags = parser.add_mutually_exclusive_group()
    antigravity_flags.add_argument(
        "--antigravity",
        action="store_true",
        default=None,
        help=(
            "admit Antigravity Room participants (default: auto-detect); requires the "
            "Room MCP on 127.0.0.1:8100"
        ),
    )
    opencode_flags = parser.add_mutually_exclusive_group()
    opencode_flags.add_argument(
        "--opencode",
        action="store_true",
        default=None,
        help=(
            "admit OpenCode Room participants in a read-only bubblewrap sandbox "
            "(default: auto-detect); the model comes from XMUSE_OPENCODE_MODEL"
        ),
    )
    opencode_flags.add_argument(
        "--no-opencode",
        action="store_true",
        help="refuse OpenCode Room participants even when available",
    )
    antigravity_flags.add_argument(
        "--no-antigravity",
        action="store_true",
        help="refuse Antigravity Room participants even when available",
    )
    memory_flags = parser.add_mutually_exclusive_group()
    memory_flags.add_argument(
        "--memory",
        action="store_true",
        help="enable the optional source-backed MemoryOS archive sidecar (alias for mode on)",
    )
    memory_flags.add_argument(
        "--no-memory",
        action="store_true",
        help="disable MemoryOS even when an installed companion is available",
    )
    parser.add_argument(
        "--memory-mode",
        choices=("auto", "on", "off"),
        default=None,
        help="select MemoryOS auto-discovery, explicit enablement, or disablement",
    )
    parser.add_argument(
        "--memoryos-executable",
        type=Path,
        help="absolute or relative path to the MemoryOS executable (requires --memory)",
    )
    parser.add_argument(
        "--memory-profile",
        choices=("archive-only", "full-local", "full-local-curated"),
        default=None,
        help=(
            "MemoryOS capability profile (default: full-local; archive-only is "
            "compatibility mode; full-local-curated additionally enables the opt-in "
            "MemoryOS Curator with XMUSE_MEMORYOS_LLM_API_KEY)"
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

    pair = subparsers.add_parser(
        "pair", help="pair a host plugin (main window) with this Workroom; terminal only"
    )
    pair.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)
    pair.add_argument("--host", default="claude-code")
    pair.add_argument("--room", action="append", default=[], help="Room id prefix (repeatable)")
    pair.add_argument("--scope", action="append", default=[], help="grant scope (repeatable)")
    pair.add_argument("--ttl", type=int, default=None, help="grant lifetime in seconds")
    pair_mode = pair.add_mutually_exclusive_group()
    pair_mode.add_argument("--revoke", action="store_true", help="revoke every grant of the host")
    pair_mode.add_argument("--list", action="store_true", help="list the host's live grants")
    pair_mode.add_argument(
        "--pending",
        action="store_true",
        help="show the splits and reviews waiting for you, with the digest the pane asks for",
    )
    return parser


def _requested_provider(value: bool | None, disabled: bool) -> bool | None:
    if value:
        return True
    if disabled:
        return False
    return None


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    dependencies: WorkroomDependencies | None = None,
    launch_dependencies: WorkroomLaunchDependencies | None = None,
    pair_dependencies: PairDependencies | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    deps = dependencies or WorkroomDependencies()
    paths = WorkroomPaths.resolve(args.root, deps.repo_root, deps.assets_root)
    requested_claude = _requested_provider(
        getattr(args, "claude", None), getattr(args, "no_claude", False)
    )
    requested_antigravity = _requested_provider(
        getattr(args, "antigravity", None), getattr(args, "no_antigravity", False)
    )
    requested_opencode = _requested_provider(
        getattr(args, "opencode", None), getattr(args, "no_opencode", False)
    )
    requested_mode = getattr(args, "memory_mode", None)
    if requested_mode is None:
        requested_mode = (
            "on"
            if getattr(args, "memory", False)
            else "off"
            if getattr(args, "no_memory", False)
            else "auto"
        )
    if getattr(args, "memory", False) and requested_mode != "on":
        build_parser().error("--memory is an alias for --memory-mode on")
    if getattr(args, "no_memory", False) and requested_mode != "off":
        build_parser().error("--no-memory conflicts with --memory-mode on")
    if args.command == "start":
        if args.readiness_timeout_s <= 0 or args.stop_timeout_s <= 0:
            build_parser().error("timeouts must be positive")
        if requested_mode == "off" and args.memoryos_executable is not None:
            build_parser().error("--memoryos-executable requires memory mode on")
        if requested_mode == "auto" and args.memoryos_executable is not None:
            build_parser().error("an explicit MemoryOS executable requires memory mode on")
        if args.memory_profile is not None and requested_mode != "on":
            build_parser().error("--memory-profile requires memory mode on")
        memory_enabled = requested_mode == "on"
        executable = args.memoryos_executable
        disabled_code: str | None = None
        if requested_mode == "auto":
            try:
                companion = discover_managed_companion()
            except MemoryOSCompanionError as exc:
                companion = None
                disabled_code = exc.code
            if companion is not None:
                memory_enabled = True
                executable = companion.executable
                try:
                    _prepare_managed_memoryos_cache(executable, paths.xmuse_root)
                except ManagedMemoryOSError as exc:
                    memory_enabled = False
                    executable = None
                    disabled_code = str(exc) or "memoryos_companion_cache_invalid"
        if memory_enabled and executable is None:
            build_parser().error(
                "memory mode on requires an explicit or managed MemoryOS executable"
            )
        resolved_memory_profile = args.memory_profile or (
            "full-local" if memory_enabled else "archive-only"
        )
        return start_workroom(
            paths,
            deps,
            readiness_timeout_s=args.readiness_timeout_s,
            stop_timeout_s=args.stop_timeout_s,
            execution_workspace=args.workspace,
            execution_profile_id=args.execution_profile,
            memory_enabled=memory_enabled,
            memoryos_executable=executable,
            memory_profile=resolved_memory_profile,
            memory_disabled_code=disabled_code,
            claude=requested_claude,
            antigravity=requested_antigravity,
            opencode=requested_opencode,
        )
    if args.command == "launch":
        if args.readiness_timeout_s <= 0 or args.stop_timeout_s <= 0:
            build_parser().error("timeouts must be positive")
        if requested_mode == "off" and args.memoryos_executable is not None:
            build_parser().error("--memoryos-executable requires memory mode on")
        if requested_mode == "auto" and args.memoryos_executable is not None:
            build_parser().error("an explicit MemoryOS executable requires memory mode on")
        if args.memory_profile is not None and requested_mode != "on":
            build_parser().error("--memory-profile requires memory mode on")
        memory_enabled = requested_mode == "on"
        executable = args.memoryos_executable
        exit_code, payload = launch_workroom(
            paths,
            deps,
            WorkroomLaunchRequest(
                root=args.root,
                readiness_timeout_s=args.readiness_timeout_s,
                stop_timeout_s=args.stop_timeout_s,
                workspace=args.workspace,
                execution_profile=args.execution_profile,
                memory=memory_enabled,
                memory_mode="on" if memory_enabled else requested_mode,
                memoryos_executable=executable,
                memory_profile=args.memory_profile,
                open_browser=not args.no_open,
                claude=requested_claude,
                antigravity=requested_antigravity,
                opencode=requested_opencode,
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
    if args.command == "pair":
        return run_pair(
            root=args.root,
            host=args.host,
            room_prefixes=args.room,
            scopes=args.scope or None,
            ttl_seconds=args.ttl,
            revoke=args.revoke,
            list_only=args.list,
            pending=args.pending,
            deps=pair_dependencies
            or PairDependencies(
                stdin_isatty=sys.stdin.isatty,
                stdout_isatty=sys.stdout.isatty,
            ),
        )
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
