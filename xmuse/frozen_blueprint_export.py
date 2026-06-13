"""CLI for exporting mission_blueprint.v1 artifacts from chat resolution authority."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.structuring.frozen_blueprint_export import (
    export_frozen_blueprint_from_chat_store,
)

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chat-db",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "chat.db",
        help="Path to the durable xmuse chat.db.",
    )
    parser.add_argument(
        "--resolution-id",
        help="Approved deliberation_freeze resolution id to export.",
    )
    parser.add_argument(
        "--conversation-id",
        help="Conversation id used when exporting the latest frozen blueprint.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "mission-blueprint.json",
        help="Path for the exported mission_blueprint.v1 JSON artifact.",
    )
    args = parser.parse_args(argv)

    artifact = export_frozen_blueprint_from_chat_store(
        chat_db=args.chat_db,
        output_path=args.output,
        resolution_id=args.resolution_id,
        conversation_id=args.conversation_id,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(artifact),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
