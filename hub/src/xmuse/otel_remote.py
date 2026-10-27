"""Traces across the hub and MemoryOS: a layer on top of the hub's own export, removable as a whole.

With export on, `install(hub)` watches every MemoryOS call through memoryos.Client's observer: it records the call
in its own table `mo_calls` and sends a W3C `traceparent` header, so MemoryOS (when it traces too) hangs its server
span under the hub's client span. That client span, `xmuse.memoryos.call`, is derived from the `mo_calls` row like
every other hub span, through the span source registered below; its parent is the turn or message the call was for
(memoryos.cause). Both sides report to one Phoenix project, `openinference.project.name` (default "xmuse").

With export off nothing happens: no table, no header, no extra writes. The hub core does not know this module;
removing it and its two wiring calls (server.py, cli.py) leaves the hub as it was.
"""
import hashlib
import logging
import os
import urllib.parse

from . import db, otel

log = logging.getLogger("xmuse.otel_remote")
MARK = "mo_call"  # otel_marks kind and span id namespace
PROJECT = "openinference.project.name"
A_CALL_ID = "xmuse.memoryos.call.id"
A_CAP = "xmuse.memoryos.capability"
CAUSES = ("turn", "message")  # the span kinds a cause names (otel.MARK_TURNS, otel.MARK_MESSAGES)

SCHEMA = """create table if not exists mo_calls(
  id integer primary key autoincrement, path text not null, cap text, server text,
  cause_kind text, cause_id integer, chain_id integer,
  started_at real not null, ended_at real, ok integer, status integer, error text, ms integer)"""


def project(cfg: dict) -> str:
    """The Phoenix project both sides report to: config otel.project, else $XMUSE_OTEL_PROJECT, else "xmuse"."""
    raw = cfg.get("otel") if isinstance(cfg.get("otel"), dict) else {}
    return str(raw.get("project") or os.environ.get("XMUSE_OTEL_PROJECT") or "xmuse")


def _has_table(conn) -> bool:
    return conn.execute("select 1 from sqlite_master where type='table' and name='mo_calls'").fetchone() is not None


def _own_trace(room_id: str, call_id: int) -> int:
    """The trace of a call with no cause: its own, one per call."""
    return int.from_bytes(hashlib.sha256(f"{room_id}:{MARK}:{call_id}".encode()).digest()[:16], "big") or 1


def _trace(room_id: str, row: dict) -> int:
    return otel._trace_id(room_id, row["chain_id"]) if row["cause_kind"] else _own_trace(room_id, row["id"])


def traceparent(room_id: str, row: dict) -> str:
    return f"00-{_trace(room_id, row):032x}-{otel._span_id(room_id, MARK, row['id']):016x}-01"


def _chain(conn, kind: str, row_id: int):
    """The chain whose trace the cause's span is in, derived exactly as otel derives it for that span."""
    if kind == "message":
        r = conn.execute("select chain_id from messages where id=?", (row_id,)).fetchone()
        return r[0] if r else None
    r = conn.execute("select chain_id from turns where id=?", (row_id,)).fetchone()
    if r and r[0] is not None:
        return r[0]
    wake = otel._turn_wake(conn, row_id)
    return wake[0]["chain_id"] if wake else 0


class Observer:
    """memoryos.Client observer: a row per call, and the traceparent that points at that row's span."""

    def __init__(self, pool, server: str):
        self.pool, self.server = pool, server

    def start(self, call: dict) -> dict:
        # plain statements, no BEGIN: a caller inside a transaction (on this thread's pooled connection) takes the
        # row with it, anyone else autocommits; a separate connection would wait on the caller's own write lock
        conn = self.pool()
        kind, cid = call["cause"] if call["cause"] and call["cause"][0] in CAUSES else (None, None)
        row = {"cause_kind": kind, "cause_id": cid, "chain_id": _chain(conn, kind, cid) if kind else None}
        row["id"] = conn.execute(
            "insert into mo_calls(path, cap, server, cause_kind, cause_id, chain_id, started_at)"
            " values(?,?,?,?,?,?,?)", (call["path"], call["cap"], self.server, kind, cid, row["chain_id"],
                                       call["started_at"])).lastrowid
        call["mo_call"] = row["id"]
        return {"traceparent": traceparent(otel._room(conn)["id"], row)}

    def end(self, call: dict, outcome: dict) -> None:
        if "mo_call" in call:
            self.pool().execute("update mo_calls set ended_at=?, ok=?, status=?, error=?, ms=? where id=?",
                                (outcome["ended_at"], int(outcome["ok"]), outcome["status"], outcome["error"],
                                 outcome["ms"], call["mo_call"]))


def install(hub) -> bool:
    """Watch the hub's MemoryOS calls when export is on. Returns whether it did."""
    if not otel.otel_config(hub.cfg)["enabled"]:
        return False
    hub.db().execute(SCHEMA)
    otel.register_resource({PROJECT: project(hub.cfg)})
    u = urllib.parse.urlsplit(hub.mo.url)
    hub.mo.observer = Observer(hub.db, u.netloc)
    log.info("memoryos calls traced into project %s", project(hub.cfg))
    return True


def prepare_replay(dbfile, cfg: dict) -> None:
    """`xmuse trace export` of a hub.db that recorded MemoryOS calls goes to the shared project; older ones don't."""
    import sqlite3

    conn = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    try:
        if _has_table(conn):
            otel.register_resource({PROJECT: project(cfg)})
    finally:
        conn.close()


def _spans(sc) -> list:
    """xmuse.memoryos.call: one CLIENT span per finished call, under the span of its cause."""
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import SpanKind, Status, StatusCode

    if not _has_table(sc.conn):
        return []  # a hub that never traced MemoryOS calls (or a db from before this module)
    out: list = []
    ex, args = sc.exclude(MARK, "mo_calls")
    for r in db.rows(sc.conn.execute("select * from mo_calls where ended_at is not null" + ex + " order by id", args)):
        if sc.since is not None and r["ended_at"] < sc.since:
            continue
        trace = _trace(sc.rid, r)
        parent = sc.ctx(trace, otel._span_id(sc.rid, r["cause_kind"], r["cause_id"])) if r["cause_kind"] else None
        attrs: dict = {A_CALL_ID: r["id"], "http.request.method": "POST", "url.path": r["path"],
                       otel.ATTR_OI_KIND: otel.OI_CHAIN}
        server = urllib.parse.urlsplit("//" + (r["server"] or ""))
        if server.hostname:
            attrs["server.address"] = server.hostname
        if server.port:
            attrs["server.port"] = server.port
        if r["cap"]:
            attrs[A_CAP] = r["cap"]
        if r["status"] is not None:
            attrs["http.response.status_code"] = r["status"]
        if r["error"]:
            attrs["error.type"] = r["error"]
        out.append(ReadableSpan(
            name=f"xmuse.memoryos.call {r['path']}", context=sc.ctx(trace, otel._span_id(sc.rid, MARK, r["id"])),
            parent=parent, resource=sc.resource, attributes=attrs, kind=SpanKind.CLIENT,
            status=Status(StatusCode.OK) if r["ok"] else Status(StatusCode.ERROR, r["error"] or "failed"),
            start_time=otel._ns(r["started_at"]), end_time=otel._ns(r["ended_at"])))
    return out


def _mark(s) -> tuple[str, str] | None:
    a = s.attributes or {}
    return (MARK, str(a[A_CALL_ID])) if s.name.startswith("xmuse.memoryos.call") and A_CALL_ID in a else None


otel.register_source(_spans, _mark)  # inert for databases without mo_calls
