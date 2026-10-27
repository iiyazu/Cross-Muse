"""MemoryOS client (contract XMUSE2-M2-MO-CONTRACT): /recall ranks over-cap view layers, /curate collab proposes
entries from a background thread, /similar finds near-duplicates for it.

MemoryOS is never on the correctness path: any failure (down, timeout, non-2xx, malformed reply) means
"memory unavailable" and the hub keeps its deterministic behaviour. It holds no state; the hub sends everything.
"""
import contextlib
import contextvars
import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.request

from . import align, config, db, mail

log = logging.getLogger("xmuse.memoryos")
KINDS = ("decision", "convention", "assumption", "question", "lesson")  # what collab may propose
MSGS = ("message", "handoff", "review_request", "decision", "assumption", "question")  # what curate reads
EVERY, WINDOW, CONTEXT, ACTIVE, SIMILAR = 8, 32, 8, 60, 0.88
_in = lambda xs: ",".join("?" * len(xs))  # noqa: E731


_cause: contextvars.ContextVar[tuple[str, int] | None] = contextvars.ContextVar("memoryos_cause", default=None)


@contextlib.contextmanager
def cause(kind: str, row_id: int | None):
    """Mark the calls made inside the block as caused by a hub row: ("turn", 88) or ("message", 412).

    Only observers read it (the client never does); a None id means no known cause.
    """
    token = _cause.set(None if row_id is None else (kind, row_id))
    try:
        yield
    finally:
        _cause.reset(token)


def _error_type(e: Exception) -> str:
    """The kind of failure, never its text (bodies and URLs stay out of telemetry)."""
    if isinstance(e, urllib.error.HTTPError):
        return "http_5xx" if e.code >= 500 else "http_4xx" if e.code >= 400 else "other"
    if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException):
        e = e.reason
    if isinstance(e, TimeoutError):
        return "timeout"
    if isinstance(e, ConnectionRefusedError):
        return "refused"
    if isinstance(e, ValueError):  # json.JSONDecodeError, or a body that is not UTF-8
        return "bad_json"
    return "other"


class Client:
    """`observer` (optional) watches every call: observer.start(call) before it is sent, returning extra request
    headers or None, and observer.end(call, outcome) after it. `call` is a dict (cap, path, cause, started_at) the
    observer may add its own keys to; `outcome` has ok, status, error (see _error_type; "bad_json" also for a
    reply that is not an object), ms and ended_at. An observer that raises is logged and ignored."""
    cause = staticmethod(cause)

    def __init__(self, url: str, skip=(), observer=None):
        self.url, self.caps, self.timeout, self.observer = url.rstrip("/"), set(), 2.0, observer
        if self.url:  # an unreachable MemoryOS at start means "not used" until the hub restarts
            caps = (self.call(None, "/health", None, 5) or {}).get("capabilities")
            self.caps = (set(caps) if isinstance(caps, (list, dict)) else set()) - set(skip)
            log.info("memoryos %s: capabilities %s", self.url, sorted(self.caps) or "none (disabled)")

    def _observe(self, method: str, *args):
        try:
            return getattr(self.observer, method)(*args)
        except Exception:  # noqa: BLE001 - telemetry never changes what the call does
            log.warning("memoryos observer %s failed", method, exc_info=True)
            return None

    def call(self, cap: str | None, path: str, body: dict | None, timeout: float | None = None) -> dict | None:
        if cap and cap not in self.caps:
            return None
        t0 = time.monotonic()
        headers = {"content-type": "application/json"}
        seen = None if self.observer is None else {"cap": cap, "path": path, "cause": _cause.get(),
                                                   "started_at": time.time()}
        if seen is not None:
            extra = self._observe("start", seen)
            if isinstance(extra, dict):
                headers.update({str(k): str(v) for k, v in extra.items()})
        status, error = None, None
        try:
            req = urllib.request.Request(self.url + path, data=body and json.dumps(body).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                status = r.status
                out = json.load(r)
            log.info("memoryos-call %s", json.dumps({"path": path, "ms": int((time.monotonic() - t0) * 1000), "ok": True}))
            if not isinstance(out, dict):
                error = "bad_json"
            return out if isinstance(out, dict) else None
        except Exception as e:  # noqa: BLE001 - every failure has the same meaning
            error = _error_type(e)
            if isinstance(e, urllib.error.HTTPError):
                status = e.code
            log.warning("memoryos %s failed: %r", path, e)
            log.info("memoryos-call %s", json.dumps({"path": path, "ms": int((time.monotonic() - t0) * 1000), "ok": False}))
            return None
        finally:
            if seen is not None:
                self._observe("end", seen, {"ok": error is None, "status": status, "error": error,
                                            "ms": int((time.monotonic() - t0) * 1000), "ended_at": time.time()})

    def rank(self, es: list[dict], scope: str, role: str, query: str, cap: int, budget: int) -> list[str] | None:
        """Ids ("E12") MemoryOS keeps from one over-cap layer, best first; None means use the newest-by-seq cut."""
        items = [{"id": f"E{e['id']}", "text": e["statement"], "kind": e["kind"], "seq": e["seq"],
                  **({"thread_id": e["thread_id"]} if e["thread_id"] else {}),
                  **({"roles": [scope[5:]]} if scope.startswith("role:") else {})} for e in es[:500]]
        hints = {"thread_id": scope[7:] if scope.startswith("thread:") else "", "role": role}
        r = self.call("recall", "/recall", {"schema": "memoryos_recall/v1", "query": query[:2000], "items": items,
                                            "hints": {k: v for k, v in hints.items() if v},
                                            "budget_tokens": budget, "k": cap})
        try:
            ids = [x["id"] for x in r["ranked"]]
            if ids and len(set(ids)) == len(ids) and set(ids) <= {i["id"] for i in items}:
                return ids[:cap]
        except (KeyError, TypeError):
            pass
        return None  # a failed call already logged; an empty or foreign ranking is as unusable


def _ids(vals, prefix: str, ok) -> list[int]:
    """["E12", ...] -> [12] for the ids in `ok`; anything malformed is dropped."""
    return [int(v[1:]) for v in vals if isinstance(v, str) and re.fullmatch(prefix + r"\d+", v) and int(v[1:]) in ok]


def _act(m: dict) -> dict:
    why = "".join(f"\n{k}: {v}" for k, v in json.loads(m["why"] or "{}").items() if v)
    return {"id": f"m{m['id']}", "seq": m["id"], "type": "message", "speaker": m["sender"], "kind": m["kind"],
            "text": m["body"] + why}


class Curator:
    """Background /curate collab. `kick(thread)` is cheap and synchronous (it only reads hub.db and queues a job);
    the HTTP call and the write-back run in the worker thread, so no turn ever waits for MemoryOS."""

    def __init__(self, mo: Client, pool, cfg: dict):
        self.mo, self.pool, self.cfg = mo, pool, cfg
        self.q, self.busy, self.lock = queue.Queue(), set(), threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        if "curate.collab" in mo.caps:
            self.thread.start()

    def stop(self) -> None:
        if self.thread.is_alive():
            self.q.put(None)
            self.thread.join(5)

    def kick(self, tid: str, closed: bool = False) -> None:
        """Queue a curation if the thread has 8 new messages, a new handoff, or was just closed."""
        if "curate.collab" not in self.mo.caps or not config.alignment_on(self.cfg):
            return
        with self.lock:
            conn = self.pool()
            last = (conn.execute("select msg_id from curated where thread_id=?", (tid,)).fetchone() or [0])[0]
            sql = f"select * from messages where thread_id=? and kind in ({_in(MSGS)}) and id"
            new = db.rows(conn.execute(sql + ">? order by id desc limit ?", (tid, *MSGS, last, WINDOW)))[::-1]
            if tid in self.busy or not new or not (closed or len(new) >= EVERY or any(m["kind"] == "handoff" for m in new)):
                return
            ctx = db.rows(conn.execute(sql + "<=? order by id desc limit ?", (tid, *MSGS, last, CONTEXT)))[::-1]
            active = db.rows(conn.execute(
                f"select * from entries where scope=? and status='active' and kind in ({_in(KINDS)}) order by seq desc"
                " limit ?", (f"thread:{tid}", *KINDS, ACTIVE)))
            self.busy.add(tid)
            self.q.put((tid, new, ctx, active))

    def _run(self) -> None:
        while (job := self.q.get()) is not None:
            try:
                self._curate(*job)
            except Exception:  # noqa: BLE001 - a failed curation is retried by the next trigger
                log.exception("curate %s failed", job[0])
            finally:
                self.busy.discard(job[0])
                self.q.task_done()

    def join(self) -> None:
        self.q.join()

    def _similar(self, active: list[dict]) -> dict | None:
        """Near-duplicate pairs as read-only context for the curator, once the thread layer is over 120% of its cap."""
        if len(active) <= self.cfg["align_thread_cap"] * 1.2:
            return None
        r = self.mo.call("similar", "/similar", {"schema": "memoryos_similar/v1", "threshold": SIMILAR,
                         "items": [{"id": f"E{e['id']}", "text": e["statement"]} for e in active[:500]]}, self.cfg["similar_timeout_s"])
        try:
            pairs = ", ".join(f"{p['a']}~{p['b']} ({p['score']:.2f})" for p in r["pairs"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"id": "hub-similar", "seq": 0, "type": "message", "speaker": "hub", "text":
                f"Near-duplicate active entries, consider proposing a merge: {pairs}"} if pairs else None

    def _curate(self, tid: str, win: list[dict], ctx: list[dict], active: list[dict]) -> None:
        with cause("message", win[-1]["id"]):  # every call of one curation is for the window's last message
            self._curate_window(tid, win, ctx, active)

    def _curate_window(self, tid: str, win: list[dict], ctx: list[dict], active: list[dict]) -> None:
        note = self._similar(active)
        r = self.mo.call("curate.collab", "/curate", {
            "scope_id": tid, "profile": "collab",
            "active": [{"id": f"E{e['id']}", "kind": e["kind"], "topic_key": f"e{e['id']}", "statement": e["statement"],
                        "version": e["seq"]} for e in active],
            "context": [_act(m) for m in ctx][-(CONTEXT - bool(note)):] + [note] * bool(note),
            "window": [_act(m) for m in win], "max_repairs": 1}, self.cfg["curate_timeout_s"])  # worst case 2 x 180 s
        if r is None:
            return
        u = (r.get("diagnostics") or {}).get("usage") or {}  # a lower bound when unmetered_attempts > 0
        log.info("curate %s usage %s", tid, json.dumps(u, sort_keys=True))
        conn, wid, aid = self.pool(), {m["id"] for m in win}, {e["id"] for e in active}
        questions = {e["id"] for e in active if e["kind"] == "question"}
        made, notes = {}, []
        with db.tx(conn):
            for m in r.get("memories") or []:
                st = m.get("statement")
                if m.get("kind") not in KINDS or not isinstance(st, str) or not st.strip() or conn.execute(
                        "select 1 from entries where thread_id=? and statement=? and status in ('proposed','active')",
                        (tid, st)).fetchone():
                    continue
                sup = _ids([m.get("supersedes_id")], "E", aid)
                srcs = [s.get("activity_id") for s in m.get("sources") or [] if isinstance(s, dict)]
                made[m.get("id")] = align.add(
                    conn, m["kind"], f"thread:{tid}", tid, st, _ids(srcs, "m", wid) or [win[-1]["id"]], "curate",
                    sup[0] if sup else None, status="proposed", resolves=_ids(m.get("resolves_ids") or [], "E", questions))
            for c in r.get("conflicts") or []:
                a, b = (made.get(c.get(k)) or next(iter(_ids([c.get(k)], "E", aid)), None) for k in ("a_id", "b_id"))
                if a and b:
                    notes.append(f"curate: E{a} and E{b} may contradict each other: {c.get('reason', '')}")
            conn.execute("insert into curated values(?,?) on conflict(thread_id) do update set msg_id=excluded.msg_id",
                         (tid, win[-1]["id"]))
        log.info("curate %s result %s", tid, json.dumps({  # what came back vs what the hub kept (ops metrics)
            "memories": len(r.get("memories") or []), "added": len(made), "conflicts": len(r.get("conflicts") or []),
            "notices": len(notes)}, sort_keys=True))
        for body in notes:
            mail.notice(conn, tid, body)
        if made and len(active) > self.cfg["align_thread_cap"] * 0.8:  # warm MemoryOS's embedding cache; result unused
            self.mo.rank(active, f"thread:{tid}", "", "", self.cfg["align_thread_cap"], self.cfg["recall_budget_tokens"])
