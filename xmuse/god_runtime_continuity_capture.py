from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.god_runtime_continuity_capture import (
    capture_selected_god_runtime_continuity_artifact,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-god-runtime-continuity-capture",
        description="Export selected GOD runtime continuity from durable xmuse stores.",
    )
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument(
        "--selection-store",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "god_cli_selections.json",
        help="Path to god_cli_selections.json.",
    )
    parser.add_argument(
        "--registration-store",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "god_cli_registrations.json",
        help="Path to god_cli_registrations.json.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "god_sessions.json",
        help="Path to god_sessions.json.",
    )
    parser.add_argument(
        "--now-utc",
        default=None,
        help="Optional UTC timestamp for deterministic heartbeat freshness checks.",
    )
    parser.add_argument(
        "--heartbeat-ttl-seconds",
        type=int,
        default=300,
        help="Maximum selected GOD heartbeat age before the artifact is blocked.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "god-runtime-continuity.json",
        help="Path for the xmuse.god_runtime_continuity.v1 artifact.",
    )
    args = parser.parse_args(argv)
    artifact = capture_selected_god_runtime_continuity_artifact(
        conversation_id=args.conversation_id,
        selection_store_path=args.selection_store,
        registration_store_path=args.registration_store,
        registry_path=args.registry,
        output_path=args.output,
        now_utc=args.now_utc,
        heartbeat_ttl_seconds=args.heartbeat_ttl_seconds,
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
