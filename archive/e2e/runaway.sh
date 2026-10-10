#!/usr/bin/env bash
# Runaway guard, end to end: e2e/runaway.sh <run-no>
# A) a ping-pong task with no natural end: the chain must be capped at max_chain_wakes (12).
# B) the same game again (new chain): after 3 wakes the human runs `xmuse stop`; the running turn is
#    interrupted, queued messages are canceled and nothing wakes afterwards.
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
n=$1
WS="$E2E/ws-runaway-$n" RES="$E2E/results/runaway-$n"
export XMUSE_STATE_ROOT="$E2E/state-runaway-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES" "$WS"
git -C "$WS" init -q
echo "# runaway test" > "$WS/README.md"
git -C "$WS" add -A
git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm seed
cd "$WS"
"$X" init . >/dev/null
"$X" agent add claude-1 --vendor claude >/dev/null
"$X" agent add opencode-1 --vendor opencode >/dev/null
"$X" hub start
GAME="Counting game (a test of the xmuse relay that the user is running on purpose). claude-1 starts by sending the number 1 to opencode-1 with xmuse_send(to='opencode-1'). Whoever receives a number N from the other replies directly to the sender with N+1 via xmuse_send. Keep going and do not end the game yourselves: the hub's runaway guard is what should stop it. Do not touch any files."
db() { python3 - "$XMUSE_STATE_ROOT" "$@" <<'PY'
import glob, sqlite3, sys
c = sqlite3.connect(glob.glob(sys.argv[1] + "/*/hub.db")[0])
print(c.execute(sys.argv[2]).fetchone()[0])
PY
}
# A: cap
"$X" send '#game' "$GAME" --mention claude-1 > "$RES/a-sent.json"
"$X" wait --timeout 1800 --settle 30
echo "A: chain 1 $(db 'select state||" "||coalesce(note,"")||" wakes="||wakes from chains where id=1')" | tee "$RES/a.txt"
echo "A: turns=$(db 'select count(*) from turns where chain_id=1')" | tee -a "$RES/a.txt"
# B: stop
"$X" send '#game' "Second game, same rules. $GAME" --mention claude-1 > "$RES/b-sent.json"
chain=$(python3 -c "import json;print(json.load(open('$RES/b-sent.json'))['chain'])")
until [ "$(db "select count(*) from turns where chain_id=$chain")" -ge 3 ] && \
      [ "$(db "select count(*) from turns where chain_id=$chain and state='running'")" -ge 1 ]; do sleep 1; done
"$X" stop | tee "$RES/b-stop.json"
before=$(db "select count(*) from turns where chain_id=$chain")
sleep 60
after=$(db "select count(*) from turns where chain_id=$chain")
echo "B: chain $chain $(db "select state||' '||coalesce(note,'') from chains where id=$chain") turns_at_stop=$before turns_60s_later=$after" | tee "$RES/b.txt"
echo "B: running=$(db "select count(*) from turns where state='running'") queued=$(db "select count(*) from deliveries where state='queued'") canceled=$(db "select count(*) from deliveries where state='canceled'")" | tee -a "$RES/b.txt"
"$X" log > "$RES/log.txt"
"$X" log --json > "$RES/log.json"
"$X" usage > "$RES/usage.txt"
"$X" hub stop
