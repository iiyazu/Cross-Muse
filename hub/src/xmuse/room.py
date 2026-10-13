"""Rooms, invitations, sidebar tokens and the sidebar view (D2; contract docs/design/XMUSE2-VIEW-API.zh.md v0).

A room is this workspace: one hub, one state directory, one `room` row (created by the first sidebar's
POST /v1/rooms, or synthesized for a workspace set up with `xmuse init`). Three kinds of callers:
  - member: an agent's own token (tokens/<id>); may only `say` and `ack`. Once a sidebar bound the member to a
    session, every member request must carry that session id (x-xmuse-session).
  - operator: a token handed to a sidebar plugin (rooms/join); the user acting from that member's sidebar. It may
    approve and manage; what it says is recorded as the user's, `via "<vendor> sidebar"`.
  - admin: the CLI's tokens/_admin (`via "cli"`).
The view is one snapshot for every reader; `version` changes whenever anything a sidebar shows changes (a
fingerprint of the tables, checked after each request and while long polls wait).
"""
import hashlib
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import align, config, db, dispatch, evidence, mail, share
from . import threads as groups
from .config import HUMAN, VIA_CLI
from .tools import ToolError

VENDORS = ("claude", "opencode", "dsh", "agy")
TIMELINE_N = 50
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: read aloud and typed by hand
MEMBER_ACTS = {"say", "ack"}
ACTS = {"say", "ack", "approve", "invite", "remove", "pause", "resume", "transfer_host", "align", "share_mark",
        "member_add", "member_edit", "wake_host", "promote", "read", "brief", "compact", "stop", "retract"}
ACTS |= groups.ACTS  # T2 private groups


class ApiError(Exception):
    """A contract error: HTTP status plus {"error": code, "message": ...}."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Principal:
    kind: str             # member | operator | admin
    member: str | None    # the member it belongs to (None: admin)

    @property
    def reader(self) -> str:
        return self.member or HUMAN


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def principal(conn, admin_digest: str, header: str | None) -> Principal | None:
    token = (header or "").removeprefix("Bearer ").strip()
    if not token:
        return None
    d = digest(token)
    if secrets.compare_digest(d, admin_digest):
        return Principal("admin", None)
    r = conn.execute("select id from agents where token_digest=? and removed=0", (d,)).fetchone()
    if r:
        return Principal("member", r[0])
    r = conn.execute("select o.member_id from operators o join agents a on a.id=o.member_id"
                     " where o.token_digest=? and a.removed=0", (d,)).fetchone()
    return r and Principal("operator", r[0])


# ---- room row and version ---------------------------------------------------------------------------------

def room_row(conn, ws: Path) -> dict:
    """The room; a workspace set up with `xmuse init` gets one on first use (host: its desktop coordinator)."""
    r = db.row(conn.execute("select * from room"))
    if r:
        return r
    host = next((a["id"] for a in db.rows(conn.execute("select id, settings from agents where removed=0 order by id"))
                 if db.settings(a).get("desktop")), None)
    with db.tx(conn):
        conn.execute("insert or ignore into room(id, name, dir, host, created_at) values(?,?,?,?,?)",
                     (room_id(ws), ws.name, str(ws), host, db.now()))
    return db.row(conn.execute("select * from room"))


def room_id(ws: Path) -> str:
    return "r-" + hashlib.sha1(str(ws).encode()).hexdigest()[:4]


def fingerprint(conn) -> tuple:
    """Everything a sidebar shows, cheaply: changes in any of these change the view."""
    one = lambda sql: tuple(conn.execute(sql).fetchone())  # noqa: E731
    return (one("select max(id) from messages"),
            one("select count(*), max(updated_at), total(read_at), total(acked_at) from deliveries"),
            one("select group_concat(id || ':' || paused || ':' || removed || ':' || coalesce(bound_session, '')"
                " || ':' || role || ':' || description || ':' || model, '|') from agents"),
            one("select max(id), group_concat(agent_id) from turns where state='running'"),
            one("select count(*), max(id) from turns"),
            one("select group_concat(agent_id || ':' || online, '|') from sessions where state='current'"),
            one("select count(*), max(updated_at) from leases"),
            one("select coalesce(max(seq), 0) from entry_events"),
            one("select group_concat(id || ':' || state, '|') from approvals"),
            one("select name, host from room"),
            one("select count(*), max(used_at) from invites"),
            one("select max(id), max(phase_at), group_concat(state) from preset_runs"),
            one("select max(id) from preset_events"), dispatch.fingerprint(conn),
            one("select total(last_read_id) from human_reads"),  # T8a H6: the user's read cursors (unread badges)
            one("select coalesce(max(cast(value as integer)), 0) from meta where key='progress_tick'"))


def stored_version(conn) -> int:
    r = conn.execute("select value from meta where key='view_version'").fetchone()
    return int(r[0]) if r else 0


def save_version(conn, v: int) -> None:
    with db.tx(conn):
        conn.execute("insert or replace into meta values('view_version', ?)", (str(v),))


# ---- members ----------------------------------------------------------------------------------------------

def _online(conn, a: dict) -> bool:
    if not db.polled(a):
        return True  # the hub runs it
    if a["bound_session"]:
        return True
    if conn.execute("select 1 from sessions where agent_id=? and state='current' and online=1", (a["id"],)).fetchone():
        return True
    return bool(conn.execute("select 1 from leases where agent_id=?", (a["id"],)).fetchone())


def _unread(conn, member: str, thread: str | None = None) -> int:
    # hub notices reach only desktop members (the coordinator relays them): left out, so unread means the same
    # for every vendor's sidebar
    sql = ("select count(*) from deliveries d join messages m on m.id=d.message_id where d.recipient=?"
           " and d.read_at is null and d.acked_at is null and d.state != 'canceled' and m.kind != 'notice'")
    args = [member]
    if thread:
        sql, args = sql + " and m.thread_id=?", args + [thread]
    return conn.execute(sql, args).fetchone()[0]


def _human_unread(conn, thread: str) -> int:
    """T8a H6: the user's unread in a thread: past its read cursor, not its own words, no notices."""
    cur = conn.execute("select last_read_id from human_reads where thread_id=?", (thread,)).fetchone()
    return conn.execute("select count(*) from messages where thread_id=? and id>? and sender!=? and kind != 'notice'",
                        (thread, cur[0] if cur else 0, HUMAN)).fetchone()[0]


def mentions_me(conn) -> int:
    """T8a H6: unread messages that @ the user or answer one of the user's messages."""
    cursors = dict(conn.execute("select thread_id, last_read_id from human_reads").fetchall())
    user_msgs = {r[0] for r in conn.execute("select id from messages where sender=?", (HUMAN,))}
    n = 0
    for m in db.rows(conn.execute("select id, thread_id, mentions, reply_to from messages"
                                  " where kind != 'notice' and sender != ?", (HUMAN,))):
        if m["id"] <= cursors.get(m["thread_id"], 0):
            continue
        if HUMAN in json.loads(m["mentions"] or "[]") or m["reply_to"] in user_msgs:
            n += 1
    return n


def _status(conn, a: dict, online: bool) -> str:
    if a["paused"]:
        return "paused"
    if conn.execute("select 1 from turns where agent_id=? and state='running'", (a["id"],)).fetchone():
        return "running"
    if conn.execute("select 1 from deliveries where recipient=? and state='queued' and wake=1", (a["id"],)).fetchone():
        return "queued"
    return "idle" if online else "offline"


def _context(conn, agent_id: str) -> dict:
    """The latest turn's context size; compacting (a hub-run compaction in flight); compacted (one succeeded after
    that turn, so the size is stale and shows as 0 until the next turn measures the compacted session)."""
    last = conn.execute("select u.context, t.started_at from usage u join turns t on t.id=u.turn_id"
                        " where t.agent_id=? order by t.id desc limit 1", (agent_id,)).fetchone()
    s = conn.execute("select coalesce(compacting, 0), compacted_at from sessions where agent_id=? and state='current'"
                     " order by id desc limit 1", (agent_id,)).fetchone()
    compacted = bool(s and s[1] and (last is None or s[1] > last[1]))
    return {"context_tokens": 0 if compacted or last is None else last[0],
            "compacting": bool(s and s[0]), "compacted": compacted}


def members(conn, cfg: dict) -> list[dict]:
    since, out = db.now() - 3600, []
    prog = cfg.get("_progress") or {}
    for a in db.rows(conn.execute("select * from agents where removed=0 order by created_at, id")):
        online = _online(conn, a)
        tokens = conn.execute("select coalesce(sum(input+cache_read+cache_write+output), 0) from usage"
                              " where agent_id=? and created_at>?", (a["id"], since)).fetchone()[0]
        running = conn.execute("select id, started_at from turns where agent_id=? and state='running'"
                               " order by id desc limit 1", (a["id"],)).fetchone()
        pe = running and prog.get(running[0])
        out.append({"id": a["id"], "vendor": a["vendor"], "model": a["model"], "role": a["role"],
                    "description": a["description"], "status": _status(conn, a, online), "online": online,
                    "paused": bool(a["paused"]), "unread": _unread(conn, a["id"]), "tokens_hour": tokens,
                    "tokens_hour_cap": int(cfg.get("agent_hourly_tokens") or 0),
                    "wakes_hour": dispatch.wakes_hour(conn, a, since),
                    # T8a H5: deliveries asking for a wake that it has not taken yet
                    "queued": conn.execute("select count(*) from deliveries where recipient=? and wake=1"
                                           " and state in ('queued','held')", (a["id"],)).fetchone()[0],
                    # T8b H4: live progress of the running turn, null when idle
                    "progress": {"turn": running[0], "started_at": running[1], "tools": pe.get("tools", 0),
                                 "last_tool": pe.get("last_tool"), "text": pe.get("text", ""),
                                 "updated_at": pe.get("updated_at", 0.0)} if pe else None,
                    # T8c H3: the latest turn's context size, and whether a compaction is running
                    **_context(conn, a["id"])})
    return out


# ---- timeline -----------------------------------------------------------------------------------------------

def _via(v: str | None, roster: set) -> str | None:
    """Contract values: null, "cli", "<provider> sidebar", "coordinator" (a desktop coordinator relayed it)."""
    if v is None or v == VIA_CLI or v.endswith(" sidebar"):
        return v
    return "coordinator" if v in roster else v


def _item(conn, m: dict, reader: str, mem: dict, roster: set) -> dict:
    mentions = json.loads(m["mentions"] or "[]")
    to = [x for x in mem.get(m["thread_id"], []) if x != m["sender"]]
    for_me = m["sender"] != reader and (
        reader in mentions or (m["thread_id"].startswith("dm:") and reader in to) or bool(conn.execute(
            "select 1 from deliveries where message_id=? and recipient=? and wake=1", (m["id"], reader)).fetchone()))
    for_me = dispatch.for_me(conn, m, reader, for_me)  # a result held for the host's batch is not for it yet
    if not for_me and reader == HUMAN and m.get("reply_to"):
        # T8a H9: a reply to the user's own message is marked for the human reader (it wakes nobody).
        om = conn.execute("select sender from messages where id=?", (m["reply_to"],)).fetchone()
        for_me = bool(om and om[0] == HUMAN)
    item = {"id": m["id"], "thread": m["thread_id"], "from": m["sender"], "via": _via(m["via"], roster), "to": to,
            "mentions": mentions, "kind": "system" if m["kind"] == "notice" else m["kind"], "text": m["body"],
            "at": m["created_at"], "for_me": for_me, **dispatch.item(m),
            **({"reply_to": m["reply_to"]} if m.get("reply_to") else {}),
            **({"retracted": True} if m.get("retracted_at") else {}),
            **({"shared_from": json.loads(m["shared_from"])} if m.get("shared_from") else {}),
            **({"routed_to": json.loads(m["route_to"])} if m.get("route_to") else {}),
            **({"route_reason": m["route_reason"]} if m.get("route_reason") else {})}
    if m["kind"] == "done":
        item.update(evidence.view_fields(conn, m["id"]))
    return item


def _thread_members(conn) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tid, m in conn.execute("select thread_id, member from thread_members order by member"):
        out.setdefault(tid, []).append(m)
    return out


def timeline(conn, reader: str, before: int | None = None, limit: int = TIMELINE_N, restrict: bool = False) -> dict:
    """`restrict` (a member token): only the threads the reader is in, plus #room and public groups (T2)."""
    limit = max(1, min(int(limit), 200))
    where, args = [], []
    if before is not None:
        where, args = ["id<?"], [int(before)]
    if restrict:
        cond, a = groups.visible_sql("thread_id", reader)
        where, args = where + [cond], args + a
    sql = "select * from messages" + (" where " + " and ".join(where) if where else "")
    rs = db.rows(conn.execute(sql + " order by id desc limit ?", (*args, limit + 1)))
    more, rs = len(rs) > limit, list(reversed(rs[:limit]))
    mem, roster = _thread_members(conn), {r[0] for r in conn.execute("select id from agents")}
    return {"items": [_item(conn, m, reader, mem, roster) for m in rs], "has_more": more}


def threads(conn, reader: str, restrict: bool = False) -> list[dict]:
    mem, out = _thread_members(conn), []
    cond, args = groups.visible_sql("t.id", reader) if restrict else ("1", [])
    for t in db.rows(conn.execute("select t.*, (select max(created_at) from messages m where m.thread_id=t.id) last_at"
                                  f" from threads t where {cond} order by last_at desc", args)):
        ms = mem.get(t["id"], [])
        title = " ↔ ".join(t["id"][3:].split("+")) if t["kind"] == "dm" else t["id"]
        title = t["title"] if t["private"] and t["title"] else title
        out.append({"id": t["id"], "kind": "dm" if t["kind"] == "dm" else "topic", "title": title, "members": ms,
                    "private": bool(t["private"]), "last_at": t["last_at"],
                    # T8a H6: the user's own cursor; members keep delivery-based unread.
                    "unread": _human_unread(conn, t["id"]) if reader == HUMAN else _unread(conn, reader, t["id"])})
    return out


# ---- alignment, approvals, run ------------------------------------------------------------------------------

def alignment(conn, hidden: list | None = None) -> list[dict]:
    """`hidden`: entry scopes a member token may not see (thread entries of private groups it is not in)."""
    rs = db.rows(conn.execute("select * from entries where status in ('active','proposed') order by id desc limit 200"))
    rs = [e for e in rs if e["scope"] not in (hidden or ())]
    return [{"id": f"E{e['id']}", "kind": e["kind"], "scope": e["scope"], "author": e["author"],
             "text": e["statement"], "supersedes": f"E{e['supersedes']}" if e["supersedes"] else None,
             "status": e["status"], "at": e["recorded_at"],
             **({"assignee": e["assignee"]} if e["assignee"] else {}), **({"via": e["via"]} if e.get("via") else {})}
            for e in reversed(rs)]


def approvals(conn, hidden: list | None = None) -> list[dict]:
    out = []
    for a in db.rows(conn.execute("select * from approvals where state='pending' and id not like 'share:%'"
                                  " order by created_at")):
        res = a["resources"] or ""
        try:  # resources: the JSON list OpenCode asked about (commands, paths)
            summary = " ; ".join(map(str, json.loads(res))) if res.startswith("[") else res
        except ValueError:
            summary = res
        out.append({"id": a["id"], "kind": "shell", "member": a["agent_id"],
                    "summary": f"{a['action'] or 'shell'}: {summary}"[:200], "detail": res, "risk": "normal",
                    "at": a["created_at"]})
    for e in db.rows(conn.execute("select * from entries where status='proposed' order by id")):
        if e["scope"] in (hidden or ()):
            continue
        out.append({"id": f"E{e['id']}", "kind": "alignment", "member": e["author"],
                    "summary": f"{e['kind']}: {e['statement']}"[:200], "detail": e["statement"], "risk": "normal",
                    "at": e["recorded_at"]})
    for a in db.rows(conn.execute("select * from agents where paused=1 and removed=0 order by id")):
        out.append({"id": f"resume:{a['id']}", "kind": "resume", "member": a["id"],
                    "summary": f"{a['id']} is paused; approve to resume it", "detail": "", "risk": "normal",
                    "at": a["paused_until"] or a["created_at"]})
    return out + share.approvals(conn)


def run_view(conn) -> dict | None:
    r = db.row(conn.execute("select * from preset_runs where state='running' order by id desc limit 1"))
    if r is None:
        return None
    lim, ex = json.loads(r["limits"]), json.loads(r["executors"])
    st = {m["id"]: m for m in db.rows(conn.execute("select * from agents"))}
    ev = db.rows(conn.execute("select at, phase, kind, detail from preset_events where run_id=? order by id desc limit 20",
                              (r["id"],)))
    return {"id": r["id"], "preset": r["preset"], "phase": r["phase"],
            "deadline_at": r["phase_at"] + lim[r["phase"]] if isinstance(lim.get(r["phase"]), (int, float)) else None,
            "executors": [{"id": a, "state": "paused" if st.get(a, {}).get("paused") else (
                "running" if conn.execute("select 1 from turns where agent_id=? and state='running'", (a,)).fetchone()
                else "idle")} for a in ex],
            "events": [{"at": e["at"], "kind": e["kind"], "text": f"{e['phase'] or ''} {e['detail']}".strip()}
                       for e in reversed(ev)]}


def view(conn, cfg: dict, ws: Path, p: Principal, version: int) -> dict:
    room = room_row(conn, ws)
    restrict = p.kind == "member"  # a member token sees its own threads, not everyone's (T2)
    tl = timeline(conn, p.reader, restrict=restrict)
    hidden = groups.hidden_scopes(conn, p.reader) if restrict else []
    pending = approvals(conn, hidden)
    if restrict:  # share requests quote the user's DMs and only the operator can decide them: not for member tokens
        pending = [x for x in pending if x["kind"] != "share"]
    return {"version": version,
            "room": {"id": room["id"], "name": room["name"], "dir": room["dir"], "host": room["host"],
                     "info_layer": "on" if config.info_on(cfg) else "off", "created_at": room["created_at"]},
            "me": {"kind": p.kind, "id": p.reader},
            "members": members(conn, cfg), "threads": threads(conn, p.reader, restrict), "timeline": tl["items"],
            "timeline_cursor": {"oldest": tl["items"][0]["id"] if tl["items"] else None, "has_more": tl["has_more"]},
            "alignment": alignment(conn, hidden), "approvals": pending, "run": run_view(conn),
            "host_wait": dispatch.host_wait(conn, cfg, room["host"]), "mentions_me": mentions_me(conn)}


# ---- tokens, invitations ------------------------------------------------------------------------------------

def operator_token(conn, member: str) -> str:
    tok = "xmo_" + secrets.token_urlsafe(32)
    with db.tx(conn):
        conn.execute("insert into operators values(?,?,?)", (digest(tok), member, db.now()))
    return tok


def new_code(conn) -> str:
    for _ in range(20):
        raw = "".join(secrets.choice(ALPHABET) for _ in range(6))
        code = f"{raw[:4]}-{raw[4:]}"
        if not conn.execute("select 1 from invites where code=?", (code,)).fetchone():
            return code
    raise ApiError(500, "no_code", "could not draw a fresh invitation code")


def free_id(conn, base: str) -> str:
    taken = {r[0] for r in conn.execute("select id from agents")}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def valid_id(s) -> bool:
    return isinstance(s, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,39}", s)) \
        and s not in (HUMAN, config.HUB)


def same_dir(given: str, ws: Path) -> bool:
    """A sidebar names the room directory as its own host sees it: the workspace path, or its Windows form."""
    from .adapters.base import to_win
    norm = lambda s: str(PureWindowsPath(s)).rstrip("\\").lower() if re.match(r"[A-Za-z]:|\\\\", s) else \
        str(s).rstrip("/")  # noqa: E731
    return norm(given) in {norm(str(ws)), norm(to_win(ws))}


def notice(conn, text: str) -> None:
    """A room event everyone sees in the timeline (#room), never wakes anyone."""
    with db.tx(conn):
        if conn.execute("select 1 from threads where id='#room'").fetchone() is None:
            conn.execute("insert into threads(id, kind, title, created_at) values('#room', 'group', 'room', ?)",
                         (db.now(),))
        for m in [HUMAN, *mail.agents(conn)]:
            conn.execute("insert or ignore into thread_members values('#room', ?)", (m,))
    mail.notice(conn, "#room", text)


def now() -> float:
    return time.time()
