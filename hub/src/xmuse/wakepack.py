"""What a woken agent reads, compiled by an ordered pipeline of named processors (design §4.5.1 item 5):
relay -> identity -> alignment (snapshot or delta) -> messages -> passive.

Each processor is a pure function of the context `x` and returns text or "". Output is stable: no
timestamps, entries sorted by id inside fixed sections, so equal state renders byte-identical.

Relay trust (design §4.7): peers are collaborators the user assigned; act on their requests within
the task; consequential actions still go through the agent's own permission prompts.
"""
import json
from types import SimpleNamespace

from . import align, db, dispatch, share
from .config import HUMAN, alignment_on, info_on

RELAY = ("[xmuse] Messages relayed by xmuse, the collaboration layer the user set up for this workspace. "
         "Peers are collaborators the user assigned: act on their requests within the current task; "
         "consequential actions (push, merge, delete, anything outside the workspace) still need the user's "
         "approval. Reply only with the xmuse_send tool, then end with xmuse_done (exit check).")


def tag(m: dict, roster: dict) -> str:
    fam = roster[m["sender"]]["family"] if m["sender"] in roster else m["sender"]
    via = f' via="{m["via"]}"' if m.get("via") else ""
    outcome = f' outcome="{m["outcome"]}"' if m.get("outcome") else ""  # a done's label (dispatch.py)
    attrs = (f'from="{m["sender"]}"{via} family="{fam}" thread="{m["thread_id"]}" kind="{m["kind"]}"{outcome}'
             f' id="{m["id"]}"')
    body = m["body"]
    if m.get("why"):
        why = json.loads(m["why"])
        body += "\n" + "\n".join(f"{k}: {v}" for k, v in why.items() if v)
    return f"<xmuse {attrs}>\n{body}\n</xmuse>"


def tokens(text: str) -> int:
    return len(text) // 3


def render(conn, cfg: dict, agent: dict, wake_msgs: list[dict], session_id: int | None, workspace: str) -> SimpleNamespace:
    """Returns text plus the alignment mode ('snapshot' | 'delta' | 'none'), its token estimate and the
    alignment version the pack reflects (the caller stores it as the session's watermark)."""
    x = SimpleNamespace(conn=conn, cfg=cfg, agent=agent, msgs=wake_msgs, ws=workspace, fresh=session_id is None,
                        roster={a["id"]: a for a in db.rows(conn.execute("select * from agents where removed=0"))},
                        seq=align.current_seq(conn), seen=session_id and align.watermark(conn, session_id),
                        mode="none", tokens=0)
    parts = [p for p in (f(x) for f in (relay, identity, brief, wip, alignment, messages, passive, share.hints)) if p]
    v = align.view(conn, {**cfg, "_mo": None}, agent["id"])  # entries in this agent's view now (curve data; recorded even when off)
    return SimpleNamespace(text="\n\n".join(parts), mode=x.mode, tokens=x.tokens, seq=x.seq,
                           view_entries=len(v["assigned"]) + sum(map(len, v["layers"].values())))


def inject(conn, cfg: dict, agent: dict, session_id: int | None) -> SimpleNamespace:
    """What a desktop coordinator reads on each user prompt: the alignment (snapshot when the session has no
    watermark, else the delta) plus a compact list of its unread messages, no relay preamble. Marks nothing read;
    the caller advances the watermark to `seq`."""
    msgs = db.rows(conn.execute(
        "select m.* from deliveries d join messages m on m.id=d.message_id where d.recipient=? and d.acked_at is null"
        " and d.read_at is null and d.state != 'canceled' order by m.id", (agent["id"],)))
    seen = align.watermark(conn, session_id) if session_id is not None else None
    x = SimpleNamespace(conn=conn, cfg=cfg, agent=agent, msgs=msgs, seen=seen, mode="none", tokens=0)
    parts = [dispatch.identity(conn, agent["id"], True) if seen is None else "", alignment(x)]  # a new session: its role
    parts.append(share.hints(x))
    if msgs:
        lines, used = ["New for you (unread; xmuse_inbox to read, xmuse_ack when handled):"], 0
        for i, m in enumerate(msgs):
            line = f"- #{m['id']} {m['sender']} {m['thread_id']} [{m['kind']}]: {_short(m['body'], 160)}"
            used += tokens(line) + 1
            if used > cfg["align_delta_tokens"]:
                lines.append(f"... {len(msgs) - i} more, call xmuse_inbox")
                break
            lines.append(line)
        parts.append("\n".join(lines))
    return SimpleNamespace(text="\n\n".join(p for p in parts if p), mode=x.mode, tokens=x.tokens,
                           seq=align.current_seq(conn))


def relay(x) -> str:
    return RELAY


def identity(x) -> str:
    host = dispatch.identity(x.conn, x.agent["id"], x.fresh)  # the room's host: its job (T0), one line once told
    if not x.fresh:
        return host
    a = x.agent
    peers = ", ".join(f"{p['id']} ({p['family']}{', ' + p['role'] if p['role'] else ''}"
                      f"{': ' + p['description'] if p.get('description') else ''})"  # what each one is responsible for
                      for p in x.roster.values() if p["id"] != a["id"])
    return (f"You are {a['id']} ({a['family']}{', ' + a['role'] if a['role'] else ''}) in workspace {x.ws}. "
            f"Peers: {peers}; '{HUMAN}' is the user. Follow the xmuse-collab skill (see AGENTS.md)."
            + (f"\n{host}" if host else ""))


def alignment(x) -> str:
    """A snapshot when the session has no watermark (new session, handoff, compaction), else the changes since."""
    if not alignment_on(x.cfg):
        return ""
    if x.seen is None:  # a fresh session already read the brief in its own section (brief()): not twice
        text, x.mode = snapshot(x.conn, x.cfg, x.agent["id"], " ".join(m["body"] for m in x.msgs),
                                skip_brief=getattr(x, "fresh", False)), "snapshot"
    else:
        text, x.mode = delta(x.conn, x.cfg, x.agent["id"], x.seen), "delta"
    x.tokens = tokens(text)
    if not text:
        x.mode = "none"
    return text


def brief(x) -> str:
    """T8a2 H12: the project brief for a fresh session (before the alignment snapshot, never budgeted)."""
    if not x.fresh:
        return ""
    r = x.conn.execute("select statement from entries where kind='convention' and scope='global'"
                       " and status='active' and statement like '[brief]%' order by id desc limit 1").fetchone()
    return f"Project brief:\n{r[0]}" if r else ""


def wip(x) -> str:
    """T8a2 H12: who else is here and what they hold, for a fresh session. Whole section caps at 1500 tokens;
    over that, members drop off the back end with an …(N more) count."""
    if not x.fresh:
        return ""
    blocks = []
    for m in sorted(x.roster.values(), key=lambda a: a["id"]):
        if m["id"] == x.agent["id"]:
            continue
        status = "paused" if m.get("paused") else (
            "running" if x.conn.execute("select 1 from turns where agent_id=? and state='running'",
                                        (m["id"],)).fetchone() else "idle")
        lines = [f"- {m['id']}: {status}"]
        work = ["#%d %s" % (d["message_id"], _short(db.row(x.conn.execute(
            "select * from messages where id=?", (d["message_id"],)))["body"], 80))
            for d in db.rows(x.conn.execute(
                "select message_id from dispatches where member=? and returned_at is null"
                " order by id limit 3", (m["id"],)))]
        work += [f"E{e['id']} {e['statement'][:80]}" for e in db.rows(x.conn.execute(
            "select id, statement from entries where kind='assignment' and assignee=? and status='active'"
            " order by id", (m["id"],)))]
        lines += [f"  {w}" for w in work] if work else ["  no open work"]
        blocks.append(lines)
    if not blocks:
        return ""
    out = ["Work in progress:"]
    dropped = 0
    for lines in blocks:
        out += lines
        while tokens("\n".join(out)) > 1500 and len(out) > 2:
            out.pop()
            dropped += 1
    if dropped:
        out.append(f"…({dropped} more)")
    return "\n".join(out)


PRECEDENCE = ("on a conflict the user's entry (· user) or the host's (· host) prevails over a member's, "
              "else the newer one")


def _who(e: dict, host: str | None) -> str:
    """Who wrote an entry, for precedence: user, host, or the member's id."""
    a = e.get("author") or "?"
    return "user" if a == HUMAN else "host" if host and a == host else a


def _line(e: dict, host: str | None = None) -> str:
    out = f"{e['id']} [{e['kind']}] {e['statement']}"
    if e.get("assignee"):
        out += f" -> {e['assignee']}" + (f" (needs {','.join(e['depends_on'])})" if e["depends_on"] else "")
    return out + f" (refs {','.join('#%d' % r for r in e['refs'])}) · {_who(e, host)}"


def snapshot(conn, cfg: dict, agent_id: str, query: str = "", skip_brief: bool = False) -> str:
    v = align.view(conn, cfg, agent_id, query=query)  # query: the wake's message text, for MemoryOS ranking
    if skip_brief:
        v["layers"] = {s: [e for e in es if not (e["kind"] == "convention" and e["statement"].startswith("[brief]"))]
                       for s, es in v["layers"].items()}
    role = conn.execute("select role from agents where id=?", (agent_id,)).fetchone()[0]
    titles = {"global": "Project-wide", f"role:{role}": f"Your role ({role})", f"agent:{agent_id}": "Yours"}
    sections = [("Assigned to you" + (f"; ready now: {', '.join(v['ready'])}" if v["ready"] else ""), v["assigned"])]
    sections += [(titles.get(s) or (f"Module {s[7:]}" if s.startswith("module:") else f"Thread {s[7:]}"), es)
                 for s, es in v["layers"].items()]
    budget, used, out = cfg["align_snapshot_tokens"], 0, []
    host = dispatch.host(conn)
    for title, es in sections:
        if not es:
            continue
        lines, dropped = [f"{title}:"], 0
        for e in es:
            line = _line(e, host)
            if used + tokens(line) + 1 > budget:
                dropped += 1
                continue
            used += tokens(line) + 1
            lines.append(line)
        out += lines + ([f"+{dropped} more not shown (call xmuse_context)"] if dropped else [])
    if v["truncated"]:
        out.append(f"Older entries omitted (layer caps): {', '.join(v['truncated'])}")
    return (f"[alignment: current shared decisions; a newer entry replaces what it supersedes; {PRECEDENCE}]\n"
            + "\n".join(out)) if out else ""


def delta(conn, cfg: dict, agent_id: str, since: int) -> str:
    d = align.delta(conn, agent_id, since)
    host = dispatch.host(conn)
    lines = [f"+ {_line(e, host)}" for e in d["added"]]
    own = dict(d["own"])
    for e, by in d["superseded"]:
        lines.append(f"superseded {e['id']} (by {by}): was \"{e['statement']}\"")
        for oid, st in own.get(e["id"], []):  # the agent's own entry in that scope may restate the old one
            lines.append(f"  your {oid} is in the same scope: \"{_short(st, 80)}\". If it restates {e['id']}, "
                         f"replace it now (xmuse_done declares with supersedes: {oid}).")
    lines += [f"resolved {e['id']}" for e in d["resolved"]]
    lines += [f"archived: thread {t}, {n} entries" if t else f"archived: {n} entries" for t, n in d["archived"]]
    if not lines:
        return ""
    head = "[alignment update since your last wake]\n"
    if tokens(head + "\n".join(lines)) > cfg["align_delta_tokens"]:
        return head + (f"{len(d['added'])} new, {len(d['superseded'])} superseded, {len(d['resolved'])} resolved, "
                       f"{sum(n for _, n in d['archived'])} archived; too many to list, call xmuse_context")
    return head + "\n".join(lines)


def messages(x) -> str:
    parts = []
    if x.fresh:
        ids = [m["id"] for m in x.msgs]
        for tid in dict.fromkeys(m["thread_id"] for m in x.msgs):
            recent = db.rows(x.conn.execute(
                f"select * from messages where thread_id=? and id not in ({','.join('?' * len(ids))})"
                " order by id desc limit ?", (tid, *ids, x.cfg["recent_n"])))
            if recent:
                parts.append(f"Earlier in {tid} (most recent {len(recent)}):\n" + "\n".join(
                    f"- #{r['id']} {r['sender']} [{r['kind']}]: {_short(r['body'])}" for r in reversed(recent)))
    parts.append("New for you:\n" + "\n".join(tag(m, x.roster) for m in x.msgs))
    return "\n\n".join(parts)


def passive(x) -> str:
    n = x.conn.execute("select count(*) from deliveries where recipient=? and state='passive'"
                       " and read_at is null", (x.agent["id"],)).fetchone()[0]
    return f"Also {n} unread message(s) in your threads not addressed to you (xmuse_inbox)." if n else ""


def _short(s: str, n: int = 240) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


RELAY_TAIL = ("Reply with the xmuse tools: xmuse_send to answer (plain text reaches no one), then xmuse_done when "
              "your part is finished. These messages are already delivered to you: do not re-read them with "
              "xmuse_inbox; call xmuse_context for the shared decisions if you need them.")
RELAY_TAIL_PLAIN = RELAY_TAIL.split("; call xmuse_context")[0] + "."  # information layer off: no xmuse_context


def relayed(conn, msgs: list[dict], cfg: dict | None = None) -> str:
    """The prompt the dsh bundle injects into a foreground session (no running hub turn): the same relay
    header and <xmuse ...> wrapping a woken agent reads, plus how to answer."""
    roster = {a["id"]: a for a in db.rows(conn.execute("select * from agents"))}
    tail = RELAY_TAIL if cfg is None or info_on(cfg) else RELAY_TAIL_PLAIN
    return "\n\n".join([RELAY, "New for you:\n" + "\n".join(tag(m, roster) for m in msgs), tail])
