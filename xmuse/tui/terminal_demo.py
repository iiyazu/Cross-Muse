from __future__ import annotations

import argparse
from pathlib import Path

from xmuse_core.chat.terminal_tui_demo import run_terminal_tui_demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the xmuse terminal TUI demo harness.")
    parser.add_argument("--xmuse-root", required=True, type=Path)
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--command", default="uv run python -m xmuse.tui")
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--chat-api-url", default=None)
    args = parser.parse_args(argv)

    result = run_terminal_tui_demo(
        xmuse_root=args.xmuse_root,
        conversation_id=args.conversation_id,
        command=args.command,
        timeout_s=args.timeout_s,
        chat_api_base_url=args.chat_api_url,
    )
    path = args.xmuse_root / "tui_terminal_demo.json"
    if not result.written:
        print(
            "terminal-tui-demo-evidence-missing: "
            + ", ".join(result.missing_surfaces)
        )
        return 1
    print(f"terminal-tui-demo-evidence-written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
