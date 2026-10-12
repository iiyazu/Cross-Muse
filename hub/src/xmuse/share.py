"""Sharing the user's private messages (T3, contract docs/design/XMUSE2-VIEW-API.zh.md 8.6).

What the user sends a member in a DM (thread dm:<member>+human, sender human) stays with that member. The member
may ask to share it (`xmuse_share`): if the user marked the message shareable it is delivered at once, else the
request becomes a pending approval (approvals[] kind "share", id "share:<n>", stored in the approvals table) that the
user answers once / always / reject. A delivered share is an ordinary message from the member to the target with
via "shared" and shared_from {member, message_id}. Suggestions are rule based and only ever add a line to a wake
pack (never a wake of their own): a teammate's question or handoff that mentions an identifier found in a user DM
queues a hint for the DM's holder.
"""
import json
import re

from . import db
from .config import HUMAN
from .tools import ToolError

EXCERPT = 200
HINTS_PER_WAKE = 3


# ---- what may be shared ----------------------------------------------------------------------------------------

def user_dm(conn, mid) -> tuple[dict, str] | None:
    """(message, holder) when `mid` is a user's private message to a member, else None."""
    m = db.row(conn.execute("select * from messages where id=?", (mid,))) if isinstance(mid, int) \
        and not isinstance(mid, bool) else None
    if m is None or m["sender"] != HUMAN or not m["thread_id"].startswith("dm:"):
        return None
    ms = [r[0] for r in conn.execute("select member from thread_members where thread_id=?", (m["thread_id"],))]
    return (m, next(x for x in ms if x != HUMAN)) if len(ms) == 2 and HUMAN in ms else None


def target(conn, me: str, to, member_check: bool = True) -> str:
    """A member id or an existing thread (`me` must be in it, unless the operator names it); a `dm:` id means its
    other end."""
    from . import mail
    if not isinstance(to, str) or not to:
        raise ToolError("invalid_arguments", "to must be a member id or a thread id")
    if to.startswith("dm:"):
        ends = to[3:].split("+")
        if len(ends) == 2 and me in ends:
            to = ends[0] if ends[1] == me else ends[1]
    roster = mail.agents(conn)
    if to in roster and to != me:
        return to
    if to.startswith("#") and conn.execute("select 1 from threads where id=?", (to,)).fetchone() and (
            not member_check or me in mail.members(conn, to)):
        return to
    peers = ", ".join(x for x in roster if x != me)
    raise ToolError("unknown_recipient", f"to must be a member other than yourself ({peers}) or a thread you are in")


def marked(conn, mid: int, to: str | None = None) -> bool:
    """The user released the message: for anyone (target ''), or for this target."""
    return bool(conn.execute("select 1 from share_marks where message_id=? and target in ('', ?)",
                             (mid, to or "")).fetchone())


def mark(conn, mid, to=None) -> dict:
    """act share_mark (operator): release one user DM, for `to` or for anyone."""
    if not isinstance(mid, int) or isinstance(mid, bool):
        raise ToolError("invalid_arguments", "share_mark needs message_id (integer)")
    if conn.execute("select 1 from messages where id=?", (mid,)).fetchone() is None:
        raise ToolError("unknown_message", f"no message {mid}")
    dm = user_dm(conn, mid)
    if dm is None:
        raise ToolError("not_shareable", f"#{mid} is not a user's private message to a member")
    t = target(conn, dm[1], to, False) if to else ""
    with db.tx(conn):
        conn.execute("insert or ignore into share_marks values(?,?,?)", (mid, t, db.now()))
    return {"ok": True}


# ---- request, approval, delivery -------------------------------------------------------------------------------

def request(conn, cfg: dict, me: str, args: dict) -> dict:
    """xmuse_share {message_id, to, why}: deliver at once if released, else ask the user."""
    dm = user_dm(conn, args["message_id"])
    if dm is None or dm[1] != me:
        raise ToolError("not_shareable", "403 not_shareable: you can only share a private message the user sent you")
    m, to = dm[0], target(conn, me, args["to"])
    if marked(conn, m["id"], to):
        return deliver(conn, cfg, me, m, to)
    for a in db.rows(conn.execute("select * from approvals where id like 'share:%' and state='pending' and agent_id=?",
                                  (me,))):
        d = json.loads(a["resources"])
        if d["message_id"] == m["id"] and d["to"] == to:  # asked already: one question for the user
            return {"status": "pending_approval", "approval": a["id"]}
    detail = {"message_id": m["id"], "to": to, "why": args["why"], "excerpt": m["body"][:EXCERPT]}
    with db.tx(conn):
        n = conn.execute("select coalesce(max(cast(substr(id, 7) as integer)), 0) + 1 from approvals"
                         " where id like 'share:%'").fetchone()[0]
        conn.execute("insert into approvals(id, agent_id, action, resources, created_at) values(?,?,?,?,?)",
                     (f"share:{n}", me, "share", json.dumps(detail, ensure_ascii=False), db.now()))
    return {"status": "pending_approval", "approval": f"share:{n}"}


def approvals(conn) -> list[dict]:
    """The pending share requests as sidebar approvals[] items."""
    out = []
    for a in db.rows(conn.execute("select * from approvals where id like 'share:%' and state='pending'"
                                  " order by created_at, id")):
        d = json.loads(a["resources"])
        out.append({"id": a["id"], "kind": "share", "member": a["agent_id"],
                    "summary": f"{a['agent_id']} 想把 #{d['message_id']} 分享给 {d['to']}"[:200], "detail": d,
                    "risk": "normal", "at": a["created_at"]})
    return out


def decide(conn, cfg: dict, aid: str, decision: str) -> dict:
    """The user's answer to a share request. once: deliver; always: deliver and release the message for anyone;
    reject: tell the requester."""
    a = db.row(conn.execute("select * from approvals where id=? and action='share'", (aid,)))
    if a is None:
        raise ToolError("unknown_approval", f"no approval {aid}")
    if a["state"] == "decided":
        raise ToolError("invalid_arguments", f"approval {aid} was already decided ({a['decision']})")
    d, me = json.loads(a["resources"]), a["agent_id"]
    with db.tx(conn):  # claim it: two answers racing deliver once
        if not conn.execute("update approvals set state='decided', decision=?, decided_at=? where id=?"
                            " and state='pending'", (decision, db.now(), aid)).rowcount:
            raise ToolError("invalid_arguments", f"approval {aid} was already decided")
    if decision == "reject":
        _tell(conn, me, f"The user rejected your request {aid} to share #{d['message_id']} with {d['to']}.")
        return {"status": "rejected"}
    try:
        if decision == "always":
            with db.tx(conn):
                conn.execute("insert or ignore into share_marks values(?,?,?)", (d["message_id"], "", db.now()))
        out = deliver(conn, cfg, me, db.row(conn.execute("select * from messages where id=?", (d["message_id"],))),
                      d["to"])
    except Exception:
        with db.tx(conn):  # nothing was delivered: the request stays open
            conn.execute("update approvals set state='pending', decision=null, decided_at=null where id=?", (aid,))
        raise
    _tell(conn, me, f"The user approved your request {aid} ({decision}): #{d['message_id']} was delivered to "
                    f"{d['to']}.")
    return out


def deliver(conn, cfg: dict, me: str, m: dict, to: str) -> dict:
    """The user's original text goes to `to` as a message from the member, with its provenance."""
    from . import mail
    body = (f"[shared by {me}: the user's private message #{m['id']} to them, released with the user's approval]\n"
            + m["body"])
    out = mail.send(conn, cfg, me, to, body, via="shared")
    with db.tx(conn):
        conn.execute("update messages set shared_from=? where id=?",
                     (json.dumps({"member": me, "message_id": m["id"]}), out["id"]))
    return {"status": "delivered", "id": out["id"], "thread": out["thread_id"], "woken": out.get("woken", [])}


def _tell(conn, member: str, text: str) -> None:
    """A hub notice in the member's DM with the user (as every approval decision does), also unread in its inbox."""
    from . import mail
    tid = mail.dm_id(member, HUMAN)
    mail.notice(conn, tid, text)
    with db.tx(conn):
        mid = conn.execute("select max(id) from messages where thread_id=? and kind='notice'", (tid,)).fetchone()[0]
        conn.execute("insert or ignore into deliveries(message_id, recipient, wake, state, updated_at)"
                     " values(?,?,0,'passive',?)", (mid, member, db.now()))


# ---- suggestions -----------------------------------------------------------------------------------------------

def idents(text: str) -> set[str]:
    """Key names in a text: identifiers of 3+ characters that look like code (snake_case, camelCase, CONSTANTS, with a
    digit), and numbers of 3+ digits. Plain words would match everything."""
    code = lambda t: "_" in t.strip("_") or re.search(r"\d|[a-z][A-Z]", t) or t.isupper()  # noqa: E731
    out = {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text) if len(t) >= 3 and code(t)}
    return out | set(re.findall(r"(?<![\w.])\d{3,}(?!\w)", text))


def released(conn, dm_id: int) -> bool:
    """Already shareable or already shared (a share needs no suggestion any more)."""
    return bool(conn.execute("select 1 from share_marks where message_id=? and target=''", (dm_id,)).fetchone()
                or conn.execute("select 1 from messages where json_extract(shared_from, '$.message_id')=?",
                                (dm_id,)).fetchone())


def suggest(conn, qid: int, asker: str, text: str) -> None:
    """A member's question or handoff (message `qid`): queue a hint for each holder of a user DM sharing an
    identifier with it. Writes no delivery, so nobody is woken by it."""
    from . import mail
    terms = idents(text)
    if not terms:
        return
    roster = mail.agents(conn)
    for r in conn.execute("select m.id, m.body, h.member holder from messages m join threads t on t.id=m.thread_id"
                          " and t.kind='dm' join thread_members h on h.thread_id=m.thread_id and h.member != ?"
                          " where m.sender=? order by m.id desc limit 200", (HUMAN, HUMAN)).fetchall():
        if r["holder"] == asker or r["holder"] not in roster or not idents(r["body"]) & terms:
            continue
        if released(conn, r["id"]):
            continue
        conn.execute("insert or ignore into share_hints(dm_id, question_id, holder, asker) values(?,?,?,?)",
                     (r["id"], qid, r["holder"], asker))


def hints(x) -> str:
    """Wake pack processor: each queued hint for this agent, once. Placed after the passive section."""
    conn, me = x.conn, x.agent["id"]
    lines, keys = [], []
    for h in db.rows(conn.execute("select * from share_hints where holder=? and shown=0 order by question_id, dm_id",
                                  (me,))):
        if released(conn, h["dm_id"]):
            continue
        if len(lines) == HINTS_PER_WAKE:
            break
        lines.append(f"你有一条用户私信（#{h['dm_id']}）可能与 {h['asker']} 的问题有关，需要的话用 xmuse_share 申请")
        keys.append((h["dm_id"], h["question_id"]))
    if keys:
        with db.tx(conn):
            conn.executemany("update share_hints set shown=1 where dm_id=? and question_id=?", keys)
    return "\n".join(lines)
