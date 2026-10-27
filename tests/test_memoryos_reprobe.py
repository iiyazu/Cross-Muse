"""A MemoryOS that is unreachable when the hub starts (it started later, or was down) is picked up without a hub
restart: the client asks /health again at most every REPROBE_S, and the curator and auditor start their workers on
the first kick after their capability appears. One that answers with no capabilities stays disabled."""
import time

import pytest

from fakes.fake_memoryos import FakeMemoryOS
from xmuse import align, db, memoryos

DOWN = "http://127.0.0.1:1"  # nothing listens there
ALL = ("curate", "curate.collab", "recall", "audit")


@pytest.fixture
def mo():
    made = []

    def _mo(**kw):
        made.append(FakeMemoryOS(**kw))
        return made[-1]
    yield _mo
    for f in made:
        f.close()


def hub(make, url, **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude")], memoryos_url=url, audit_poll_s=3600, **cfg)
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1")  # nobody runs a turn: only the hub talks to MemoryOS
    return h


def decl(h, body, **kw):
    r = h.tool("claude-1", "xmuse_send", to="#g", body=body, kind="decision", **kw)
    assert "result" in r, r
    return r["result"]["id"]


def talk(h, n):
    for i in range(n):
        h.send("#g", f"message {i}")
    h.hub.curator.join()


def test_memoryos_that_comes_up_later_is_used_without_a_restart(make, mo, monkeypatch):
    monkeypatch.setattr(memoryos, "REPROBE_S", 0)
    h = hub(make, DOWN, align_thread_cap=2)
    assert h.hub.mo.caps == set() and not h.hub.curator.thread.is_alive() and not h.hub.auditor.thread.is_alive()
    for body in ("parser rule", "lexer rule", "emitter rule"):
        decl(h, body)
    r = h.tool("claude-2", "xmuse_send", to="#g", body="Done: the parser follows the parser rule.", mentions=[])
    assert "result" in r, r                   # someone else relied on E1 ...
    decl(h, "cache rule", supersedes="E1")  # ... and E1 is superseded while MemoryOS is down
    fake = mo(caps=ALL)
    h.hub.mo.url = fake.url  # it is up now (the fake picks its own port, so the client is pointed at it)
    view = align.view(h.conn(), h.hub.cfg, "claude-2", query="parser")
    assert h.hub.mo.caps == set(ALL) and fake.paths() == ["/recall"] and view["truncated"] == ["thread:#g"]
    talk(h, 8)
    assert h.hub.curator.thread.is_alive() and "/curate" in fake.paths()
    h.hub.auditor.kick()
    assert h.hub.auditor.thread.is_alive()
    h.hub.auditor.run_pending()
    [(path, req)] = [c for c in fake.calls if c[0] == "/audit"]
    assert (req["old"]["id"], req["new"]["id"]) == ("E1", "E4")  # what was superseded while it was down


def test_memoryos_that_answers_without_capabilities_stays_disabled(make, mo, monkeypatch):
    monkeypatch.setattr(memoryos, "REPROBE_S", 0)
    fake = mo(caps=())
    h = hub(make, fake.url, align_thread_cap=2)
    fake.caps = list(ALL)  # it would offer them now, but the hub only re-asks an unreachable MemoryOS
    for body in ("a rule", "b rule", "c rule"):
        decl(h, body)
    talk(h, 8)
    align.view(h.conn(), h.hub.cfg, "claude-2", query="rule")
    assert h.hub.mo.caps == set() and h.hub.mo.retry_at is None and fake.paths() == []


def test_an_unreachable_memoryos_is_asked_again_at_most_every_reprobe_interval(monkeypatch):
    c = memoryos.Client(DOWN)
    assert c.caps == set() and c.retry_at is not None and c.retry_at > time.monotonic() + memoryos.REPROBE_S - 5
    probes = []
    monkeypatch.setattr(c, "_probe", lambda: probes.append(1))
    assert not any(c.ready("recall") for _ in range(5)) and c.call("recall", "/recall", {}) is None
    assert probes == []                       # still inside the interval: nobody waits on a dead MemoryOS
    c.retry_at = time.monotonic() - 1
    c.ready("recall")
    assert probes == [1]


def test_no_worker_starts_after_shutdown(make, mo, monkeypatch):
    monkeypatch.setattr(memoryos, "REPROBE_S", 0)
    h = hub(make, DOWN)
    h.hub.curator.stop()
    h.hub.auditor.stop()
    h.hub.mo.url = mo(caps=ALL).url
    talk(h, 8)
    h.hub.auditor.kick()
    assert not h.hub.curator.thread.is_alive() and not h.hub.auditor.thread.is_alive()
