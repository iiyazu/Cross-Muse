"""No silent stops (T7): when a member's turn ends with handoffs still unreturned, tell the assigner.

Only this rule lives here; the interrupted-delivery canceling it replaces stays as it is. Everything is derived
from existing messages: no new tables, no task state machine.
"""
import json
import logging

from . import db, dispatch, mail
from .adapters.opencode import names_key
from .config import HUMAN, HUB, info_on
from .tools import ToolError

log = logging.getLogger(__name__)


def enabled(cfg: dict | None) -> bool:
    return bool(cfg and cfg.get("stall_notice", True) and info_on(cfg))


def unreturned(conn, agent_id: str) -> list[dict]:
    """Handoffs addressed to this member newer than its last non-progress done."""
    last = conn.execute("select coalesce(max(id), 0) from messages where sender=? and kind='done'"
                        " and coalesce(outcome, 'completed') != 'progress'", (agent_id,)).fetchone()[0]
    return db.rows(conn.execute(
        "select m.* from messages m join deliveries d on d.message_id=m.id"
        " where m.kind='handoff' and d.recipient=? and m.id>? order by m.id", (agent_id, last)))


def _rejected_cmd(conn, agent_id: str, session: str | None, started_at: float) -> str | None:
    """The command whose reject cut the turn short, if the log shows one (';'-suffixed, else None). Kept small on
    purpose: the approvals table is the only record, and only worth one query."""
    if not session:
        return None
    rej = db.row(conn.execute(
        "select action, resources from approvals where agent_id=? and vendor_session=? and state='decided'"
        " and decision='reject' and decided_at>=? order by decided_at desc limit 1",
        (agent_id, session, started_at)))
    if rej is None:
        return None
    try:
        resources = json.loads(rej["resources"] or "[]")
    except ValueError:
        resources = []
    if not isinstance(resources, list):
        resources = [resources]
    auto = rej["action"] == "shell" and names_key(resources)
    cmd = " ".join([str(r) for r in resources]).strip()[:160]
    return f"; command `{cmd}` was {'auto-rejected by the shell policy' if auto else 'rejected by the user'}"


def _ending(conn, turn: dict, end) -> str:
    if end.status == "succeeded":
        prog = conn.execute("select 1 from messages where turn_id=? and kind='done'"
                            " and coalesce(outcome, 'completed') = 'progress'", (turn["id"],)).fetchone()
        return "ended its turn after a progress report" if prog else "ended its turn without xmuse_done"
    if end.status == "failed":
        return f"turn failed: {end.error or 'no error recorded'}"
    extra = ""
    if end.status == "interrupted":
        extra = _rejected_cmd(conn, turn["agent_id"], end.session, turn["started_at"]) or ""
    return f"turn interrupted: {end.error or 'no error recorded'}{extra}"


def on_turn_end(conn, cfg: dict | None, turn: dict, end) -> None:
    """The single T7 hook (called from engine._on_end). Notifies each assigner once; never raises: the rest of the
    turn's bookkeeping runs after it."""
    if not enabled(cfg):
        return
    try:
        _notify(conn, cfg, turn, end)
    except Exception:  # a notice must never break the turn's end
        log.exception("stall notice for turn %s failed", turn.get("id"))


def _notify(conn, cfg: dict, turn: dict, end) -> None:
    pending = unreturned(conn, turn["agent_id"])
    if not pending:
        return
    by_sender: dict[str, list] = {}
    for m in pending:
        by_sender.setdefault(m["sender"], []).append(m["id"])
    roster = mail.agents(conn)
    h = dispatch.host(conn)
    for sender, ids in by_sender.items():
        what = ", ".join(f"#{i}" for i in ids)
        text = (f"[hub] {turn['agent_id']} stopped without handing back handoff {what}: "
                f"{_ending(conn, turn, end)}. Decide: resend, reassign, or ask the user.")
        try:
            if sender == HUMAN:
                mail.notice(conn, mail.dm_id(turn["agent_id"], HUMAN), text)
            else:
                target = sender if sender in roster else h
                if target is None or target == HUMAN:
                    mail.notice(conn, mail.dm_id(turn["agent_id"], HUMAN), text)
                else:
                    # hub-originated (e.g. review) goes to the host; mentions wake whoever can run
                    mail.send(conn, cfg, HUB, target, text, mentions=[target])
        except ToolError:
            try:
                mail.notice(conn, mail.dm_id(turn["agent_id"], HUMAN), text)
            except ToolError:
                pass
