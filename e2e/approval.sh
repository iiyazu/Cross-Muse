#!/usr/bin/env bash
# Approval forwarding with a real OpenCode agent: e2e/approval.sh <run-no>
# `git clean*` is an `ask` rule in the generated opencode.json. The hub must turn permission.asked into an
# approvals row plus a notice to the human; `xmuse approve <id> once` lets the command run.
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
n=$1
WS="$E2E/ws-approval-$n" RES="$E2E/results/approval-$n"
export XMUSE_STATE_ROOT="$E2E/state-approval-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES"
cp -r "$E2E/seeds/textkit" "$WS"
git -C "$WS" init -q && git -C "$WS" add -A && git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm seed
touch "$WS/scratch.tmp"
cd "$WS"
"$X" init . >/dev/null
"$X" agent add opencode-1 --vendor opencode >/dev/null
"$X" hub start
"$X" send opencode-1 "Run exactly \`git clean -n\` with your shell tool (a dry run, it deletes nothing) and send human its output."
db() { python3 - "$XMUSE_STATE_ROOT" "$@" <<'PY'
import glob, sqlite3, sys
c = sqlite3.connect(glob.glob(sys.argv[1] + "/*/hub.db")[0])
r = c.execute(sys.argv[2]).fetchone()
print(r[0] if r else "")
PY
}
for _ in $(seq 1 120); do [ -n "$(db 'select id from approvals')" ] && break; sleep 1; done
id=$(db "select id from approvals")
echo "approval: $id $(db 'select action||" "||resources from approvals')" | tee "$RES/approval.txt"
echo "notice: $(db "select body from messages where kind='notice'")" | tee -a "$RES/approval.txt"
"$X" approve "$id" once | tee -a "$RES/approval.txt"
"$X" wait --timeout 600 --settle 5
echo "reply: $(db "select body from messages where sender='opencode-1' and kind='message'")" | tee -a "$RES/approval.txt"
"$X" log > "$RES/log.txt"
"$X" usage > "$RES/usage.txt"
"$X" hub stop
