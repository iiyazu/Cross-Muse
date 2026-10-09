#!/usr/bin/env bash
# Session rotation with real agents: e2e/rotation.sh <run-no>
# Both agents get a low --rotate-at so the second wake must open a new session. The second message asks
# what the agent said before, which only the bootstrap pack (recent thread messages) can answer.
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
n=$1
WS="$E2E/ws-rotation-$n" RES="$E2E/results/rotation-$n"
export XMUSE_STATE_ROOT="$E2E/state-rotation-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES"
cp -r "$E2E/seeds/textkit" "$WS"
git -C "$WS" init -q && git -C "$WS" add -A && git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm seed
cd "$WS"
"$X" init . >/dev/null
"$X" agent add claude-1 --vendor claude --rotate-at 20000 >/dev/null
"$X" agent add opencode-1 --vendor opencode --rotate-at 10000 >/dev/null
"$X" hub start
for a in claude-1 opencode-1; do
  "$X" send '#notes' "Pick one rule of SPEC.md at random and post its number and a six-word paraphrase here in #notes (to '#notes', no mentions)." \
    --mention $a >/dev/null
  "$X" wait --timeout 600 --settle 5
  "$X" send '#notes' "Without re-reading SPEC.md or calling xmuse_thread: which rule number and paraphrase did $a post in #notes earlier? Send the answer to human." \
    --mention $a >/dev/null
  "$X" wait --timeout 600 --settle 5
done
python3 - "$XMUSE_STATE_ROOT" <<'PY' | tee "$RES/sessions.txt"
import glob, sqlite3, sys
c = sqlite3.connect(glob.glob(sys.argv[1] + "/*/hub.db")[0])
for r in c.execute("select t.id, t.agent_id, t.fresh, s.vendor_session, s.state, u.context from turns t"
                   " join sessions s on s.id=t.session_id join usage u on u.turn_id=t.id order by t.id"):
    print("turn %s %s fresh=%s session=%s (%s) context=%s" % r)
PY
"$X" log > "$RES/log.txt"
"$X" usage > "$RES/usage.txt"
"$X" hub stop
