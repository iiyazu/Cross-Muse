"""Hub startup preflight: the host facts a unit needs, stale generated files rewritten, what cannot be fixed refused."""
import json
import subprocess

import pytest

from xmuse import cli, db, doctor, init as xinit, preflight


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


def test_host_env_gives_a_unit_what_the_shell_would(monkeypatch, tmp_path):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setattr(preflight, "_newest_interop", lambda: "/run/WSL/9_interop")
    env = preflight.host_env(tmp_path)
    assert env["WSL_DISTRO_NAME"] == "Ubuntu-24.04"
    assert env["WSL_INTEROP"] == "/run/WSL/9_interop"
    assert env["XMUSE_STATE"] == str(tmp_path) and env["PATH"]


def test_the_distro_falls_back_to_the_override(monkeypatch, tmp_path):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setenv("XMUSE_WSL_DISTRO", "Ubuntu-22.04")
    monkeypatch.setattr(preflight, "_newest_interop", lambda: None)
    env = preflight.host_env(tmp_path)
    assert env["WSL_DISTRO_NAME"] == "Ubuntu-22.04" and "WSL_INTEROP" not in env


def test_stale_member_config_is_rewritten_at_start(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "c1", "claude")
    mcp = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    mcp["mcpServers"]["xmuse"]["env"]["XMUSE_STATE"] = "/elsewhere"
    (ws / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
    checks, fixed = preflight.run(state)
    assert any(line.startswith("agent c1") for line in fixed)
    assert by_name(checks)["agent c1"].level == "ok"
    assert str(state) in (ws / ".mcp.json").read_text(encoding="utf-8")


def test_a_removed_member_is_not_checked_or_rewritten(ws):
    state = xinit.init(ws)
    xinit.add_agent(state, "c1", "claude")
    conn = db.connect(state / "hub.db")  # a removed member that shares the workspace root with c1 (a FAIL if counted)
    conn.execute("insert into agents(id, vendor, model, family, role, settings, token_digest, created_at, description,"
                 " removed, paused) values('c2','claude','opus','anthropic','','{}','x',0,'',1,1)")
    conn.close()
    before = (ws / ".mcp.json").read_bytes()
    checks, fixed = preflight.run(state)
    assert "agent c2" not in by_name(checks)
    assert by_name(checks)["instances"].level == "ok"  # one claude left in the directory
    assert not any("c2" in line for line in fixed)
    assert (ws / ".mcp.json").read_bytes() == before  # the shared file still carries c1's identity


def test_stale_workspace_files_are_regenerated_at_start(ws):
    state = xinit.init(ws)
    (ws / "AGENTS.md").write_text("# mine\n", encoding="utf-8")
    checks, fixed = preflight.run(state)
    assert any("workspace files" in line for line in fixed)
    assert by_name(checks)["AGENTS.md"].level == "ok"


def test_a_desktop_claude_needs_no_cli_in_the_distro(monkeypatch):
    monkeypatch.setattr(doctor, "cli_paths", lambda cfg: {"claude": None, "opencode": "/x", "dsh": None, "agy": None})
    assert by_name(doctor.vendor_clis({"claude"}, {}, headless=set()))["claude cli"].level == "warn"
    assert by_name(doctor.vendor_clis({"claude"}, {}, headless={"claude"}))["claude cli"].level == "FAIL"


def test_hub_start_refuses_a_fail_and_spawns_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "run", lambda st: ([doctor.Check("FAIL", "claude cli", "not found", "install")], []))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **kw: pytest.fail("the hub was spawned"))
    with pytest.raises(SystemExit, match="hub not started"):
        cli.hub_start(tmp_path)
