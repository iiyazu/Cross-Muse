"""T12: several agents of one vendor in one workspace, each with its own identity."""
import io
import json

from xmuse import doctor, init as xinit
from xmuse.adapters import dsh


def _records(h, aid):
    return [json.loads(x) for x in (h.state / "fake-oc" / f"{aid}.jsonl").open(encoding="utf-8")]


def test_two_opencode_instances_keep_their_identity(make):
    h = make([("oc-a", "opencode"), ("oc-b", "opencode")], _oc_serve=True)
    drv = h.hub.engine.drivers["opencode"]
    a, b = drv.servers["oc-a"], drv.servers["oc-b"]
    assert a.base != b.base and a.pw != b.pw and a.pw.read_text(encoding="utf-8") != b.pw.read_text(encoding="utf-8")  # own port, own password
    assert len(drv.prompts) == 2
    h.send("oc-a", "ping a", mentions=["oc-a"])
    h.send("oc-b", "ping b", mentions=["oc-b"])
    h.wait(lambda: len(h.q("select 1 from messages where body like 'hello from %'")) == 2, 30, "both replies")
    h.wait_quiet(30)
    for aid in ("oc-a", "oc-b"):
        rec = _records(h, aid)
        assert rec[0]["started"] == aid and rec[0]["shared_identity"] is False  # identity only from OPENCODE_CONFIG
        assert [r["for"] for r in rec if "prompt" in r] == [aid]  # each server only ran its own agent's turn
        who = next(r["result"] for r in rec if r.get("tool") == "xmuse_whoami")
        assert who["id"] == aid and {p["id"] for p in who["peers"]} == {"oc-a", "oc-b", "human"} - {aid}
    msgs = h.q("select sender, body from messages where body like 'hello from %' order by sender")
    assert [(m["sender"], m["body"]) for m in msgs] == [("oc-a", "hello from oc-a"), ("oc-b", "hello from oc-b")]
    turns = h.turns()
    assert sorted(t["agent_id"] for t in turns) == ["oc-a", "oc-b"] and all(t["state"] == "succeeded" for t in turns)
    use = {r["agent_id"]: r for r in h.q("select agent_id, count(*) n, sum(calls) calls from usage group by agent_id")}
    assert set(use) == {"oc-a", "oc-b"} and all(u["n"] == 1 and u["calls"] > 0 for u in use.values())
    sessions = {r["agent_id"]: r["vendor_session"] for r in h.q("select * from sessions")}
    # session ids are only unique per server (both fakes start at ses_fake1): approvals route by agent
    assert drv.server_for(sessions["oc-a"], "oc-a") is a and drv.server_for(sessions["oc-b"], "oc-b") is b
    assert str(a.base) in h.admin("attach", agent="oc-a")["result"]["command"]


def test_approval_goes_to_the_asking_instance(make):
    h = make([("oc-a", "opencode"), ("oc-b", "opencode")], _oc_serve=True)
    h.send("oc-b", "ping b", mentions=["oc-b"])
    h.wait_quiet(30)
    sid = h.q("select vendor_session from sessions where agent_id='oc-b'")[0]["vendor_session"]
    drv = h.hub.engine.drivers["opencode"]
    calls = []
    for aid, srv in drv.servers.items():
        srv.api = (lambda aid: lambda m, p, body=None: calls.append((aid, p)))(aid)
    with h.conn() as c:  # what the engine records on permission.asked
        c.execute("insert into approvals(id, agent_id, vendor_session, action, resources, created_at)"
                  " values('per_9', 'oc-b', ?, 'shell', '[\"git push\"]', 0)", (sid,))
    assert h.admin("approve", id="per_9", decision="reject")["result"] == {"ok": True}
    assert calls == [("oc-b", f"/api/session/{sid}/permission/per_9/reply")]
    drv.approve(sid, "per_10", "once")  # no agent given: the listener that saw the session
    assert calls[-1] == ("oc-b", f"/api/session/{sid}/permission/per_10/reply")


def test_registering_several_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(xinit, "_dsh_ws_ok", lambda ws: True)  # dsh wants /mnt/<drive>/
    ws = tmp_path / "ws"
    ws.mkdir()
    state = xinit.init(ws)
    for aid, vendor in (("oc-a", "opencode"), ("oc-b", "opencode"), ("ds-a", "dsh"), ("ds-b", "dsh"),
                        ("claude-1", "claude")):
        xinit.add_agent(state, aid, vendor)
    shared = (ws / "opencode.json").read_text(encoding="utf-8")
    assert "XMUSE_AGENT" not in shared and "mcp" not in json.loads(shared)
    for aid in ("oc-a", "oc-b"):
        env = json.loads((state / "oc" / aid / "opencode.json").read_text(encoding="utf-8"))["mcp"]["servers"]["xmuse"]["environment"]
        assert env == {"XMUSE_STATE": str(state), "XMUSE_AGENT": aid}
    assert dsh.hooks_owner(ws) == "ds-a"  # one hooks.json: desktop presence follows the first dsh agent
    xinit.add_agent(state, "ds-b", "dsh", model="opencode-go/deepseek-v4.1-flash")  # re-add keeps the owner
    assert dsh.hooks_owner(ws) == "ds-a"
    patch_a = json.loads(dsh.overlay({"id": "ds-a", "model": "deepseek/deepseek-chat"}, state))
    patch_b = json.loads(dsh.overlay({"id": "ds-b", "model": "deepseek/deepseek-chat"}, state))
    env_of = lambda p: next(r for r in p if "insert" in r)["insert"][0]["config"]["env"]["XMUSE_AGENT"]  # noqa: E731
    assert (env_of(patch_a), env_of(patch_b)) == ("ds-a", "ds-b")  # headless identity is per run
    try:
        xinit.add_agent(state, "claude-2", "claude")
        raise AssertionError("second claude agent accepted")
    except SystemExit as e:
        assert "already has a claude agent" in str(e)

    checks = {c.name: c for c in doctor.workspace(state)}
    assert checks["instances"].level == "ok"
    assert checks["instances"].detail == ("claude x1 (claude-1), dsh x2 (ds-a, ds-b), opencode x2 (oc-a, oc-b)")
    for aid in ("oc-a", "oc-b", "ds-a", "ds-b"):
        assert checks[f"agent {aid}"].level == "ok", checks[f"agent {aid}"]
    assert "belong to ds-a" in checks["agent ds-b"].detail
    # a workspace opencode.json that names an agent (pre-T12 layout) fails every instance
    (ws / "opencode.json").write_text(json.dumps({"mcp": {"servers": {"xmuse": {"environment": {"XMUSE_AGENT": "oc-a"}}}}}), encoding="utf-8")
    (state / "oc" / "oc-b" / "opencode.json").write_text("{}", encoding="utf-8")
    checks = {c.name: c for c in doctor.workspace(state)}
    assert checks["agent oc-a"].level == "FAIL" and "carries an agent identity" in checks["agent oc-a"].detail
    assert "has no xmuse server" in checks["agent oc-b"].detail
    out = io.StringIO()
    assert doctor.report(list(checks.values()), out) == 1
