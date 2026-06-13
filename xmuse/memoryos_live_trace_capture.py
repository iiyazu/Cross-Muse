from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.integrations.memoryos_lite_interop import (
    MEMORYOS_LITE_BASE_URL_ENV,
    live_memoryos_lite_enabled,
)
from xmuse_core.integrations.memoryos_namespace import task_namespace
from xmuse_core.platform.memoryos_live_trace_capture import (
    capture_memoryos_lite_live_trace_artifact,
    capture_memoryos_lite_live_trace_manual_gap_artifact,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-memoryos-live-trace-capture",
        description="Run an opt-in live MemoryOS Lite trace capture.",
    )
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--god-id", required=True)
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--blueprint-id", required=True)
    parser.add_argument("--feature-id", required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--budget", type=int, default=4096)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "memoryos-trace.json",
        help="Path for the xmuse.memoryos_lite_trace.v1 artifact.",
    )
    parser.add_argument(
        "--binding-store",
        type=Path,
        default=None,
        help="Optional MemoryOS Lite namespace/session binding store path.",
    )
    args = parser.parse_args(argv)

    namespace = task_namespace(
        repo_id=args.repo_id,
        workspace_id=args.workspace_id,
        god_id=args.god_id,
        conversation_id=args.conversation_id,
        thread_id=args.thread_id,
        blueprint_id=args.blueprint_id,
        feature_id=args.feature_id,
        lane_id=args.lane_id,
    )
    env = os.environ
    if not live_memoryos_lite_enabled(env):
        artifact = capture_memoryos_lite_live_trace_manual_gap_artifact(
            namespace=namespace,
            output_path=args.output,
            source_refs=args.source_ref,
        )
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "proof_level": artifact["proof_level"],
                    "reason": "memoryos_lite_live_environment_missing",
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
        return 2

    artifact = asyncio.run(
        capture_memoryos_lite_live_trace_artifact(
            base_url=env[MEMORYOS_LITE_BASE_URL_ENV],
            namespace=namespace,
            actor_id=args.actor_id,
            content=args.content,
            query=args.query,
            source_refs=args.source_ref,
            output_path=args.output,
            binding_store_path=args.binding_store,
            budget=args.budget,
        )
    )
    status = "ok" if artifact["fact_state"] == "observed" else "blocked"
    print(
        json.dumps(
            {
                "status": status,
                "proof_level": artifact["proof_level"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
