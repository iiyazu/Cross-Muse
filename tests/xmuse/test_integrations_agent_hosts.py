"""Host-side checks for the agy plugin and the dsh package (no hosts needed).

Covers the new ``xmuse-ctl hook`` subcommand against the same fake
loopback server the xmuse-ctl tests use, plus static checks over the
``integrations/agy`` and ``integrations/dsh`` package files: only
structured fields may reach a model, never agent-authored text.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import stat
import sys
import threading
import unicodedata
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import test_integrations_xmuse_ctl as ctl_test
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CTL_ROOT = REPO_ROOT / "integrations" / "xmuse-ctl"
PKG_ROOT = CTL_ROOT / "xmuse_ctl"
CTL_README = CTL_ROOT / "README.md"
AGY_ROOT = REPO_ROOT / "integrations" / "agy"
DSH_ROOT = REPO_ROOT / "integrations" / "dsh"
AGY_SKILL = AGY_ROOT / "skills" / "xmuse-board" / "SKILL.md"
DSH_SKILL = DSH_ROOT / "skills" / "xmuse-board" / "SKILL.md"
FIXTURE_DIR = REPO_ROOT / "docs" / "contracts" / "fixtures" / "board_v2"

sys.path.insert(0, str(CTL_ROOT))

from xmuse_ctl import binding as ctl_binding  # noqa: E402
from xmuse_ctl import cli as ctl_cli  # noqa: E402
from xmuse_ctl import hook as ctl_hook  # noqa: E402

EXPECTED_SCENARIOS = ctl_test.EXPECTED_SCENARIOS


@pytest.fixture()
def hook_server() -> object:
    state = ctl_test._build_state()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ctl_test._make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    info = {"base": f"http://127.0.0.1:{httpd.server_port}", "state": state, "httpd": httpd}
    yield info
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=10)


def _room_id(stem: str) -> str:
    return "conv-" + stem.replace("_", "-")


def _run_hook(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    argv: list[str],
    stdin_data: str,
    cwd: Path,
    xdg: Path,
    api_base: str | None = None,
) -> tuple[int, str, str]:
    assert isinstance(server, dict)
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg / "state"))
    monkeypatch.setenv("XMUSE_API_BASE", api_base or str(server["base"]))
    monkeypatch.delenv("XMUSE_WEB_BASE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))
    code = ctl_cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def _bind(xdg: Path, cwd: Path, room_id: str) -> None:
    config_home = xdg / "config"
    old = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(config_home)
    try:
        stored = ctl_binding.load_bindings()
        stored[str(cwd)] = room_id
        ctl_binding.save_bindings(stored)
    finally:
        if old is None:
            del os.environ["XDG_CONFIG_HOME"]
        else:
            os.environ["XDG_CONFIG_HOME"] = old


def _payload(room_stem: str, host: str, work: Path) -> str:
    if host == "agy":
        return json.dumps({"workspacePaths": [str(work)]})
    return json.dumps({"cwd": str(work), "session_id": "sess-1", "hook_event_name": "x"})


def test_hook_agy_emits_operator_pending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("review_operator_pending"))
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", "agy"],
        _payload("review_operator_pending", "agy", work),
        tmp_path,
        xdg,
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    line = payload["injectSteps"][0]["ephemeralMessage"]
    assert set(payload.keys()) == {"injectSteps"}
    assert line.startswith("[xmuse] ")
    assert "待你复核" in line
    assert "beta" in line
    assert len(line) <= 300


def test_hook_dsh_emits_split_pending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("split_pending"))
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", "dsh", "--event", "SessionStart"],
        _payload("split_pending", "dsh", work),
        tmp_path,
        xdg,
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert set(payload.keys()) == {"hookSpecificOutput"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    line = payload["hookSpecificOutput"]["additionalContext"]
    assert line.startswith("[xmuse] ")
    assert "待审批拆分" in line
    assert "split_00000000000000000000000000000018" in line
    assert len(line) <= 300


def test_hook_dsh_default_event_is_user_prompt_submit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("review_operator_pending"))
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", "dsh"],
        _payload("review_operator_pending", "dsh", work),
        tmp_path,
        xdg,
    )
    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


@pytest.mark.parametrize("host", ["agy", "dsh"])
def test_hook_quiet_room_without_operator_items(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
    host: str,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("verified"))
    event = ["--event", "SessionStart"] if host == "dsh" else []
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", host, *event],
        _payload("verified", host, work),
        tmp_path,
        xdg,
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


@pytest.mark.parametrize("host", ["agy", "dsh"])
def test_hook_unbound_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
    host: str,
) -> None:
    xdg = tmp_path / "xdg"
    code, out, err = _run_hook(
        monkeypatch, capsys, hook_server, ["hook", "--host", host], "{}", tmp_path, xdg
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


@pytest.mark.parametrize("host", ["agy", "dsh"])
def test_hook_offline_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
    host: str,
) -> None:
    import socket as _socket

    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("review_operator_pending"))
    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    finally:
        probe.close()
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", host],
        _payload("review_operator_pending", host, work),
        tmp_path,
        xdg,
        api_base=f"http://127.0.0.1:{port}",
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


@pytest.mark.parametrize("host", ["agy", "dsh"])
@pytest.mark.parametrize("stdin_data", ["not json{{{", "", "[1, 2]", "x" * 65537])
def test_hook_bad_stdin_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
    host: str,
    stdin_data: str,
) -> None:
    # Malformed or oversized stdin counts as {}: no directory hints, and
    # the process cwd is unbound, so there is nothing to say.
    xdg = tmp_path / "xdg"
    code, out, err = _run_hook(
        monkeypatch, capsys, hook_server, ["hook", "--host", host], stdin_data, tmp_path, xdg
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


def test_hook_unknown_event_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("review_operator_pending"))
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", "dsh", "--event", "Nope"],
        _payload("review_operator_pending", "dsh", work),
        tmp_path,
        xdg,
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


def test_hook_unknown_host_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    xdg = tmp_path / "xdg"
    code, out, err = _run_hook(
        monkeypatch, capsys, hook_server, ["hook", "--host", "nope"], "{}", tmp_path, xdg
    )
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


def test_hook_refused_base_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("review_operator_pending"))
    code, out, err = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", "agy", "--api-base", "http://example.com"],
        _payload("review_operator_pending", "agy", work),
        tmp_path,
        xdg,
    )
    # Unlike other commands (exit 2), the hook stays silent and exits 0.
    assert code == 0
    assert err == ""
    assert json.loads(out) == {}


def test_hook_rate_limit_and_changed_signature(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    assert isinstance(hook_server, dict)
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    room_id = _room_id("review_operator_pending")
    _bind(xdg, work, room_id)
    stdin_data = _payload("review_operator_pending", "agy", work)
    clock = [1000.0]
    monkeypatch.setattr(ctl_hook.time, "time", lambda: clock[0])

    def call() -> dict[str, object]:
        code, out, err = _run_hook(
            monkeypatch,
            capsys,
            hook_server,
            ["hook", "--host", "agy"],
            stdin_data,
            tmp_path,
            xdg,
        )
        assert code == 0
        assert err == ""
        return json.loads(out)

    first = call()
    assert first != {}
    # Changed attention set but inside the window: still quiet.
    state = hook_server["state"]
    assert isinstance(state, dict)
    by_room = state["by_room"]
    assert isinstance(by_room, dict)
    entry = by_room[room_id]
    assert isinstance(entry, dict)
    summary = entry["summary"]
    assert isinstance(summary, dict)
    summary["attention"] = [
        {
            "kind": "operator",
            "reason_code": "board_attention_module_blocked",
            "module_id": "gamma",
            "split_id": None,
        }
    ]
    clock[0] += 10.0
    assert call() == {}
    # Changed set past the window: emits again with the new label.
    clock[0] += 25.0
    second = call()
    assert second != {}
    line = second["injectSteps"][0]["ephemeralMessage"]
    assert "模块已阻塞" in line
    assert "gamma" in line
    assert second != first
    # Same set again: quiet.
    clock[0] += 31.0
    assert call() == {}


def test_hook_announces_again_after_attention_cleared(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    assert isinstance(hook_server, dict)
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    room_id = _room_id("review_operator_pending")
    _bind(xdg, work, room_id)
    stdin_data = _payload("review_operator_pending", "agy", work)
    clock = [1000.0]
    monkeypatch.setattr(ctl_hook.time, "time", lambda: clock[0])

    def call() -> dict[str, object]:
        code, out, err = _run_hook(
            monkeypatch, capsys, hook_server, ["hook", "--host", "agy"], stdin_data, tmp_path, xdg
        )
        assert code == 0
        assert err == ""
        return json.loads(out)

    state = hook_server["state"]
    assert isinstance(state, dict)
    summary = state["by_room"][room_id]["summary"]
    original = list(summary["attention"])
    assert call() != {}
    clock[0] += 60.0
    assert call() == {}  # unchanged set: quiet
    # The operator handled everything: nothing to say, and the memory is dropped ...
    summary["attention"] = []
    clock[0] += 60.0
    assert call() == {}
    state_file = xdg / "state" / "xmuse-ctl" / "hook-state.json"
    assert room_id not in json.loads(state_file.read_text(encoding="utf-8"))
    # ... so the very same item showing up later is announced again.
    summary["attention"] = original
    clock[0] += 60.0
    assert call() != {}


def test_hook_does_not_wait_on_a_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

        def read(self, size: int | None = -1) -> str:
            raise AssertionError("must not read from a terminal")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(sys, "stdin", Terminal())
    assert ctl_cli.main(["hook", "--host", "agy"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == {}
    assert err == ""


def test_hook_state_file_permissions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id("review_operator_pending"))
    code, out, _ = _run_hook(
        monkeypatch,
        capsys,
        hook_server,
        ["hook", "--host", "agy"],
        _payload("review_operator_pending", "agy", work),
        tmp_path,
        xdg,
    )
    assert code == 0
    assert json.loads(out) != {}
    state_file = xdg / "state" / "xmuse-ctl" / "hook-state.json"
    assert state_file.is_file()
    assert stat.S_IMODE(os.stat(state_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(state_file.parent).st_mode) == 0o700
    stored = json.loads(state_file.read_text(encoding="utf-8"))
    assert set(stored.keys()) == {_room_id("review_operator_pending")}


def _clean(text: str) -> None:
    assert "\x1b" not in text
    for char in text:
        code = ord(char)
        assert char == "\n" or code >= 0x20, f"control character U+{code:04X}"
        assert not 0x80 <= code <= 0x9F, f"C1 character U+{code:04X}"
        assert unicodedata.category(char) != "Cf", f"format character U+{code:04X}"


@pytest.mark.parametrize("stem", EXPECTED_SCENARIOS)
def test_hook_never_emits_agent_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    hook_server: object,
    tmp_path: Path,
    stem: str,
) -> None:
    work = tmp_path / "proj"
    work.mkdir()
    xdg = tmp_path / "xdg"
    _bind(xdg, work, _room_id(stem))
    fixture = json.loads((FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    forbidden = ctl_test._agent_texts(fixture)
    for host in ("agy", "dsh"):
        event = ["--event", "SessionStart"] if host == "dsh" else []
        code, out, err = _run_hook(
            monkeypatch,
            capsys,
            hook_server,
            ["hook", "--host", host, *event],
            _payload(stem, host, work),
            tmp_path,
            xdg,
        )
        assert code == 0
        assert err == ""
        payload = json.loads(out)
        if payload == {}:
            continue
        if host == "agy":
            line = payload["injectSteps"][0]["ephemeralMessage"]
        else:
            line = payload["hookSpecificOutput"]["additionalContext"]
        assert len(line) <= 300
        _clean(line)
        for secret in forbidden:
            assert secret not in line, f"hook leaked agent text in {stem}"


def _package_sources() -> list[Path]:
    files = sorted(PKG_ROOT.glob("*.py"))
    assert files, "no xmuse_ctl sources found"
    assert (PKG_ROOT / "hook.py").is_file()
    return files


def test_hook_only_get_method() -> None:
    texts = {path: path.read_text(encoding="utf-8") for path in _package_sources()}
    assert any('"GET"' in text for text in texts.values())
    for path, text in texts.items():
        for needle in ('"POST"', '"PUT"', '"DELETE"', '"PATCH"'):
            assert needle not in text, f"{path.name} spells {needle}"


def test_hook_no_tokens_or_state_changing_names() -> None:
    for path in _package_sources():
        text = path.read_text(encoding="utf-8")
        for needle in ("Authorization", "XMUSE_OPERATOR_TOKEN", "Cookie"):
            assert needle not in text, f"{path.name} contains {needle}"


def test_hook_no_server_imports_and_no_process_spawn() -> None:
    for path in _package_sources():
        text = path.read_text(encoding="utf-8")
        assert "xmuse_core" not in text, f"{path.name} mentions xmuse_core"
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if re.match(r"import\s+xmuse\b", stripped) and "xmuse_ctl" not in stripped:
                raise AssertionError(f"{path.name}:{lineno}: server import")
            if re.match(r"from\s+xmuse\s+import", stripped):
                raise AssertionError(f"{path.name}:{lineno}: server import")
            if re.match(r"from\s+xmuse\.", stripped) and "xmuse_ctl" not in stripped:
                raise AssertionError(f"{path.name}:{lineno}: server import")
        assert "subprocess" not in text, f"{path.name} mentions subprocess"
        assert "os.system" not in text, f"{path.name} uses os.system"


def test_hook_stdlib_imports_only() -> None:
    import sys as _sys

    allowed = set(_sys.stdlib_module_names) | {"xmuse_ctl", "test_integrations_xmuse_ctl"}
    for path in _package_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in allowed, (
                        f"{path.name} imports non-stdlib {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level != 0:
                    continue
                root = (node.module or "").split(".")[0]
                assert root in allowed, f"{path.name} imports non-stdlib {node.module}"


def test_agy_plugin_json() -> None:
    path = AGY_ROOT / "plugin.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "name",
        "displayName",
        "description",
        "version",
        "suggestedPrompts",
        "logo",
        "disabled",
    }
    assert set(payload.keys()) <= allowed, f"unexpected keys: {set(payload.keys()) - allowed}"
    assert payload["name"] == "xmuse"
    assert re.fullmatch(r"[a-z][a-z0-9-]*", payload["name"])
    assert payload["displayName"] == "xmuse board"
    assert isinstance(payload["description"], str) and len(payload["description"]) > 0
    assert payload["version"] == "0.1.0"
    prompts = payload["suggestedPrompts"]
    assert isinstance(prompts, list) and 1 <= len(prompts) <= 3
    assert all(isinstance(entry, str) and entry != "" for entry in prompts)


def test_agy_hooks_json() -> None:
    payload = json.loads((AGY_ROOT / "hooks.json").read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"xmuse-status"}
    hook = payload["xmuse-status"]
    assert hook["enabled"] is False
    handlers = hook["PreInvocation"]
    assert isinstance(handlers, list) and len(handlers) == 1
    assert handlers[0] == {
        "type": "command",
        "command": "xmuse-ctl hook --host agy",
        "timeout": 5,
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "type" in value:
                assert value["type"] == "command"
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)


def test_dsh_hooks_json() -> None:
    payload = json.loads((DSH_ROOT / "hooks.claude.json").read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"hooks"}
    hooks = payload["hooks"]
    assert set(hooks.keys()) == {"UserPromptSubmit", "SessionStart"}
    expected = {
        "UserPromptSubmit": "xmuse-ctl hook --host dsh --event UserPromptSubmit",
        "SessionStart": "xmuse-ctl hook --host dsh --event SessionStart",
    }
    for event, command in expected.items():
        entries = hooks[event]
        assert isinstance(entries, list) and len(entries) == 1
        handlers = entries[0]["hooks"]
        assert isinstance(handlers, list) and len(handlers) == 1
        assert handlers[0] == {"type": "command", "command": command, "timeout": 5}


def test_dsh_cordis_example() -> None:
    text = (DSH_ROOT / "cordis.example.yml").read_text(encoding="utf-8")
    for needle in (
        "@deepseek-ai/dsh-hooks-claude-code",
        "configPath",
        "pluginRoot",
        "projectDir",
        "./integrations/dsh/hooks.claude.json",
    ):
        assert needle in text, f"cordis.example.yml missing {needle!r}"
    payload = yaml.safe_load(text)
    entries = payload["hooks"] if isinstance(payload, dict) else payload
    if isinstance(entries, dict):
        entries = [entries]
    found = False
    for entry in entries:
        if isinstance(entry, dict) and entry.get("name") == "@deepseek-ai/dsh-hooks-claude-code":
            config = entry.get("config")
            assert isinstance(config, dict)
            assert config.get("configPath") == "./integrations/dsh/hooks.claude.json"
            assert "pluginRoot" in config
            assert "projectDir" in config
            found = True
    assert found, "bridge entry missing"


def _read_skill_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} missing frontmatter"
    end = text.find("\n---\n", 4)
    assert end != -1, f"{path} missing frontmatter end"
    front = yaml.safe_load(text[4:end])
    assert isinstance(front, dict)
    return front, text[end + len("\n---\n") :]


def test_skills_identical_and_valid() -> None:
    agy_text = AGY_SKILL.read_text(encoding="utf-8")
    dsh_text = DSH_SKILL.read_text(encoding="utf-8")
    assert agy_text == dsh_text, "skill copies differ"
    front, body = _read_skill_frontmatter(AGY_SKILL)
    assert front.get("name") == "xmuse-board"
    assert re.fullmatch(r"[a-z][a-z0-9-]*", str(front.get("name")))
    description = front.get("description")
    assert isinstance(description, str) and len(description.strip()) > 0
    for needle in (
        "xmuse-ctl status",
        "xmuse-ctl board",
        "已验收",
        "Web",
        "XMUSE_OPERATOR_TOKEN",
    ):
        assert needle in body, f"SKILL.md missing {needle!r}"
    assert "不要" in body or "never" in body


def test_readmes_do_not_promise_writes() -> None:
    for path in (AGY_ROOT / "README.md", DSH_ROOT / "README.md"):
        text = path.read_text(encoding="utf-8")
        assert "Decisions stay in the Web" in text, f"{path} missing read-only line"
        for needle in ('"POST"', '"PUT"', '"DELETE"', '"PATCH"', "curl -X"):
            assert needle not in text, f"{path} hints at writes via {needle}"


def test_agy_readme_needles() -> None:
    readme = (AGY_ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "agy plugin install",
        "xmuse-ctl",
        "XMUSE_API_BASE",
        "XMUSE_WEB_BASE",
        "attach",
        "enabled",
        "xmuse-ctl hook --host agy",
        "never agent text",
        "Decisions stay in the Web",
        "agy plugin validate integrations/agy",
        "只读",
    ):
        assert needle in readme, f"agy README missing {needle!r}"


def test_dsh_readme_needles() -> None:
    readme = (DSH_ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        ".agents/skills",
        ".dsh/skills",
        "dsh-hooks-claude-code",
        "cordis.example.yml",
        "UserPromptSubmit",
        "SessionStart",
        "additionalContext",
        "developer preview",
        "Claude Code",
        "band",
        "xmuse-ctl",
        "attach",
        "never agent text",
        "Decisions stay in the Web",
        "只读",
    ):
        assert needle in readme, f"dsh README missing {needle!r}"


def test_ctl_readme_documents_hook() -> None:
    readme = CTL_README.read_text(encoding="utf-8")
    for needle in (
        "hook",
        "--host",
        "agy",
        "dsh",
        "[xmuse]",
        "hook-state.json",
        "XDG_STATE_HOME",
        "300",
        "30",
        "opt-in",
        "never injects agent text",
        "injectSteps",
        "hookSpecificOutput",
        "UserPromptSubmit",
        "SessionStart",
    ):
        assert needle in readme, f"xmuse-ctl README missing {needle!r}"
