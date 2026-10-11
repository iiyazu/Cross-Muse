"""Delivery engine (design §4.4): admission, completion, caps, cancel. Event-driven on one thread.

Admission is the only switch point: an agent with queued wake deliveries, no running turn,
no human input in flight, and a writable session gets ALL its queued messages merged into one
turn through its vendor driver. Every other thread only enqueues events.
"""
import json
import logging
import queue
import threading
import time
from pathlib import Path

from . import align, db, mail, wakepack
from .adapters.base import TurnEnd, TurnSpec
from .adapters.opencode import shell_auto_ok
from .config import HUMAN

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, state: Path, cfg: dict, dbf, drivers: dict, workspace: Path):
        self.state, self.cfg, self.db, self.drivers, self.ws = state, cfg, dbf, drivers, workspace
        self.q: queue.Queue = queue.Queue()
        self.adapters = {}  # turn id -> adapter that runs it
        self.shell_policy = "allowlist"  # Hub sets it from its own environment (XMUSE_SHELL_POLICY), never from config
        self._recover()

    # ---- events from other threads -------------------------------------------------
    def kick(self) -> None:
        self.q.put(("kick",))

    def turn_ended(self, end: TurnEnd) -> None:
        self.q.put(("end", end))

    def approval(self, agent_id, session: str, request: dict) -> None:
        self.q.put(("approval", agent_id, session, request))

    def compacted(self, vendor_session: str) -> None:
        """The vendor compacted this session: its next wake gets a full alignment snapshot."""
        self.q.put(("compacted", vendor_session))

    def _on_compacted(self, vendor_session: str) -> None:
        conn = self.db()
        for r in conn.execute("select id from sessions where vendor_session=?", (vendor_session,)).fetchall():
            align.reset_watermark(conn, r[0])

    def call(self, fn, *args, timeout: float = 60):
        """Run fn on the engine thread (state changes stay single-threaded) and return its result."""
        box: queue.Queue = queue.Queue(maxsize=1)
        self.q.put(("call", fn, args, box))
        out = box.get(timeout=timeout)
        if isinstance(out, Exception):
            raise out
        return out

    def _on_call(self, fn, args, box) -> None:
        try:
            box.put(fn(*args))
        except Exception as e:
            box.put(e)

    def run_forever(self, stop: threading.Event) -> None:
        last_sweep = time.time()
        while not stop.is_set():
            try:
                ev = self.q.get(timeout=1)
                if ev[0] == "stop":  # sentinel from Hub.shutdown: do not sit out the get timeout
                    break
                getattr(self, "_on_" + ev[0])(*ev[1:])
            except queue.Empty:
                pass
            if time.time() - last_sweep >= self.cfg["sweep_interval"]:
                last_sweep = time.time()
                self.sweep()

    def drain(self, timeout: float = 5) -> None:
        """Process queued events on the caller's thread (tests)."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = self.q.get(timeout=0.05)
            except queue.Empty:
                return
            getattr(self, "_on_" + ev[0])(*ev[1:])

    # ---- admission -----------------------------------------------------------------
    def _on_kick(self) -> None:
        conn = self.db()
        for agent in db.rows(conn.execute("select * from agents where paused=0 and coalesce(paused_until, 0)<=? order by id",
                                          (db.now(),))):
            if mail.running_turn(conn, agent["id"]) is None:
                self._admit(conn, agent)

    def _admit(self, conn, agent: dict) -> None:
        if db.polled(agent):
            return  # desktop / foreground sessions live on the Windows side: never woken in the background, only polled
        with db.tx(conn):  # no wake for mail already handled (audit B2-3): acked, or read (xmuse_inbox mid-turn) and
            # answered in its thread afterwards. Read but unanswered mail still wakes: a missed wake breaks the chain.
            conn.execute(
                "update deliveries set state='done', updated_at=? where recipient=? and wake=1 and state='queued'"
                " and (acked_at is not null or (read_at is not null and exists (select 1 from messages m0 join"
                " messages r on r.thread_id=m0.thread_id where m0.id=deliveries.message_id and r.sender=?"
                " and r.created_at>=deliveries.read_at)))", (db.now(), agent["id"], agent["id"]))
        pending = db.rows(conn.execute(
            "select d.id did, m.*, c.state cstate, c.wakes cwakes, c.max_wakes, c.tokens ctokens, c.max_tokens"
            " from deliveries d join messages m on m.id=d.message_id join chains c on c.id=m.chain_id"
            " where d.recipient=? and d.wake=1 and d.state='queued' order by m.id", (agent["id"],)))
        if not pending:
            return
        for c in {p["chain_id"]: p for p in pending}.values():
            why = ("max_chain_wakes" if c["cwakes"] >= c["max_wakes"] else
                   "max_chain_tokens" if c["ctokens"] >= c["max_tokens"] else None)
            if why:
                self._cap_chain(conn, c["chain_id"], c["thread_id"], why)
        pending = [p for p in pending if conn.execute(
            "select state from chains where id=?", (p["chain_id"],)).fetchone()[0] == "open"]
        if not pending or self._agent_capped(conn, agent):
            return
        driver = self.drivers[agent["vendor"]]
        session = db.row(conn.execute("select * from sessions where agent_id=? and state='current'", (agent["id"],)))
        pres = driver.presence(agent, session and session["vendor_session"])
        if pres.human_turn:
            return  # human input in flight: wait for its turn end
        if pres.holder == "tui":
            if not pres.push:
                return  # the human's TUI holds the session and cannot take pushes: queue
            adapter, fresh = driver.push, False
        else:
            adapter = driver.headless
            fresh = session is None  # never rotated automatically (design §4.1 principle 9)
        with db.tx(conn):
            chain = pending[-1]["chain_id"]
            tid = conn.execute("insert into turns(agent_id, session_id, adapter, chain_id, fresh, state, started_at)"
                               " values(?,?,?,?,?,?,?)", (agent["id"], None if fresh else session["id"], adapter.name,
                                                          chain, int(fresh), "running", db.now())).lastrowid
            conn.executemany("update deliveries set state='admitted', turn_id=?, read_at=?, updated_at=? where id=?",
                             [(tid, db.now(), db.now(), p["did"]) for p in pending])
            for c in {p["chain_id"] for p in pending}:
                conn.execute("update chains set wakes=wakes+1 where id=?", (c,))
        # settings.cwd: an agent working in its own git worktree (plan-split-integrate executors, T13)
        cwd = Path(db.settings(agent).get("cwd") or self.ws)
        pack = wakepack.render(conn, self.cfg, agent, pending, None if fresh else session["id"], str(cwd))
        with db.tx(conn):  # passive messages are now summarized to the agent; the session has seen this alignment
            conn.execute("update deliveries set read_at=? where recipient=? and state='passive' and read_at is null",
                         (db.now(), agent["id"]))
            conn.execute("update turns set align_tokens=?, align_mode=?, view_entries=? where id=?",
                         (pack.tokens, pack.mode, pack.view_entries, tid))
            if not fresh:
                conn.execute("insert or replace into seen values(?,?)", (session["id"], pack.seq))
        spec = TurnSpec(tid, agent, None if fresh else session["vendor_session"], pack.text, cwd,
                        self.state / "runs" / f"turn-{tid}.jsonl")
        self.adapters[tid] = adapter
        try:
            info = adapter.start(spec)
        except Exception as e:
            self._on_end(TurnEnd(tid, "failed", spec.session, error=f"start failed: {e}"))
            return
        with db.tx(conn):
            sid = None if not fresh else conn.execute(
                "insert into sessions(agent_id, vendor_session, cwd, origin, created_at) values(?,?,?,?,?)",
                (agent["id"], info.get("handle"), info.get("cwd", str(cwd)), "hub", db.now())).lastrowid
            conn.execute("update turns set pid=?, handle=?, session_id=coalesce(session_id, ?) where id=?",
                         (info.get("pid"), info.get("handle"), sid, tid))
            if sid:
                conn.execute("insert or replace into seen values(?,?)", (sid, pack.seq))

    def _cap_chain(self, conn, chain_id: int, thread_id: str, why: str) -> None:
        with db.tx(conn):
            conn.execute("update chains set state='capped', note=? where id=?", (why, chain_id))
            conn.execute("update deliveries set state='held', updated_at=? where state='queued' and message_id in"
                         " (select id from messages where chain_id=?)", (db.now(), chain_id))
        mail.notice(conn, thread_id, f"chain {chain_id} capped ({why}); its pending messages are held. "
                                     "Send a new message to continue.", chain_id)

    def _agent_capped(self, conn, agent: dict) -> bool:
        since = db.now() - 3600
        turns = conn.execute("select count(*) from turns where agent_id=? and started_at>?",
                             (agent["id"], since)).fetchone()[0]
        tokens = conn.execute("select coalesce(sum(input+cache_read+cache_write+output), 0) from usage"
                              " where agent_id=? and created_at>?", (agent["id"], since)).fetchone()[0]
        why = ("agent_hourly_turns" if turns >= self.cfg["agent_hourly_turns"] else
               "agent_hourly_tokens" if tokens >= self.cfg["agent_hourly_tokens"] else None)
        if why:
            with db.tx(conn):
                conn.execute("update agents set paused=1 where id=?", (agent["id"],))
            mail.notice(conn, mail.dm_id(agent["id"], HUMAN), f"{agent['id']} paused ({why}). "
                                                              f"`xmuse resume --agent {agent['id']}` to continue.")
        return bool(why)

    # ---- completion ----------------------------------------------------------------
    def _on_end(self, end: TurnEnd) -> None:
        conn = self.db()
        turn = db.row(conn.execute("select * from turns where id=?", (end.turn_id,)))
        if turn is None or turn["state"] != "running":
            return
        agent = db.row(conn.execute("select * from agents where id=?", (turn["agent_id"],)))
        u = end.usage
        dstate = {"succeeded": "done", "failed": "failed", "interrupted": "canceled"}[end.status]
        with db.tx(conn):
            conn.execute("update turns set state=?, ended_at=?, error=? where id=?",
                         (end.status, db.now(), "; ".join(x for x in (end.error, end.note) if x) or None, turn["id"]))
            if end.retry_at or end.requeue:  # the messages were not handled: put them back
                conn.execute("update chains set wakes=max(wakes-1, 0) where id in (select m.chain_id from deliveries"
                             " d join messages m on m.id=d.message_id where d.turn_id=? and d.state='admitted')",
                             (turn["id"],))
                conn.execute("update deliveries set state='queued', turn_id=null, updated_at=? where turn_id=?"
                             " and state='admitted'", (db.now(), turn["id"]))
                if end.retry_at:
                    conn.execute("update agents set paused_until=? where id=?", (end.retry_at, agent["id"]))
                if end.requeue == "hold":
                    conn.execute("update agents set paused=1 where id=?", (agent["id"],))
                if end.requeue == "fresh" and turn["session_id"]:
                    conn.execute("update sessions set state='retired', retired_at=? where id=?",
                                 (db.now(), turn["session_id"]))
            conn.execute("update deliveries set state=?, updated_at=? where turn_id=? and state='admitted'",
                         (dstate, db.now(), turn["id"]))
            conn.execute("insert or replace into usage values(?,?,?,?,?,?,?,?,?,?,?,?)",
                         (turn["id"], agent["id"], agent["vendor"], u.model or agent["model"], u.mode, u.input,
                          u.cache_read, u.cache_write, u.output, u.context, u.calls, db.now()))
            if turn["session_id"]:
                prev = conn.execute("select context_tokens from sessions where id=?", (turn["session_id"],)).fetchone()[0]
                conn.execute("update sessions set vendor_session=coalesce(?, vendor_session), context_tokens=?,"
                             " total_tokens=total_tokens+?, wakes=wakes+1 where id=?",
                             (end.session, u.context, u.total, turn["session_id"]))
                # the pack may not have been read: re-send the snapshot next time. A context that fell sharply
                # means the vendor compacted (the signal every vendor shares, and dsh's only one)
                if end.status != "succeeded" or 0 < u.context < prev * self.cfg["compact_drop_ratio"]:
                    conn.execute("delete from seen where session_id=?", (turn["session_id"],))
            if turn["chain_id"]:
                conn.execute("update chains set tokens=tokens+? where id=?", (u.total, turn["chain_id"]))
        self.adapters.pop(turn["id"], None)
        thread = turn["chain_id"] and conn.execute("select thread_id from chains where id=?",
                                                   (turn["chain_id"],)).fetchone()[0]
        if turn["session_id"] and u.context >= self.cfg["session_notice_tokens"] and conn.execute(
                "update sessions set notified=1 where id=? and notified=0", (turn["session_id"],)).rowcount:
            mail.notice(conn, thread or mail.dm_id(agent["id"], HUMAN),
                        f"{agent['id']} session holds about {u.context // 1000}k tokens; one wake now costs about "
                        f"{u.total // 1000}k. A new session would start from the maintained alignment view "
                        "(handover pack ready) if you want one.", turn["chain_id"])
        if end.requeue == "hold":
            mail.notice(conn, mail.dm_id(agent["id"], HUMAN), f"{agent['id']} paused: {end.error}. Its messages are"
                                                              f" requeued; `xmuse resume --agent {agent['id']}` to retry.")
        elif end.requeue:
            pass  # retried in a fresh session right away
        elif end.retry_at:
            until = time.strftime("%H:%M", time.localtime(end.retry_at))
            mail.notice(conn, mail.dm_id(agent["id"], HUMAN), f"{agent['id']} hit its vendor usage limit; its messages"
                                                              f" are requeued and it resumes at {until}.")
        elif thread and end.status == "succeeded" and not end.note and conn.execute(
                "select 1 from messages where turn_id=?", (turn["id"],)).fetchone() is None:
            mail.notice(conn, thread, f"turn {turn['id']} of {agent['id']} ended without xmuse_send or xmuse_done;"
                                      " its reply, if any, reached no one", turn["chain_id"])
        elif thread and (end.status == "failed" or end.note):
            mail.notice(conn, thread, f"turn {turn['id']} of {agent['id']} {end.status}"
                                      f"{': ' + end.error if end.status == 'failed' else ''}"
                                      f"{' [' + end.note + ']' if end.note else ''}", turn["chain_id"])
        warn_at = {"chat": self.cfg["chat_warn_tokens"],
                   "code": self.cfg["code_warn_tokens"]}.get(u.mode)
        if end.status == "succeeded" and warn_at and u.total > warn_at:
            log.warning("%s wake over %s tokens: turn %s of %s used %s (input %s + cache_read %s"
                        " + cache_write %s + output %s)",
                        u.mode, warn_at, turn["id"], agent["id"], u.total,
                        u.input, u.cache_read, u.cache_write, u.output)
        self._on_kick()

    def _on_approval(self, agent_id, session: str, req: dict) -> None:
        conn = self.db()
        if agent_id is None:
            agent_id = (conn.execute("select agent_id from sessions where vendor_session=?", (session,)).fetchone()
                        or [None])[0]
        auto = shell_auto_ok(req.get("action"), req.get("resources"), self.shell_policy) and "opencode" in self.drivers
        with db.tx(conn):
            conn.execute("insert or ignore into approvals(id, agent_id, vendor_session, action, resources, created_at)"
                         " values(?,?,?,?,?,?)", (req["id"], agent_id, session, req.get("action"),
                                                  json.dumps(req.get("resources")), db.now()))
        if auto:  # not one of the consequential commands (env prefix stripped): no need to bother the human
            try:
                self.drivers["opencode"].approve(session, req["id"], "once", agent_id)
                with db.tx(conn):
                    conn.execute("update approvals set state='decided', decision='once', decided_at=? where id=?",
                                 (db.now(), req["id"]))
                log.info("auto-approved shell for %s: %s", agent_id, req.get("resources"))
                return
            except Exception:
                log.exception("auto-approve failed; asking the human")
        mail.notice(conn, mail.dm_id(agent_id or "unknown", HUMAN),
                    f"{agent_id} asks permission: {req.get('action')} {req.get('resources')} — the user decides: "
                    f"`xmuse approve {req['id']} once|always|reject` in their own terminal, or the desktop "
                    f"coordinator asks the user and relays the answer with xmuse_approve")

    # ---- cancel, sweep, recovery ---------------------------------------------------
    def stop(self, agent: str | None = None, thread: str | None = None) -> dict:
        conn = self.db()
        where, args = "1=1", []
        if agent:
            where, args = "d.recipient=?", [agent]
        if thread:
            where, args = where + " and m.thread_id=?", args + [thread]
        with db.tx(conn):
            n = conn.execute(f"update deliveries set state='canceled', updated_at=? where id in (select d.id from"
                             f" deliveries d join messages m on m.id=d.message_id where d.state in ('queued','held','blocked')"
                             f" and {where})", (db.now(), *args)).rowcount
            if not agent:
                conn.execute("update chains set state='stopped', note='stopped by human' where state != 'stopped'"
                             + (" and thread_id=?" if thread else ""), ([thread] if thread else []))
        running = db.rows(conn.execute(
            "select t.* from turns t left join chains c on c.id=t.chain_id where t.state='running'"
            + (" and t.agent_id=?" if agent else "") + (" and c.thread_id=?" if thread else ""),
            [x for x in (agent, thread) if x]))
        for t in running:
            self.adapters[t["id"]].interrupt(t["id"]) if t["id"] in self.adapters else \
                self._on_end(TurnEnd(t["id"], "interrupted", None, error="no live adapter"))
        return {"canceled_deliveries": n, "interrupted_turns": [t["id"] for t in running]}

    def sweep(self) -> None:
        conn = self.db()
        old = db.rows(conn.execute("select * from turns where state='running' and started_at<?",
                                   (db.now() - self.cfg["turn_timeout"],)))
        for t in old:
            if t["id"] in self.adapters:
                self.adapters[t["id"]].interrupt(t["id"])
        self._on_kick()

    def _recover(self) -> None:
        """Hub restart: turns that were running have no live adapter; requeue their messages."""
        conn = self.db()
        with db.tx(conn):
            for t in db.rows(conn.execute("select id from turns where state='running'")):
                conn.execute("update turns set state='failed', ended_at=?, error='hub restarted' where id=?",
                             (db.now(), t["id"]))
                conn.execute("update deliveries set state='queued', turn_id=null where turn_id=? and state='admitted'",
                             (t["id"],))
