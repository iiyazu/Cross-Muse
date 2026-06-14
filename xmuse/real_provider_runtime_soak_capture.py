from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.real_provider_runtime_soak_capture import (
    export_real_provider_runtime_soak_artifact,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-real-provider-runtime-soak-capture",
        description="Export a real provider runtime soak artifact from durable traces.",
    )
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--fresh-inbox-item-id", required=True)
    parser.add_argument("--resume-inbox-item-id", required=True)
    parser.add_argument("--runtime-backend", required=True)
    parser.add_argument("--transport", required=True)
    parser.add_argument("--run-id")
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
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "real-provider-runtime.json",
        help="Path for the xmuse.real_provider_runtime.v1 artifact.",
    )
    args = parser.parse_args(argv)
    artifact = export_real_provider_runtime_soak_artifact(
        chat_db_path=args.chat_db,
        registry_path=args.registry,
        conversation_id=args.conversation_id,
        fresh_inbox_item_id=args.fresh_inbox_item_id,
        resume_inbox_item_id=args.resume_inbox_item_id,
        runtime_backend=args.runtime_backend,
        transport=args.transport,
        output_path=args.output,
        run_id=args.run_id,
        source_refs=args.source_ref,
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
