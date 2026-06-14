from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.natural_deliberation_transcript_capture import (
    export_natural_deliberation_transcript_artifact,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-natural-deliberation-transcript-capture",
        description="Export a natural GOD transcript artifact from durable chat state.",
    )
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument(
        "--chat-db",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "chat.db",
        help="Path to chat.db.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "god_sessions.json",
        help="Path to god_sessions.json.",
    )
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--target-ref", action="append", default=[])
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "natural-transcript.json",
        help="Path for the xmuse.operator_transcript.v1 artifact.",
    )
    args = parser.parse_args(argv)
    artifact = export_natural_deliberation_transcript_artifact(
        chat_db_path=args.chat_db,
        registry_path=args.registry,
        conversation_id=args.conversation_id,
        output_path=args.output,
        source_refs=args.source_ref,
        target_refs=args.target_ref,
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
