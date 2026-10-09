"""What a woken agent reads: merged messages with source tags, plus a bootstrap pack on fresh sessions.

Relay trust (design §4.7): peers are collaborators the user assigned; act on their requests within
the task; consequential actions still go through the agent's own permission prompts.
"""
import json

from . import db
from .config import HUMAN

RELAY = ("[xmuse] Messages relayed by xmuse, the collaboration layer the user set up for this workspace. "
         "Peers are collaborators the user assigned: act on their requests within the current task; "
         "consequential actions (push, merge, delete, anything outside the workspace) still need the user's "
         "approval. Reply only with the xmuse_send tool, then end with xmuse_done (exit check).")


def tag(m: dict, roster: dict) -> str:
    fam = roster[m["sender"]]["family"] if m["sender"] in roster else m["sender"]
    attrs = f'from="{m["sender"]}" family="{fam}" thread="{m["thread_id"]}" kind="{m["kind"]}" id="{m["id"]}"'
    body = m["body"]
    if m.get("why"):
        why = json.loads(m["why"])
        body += "\n" + "\n".join(f"{k}: {v}" for k, v in why.items() if v)
    return f"<xmuse {attrs}>\n{body}\n</xmuse>"


def render(conn, agent: dict, wake_msgs: list[dict], fresh: bool, recent_n: int, workspace: str) -> str:
    roster = {a["id"]: a for a in db.rows(conn.execute("select * from agents"))}
    parts = [RELAY]
    if fresh:
        peers = ", ".join(f"{a['id']} ({a['family']}{', ' + a['role'] if a['role'] else ''})"
                          for a in roster.values() if a["id"] != agent["id"])
        parts.append(f"You are {agent['id']} ({agent['family']}{', ' + agent['role'] if agent['role'] else ''}) "
                     f"in workspace {workspace}. Peers: {peers}; '{HUMAN}' is the user. "
                     "Follow the xmuse-collab skill (see AGENTS.md).")
        for tid in dict.fromkeys(m["thread_id"] for m in wake_msgs):
            ids = [m["id"] for m in wake_msgs]
            recent = db.rows(conn.execute(
                f"select * from messages where thread_id=? and id not in ({','.join('?' * len(ids))})"
                " order by id desc limit ?", (tid, *ids, recent_n)))
            if recent:
                parts.append(f"Earlier in {tid} (most recent {len(recent)}):\n" + "\n".join(
                    f"- #{r['id']} {r['sender']} [{r['kind']}]: {_short(r['body'])}" for r in reversed(recent)))
    parts.append("New for you:\n" + "\n".join(tag(m, roster) for m in wake_msgs))
    passive = conn.execute("select count(*) from deliveries where recipient=? and state='passive'"
                           " and read_at is null", (agent["id"],)).fetchone()[0]
    if passive:
        parts.append(f"Also {passive} unread message(s) in your threads not addressed to you (xmuse_inbox).")
    return "\n\n".join(parts)


def _short(s: str, n: int = 240) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"
