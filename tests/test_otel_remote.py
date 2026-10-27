"""otel_remote: MemoryOS calls as CLIENT spans under the turn or message that caused them, a traceparent pointing at
that span, and nothing at all while export is off."""
import importlib.util
import json
import logging
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fakes.fake_memoryos import FakeMemoryOS
from xmuse import db, memoryos, otel, otel_remote


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except ModuleNotFoundError:
        return False


needs_sdk = pytest.mark.skipif(not _has("opentelemetry.sdk"), reason="otel group not installed")
ON = {"enabled": True, "endpoint": "http://127.0.0.1:9", "interval": 3600}  # nothing listens; never Phoenix


class Server:
    """/health reports recall; /500 fails with a body that must never be stored; the rest answer {}."""

    def __init__(self):
        self.headers = []
        srv = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.do_POST()

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length") or 0))
                srv.headers.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                code, raw = {"/health": (200, b'{"capabilities": ["recall"]}'),
                             "/500": (500, b'{"error": "secret boom"}')}.get(self.path, (200, b"{}"))
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


@pytest.fixture
def srv():
    s = Server()
    yield s
    s.httpd.shutdown()


@pytest.fixture(autouse=True)
def resource(monkeypatch):
    monkeypatch.setattr(otel, "_RESOURCE", {})  # install() registers the project process-wide
    # the hub's own export thread ships nowhere and marks nothing: the tests export themselves
    monkeypatch.setattr(otel, "_otlp_exporter", lambda oc: type("Nowhere", (), {"export": lambda self, s: False})())


def room(make, url, otel_cfg=None, **cfg):
    h = make([("claude-1", "claude"), ("claude-2", "claude")], memoryos_url=url, audit_poll_s=3600,
             **({"otel": otel_cfg} if otel_cfg else {}), **cfg)
    h.hub.engine.drivers["claude"].headless.bin = "/bin/true"
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1")
    return h


def has_table(h):
    return h.conn().execute("select 1 from sqlite_master where name='mo_calls'").fetchone() is not None


def calls(h):
    return h.q("select * from mo_calls order by id")


def mo_spans(h, **kw):
    return [s for s in otel.spans(h.conn(), **kw) if s.name.startswith("xmuse.memoryos.call")]


def test_export_off_installs_nothing(make, srv):
    h = room(make, srv.url)
    assert h.hub.mo.observer is None and not has_table(h)
    assert h.hub.mo.call("recall", "/recall", {"q": 1}) == {}
    assert "traceparent" not in srv.headers[-1][1] and "openinference.project.name" not in otel._RESOURCE


def test_a_call_gets_a_row_and_a_traceparent_naming_its_span(make, srv):
    h = room(make, srv.url, ON)
    assert has_table(h) and otel._RESOURCE == {"openinference.project.name": "xmuse"}
    mid = h.send("#g", "hello")["id"]
    with memoryos.cause("message", mid):
        assert h.hub.mo.call("recall", "/recall", {"q": 1}) == {}
    [row] = calls(h)
    chain = h.q("select chain_id from messages where id=?", mid)[0]["chain_id"]
    assert (row["path"], row["cap"], row["cause_kind"], row["cause_id"], row["chain_id"]) == (
        "/recall", "recall", "message", mid, chain)
    assert (row["ok"], row["status"], row["error"], row["server"]) == (1, 200, None, srv.url[7:])
    assert row["started_at"] <= row["ended_at"] and isinstance(row["ms"], int)
    rid = otel._room(h.conn())["id"]
    trace, span = otel._trace_id(rid, chain), otel._span_id(rid, "mo_call", row["id"])
    assert srv.headers[-1][1]["traceparent"] == f"00-{trace:032x}-{span:016x}-01"


@needs_sdk
def test_the_span_hangs_under_its_cause_with_client_attributes(make, srv):
    from opentelemetry.trace import SpanKind, StatusCode
    h = room(make, srv.url, ON)
    mid = h.send("#g", "hello")["id"]
    with memoryos.cause("message", mid):
        h.hub.mo.call("recall", "/recall", {"q": 1})
    [s] = mo_spans(h)
    [msg] = [x for x in otel.spans(h.conn()) if x.attributes.get(otel.A_MSG_ID) == mid]
    tp = srv.headers[-1][1]["traceparent"].split("-")
    assert (f"{s.context.trace_id:032x}", f"{s.context.span_id:016x}") == (tp[1], tp[2])
    assert s.parent.span_id == msg.context.span_id and s.context.trace_id == msg.context.trace_id
    assert s.name == "xmuse.memoryos.call /recall" and s.kind == SpanKind.CLIENT and s.status.status_code == StatusCode.OK
    a = dict(s.attributes)
    assert a["http.request.method"] == "POST" and a["url.path"] == "/recall" and a["http.response.status_code"] == 200
    assert a["server.address"] == "127.0.0.1" and a["server.port"] == int(srv.url.rsplit(":", 1)[1])
    assert a["xmuse.memoryos.capability"] == "recall" and a["openinference.span.kind"] == "CHAIN"
    assert "error.type" not in a and otel.mark_key(s) == ("mo_call", str(a["xmuse.memoryos.call.id"]))
    assert s.resource.attributes["openinference.project.name"] == "xmuse"


@needs_sdk
def test_a_call_without_a_cause_is_its_own_root(make, srv):
    h = room(make, srv.url, ON)
    h.hub.mo.call("recall", "/recall", {"q": 1})
    [s] = mo_spans(h)
    [row] = calls(h)
    assert s.parent is None and row["cause_kind"] is None
    assert s.context.trace_id == otel_remote._own_trace(otel._room(h.conn())["id"], row["id"])
    assert srv.headers[-1][1]["traceparent"].split("-")[1] == f"{s.context.trace_id:032x}"


@needs_sdk
def test_a_failed_call_keeps_its_error_type_never_its_text(make, srv):
    from opentelemetry.trace import StatusCode
    h = room(make, srv.url, ON)
    assert h.hub.mo.call(None, "/500", {"q": 1}) is None
    [row] = calls(h)
    assert (row["ok"], row["status"], row["error"]) == (0, 500, "http_5xx")
    assert "boom" not in json.dumps(row)
    [s] = mo_spans(h)
    assert s.status.status_code == StatusCode.ERROR and s.attributes["error.type"] == "http_5xx"
    assert "boom" not in s.to_json()


@needs_sdk
def test_an_unfinished_call_is_not_exported_yet(make, srv):
    h = room(make, srv.url, ON)
    h.hub.mo.call("recall", "/recall", {"q": 1})
    h.conn().execute("update mo_calls set ended_at=null")
    assert mo_spans(h) == []


def test_a_broken_observer_never_breaks_the_call(make, srv, caplog):
    h = room(make, srv.url, ON)
    h.conn().execute("drop table mo_calls")
    with caplog.at_level(logging.WARNING, "xmuse.memoryos"):
        assert h.hub.mo.call("recall", "/recall", {"q": 1}) == {}
    assert "memoryos observer start failed" in caplog.text and "traceparent" not in srv.headers[-1][1]


# ---- causes from the real call sites -------------------------------------------------------------------------------

@pytest.fixture
def fake():
    f = FakeMemoryOS(caps=("curate", "curate.collab", "recall", "audit"))
    yield f
    f.close()


@needs_sdk
def test_wake_recall_hangs_under_the_turn(make, fake):
    h = room(make, fake.url, ON, align_thread_cap=2)
    for body in ("parser rule", "lexer rule", "emitter rule", "cache rule"):
        assert "result" in h.tool("claude-1", "xmuse_send", to="#g", body=body, kind="decision")
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=0 where id='claude-2'")
    h.tool("claude-1", "xmuse_send", to="#g", body="claude-2: fix the parser", mentions=["claude-2"])
    h.wait_quiet()
    turned = {r["id"]: r for r in calls(h) if r["cause_kind"] == "turn"}
    assert turned and {r["path"] for r in turned.values()} == {"/recall"}
    by_turn = {s.attributes[otel.A_TURN_ID]: s for s in otel.spans(h.conn()) if otel.A_TURN_ID in s.attributes}
    under = [s for s in mo_spans(h) if s.attributes["xmuse.memoryos.call.id"] in turned]
    assert under
    for s in under:
        t = by_turn[turned[s.attributes["xmuse.memoryos.call.id"]]["cause_id"]]
        assert (s.parent.span_id, s.context.trace_id) == (t.context.span_id, t.context.trace_id)


def test_curate_and_audit_rows_name_their_messages(make, fake):
    h = room(make, fake.url, ON)
    for i in range(8):
        h.send("#g", f"message {i}")
    h.hub.curator.join()
    say = lambda body, **kw: h.tool("claude-1", "xmuse_send", to="#g", body=body, **kw)["result"]["id"]  # noqa: E731
    say("Amounts are integer cents everywhere.", kind="decision")
    h.tool("claude-2", "xmuse_send", to="#g", body="Done: the parser returns integer cents.")
    sup = say("Amounts are decimal strings.", kind="decision", supersedes="E1")
    h.hub.auditor.run_pending()
    got = {(r["path"], r["cause_kind"], r["cause_id"]) for r in calls(h)}
    assert ("/curate", "message", 8) in got and ("/audit", "message", sup) in got


# ---- export, replay ------------------------------------------------------------------------------------------------

@needs_sdk
def test_realtime_export_marks_once_and_replay_agrees(make, srv, tmp_path, monkeypatch):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as _exp_mod
    h = room(make, srv.url, ON)
    mid = h.send("#g", "hello")["id"]
    with memoryos.cause("message", mid):
        h.hub.mo.call("recall", "/recall", {"q": 1})
    h.hub.mo.call("recall", "/recall", {"q": 2})
    mem = InMemorySpanExporter()
    otel.export_once(h.state, h.hub.cfg, exporter=mem)
    live = sorted(s.to_json() for s in mem.get_finished_spans() if s.name.startswith("xmuse.memoryos.call"))
    assert len(live) == 2 and otel.export_once(h.state, h.hub.cfg, exporter=InMemorySpanExporter())["exported"] == 0
    assert h.q("select count(*) n from otel_marks where kind='mo_call'")[0]["n"] == 2
    dst = tmp_path / "hub.db"
    src = h.conn()
    src.execute("pragma wal_checkpoint(full)")
    shutil.copy(h.state / "hub.db", dst)
    seen = []

    class Fake:
        def __init__(self, **kw):
            pass

        def export(self, spans):
            from opentelemetry.sdk.trace.export import SpanExportResult
            seen.extend(spans)
            return SpanExportResult.SUCCESS

    monkeypatch.setattr(_exp_mod, "OTLPSpanExporter", Fake)
    otel.replay(dst, "http://127.0.0.1:9")
    assert sorted(s.to_json() for s in seen if s.name.startswith("xmuse.memoryos.call")) == live


def test_replay_uses_the_shared_project_only_for_dbs_that_traced_calls(tmp_path):
    import sqlite3
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    sqlite3.connect(old).execute("create table messages(id integer)").connection.close()
    sqlite3.connect(new).execute(otel_remote.SCHEMA).connection.close()
    otel_remote.prepare_replay(old, {"otel": {"project": "p"}})
    assert otel._RESOURCE == {}
    otel_remote.prepare_replay(new, {"otel": {"project": "p"}})
    assert otel._RESOURCE == {"openinference.project.name": "p"}


def test_cli_replay_prepares_the_project(make, srv, monkeypatch):
    from xmuse import cli
    monkeypatch.setattr(otel, "replay", lambda dbfile, endpoint, **kw: {})
    h = room(make, srv.url, ON)
    otel._RESOURCE.clear()
    cli.main(["trace", "export", "--state", str(h.state), "--endpoint", "http://127.0.0.1:9"])
    assert otel._RESOURCE == {"openinference.project.name": "xmuse"}


def test_project_name_is_configurable(monkeypatch):
    assert otel_remote.project({}) == "xmuse"
    assert otel_remote.project({"otel": {"project": "mine"}}) == "mine"
    monkeypatch.setenv("XMUSE_OTEL_PROJECT", "env")
    assert otel_remote.project({}) == "env" and otel_remote.project({"otel": {"project": "mine"}}) == "mine"
