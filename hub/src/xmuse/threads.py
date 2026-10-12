"""Private small groups (T2, contract XMUSE2-VIEW-API section 8.3).

A group `#name` is public (everyone, created by its first message) or private (`threads.private=1`: only the user
and the listed members). Membership is `thread_members`, which already drives delivery, `xmuse_thread` and
`xmuse_context`/wake-pack scopes; what this module adds is how a private group is made and changed, the guard that
keeps non-members out, and the filters the sidebar view uses.
"""
from . import db
from .config import HUMAN
from .tools import ToolError

ROOM = "#room"
ACTS = {"thread_new", "thread_add", "thread_remove"}
# HTTP status of the codes the contract fixes; the rest keep the act dispatcher's mapping (unknown_* 404, else 400)
STATUS = {"not_a_member": 403, "thread_exists": 409, "unknown_member": 400, "public_thread": 400}
_PENDING = "('queued','held','passive','blocked')"  # deliveries nobody has taken yet


def _roster(conn) -> set[str]:
    return {r[0] for r in conn.execute("select id from agents where removed=0")}


def get(conn, tid: str) -> dict | None:
    return db.row(conn.execute("select * from threads where id=?", (tid,)))


def is_private(conn, tid: str) -> bool:
    return bool(conn.execute("select 1 from threads where id=? and private=1", (tid,)).fetchone())


def can_see(conn, member: str, tid: str) -> bool:
    """Everything is visible to the user and to members; a private group only to the user and its members."""
    if member == HUMAN or not is_private(conn, tid):
        return True
    return bool(conn.execute("select 1 from thread_members where thread_id=? and member=?", (tid, member)).fetchone())


def visible_sql(col: str, member: str) -> tuple[str, list]:
    """SQL condition (and args) for the threads a member token's view shows: #room, public groups, and the threads
    it is in (its DMs, its private groups). Other people's DMs and private groups stay out."""
    return (f"({col}='{ROOM}' or {col} in (select id from threads where (kind='group' and private=0)"
            f" or id in (select thread_id from thread_members where member=?)))", [member])


def hidden_scopes(conn, member: str) -> list[str]:
    """Alignment scopes `thread:<tid>` of the private groups this member is not in."""
    return [f"thread:{r[0]}" for r in conn.execute(
        "select id from threads where private=1 and id not in (select thread_id from thread_members where member=?)",
        (member,))]


def resync(conn, member: str, tid: str) -> None:
    """A member joined a thread that already has entries: deltas only cover changes after the watermark, so drop
    its sessions' watermarks and the next wake injects a snapshot that includes this thread."""
    if conn.execute("select 1 from entries where scope=? and status='active'", (f"thread:{tid}",)).fetchone():
        conn.execute("delete from seen where session_id in (select id from sessions where agent_id=?)", (member,))


def create(conn, tid: str, creator: str, members: list, roster: set | None = None, title: str = "") -> dict:
    """Make a private group; the user and the creator are in it. Runs inside the caller's transaction."""
    if not isinstance(tid, str) or not tid.startswith("#") or len(tid) < 2 or any(c.isspace() for c in tid):
        raise ToolError("invalid_arguments", f"a group id is '#name' without spaces; got {tid!r}")
    if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
        raise ToolError("invalid_arguments", "members must be a list of member ids")
    if tid == ROOM or get(conn, tid):
        raise ToolError("thread_exists", f"{tid} already exists")
    roster = _roster(conn) if roster is None else set(roster)
    bad = [m for m in members if m != HUMAN and m not in roster]
    if bad:
        raise ToolError("unknown_member",
                        f"not members of this room: {', '.join(bad)}; members: {', '.join(sorted(roster))}")
    conn.execute("insert into threads(id, kind, title, created_at, private) values(?,?,?,?,1)",
                 (tid, "group", str(title or ""), db.now()))
    for m in dict.fromkeys([HUMAN, creator, *members]):
        conn.execute("insert or ignore into thread_members values(?,?)", (tid, m))
    return get(conn, tid)


def _private(conn, tid) -> dict:
    t = get(conn, tid) if isinstance(tid, str) else None
    if t is None:
        raise ToolError("unknown_thread", f"no thread {tid!r}")
    if t["kind"] != "group":
        raise ToolError("invalid_arguments", f"{tid} is not a group")
    if not t["private"]:
        raise ToolError("public_thread", f"{tid} is a public group: everyone is in it")
    return t


def act_new(conn, b: dict) -> dict:
    """act thread_new {id, members, title?}: the user makes a private group."""
    from . import mail
    members = b.get("members")
    if members is None:
        raise ToolError("bad_request", "thread_new needs id and members (list)")
    with db.tx(conn):
        create(conn, b.get("id"), HUMAN, members, title=b.get("title") or "")
    tid = b["id"]
    mail.notice(conn, tid, f"private group {tid} created with {', '.join(members_of(conn, tid))}")
    return {"thread": tid}


def members_of(conn, tid: str) -> list[str]:
    return [r[0] for r in conn.execute("select member from thread_members where thread_id=? order by member", (tid,))]


def act_add(conn, b: dict) -> dict:
    """act thread_add {thread, member}: the user adds a member; its next wake gets the thread's alignment snapshot."""
    from . import mail
    tid, member = b.get("thread"), b.get("member")
    with db.tx(conn):
        _private(conn, tid)
        if not isinstance(member, str) or member not in _roster(conn):
            raise ToolError("unknown_member", f"no member {member!r} in this room")
        added = conn.execute("insert or ignore into thread_members values(?,?)", (tid, member)).rowcount
        if added:
            resync(conn, member, tid)
    if added:
        mail.notice(conn, tid, f"{member} was added to {tid}")
    return {"ok": True}


def _drop(conn, tid: str, member: str) -> bool:
    """Take a member out: no more deliveries, and what it has not taken yet from this thread is canceled."""
    if not conn.execute("delete from thread_members where thread_id=? and member=?", (tid, member)).rowcount:
        return False
    conn.execute(f"update deliveries set state='canceled', updated_at=? where recipient=? and state in {_PENDING}"
                 " and message_id in (select id from messages where thread_id=?)", (db.now(), member, tid))
    return True


def act_remove(conn, b: dict) -> dict:
    """act thread_remove {thread, member}."""
    from . import mail
    tid, member = b.get("thread"), b.get("member")
    if member == HUMAN:
        raise ToolError("invalid_arguments", "the user is always in a private group")
    with db.tx(conn):
        _private(conn, tid)
        dropped = _drop(conn, tid, member) if isinstance(member, str) else False
    if not dropped:
        raise ToolError("not_in_thread", f"{member!r} is not in {tid}: {', '.join(members_of(conn, tid))}")
    mail.notice(conn, tid, f"{member} was removed from {tid}")
    return {"ok": True}


def leave(conn, member: str, tid: str) -> dict:
    """Tool xmuse_leave_thread: a member leaves a private group it is in. Other threads read as unknown."""
    from . import mail
    with db.tx(conn):
        t = get(conn, tid)
        if t is None or not can_see(conn, member, tid):
            mine = [r[0] for r in conn.execute("select thread_id from thread_members where member=?", (member,))]
            raise ToolError("unknown_thread", f"id must be one of your threads: {', '.join(mine) or '(none)'}")
        if not t["private"]:
            raise ToolError("public_thread", f"{tid} is not a private group: you can only leave private groups")
        _drop(conn, tid, member)
    mail.notice(conn, tid, f"{member} left {tid}")
    return {"ok": True, "thread": tid}
