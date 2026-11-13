"""Per-turn workdir snapshots for file-overlap detection.

A turn's change = paths whose snapshot entry differs between turn start and turn
end, plus files from `git diff --name-only` when HEAD moved inside the turn (the
member committed). Pairs of members touching the same repo-relative path within
`overlap_window_s` get a notice through room.notice (#room): hub notices never
wake anyone, so detection itself can never admit a turn (a notice that woke a member could start a
notice -> turn -> notice loop).
Dedup is windowed: a pair x path notified longer ago than `overlap_window_s`
notifies again (and refreshes its timestamp).

Not a git repo -> skip silently, never an error. Over TOO_MANY dirty files ->
record nothing for that turn (a marker row would false-positive the matcher).
"""
import hashlib
import logging
import subprocess
from pathlib import Path

from . import db, room

log = logging.getLogger(__name__)

TOO_MANY = 2000
MARKER = "<snapshot-too-many>"


def _git(workdir, *args, timeout=60):
    try:
        r = subprocess.run(["git", *args], cwd=workdir, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("overlap git failed in %s: %r", workdir, e)
        return None
    return r.stdout if r.returncode == 0 else None


def repo_root(workdir: Path) -> Path | None:
    """The worktree's own top level (differs per linked worktree)."""
    out = _git(workdir, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None


def repo_common(workdir: Path) -> Path | None:
    """The shared git dir (identical for a repo and all its linked worktrees);
    used as the `repo` match key. None when workdir is not a git repo."""
    out = _git(workdir, "rev-parse", "--git-common-dir")
    if not out:
        return None
    p = Path(out.strip())
    return (Path(workdir) / p).resolve() if not p.is_absolute() else p.resolve()


def head(workdir: Path) -> str | None:
    out = _git(workdir, "rev-parse", "HEAD")
    return out.strip() if out else None


def _hash_file(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(workdir) -> tuple[dict[str, str] | None, str | None, bool]:
    """(entries, head, too_many). entries: worktree-relative path -> sha1 hex,
    'deleted' for deletions. (None, None, False) when workdir is not a git repo."""
    workdir = Path(workdir)
    root = repo_root(workdir)
    if root is None or repo_common(workdir) is None:
        return None, None, False
    out = _git(workdir, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if out is None:
        return None, None, False
    parts = out.split("\0")
    entries: dict[str, str] = {}
    too_many = False
    for field in parts:
        if not field:
            continue
        if len(entries) >= TOO_MANY:
            too_many = True
            break
        xy, path = field[:2], field[3:]
        if " -> " in path and xy[0] in "RC":
            path = path.split(" -> ")[-1]  # renamed: match on the new side
        full = root / path
        if "D" in xy or not full.exists():
            entries[path] = "deleted"
        else:
            # Content hash in-process: only compared between our own two snapshots,
            # so it never needs to match git's blob id (no `git hash-object` fork per file).
            try:
                entries[path] = _hash_file(full) if full.is_file() else "deleted"
            except OSError:
                entries[path] = "deleted"
    if too_many:
        log.warning("overlap snapshot of %s: over %d dirty files, skipping", workdir, TOO_MANY)
        return {}, head(workdir), True
    return entries, head(workdir), False


def diff(old: dict[str, str] | None, new: dict[str, str] | None) -> set[str]:
    old, new = old or {}, new or {}
    return {p for p in set(old) | set(new) if old.get(p) != new.get(p)}


def head_files(workdir: Path, old_head: str | None, new_head: str | None) -> set[str]:
    if not old_head or not new_head or old_head == new_head:
        return set()
    out = _git(workdir, "diff", "--name-only", old_head, new_head)
    return set(out.splitlines()) if out is not None else set()


def record_turn_end(conn, cfg: dict, agent_id: str, turn_id: int, workdir,
                    pre: tuple[dict | None, str | None], started_at: float, ended_at: float) -> list[str]:
    """Snapshot, diff vs pre, store touched rows, check overlaps, notify. Any
    terminal turn state. Returns the notice lines (empty when nothing overlaps).
    Never raises: detection must not break turn bookkeeping."""
    try:
        return _record(conn, cfg, agent_id, turn_id, workdir, pre, started_at, ended_at)
    except Exception:
        log.exception("overlap record failed for turn %s", turn_id)
        return []


def _record(conn, cfg, agent_id, turn_id, workdir, pre, started_at, ended_at):
    if not cfg.get("file_overlap_notice", True):
        return []
    workdir = Path(workdir)
    common = repo_common(workdir)
    if common is None:
        return []
    top = repo_root(workdir)
    pre_entries, pre_head = pre
    if pre_entries is None:
        pre_entries, pre_head, _ = snapshot(workdir)
        pre_entries = pre_entries or {}
    entries, hd, too_many = snapshot(workdir)
    if too_many:
        return []
    changed = diff(pre_entries, entries) | head_files(workdir, pre_head, hd)
    if not changed or MARKER in changed:
        return []
    now = db.now()
    with db.tx(conn):
        conn.executemany("insert into touched(turn_id, agent_id, repo, worktree, path, at)"
                         " values(?,?,?,?,?,?)",
                         [(turn_id, agent_id, str(common), str(top), p, now) for p in sorted(changed)])
    window = cfg.get("overlap_window_s", 6 * 3600)
    notes = []
    for path in sorted(changed):
        hit = _find_overlap(conn, str(common), str(top), path, agent_id, turn_id,
                            started_at, ended_at, window)
        if hit is None:
            continue
        other, o_turn, o_worktree, o_start, o_end, concurrent = hit
        a, b = sorted([agent_id, other])
        with db.tx(conn):
            row = conn.execute("select at from overlap_notified where a=? and b=? and repo=? and path=?",
                               (a, b, str(common), path)).fetchone()
            if row is not None and row[0] >= now - window:
                continue  # already notified within the window: still deduped
            conn.execute("insert into overlap_notified(a, b, repo, path, at) values(?,?,?,?,?)"
                         " on conflict(a, b, repo, path) do update set at=excluded.at",
                         (a, b, str(common), path, now))
        if concurrent:
            notes.append(f"{other} 与 {agent_id} 并发改同一工作区 {top} 的 {path}"
                         f"（回合 {o_turn} 与 {turn_id} 时间重叠），无法区分是谁改的")
        elif str(o_worktree) != str(top):
            notes.append(f"{other}（回合 {o_turn}）与 {agent_id}（回合 {turn_id}）都改了 {path}，"
                         f"合并时可能冲突")
        else:
            notes.append(f"{other}（回合 {o_turn}）与 {agent_id}（回合 {turn_id}）先后改了"
                         f"同一工作区 {top} 的 {path}")
    if notes:
        room.notice(conn, "文件重叠：" + "；".join(notes))
    return notes


def _find_overlap(conn, repo, worktree, path, agent_id, turn_id, started_at, ended_at, window):
    """Latest other-agent touch of repo+path inside the window, skipping marker
    rows. Returns (other, o_turn, o_worktree, o_start, o_end, concurrent)."""
    now = db.now()
    rows = conn.execute(
        "select agent_id, turn_id, worktree, at from touched"
        " where repo=? and path=? and agent_id!=? and turn_id!=? and at>=? and path!=?"
        " order by at desc limit 20", (repo, path, agent_id, turn_id, now - window, MARKER)).fetchall()
    for other, o_turn, o_worktree, at in rows:
        tr = conn.execute("select started_at, ended_at from turns where id=?", (o_turn,)).fetchone()
        o_start = tr[0] if tr else at
        o_end = tr[1] if tr and tr[1] is not None else now
        concurrent = str(o_worktree) == str(worktree) and o_start <= ended_at and started_at <= o_end
        return other, o_turn, o_worktree, o_start, o_end, concurrent
    return None
