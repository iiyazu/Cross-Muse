"""The two seams other modules hook into: memoryos.Client's observer plus the cause context, and otel's span sources.
With no observer and no extra source the hub behaves exactly as before; these tests pin what a hook sees."""
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fakes.fake_memoryos import FakeMemoryOS
from xmuse import db, memoryos, otel


class Server:
    """/health, /ok (an object), /list (a JSON array), /garbage (not JSON), /500, /404, /slow; records headers."""

    def __init__(self):
        self.headers = []
        srv = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.do_POST()

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length") or 0))
                srv.headers.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                code, raw = {"/health": (200, b'{"capabilities": ["recall"]}'), "/ok": (200, b'{"ok": 1}'),
                             "/list": (200, b"[1]"), "/garbage": (200, b"<html>"), "/500": (500, b"{}"),
                             "/404": (404, b"{}")}.get(self.path, (200, b"{}"))
                if self.path == "/slow":
                    time.sleep(1)
                self.send_response(code)
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        ThreadingHTTPServer.daemon_threads = True
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


class Recorder:
    def __init__(self, headers=None):
        self.started, self.ended, self.extra = [], [], headers

    def start(self, call):
        self.started.append(dict(call))
        call["mine"] = len(self.started)  # an observer may keep its own state on the call
        return self.extra

    def end(self, call, outcome):
        self.ended.append((dict(call), outcome))


@pytest.fixture
def srv():
    s = Server()
    yield s
    s.httpd.shutdown()


def test_observer_sees_every_call_with_its_cause_and_adds_headers(srv):
    rec = Recorder({"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"})
    c = memoryos.Client(srv.url, observer=rec)
    assert c.caps == {"recall"} and rec.started[0]["path"] == "/health" and rec.started[0]["cause"] is None
    with memoryos.Client.cause("turn", 7):
        assert c.call(None, "/ok", {"q": 1}) == {"ok": 1}
    call, outcome = rec.ended[-1]
    assert (call["cap"], call["path"], call["cause"], call["mine"]) == (None, "/ok", ("turn", 7), 2)
    assert set(outcome) == {"ok", "status", "error", "ms", "ended_at"}
    assert (outcome["ok"], outcome["status"], outcome["error"]) == (True, 200, None)
    assert isinstance(outcome["ms"], int) and call["started_at"] <= outcome["ended_at"]
    path, headers = srv.headers[-1]
    assert path == "/ok" and headers["traceparent"].startswith("00-111") and headers["content-type"] == "application/json"


def test_a_call_the_client_skips_is_not_observed(srv):
    rec = Recorder()
    c = memoryos.Client(srv.url, observer=rec)
    assert c.call("curate.collab", "/ok", {}) is None and len(rec.started) == len(rec.ended) == 1  # only /health


@pytest.mark.parametrize("path,status,error", [("/500", 500, "http_5xx"), ("/404", 404, "http_4xx"),
                                               ("/garbage", 200, "bad_json"), ("/list", 200, "bad_json"),
                                               ("/slow", None, "timeout")])
def test_failures_are_classified_and_their_text_is_not_kept(srv, path, status, error):
    rec = Recorder()
    c = memoryos.Client(srv.url, observer=rec)
    c.timeout = 0.3
    assert c.call(None, path, {}) is None
    _, outcome = rec.ended[-1]
    assert (outcome["ok"], outcome["status"], outcome["error"]) == (False, status, error)


def test_a_refused_connection_is_classified():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again before the call: nothing listens there
    rec = Recorder()
    memoryos.Client(f"http://127.0.0.1:{port}", observer=rec)
    assert rec.ended[0][1]["error"] == "refused" and rec.ended[0][1]["status"] is None


def test_an_observer_that_raises_changes_nothing(srv, caplog):
    class Broken:
        def start(self, call):
            raise RuntimeError("start")

        def end(self, call, outcome):
            raise RuntimeError("end")

    with caplog.at_level(logging.WARNING, "xmuse.memoryos"):
        c = memoryos.Client(srv.url, observer=Broken())
        assert c.caps == {"recall"} and c.call(None, "/ok", {}) == {"ok": 1}
    assert "memoryos observer start failed" in caplog.text and "memoryos observer end failed" in caplog.text
    assert "traceparent" not in srv.headers[-1][1]


def test_without_an_observer_the_request_is_unchanged(srv):
    c = memoryos.Client(srv.url)
    with memoryos.cause("turn", 1):
        c.call(None, "/ok", {"a": 1})
    assert set(srv.headers[-1][1]) == {"accept-encoding", "host", "user-agent", "content-type", "content-length", "connection"}


def test_cause_nests_resets_and_a_missing_id_means_none():
    assert memoryos._cause.get() is None
    with memoryos.cause("message", 4):
        with memoryos.cause("message", None):
            assert memoryos._cause.get() is None
        assert memoryos._cause.get() == ("message", 4)
    assert memoryos._cause.get() is None


# ---- the hub's call sites ----------------------------------------------------------------------------------------

@pytest.fixture
def fake():
    f = FakeMemoryOS(caps=("curate", "curate.collab", "recall", "audit"))
    yield f
    f.close()


def room(make, url, **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude")], memoryos_url=url, audit_poll_s=3600, **cfg)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1")
    h.hub.mo.observer = rec = Recorder()
    return h, rec


def say(h, agent, body, **kw):
    r = h.tool(agent, "xmuse_send", to="#g", body=body, **kw)
    assert "result" in r, r
    return r["result"]["id"]


def causes(rec, path):
    return [call["cause"] for call, _ in rec.ended if call["path"] == path]


def test_curate_calls_are_caused_by_the_last_message_of_the_window(make, fake):
    h, rec = room(make, fake.url)
    for i in range(8):
        h.send("#g", f"message {i}")
    h.hub.curator.join()
    assert causes(rec, "/curate") == [("message", 8)]


def test_an_audit_is_caused_by_the_message_that_superseded_the_entry(make, fake):
    h, rec = room(make, fake.url)
    say(h, "claude-1", "Amounts are integer cents everywhere.", kind="decision")
    say(h, "claude-2", "Done: the parser returns integer cents.")
    sup = say(h, "claude-1", "Amounts are decimal strings.", kind="decision", supersedes="E1")
    h.hub.auditor.run_pending()
    assert causes(rec, "/audit") == [("message", sup)]


def test_recall_while_building_a_wake_pack_is_caused_by_the_turn(make, fake):
    h, rec = room(make, fake.url, align_thread_cap=2)
    for body in ("parser rule", "lexer rule", "emitter rule", "cache rule"):
        say(h, "claude-1", body, kind="decision")
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=0 where id='claude-2'")
    say(h, "claude-1", "claude-2: fix the parser", mentions=["claude-2"])
    h.wait_quiet()
    turns = {("turn", r["id"]) for r in h.q("select id from turns where agent_id='claude-2'")}
    assert turns and set(causes(rec, "/recall")) & turns


# ---- span sources -------------------------------------------------------------------------------------------------

@pytest.fixture
def sources(monkeypatch):
    pytest.importorskip("opentelemetry.sdk.trace")
    monkeypatch.setattr(otel, "_SOURCES", list(otel._SOURCES))
    monkeypatch.setattr(otel, "_RESOURCE", {})


def test_a_registered_source_comes_after_the_built_in_ones_and_owns_its_marks(make, sources):
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import SpanKind

    h = make()
    h.send("claude-1", "hello")
    before = otel.spans(h.conn())
    seen = []

    def build(sc):
        seen.append((sc.since, sc.unmarked, sc.rid))
        return [ReadableSpan(name="extra", context=sc.ctx(1, 2), resource=sc.resource, attributes={"n": 5},
                             kind=SpanKind.CLIENT)]

    mark = lambda s: ("extra", str(s.attributes["n"])) if s.name == "extra" else None  # noqa: E731
    otel.register_source(build, mark)
    otel.register_source(build, mark)  # once only
    otel.register_resource({"openinference.project.name": "xmuse", "service.name": "not-this"})
    after = otel.spans(h.conn(), since=0.0)
    assert [s.to_json() for s in after[:-1]] != [] and [s.name for s in after[:-1]] == [s.name for s in before]
    assert after[-1].name == "extra" and seen[-1][:2] == (0.0, False) and len(after) == len(before) + 1
    assert otel.mark_key(after[-1]) == ("extra", "5") and otel.mark_key(after[0]) == otel.mark_key(before[0])
    res = after[0].resource.attributes
    assert res["openinference.project.name"] == "xmuse" and res["service.name"] == otel.SERVICE_NAME


def test_built_in_sources_and_marks_are_unchanged(make, sources):
    h = make()
    h.send("claude-1", "hello")
    got = otel.spans(h.conn())
    assert [s.name for s in got] and all(otel.mark_key(s) is not None for s in got)
    assert [b.__name__ for b, _ in otel._SOURCES] == ["_turn_spans", "_message_spans", "_approval_spans",
                                                       "_capped_spans"]
    assert "openinference.project.name" not in got[0].resource.attributes
    assert json.loads(got[0].to_json())["resource"]["attributes"]["service.name"] == otel.SERVICE_NAME
