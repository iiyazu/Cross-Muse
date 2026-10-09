#!/usr/bin/env bash
# One end-to-end run: e2e/run.sh <scenario> <run-no>
# Rebuilds e2e/ws-<scenario>-<n> from seeds/, sets up xmuse with claude-1 + opencode-1, sends the task
# to #task (mentioning the implementer), waits for the chain to go quiet, then records the message
# flow, per-wake tokens and test results under e2e/results/<scenario>-<n>/. Hub state (logs, raw
# vendor streams) stays in e2e/state-<scenario>-<n>/ (not committed).
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
sc=$1 n=$2
. "$E2E/scenarios/$sc.env"
WS="$E2E/ws-$sc-$n" RES="$E2E/results/$sc-$n"
export XMUSE_STATE_ROOT="$E2E/state-$sc-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES"
cp -r "$E2E/seeds/$SEED" "$WS"
git -C "$WS" init -q
git -C "$WS" add -A
git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm "seed $SEED"
cd "$WS"
"$X" init . >/dev/null
"$X" agent add claude-1 --vendor claude --role "${CLAUDE_ROLE:-}" >/dev/null
"$X" agent add opencode-1 --vendor opencode >/dev/null
"$X" hub start
start=$(date +%s)
"$X" send '#task' "$TASK" --mention "$IMPL" > "$RES/sent.json"
rc=0
"$X" wait --timeout "${TIMEOUT:-3600}" --settle 30 || rc=$?
end=$(date +%s)
"$X" log > "$RES/log.txt"
"$X" log --json > "$RES/log.json"
"$X" usage > "$RES/usage.txt"
"$X" hub status > "$RES/status.json"
"$X" hub stop
git -C "$WS" status --short > "$RES/git-status.txt"
git -C "$WS" diff --stat HEAD > "$RES/git-diff-stat.txt" || true
(python3 -m unittest discover -s tests > "$RES/tests-public.txt" 2>&1) && pub=pass || pub=fail
cp "$E2E/hidden/test_hidden_$SEED.py" tests/
(python3 -m unittest discover -s tests -p 'test_hidden_*.py' > "$RES/tests-hidden.txt" 2>&1) && hid=pass || hid=fail
rm tests/test_hidden_$SEED.py
python3 "$E2E/check.py" "$RES" "$IMPL" "$REVIEW" "$pub" "$hid" "$((end - start))" "$rc" | tee "$RES/summary.json"
