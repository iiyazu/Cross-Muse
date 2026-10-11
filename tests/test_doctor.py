"""`xmuse doctor`: each main check finds its problem and names the fix; it never changes anything."""
import io
import json
import subprocess

import pytest

from conftest import wsl_hub

from xmuse import doctor, init as xinit


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    (tmp_path / "home").mkdir()
    w = tmp_path / "ws"
    w.mkdir()
    subprocess.run(["git", "init", "-q", str(w)], check=True)
    return w


def by_name(checks):
    return {c.name: c for c in checks}


def snapshot(ws):
    return {p: p.read_bytes() for p in ws.rglob("*") if p.is_file() and ".git/" not in str(p)}


def test_fresh_workspace_is_clean(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "c1", "claude")
    c = by_name(doctor.workspace(state))
    for name in ("tools.json", "skill", "AGENTS.md", "agent c1"):
        assert c[name].level == "ok", c[name]
    assert c["hub"].level == "warn" and "hub start" in c["hub"].fix


def test_stale_files_are_reported_with_the_fix_and_left_alone(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "c1", "claude")
    (ws / ".claude/skills/xmuse-collab/SKILL.md").write_text("old skill", encoding="utf-8")
    (ws / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
    mcp = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    mcp["mcpServers"]["xmuse"]["env"]["XMUSE_STATE"] = "/elsewhere"
    (ws / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
    (state / "hub.json").write_text(json.dumps({"pid": 99999999, "port": 1}), encoding="utf-8")
    before = snapshot(ws)
    c = by_name(doctor.workspace(state))
    assert c["skill"].level == "warn" and ".claude/skills" in c["skill"].detail and "xmuse init" in c["skill"].fix
    assert c["AGENTS.md"].level == "warn"
    assert c["agent c1"].level == "FAIL" and "another state dir" in c["agent c1"].detail
    assert "agent add c1 --vendor claude" in c["agent c1"].fix
    assert c["hub"].level == "FAIL" and "stale" in c["hub"].detail
    assert snapshot(ws) == before  # read-only
    out = io.StringIO()
    assert doctor.report(list(c.values()), out) == 1
    assert "fix: xmuse --ws" in out.getvalue()


def test_missing_toolchain(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert doctor.node_env()[0].level == "FAIL"
    c = by_name(doctor.vendor_clis({"opencode"}, {}))
    assert c["opencode cli"].level == "FAIL"  # a configured agent needs it
    assert c["claude cli"].level == "warn"    # merely absent


@wsl_hub
def test_dsh_needs_a_windows_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XMUSE_WIN_HOME")
    from xmuse import host
    monkeypatch.setattr(host, "_userprofile", lambda: None)
    assert by_name(doctor.vendor_clis({"dsh"}, {}))["dsh"].level == "FAIL"
    exe = tmp_path / "dsh.exe"
    exe.write_text("", encoding="utf-8")
    assert by_name(doctor.vendor_clis({"dsh"}, {"dsh_exe": str(exe)}))["dsh"].level == "ok"


def test_outside_a_workspace_only_warns(tmp_path, monkeypatch):
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert doctor.find_state(None) is None
    c = by_name(doctor.run(None))
    assert c["workspace"].level == "warn" and "xmuse init" in c["workspace"].fix
