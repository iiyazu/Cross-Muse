#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from xmuse_core.platform.runner_supervisor import (
    RunnerSupervisorConfig,
    runner_status,
    start_runner,
)
from xmuse_core.runtime.paths import default_xmuse_root

ROOT = Path(__file__).resolve().parent.parent
XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="xmuse runner supervisor")
    parser.add_argument("command", choices=("start", "status"))
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--pid-file",
        type=Path,
        default=XMUSE_ROOT / "runner.pid.json",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=XMUSE_ROOT / "logs" / "platform_runner.supervisor.log",
    )
    parser.add_argument("--max-hours", type=float, default=10.0)
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--mcp-port", type=int, default=8100)
    parser.add_argument("--persistent-execute-god", action="store_true")
    return parser


def _config(args: argparse.Namespace) -> RunnerSupervisorConfig:
    return RunnerSupervisorConfig(
        repo_root=ROOT,
        pid_file=args.pid_file,
        log_path=args.log_path,
        max_hours=args.max_hours,
        max_concurrent=args.max_concurrent,
        mcp_port=args.mcp_port,
        persistent_execute_god=args.persistent_execute_god,
    )


def main() -> None:
    args = main_arg_parser().parse_args()
    config = _config(args)
    if args.command == "start":
        payload = start_runner(config, replace=args.replace)
    else:
        payload = runner_status(config)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
