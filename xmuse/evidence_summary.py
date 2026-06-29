#!/usr/bin/env python3
"""Print a read-only natural groupchat evidence summary."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.chat.frontend_projection import build_peer_chat_ux_projection
from xmuse_core.runtime.paths import default_xmuse_root


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--conversation-id",
        required=True,
        help="Peer-chat conversation id to summarize.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_xmuse_root(Path(__file__).resolve().parent),
        help="xmuse runtime root containing chat.db and durable evidence files.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        projection = build_peer_chat_ux_projection(args.conversation_id, args.root)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            projection["evidence_summary"],
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
