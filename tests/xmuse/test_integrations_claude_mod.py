"""Host-side checks for the Claude Code xmuse mod (no Claude needed).

Covers the hard rules that are statically verifiable:
- tools/sync_fixtures.py --check passes (generated fixtures are current);
- hooks/ and src/ use no forbidden engine calls, only GET, no operator
  token material, no write HTTP verbs;
- plugin.json / hooks.json / marketplace.json parse and agree on the name.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "integrations" / "claude-code"

FORBIDDEN_SNIPPETS = [
    "$.process",
    "$.fs",
    "$.model",
    "$.agent",
    "$.prompt.submit",
    "$.session.append",
    "$.session.send",
    "$.mcp",
    "$.config.set",
]

FORBIDDEN_TOKENS = [
    "X-XMuse-Operator-Token",
    "XMUSE_OPERATOR_TOKEN",
]

WRITE_VERBS = ["POST", "PUT", "DELETE"]


def _plugin_sources() -> list[Path]:
    files: list[Path] = []
    for sub in ("hooks", "src"):
        root = PLUGIN_ROOT / sub
        assert root.is_dir(), f"missing plugin dir: {root}"
        files.extend(sorted(root.rglob("*.ts")) + sorted(root.rglob("*.tsx")))
    assert files, "no plugin sources found"
    return files


def test_fixtures_current() -> None:
    proc = subprocess.run(
        [sys.executable, "tools/sync_fixtures.py", "--check"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"sync_fixtures.py --check failed:\n{proc.stdout}\n{proc.stderr}"
    generated = PLUGIN_ROOT / "tests" / "fixtures.generated.ts"
    assert generated.is_file(), "tests/fixtures.generated.ts missing"
    text = generated.read_text(encoding="utf-8")
    assert "export const empty" in text
    assert "export const injection_text" in text


def test_no_forbidden_calls() -> None:
    violations: list[str] = []
    for path in _plugin_sources():
        text = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in text:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}: {snippet}")
    assert not violations, "forbidden engine calls in mod source:\n" + "\n".join(violations)


def test_engine_calls_stay_in_hooks_module() -> None:
    """Mirrors the `claude plugin validate` rule: $ is spelled only in the
    hooks module, never across an import into src/."""
    violations: list[str] = []
    sources = sorted((PLUGIN_ROOT / "src").rglob("*.ts"))
    sources += sorted((PLUGIN_ROOT / "src").rglob("*.tsx"))
    for path in sources:
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "$." in line:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}:{lineno}: {line.strip()}")
    assert not violations, "engine calls outside hooks/:\n" + "\n".join(violations)


def test_only_get_and_no_operator_token() -> None:
    violations: list[str] = []
    for path in _plugin_sources():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}: {token}")
        for verb in WRITE_VERBS:
            if f'"{verb}"' in text or f"'{verb}'" in text:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}: {verb}")
    assert not violations, "write verbs or operator token material:\n" + "\n".join(violations)


def test_manifests_agree() -> None:
    plugin_path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    hooks_path = PLUGIN_ROOT / "hooks" / "hooks.json"
    market_path = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"
    plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    market = json.loads(market_path.read_text(encoding="utf-8"))

    assert plugin["name"] == "xmuse"
    assert plugin["version"] == "0.1.0"
    assert plugin["types"] == "./types/index.d.ts"
    assert plugin["userConfig"]["baseUrl"]["default"] == "http://127.0.0.1:8201"
    assert plugin["userConfig"]["webUrl"]["default"] == "http://127.0.0.1:3000"
    assert plugin["userConfig"]["pollSeconds"]["default"] == 5

    assert hooks["modules"] == ["./register.tsx"]
    assert (PLUGIN_ROOT / "hooks" / "register.tsx").is_file()

    listed = [p.get("name") for p in market.get("plugins", [])]
    assert "xmuse" in listed, f"marketplace does not list xmuse: {listed}"
    entry = next(p for p in market["plugins"] if p.get("name") == "xmuse")
    assert entry.get("source") == "./"


def test_readme_documents_safety() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    for needle in ("mcp__xmuse__status", "/xmuse", "WSL", "Read-only"):
        assert needle in readme, f"README missing {needle!r}"
