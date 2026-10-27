"""Consistency auditor: after an entry is superseded, which earlier messages relied on the old version.

Runs in a background thread, off every turn: it polls entry_events for new 'supersede' events (and is kicked after
each send), sends MemoryOS /audit the old and new statements plus the messages written while the old one was in
force, and records what came back. The host gets one notice listing the flagged messages; each flagged message's
author gets a line in its next wake pack (wakepack.audits). Supersedes that happened before the hub started are
marked skipped, never audited late. MemoryOS failing means no audit, never a blocked or changed turn; a failed
audit is tried once more audit_retry_s later (E13: a supersede made while MemoryOS was down was lost for good).
An author revising its own entry is audited without its own messages and those already flagged: in E13 members
re-declared their module decisions while reworking an audit's flags, and those audits only flagged them again.
Evidence for the retrieval and judge design: xmuse2-learn handson/exp-dep-recall (DepRecall rounds 1-3).
"""
import json
import logging
import threading

from . import db, mail, memoryos
from .config import HUB, alignment_on

log = logging.getLogger("xmuse.audit")
TEXT, WINDOW = 8000, 2000  # WINDOW: newest messages sent; 500 cut 3% of DepRecall dependents
KINDS = ("decision", "convention", "assumption")  # a superseded question was answered: nothing relied on it
TRIES = 2  # a failed audit: the first try and one retry


def _text(conn, e: dict) -> str:
    """The entry's statement plus its source message (statements are cut to their first sentence)."""
    refs = json.loads(e["refs"] or "[]")
    src = conn.execute("select body from messages where id=?", (refs[0],)).fetchone() if refs else None
    body = src[0] if src and src[0] and src[0] != e["statement"] else ""
    return (e["statement"] + ("\n\n" + body if body else ""))[:TEXT]


def _item(m: dict) -> dict:
    why = "".join(f"\n{k}: {v}" for k, v in json.loads(m["why"] or "{}").items() if v)
    return {"id": f"m{m['id']}", "text": ((m["body"] or "") + why)[:TEXT] or "(empty)", "speaker": m["sender"],
            "seq": m["id"]}


class Auditor:
    def __init__(self, mo, pool, cfg: dict):
        self.mo, self.pool, self.cfg = mo, pool, cfg
        self.wake, self.stopping, self.lock = threading.Event(), threading.Event(), threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        if "audit" in mo.caps and alignment_on(cfg):
            with db.tx(pool()) as c:  # only what is superseded from now on gets audited
                c.execute("insert or ignore into audits(entry_id, state, at) select distinct entry_id, 'skipped', ?"
                          " from entry_events where op='supersede'", (db.now(),))
            self.thread.start()

    def kick(self) -> None:
        self.wake.set()

    def stop(self) -> None:
        if self.thread.is_alive():
            self.stopping.set()
            self.wake.set()
            self.thread.join(5)

    def _run(self) -> None:
        while not self.stopping.is_set():
            self.wake.wait(self.cfg["audit_poll_s"])
            self.wake.clear()
            try:
                self.run_pending()
            except Exception:  # noqa: BLE001 - a broken audit must not stop the next one
                log.exception("audit failed")

    def run_pending(self) -> int:
        """Audit every supersede not audited yet, oldest first; returns how many were handled."""
        with self.lock:  # the poller and a direct call (tests, shutdown) never audit the same entry twice
            conn = self.pool()
            todo = [r[0] for r in conn.execute(
                "select entry_id from entry_events where op='supersede' and entry_id not in (select entry_id from"
                " audits where state != 'failed' or tries >= ? or at > ?) group by entry_id order by min(seq)",
                (TRIES, db.now() - self.cfg["audit_retry_s"]))]
            for eid in todo:
                if self.stopping.is_set():
                    break
                self.audit(eid)
            return len(todo)

    def audit(self, eid: int) -> None:
        conn = self.pool()
        old = db.row(conn.execute("select * from entries where id=?", (eid,)))
        new = db.row(conn.execute("select * from entries where supersedes=? and status='active' order by id desc"
                                  " limit 1", (eid,)))
        at = conn.execute("select max(at) from entry_events where entry_id=? and op='supersede'", (eid,)).fetchone()[0]
        if not new or old["kind"] not in KINDS:  # replaced by something no longer active, or a question answered
            return self._record(conn, eid, new and new["id"], "skipped", None)
        refs = set(json.loads(old["refs"] or "[]")) | set(json.loads(new["refs"] or "[]"))
        scoped = old["scope"].startswith("thread:")
        msgs = db.rows(conn.execute(
            "select * from messages where created_at>=? and created_at<? and kind != 'notice' and sender != ?"
            + (" and thread_id=?" if scoped else "") + " order by id desc limit ?",
            (old["recorded_at"], at, HUB, *([old["scope"][7:]] if scoped else []), WINDOW)))
        if old["author"] == new["author"]:  # it knows its own messages; flagged ones are being reworked already
            refs |= {r[0] for r in conn.execute("select message_id from audit_flags")}
            msgs = [m for m in msgs if m["sender"] != new["author"]]
        msgs = [m for m in msgs if m["id"] not in refs][::-1]
        if not msgs:
            return self._record(conn, eid, new["id"], "done", {"flagged": [], "candidates": []})
        items = [_item(m) for m in msgs]
        sent = conn.execute("select msg from entry_events where entry_id=? and op='supersede' order by at desc"
                            " limit 1", (eid,)).fetchone()
        with memoryos.cause("message", sent and sent[0]):  # the message whose send superseded the entry, if known
            r = self.mo.call("audit", "/audit", {"schema": "memoryos_audit/v1", "k": self.cfg["audit_top"],
                                                 "old": {"id": f"E{eid}", "text": _text(conn, old)},
                                                 "new": {"id": f"E{new['id']}", "text": _text(conn, new)},
                                                 "items": items}, self.cfg["audit_timeout_s"])
        if r is None:
            return self._record(conn, eid, new["id"], "failed", None)
        text, by_id = {i["id"]: i["text"] for i in items}, {f"m{m['id']}": m for m in msgs}
        flags = [f for f in r.get("flagged") or [] if isinstance(f, dict) and f.get("id") in by_id
                 and isinstance(f.get("quote"), str) and f["quote"] and f["quote"] in text[f["id"]]]
        log.info("audit E%s result %s", eid, json.dumps({"items": len(items), "flagged": len(flags),
                                                         "diagnostics": r.get("diagnostics")}, sort_keys=True))
        self._record(conn, eid, new["id"], "done", {"flagged": flags, "candidates": r.get("candidates") or []},
                     [(by_id[f["id"]], f["quote"]) for f in flags])
        if flags:
            lines = [f"#{by_id[f['id']]['id']} {by_id[f['id']]['sender']}: \"{f['quote']}\"" for f in flags]
            mail.notice(conn, new["thread_id"], (
                f"audit: E{new['id']} replaced E{eid}. {len(flags)} earlier message(s) relied on the old version:\n"
                + "\n".join(lines) + "\nTheir authors see this at their next wake. Found by retrieval and a model "
                f"check over the messages since E{eid}: it may miss some."))

    def _record(self, conn, eid: int, by: int | None, state: str, result: dict | None,
                flags: list | None = None) -> None:
        with db.tx(conn):  # only a failed row is ever replaced: by its retry
            conn.execute("insert into audits(entry_id, by_id, state, at, result) values(?,?,?,?,?) on conflict(entry_id)"
                         " do update set by_id=excluded.by_id, state=excluded.state, at=excluded.at,"
                         " result=excluded.result, tries=tries+1 where state='failed'",
                         (eid, by, state, db.now(), json.dumps(result) if result is not None else None))
            if flags:  # one alignment version for the audit: wake packs show flags newer than their watermark
                seq = conn.execute("insert into entry_events(entry_id, op, at) values(?,?,?)",
                                   (eid, "audit", db.now())).lastrowid
                conn.executemany("insert into audit_flags(entry_id, by_id, message_id, agent_id, quote, seq)"
                                 " values(?,?,?,?,?,?)", [(eid, by, m["id"], m["sender"], q, seq) for m, q in flags])
