#!/usr/bin/env python3
"""Regenerate tests/fixtures.generated.ts from the board v2 contract fixtures.

Reads docs/contracts/fixtures/board_v2/*.json and exports each scenario as a
typed const with keys {projection, summary}. Never hand-edit the generated
file; run `python tools/sync_fixtures.py` from integrations/claude-code, or
`python tools/sync_fixtures.py --check` to fail when it is stale.

Stdlib only. Output is deterministic: scenarios sorted by name, JSON keys
sorted, ASCII-escaped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
FIXTURE_DIR = PLUGIN_ROOT / ".." / ".." / "docs" / "contracts" / "fixtures" / "board_v2"
OUT_PATH = PLUGIN_ROOT / "tests" / "fixtures.generated.ts"
GRANT_GOLDEN_DIR = PLUGIN_ROOT / ".." / ".." / "docs" / "contracts" / "fixtures" / "plugin_grant_v2"
GRANT_OUT_PATH = PLUGIN_ROOT / "tests" / "grant_golden.generated.ts"

GRANT_HEADER = """// GENERATED from docs/contracts/fixtures/plugin_grant_v2/*.json by
// tools/sync_fixtures.py. Do not edit by hand.
"""

HEADER = """// GENERATED from docs/contracts/fixtures/board_v2/*.json by
// tools/sync_fixtures.py. Do not edit by hand.
"""


def load_scenarios() -> list[tuple[str, dict]]:
    scenarios: list[tuple[str, dict]] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        name = path.stem
        if "." in name:
            # Sidecar golden files (<scenario>.review/material/verification.json)
            # live next to the scenarios per the board contract; they are not
            # scenarios themselves.
            continue
        if not name.replace("_", "").isalnum() or not name[0].isalpha():
            raise ValueError(f"fixture name is not a TS identifier: {name}")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if "projection" not in data or "summary" not in data:
            raise ValueError(f"fixture {name}.json lacks projection/summary keys")
        scenarios.append((name, {"projection": data["projection"], "summary": data["summary"]}))
    if not scenarios:
        raise ValueError(f"no fixtures found in {FIXTURE_DIR}")
    return scenarios


def load_grant_golden() -> dict[str, dict]:
    golden: dict[str, dict] = {}
    for path in sorted(GRANT_GOLDEN_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            golden[path.stem] = json.load(fh)
    if not golden:
        raise ValueError(f"no grant golden files found in {GRANT_GOLDEN_DIR}")
    return golden


def render_grant_golden(golden: dict[str, dict]) -> str:
    body = json.dumps(golden, sort_keys=True, ensure_ascii=True, indent=2)
    return GRANT_HEADER + f"export const GRANT_GOLDEN: Record<string, any> = {body};\n"


def render(scenarios: list[tuple[str, dict]]) -> str:
    chunks = [HEADER]
    names = []
    for name, payload in scenarios:
        names.append(name)
        body = json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2)
        chunks.append(f"export const {name} = {body};\n")
    chunks.append(f"\nexport const SCENARIO_NAMES = {json.dumps(names)} as const;\n")
    chunks.append("\nexport type ScenarioName = (typeof SCENARIO_NAMES)[number];\n")
    return "\n".join(chunks)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Regenerate board v2 TS fixtures.")
    parser.add_argument(
        "--check", action="store_true", help="Fail when the generated file is stale."
    )
    args = parser.parse_args(argv)
    scenarios = load_scenarios()
    rendered = render(scenarios)
    golden = load_grant_golden()
    grant_rendered = render_grant_golden(golden)
    outputs = [(OUT_PATH, rendered), (GRANT_OUT_PATH, grant_rendered)]
    if args.check:
        for path, text in outputs:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                print(f"stale: {path} (run python tools/sync_fixtures.py)", file=sys.stderr)
                return 1
        print(
            f"ok: generated fixtures are current ({len(scenarios)} scenarios, {len(golden)} golden)"
        )
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    for path, text in outputs:
        path.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(scenarios)} scenarios)")
    print(f"wrote {GRANT_OUT_PATH} ({len(golden)} grant golden)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
