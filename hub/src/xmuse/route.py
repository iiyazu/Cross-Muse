"""Duty routing (contract §8.7, T4): a member's unaddressed question in a public group wakes only the
1-2 members whose role + description best match the question text. Keyword-overlap scoring is deliberately
rough; when nothing matches, the caller keeps the old behaviour (wake everyone)."""
import re

from . import db
from .config import HUMAN

STOPWORDS = frozenset("""
the and for with this that from into have will your are was were been has had not but you its our their
they them then than when what which who how all any can her his one out she there about would could should
""".split())

_WORD = re.compile(r"[a-z0-9]+")
_HAN = re.compile(r"[\u4e00-\u9fff]")


def terms(text: str) -> set[str]:
    """English/digit words (lowercased, len>=3, stopwords out) plus every adjacent Han pair."""
    out = set()
    for w in _WORD.findall((text or "").lower()):
        if len(w) >= 3 and w not in STOPWORDS:
            out.add(w)

    def flush(run: str) -> None:
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])

    run = ""
    for ch in text or "":
        if _HAN.match(ch):
            run += ch
        else:
            flush(run)
            run = ""
    flush(run)
    return out


def pick(conn, sender: str, kind: str, thread: dict, mentions: list, body: str) -> dict[str, list[str]]:
    """Member id -> sorted hit terms (at most 5 each, at most 2 members); {} when routing does not apply.
    Applies only to a member's kind=question in a public group with nobody mentioned."""
    if kind != "question" or mentions or sender == HUMAN:
        return {}
    if thread["kind"] == "dm" or thread.get("private") or not thread["id"].startswith("#"):
        return {}
    q = terms(body)
    if not q:
        return {}
    roster = {a["id"]: a for a in db.rows(conn.execute("select * from agents where removed=0"))}
    mem = [m for m, in conn.execute("select member from thread_members where thread_id=?", (thread["id"],))
           if m in roster and m != sender]
    scored = []
    for mid in mem:
        a = roster[mid]
        hit = sorted(q & terms(f"{a.get('role') or ''} {a.get('description') or ''}"))
        if hit:
            scored.append((mid, len(hit), hit))
    scored.sort(key=lambda t: (-t[1], t[0]))
    if not scored:
        return {}
    top = scored[0][1]
    keep = [scored[0]]
    if len(scored) > 1 and scored[1][1] >= -(-top // 2):  # runner-up reaches ceil(top/2)
        keep.append(scored[1])
    return {mid: hit[:5] for mid, _, hit in keep}


def reason(picked: dict[str, list[str]]) -> str:
    """route_reason text: `e1: sidebar, opencode; e2: drawer`."""
    return "; ".join(f"{mid}: {', '.join(hits)}" for mid, hits in picked.items())
