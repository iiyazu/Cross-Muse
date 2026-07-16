#!/usr/bin/env python3
"""Internal one-shot entrypoint for the exact-patch execution controller."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_controller import (
    ControllerConfig,
    RoomExecutionControllerError,
    run_execution_controller,
)
from xmuse_core.chat.room_execution_controller_store import RoomExecutionControllerStore
from xmuse_core.chat.room_runtime import read_process_start_identity
from xmuse_core.runtime.data_guard import assert_data_operation_complete


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one authorized Room execution")
    parser.add_argument("--xmuse-root", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    xmuse_root = Path(args.xmuse_root).expanduser().resolve()
    worktree = Path(args.worktree).expanduser().resolve(strict=True)
    try:
        assert_data_operation_complete(xmuse_root)
        pid = os.getpid()
        start_identity = read_process_start_identity(pid)
        if start_identity is None:
            raise RoomExecutionControllerError("execution_controller_identity_unavailable")
        controller_id = os.environ.get("XMUSE_EXECUTION_CONTROLLER_ID") or (
            f"execution_controller_{uuid.uuid4().hex}"
        )
        generation = os.environ.get("XMUSE_WORKROOM_GENERATION")
        if not generation:
            raise RoomExecutionControllerError("execution_controller_generation_required")
        result = run_execution_controller(
            RoomExecutionControllerStore(xmuse_root / "chat.db"),
            ControllerConfig(
                xmuse_root=xmuse_root,
                execution_root=worktree,
                run_id=str(args.run_id),
                controller_id=controller_id,
                controller_generation=generation,
                controller_pid=pid,
                controller_start_identity=start_identity,
            ),
        )
        print(
            json.dumps(
                {
                    "schema_version": "room_execution_controller_result/v1",
                    "run_id": result.get("run_id"),
                    "state": result.get("state"),
                    "reason_code": result.get("reason_code"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except (RoomExecutionControllerError, RoomExecutionStoreError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "room_execution_controller_error/v1",
                    "code": exc.code,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return (
            75
            if exc.code
            in {
                "execution_repo_busy",
                "room_execution_run_claim_conflict",
                "room_execution_takeover_guard_mismatch",
            }
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
