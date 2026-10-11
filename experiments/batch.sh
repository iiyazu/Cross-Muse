#!/usr/bin/env bash
# usage: experiments/batch.sh <plan-file>
# Runs "<scenario> <run-no>" lines of the plan one after another (blank lines and # comments skipped). Progress goes to
# experiments/results/batch-progress.txt (start / end with rc and time); a failing run does not stop the batch.
# A results folder that already exists is moved to results/_prev/ first, never overwritten. At the end metrics.py
# writes experiments/results/metrics-<plan name>/.
export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"
export WSL_INTEROP=/run/WSL/1_interop   # a background start inherits the caller's interop socket, which goes stale (dsh then exits 1 silently)

plan="$1"
[ -f "$plan" ] || { echo "usage: $0 <plan-file>" >&2; exit 2; }
exp="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
res="$exp/results"
prog="$res/batch-progress.txt"
name="$(basename "$plan" .txt)"
mkdir -p "$res"
dirs=()

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(stamp) BATCH start $name" >> "$prog"
while read -r scen no rest; do
    case "$scen" in ''|'#'*) continue ;; esac
    run="$scen-$no"
    if [ -d "$res/$run" ]; then
        mkdir -p "$res/_prev"
        mv "$res/$run" "$res/_prev/$run-$(date +%Y%m%d-%H%M%S)"
    fi
    t0=$(date +%s)
    echo "$(stamp) START $run" >> "$prog"
    python3 "$exp/run.py" "$scen" "$no" > "$res/batch-$run.log" 2>&1 < /dev/null
    rc=$?
    echo "$(stamp) END   $run rc=$rc seconds=$(( $(date +%s) - t0 ))" >> "$prog"
    [ -f "$res/$run/meta.json" ] && dirs+=("$res/$run")
done < "$plan"

if [ "${#dirs[@]}" -gt 0 ]; then
    python3 "$exp/metrics.py" "${dirs[@]}" --out "$res/metrics-$name" > "$res/metrics-$name.log" 2>&1
    echo "$(stamp) METRICS rc=$? -> results/metrics-$name" >> "$prog"
fi
echo "$(stamp) BATCH end $name" >> "$prog"
