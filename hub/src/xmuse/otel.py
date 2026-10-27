"""OpenTelemetry trace export.

Spans are *derived* from hub.db rows after they reach their terminal state; the
hub never reads spans back and a failed export never affects hub behaviour.
Real-time export and `xmuse trace export` replay share `spans()`, so both
produce identical trace/span ids.

This module never imports `opentelemetry` at top level: with export disabled
the hub (and the test suite) runs without the SDK installed. The SDK is
imported lazily inside the functions that build or ship spans.
"""
import hashlib
import json
import logging
import os
import threading
import time
import urllib.parse
from importlib import metadata as _metadata
from pathlib import Path

from . import db

log = logging.getLogger(__name__)

# ---- attribute names (locked semconv opentelemetry-semantic-conventions==0.66b1;
# all Development). One place: a semconv bump only changes these. ------------------
SERVICE_NAME = "xmuse-hub"
ATTR_OPERATION = "gen_ai.operation.name"
OP_INVOKE_AGENT = "invoke_agent"
ATTR_AGENT_ID = "gen_ai.agent.id"
ATTR_AGENT_NAME = "gen_ai.agent.name"
ATTR_PROVIDER = "gen_ai.provider.name"
ATTR_REQUEST_MODEL = "gen_ai.request.model"
ATTR_CONVERSATION_ID = "gen_ai.conversation.id"
ATTR_USAGE_IN = "gen_ai.usage.input_tokens"
ATTR_USAGE_OUT = "gen_ai.usage.output_tokens"
ATTR_USAGE_CACHE_READ = "gen_ai.usage.cache_read.input_tokens"
# 0.66b1's released name for cache writes (upstream main renamed it to
# gen_ai.usage.cache_write.input_tokens; adopt on the next semconv bump).
ATTR_USAGE_CACHE_WRITE = "gen_ai.usage.cache_creation.input_tokens"
ATTR_OI_KIND = "openinference.span.kind"
OI_AGENT = "AGENT"
OI_CHAIN = "CHAIN"

# xmuse.* (our own namespace; never collides with semconv renames)
A_TURN_ID = "xmuse.turn.id"
A_VENDOR = "xmuse.vendor"
A_ADAPTER = "xmuse.adapter"
A_TURN_FRESH = "xmuse.turn.fresh"
A_TURN_STATE = "xmuse.turn.state"
A_CTX_TOKENS = "xmuse.turn.context_tokens"
A_ALIGN_TOKENS = "xmuse.align.tokens"
A_ALIGN_MODE = "xmuse.align.mode"
A_ALIGN_VIEW = "xmuse.align.view_entries"
A_QUEUE_WAIT = "xmuse.queue_wait_s"
A_THREAD = "xmuse.thread.id"
A_MSG_ID = "xmuse.message.id"
A_MSG_KIND = "xmuse.message.kind"
A_MSG_THREAD = "xmuse.message.thread"
A_MSG_SENDER = "xmuse.message.sender"
A_MSG_DEPTH = "xmuse.message.depth"
A_MSG_MENTIONS = "xmuse.message.mentions"
A_MSG_CHARS = "xmuse.message.body_chars"
A_MSG_VIA = "xmuse.message.via"
A_MSG_BODY = "xmuse.message.body"
A_APPR_ID = "xmuse.approval.id"
A_APPR_ACTION = "xmuse.approval.action"
A_APPR_RES = "xmuse.approval.resources"
A_APPR_STATE = "xmuse.approval.state"
A_APPR_DECISION = "xmuse.approval.decision"
A_APPR_WAIT = "xmuse.approval.wait_s"
A_CHAIN_ID = "xmuse.chain.id"
A_CHAIN_STATE = "xmuse.chain.state"
A_CHAIN_NOTE = "xmuse.chain.note"
EVENT_ENTRY = "xmuse.entry"

TERMINAL_TURNS = ("succeeded", "failed", "interrupted", "canceled")
MARK_TURNS, MARK_MESSAGES, MARK_APPROVALS, MARK_CHAINS = "turn", "message", "approval", "chain"

# One warning per process when export is enabled but the SDK is missing.
_warned_missing = False


def _version() -> str:
    try:
        return _metadata.version("xmuse")
    except Exception:
        return "0.1.0"


def otel_config(cfg: dict) -> dict:
    """Effective otel config: file config merged over the standard env vars.

    `enabled` is also forced on by XMUSE_OTEL_ENABLED=1/true/yes (measuring and
    experiments; the file config stays the source of record). Never logs or
    returns secret material beyond the headers dict itself, which callers must
    not print (the OTLP headers carry the backend's credentials).
    """
    raw = cfg.get("otel") or {}
    if not isinstance(raw, dict):
        raw = {}
    env_on = os.environ.get("XMUSE_OTEL_ENABLED", "").lower() in ("1", "true", "yes")
    env_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or ""
    env_traces = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or ""
    if env_traces.endswith("/v1/traces"):
        env_traces = env_traces[: -len("/v1/traces")]
    endpoint = raw.get("endpoint") or env_traces or env_endpoint or "http://localhost:6006"
    headers: dict[str, str] = {}
    for src in (os.environ.get("OTEL_EXPORTER_OTLP_HEADERS") or "",
                os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or ""):
        for pair in src.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip():
                    headers[k.strip()] = urllib.parse.unquote(v.strip())
    for k, v in (raw.get("headers") or {}).items():
        headers[str(k)] = str(v)
    return {"enabled": bool(raw.get("enabled", False)) or env_on, "endpoint": endpoint, "headers": headers,
            "capture_content": bool(raw.get("capture_content", False)),
            "body_clip": int(raw.get("body_clip") or 2000),
            "interval": float(raw.get("interval") or 5)}


def _trace_id(room_id: str, chain_id) -> int:
    return int.from_bytes(hashlib.sha256(f"{room_id}:chain:{chain_id}".encode()).digest()[:16], "big") or 1


def _span_id(room_id: str, kind: str, row_id) -> int:
    return int.from_bytes(hashlib.sha256(f"{room_id}:{kind}:{row_id}".encode()).digest()[:8], "big") or 1


def _ns(seconds: float | None) -> int | None:
    return None if seconds is None else int(seconds * 1e9)


def _room(conn) -> dict:
    r = db.row(conn.execute("select * from room limit 1"))
    return {"id": r["id"], "name": r["name"]} if r else {"id": "", "name": ""}


def _turn_wake(conn, turn_id: int) -> list[dict]:
    """Wake deliveries admitted into a turn, earliest message first."""
    return db.rows(conn.execute(
        "select m.*, d.wake from deliveries d join messages m on m.id=d.message_id"
        " where d.turn_id=? and d.wake=1 order by m.created_at, m.id", (turn_id,)))


def _entry_events_indexed(conn) -> dict[int, list[dict]]:
    """All message-caused alignment ops, indexed by message id in one pass.

    entry_events.msg records which send caused each op, so a later supersede or
    resolve never rewrites what an earlier message's span shows. Ops with no
    msg (DBs from before the column, e.g. experiment runs) are attributed from
    facts that never change: an add to the entry's first source message, a
    supersede to the message that added the replacing entry. Other ops without
    msg (resolve, confirm, ...) cannot be attributed and are left out.
    """
    has_msg = "msg" in {r[1] for r in conn.execute("pragma table_info(entry_events)")}
    entries = {r[0]: r for r in conn.execute("select id, kind, scope, supersedes, refs from entries")}
    replaced_by = {}
    for e in sorted(entries.values(), key=lambda r: r[0]):
        if e[3] is not None:
            replaced_by.setdefault(e[3], e[0])  # the earliest replacement

    def source(eid):
        try:
            refs = json.loads(entries[eid][4] or "[]")
        except (KeyError, ValueError):
            return None
        return refs[0] if refs and isinstance(refs[0], int) and not isinstance(refs[0], bool) else None

    out: dict[int, list[dict]] = {}
    for eid, op, msg in conn.execute("select entry_id, op, " + ("msg" if has_msg else "null")
                                     + " from entry_events order by seq"):
        e = entries.get(eid)
        if e is None:
            continue
        if msg is None:
            if op == "add":
                msg = source(eid)
            elif op == "supersede" and eid in replaced_by:
                msg = source(replaced_by[eid])
        if msg is None:
            continue
        out.setdefault(msg, []).append({"id": eid, "kind": e[1], "scope": e[2], "supersedes": e[3], "op": op})
    return out


def _is_user_dm(conn, m: dict) -> bool:
    if m["sender"] != "human" or not m["thread_id"].startswith("dm:"):
        return False
    ms = [r[0] for r in conn.execute("select member from thread_members where thread_id=?", (m["thread_id"],))]
    return len(ms) == 2 and "human" in ms


def _released(conn, mid: int) -> bool:
    return bool(conn.execute("select 1 from share_marks where message_id=? and target=''",
                             (mid,)).fetchone())


def spans(conn, since: float | None = None, capture: bool = False, body_clip: int = 2000,
          unmarked: bool = False, room: tuple[str, str] | None = None):
    """Map every terminal hub.db row to a deterministic ReadableSpan.

    Pure: reads the DB, writes nothing. `since` (unix
    seconds) keeps only rows at/after that time (turns by ended_at, messages by
    created_at, approvals by decided_at; capped chains carry no timestamp and
    are always included). `capture` adds message bodies, except unmarked user
    DMs, truncated to `body_clip` chars. `unmarked` leaves out rows already in
    otel_marks without building their spans (the table must exist; replay
    leaves it False and needs no marks table). `room`
    overrides the room row (experiment DBs have none; replay then namespaces
    each run explicitly, otherwise colliding ids would overwrite each other).
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.trace import Link, SpanContext, SpanKind, Status, StatusCode, TraceFlags

    room = {"id": room[0], "name": room[1]} if room is not None else _room(conn)
    rid = room["id"]
    resource = Resource.create({"service.name": SERVICE_NAME, "service.version": _version(),
                                "xmuse.room.id": rid, "xmuse.room.name": room["name"]})
    agents = {r["id"]: r for r in db.rows(conn.execute("select * from agents"))}
    sessions = {r["id"]: r for r in db.rows(conn.execute("select * from sessions"))}
    chains = {r["id"]: r for r in db.rows(conn.execute("select * from chains"))}
    usage = {r["turn_id"]: r for r in db.rows(conn.execute("select * from usage"))}

    def _exclude(kind: str, table: str):
        # a correlated NOT EXISTS against the (kind, id) primary key: the query stays the same size however many
        # rows were exported (an `id not in (...)` list hits SQLite's variable limit in a long-lived room)
        if not unmarked:
            return "", []
        return (f" and not exists (select 1 from otel_marks o where o.kind=? and o.id=cast({table}.id as text))",
                [kind])

    def ctx(trace: int, sid: int) -> SpanContext:
        return SpanContext(trace_id=trace, span_id=sid, is_remote=False, trace_flags=TraceFlags(0x01))

    def msg_ctx(m: dict) -> SpanContext:
        return ctx(_trace_id(rid, m["chain_id"]), _span_id(rid, MARK_MESSAGES, m["id"]))

    # every turn's chain, terminal or not: message parents are computed from the
    # row, so a message sent mid-turn keeps its parent when the turn later ends
    turn_chains = {r[0]: r[1] for r in conn.execute("select id, chain_id from turns")}
    entry_index = _entry_events_indexed(conn)

    # ---- invoke_agent (turns) -------------------------------------------------
    turn_spans: dict[int, object] = {}
    turn_traces: dict[int, int] = {}
    t_ex, t_args = _exclude(MARK_TURNS, "turns")
    for t in db.rows(conn.execute("select * from turns where 1=1" + t_ex + " order by id", t_args)):
        if t["state"] not in TERMINAL_TURNS:
            continue
        if since is not None and (t["ended_at"] is None or t["ended_at"] < since):
            continue
        wake = _turn_wake(conn, t["id"])
        cid = t["chain_id"] if t.get("chain_id") is not None else (wake[0]["chain_id"] if wake else 0)
        trace = _trace_id(rid, cid)
        a = agents.get(t["agent_id"]) or {}
        u = usage.get(t["id"])
        attrs: dict = {A_TURN_ID: t["id"], ATTR_OPERATION: OP_INVOKE_AGENT,
                       ATTR_AGENT_ID: t["agent_id"], ATTR_AGENT_NAME: t["agent_id"],
                       A_VENDOR: a.get("vendor", ""), A_ADAPTER: t["adapter"] or "",
                       A_TURN_FRESH: bool(t["fresh"]), ATTR_OI_KIND: OI_AGENT}
        if a.get("family"):
            attrs[ATTR_PROVIDER] = a["family"]
        model = (u["model"] if u and u.get("model") else None) or a.get("model") or ""
        if model:
            attrs[ATTR_REQUEST_MODEL] = model
        sess = sessions.get(t["session_id"]) if t.get("session_id") else None
        if sess and sess.get("vendor_session"):
            attrs[ATTR_CONVERSATION_ID] = sess["vendor_session"]
        if u:
            attrs[ATTR_USAGE_IN] = u["input"]
            attrs[ATTR_USAGE_OUT] = u["output"]
            attrs[ATTR_USAGE_CACHE_READ] = u["cache_read"]
            attrs[ATTR_USAGE_CACHE_WRITE] = u["cache_write"]
            attrs[A_CTX_TOKENS] = u["context"]
        for col, key in (("align_tokens", A_ALIGN_TOKENS), ("align_mode", A_ALIGN_MODE),
                         ("view_entries", A_ALIGN_VIEW)):
            if t.get(col) is not None:
                attrs[key] = t[col]
        if wake:
            attrs[A_QUEUE_WAIT] = max(0.0, t["started_at"] - wake[0]["created_at"])
        ch = chains.get(t["chain_id"]) if t.get("chain_id") is not None else None
        thread = (ch["thread_id"] if ch else None) or (sess["thread_id"] if sess and sess.get("thread_id") else "")
        if thread:
            attrs[A_THREAD] = thread
        parent, links = None, []
        if wake:
            # the earliest wake message on the turn's own chain is the parent;
            # everything else (including earlier cross-chain messages) is a link
            same = [m for m in wake if m["chain_id"] == cid]
            rest = [m for m in wake if m["chain_id"] != cid]
            if same:
                parent = msg_ctx(same[0])
                rest = [m for m in wake if m is not same[0]]
            for m in rest:
                links.append(Link(msg_ctx(m)))
        if t["state"] != "succeeded":
            attrs[A_TURN_STATE] = t["state"]
        status = {"succeeded": Status(StatusCode.OK),
                  "failed": Status(StatusCode.ERROR, (t["error"] or "")[:500] or t["state"])}.get(
                      t["state"], Status(StatusCode.UNSET))
        turn_traces[t["id"]] = trace
        turn_spans[t["id"]] = ReadableSpan(
            name=f"{OP_INVOKE_AGENT} {t['agent_id']}", context=ctx(trace, _span_id(rid, MARK_TURNS, t["id"])),
            parent=parent, resource=resource, attributes=attrs, links=links, kind=SpanKind.INTERNAL,
            status=status, start_time=_ns(t["started_at"]), end_time=_ns(t["ended_at"]))

    # ---- xmuse.message --------------------------------------------------------
    msg_spans: list = []
    m_ex, m_args = _exclude(MARK_MESSAGES, "messages")
    messages = db.rows(conn.execute("select * from messages where 1=1" + m_ex + " order by id", m_args))
    if since is not None:
        messages = [m for m in messages if m["created_at"] >= since]
    for m in messages:
        trace = _trace_id(rid, m["chain_id"])
        attrs = {A_MSG_ID: m["id"], A_MSG_KIND: m["kind"], A_MSG_THREAD: m["thread_id"],
                 A_MSG_SENDER: m["sender"], A_MSG_DEPTH: m["depth"],
                 A_MSG_MENTIONS: list(json.loads(m["mentions"] or "[]")),
                 A_MSG_CHARS: len(m["body"] or ""), ATTR_OI_KIND: OI_CHAIN}
        if m.get("via"):
            attrs[A_MSG_VIA] = m["via"]
        if capture and not (_is_user_dm(conn, m) and not _released(conn, m["id"])):
            attrs[A_MSG_BODY] = (m["body"] or "")[:body_clip]
        parent, links = None, []
        # the parent comes from the turns row, whatever its state: a message
        # sent mid-turn is exported at once and keeps this parent forever
        if m.get("turn_id") is not None and m["turn_id"] in turn_chains:
            t_cid = turn_chains[m["turn_id"]]
            if t_cid is not None:
                t_trace = _trace_id(rid, t_cid)
                pctx = ctx(t_trace, _span_id(rid, MARK_TURNS, m["turn_id"]))
                if t_trace == trace:
                    parent = pctx
                else:
                    links.append(Link(pctx))
        events = [Event(EVENT_ENTRY,
                        {"entry": f"E{e['id']}", "kind": e["kind"], "scope": e["scope"], "op": e["op"],
                         **({"supersedes": e["supersedes"]} if e["supersedes"] is not None else {})},
                        _ns(m["created_at"]))
                  for e in entry_index.get(m["id"], [])]
        msg_spans.append(ReadableSpan(
            name=f"xmuse.message {m['kind']}", context=msg_ctx(m),
            parent=parent, resource=resource, attributes=attrs, events=events, links=links,
            kind=SpanKind.INTERNAL, status=Status(StatusCode.UNSET),
            start_time=_ns(m["created_at"]), end_time=_ns(m["created_at"])))

    # ---- xmuse.approval (decided only) -----------------------------------------
    appr_spans: list = []
    a_ex, a_args = _exclude(MARK_APPROVALS, "approvals")
    for a in db.rows(conn.execute("select * from approvals where 1=1" + a_ex + " order by created_at", a_args)):
        if not a.get("decided_at"):
            continue
        if since is not None and a["decided_at"] < since:
            continue
        t = db.row(conn.execute(
            "select id, chain_id from turns where agent_id=? and started_at<=? and (ended_at is null or ended_at>=?)"
            " order by started_at desc limit 1", (a["agent_id"], a["created_at"], a["created_at"])))
        if t is None:
            t = db.row(conn.execute("select id, chain_id from turns where agent_id=? and started_at<=?"
                                    " order by started_at desc limit 1", (a["agent_id"], a["created_at"])))
        if t is None or t.get("chain_id") is None:
            continue  # no turn to hang the approval on: skip (never invent a trace)
        trace = _trace_id(rid, t["chain_id"])
        attrs = {A_APPR_ID: a["id"], A_APPR_ACTION: a.get("action") or "",
                 A_APPR_RES: a.get("resources") or "", A_APPR_STATE: a["state"],
                 A_APPR_DECISION: a.get("decision") or "",
                 A_APPR_WAIT: max(0.0, a["decided_at"] - a["created_at"]), ATTR_OI_KIND: OI_AGENT}
        ok = a.get("decision") in ("once", "always")
        appr_spans.append(ReadableSpan(
            name="xmuse.approval", context=ctx(trace, _span_id(rid, MARK_APPROVALS, a["id"])),
            parent=ctx(trace, _span_id(rid, MARK_TURNS, t["id"])), resource=resource, attributes=attrs,
            kind=SpanKind.INTERNAL,
            status=Status(StatusCode.OK) if ok else Status(StatusCode.ERROR, (a.get("decision") or "decided")),
            start_time=_ns(a["created_at"]), end_time=_ns(a["decided_at"])))

    # ---- xmuse.chain.capped ----------------------------------------------------
    cap_spans: list = []
    c_ex, c_args = _exclude(MARK_CHAINS, "chains")
    for c in db.rows(conn.execute("select * from chains where state in ('capped','stopped')" + c_ex +
                                  " order by id", c_args)):
        last = db.row(conn.execute("select id, created_at from messages where chain_id=? order by id desc limit 1",
                                   (c["id"],)))
        at = last["created_at"] if last else c["created_at"]
        attrs = {A_CHAIN_ID: c["id"], A_CHAIN_STATE: c["state"], ATTR_OI_KIND: OI_CHAIN}
        if c.get("note"):
            attrs[A_CHAIN_NOTE] = c["note"]
        parent = ctx(_trace_id(rid, c["id"]), _span_id(rid, MARK_MESSAGES, last["id"])) if last else None
        cap_spans.append(ReadableSpan(
            name="xmuse.chain.capped", context=ctx(_trace_id(rid, c["id"]), _span_id(rid, MARK_CHAINS, c["id"])),
            parent=parent, resource=resource, attributes=attrs, kind=SpanKind.INTERNAL,
            status=Status(StatusCode.UNSET), start_time=_ns(at), end_time=_ns(at)))

    return [*turn_spans.values(), *msg_spans, *appr_spans, *cap_spans]


def mark_key(s) -> tuple[str, str] | None:
    """otel_marks (kind, id) for a built span; None when the span carries no row id."""
    a = s.attributes or {}
    if s.name.startswith(OP_INVOKE_AGENT) and A_TURN_ID in a:
        return (MARK_TURNS, str(a[A_TURN_ID]))
    if s.name.startswith("xmuse.message") and A_MSG_ID in a:
        return (MARK_MESSAGES, str(a[A_MSG_ID]))
    if s.name == "xmuse.approval" and A_APPR_ID in a:
        return (MARK_APPROVALS, str(a[A_APPR_ID]))
    if s.name == "xmuse.chain.capped" and A_CHAIN_ID in a:
        return (MARK_CHAINS, str(a[A_CHAIN_ID]))
    return None


def ensure_marks(conn) -> None:
    conn.execute("create table if not exists otel_marks(kind text not null, id text not null,"
                 " primary key(kind, id))")


def _require_sdk() -> None:
    import opentelemetry.exporter.otlp.proto.http.trace_exporter  # noqa: F401
    import opentelemetry.sdk.trace  # noqa: F401


def _otlp_exporter(oc: dict):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter(endpoint=oc["endpoint"].rstrip("/") + "/v1/traces",
                            headers=oc["headers"] or None, timeout=10)


def export_once(state, cfg: dict, exporter=None) -> dict:
    """Export every unmarked terminal row; write marks only on success.

    Never raises, never touches hub behaviour: on any failure it logs (without
    headers) and returns ok False so the next kick retries. `exporter` is a
    test seam (an object with .export(spans)); default is OTLP/HTTP.
    `state` is the workspace state dir.
    """
    oc = otel_config(cfg)
    if not oc["enabled"]:
        return {"enabled": False, "ok": True, "exported": 0}
    global _warned_missing
    try:
        _require_sdk()
    except ImportError:
        if not _warned_missing:
            _warned_missing = True
            log.warning("otel enabled but opentelemetry is not installed; hub runs unchanged"
                        " (uv sync --project hub --group otel)")
        return {"enabled": True, "ok": False, "reason": "missing-deps", "exported": 0}
    conn = db.connect(Path(state) / "hub.db")
    try:
        ensure_marks(conn)
        pending, keys = [], []
        for s in spans(conn, capture=oc["capture_content"], body_clip=oc["body_clip"], unmarked=True):
            key = mark_key(s)
            if key is None:
                continue
            pending.append(s)
            keys.append(key)
        if not pending:
            return {"enabled": True, "ok": True, "exported": 0}
        exp = exporter if exporter is not None else _otlp_exporter(oc)
        try:
            from opentelemetry.sdk.trace.export import SpanExportResult
            res = exp.export(pending)
            good = res is True or res == SpanExportResult.SUCCESS
        except Exception:
            log.warning("otel export to %s failed (%d spans pending); hub unaffected, will retry",
                        oc["endpoint"], len(pending), exc_info=True)
            return {"enabled": True, "ok": False, "reason": "export-failed", "exported": 0}
        if not good:
            log.warning("otel export to %s rejected %d spans; hub unaffected, will retry",
                        oc["endpoint"], len(pending))
            return {"enabled": True, "ok": False, "reason": "export-failed", "exported": 0}
        with db.tx(conn):
            conn.executemany("insert or ignore into otel_marks values(?,?)", keys)
        return {"enabled": True, "ok": True, "exported": len(pending)}
    finally:
        conn.close()


def replay(dbpath, endpoint: str, since: float | None = None, capture: bool = False,
           body_clip: int = 2000, headers: dict | None = None, room: tuple[str, str] | None = None) -> dict:
    """One-shot export of any hub.db (experiment runs included).

    Uses the same spans() as real-time export, so ids match. Reads the DB
    read-only, never touches otel_marks (nothing to dedup against on replay).
    `room` namespaces DBs without a room row (experiment runs); without it two
    runs with identical row ids would produce identical trace ids and overwrite
    each other in the backend. Raises on export failure (the CLI reports it);
    never logs headers.
    """
    import sqlite3

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import SpanExportResult
    uri = f"file:{Path(dbpath).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        all_spans = spans(conn, since=since, capture=capture, body_clip=body_clip, room=room)
    finally:
        conn.close()
    if not all_spans:
        return {"exported": 0, "traces": 0, "endpoint": endpoint}
    res = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces",
                           headers=headers or None, timeout=30).export(all_spans)
    if res != SpanExportResult.SUCCESS:
        raise RuntimeError(f"export to {endpoint} failed: {res}")
    return {"exported": len(all_spans),
            "traces": len({s.context.trace_id for s in all_spans}), "endpoint": endpoint}


class Exporter:
    """Background export thread for a running hub: kicked by the engine plus a
    periodic sweep, so a missed kick only delays spans by `interval` seconds."""

    def __init__(self, state: Path, cfg: dict):
        self.state, self.cfg = state, cfg
        self.oc = otel_config(cfg)
        self._kick = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.oc["enabled"]:
            return
        try:
            _require_sdk()
        except ImportError:
            log.warning("otel enabled but opentelemetry is not installed; hub runs unchanged"
                        " (uv sync --project hub --group otel)")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="otel-export")
        self._thread.start()

    def kick(self) -> None:
        self._kick.set()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        if self._thread is not None:
            self._thread.join(10)

    def _run(self) -> None:
        last = 0.0
        while not self._stop.is_set():
            self._kick.wait(self.oc["interval"])
            self._kick.clear()
            if self._stop.is_set():
                break
            try:  # the whole pass: nothing raised here may end the thread
                # debounce: a burst of kicks ships at most one batch per interval
                now = time.monotonic()
                if now - last < self.oc["interval"]:
                    continue
                last = now
                export_once(self.state, self.cfg)
            except Exception:
                log.warning("otel background export raised; hub unaffected, will retry", exc_info=True)
