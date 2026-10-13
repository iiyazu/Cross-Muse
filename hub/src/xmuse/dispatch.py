"""Host dispatch and outcome labels (contract XMUSE2-VIEW-API §8.4; design XMUSE2-TOPO T0).

The host (room.host) takes the user's unaddressed words, hands work out with kind=handoff and checks what comes back;
everyone else does the work. A host wake is the expensive thing, so members' results are labelled and the host is
woken by label:
  - needs_alignment, blocked, a question: at once;
  - progress: never (a passive delivery);
  - completed: once per batch. The batch is the host's handoffs still out; it is released when all are back, or
    host_batch_max_s after its first held result, or with any other wake of the host, or by the act wake_host.
    A handoff sent with notify="now" releases it as soon as that task comes back.

A held result has no delivery to the host at all, only a dispatch_holds row: nothing that wakes, counts or lists
mail sees it (engine admission, a sidebar's for_me and unread, xmuse_inbox, the desktop hook's pending count). Release
writes the ordinary wake delivery, which then runs the usual paths (chain caps included). `settle` decides and runs
inside every send and done, on every engine kick (so also on the periodic sweep) and on wake_host.

Which handoff a result answers: dispatches rows (one per handoff assignee) are opened when the host sends a handoff.
A member's done returns the open ones whose handoff it has already seen (delivered into a hub turn, read with
xmuse_inbox, acked, or pushed by the relay); if it has seen none, the oldest open one that is not blocked.
"""
from . import db
from .config import DEFAULTS, HUMAN, VIA_CLI
from .tools import DECLARE, ToolError

OUTCOMES = ("completed", "needs_alignment", "blocked", "progress")
NOW = ("needs_alignment", "blocked")

HOST_DUTY = ("You host this room: whatever the user says without naming anyone comes to you. Your job: analyse it, "
             "split it into tasks, hand each task to the best-suited member with xmuse_send kind=handoff (add "
             "notify=\"now\" when you need that result before anything else), then check what they return. Do not "
             "write code yourself unless the user names you for it. Results reach you batched: completed ones once "
             "everything you handed out is back (or after a time limit); needs_alignment, blocked and questions at once.")
HOST_LINE = ("[xmuse] You host this room: analyse, split, hand off (kind=handoff), verify; write code only when the user "
             "names you for it.")


def host(conn) -> str | None:
    """The room's host while it is a member; None without a room (e.g. a workspace no sidebar has opened yet)."""
    r = conn.execute("select r.host from room r join agents a on a.id=r.host and a.removed=0").fetchone()
    return r and r[0]


def _max_s(cfg: dict | None) -> float:
    return float((cfg or {}).get("host_batch_max_s", DEFAULTS["host_batch_max_s"]))


# ---- the user's words ---------------------------------------------------------------------------------------------

def user_via(via: str | None) -> bool:
    """Said by the user: from a sidebar (operator token) or the CLI (admin token); not a coordinator's relay."""
    return via == VIA_CLI or bool(via and via.endswith(" sidebar"))


def route(conn, sender: str, via: str | None, kind: str, thread: dict, mentions: list) -> str | None:
    """The user's unaddressed words relayed by a coordinator (not a broadcast): only the host.
    Plain broadcasts (sender == HUMAN straight from a sidebar/CLI) wake the whole group instead
    and never reach here (mail.send). Returns the host."""
    if sender != HUMAN or kind != "message" or mentions or not user_via(via) or thread["kind"] == "dm" \
            or thread.get("private"):
        return None
    h = host(conn)
    return h if h and conn.execute("select 1 from thread_members where thread_id=? and member=?",
                                    (thread["id"], h)).fetchone() else None


# ---- batches --------------------------------------------------------------------------------------------------------

def waiting(conn, h: str) -> list[dict]:
    """The host's batch: handoffs it sent that are not back. A removed member, a canceled delivery or an assignment the
    host closed (resolved, archived, rejected) no longer counts."""
    return db.rows(conn.execute(
        "select d.* from dispatches d join agents a on a.id=d.member and a.removed=0"
        " left join entries e on e.id=d.entry_id"
        " left join deliveries v on v.message_id=d.message_id and v.recipient=d.member"
        " where d.host=? and d.returned_at is null and coalesce(e.status, 'active') not in"
        " ('resolved', 'archived', 'rejected') and coalesce(v.state, '') != 'canceled' order by d.id", (h,)))


def hold(conn, mid: int, h: str) -> None:
    conn.execute("delete from deliveries where message_id=? and recipient=?", (mid, h))
    conn.execute("insert or ignore into dispatch_holds(message_id, host, created_at) values(?,?,?)", (mid, h, db.now()))


def _limits(conn, cfg: dict | None, mid: int) -> None:
    """A done outside a hub turn starts a chain with no wake budget (it never woke anyone); a result for the host does."""
    c = cfg or DEFAULTS
    conn.execute("update chains set max_wakes=?, max_tokens=? where id=(select chain_id from messages where id=?)"
                 " and max_wakes=0 and max_tokens=0 and state='open'", (c["max_chain_wakes"], c["max_chain_tokens"], mid))


def _wake(conn, cfg: dict | None, mid: int, h: str) -> None:
    _limits(conn, cfg, mid)
    st = conn.execute("select c.state from messages m join chains c on c.id=m.chain_id where m.id=?", (mid,)).fetchone()[0]
    conn.execute("insert into deliveries(message_id, recipient, wake, state, updated_at) values(?,?,1,?,?)"
                 " on conflict(message_id, recipient) do update set wake=1, state=excluded.state,"
                 " updated_at=excluded.updated_at", (mid, h, "queued" if st == "open" else "held", db.now()))


def release(conn, cfg: dict | None, h: str, why: str) -> int:
    """Held results become the host's ordinary wake deliveries (a stopped chain's stay out). Caller's transaction."""
    n = 0
    for mid, chain in conn.execute("select d.message_id, c.state from dispatch_holds d join messages m on"
                                   " m.id=d.message_id join chains c on c.id=m.chain_id where d.host=?"
                                   " and d.released_at is null order by d.message_id", (h,)).fetchall():
        if chain != "stopped":
            _wake(conn, cfg, mid, h)
            n += 1
        conn.execute("update dispatch_holds set released_at=?, why=? where message_id=? and host=?",
                     (db.now(), why if chain != "stopped" else "stopped", mid, h))
    return n


def batch_thread(conn, host: str, pending: list[dict]) -> dict[int, str]:
    """Where a released batch of host results is answered (room binding: one batch, one turn, one session).

    Maps each pending message that came out of a released batch to one thread: the host's group thread when it is
    in one (the room), else the thread of the batch's first result. Other pending messages keep their own thread,
    so {} when no pending message belongs to a released batch."""
    ids = {p["id"] for p in pending}
    released = [r[0] for r in conn.execute(
        "select message_id from dispatch_holds where host=? and released_at is not null order by message_id",
        (host,)).fetchall() if r[0] in ids]
    if not released:
        return {}
    # the host's own work comes back as wakes from its assignees (a question, a block) in the same admission: same thread
    assignees = {r[0] for r in conn.execute(
        "select d.member from dispatches d join messages hm on hm.id=d.message_id where hm.sender=?", (host,))}
    batch = sorted(released + [p["id"] for p in pending if p["sender"] in assignees])
    group = conn.execute(
        "select t.id from threads t join thread_members m on m.thread_id=t.id"
        " where m.member=? and t.kind!='dm' order by t.id desc limit 1", (host,)).fetchone()
    target = group[0] if group else next(p["thread_id"] for p in pending if p["id"] == batch[0])
    return {mid: target for mid in batch}


def settle(conn, cfg: dict | None, h: str, force: str | None = None, woke: bool = False) -> int:
    """Release the host's held results when their batch is due. `woke`: the host wakes now anyway, so they go along.
    Caller's transaction."""
    first = conn.execute("select min(created_at) from dispatch_holds where host=? and released_at is null",
                         (h,)).fetchone()[0]
    if first is None:
        return 0
    why = force or ("with_wake" if woke else "batch" if not waiting(conn, h) else
                    "timeout" if db.now() >= first + _max_s(cfg) else None)
    return release(conn, cfg, h, why) if why else 0


def tick(conn, cfg: dict) -> int:
    """Engine kick (every send, turn end and sweep): due batches go out, so a held result is never stuck. A hub-run
    host about to be admitted for something else takes its held results along."""
    hosts = [r[0] for r in conn.execute("select distinct host from dispatch_holds where released_at is null")]
    if not hosts:
        return 0
    n = 0
    with db.tx(conn):
        for h in hosts:
            a = db.row(conn.execute("select * from agents where id=?", (h,)))
            woke = bool(a and not db.polled(a) and conn.execute(
                "select 1 from deliveries where recipient=? and wake=1 and state='queued' and read_at is null"
                " and acked_at is null", (h,)).fetchone())
            n += settle(conn, cfg, h, woke=woke)
    return n


def wake_host(conn, cfg: dict) -> int:
    """The act wake_host: the user releases the host's held results now."""
    h = host(conn)
    if not h:
        return 0
    with db.tx(conn):
        return settle(conn, cfg, h, force="wake_host")


# ---- hooks in mail.send and mail.done (inside their transactions) -----------------------------------------------

def on_send(conn, cfg: dict, mid: int, sender: str, kind: str, wake: set, eids: list, notify: str | None) -> set:
    """A host handoff opens one dispatch per assignee. A member's plain message to the host while it works on one of
    the host's handoffs is part of its result: held with the batch. Returns the recipients held back."""
    h = host(conn)
    if not h:
        return set()
    if sender == h:
        if kind == "handoff" and eids:
            for eid, member in conn.execute(f"select id, assignee from entries where id in ({','.join('?' * len(eids))})",
                                            eids).fetchall():
                if member and member != h:
                    conn.execute("insert or ignore into dispatches(message_id, entry_id, host, member, notify, created_at)"
                                 " values(?,?,?,?,?,?)", (mid, eid, h, member, notify or "batch", db.now()))
        return set()
    if h not in wake or not conn.execute("select 1 from deliveries where message_id=? and recipient=? and wake=1"
                                         " and state='queued'", (mid, h)).fetchone():
        return set()
    if kind == "message" and any(d["member"] == sender for d in waiting(conn, h)):
        hold(conn, mid, h)
        settle(conn, cfg, h)
        return {h}
    settle(conn, cfg, h, woke=True)  # a question, the user's words, ...: the host wakes, held results go along
    return set()


def upgrade(outcome: str, declares: list | None, member: str, evidence_status: str | None = None,
            evidence_problems: list | None = None) -> tuple[str, str | None]:
    """The hub's check on a member's label (§8.4). Returns (outcome, reason); reason is None when unchanged.
    evidence_status/_problems come from the evidence check (§8.5); None until it exists."""
    if outcome in ("completed", "needs_alignment") and evidence_status == "unverified" and not any(
            "transcript unavailable" in str(p) for p in evidence_problems or []):
        return "blocked", "evidence not verified" + (f": {'; '.join(map(str, evidence_problems))}"
                                                     if evidence_problems else "")
    if outcome == "completed":
        wide = [d for d in declares or [] if d.get("kind") in DECLARE
                and (d.get("supersedes") or d.get("scope") not in (f"member:{member}", f"agent:{member}"))]
        if wide:
            return "needs_alignment", "declares " + ", ".join(dict.fromkeys(
                d["kind"] + (f" superseding {d['supersedes']}" if d.get("supersedes") else "") for d in wide)) + \
                " beyond its own scope"
    return outcome, None


def _answered(conn, h: str, member: str) -> list[dict]:
    """The host's open handoffs this member's result answers (see the module docstring)."""
    mine = [d for d in waiting(conn, h) if d["member"] == member]
    seen, rest = [], []
    for d in mine:
        v = db.row(conn.execute("select * from deliveries where message_id=? and recipient=?", (d["message_id"], member)))
        if v and (v["read_at"] or v["acked_at"] or v["delivered_at"] or v["state"] in ("admitted", "done", "failed",
                                                                                       "delivered")):
            seen.append(d)
        elif not v or v["state"] != "blocked":
            rest.append(d)
    return seen or rest[:1]


def on_done(conn, cfg: dict | None, mid: int, member: str, nxt: str, outcome: str | None, declares: list | None,
            evidence_status: str | None = None, evidence_problems: list | None = None) -> dict:
    """Label the done, then route it to the host if it is a result for the host (next is the host, or it answers one
    of the host's handoffs). Returns the fields for xmuse_done's reply."""
    given = outcome or "completed"
    if given not in OUTCOMES:
        raise ToolError("invalid_arguments", f"outcome must be one of: {', '.join(OUTCOMES)}; got {outcome!r}")
    final, reason = upgrade(given, declares, member, evidence_status, evidence_problems)
    by = "hub" if reason else "member"
    conn.execute("update messages set outcome=?, outcome_by=?, outcome_reason=? where id=?", (final, by, reason, mid))
    out = {"outcome": final, "outcome_by": "hub", "outcome_reason": reason} if reason else \
        {"outcome": final} if outcome else {}  # a done that left the default alone gets the reply it always got
    h = host(conn)
    if not h or h == member:
        return out
    answers = _answered(conn, h, member)
    if nxt != h and not answers:
        return out  # not a result for the host
    if final != "progress" and answers:
        conn.execute(f"update dispatches set returned_at=?, result_id=? where id in ({','.join('?' * len(answers))})",
                     (db.now(), mid, *[d["id"] for d in answers]))
    if final == "progress":
        conn.execute("insert or ignore into deliveries(message_id, recipient, wake, state, updated_at)"
                     " values(?,?,0,'passive',?)", (mid, h, db.now()))
    elif final in NOW or any(d["notify"] == "now" for d in answers):
        _wake(conn, cfg, mid, h)
        settle(conn, cfg, h, force="with_wake")
    else:
        _limits(conn, cfg, mid)
        hold(conn, mid, h)
        settle(conn, cfg, h)
    return out


# ---- the sidebar view -----------------------------------------------------------------------------------------------

def host_wait(conn, cfg: dict, h: str | None) -> dict:
    if not h:
        return {"waiting_on": [], "results_held": 0, "wake_at": None}
    w = waiting(conn, h)
    n, first = conn.execute("select count(*), min(created_at) from dispatch_holds where host=? and released_at is null",
                            (h,)).fetchone()
    return {"waiting_on": [{"member": d["member"], "handoff_id": d["message_id"], "since": d["created_at"]} for d in w],
            "results_held": n, "wake_at": first + _max_s(cfg) if n and w else None}


def wakes_hour(conn, agent: dict, since: float) -> int:
    """Hub-run members: turns started. Polled ones (desktop, foreground) have no hub turns: count the distinct seconds
    in which wake deliveries reached them (one burst is one prompt)."""
    if not db.polled(agent):
        return conn.execute("select count(*) from turns where agent_id=? and started_at>?", (agent["id"], since)).fetchone()[0]
    return conn.execute("select count(distinct cast(coalesce(delivered_at, updated_at) as integer)) from deliveries"
                        " where recipient=? and wake=1 and state not in ('canceled', 'blocked', 'held')"
                        " and coalesce(delivered_at, updated_at)>?", (agent["id"], since)).fetchone()[0]


def item(m: dict) -> dict:
    """Timeline fields of a done message."""
    if m["kind"] != "done":
        return {}
    return {"outcome": m.get("outcome"), "outcome_by": m.get("outcome_by"),
            **({"outcome_reason": m["outcome_reason"]} if m.get("outcome_reason") else {})}


def for_me(conn, m: dict, reader: str, base: bool) -> bool:
    """A held result is not for its host yet; a done is for the host only when it was delivered as a wake."""
    if not base:
        return False
    if conn.execute("select 1 from dispatch_holds where message_id=? and host=? and released_at is null",
                    (m["id"], reader)).fetchone():
        return False
    if m["kind"] == "done" and reader == host(conn):
        return bool(conn.execute("select 1 from deliveries where message_id=? and recipient=? and wake=1"
                                 " and state not in ('canceled', 'blocked')", (m["id"], reader)).fetchone())
    return True


def fingerprint(conn) -> tuple:
    return tuple(conn.execute("select (select count(*) from dispatches), (select count(returned_at) from dispatches),"
                              " (select count(*) from dispatch_holds), (select count(released_at) from dispatch_holds)")
                 .fetchone())


def identity(conn, agent_id: str, fresh: bool) -> str:
    """The host's role in its wake pack: in full for a new session, one line after that."""
    if agent_id != host(conn):
        return ""
    return HOST_DUTY if fresh else HOST_LINE
