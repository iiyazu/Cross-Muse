#!/usr/bin/env bash
# dsh crash recovery through the hub: e2e/killresume.sh <run-no>
# dsh-1 is told to send K1, then do slow work, then finish. Right after K1 reaches the hub, `xmuse stop`
# kills the dsh process (SIGKILL to its group). The next message makes the hub resume the session: dsh
# replays the killed turn before the new one, so its tool calls may run again. Records whether K1 arrives
# twice, and the session log's turn/end records.
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
PY="$E2E/../hub/.venv/bin/python"
n=$1
WS="${E2E_WS_ROOT:-/mnt/c/Users/$USER/xmuse-e2e}/ws-killresume-$n" RES="$E2E/results/killresume-$n"
export XMUSE_STATE_ROOT="$E2E/state-killresume-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES"
cp -r "$E2E/seeds/textkit" "$WS"
git -C "$WS" init -q && git -C "$WS" add -A && git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm seed
cd "$WS"
"$X" init . >/dev/null
"$X" agent add dsh-1 --vendor dsh >/dev/null
"$X" hub start
STATE=$(ls -d "$XMUSE_STATE_ROOT"/*/)
q() { "$PY" -c "import sqlite3,sys;r=sqlite3.connect(sys.argv[1]).execute(sys.argv[2]).fetchone();print(r[0] if r else '')" "$STATE/hub.db" "$1"; }
"$X" send dsh-1 "Warm-up: reply READY to human with xmuse_send, then xmuse_done." >/dev/null
"$X" wait --timeout 300 --settle 3
"$X" send dsh-1 "Step 1: send human exactly 'K1' with xmuse_send. Step 2: without tools, write the numbers 1 to 400 as English words, comma-separated. Step 3: xmuse_done." >/dev/null
until [ "$(q "select count(*) from messages where body='K1'")" -ge 1 ]; do sleep 0.3; done
"$X" stop --agent dsh-1 | tee "$RES/stop.json"
sleep 3
"$X" send dsh-1 "After the interruption: reply K2 to human with xmuse_send, then xmuse_done." >/dev/null
"$X" wait --timeout 600 --settle 5
sid=$(q "select vendor_session from sessions where state='current'")
{
  echo "K1 messages: $(q "select count(*) from messages where body='K1'")"
  echo "K2 messages: $(q "select count(*) from messages where body='K2'")"
  "$PY" -c "import sqlite3,sys;[print('turn',*r) for r in sqlite3.connect(sys.argv[1]).execute('select id,state,error from turns')]" "$STATE/hub.db"
  "$PY" - "$sid" "${DSH_HOME_WSL:-/mnt/c/Users/$USER/.dsh}" <<'PY'
import glob, json, sys
import zstandard
[log] = glob.glob(f"{sys.argv[2]}/sessions/*/{sys.argv[1]}/session.v4.jsonl.zstd")
recs = [json.loads(x) for x in zstandard.ZstdDecompressor().stream_reader(open(log, "rb")).read().decode().splitlines()]
print("session log turn/end:", [r["data"].get("reason", {}).get("kind") for r in recs if r["type"] == "turn/end"])
print("xmuse_send calls in log:", sum(r["type"] == "tool/call" and "xmuse_send" in json.dumps(r) for r in recs))
PY
} | tee "$RES/killresume.txt"
"$X" log > "$RES/log.txt"
"$X" usage > "$RES/usage.txt"
"$X" hub stop
