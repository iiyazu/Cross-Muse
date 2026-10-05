"""Host-side checks for the OpenCode xmuse TUI plugin (no OpenCode needed).

Covers the hard rules that are statically verifiable:
- tools/sync_core.py and tools/sync_fixtures.py --check pass (generated
  core copies and fixtures are current and cannot drift from the Claude mod);
- src/ uses no model-callable writes: no context.client, no session.* use,
  no tool registration, no operator token material, no write HTTP verbs,
  no xmuse/xmuse_core imports (loopback HTTP contract only);
- src/index.ts (server entry) is dependency-free;
- package.json exports the server entry and the TUI entry and depends on
  @opencode/plugin;
- bun test passes in integrations/opencode (skipped with a reason when bun
  is not on PATH).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "integrations" / "opencode"
CLAUDE_ROOT = REPO_ROOT / "integrations" / "claude-code"

FORBIDDEN_TOKENS = [
    "context.client",
    "session.",
    ".tool",
    "Authorization",
    "X-XMuse-Operator-Token",
    'method: "POST"',
    "process.spawn",
    "child_process",
]

IMPORT_RE = re.compile(
    r"""(?:from\s+["']|require\(\s*["']|import\(\s*["'])(xmuse[^"']*|xmuse_core[^"']*)["']""",
)

CORE_MODULES = ("api", "board_state", "labels", "poll", "text")
IMPORT_REWRITE_FROM = '"../types/index"'
IMPORT_REWRITE_TO = '"./types"'


def _plugin_sources() -> list[Path]:
    root = PLUGIN_ROOT / "src"
    assert root.is_dir(), f"missing plugin src dir: {root}"
    files = sorted(root.rglob("*.ts")) + sorted(root.rglob("*.tsx"))
    assert files, "no plugin sources found"
    return files


def test_generators_current() -> None:
    for tool in ("tools/sync_core.py", "tools/sync_fixtures.py"):
        proc = subprocess.run(
            [sys.executable, tool, "--check"],
            cwd=PLUGIN_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, f"{tool} --check failed:\n{proc.stdout}\n{proc.stderr}"
    generated = PLUGIN_ROOT / "tests" / "fixtures.generated.ts"
    assert generated.is_file(), "tests/fixtures.generated.ts missing"
    text = generated.read_text(encoding="utf-8")
    assert "export const empty" in text
    assert "export const injection_text" in text


def test_core_matches_claude_mod() -> None:
    for name in CORE_MODULES:
        claude = (CLAUDE_ROOT / "src" / f"{name}.ts").read_text(encoding="utf-8")
        opencode = (PLUGIN_ROOT / "src" / "core" / f"{name}.ts").read_text(encoding="utf-8")
        assert opencode == claude.replace(IMPORT_REWRITE_FROM, IMPORT_REWRITE_TO), (
            f"src/core/{name}.ts drifted from the Claude mod "
            "(regenerate with python tools/sync_core.py)"
        )
    claude_types = (CLAUDE_ROOT / "types" / "index.d.ts").read_text(encoding="utf-8")
    opencode_types = (PLUGIN_ROOT / "src" / "core" / "types.ts").read_text(encoding="utf-8")
    assert opencode_types == claude_types, "src/core/types.ts drifted from the Claude mod"


def test_no_forbidden_tokens() -> None:
    violations: list[str] = []
    for path in _plugin_sources():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}: {token}")
    assert not violations, "forbidden tokens in plugin source:\n" + "\n".join(violations)


def test_no_host_imports() -> None:
    violations: list[str] = []
    for path in _plugin_sources():
        text = path.read_text(encoding="utf-8")
        if "xmuse_core" in text:
            violations.append(f"{path.relative_to(PLUGIN_ROOT)}: xmuse_core")
            continue
        for match in IMPORT_RE.finditer(text):
            line = text[: match.start()].count("\n") + 1
            violations.append(f"{path.relative_to(PLUGIN_ROOT)}:{line}: {match.group(0).strip()}")
    assert not violations, "host imports in plugin source:\n" + "\n".join(violations)


def test_server_entry_has_no_import() -> None:
    text = (PLUGIN_ROOT / "src" / "index.ts").read_text(encoding="utf-8")
    assert re.search(r"\bimport\b", text) is None, "src/index.ts must stay dependency-free"
    assert "xmuse.server" in text


def test_no_markdown_commands() -> None:
    stray = sorted((PLUGIN_ROOT / "src").rglob("*.md"))
    assert not stray, f"markdown command files are not allowed: {stray}"
    assert not (PLUGIN_ROOT / "commands").exists(), "commands/ dir is not allowed"


def test_tui_pragma_first_line() -> None:
    first = (PLUGIN_ROOT / "src" / "tui.tsx").read_text(encoding="utf-8").splitlines()[0]
    assert first == "/** @jsxImportSource @opentui/solid */", f"bad first line: {first!r}"


def test_package_manifest() -> None:
    manifest = json.loads((PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "xmuse"
    assert "@opencode/plugin" in manifest.get("dependencies", {}), "missing @opencode/plugin dep"
    exports = manifest.get("exports", {})
    assert "./tui" in exports, f"missing ./tui export: {exports}"
    assert "." in exports, f"missing . export: {exports}"
    server_entry = exports["."]
    assert isinstance(server_entry, str) and server_entry.endswith("index.ts")


def test_bun_suite() -> None:
    bun = shutil.which("bun")
    if bun is None:
        pytest.skip("bun is not on PATH; cannot run the OpenCode plugin suite")
    proc = subprocess.run(
        [bun, "test"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"bun test failed:\n{proc.stdout}\n{proc.stderr}"


def test_never_fetch_integration_detail() -> None:
    violations: list[str] = []
    for path in _plugin_sources():
        text = path.read_text(encoding="utf-8")
        if "board/integrations" in text:
            violations.append(str(path.relative_to(PLUGIN_ROOT)))
    assert not violations, "§5.3 route referenced in plugin source:\n" + "\n".join(violations)


def test_integration_vocabulary_matches_claude_mod() -> None:
    claude_labels = (CLAUDE_ROOT / "src" / "labels.ts").read_text(encoding="utf-8")
    opencode_labels = (PLUGIN_ROOT / "src" / "core" / "labels.ts").read_text(encoding="utf-8")
    # Generated core cannot drift: sync_core.py already asserts byte equality,
    # but the vocabulary itself must contain the fixed words.
    assert (
        opencode_labels == claude_labels.replace('"../types/index"', '"./types"')
        or opencode_labels.replace('"./types"', '"../types/index"') == claude_labels
    )
    for needle in (
        "排队集成",
        "集成中",
        "已集成",
        "等待依赖集成",
        "门禁失败·嫌疑",
        "集成异常·自动重试",
        "分支为旧版本",
        "未入分支",
        "集成异常（宿主自动重试）",
        "集成冲突待处理",
        "集成门禁失败",
    ):
        assert needle in opencode_labels, f"src/core/labels.ts missing {needle!r}"
