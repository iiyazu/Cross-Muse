#!/usr/bin/env bash
# One end-to-end run: e2e/run.sh <scenario> <run-no>
# Rebuilds the workspace from seeds/ under $E2E_WS_ROOT (default C:\\Users\\$USER\\xmuse-e2e, shared by all
# three agents: dsh needs a native C:\\ path), sets up xmuse with $AGENTS (default claude-1, opencode-1 and
# dsh-1), sends the task to #task (mentioning the implementer), waits for the chain to go quiet, then
# records the message flow, per-wake tokens and test results under e2e/results/<scenario>-<n>/. Hub state
# (logs, raw vendor streams) stays in e2e/state-<scenario>-<n>/ (not committed).
# A scenario sets SEED, IMPL, REVIEW (one id, or two separated by a comma) and either TASK or GOAL (the
# roles part of the task is then built from IMPL and REVIEW).
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
sc=$1 n=$2
. "$E2E/scenarios/$sc.env"
WS="${E2E_WS_ROOT:-/mnt/c/Users/$USER/xmuse-e2e}/ws-$sc-$n" RES="$E2E/results/$sc-$n"
AGENTS=${AGENTS:-"claude-1:claude opencode-1:opencode dsh-1:dsh"}
if [ -z "${TASK:-}" ]; then
  case $REVIEW in
    *,*) r1=${REVIEW%,*} r2=${REVIEW#*,}
         ROLES="Roles: $IMPL implements; $r1 and $r2 both review. When the implementation is ready, $IMPL sends ONE review_request in #task that mentions both $r1 and $r2. Each reviewer checks the code against SPEC.md, runs the tests, and probes every SPEC rule with edge cases of its own (in a throwaway script, not committed), then replies in #task with concrete findings or an explicit approval. $IMPL merges both reviews, fixes every finding, and asks again (mentioning only the reviewers who have not approved yet) until both approve. Then $IMPL reports the result to human." ;;
    *)   ROLES="Roles: $IMPL implements; $REVIEW reviews. When the implementation is ready, $IMPL sends a review_request to $REVIEW in #task. $REVIEW checks the code against SPEC.md, runs the tests, and probes every SPEC rule with edge cases of its own (in a throwaway script, not committed), then replies with concrete findings or an explicit approval. $IMPL fixes every finding and asks again until $REVIEW approves. Then $IMPL reports the result to human." ;;
  esac
  TASK="Task: $GOAL (run: python3 -m unittest discover -s tests). $ROLES Do not push, merge or touch files outside this repo."
fi
export XMUSE_STATE_ROOT="$E2E/state-$sc-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES"
cp -r "$E2E/seeds/$SEED" "$WS"
git -C "$WS" init -q
git -C "$WS" add -A
git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm "seed $SEED"
cd "$WS"
"$X" init . >/dev/null
for a in $AGENTS; do "$X" agent add "${a%:*}" --vendor "${a#*:}" >/dev/null; done
echo "$TASK" > "$RES/task.txt"
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
