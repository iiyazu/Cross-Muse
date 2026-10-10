#!/usr/bin/env python3
"""M2b metrics (README section 5), standard library only.

usage: metrics.py <results-dir>... [--out DIR]

A results dir is one run folder written by run.py (meta.json inside) or a parent holding several (group L: one
sub-folder per task). Writes DIR/metrics.json (per run + per group), DIR/metrics.md (tables) and
DIR/view-curve.csv (entries in each agent's view at every wake). DIR defaults to the current directory.

Per run: completion (public + hidden tests; after an injected rot: public + the hidden tests NOT listed in
rot-affects/<seed>-rot<n>.txt + rot verdict "followed"; both the raw hidden result and hidden_unaffected are reported,
and a rot run without hidden-tests.json has completed=None), turns and tokens (by agent), human interventions (the rot message is
not counted), injection share (align_tokens / input+cache_read+cache_write per turn), align_mode distribution, rot
verdict (followed | partial | ignored from rot-tests.json), declaration rate (declare-checklist/<seed>.txt: label |
regex, matched against statements of decision/assumption/convention entries authored by agents) and, in review
mode, whether the planted bug was named (review-keys/<seed>.json) plus false positives on modules without a bug.
When the run enabled MemoryOS (meta memoryos.enabled), an ops section reports /recall and curate counts and
median latencies, failures, summed curate usage (flagged as a lower bound when unmetered_attempts > 0),
proposed curate entries and curate: conflict notices. Runs without MemoryOS omit this section.
"""
import csv
import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent
DECLARED = ("decision", "assumption", "convention")
DEFECT = re.compile(r"\b(bug|wrong|incorrect|broken|fails?|violat\w*|mismatch\w*|defect)\b", re.I)
SOUND = re.compile(r"\bno (bugs?|issues?|problems?|defects?|findings)\b|\bcorrect\b|\bconforms?\b|\bapprove\w*\b|"
                   r"\bmatches (the )?spec\b|\bpass(es|ed)?\b|\blooks good\b", re.I)
SOUND_HEADING = re.compile(r"confirmed|correct|verif|passes|passing|no (bugs?|issues?|findings)|clean|\bok\b|looks good", re.I)


def tok(t: dict) -> int:
    return sum(t.get(k) or 0 for k in ("input", "cache_read", "cache_write", "output"))


def median(xs):
    return st.median(xs) if xs else None


def units(paths) -> list[Path]:
    out = []
    for p in map(Path, paths):
        out += [p] if (p / "meta.json").exists() else sorted(d for d in p.iterdir() if (d / "meta.json").exists())
    return out


def memoryos_metrics(d: Path, meta: dict) -> dict | None:
    """Ops metrics for a MemoryOS-enabled run; None when MemoryOS was off.

    Reads memoryos-calls.json (per-call path/ms/ok/usage from hub.log), entries.json
    (author='curate' proposed count) and log.json (curate: conflict notices).
    """
    mo = meta.get("memoryos") or {}
    enabled = bool(mo.get("enabled")) or meta.get("scenario", {}).get("MEMORYOS") == "on"
    if not enabled:
        return None
    calls = []
    try:
        if (d / "memoryos-calls.json").exists():
            calls = json.loads((d / "memoryos-calls.json").read_text())
    except Exception:
        calls = []
    recall = [c for c in calls if c.get("path") == "/recall"]
    curate = [c for c in calls if c.get("path") == "/curate"]
    r_ms = [c["ms"] for c in recall if isinstance(c.get("ms"), (int, float))]
    c_ms = [c["ms"] for c in curate if isinstance(c.get("ms"), (int, float))]
    usages = [c["usage"] for c in calls if isinstance(c.get("usage"), dict)]
    usage_total: dict = {}
    attempts, unmetered = 0, 0
    for u in usages:
        for k, v in u.items():
            if k in ("attempts", "unmetered_attempts"):
                continue
            if isinstance(v, (int, float)):
                usage_total[k] = usage_total.get(k, 0) + v
        a = u.get("attempts")
        attempts += a if isinstance(a, int) else 1
        um = u.get("unmetered_attempts")
        unmetered += um if isinstance(um, int) else 0
    try:
        ej = json.loads((d / "entries.json").read_text()) if (d / "entries.json").exists() else {"entries": []}
        proposals = sum(1 for e in ej.get("entries", [])
                        if e.get("author") == "curate" and e.get("status") == "proposed")
    except Exception:
        proposals = mo.get("proposals", 0)
    try:
        lj = json.loads((d / "log.json").read_text()) if (d / "log.json").exists() else {"messages": []}
        conflicts = sum(1 for m in lj.get("messages", [])
                        if m.get("kind") == "notice" and isinstance(m.get("body"), str) and "curate:" in m["body"])
    except Exception:
        conflicts = mo.get("conflicts", 0)
    if not proposals and isinstance(mo.get("proposals"), int):
        proposals = mo["proposals"]
    if not conflicts and isinstance(mo.get("conflicts"), int):
        conflicts = mo["conflicts"]
    return {
        "enabled": True,
        "capabilities": mo.get("capabilities", []),
        "recall_calls": len(recall), "recall_ms_median": median(r_ms),
        "recall_failures": sum(1 for c in recall if not c.get("ok")),
        "curate_calls": len(curate), "curate_ms_median": median(c_ms),
        "curate_failures": sum(1 for c in curate if not c.get("ok")),
        "failures": sum(1 for c in calls if not c.get("ok")),
        "usage_total": usage_total, "usage_calls": len(usages),
        "usage_attempts": attempts, "unmetered_attempts": unmetered,
        "usage_lower_bound": unmetered > 0,
        "proposals": proposals, "conflicts": conflicts,
    }


def rot_verdict(d: Path, meta: dict) -> dict:
    rot = meta.get("rot") or {}
    if not rot.get("expected"):
        return {"verdict": "no_rot"}
    if not rot.get("injected"):
        return {"verdict": "not_injected"}
    f = d / "rot-tests.json"
    tests = {k: v for k, v in (json.loads(f.read_text())["tests"] if f.exists() else {}).items()
             if k.startswith(f"test_rot{rot['n']}_")}
    ok = sum(v == "ok" for v in tests.values())
    verdict = "no_tests" if not tests else "followed" if ok == len(tests) else "ignored" if ok == 0 else "partial"
    return {"verdict": verdict, "passed": ok, "total": len(tests), "kind": rot.get("kind"),
            "superseded_entry": rot.get("supersedes")}


def hidden_unaffected(d: Path, meta: dict) -> dict | None:
    """Hidden tests minus the ones the injected rot legitimately breaks (rot-affects/<seed>-rot<n>.txt).

    None when no rot was injected or the per-test results are missing (hidden-tests.json, written by run.py)."""
    rot = meta.get("rot") or {}
    f, a = d / "hidden-tests.json", EXP / "rot-affects" / f"{meta['seed']}-rot{rot.get('n')}.txt"
    if not rot.get("injected") or not f.exists() or not a.exists():
        return None
    skip = {ln.strip() for ln in a.read_text().splitlines() if ln.strip()}
    ids = json.loads(f.read_text()).get("ids") or {}
    kept = {k: v for k, v in ids.items() if k not in skip}
    return {"passed": sum(v == "ok" for v in kept.values()), "total": len(kept), "excluded": len(skip),
            "failed": sorted(k for k, v in kept.items() if v == "fail")}


def declaration(d: Path, meta: dict) -> dict | None:
    f = EXP / "declare-checklist" / f"{meta['seed']}.txt"
    e = d / "entries.json"
    if not f.exists() or not e.exists():
        return None
    agents = {a[0] for a in meta["agents"]}
    stmts = [x["statement"] for x in json.loads(e.read_text())["entries"]
             if x["kind"] in DECLARED and x["author"] in agents and json.loads(x["refs"] or "[0]")[0] >= meta["first_message_id"]]
    items = [ln.split("|", 1) for ln in f.read_text().splitlines() if "|" in ln and not ln.startswith("#")]
    hit = {label.strip(): any(re.search(rx.strip(), s, re.I) for s in stmts) for label, rx in items}
    return {"declared": sum(hit.values()), "total": len(hit), "rate": sum(hit.values()) / len(hit),
            "missing": [k for k, v in hit.items() if not v], "agent_entries": len(stmts)}


def claim_lines(block: str) -> list[str]:
    """Lines of a review message that can name a defect: a line is judged alone (a message that says "other modules pass"
    and also reports a bug elsewhere must not taint the passing modules), and lines under a heading that declares the
    section sound (CONFIRMED CORRECT, Verification, ...) are skipped."""
    out, sound_section = [], False
    for ln in block.splitlines():
        if ln.lstrip().startswith("#"):
            sound_section = bool(SOUND_HEADING.search(ln))
        if not sound_section:
            out += [x for x in re.split(r"(?<=[.;:])\s+(?=[A-Z`])|;\s+", ln) if x.strip()]
    return out


def review(d: Path, meta: dict) -> dict | None:
    f = EXP / "review-keys" / f"{meta['seed']}.json"
    r = d / "review.md"
    if meta["scenario"].get("MODE") != "review" or not f.exists() or not r.exists():
        return None
    keys, planted = json.loads(f.read_text()), f"bug-{meta['scenario']['BUG']}"
    blocks = re.split(r"\n(?=## #)", r.read_text())
    has = lambda b, rx: re.search(rx, b, re.I)  # noqa: E731
    k = keys[planted]
    detected = any(has(b, k["file"]) and has(b, k["function"]) and has(b, k["symptom"]) for b in blocks)
    clean = keys["clean"] + [{"file": v["file"]} for n, v in keys.items() if n.startswith("bug-") and n != planted]
    lines = [ln for b in blocks for ln in claim_lines(b)]
    flagged = [c["file"] for c in clean if any((has(ln, c["file"]) or (c.get("function") and has(ln, c["function"]))) and DEFECT.search(ln)
                                              and not SOUND.search(ln) for ln in lines)]
    return {"planted": planted, "detected": detected, "false_positives": flagged, "modules_without_bug": len(clean)}


def run_metrics(d: Path) -> dict:
    meta = json.loads((d / "meta.json").read_text())
    log = json.loads((d / "log.json").read_text())
    turns, msgs = log["turns"], log["messages"]
    ratios, align, per_agent = [], 0, {}
    for t in turns:
        total_in = sum(t.get(k) or 0 for k in ("input", "cache_read", "cache_write"))
        align += t.get("align_tokens") or 0
        if total_in:
            ratios.append((t.get("align_tokens") or 0) / total_in)
        a = per_agent.setdefault(t["agent_id"], {"turns": 0, "tokens": 0})
        a["turns"] += 1
        a["tokens"] += tok(t)
    inj_total = sum(sum(t.get(k) or 0 for k in ("input", "cache_read", "cache_write")) for t in turns)
    human = sum(m["sender"] == "human" for m in msgs)
    rot = rot_verdict(d, meta)
    status = lambda n: (d / n).read_text().strip() if (d / n).exists() else None  # noqa: E731
    pub, hid = status("public.status"), status("hidden.status")
    hu = hidden_unaffected(d, meta)
    if pub is None:
        done = None
    elif meta["rot"].get("injected"):  # rot injected: unaffected hidden tests + the post-rot tests, not the original hidden run
        done = None if hu is None else pub == "pass" and hu["total"] > 0 and not hu["failed"] and rot["verdict"] == "followed"
    else:
        done = pub == "pass" and hid == "pass"
    return {
        "run": meta["run"], "seed": meta["seed"], "group": meta["group"], "mode": meta["scenario"].get("MODE", "run"),
        "completed": done, "public": pub, "hidden": hid, "hidden_unaffected": hu,
        "quiet": meta["quiet"], "seconds": meta["seconds"],
        "turns": len(turns), "failed_turns": sum(t["state"] != "succeeded" for t in turns),
        "tokens": sum(tok(t) for t in turns), "by_agent": per_agent,
        "human_messages": human, "human_interventions": max(human - 1 - bool(meta["rot"].get("injected")), 0),
        "notices": sum(m["kind"] == "notice" for m in msgs),
        "injection": {"align_tokens": align, "share_total": align / inj_total if inj_total else None,
                      "share_median": median(ratios), "share_max": max(ratios, default=None),
                      "share_median_injected": median([r for r in ratios if r]),
                      "modes": dict(Counter(t.get("align_mode") or "none" for t in turns))},
        "rot": rot, "declaration": declaration(d, meta), "review": review(d, meta),
        "memoryos": memoryos_metrics(d, meta),
        "view_curve": {a: [t["view_entries"] for t in turns if t["agent_id"] == a] for a in per_agent},
    }


def group_metrics(rs: list[dict]) -> dict:
    mean = lambda xs: st.mean(xs) if xs else None  # noqa: E731
    done = [r["completed"] for r in rs if r["completed"] is not None]
    rev = [r["review"] for r in rs if r["review"]]
    decl = [r["declaration"]["rate"] for r in rs if r["declaration"]]
    return {
        "runs": len(rs), "completion_rate": mean([float(x) for x in done]),
        "turns_mean": mean([r["turns"] for r in rs]), "tokens_mean": mean([r["tokens"] for r in rs]),
        "tokens_median": median([r["tokens"] for r in rs]),
        "interventions_mean": mean([r["human_interventions"] for r in rs]),
        "injection_share_total": mean([r["injection"]["share_total"] for r in rs if r["injection"]["share_total"] is not None]),
        "injection_share_max": max([r["injection"]["share_max"] for r in rs if r["injection"]["share_max"] is not None], default=None),
        "rot": dict(Counter(r["rot"]["verdict"] for r in rs)),
        "declaration_rate_mean": mean(decl),
        "review_detection_rate": mean([float(x["detected"]) for x in rev]),
        "review_false_positive_rate": mean([len(x["false_positives"]) / x["modules_without_bug"] for x in rev]),
    }


def fmt(v, pct=False) -> str:
    return "-" if v is None else f"{v:.1%}" if pct else f"{v:,.0f}" if isinstance(v, float) and abs(v) >= 100 else str(round(v, 2) if isinstance(v, float) else v)


def fmt_usage(mo: dict) -> str:
    if not mo or not mo.get("usage_total"):
        return "-" if not mo or not mo.get("usage_calls") else "{} (n={})".format(
            ", ".join(f"{k}={v}" for k, v in sorted(mo["usage_total"].items())), mo["usage_calls"]) + (" lower-bound" if mo.get("usage_lower_bound") else "")
    s = ", ".join(f"{k}={v}" for k, v in sorted(mo["usage_total"].items()))
    return f"{s} (n={mo['usage_calls']})" + (" lower-bound" if mo.get("usage_lower_bound") else "")


def markdown(runs: list[dict], groups: dict) -> str:
    out = ["## Runs", "", "| run | group | mode | done | hidden (raw) | hidden unaffected | turns | tokens | interv. | inject total | inject median | inject max | modes | rot | declared | review |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        i, d, v, u = r["injection"], r["declaration"], r["review"], r["hidden_unaffected"]
        out.append(f"| {r['run']}/{r['seed']} | {r['group']} | {r['mode']} | {fmt(r['completed'])} | {fmt(r['hidden'])} |"
                   f" {u and f'{u['passed']}/{u['total']}' or '-'} | {r['turns']} | {r['tokens']:,} |"
                   f" {r['human_interventions']} | {fmt(i['share_total'], True)} | {fmt(i['share_median'], True)} | {fmt(i['share_max'], True)} |"
                   f" {' '.join(f'{k}:{n}' for k, n in sorted(i['modes'].items()))} | {r['rot']['verdict']} |"
                   f" {d and f'{d['declared']}/{d['total']}' or '-'} |"
                   f" {v and ('hit' if v['detected'] else 'miss') + f' (fp {len(v['false_positives'])})' or '-'} |")
    out += ["", "## Groups", "", "| group | runs | completion | turns | tokens (mean) | interv. | inject total | inject max | rot | declared | detection | false pos. |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, g in sorted(groups.items()):
        out.append(f"| {k} | {g['runs']} | {fmt(g['completion_rate'], True)} | {fmt(g['turns_mean'])} | {fmt(g['tokens_mean'])} |"
                   f" {fmt(g['interventions_mean'])} | {fmt(g['injection_share_total'], True)} | {fmt(g['injection_share_max'], True)} |"
                   f" {' '.join(f'{a}:{n}' for a, n in sorted(g['rot'].items()))} | {fmt(g['declaration_rate_mean'], True)} |"
                   f" {fmt(g['review_detection_rate'], True)} | {fmt(g['review_false_positive_rate'], True)} |")
    mo_runs = [r for r in runs if r.get("memoryos")]
    if mo_runs:
        out += ["", "## MemoryOS (ops; unattended: proposals are never confirmed)", "",
                "| run | recall calls | recall ms median | curate calls | curate ms median | failures | usage total | proposals | conflicts |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in mo_runs:
            m = r["memoryos"]
            out.append(f"| {r['run']}/{r['seed']} | {m['recall_calls']} | {fmt(m['recall_ms_median'])} |"
                       f" {m['curate_calls']} | {fmt(m['curate_ms_median'])} | {m['failures']} |"
                       f" {fmt_usage(m)} | {m['proposals']} | {m['conflicts']} |")
    return "\n".join(out) + "\n"


def main(argv) -> None:
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path(".")
    paths = [a for i, a in enumerate(argv) if a != "--out" and (i == 0 or argv[i - 1] != "--out")]
    runs = [run_metrics(d) for d in units(paths)]
    if not runs:
        raise SystemExit("no results (a folder with meta.json) found")
    groups = {}
    for r in runs:
        groups.setdefault(("review-" if r["mode"] == "review" else "") + r["group"], []).append(r)
    groups = {k: group_metrics(v) for k, v in groups.items()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps({"runs": runs, "groups": groups}, indent=1, ensure_ascii=False))
    (out / "metrics.md").write_text(markdown(runs, groups))
    with (out / "view-curve.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "seed", "group", "agent", "wake_no", "view_entries"])
        for r in runs:
            for agent, curve in r["view_curve"].items():
                w.writerows([r["run"], r["seed"], r["group"], agent, i, v] for i, v in enumerate(curve, 1))
    print((out / "metrics.md").read_text())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
