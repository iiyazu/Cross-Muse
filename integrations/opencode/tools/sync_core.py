#!/usr/bin/env python3
"""Regenerate src/core/*.ts from the Claude Code mod's host-agnostic modules.

Copies integrations/claude-code/src/{api,board_state,labels,poll,text}.ts and
integrations/claude-code/types/index.d.ts into src/core/ (the types file lands
as src/core/types.ts). The only rewrite is the relative import of the types
file: "../types/index" -> "./types". Every other byte is identical so the two
hosts cannot drift; tests/xmuse/test_integrations_opencode_plugin.py asserts
this. Never hand-edit src/core/; run `python tools/sync_core.py` from
integrations/opencode, or `python tools/sync_core.py --check` to fail when
stale.

Stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
CLAUDE_SRC = PLUGIN_ROOT / ".." / "claude-code" / "src"
CLAUDE_TYPES = PLUGIN_ROOT / ".." / "claude-code" / "types" / "index.d.ts"
CORE_DIR = PLUGIN_ROOT / "src" / "core"

# The single documented rewrite. Keep it minimal: every other byte stays
# identical to the Claude mod so host-agnostic logic cannot drift.
IMPORT_REWRITE_FROM = '"../types/index"'
IMPORT_REWRITE_TO = '"./types"'

MODULES = ("api", "board_state", "labels", "poll", "text")


def render_one(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    return text.replace(IMPORT_REWRITE_FROM, IMPORT_REWRITE_TO)


def planned() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for name in MODULES:
        out.append((CORE_DIR / f"{name}.ts", render_one(CLAUDE_SRC / f"{name}.ts")))
    out.append((CORE_DIR / "types.ts", CLAUDE_TYPES.read_text(encoding="utf-8")))
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Regenerate src/core from the Claude mod.")
    parser.add_argument(
        "--check", action="store_true", help="Fail when the generated files are stale."
    )
    args = parser.parse_args(argv)
    if not CLAUDE_TYPES.is_file():
        print(f"missing Claude types file: {CLAUDE_TYPES}", file=sys.stderr)
        return 1
    for name in MODULES:
        if not (CLAUDE_SRC / f"{name}.ts").is_file():
            print(f"missing Claude module: {CLAUDE_SRC / f'{name}.ts'}", file=sys.stderr)
            return 1
    items = planned()
    if args.check:
        stale = [str(p) for p, want in items if not p.is_file() or p.read_text() != want]
        if stale:
            print(f"stale: {', '.join(stale)} (run python tools/sync_core.py)", file=sys.stderr)
            return 1
        print(f"ok: src/core is current ({len(items)} files)")
        return 0
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    for path, want in items:
        path.write_text(want, encoding="utf-8")
    print(f"wrote {CORE_DIR} ({len(items)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
