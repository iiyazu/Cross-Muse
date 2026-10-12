"""Machine-local assistant registry (T8 H11): scan/trial/model/usable and the /v1/agents endpoints.

External commands are always faked (injected paths, versions and trial runners): no real agent runs here.
The registry dir is the per-test XMUSE_REGISTRY_DIR the conftest already points at a temp dir.
"""
import json

import pytest

from test_room import act, call, open_room
from test_trust import OC
from xmuse import agents, config
from xmuse.tools import ToolError


def regfile():
    return agents.path()


def test_scan_records_installed_missing_and_versions():
    out = agents.scan(paths={"opencode": "/x/oc", "dsh": None, "claude": "/x/claude"},
                      version_of=lambda p: "opencode 2.0.26" if p.endswith("/oc") else "")
    by = {e["vendor"]: e for e in out}
    assert (by["opencode"]["status"], by["opencode"]["version"]) == ("installed", "opencode 2.0.26")
    assert by["dsh"]["status"] == "missing" and by["dsh"]["path"] == ""
    assert by["claude"]["billing_note"] == agents.CLAUDE_BILLING_NOTE
    assert by["opencode"]["model"] == config.MODELS["opencode"]
    stored = json.loads(regfile().read_text(encoding="utf-8"))["agents"]
    assert {e["vendor"] for e in stored} == {"opencode", "dsh", "claude", "agy"}


def test_scan_keeps_model_and_ok_when_the_path_does_not_change():
    agents.scan(paths={"opencode": "/x/oc", "dsh": None, "claude": None}, version_of=lambda p: "v1")
    agents.set_model("opencode", "opencode-go/custom")
    agents.trial("opencode", run=lambda argv, cwd, timeout: (0, "OK"))
    first = {e["vendor"]: e for e in agents.entries()}
    assert first["opencode"]["status"] == "ok"
    second = {e["vendor"]: e
              for e in agents.scan(paths={"opencode": "/x/oc", "dsh": None, "claude": None},
                                   version_of=lambda p: "v2")}
    assert second["opencode"]["model"] == "opencode-go/custom"  # kept
    assert second["opencode"]["status"] == "ok"  # kept, with its check time
    assert second["opencode"]["checked_at"] == first["opencode"]["checked_at"]
    assert second["opencode"]["version"] == "v2"  # re-probed
    moved = {e["vendor"]: e
             for e in agents.scan(paths={"opencode": "/y/oc", "dsh": None, "claude": None},
                                  version_of=lambda p: "v3")}
    assert moved["opencode"]["status"] == "installed" and moved["opencode"]["version"] == "v3"


def test_trial_ok_failed_and_secret_free_detail():
    agents.scan(paths={"opencode": "/x/oc", "dsh": None, "claude": None}, version_of=lambda p: "")
    seen = {}

    def run(argv, cwd, timeout):
        seen["argv"] = argv
        return (0, "sure, OK")
    e = agents.trial("opencode", run=run)
    assert (e["status"], e["detail"]) == ("ok", "")
    assert seen["argv"][:4] == ["/x/oc", "run", "-m", config.MODELS["opencode"]]
    e = agents.trial("opencode", model="m/custom", run=lambda argv, cwd, timeout: (0, "OK"))
    assert (e["status"], e["model"]) == ("ok", "m/custom")
    e = agents.trial("opencode", run=lambda argv, cwd, timeout: (1, "API_KEY=zzz\nPATH=/x\nboom" * 50))
    assert e["status"] == "failed"
    assert len(e["detail"]) <= 300 and "zzz" not in e["detail"] and "PATH=" not in e["detail"]
    with pytest.raises(ToolError) as err:
        agents.trial("claude")
    assert err.value.code == "claude_billed"
    with pytest.raises(ToolError) as err:
        agents.trial("slack")
    assert err.value.code == "bad_vendor"
    with pytest.raises(ToolError) as err:
        agents.trial("dsh")
    assert err.value.code == "not_installed"  # no path scanned


def test_trial_dsh_without_a_runner_reports_unsupported():
    agents.scan(paths={"opencode": None, "dsh": "/x/dsh", "claude": None}, version_of=lambda p: "")
    e = agents.trial("dsh", dsh_run=None)
    assert (e["status"], e["detail"]) == ("installed", "trial unsupported")
    e = agents.trial("dsh", dsh_run=lambda agent, ws: "exit 1: no dsh here")
    assert e["status"] == "failed" and "exit 1" in e["detail"]
    e = agents.trial("dsh", dsh_run=lambda agent, ws: None)
    assert e["status"] == "ok"


def test_usable_excludes_claude_and_non_ok():
    agents.scan(paths={"opencode": "/x/oc", "dsh": "/x/dsh", "claude": "/x/claude"},
                version_of=lambda p: "")
    agents.trial("opencode", run=lambda argv, cwd, timeout: (0, "OK"))
    assert [e["vendor"] for e in agents.usable()] == ["opencode"]
    assert agents.default_model("opencode") == config.MODELS["opencode"]
    assert agents.default_model("dsh") == config.MODELS["dsh"]
    e = agents.set_model("opencode", "opencode-go/custom")
    assert (e["model"], e["status"]) == ("opencode-go/custom", "installed")  # back to installed: re-trial
    assert agents.default_model("opencode") == "opencode-go/custom"
    assert [e["vendor"] for e in agents.usable()] == []
    with pytest.raises(ToolError) as err:
        agents.set_model("slack", "x")
    assert err.value.code == "bad_vendor"
    with pytest.raises(ToolError) as err:
        agents.set_model("opencode", "  ")
    assert err.value.code == "bad_request"


def ag(h, method, path, body=None, key="K"):
    return call(h, method, path, body, None, None, key=key)


def test_agents_endpoints_need_the_sidebar_key_not_a_member_token(make):
    h = make()
    open_room(h)
    lead_tok = (h.state / "tokens" / "lead").read_text(encoding="utf-8").strip()
    st, out = ag(h, "GET", "/v1/agents")
    assert st == 401 and out["error"] == "bad_sidebar_key"
    assert ag(h, "GET", "/v1/agents", key="wrong")[0] == 401
    st, out = call(h, "GET", "/v1/agents", None, lead_tok, "S-lead", key=h.key())
    assert (st, out["error"]) == (403, "member_forbidden")
    assert ag(h, "POST", "/v1/agents/trial", {"vendor": "opencode"})[0] == 401


def test_agents_scan_trial_model_round_trip(make, monkeypatch):
    h = make()
    open_room(h)
    key = h.key()
    assert ag(h, "GET", "/v1/agents", key=key) == (200, {"agents": []})
    monkeypatch.setattr("xmuse.agents.cli_paths", lambda cfg: {"opencode": "/x/oc", "dsh": None, "claude": None})
    monkeypatch.setattr("xmuse.agents._version_of", lambda p, timeout=10: "opencode 9.9")
    st, out = ag(h, "POST", "/v1/agents/scan", None, key=key)
    assert st == 200 and [e["vendor"] for e in out["agents"]] == ["opencode", "dsh", "claude", "agy"]
    assert out["agents"][0]["version"] == "opencode 9.9"
    monkeypatch.setattr("xmuse.agents._run_cmd", lambda argv, cwd, timeout: (0, "OK"))
    st, out = ag(h, "POST", "/v1/agents/trial", {"vendor": "opencode"}, key=key)
    assert st == 200 and (out["status"], out["model"]) == ("ok", config.MODELS["opencode"])
    st, out = ag(h, "POST", "/v1/agents/trial", {"vendor": "claude"}, key=key)
    assert (st, out["error"]) == (400, "claude_billed")
    st, out = ag(h, "POST", "/v1/agents/trial", {"vendor": "dsh"}, key=key)
    assert (st, out["error"]) == (400, "not_installed")
    st, out = ag(h, "POST", "/v1/agents/model", {"vendor": "opencode", "model": "opencode-go/custom"}, key=key)
    assert st == 200 and (out["model"], out["status"]) == ("opencode-go/custom", "installed")
    st, out = ag(h, "POST", "/v1/agents/model", {"vendor": "slack", "model": "x"}, key=key)
    assert (st, out["error"]) == (400, "bad_vendor")
    assert ag(h, "POST", "/v1/agents/model", {"vendor": "opencode", "model": ""}, key=key)[0] == 400


def test_member_add_uses_the_registry_model_by_default(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    agents.set_model("opencode", "opencode-go/registry-model")
    st, out = act(h, ot, act="member_add", vendor="opencode", name="oc-reg")
    assert (st, out) == (200, {"member_id": "oc-reg"})
    assert h.q("select model from agents where id='oc-reg'")[0]["model"] == "opencode-go/registry-model"
