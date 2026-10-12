"""Stale opencode approvals: after a restart the request is gone on opencode's side. Approving must close the
card (expired), not drop the connection; startup expires every pending opencode approval at once."""
import io
import urllib.error

from test_room import act, call, open_room
from test_trust import OC


def add_approval(h, aid="per_9", agent="opencode-1"):
    with h.conn() as c:
        c.execute("insert into approvals(id, agent_id, vendor_session, action, resources, created_at)"
                  " values(?, ?, 'ses_old', 'shell', '[\"git push\"]', 0)", (aid, agent))


def failing(exc):
    def approve(*a, **k):
        raise exc
    return approve


def http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b""))


def state(h, aid):
    return h.q("select state, decision from approvals where id=?", aid)[0]


def test_404_from_opencode_expires_the_approval_with_a_dm_notice(make, monkeypatch):
    h = make(OC)
    add_approval(h)
    monkeypatch.setattr(h.hub.engine.drivers["opencode"], "approve", failing(http_error(404)))
    out = h.admin("approve", id="per_9", decision="once")
    assert out["result"] == {"ok": True, "expired": True}
    assert state(h, "per_9") == {"state": "decided", "decision": "expired"}
    assert any("per_9" in n["body"] and "已过期" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    # closed for good: the card is gone and a second click is an ordinary 'already decided'
    assert h.admin("approve", id="per_9", decision="once")["error"]["code"] == "invalid_arguments"


def test_unreachable_opencode_expires_too(make, monkeypatch):
    h = make(OC)
    drv = h.hub.engine.drivers["opencode"]
    for i, exc in enumerate([urllib.error.URLError("refused"), ConnectionResetError("reset"), TimeoutError("slow")]):
        add_approval(h, f"per_{i}")
        monkeypatch.setattr(drv, "approve", failing(exc))
        assert h.admin("approve", id=f"per_{i}", decision="reject")["result"] == {"ok": True, "expired": True}
        assert state(h, f"per_{i}")["decision"] == "expired"


def test_other_http_errors_answer_json_and_stay_pending(make, monkeypatch):
    h = make(OC)
    add_approval(h)
    monkeypatch.setattr(h.hub.engine.drivers["opencode"], "approve", failing(http_error(500)))
    out = h.admin("approve", id="per_9", decision="once")
    assert out["error"]["code"] == "approval_failed" and "500" in out["error"]["message"]
    assert state(h, "per_9") == {"state": "pending", "decision": None}


def test_sidebar_approve_reports_expired(make, monkeypatch):
    h = make(OC)
    ot = open_room(h)["operator_token"]
    add_approval(h)
    monkeypatch.setattr(h.hub.engine.drivers["opencode"], "approve", failing(http_error(404)))
    st, out = act(h, ot, act="approve", id="per_9", decision="once")
    assert (st, out) == (200, {"ok": True, "expired": True})
    assert state(h, "per_9")["decision"] == "expired"


def test_startup_expires_pending_opencode_approvals_but_not_shares(make):
    h = make(OC)
    add_approval(h, "per_1")
    add_approval(h, "per_2")
    with h.conn() as c:
        c.execute("update approvals set state='decided', decision='once' where id='per_2'")
    add_approval(h, "share:7", agent="opencode-1")
    assert h.hub.expire_stale_approvals() == 1  # what Hub.__init__ does on every start
    assert state(h, "per_1") == {"state": "decided", "decision": "expired"}
    assert state(h, "per_2")["decision"] == "once"
    assert state(h, "share:7")["state"] == "pending"


def test_unexpected_handler_errors_answer_500_json(make, monkeypatch):
    h = make(OC)
    ot = open_room(h)["operator_token"]
    monkeypatch.setattr(type(h.hub), "act_pause", lambda self, p, b: (_ for _ in ()).throw(OSError("disk")))
    st, out = act(h, ot, act="pause", member="opencode-1")
    assert st == 500 and out["error"] == "internal_error" and "OSError" in out["message"]
    monkeypatch.setattr(type(h.hub), "admin_pause", lambda self, b: (_ for _ in ()).throw(OSError("disk")), raising=False)
    monkeypatch.setattr(type(h.hub), "route", lambda self, *a, **k: (_ for _ in ()).throw(OSError("disk")))
    r = h.post("/v1/admin/stop", {}, h.token("human"))
    assert r["error"]["code"] == "internal_error"
