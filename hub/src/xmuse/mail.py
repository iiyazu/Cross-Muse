"""Messages, threads and per-recipient deliveries (design §4.4 items 1 and 6).

`send` is the only trigger path (design §4.1 principle 3): one transaction writes the
message and one delivery per recipient, idempotently. Who gets woken is decided here;
when they are woken is the engine's job.
"""
import hashlib
import json
import re

from . import align, db, dispatch, route, share, threads
from . import evidence as ev
from .config import HUB, HUMAN, info_on
from .tools import DECLARE, WHY_FIELDS, ToolError

# A retried tool call resends identical content: same-turn retries, and replays when a killed
# turn resumes in a later turn (M1b report section 6 item 3). Collapse those, but only against
# the current turn or an interrupted turn nobody has handled since (a later succeeded turn
# means the content was seen; repeating it then, e.g. ping-pong "again", is a new message).
# An explicit idem_key (human `--idem`) stays permanent.


def agents(conn) -> dict[str, dict]:
    """The roster: members still in the room (a removed member keeps its history but gets no mail)."""
    return {a["id"]: a for a in db.rows(conn.execute("select * from agents where removed=0 order by id"))}


def dm_id(a: str, b: str) -> str:
    return "dm:" + "+".join(sorted((a, b)))


def running_turn(conn, agent_id: str) -> dict | None:
    return db.row(conn.execute(
        "select * from turns where agent_id=? and state='running' order by id desc limit 1", (agent_id,)))


def _thread(conn, sender: str, to: str, roster: dict, new_members: list | None = None) -> dict:
    if to.startswith("#"):
        t = db.row(conn.execute("select * from threads where id=?", (to,)))
        if t is None and new_members is not None:  # a member opens a private group (T2); the user is in it too
            return threads.create(conn, to, sender, new_members, set(roster))
        if t is None:
            conn.execute("insert into threads(id, kind, title, created_at) values(?,?,?,?)",
                         (to, "group", to[1:], db.now()))
            for m in [HUMAN, *roster]:
                conn.execute("insert into thread_members values(?,?)", (to, m))
            t = db.row(conn.execute("select * from threads where id=?", (to,)))
        if t["private"]:  # only its members write to it
            if sender not in members(conn, to):
                raise ToolError("not_a_member", f"{to} is a private group you are not in")
            return t
        if conn.execute("insert or ignore into thread_members values(?,?)", (to, sender)).rowcount:
            threads.resync(conn, sender, to)  # joined: the next wake injects a snapshot including this thread
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


def _desktop_agents(conn) -> list[str]:
    return [a["id"] for a in db.rows(conn.execute("select id, settings from agents order by id"))
            if db.settings(a).get("desktop")]


def _foreground_agents(conn) -> list[str]:
    """dsh foreground agents: never woken by the hub; the bundle's relay pushes their mail into the bound session."""
    return [a["id"] for a in db.rows(conn.execute("select id, settings from agents order by id"))
            if db.settings(a).get("foreground")]


def _to_coordinators(conn, mid: int, thread_id: str, sender: str) -> None:
    """The desktop coordinator is the user's interface: whatever reaches  also lands, unread and never
    woken, in each coordinator's inbox (unless it sent it or already has a delivery of it)."""
    if sender == HUMAN or HUMAN not in members(conn, thread_id):
        return
    for a in _desktop_agents(conn):
        if a != sender and threads.can_see(conn, a, thread_id) and not conn.execute(
                "select 1 from deliveries where message_id=? and recipient=?", (mid, a)).fetchone():
            conn.execute("insert into deliveries(message_id, recipient, wake, state, updated_at)"
                         " values(?,?,0,'passive',?)", (mid, a, db.now()))


def send(conn, cfg: dict, sender: str, to: str, body: str, kind: str = "message",
         mentions: list | None = None, why: dict | None = None, idem: str | None = None, scope: str | None = None,
         supersedes: str | None = None, resolves: list | None = None, depends_on: list | None = None, via: str | None = None,
         new_members: list | None = None, notify: str | None = None, reply_to: int | None = None) -> dict:
    """Write a message and its deliveries in one transaction. Returns the message (+duplicate flag).
    `new_members`: sending to a '#group' that does not exist yet makes it a private group of these members.
    `notify` (a host's handoff): batch | now, when the assignee's result wakes the host (dispatch.py).
    `reply_to` (T8a H9): the message this one answers; whoever it mentioned, DM'd or handed work to wakes them."""
    mentions = list(dict.fromkeys(mentions or []))
    if notify is not None and (kind != "handoff" or notify not in ("batch", "now")):
        raise ToolError("invalid_arguments", "notify is batch or now, and needs kind=handoff")
    if not info_on(cfg) and (kind != "message" or scope or supersedes or resolves or depends_on or why):
        # T-plain (T14): agents are not offered these (tools_for); refuse them from every other path too
        raise ToolError("invalid_arguments", "the information layer is off in this workspace: plain messages only "
                                             "(kind=message, no scope/supersedes/resolves/depends_on/why)")
    if kind == "handoff":
        missing = [k for k in WHY_FIELDS if not (why or {}).get(k)]
        if missing:
            raise ToolError("invalid_arguments", f"kind=handoff needs why.{', why.'.join(missing)}")
    if supersedes and kind not in DECLARE:
        raise ToolError("invalid_arguments", "supersedes needs kind=decision|assumption|question")
    if scope and kind not in DECLARE and kind != "handoff":
        raise ToolError("invalid_arguments", "scope needs kind=decision|assumption|question (or handoff: module:<name>)")
    modules = align.modules_of(scope) if kind == "handoff" else []
    if kind == "handoff" and scope and not modules:
        raise ToolError("invalid_arguments", f"a handoff's scope names the modules the assignee owns: "
                                             f"module:<name>[,<name>...]; got {scope!r}")
    if depends_on and kind != "handoff":
        raise ToolError("invalid_arguments", "depends_on needs kind=handoff")
    with db.tx(conn):
        roster = agents(conn)
        turn = running_turn(conn, sender) if sender in roster else None
        if idem is not None:
            dup = db.row(conn.execute("select * from messages where sender=? and idem_key=?", (sender, idem)))
            if dup:
                return {**dup, "duplicate": True}
        thread = _thread(conn, sender, to, roster, new_members)
        if idem is None and turn is not None:
            dup = db.row(conn.execute(
                "select m.* from messages m left join turns t0 on t0.id = m.turn_id"
                " where m.sender = ? and m.thread_id = ? and m.kind = ? and m.body = ?"
                " and m.mentions = ? and (m.turn_id = ? or (t0.state = 'interrupted' and not exists ("
                " select 1 from turns t2 where t2.agent_id = m.sender and t2.started_at > m.created_at"
                " and t2.state = 'succeeded')))"
                " order by m.id desc",
                (sender, thread["id"], kind, body, json.dumps(mentions), turn["id"])))
            if dup:
                return {**dup, "duplicate": True}
        mem = members(conn, thread["id"])
        bad = [m for m in mentions if m not in mem or m == HUMAN]
        if bad:
            raise ToolError("invalid_arguments", f"mentions must be members of {thread['id']}: "
                                                 f"{', '.join(m for m in mem if m not in (HUMAN, sender))}; got {bad}")
        chain, depth = _chain(conn, cfg, sender, thread["id"], turn)
        orig = None
        if reply_to is not None:
            if isinstance(reply_to, bool) or not isinstance(reply_to, int):
                raise ToolError("bad_request", "reply_to must be a message id")
            orig = db.row(conn.execute("select * from messages where id=?", (reply_to,)))
            if orig is None:
                raise ToolError("bad_reply_to", f"no message {reply_to}")
        cur = conn.execute(
            "insert into messages(thread_id, sender, kind, body, why, mentions, chain_id, depth, turn_id,"
            " idem_key, created_at, via, reply_to) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (thread["id"], sender, kind, body, json.dumps(why) if why else None, json.dumps(mentions),
             chain["id"], depth, turn and turn["id"], idem, db.now(), via, reply_to))
        mid = cur.lastrowid
        # T8a H8: a user's unaddressed group message is a broadcast (DMs are not).
        broadcast = sender == HUMAN and kind == "message" and not mentions and thread["kind"] != "dm"
        if thread["kind"] == "dm":
            wake = {to} & set(roster)
        elif broadcast:
            # A broadcast wakes every agent member of the group (host included).
            # A desktop host is never woken by the hub itself; it keeps a wake delivery the mod picks up.
            wake = set(mem) & set(roster)
        elif cfg["wake"] == "all":
            wake = set(mem) & set(roster)
        else:
            wake = (set(mentions) | ({thread["owner"]} if thread["owner"] else set())) & set(roster)
        wake |= _routed(conn, sender, kind, supersedes, resolves) & set(mem) & set(roster)
        wake.discard(sender)
        wake.discard(via)  # the relaying coordinator is not a recipient of its own message
        routed = None if broadcast \
            else dispatch.route(conn, sender, via, kind, thread, mentions)  # the user's unaddressed words: host only
        if routed:
            wake = {routed}
        picked = route.pick(conn, sender, kind, thread, mentions, body) \
            if info_on(cfg) and cfg.get("route_by_duty", False) else {}  # T8a H8: duty routing is opt-in
        if picked:  # the best-matching members, plus whoever handed the asker its work (as for any question)
            wake = set(picked) | (_routed(conn, sender, kind, supersedes, resolves) & set(mem) & set(roster))
            conn.execute("update messages set route_to=?, route_reason=? where id=?",
                         (json.dumps(sorted(picked)), route.reason(picked), mid))
        if orig is not None:
            wake |= _reply_wake(conn, sender, orig)  # a reply also wakes whoever it answers
        for r in mem:
            if r in (sender, HUMAN, via) or r not in roster:
                continue
            state = "passive" if r not in wake else ("queued" if chain["state"] == "open" else "held")
            conn.execute("insert into deliveries(message_id, recipient, wake, state, updated_at)"
                         " values(?,?,?,?,?)", (mid, r, int(r in wake), state, db.now()))
        _to_coordinators(conn, mid, thread["id"], sender)
        if kind in ("question", "handoff") and sender in roster:  # T3: hint a holder of a related user DM (no wake)
            share.suggest(conn, mid, sender, " ".join([body, *map(str, (why or {}).values())]))
        if kind in DECLARE:
            eids = [align.declare(conn, sender, thread["id"], mid, kind, body, scope, supersedes, via)]
        elif kind == "handoff":  # one assignment per named peer (a DM names its peer)
            eids = align.assign(conn, sender, thread["id"], mid, body,
                                mentions or (sorted(wake) if thread["kind"] == "dm" else []), depends_on or [], via,
                                modules)
        else:
            eids = []
        align.resolve(conn, resolves or [])
        blocked = []
        if kind == "handoff" and depends_on:  # no work is handed out before what it needs is there (T14)
            for e in db.rows(conn.execute(f"select * from entries where id in ({','.join('?' * len(eids))})", eids)):
                if align._blocked(conn, e) and conn.execute(
                        "update deliveries set state='blocked', updated_at=? where message_id=? and recipient=?"
                        " and state in ('queued','held')", (db.now(), mid, e["assignee"])).rowcount:
                    blocked.append(e["assignee"])
        held = dispatch.on_send(conn, cfg, mid, sender, kind, wake - set(blocked), eids, notify)
        released = align.release(conn) if info_on(cfg) else []
        fg = set(_foreground_agents(conn))
        wake = wake - set(blocked) - held
        return {**db.row(conn.execute("select * from messages where id=?", (mid,))),
                # the hub never wakes a coordinator or a foreground agent; the latter gets the message pushed
                "woken": sorted(wake - set(_desktop_agents(conn)) - fg), "pushed": sorted(wake & fg),
                "entries": [f"E{i}" for i in eids], **({"routed_to": routed} if routed and not picked else {}),
                **({"routed_to": sorted(picked)} if picked else {}),
                **({"blocked": blocked} if blocked else {}), **({"released": released} if released else {})}


def _reply_wake(conn, sender: str, orig: dict) -> set[str]:
    """T8a H9: a reply wakes whoever the answered message was for. Eligible when it mentioned the replier,
    was DM'd to the replier, or is a handoff assigned to the replier. A reply to the user's own message wakes
    nobody (there is no delivery to the user); the view marks it for_me for the human reader instead."""
    om = json.loads(orig["mentions"] or "[]")
    eligible = sender in om or _dm_with(conn, orig, sender) or _assigned_to(conn, orig["id"], sender)
    if not eligible:
        return set()
    return set() if orig["sender"] == HUMAN else {orig["sender"]}


def _dm_with(conn, orig: dict, sender: str) -> bool:
    t = db.row(conn.execute("select * from threads where id=?", (orig["thread_id"],)))
    return bool(t) and t["kind"] == "dm" and orig["sender"] != sender and \
        sender in members(conn, t["id"])


def _assigned_to(conn, mid: int, sender: str) -> bool:
    return bool(conn.execute("select 1 from entries where kind='assignment' and assignee=? and refs=?"
                            " and status='active'", (sender, json.dumps([mid]))).fetchone())


def _routed(conn, sender: str, kind: str, supersedes: str | None, resolves: list | None) -> set[str]:
    """Who the information layer wakes beyond mentions (T14): a question goes to whoever planned the asker's work
    (authors of its live assignments); an entry that replaces or resolves a question wakes the question's author."""
    out = set()
    if kind == "question":
        out |= {r[0] for r in conn.execute("select distinct author from entries where kind='assignment' and assignee=?"
                                           " and status='active'", (sender,))}
    for ref in [supersedes, *(resolves or [])]:
        m = ref and re.fullmatch(r"E?(\d+)", str(ref))
        r = m and conn.execute("select author from entries where id=? and kind='question'", (m[1],)).fetchone()
        if r:
            out.add(r[0])
    return out


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
        mid = conn.execute("insert into messages(thread_id, sender, kind, body, chain_id, created_at)"
                           " values(?,?,?,?,?,?)", (thread_id, HUB, "notice", body, chain_id, db.now())).lastrowid
        for a in db.rows(conn.execute("select id, settings from agents order by id")):
            # the coordinator relays approvals/pauses to the user; never woken; private groups: members only
            if db.settings(a).get("desktop") and threads.can_see(conn, a["id"], thread_id):
                conn.execute("insert or ignore into deliveries(message_id, recipient, wake, state, updated_at)"
                             " values(?,?,0,'passive',?)", (mid, a["id"], db.now()))


def inbox(conn, agent_id: str, unread_only: bool = True) -> list[dict]:
    q = ("select d.id did, d.wake, d.read_at, m.* from deliveries d join messages m on m.id=d.message_id"
         " where d.recipient=? and d.acked_at is null and d.state != 'canceled'"
         + (" and d.read_at is null" if unread_only else "") + " order by d.wake desc, m.id")
    rs = db.rows(conn.execute(q, (agent_id,)))
    with db.tx(conn):
        conn.executemany("update deliveries set read_at=? where id=? and read_at is null",
                         [(db.now(), r["did"]) for r in rs])
    return [_public(r) for r in rs]


def pending(conn, agent_id: str) -> dict:
    """Unread deliveries (what  would return) and how many of them mention the agent. Read-only."""
    rs = conn.execute("select m.mentions from deliveries d join messages m on m.id=d.message_id"
                      " where d.recipient=? and d.acked_at is null and d.read_at is null and d.state != 'canceled'",
                      (agent_id,)).fetchall()
    return {"pending": len(rs), "mentions": sum(agent_id in json.loads(r[0]) for r in rs)}


def ack(conn, agent_id: str, ids: list[int], outcome: str | None) -> int:
    with db.tx(conn):
        n = 0
        for mid in ids:
            n += conn.execute("update deliveries set acked_at=?, outcome=?, read_at=coalesce(read_at, ?)"
                              " where recipient=? and message_id=?",
                              (db.now(), outcome, db.now(), agent_id, mid)).rowcount
        return n


def thread(conn, member: str, thread_id: str, query: str | None = None, limit: int = 20) -> dict:
    desk = (member in _desktop_agents(conn) and HUMAN in members(conn, thread_id)  # the user's interface reads the user's threads
            and not threads.is_private(conn, thread_id))
    if member != HUMAN and not desk and member not in members(conn, thread_id):
        mine = [r[0] for r in conn.execute("select thread_id from thread_members where member=?", (member,))]
        raise ToolError("unknown_thread", f"id must be one of your threads: {', '.join(mine) or '(none)'}")
    sql, args = "select * from messages where thread_id=?", [thread_id]
    if query:
        sql, args = sql + " and body like ?", args + [f"%{query}%"]
    rs = db.rows(conn.execute(sql + " order by id desc limit ?", (*args, limit)))
    return {"thread": thread_id, "members": members(conn, thread_id), "messages": [_public(r) for r in reversed(rs)]}


def whoami(conn, agent_id: str, workspace: str) -> dict:
    roster = agents(conn)
    me = roster[agent_id]
    return {"id": agent_id, "vendor": me["vendor"], "family": me["family"], "role": me["role"],
            "workspace": workspace,
            "peers": [{"id": a["id"], "family": a["family"], "role": a["role"],
                       **({"description": a["description"]} if a.get("description") else {})}
                      for a in roster.values() if a["id"] != agent_id] + [{"id": HUMAN, "role": "the user"}],
            "threads": [r[0] for r in conn.execute("select thread_id from thread_members where member=?", (agent_id,))]}


def done(conn, agent_id: str, summary: str, nxt: str, declares: list | None = None, stage: str | None = None,
         outcome: str | None = None, evidence: list | None = None, cfg: dict | None = None) -> dict:
    """Exit check: record it on the running turn and post it to the chain's thread. It wakes no one, except that a
    result for the room's host reaches the host by its outcome label (dispatch.on_done). `stage`: the
    plan-split-integrate phase this ends (preset.py reads it from messages.stage). `evidence` is checked against the
    turn's log and stored with the message; an unverified claim makes the hub relabel the done blocked. With `cfg`
    (review_gate on), a finished task (next none, outcome completed) is handed to the room's reviewer (evidence.py)."""
    turn = running_turn(conn, agent_id)
    evidence = evidence or None
    key = turn and "done:%d:%s" % (turn["id"], hashlib.sha1(json.dumps(
        [summary, nxt, declares, stage] + ([outcome] if outcome else []) + ([evidence] if evidence else []))
        .encode()).hexdigest())
    verdict = ev.check(conn, turn, evidence) if evidence else None
    with db.tx(conn):
        dup = key and db.row(conn.execute("select id, thread_id from messages where sender=? and idem_key=?",
                                          (agent_id, key)))
        if dup:  # a retried done in the same turn: return the earlier result, declare nothing twice
            eids = [r[0] for r in conn.execute("select id from entries where refs=? order by id", (json.dumps([dup["id"]]),))]
            return {"recorded": True, "thread": dup["thread_id"], "duplicate": True,
                    **({"entries": [f"E{i}" for i in eids]} if eids else {})}
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
        mid = conn.execute("insert into messages(thread_id, sender, kind, body, chain_id, depth, turn_id, idem_key,"
                           " created_at, stage) values(?,?,?,?,?,?,?,?,?,?)",
                           (tid, agent_id, "done", f"{summary}\nnext: {nxt}", chain, depth, turn and turn["id"], key,
                            db.now(), stage)).lastrowid
        _to_coordinators(conn, mid, tid, agent_id)
        eids = [align.declare(conn, agent_id, tid, mid, d["kind"], d["statement"], d.get("scope"), d.get("supersedes"))
                for d in declares or []]
        if eids:
            align.release(conn)
        if verdict:
            ev.record(conn, mid, evidence, *verdict)
        labelled = dispatch.on_done(conn, cfg, mid, agent_id, nxt, outcome, declares, *(verdict or (None, None)))
        final = conn.execute("select outcome from messages where id=?", (mid,)).fetchone()[0]
    # only finished work goes to review: a done the member or the hub labelled otherwise is not finished
    reviewer = cfg and final == "completed" and ev.request_review(conn, cfg, agent_id, mid, summary, nxt)
    return {"recorded": True, "thread": tid, **({"entries": [f"E{i}" for i in eids]} if eids else {}),
            **({"evidence_status": verdict[0], "evidence_problems": verdict[1]} if verdict else {}),
            **({"review": reviewer} if reviewer else {}), **labelled}


def _public(r: dict) -> dict:
    out = {"id": r["id"], "thread": r["thread_id"], "from": r["sender"], "kind": r["kind"], "body": r["body"]}
    if r.get("why"):
        out["why"] = json.loads(r["why"])
    if r.get("mentions") and r["mentions"] != "[]":
        out["mentions"] = json.loads(r["mentions"])
    if r.get("via"):
        out["via"] = r["via"]
    if "wake" in r:
        out["mentioned"] = bool(r["wake"])
    return out
