#!/usr/bin/env bash
# Evaluate the gold patches of a pilot sample with the official SWE-Bench Pro harness on local docker.
# usage: experiments/swebp/gold-check.sh BENCH_DIR TAG [ID-substring] [WORKERS]
#   BENCH_DIR holds swebench-pro-verified/, SWE-bench_Pro-os/, pilot/ (sample.py writes pilot/ there)
# The Verified jsonl stores list fields as JSON lists; the harness eval()s them as strings, so they are repr()'d here.
set -e
bench=$(realpath "$1"); tag=$2; pat=${3:-}; workers=${4:-2}
cd "$bench"
[ -d .venv ] || { uv venv -q .venv --python 3.12 && uv pip install -q --python .venv/bin/python pandas tqdm docker; }
.venv/bin/python - "$tag" "$pat" <<'PY'
import json, sys
tag, pat = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(f"pilot/sample-{tag}.jsonl")]
rows = [r for r in rows if pat in r["instance_id"]]
with open(f"pilot/evalin-{tag}.jsonl", "w") as f:
    for r in rows:
        f.write(json.dumps({k: (repr(v) if isinstance(v, list) else v) for k, v in r.items()}) + "\n")
gold = [g for g in json.load(open(f"pilot/gold-{tag}.json")) if pat in g["instance_id"]]
json.dump(gold, open(f"pilot/goldin-{tag}.json", "w"))
print("instances:", len(rows))
PY
cd SWE-bench_Pro-os
../.venv/bin/python swe_bench_pro_eval.py --raw_sample_path=../pilot/evalin-$tag.jsonl \
  --patch_path=../pilot/goldin-$tag.json --output_dir=../pilot/gold-out-$tag --scripts_dir=run_scripts \
  --use_local_docker --dockerhub_username=jefzda --num_workers="$workers" 2>&1 | tail -5
cat ../pilot/gold-out-$tag/eval_results.json; echo
