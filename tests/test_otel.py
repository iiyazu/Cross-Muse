"""OTel export, stage 1 (design docs/design/XMUSE2-OTEL.zh.md §6).

Mapping tests build rows directly (agents paused, no drivers run); behaviour
tests (restart, failure, disabled) go through the real engine/hub paths.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from xmuse import align, config, db, mail, otel
from xmuse import doctor as _doctor
from xmuse.engine import Engine


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except ModuleNotFoundError:  # a parent package is missing
        return False


# the optional `otel` group (uv sync --project hub --group otel): without it these skip, the rest still run
needs_sdk = pytest.mark.skipif(not (_has("opentelemetry.sdk") and _has("opentelemetry.exporter.otlp.proto.http")),
                               reason="otel group not installed")

T0 = 1700000000.0


def fresh(h, agents=(("e1", "claude"), ("e2", "opencode"))):
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1")
        c.execute("insert or ignore into room(id, name, dir, host, created_at) values('r1','t','/tmp',null,?)",
                  (T0,))


def chain(h, thread="g1", state="open", note=None):
    with db.tx(h.conn()) as c:
        cur = c.execute("insert into chains(thread_id, origin, state, max_wakes, max_tokens, note, created_at)"
                        " values(?, 'human', ?, 10, 1000000, ?, ?)", (thread, state, note, T0))
        return cur.lastrowid


def message(h, sender, thread, chain_id, turn_id=None, body="hello", kind="message", mentions=(), at=None,
            via=None):
    with db.tx(h.conn()) as c:
        cur = c.execute("insert into messages(thread_id, sender, kind, body, mentions, chain_id, depth, turn_id,"
                        " created_at, via) values(?,?,?,?,?,?,?,?,?,?)",
                        (thread, sender, kind, body, json.dumps(list(mentions)), chain_id, 0, turn_id, at or T0,
                         via))
        return cur.lastrowid


def deliver(h, mid, recipient, turn_id, wake=1, state="done"):
    with db.tx(h.conn()) as c:
        c.execute("insert into deliveries(message_id, recipient, wake, state, turn_id, updated_at)"
                  " values(?,?,?,?,?,?)", (mid, recipient, wake, state, turn_id, T0))


def turn(h, agent, chain_id, state="succeeded", err=None, adapter="headless", usage=None, t1=0.0, t2=1.0,
         fresh=0):
    with db.tx(h.conn()) as c:
        cur = c.execute("insert into turns(agent_id, adapter, chain_id, fresh, state, started_at, ended_at, error)"
                        " values(?,?,?,?,?,?,?,?)",
                        (agent, adapter, chain_id, fresh, state, T0 + t1,
                         T0 + t2 if state in otel.TERMINAL_TURNS else None, err))
        tid = cur.lastrowid
        if usage is not None:
            c.execute("insert into usage values(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, agent, usage.get("vendor", "claude"), usage.get("model", "m"),
                       usage.get("mode", "code"), usage.get("input", 0), usage.get("cache_read", 0),
                       usage.get("cache_write", 0), usage.get("output", 0), usage.get("context", 0),
                       usage.get("calls", 0), T0))
        return tid


def approve(h, aid, agent, created=2.0, decided=5.0, decision="once", action="shell"):
    with db.tx(h.conn()) as c:
        c.execute("insert into approvals(id, agent_id, action, resources, state, decision, created_at, decided_at)"
                  " values(?,?,?,?,?,?,?,?)",
                  (aid, agent, action, '["x"]', "decided", decision, T0 + created, T0 + decided))


def by_name(spans):
    return {s.name: s for s in spans}


def by_msg(spans, mid):
    return [s for s in spans if s.attributes.get("xmuse.message.id") == mid][0]


AGENTS2 = (("e1", "claude"), ("e2", "opencode"))


@pytest.fixture(autouse=True)
def _no_otel_env(monkeypatch):
    """These tests set the export switches themselves: a shell that exports XMUSE_OTEL_ENABLED or
    OTEL_EXPORTER_OTLP_* (e.g. the export-on timing run of the full suite) must not leak in."""
    for k in ("XMUSE_OTEL_ENABLED", "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
              "OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_TRACES_HEADERS"):
        monkeypatch.delenv(k, raising=False)


def canon(spans):
    """Deterministic comparable form of a span set."""
    out = []
    for s in spans:
        attrs = []
        for k, v in sorted((s.attributes or {}).items()):
            attrs.append((k, tuple(v) if isinstance(v, list) else v))
        out.append((s.context.trace_id, s.context.span_id,
                    s.parent.span_id if s.parent else None,
                    sorted(x.context.span_id for x in (s.links or ())), s.name, tuple(attrs),
                    s.start_time, s.end_time, s.status.status_code.name,
                    (s.status.description or "")))
    return sorted(out)


# ---- 1. tree ---------------------------------------------------------------------------------

@needs_sdk
def test_tree_parent_links_and_ids(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, usage={"input": 10, "output": 5})
    deliver(h, m1, "e1", t1)
    m2 = message(h, "e1", "g1", c1, turn_id=t1, mentions=["e2"])
    t2 = turn(h, "e2", c1, usage={"input": 3, "output": 1})
    deliver(h, m2, "e2", t2)
    ss = by_name(otel.spans(h.conn()))
    trace = otel._trace_id("r1", c1)
    assert {s.context.trace_id for s in ss.values()} == {trace}
    assert ss["invoke_agent e1"].parent.span_id == otel._span_id("r1", "message", m1)
    assert by_msg(otel.spans(h.conn()), m1).parent is None  # the human's message is the trace root
    assert ss["invoke_agent e1"].context.span_id == otel._span_id("r1", "turn", t1)
    assert ss["invoke_agent e2"].parent.span_id == otel._span_id("r1", "message", m2)
    assert all(not s.links for s in ss.values())
    a = ss["invoke_agent e1"].attributes
    assert (a["gen_ai.operation.name"], a["gen_ai.agent.id"], a["gen_ai.provider.name"]) == \
        ("invoke_agent", "e1", "anthropic")
    assert a["openinference.span.kind"] == "AGENT"
    assert ss["xmuse.message message"].attributes["openinference.span.kind"] == "CHAIN"


# ---- 2. batch --------------------------------------------------------------------------------

@needs_sdk
def test_batch_first_message_is_parent_rest_are_links(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1, at=T0)
    m2 = message(h, "human", "g1", c1, at=T0 + 1)
    t1 = turn(h, "e1", c1, t1=2.0)
    deliver(h, m1, "e1", t1)
    deliver(h, m2, "e1", t1)
    t = by_name(otel.spans(h.conn()))["invoke_agent e1"]
    assert t.parent.span_id == otel._span_id("r1", "message", m1)
    assert [x.context.span_id for x in t.links] == [otel._span_id("r1", "message", m2)]
    assert t.attributes["xmuse.queue_wait_s"] == pytest.approx(2.0)


# ---- 3. cross-chain ----------------------------------------------------------------------------

@needs_sdk
def test_cross_chain_is_links_never_parents(make):
    h = make(AGENTS2)
    fresh(h)
    c1, c2 = chain(h), chain(h)
    m1 = message(h, "human", "g1", c1, at=T0)
    m2 = message(h, "human", "g2", c2, at=T0 + 1)
    t1 = turn(h, "e1", c1, t1=2.0)
    deliver(h, m1, "e1", t1)
    deliver(h, m2, "e1", t1)
    m3 = message(h, "e1", "g2", c2, turn_id=t1)  # sent from t1, but opens a new chain
    ss = otel.spans(h.conn())
    t = by_name(ss)["invoke_agent e1"]
    assert t.parent.span_id == otel._span_id("r1", "message", m1)
    assert [x.context.span_id for x in t.links] == [otel._span_id("r1", "message", m2)]
    assert t.context.trace_id == otel._trace_id("r1", c1) != otel._trace_id("r1", c2)
    m3s = [s for s in ss if s.attributes.get("xmuse.message.id") == m3][0]
    assert m3s.parent is None  # cross-chain: no parent across traces ...
    assert [x.context.span_id for x in m3s.links] == [t.context.span_id]  # ... only a link


@needs_sdk
def test_cross_chain_earliest_message_is_link_not_parent(make):
    """The parent is the earliest wake message on the turn's own chain, even when
    an earlier message from another chain was delivered into the same turn."""
    h = make(AGENTS2)
    fresh(h)
    c1, c2 = chain(h), chain(h)
    m1 = message(h, "human", "g2", c2, at=T0)  # earlier, but another chain
    m2 = message(h, "human", "g1", c1, at=T0 + 1)
    t1 = turn(h, "e1", c1, t1=2.0)
    deliver(h, m1, "e1", t1)
    deliver(h, m2, "e1", t1)
    t = by_name(otel.spans(h.conn()))["invoke_agent e1"]
    assert t.parent.span_id == otel._span_id("r1", "message", m2)
    assert [x.context.span_id for x in t.links] == [otel._span_id("r1", "message", m1)]


# ---- 4. determinism ------------------------------------------------------------------------------

@needs_sdk
def test_realtime_and_replay_agree(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, usage={"input": 7, "output": 2, "cache_read": 1, "cache_write": 1})
    deliver(h, m1, "e1", t1)
    approve(h, "ap1", "e1")
    first = canon(otel.spans(h.conn()))
    second = canon(otel.spans(h.conn()))  # a fresh connection: the replay path
    assert first == second and len(first) == 3


# ---- 5. restart ----------------------------------------------------------------------------------

@needs_sdk
def test_restart_marks_the_running_turn_failed_once(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, state="running")
    deliver(h, m1, "e1", t1, state="admitted")
    Engine._recover(SimpleNamespace(db=h.conn))  # the real recovery path
    ss = by_name(otel.spans(h.conn()))
    assert ss["invoke_agent e1"].status.status_code.name == "ERROR"
    assert ss["invoke_agent e1"].status.description == "hub restarted"
    assert canon(otel.spans(h.conn())) == canon(otel.spans(h.conn()))


@needs_sdk
def test_realtime_mid_turn_plus_post_turn_equals_replay(make):
    """True real-time export: a message sent mid-turn is exported at once (with
    its parent, though the turn is still running); after the turn ends the
    second batch only adds the turn span. Both batches together equal replay."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    cfg = {"otel": {"enabled": True}}
    t1 = turn(h, "e1", c1, state="running")
    m1 = message(h, "human", "g1", c1, turn_id=t1)
    deliver(h, m1, "e1", t1, state="admitted")
    first, second = InMemorySpanExporter(), InMemorySpanExporter()
    r1 = otel.export_once(h.state, cfg, exporter=first)
    assert r1["exported"] == 1  # the message; the running turn ships nothing yet
    (m1s,) = first.get_finished_spans()
    assert m1s.parent is not None and m1s.parent.span_id == otel._span_id("r1", "turn", t1)
    with db.tx(h.conn()) as c:  # the turn ends
        c.execute("update turns set state='succeeded', ended_at=? where id=?", (T0 + 1, t1))
        c.execute("insert into usage values(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (t1, "e1", "claude", "m", "code", 3, 0, 0, 1, 10, 1, T0))
    r2 = otel.export_once(h.state, cfg, exporter=second)
    assert r2["exported"] == 1 and second.get_finished_spans()[0].name == "invoke_agent e1"
    live = first.get_finished_spans() + second.get_finished_spans()
    assert canon(live) == canon(otel.spans(h.conn()))  # live batches == replay


@needs_sdk
def test_restart_exports_the_failed_turn_exactly_once(make):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    cfg = {"otel": {"enabled": True}}
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, state="running")
    deliver(h, m1, "e1", t1, state="admitted")
    assert otel.export_once(h.state, cfg, exporter=InMemorySpanExporter())["exported"] == 1
    Engine._recover(SimpleNamespace(db=h.conn))
    mem = InMemorySpanExporter()
    assert otel.export_once(h.state, cfg, exporter=mem)["exported"] == 1
    (failed,) = mem.get_finished_spans()
    assert failed.name == "invoke_agent e1" and failed.status.status_code.name == "ERROR"
    assert otel.export_once(h.state, cfg, exporter=InMemorySpanExporter())["exported"] == 0


@needs_sdk
def test_entry_events_keep_the_causing_op_across_replays(make):
    """A supersede later must not rewrite what the earlier message's span shows."""
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    conn = h.conn()
    m1 = message(h, "e1", "g1", c1)
    e1 = align.declare(conn, "e1", "g1", m1, "decision", "keep retries low", "global")
    before = {s.attributes.get("xmuse.message.id"): [e.attributes for e in s.events or ()]
              for s in otel.spans(h.conn())}
    assert before[m1] == [{"entry": f"E{e1}", "kind": "decision", "scope": "global", "op": "add"}]
    m2 = message(h, "e1", "g1", c1)
    e2 = align.declare(conn, "e1", "g1", m2, "decision", "keep retries lower", "global",
                       supersedes=f"E{e1}")
    after = {s.attributes.get("xmuse.message.id"): sorted(
        (e.attributes["entry"], e.attributes["op"]) for e in s.events or ())
        for s in otel.spans(h.conn())}
    assert after[m1] == [(f"E{e1}", "add")]  # unchanged by the later supersede
    assert after[m2] == [(f"E{e1}", "supersede"), (f"E{e2}", "add")]
    assert canon(otel.spans(h.conn())) == canon(otel.spans(h.conn()))


@needs_sdk
def test_entry_events_on_dbs_without_the_msg_column(make):
    """Experiment DBs predate entry_events.msg: add and supersede are still attributed, from the entries."""
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    conn = h.conn()
    m1 = message(h, "e1", "g1", c1)
    e1 = align.declare(conn, "e1", "g1", m1, "decision", "keep retries low", "global")
    m2 = message(h, "e1", "g1", c1)
    e2 = align.declare(conn, "e1", "g1", m2, "decision", "keep retries lower", "global", supersedes=f"E{e1}")
    with_col = canon(otel.spans(h.conn()))
    conn.execute("alter table entry_events drop column msg")
    got = {s.attributes.get("xmuse.message.id"): sorted(
        (e.attributes["entry"], e.attributes["op"]) for e in s.events or ()) for s in otel.spans(h.conn())}
    assert got[m1] == [(f"E{e1}", "add")]
    assert got[m2] == [(f"E{e1}", "supersede"), (f"E{e2}", "add")]
    assert canon(otel.spans(h.conn())) == with_col  # same spans with or without the column


# ---- 6. content ----------------------------------------------------------------------------------

@needs_sdk
def test_content_capture_keeps_unmarked_dms_private(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    with db.tx(h.conn()) as c:
        c.execute("insert into threads(id, kind, title, created_at) values('dm:e1+human','dm','',?)", (T0,))
        c.executemany("insert into thread_members(thread_id, member) values('dm:e1+human',?)",
                      [("e1",), ("human",)])
    priv = message(h, "human", "dm:e1+human", c1, body="s3cr3t")
    pub = message(h, "e1", "g1", c1, turn_id=None, body="hello all")
    off = {s.attributes.get("xmuse.message.id"): s for s in otel.spans(h.conn())}
    assert all("xmuse.message.body" not in s.attributes for s in off.values())
    on = {s.attributes.get("xmuse.message.id"): s for s in otel.spans(h.conn(), capture=True, body_clip=4)}
    assert on[pub].attributes["xmuse.message.body"] == "hell"
    assert "xmuse.message.body" not in on[priv].attributes
    from xmuse import share
    share.mark(h.conn(), priv)
    on = {s.attributes.get("xmuse.message.id"): s for s in otel.spans(h.conn(), capture=True)}
    assert on[priv].attributes["xmuse.message.body"] == "s3cr3t"


# ---- 7. disabled -----------------------------------------------------------------------------------

def test_disabled_imports_no_opentelemetry(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    script = ("import sys; sys.path.insert(0, %r);"
              "from xmuse import config, otel;"
              "bad = [m for m in sys.modules if m == 'opentelemetry' or m.startswith('opentelemetry.')];"
              "assert not bad, bad;"
              "r = otel.export_once(%r, dict(config.DEFAULTS));"
              "assert r == {'enabled': False, 'ok': True, 'exported': 0}, r;"
              "bad = [m for m in sys.modules if m == 'opentelemetry' or m.startswith('opentelemetry.')];"
              "assert not bad, bad; print('clean')" % (str(repo / "hub" / "src"), str(tmp_path / "nostate")))
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


# ---- 8. failure ------------------------------------------------------------------------------------

@needs_sdk
def test_failed_export_retries_without_touching_the_hub(make):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, usage={"input": 1, "output": 1})
    deliver(h, m1, "e1", t1)
    cfg = {**h.hub.cfg, "otel": {"enabled": True, "endpoint": "http://127.0.0.1:1", "headers": {},
                                 "capture_content": False, "body_clip": 2000, "interval": 3600}}
    r = otel.export_once(h.state, cfg)
    assert r["ok"] is False and r["exported"] == 0
    assert h.q("select * from otel_marks") == []  # nothing marked: the next kick retries
    mid = h.send("e1", "still works")["id"]  # the hub takes messages while the backend is down
    assert isinstance(mid, int) and mid > m1
    mem = InMemorySpanExporter()
    r = otel.export_once(h.state, cfg, exporter=mem)
    assert r["ok"] is True and r["exported"] == 3  # turn + 2 messages
    assert len(mem.get_finished_spans()) == 3
    assert otel.export_once(h.state, cfg, exporter=mem)["exported"] == 0  # marks dedup


# ---- 9. usage --------------------------------------------------------------------------------------

@needs_sdk
def test_token_totals_match_usage(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    rows = [("e1", {"input": 10, "cache_read": 4, "cache_write": 2, "output": 5}),
            ("e2", {"input": 100, "cache_read": 0, "cache_write": 0, "output": 50})]
    for i, (agent, u) in enumerate(rows):
        m = message(h, "human", "g1", c1, at=T0 + i)
        t = turn(h, agent, c1, usage=u, t1=float(i), t2=float(i) + 1)
        deliver(h, m, agent, t)
    total = sum(u["input"] + u["output"] for _, u in rows)
    got = sum(s.attributes["gen_ai.usage.input_tokens"] + s.attributes["gen_ai.usage.output_tokens"]
              for s in otel.spans(h.conn()) if s.name.startswith("invoke_agent"))
    assert got == total
    cached = [s for s in otel.spans(h.conn()) if s.name == "invoke_agent e1"][0].attributes
    assert (cached["gen_ai.usage.cache_read.input_tokens"],
            cached["gen_ai.usage.cache_creation.input_tokens"]) == (4, 2)


# ---- stage 2: replay, incremental export, env switch ---------------------------------------

def _copy_db(h, tmp_path, name="replay.db"):
    src = Path(h.state) / "hub.db"
    conn = h.conn()
    conn.execute("pragma wal_checkpoint(TRUNCATE)")
    conn.close()
    dst = tmp_path / name
    shutil.copy(src, dst)
    return dst


def _files_mtime(p):
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


@needs_sdk
def test_replay_derives_identical_spans_and_touches_nothing(make, tmp_path, monkeypatch):
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as _exp_mod
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, usage={"input": 4, "output": 2})
    deliver(h, m1, "e1", t1)
    dst = _copy_db(h, tmp_path)
    before = _files_mtime(dst)
    seen = {}

    class FakeExporter:
        def __init__(self, **kw):
            seen.update(kw)

        def export(self, spans):
            seen["spans"] = list(spans)
            from opentelemetry.sdk.trace.export import SpanExportResult
            return SpanExportResult.SUCCESS

    monkeypatch.setattr(_exp_mod, "OTLPSpanExporter", FakeExporter)
    out = otel.replay(dst, "http://phoenix:6006", headers={"Authorization": "Basic e"})
    assert (out["exported"], out["traces"], out["endpoint"]) == (2, 1, "http://phoenix:6006")
    assert canon(seen["spans"]) == canon(otel.spans(h.conn()))  # same mapping as real-time
    assert _files_mtime(dst) == before  # read-only: bytes untouched
    assert seen.get("headers") == {"Authorization": "Basic e"}  # passed through, never printed


def test_cli_replays_a_run_dir_without_config(make, tmp_path, monkeypatch, capsys):
    """`xmuse trace export --state <run dir>`: experiment run dirs hold hub.db but no config.json."""
    from xmuse import cli
    h = make(AGENTS2)
    fresh(h)
    run = tmp_path / "S1-X-11"
    run.mkdir()
    _copy_db(h, run, "hub.db")
    assert (run / "hub.db").exists() and not (run / "config.json").exists()
    calls = []
    monkeypatch.setattr(otel, "replay", lambda dbfile, endpoint, **kw: calls.append((dbfile, endpoint, kw)) or {})
    cli.main(["trace", "export", "--state", str(run), "--room-id", "S1-X-11", "--endpoint", "http://phoenix:6006"])
    (dbfile, endpoint, kw), = calls
    assert (dbfile, endpoint, kw["room"]) == (run / "hub.db", "http://phoenix:6006", ("S1-X-11", ""))


@needs_sdk
def test_replay_failure_raises_and_leaves_db_alone(make, tmp_path):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1)
    deliver(h, m1, "e1", t1)
    dst = _copy_db(h, tmp_path)
    before = _files_mtime(dst)
    with pytest.raises(RuntimeError):
        otel.replay(dst, "http://127.0.0.1:1")
    assert _files_mtime(dst) == before


@needs_sdk
def test_room_override_namespaces_roomless_dbs(make):
    """Two DBs with identical row ids but no room row must not share trace ids."""
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1)
    deliver(h, m1, "e1", t1)
    plain = canon(otel.spans(h.conn()))
    namespaced = canon(otel.spans(h.conn(), room=("S1-X-11", "probe")))
    assert namespaced == canon(otel.spans(h.conn(), room=("S1-X-11", "probe")))
    assert {s[0] for s in namespaced} != {s[0] for s in plain}  # distinct trace ids
    assert {s[1] for s in namespaced} != {s[1] for s in plain}  # distinct span ids
    assert sorted(s[4] for s in namespaced) == sorted(s[4] for s in plain)  # same names


def mark(h, *pairs):
    with db.tx(h.conn()) as c:
        otel.ensure_marks(c)
        c.executemany("insert or ignore into otel_marks values(?,?)", pairs)


@needs_sdk
def test_unmarked_avoids_rebuilding_exported_spans(make):
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1)
    deliver(h, m1, "e1", t1)
    approve(h, "ap1", "e1")
    assert len(otel.spans(h.conn())) == 3
    mark(h, ("turn", str(t1)), ("approval", "ap1"))
    rest = otel.spans(h.conn(), unmarked=True)
    assert [s.attributes.get("xmuse.message.id") for s in rest] == [m1]
    mark(h, ("message", str(m1)))
    assert otel.spans(h.conn(), unmarked=True) == []
    assert len(otel.spans(h.conn())) == 3  # replay ignores the marks


@needs_sdk
def test_export_once_scales_past_the_sqlite_variable_limit(make):
    """A long-lived room has more exported rows than SQLite takes variables in one query (32766)."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    cfg = {"otel": {"enabled": True}}
    m1 = message(h, "human", "g1", c1)
    assert otel.export_once(h.state, cfg, exporter=InMemorySpanExporter())["exported"] == 1
    mark(h, *[(kind, str(100000 + i)) for kind in ("message", "turn") for i in range(40000)])
    m2 = message(h, "human", "g1", c1)
    mem = InMemorySpanExporter()
    r = otel.export_once(h.state, cfg, exporter=mem)
    assert r == {"enabled": True, "ok": True, "exported": 1}
    assert [s.attributes.get("xmuse.message.id") for s in mem.get_finished_spans()] == [m2] != [m1]


def test_env_switch_enables_export_without_config_change(make, monkeypatch):
    h = make(AGENTS2)
    fresh(h)
    assert otel.otel_config(h.hub.cfg)["enabled"] is False
    monkeypatch.setenv("XMUSE_OTEL_ENABLED", "1")
    oc = otel.otel_config(h.hub.cfg)
    assert oc["enabled"] is True and oc["endpoint"] == "http://localhost:6006"


@needs_sdk
def test_spans_encode_to_otlp_protobuf(make):
    """The real OTLP protobuf encoder must accept every span (argument order, types)."""
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    h = make(AGENTS2)
    fresh(h)
    c1 = chain(h)
    m1 = message(h, "human", "g1", c1)
    t1 = turn(h, "e1", c1, usage={"input": 1, "output": 1})
    deliver(h, m1, "e1", t1)
    req = encode_spans(otel.spans(h.conn()))
    assert len(req.SerializePartialToString()) > 0


def test_attribute_names_match_locked_semconv():
    g = pytest.importorskip("opentelemetry.semconv._incubating.attributes.gen_ai_attributes")
    assert (otel.ATTR_OPERATION, otel.ATTR_AGENT_ID, otel.ATTR_AGENT_NAME, otel.ATTR_PROVIDER,
            otel.ATTR_REQUEST_MODEL, otel.ATTR_CONVERSATION_ID, otel.ATTR_USAGE_IN, otel.ATTR_USAGE_OUT,
            otel.ATTR_USAGE_CACHE_READ, otel.ATTR_USAGE_CACHE_WRITE) == \
        (g.GEN_AI_OPERATION_NAME, g.GEN_AI_AGENT_ID, g.GEN_AI_AGENT_NAME, g.GEN_AI_PROVIDER_NAME,
         g.GEN_AI_REQUEST_MODEL, g.GEN_AI_CONVERSATION_ID, g.GEN_AI_USAGE_INPUT_TOKENS,
         g.GEN_AI_USAGE_OUTPUT_TOKENS, g.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
         g.GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS)


def test_config_env_override_and_headers(monkeypatch, tmp_path):
    from xmuse import config as _config
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic%20abc%3D,k=v")
    # through the real config.load path: a config file without an otel section
    state = _config.state_dir_for(tmp_path / "ws")
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.json").write_text(json.dumps({"workspace": str(tmp_path / "ws")}), encoding="utf-8")
    oc = otel.otel_config(_config.load(state))
    assert oc["endpoint"] == "http://env:4318"
    assert oc["headers"] == {"Authorization": "Basic abc=", "k": "v"}
    oc = otel.otel_config({"otel": {"enabled": True, "endpoint": "http://cfg:6006"}})
    assert oc["endpoint"] == "http://cfg:6006"  # file config wins over env


@needs_sdk
def test_doctor_never_prints_secrets(make):
    h = make(AGENTS2)
    fresh(h)
    secret = "Basic s3cr3t-headers"
    cfg = {**h.hub.cfg, "otel": {"enabled": True, "endpoint": "http://127.0.0.1:1",
                                 "headers": {"Authorization": secret}}}
    checks = _doctor.otel_checks(cfg)
    assert [c.name for c in checks] == ["otel deps", "otel endpoint"]
    assert all(secret not in (c.detail + c.fix) for c in checks)
    assert _doctor.otel_checks(h.hub.cfg)[0].name == "otel"  # disabled by default


@needs_sdk
def test_engine_kick_wiring(make):
    h = make((("e1", "claude"),),
             otel={"enabled": True, "endpoint": "http://127.0.0.1:1", "headers": {},
                   "capture_content": False, "body_clip": 2000, "interval": 3600})
    assert h.hub.engine.otel_kick is not None and h.hub.otel._thread.is_alive()
    off = otel.Exporter(h.state, {"otel": {"enabled": False}})  # disabled: start is a no-op
    off.start()
    assert off._thread is None and off.oc["enabled"] is False


@needs_sdk
def test_export_thread_survives_its_passes(make, monkeypatch):
    """The background thread really runs export passes, and one that raises does not end it."""
    import threading
    h = make((("e1", "claude"),))
    calls, second = [], threading.Event()

    def fake(state, cfg, exporter=None):
        calls.append(state)
        if len(calls) == 1:
            raise RuntimeError("boom")
        second.set()
        return {"enabled": True, "ok": True, "exported": 0}

    monkeypatch.setattr(otel, "export_once", fake)
    ex = otel.Exporter(h.state, {"otel": {"enabled": True, "endpoint": "http://127.0.0.1:1", "interval": 0.05}})
    ex.start()
    try:
        assert second.wait(10), calls  # a pass raised, a later one still ran
        assert ex._thread.is_alive()
    finally:
        ex.stop()
    assert not ex._thread.is_alive()
