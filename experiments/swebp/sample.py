"""Stratified pilot sample from SWE-Bench Pro Verified (seeded, reproducible) + gold-patch file for harness check.

usage: python sample.py BENCH_DIR N SEED   (BENCH_DIR holds swebench-pro-verified/; output goes to BENCH_DIR/pilot/)
Writes pilot/sample-<N>-<SEED>.jsonl (rows), pilot/ids-<N>-<SEED>.txt, pilot/gold-<N>-<SEED>.json (instance_id, patch, prefix).
Strata = repo; allocation proportional to repo size, at least 1 per repo; within a repo, uniform random.
Rows whose lines-changed in the gold patch exceed MAX_LINES are dropped first (keep tasks short, see T10).
"""
import json, random, sys, collections
from pathlib import Path

MAX_LINES = 400
here = Path(sys.argv[1]).resolve()
rows = [json.loads(l) for l in open(here / "swebench-pro-verified/swebench_pro_verified.jsonl")]


def changed(p: str) -> int:
    return sum(1 for l in p.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))


n, seed = int(sys.argv[2]), int(sys.argv[3])
pool = [r for r in rows if changed(r["patch"]) <= MAX_LINES]
by = collections.defaultdict(list)
for r in pool:
    by[r["repo"]].append(r)
rng = random.Random(seed)
alloc = {k: max(1, round(n * len(v) / len(pool))) for k, v in by.items()}
while sum(alloc.values()) > n:
    alloc[max(alloc, key=alloc.get)] -= 1
pick = []
for k in sorted(by):
    pick += rng.sample(by[k], alloc[k])
out = here / "pilot"
out.mkdir(exist_ok=True)
tag = f"{n}-{seed}"
with open(out / f"sample-{tag}.jsonl", "w") as f:
    for r in pick:
        f.write(json.dumps(r) + "\n")
(out / f"ids-{tag}.txt").write_text("".join(r["instance_id"] + "\n" for r in pick))
json.dump([{"instance_id": r["instance_id"], "patch": r["patch"], "prefix": "gold"} for r in pick],
          open(out / f"gold-{tag}.json", "w"))
print(f"pool {len(pool)}/{len(rows)} (<= {MAX_LINES} changed lines); picked {len(pick)}")
for r in pick:
    print(r["repo_language"], changed(r["patch"]), r["dockerhub_tag"])
print("types:", type(rows[0]["selected_test_files_to_run"]).__name__, type(rows[0]["fail_to_pass"]).__name__)
