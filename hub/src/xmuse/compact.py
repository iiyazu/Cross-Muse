"""Context compaction (T8 H3, design §4.1): hub-written summarization instructions, auto-compact
checks, and the orchestration around a vendor compacting a session.

Principle 9 holds: the hub never swaps in a fresh session. Compaction is the only backstop: an idle
member whose session passed 500k gets compacted once, with hub-written instructions; anything else is
a manual panel action. Claude is never compacted by the hub (the mod hooks session.compact); dsh has no
compression ability (adapters/dsh.py has no compact entry, the bundle no such command).
"""
from . import align, db, mail
from . import room as rooms
from .config import HUMAN
from .wakepack import tokens

AUTO_TOKENS = 500000  # fallback when the config does not name auto_compact_tokens


def instructions(conn, cfg: dict, agent_id: str) -> str:
    """The summarization instruction for compacting agent_id's session, in Chinese, built from what the
    hub holds in sync: the member's live assignments, the current decisions/conventions of its groups,
    and the project brief. Alignment material is cut to 2000 tokens."""
    fixed = ("总结这段会话。保留以下内容，删掉排查过程：\n"
             "- 当前任务和进度；未完成的事；用户约束；关键决定及理由；"
             "文件路径和命令原文；测试结果行原文。\n"
             "按这个结构写：1. 我是谁、负责什么、在和谁协作；2. 手上的活和进度（引用 xmuse 消息号 #id、条目号 E<n>，原样保留）；"
             "3. 我在等谁、谁在等我（未完成的 handoff、待回复的问题）；4. 关键决定及理由，包括被否决的方案；"
             "5. 改过的文件、跑过的命令和结果行原文；6. 下一步。不确定的标\"未确认\"。\n"
             "下面的对齐要点和项目简介，hub 会在压缩后的下一次叫醒时完整重发：摘要里不要逐条复述，"
             "只写你的进度和它们的关系（例如\"E12 的实现做到第 2 步\"）。")
    v = align.view(conn, cfg, agent_id, query="")
    lines = []
    for scope, es in v["layers"].items():
        if scope != "global" and not scope.startswith("thread:"):
            continue
        for e in es:
            lines.append(f"- {e['id']} [{e['kind']}] {e['statement']}")
    for e in v["assigned"]:
        lines.append(f"- {e['id']} [assignment] {e['statement']}")
    brief = conn.execute("select statement from entries where kind='convention' and scope='global'"
                         " and status='active' and statement like '[brief]%' order by id desc limit 1").fetchone()
    align_part, used = [], 0
    for line in lines:
        if used + tokens(line) + 1 > 2000:
            break
        used += tokens(line) + 1
        align_part.append(line)
    parts = [fixed]
    if align_part:
        parts.append("当前对齐要点：\n" + "\n".join(align_part))
    if brief:
        parts.append("项目简介：\n" + brief[0])
    return "\n\n".join(parts)


def auto_threshold(cfg: dict) -> int:
    return int(cfg.get("auto_compact_tokens") or AUTO_TOKENS)


def auto_due(conn, cfg: dict) -> list[dict]:
    """Sessions due an automatic compaction: opencode members (only they can be compacted), idle (no
    running turn, no queued wake deliveries), current session past the threshold, not yet marked for
    this session. Pure DB reads, cheap enough for the engine's kick path."""
    threshold = auto_threshold(cfg)
    out = []
    for s in db.rows(conn.execute(
            "select s.* from sessions s join agents a on a.id=s.agent_id"
            " where s.state='current' and a.vendor='opencode' and a.removed=0 and a.paused=0"
            " and s.context_tokens>? and coalesce(s.auto_compacted, 0)=0", (threshold,))):
        if conn.execute("select 1 from turns where agent_id=? and state='running'", (s["agent_id"],)).fetchone():
            continue
        if conn.execute("select 1 from deliveries where recipient=? and wake=1 and state='queued'",
                        (s["agent_id"],)).fetchone():
            continue
        out.append(s)
    return out


def auto_reset(conn, cfg: dict) -> int:
    """Sessions whose context fell back under the threshold lose the once-per-session mark, so a later
    re-exceed triggers again. Returns how many marks were cleared."""
    threshold = auto_threshold(cfg)
    cur = conn.execute("update sessions set auto_compacted=0 where state='current'"
                       " and coalesce(auto_compacted, 0)=1 and context_tokens<?", (threshold,)).rowcount
    return cur


def mark_compacting(conn, session_id: int, on: bool) -> None:
    conn.execute("update sessions set compacting=? where id=?", (1 if on else 0, session_id))


def notice_text(member: str, before_k: int | None = None, after_k: int | None = None) -> str:
    if before_k is not None and after_k is not None:
        return f"{member} 已压缩（约 {before_k}k → {after_k}k）"
    return f"{member} 已压缩"


def notify_compacted(conn, member: str, before_k: int | None = None, after_k: int | None = None) -> int:
    """The compaction notice: the member's DM with the user when it exists, else #room. Returns its id."""
    text = notice_text(member, before_k, after_k)
    dm = f"dm:{member}+{HUMAN}" if member < HUMAN else f"dm:{HUMAN}+{member}"
    target = dm if conn.execute("select 1 from threads where id=?", (dm,)).fetchone() else "#room"
    if target == "#room":
        rooms.notice(conn, text)
    else:
        mail.notice(conn, target, text)
    return conn.execute("select id from messages where thread_id=? order by id desc limit 1",
                        (target,)).fetchone()[0]


def member_status(conn, member: str) -> str:
    if conn.execute("select 1 from agents where id=? and paused=1", (member,)).fetchone():
        return "paused"
    if conn.execute("select 1 from turns where agent_id=? and state='running'", (member,)).fetchone():
        return "running"
    return "idle"


def context_of(conn, agent_id: str) -> int:
    """The latest turn's u.context for a member, else 0."""
    r = conn.execute("select u.context from usage u join turns t on t.id=u.turn_id"
                     " where t.agent_id=? order by t.id desc limit 1", (agent_id,)).fetchone()
    return int(r[0]) if r else 0


def compacting_now(conn, agent_id: str) -> bool:
    return bool(conn.execute("select 1 from sessions where agent_id=? and state='current'"
                             " and coalesce(compacting, 0)=1", (agent_id,)).fetchone())


def current_session(conn, agent_id: str) -> dict | None:
    return db.row(conn.execute("select * from sessions where agent_id=? and state='current'"
                               " order by id desc limit 1", (agent_id,)))


def launch(db_factory, driver, agent_id: str, session_id: int, vendor_session: str,
           instructions: str):
    """Run a compaction in a daemon thread: flag the session compacting now, wait for the vendor's
    end event off-thread, then clear the flag and write the notice on success. Returns the thread."""
    import threading
    with db.tx(db_factory()):
        db_factory().execute("update sessions set compacting=1 where id=?", (session_id,))

    def job():
        conn = db_factory()
        try:
            out = driver.compact(agent_id, vendor_session, instructions) if driver is not None \
                else {"ok": False, "error": "driver gone"}
        except Exception:  # noqa: BLE001 - recorded below as silence would confuse; flag still clears
            out = {"ok": False, "error": "crashed"}
        with db.tx(conn):
            conn.execute("update sessions set compacting=0 where id=?", (session_id,))
        if out.get("ok"):
            notify_compacted(conn, agent_id)

    t = threading.Thread(target=job, daemon=True)
    t.start()
    return t
