"""Host-side checks for the Claude Code xmuse mod (no Claude needed).

Covers the hard rules that are statically verifiable:
- tools/sync_fixtures.py --check passes (generated fixtures are current);
- hooks/ and src/ use no forbidden engine calls, only GET outside the
  single pure grant writer, no operator token material, no write verbs
  except POST in src/grant_api.ts;
- the grant write paths, bearer header placement and ui-arg hygiene;
- the backend plugin_grant_v1 golden files validate against the plugin_grant/v1 schema;
- plugin.json / hooks.json / marketplace.json parse and agree on the name.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "integrations" / "claude-code"

GRANT_API = PLUGIN_ROOT / "src" / "grant_api.ts"
REGISTER = PLUGIN_ROOT / "hooks" / "register.tsx"
PANE = PLUGIN_ROOT / "src" / "pane.tsx"

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

# The full human-trigger ban: no model-, prompt-, session-, tool- or
# host-mediated path may exist beside the existing command/tool below.
FORBIDDEN_HUMAN_TRIGGER = [
    "$.prompt.",
    "$.session.",
    "$.model.",
    "$.process.",
    "$.fs.",
    "$.mcp.",
]

FORBIDDEN_TOKENS = [
    "X-XMuse-Operator-Token",
    "XMUSE_OPERATOR_TOKEN",
]

WRITE_VERBS = ["POST", "PUT", "DELETE"]

# The only write routes a plugin grant may touch (contract plugin_grant/v1
# §4). The decision route carries a dynamic split id, checked by prefix.
ALLOWED_GRANT_PATHS = {
    "/api/chat/plugin/grants/exchange",
    "/api/chat/plugin/grants/revoke",
}
DECISION_PREFIX = "/api/chat/plugin/board-splits/"
DECISION_SUFFIX = "/decision"


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
            if path.name == "grant_api.ts" and verb == "POST":
                continue  # the single pure grant writer; see below
            if f'"{verb}"' in text or f"'{verb}'" in text:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}: {verb}")
    assert not violations, "write verbs or operator token material:\n" + "\n".join(violations)


def test_writes_only_in_grant_api() -> None:
    """POST and the bearer header live only in src/grant_api.ts, and the
    header name is spelled in exactly one function there."""
    grant_text = GRANT_API.read_text(encoding="utf-8")
    assert '"POST"' in grant_text, "grant_api.ts must spell the write method"
    assert "Authorization" in grant_text, "grant_api.ts must spell the bearer header"
    assert grant_text.count("Authorization") == 1, "Authorization must appear exactly once"
    holder = grant_text.rfind("function ", 0, grant_text.index("Authorization"))
    assert holder != -1
    assert "pluginPost" in grant_text[holder : holder + 80]
    for path in _plugin_sources():
        if path == GRANT_API:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ('"POST"', "'POST'", "Authorization"):
            assert needle not in text, f"{path.relative_to(PLUGIN_ROOT)} must not spell {needle}"


def test_grant_api_allowed_paths() -> None:
    """The write paths allowed in grant_api.ts are exactly the exchange,
    revoke and decision routes; no operator or read routes may be added."""
    import re

    text = GRANT_API.read_text(encoding="utf-8")
    literals = set(re.findall(r'"/api/chat/[^"]*"', text))
    for lit in literals:
        inner = lit[1:-1]
        ok = inner in ALLOWED_GRANT_PATHS or inner == DECISION_PREFIX or inner == DECISION_SUFFIX
        assert ok, f"unexpected route literal in grant_api.ts: {lit}"
    assert "/api/chat/plugin/grants/exchange" in text
    assert "/api/chat/plugin/grants/revoke" in text
    assert DECISION_PREFIX in text and DECISION_SUFFIX in text
    for banned in ("/api/chat/operator", "/api/chat/rooms", "/board/summary"):
        assert banned not in text, f"grant_api.ts must not touch {banned}"
    for loopback in ("127", "localhost", "::1", "loopback"):
        assert loopback in text, "grant_api.ts must keep the loopback-only base URL rule"


def test_no_new_commands_tools_and_no_model_paths() -> None:
    """Writes stay human-triggered: no new command/tool registrations and
    no model/prompt/session/process/fs/mcp paths anywhere in the mod."""
    text = REGISTER.read_text(encoding="utf-8")
    assert text.count("$.command.register") == 1, "no new commands besides /xmuse"
    assert text.count("$.tool.register") == 1, "no new tools besides mcp__xmuse__status"
    assert "mcp__xmuse__status" in text
    assert "return { result: statusBlock(cache) }" in text
    assert '"xmuse 已解绑"' in text
    violations: list[str] = []
    for path in _plugin_sources():
        body = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_HUMAN_TRIGGER:
            if snippet in body:
                violations.append(f"{path.relative_to(PLUGIN_ROOT)}: {snippet}")
    assert not violations, "model-triggerable paths in mod source:\n" + "\n".join(violations)
    for fn in ("exchangeGrant", "decideSplit", "revokeGrant"):
        users = [
            str(p.relative_to(PLUGIN_ROOT))
            for p in _plugin_sources()
            if p != GRANT_API and fn in p.read_text(encoding="utf-8")
        ]
        assert users == ["hooks/register.tsx"], f"{fn} must run only from the hooks module: {users}"
    assert "onControl" in text and "onSubmit" in text
    pane_text = PANE.read_text(encoding="utf-8")
    assert "onPress" in pane_text and "onSubmit" in pane_text


def test_reviews_read_only_no_verdict_channel() -> None:
    """Reviews stay read-only in the mod: no review write route, no patch
    material route and no digest guard may be spelled outside the P3 split
    grant files (the split guard from P3 lives in grant_api.ts)."""
    allowed = {"src/grant_api.ts", "src/grant_state.ts"}
    violations: list[str] = []
    for path in _plugin_sources():
        rel = str(path.relative_to(PLUGIN_ROOT))
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("board-reviews", "/material", "expected_digest"):
            if needle in text:
                violations.append(f"{rel}: {needle}")
    assert not violations, "review write/material/digest material:\n" + "\n".join(violations)


def test_readme_documents_reviews_read_only() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        "Reviews are read-only here; verdicts belong to Room agents and the human in the Web"
        in readme
    ), "README missing the review read-only statement"
    for needle in (
        "待复核",
        "待你复核",
        "已背书",
        "已驳回",
        "已升级",
        "已验收",
        "已验证 · 待复核",
        "在 Web 复核",
        "阻塞",
        "复核被驳回待返工",
        "accepted_total",
    ):
        assert needle in readme, f"README missing review detail {needle!r}"


def test_secret_never_in_ui_args() -> None:
    """The pairing code and the token never reach a toast, status line,
    command/tool result or pane text: no such identifier may share the
    line with the call that renders it."""
    for path in (REGISTER, PANE):
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "ui.toast" in line or "ui.status" in line or "text:" in line:
                lowered = line.lower()
                for needle in ("secret", "pairing", "granttoken", "token"):
                    where = f"{path.relative_to(PLUGIN_ROOT)}:{lineno}"
                    assert needle not in lowered, f"{where}: {needle} in UI arg: {line.strip()}"


def test_grant_state_stays_pure() -> None:
    state = PLUGIN_ROOT / "src" / "grant_state.ts"
    text = state.read_text(encoding="utf-8")
    assert "$." not in text, "grant_state.ts must not touch the engine"
    assert "Authorization" not in text and '"POST"' not in text


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


def test_readme_documents_pairing_flow() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "配对码",
        "已授权",
        "撤销授权",
        "批准",
        "拒绝",
        "board.split.decide",
        "review verdicts",
        "no operator token",
        "memory only",
    ):
        assert needle in readme, f"README missing pairing detail {needle!r}"


def test_grant_fixtures_match_schema() -> None:
    import json

    from jsonschema import Draft202012Validator

    schema_path = REPO_ROOT / "docs" / "contracts" / "schemas" / "plugin_grant.v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    golden_dir = REPO_ROOT / "docs" / "contracts" / "fixtures" / "plugin_grant_v1"
    fixtures = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in golden_dir.glob("*.json")
    }
    for key in ("issue", "list", "exchange", "operator_revoke", "plugin_revoke"):
        assert key in fixtures, f"plugin_grant_v1 golden missing {key}"
        validator.validate(fixtures[key])
    assert fixtures["issue"]["grant"]["status"] == "pending"
    assert fixtures["exchange"]["grant"]["status"] == "active"
    generated = (PLUGIN_ROOT / "tests" / "grant_golden.generated.ts").read_text(encoding="utf-8")
    assert "GRANT_GOLDEN" in generated


def test_grant_ts_suite_covers_contract() -> None:
    suite = PLUGIN_ROOT / "tests" / "grant.test.ts"
    assert suite.is_file(), "tests/grant.test.ts missing"
    text = suite.read_text(encoding="utf-8")
    for needle in (
        "xmuse-pairing",
        "Origin",
        "401",
        "409",
        "detach",
        "revoke",
        "confirm",
        "digest",
        "grant_state",
        "grant_api",
    ):
        assert needle in text, f"tests/grant.test.ts missing coverage of {needle!r}"


def test_never_fetch_integration_detail() -> None:
    """Plugins, the CLI and the mod never call GET …/board/integrations/{id}."""
    violations: list[str] = []
    for path in _plugin_sources():
        text = path.read_text(encoding="utf-8")
        if "board/integrations" in text:
            violations.append(str(path.relative_to(PLUGIN_ROOT)))
    assert not violations, "§5.3 route referenced in mod source:\n" + "\n".join(violations)


def test_integration_vocabulary_matches_contract() -> None:
    labels = (PLUGIN_ROOT / "src" / "labels.ts").read_text(encoding="utf-8")
    for needle in (
        "排队集成",
        "集成中",
        "已集成",
        "等待依赖集成",
        "集成冲突 ",
        "门禁失败·嫌疑",
        "集成异常·自动重试",
        "分支为旧版本",
        "未入分支",
        "集成冲突",
        "集成门禁失败",
        "集成异常",
        "集成异常（宿主自动重试）",
        "集成冲突待处理",
        "集成门禁失败",
        "集成门禁未通过",
        "等待依赖集成",
        "集成会丢失已验收代码，已停止",
        "集成多次失败",
    ):
        assert needle in labels, f"src/labels.ts missing {needle!r}"
    pane_text = (PLUGIN_ROOT / "src" / "pane.tsx").read_text(encoding="utf-8")
    assert "集成分支" in pane_text
    api_text = (PLUGIN_ROOT / "src" / "api.ts").read_text(encoding="utf-8")
    for needle in ("integrations", "integrated_total", "integration_id", "conflict_path_count"):
        assert needle in api_text, f"src/api.ts missing {needle!r}"
    board_text = (PLUGIN_ROOT / "src" / "board_state.ts").read_text(encoding="utf-8")
    assert "集成 " in board_text
    pane_text = (PLUGIN_ROOT / "src" / "pane.tsx").read_text(encoding="utf-8")
    assert "roomIntegrationLine" in pane_text
    assert "integrationModuleWord" in pane_text
