"""Messages, threads and per-recipient deliveries (design §4.4 items 1 and 6).

`send` is the only trigger path (design §4.1 principle 3): one transaction writes the
message and one delivery per recipient, idempotently. Who gets woken is decided here;
when they are woken is the engine's job.
"""
import hashlib
import json

from . import db
from .config import HUB, HUMAN
from .tools import WHY_FIELDS, ToolError


def agents(conn) -> dict[str, dict]:
    return {a["id"]: a for a in db.rows(conn.execute("select * from agents order by id"))}


def dm_id(a: str, b: str) -> str:
    return "dm:" + "+".join(sorted((a, b)))


def running_turn(conn, agent_id: str) -> dict | None:
    return db.row(conn.execute(
        "select * from turns where agent_id=? and state='running' order by id desc limit 1", (agent_id,)))


def _thread(conn, sender: str, to: str, roster: dict) -> dict:
    if to.startswith("#"):
        t = db.row(conn.execute("select * from threads where id=?", (to,)))
        if t is None:
            conn.execute("insert into threads(id, kind, title, created_at) values(?,?,?,?)",
                         (to, "group", to[1:], db.now()))
            for m in [HUMAN, *roster]:
                conn.execute("insert into thread_members values(?,?)", (to, m))
            t = db.row(conn.execute("select * from threads where id=?", (to,)))
        conn.execute("insert or ignore into thread_members values(?,?)", (to, sender))
        return t
    if to != HUMAN and to not in roster:
        raise ToolError("unknown_recipient",
                        f"to must be one of: {', '.join([HUMAN, *roster])}, or '#group'; got {to!r}")
    if to == sender:
        raise ToolError("invalid_arguments", "to must not be yourself")
    tid = dm_id(sender, to)
    if conn.execute("select 1 from threads where id=?", (tid,)).fetchone() is None:
        conn.execute("insert into threads(id, kind, created_at) values(?,?,?)", (tid, "dm", db.now()))
        conn.executemany("insert into thread_members values(?,?)", [(tid, sender), (tid, to)])
    return db.row(conn.execute("select * from threads where id=?", (tid,)))


def members(conn, thread_id: str) -> list[str]:
    return [r[0] for r in conn.execute("select member from thread_members where thread_id=? order by member",
                                       (thread_id,))]


def send(conn, cfg: dict, sender: str, to: str, body: str, kind: str = "message",
         mentions: list | None = None, why: dict | None = None, idem: str | None = None) -> dict:
    """Write a message and its deliveries in one transaction. Returns the message (+duplicate flag)."""
    mentions = list(dict.fromkeys(mentions or []))
    if kind == "handoff":
        missing = [k for k in WHY_FIELDS if not (why or {}).get(k)]
        if missing:
            raise ToolError("invalid_arguments", f"kind=handoff needs why.{', why.'.join(missing)}")
    with db.tx(conn):
        roster = agents(conn)
        turn = running_turn(conn, sender) if sender in roster else None
        if idem is None and turn is not None:  # a retried tool call inside one turn is a duplicate
            idem = hashlib.sha256(json.dumps([turn["id"], to, kind, body]).encode()).hexdigest()[:32]
        if idem is not None:
            dup = db.row(conn.execute("select * from messages where sender=? and idem_key=?", (sender, idem)))
            if dup:
                return {**dup, "duplicate": True}
        thread = _thread(conn, sender, to, roster)
        mem = members(conn, thread["id"])
        bad = [m for m in mentions if m not in mem or m == HUMAN]
        if bad:
            raise ToolError("invalid_arguments", f"mentions must be members of {thread['id']}: "
                                                 f"{', '.join(m for m in mem if m not in (HUMAN, sender))}; got {bad}")
        chain, depth = _chain(conn, cfg, sender, thread["id"], turn)
        cur = conn.execute(
            "insert into messages(thread_id, sender, kind, body, why, mentions, chain_id, depth, turn_id,"
            " idem_key, created_at) values(?,?,?,?,?,?,?,?,?,?,?)",
            (thread["id"], sender, kind, body, json.dumps(why) if why else None, json.dumps(mentions),
             chain["id"], depth, turn and turn["id"], idem, db.now()))
        mid = cur.lastrowid
        if thread["kind"] == "dm":
            wake = {to} & set(roster)
        else:
            wake = (set(mentions) | ({thread["owner"]} if thread["owner"] else set())) & set(roster)
        wake.discard(sender)
        for r in mem:
            if r in (sender, HUMAN) or r not in roster:
                continue
            state = "passive" if r not in wake else ("queued" if chain["state"] == "open" else "held")
            conn.execute("insert into deliveries(message_id, recipient, wake, state, updated_at)"
                         " values(?,?,?,?,?)", (mid, r, int(r in wake), state, db.now()))
        return {**db.row(conn.execute("select * from messages where id=?", (mid,))), "woken": sorted(wake)}


def _chain(conn, cfg, sender, thread_id, turn) -> tuple[dict, int]:
    """Causal chain: a peer message continues the chain of the turn it was sent from."""
    if turn is not None and turn["chain_id"] is not None:
        chain = db.row(conn.execute("select * from chains where id=?", (turn["chain_id"],)))
        depth = conn.execute("select coalesce(max(m.depth), 0) from deliveries d join messages m"
                             " on m.id=d.message_id where d.turn_id=?", (turn["id"],)).fetchone()[0]
        return chain, depth + 1
    origin = "human" if sender == HUMAN else ("hub" if sender == HUB else f"agent:{sender}")
    cur = conn.execute("insert into chains(thread_id, origin, max_wakes, max_tokens, created_at) values(?,?,?,?,?)",
                       (thread_id, origin, cfg["max_chain_wakes"], cfg["max_chain_tokens"], db.now()))
    return db.row(conn.execute("select * from chains where id=?", (cur.lastrowid,))), 0


def notice(conn, thread_id: str, body: str, chain_id: int | None = None) -> None:
    """A hub notice in a thread: visible in `xmuse log` and inboxes, never wakes anyone."""
    with db.tx(conn):
        if chain_id is None:
            chain_id = conn.execute("insert into chains(thread_id, origin, state, max_wakes, max_tokens, created_at)"
                                    " values(?,?,?,?,?,?)", (thread_id, "hub", "stopped", 0, 0, db.now())).lastrowid
        conn.execute("insert into messages(thread_id, sender, kind, body, chain_id, created_at) values(?,?,?,?,?,?)",
                     (thread_id, HUB, "notice", body, chain_id, db.now()))


def inbox(conn, agent_id: str, unread_only: bool = True) -> list[dict]:
    q = ("select d.id did, d.wake, d.read_at, m.* from deliveries d join messages m on m.id=d.message_id"
         " where d.recipient=? and d.acked_at is null and d.state != 'canceled'"
         + (" and d.read_at is null" if unread_only else "") + " order by d.wake desc, m.id")
    rs = db.rows(conn.execute(q, (agent_id,)))
    with db.tx(conn):
        conn.executemany("update deliveries set read_at=? where id=? and read_at is null",
                         [(db.now(), r["did"]) for r in rs])
    return [_public(r) for r in rs]


def ack(conn, agent_id: str, ids: list[int], outcome: str | None) -> int:
    with db.tx(conn):
        n = 0
        for mid in ids:
            n += conn.execute("update deliveries set acked_at=?, outcome=?, read_at=coalesce(read_at, ?)"
                              " where recipient=? and message_id=?",
                              (db.now(), outcome, db.now(), agent_id, mid)).rowcount
        return n


def thread(conn, member: str, thread_id: str, query: str | None = None, limit: int = 20) -> dict:
    if member != HUMAN and member not in members(conn, thread_id):
        mine = [r[0] for r in conn.execute("select thread_id from thread_members where member=?", (member,))]
        raise ToolError("unknown_thread", f"id must be one of your threads: {', '.join(mine) or '(none)'}")
    sql, args = "select * from messages where thread_id=?", [thread_id]
    if query:
        sql, args = sql + " and body like ?", args + [f"%{query}%"]
    rs = db.rows(conn.execute(sql + " order by id desc limit ?", (*args, limit)))
    return {"thread": thread_id, "members": members(conn, thread_id), "messages": [_public(r) for r in reversed(rs)]}


def context(conn, agent_id: str, topic: str | None = None) -> dict:
    """Deterministic collaboration context (M1). M2 adds the MemoryOS-curated layer."""
    tids = [r[0] for r in conn.execute("select thread_id from thread_members where member=?", (agent_id,))]
    out = {"threads": []}
    for tid in tids:
        t = db.row(conn.execute("select * from threads where id=?", (tid,)))
        like = f"%{topic}%" if topic else "%"
        pick = lambda kinds, n: [_public(r) for r in reversed(db.rows(conn.execute(  # noqa: E731
            f"select * from messages where thread_id=? and kind in ({','.join('?' * len(kinds))}) and body like ?"
            " order by id desc limit ?", (tid, *kinds, like, n))))]
        out["threads"].append({
            "id": tid, "owner": t["owner"], "members": members(conn, tid),
            "decisions": pick(["decision"], 10), "handoffs": pick(["handoff"], 3),
            "open_questions": [q for q in pick(["question"], 10) if not conn.execute(
                "select 1 from deliveries where message_id=? and acked_at is not null", (q["id"],)).fetchone()],
            "last_done": pick(["done"], 2)})
    return out


def whoami(conn, agent_id: str, workspace: str) -> dict:
    roster = agents(conn)
    me = roster[agent_id]
    return {"id": agent_id, "vendor": me["vendor"], "family": me["family"], "role": me["role"],
            "workspace": workspace,
            "peers": [{"id": a["id"], "family": a["family"], "role": a["role"]}
                      for a in roster.values() if a["id"] != agent_id] + [{"id": HUMAN, "role": "the user"}],
            "threads": [r[0] for r in conn.execute("select thread_id from thread_members where member=?", (agent_id,))]}


def done(conn, agent_id: str, summary: str, nxt: str) -> dict:
    """Exit check: record it on the running turn and post it to the chain's thread (no wake)."""
    turn = running_turn(conn, agent_id)
    with db.tx(conn):
        if turn is None or turn["chain_id"] is None:
            tid = dm_id(agent_id, HUMAN)
            if conn.execute("select 1 from threads where id=?", (tid,)).fetchone() is None:
                conn.execute("insert into threads(id, kind, created_at) values(?,?,?)", (tid, "dm", db.now()))
                conn.executemany("insert into thread_members values(?,?)", [(tid, agent_id), (tid, HUMAN)])
            chain = conn.execute("insert into chains(thread_id, origin, max_wakes, max_tokens, created_at)"
                                 " values(?,?,0,0,?)", (tid, f"agent:{agent_id}", db.now())).lastrowid
        else:
            chain = turn["chain_id"]
            tid = conn.execute("select thread_id from chains where id=?", (chain,)).fetchone()[0]
            conn.execute("update turns set summary=? where id=?", (f"{summary} | next: {nxt}", turn["id"]))
        depth = 0 if turn is None else conn.execute(
            "select coalesce(max(m.depth), -1) + 1 from deliveries d join messages m on m.id=d.message_id"
            " where d.turn_id=?", (turn["id"],)).fetchone()[0]
        conn.execute("insert into messages(thread_id, sender, kind, body, chain_id, depth, turn_id, created_at)"
                     " values(?,?,?,?,?,?,?,?)", (tid, agent_id, "done", f"{summary}\nnext: {nxt}", chain, depth,
                                                  turn and turn["id"], db.now()))
    return {"recorded": True, "thread": tid}


def _public(r: dict) -> dict:
    out = {"id": r["id"], "thread": r["thread_id"], "from": r["sender"], "kind": r["kind"], "body": r["body"]}
    if r.get("why"):
        out["why"] = json.loads(r["why"])
    if r.get("mentions") and r["mentions"] != "[]":
        out["mentions"] = json.loads(r["mentions"])
    if "wake" in r:
        out["mentioned"] = bool(r["wake"])
    return out
