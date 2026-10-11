"""Per-wake tokens across e2e runs, by vendor and wake mode: python3 e2e/aggregate.py results/s*-[0-9]"""
import json
import statistics
import sys
from collections import defaultdict

by = defaultdict(list)
for run in sys.argv[1:]:
    d = json.load(open(f"{run}/summary.json"))
    for key, v in d["tokens"]["by_agent_mode"].items():
        agent, mode = key.split(":")
        by[(agent.split("-")[0], mode)] += v["per_wake"]
print(f"{'vendor':10} {'mode':5} {'wakes':>5} {'min':>9} {'median':>9} {'mean':>9} {'max':>9}")
for (vendor, mode), xs in sorted(by.items()):
    print(f"{vendor:10} {mode:5} {len(xs):5} {min(xs):9,} {int(statistics.median(xs)):9,} "
          f"{int(statistics.mean(xs)):9,} {max(xs):9,}")
