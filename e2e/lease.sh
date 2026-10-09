#!/usr/bin/env bash
# dsh lease conflict, end to end: e2e/lease.sh <run-no>
# The hub warms up dsh-1 (one session). Then an outside dsh process resumes that same session with a long
# task, and while it holds the write lease the human sends dsh-1 a message. Expected: the hub's run is
# refused ("already owned"), backs off, retries after the outside run ends, and delivers; the session log
# has one turn/end per successful run and nothing is lost.
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
PY="$E2E/../hub/.venv/bin/python"
n=$1
WS="${E2E_WS_ROOT:-/mnt/c/Users/$USER/xmuse-e2e}/ws-lease-$n" RES="$E2E/results/lease-$n"
export XMUSE_STATE_ROOT="$E2E/state-lease-$n"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$RES"
mkdir -p "$RES"
cp -r "$E2E/seeds/textkit" "$WS"
git -C "$WS" init -q && git -C "$WS" add -A && git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm seed
cd "$WS"
"$X" init . >/dev/null
"$X" agent add dsh-1 --vendor dsh >/dev/null
"$X" hub start
"$X" send dsh-1 "Warm-up: send human the title line of SPEC.md with xmuse_send, then xmuse_done." >/dev/null
"$X" wait --timeout 300 --settle 3
STATE=$(ls -d "$XMUSE_STATE_ROOT"/*/)
sid=$("$PY" -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute(\"select vendor_session from sessions where state='current'\").fetchone()[0])" "$STATE/hub.db")
echo "session: $sid" | tee "$RES/lease.txt"
# the outside writer: same session, same cwd, same exe as the hub (model-only overlay from the precheck)
"$PY" - "$STATE" "$sid" "$WS" > "$RES/outside.jsonl" 2> "$RES/outside.err" <<'PY' &
import sys
from pathlib import Path
from xmuse.adapters.dsh import DshHeadless
state, sid, ws = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
d = DshHeadless(None, state, {})
info, u = d.run(ws, state / "runs" / "precheck-dsh-1.patch.yml", sid,
                "Outside writer (a test of session locking): without using any tool, write the numbers 1 to 300 "
                "as English words, comma-separated, then the numbers 300 down to 1 the same way.", state / "logs" / "outside.jsonl")
print({"ok": info.get("ok"), "rc": info["rc"], "error": info.get("error"), "tokens": u.total})
PY
outside=$!
until grep -q '"type": *"session"\|"type":"session"' "$STATE/logs/outside.jsonl" 2>/dev/null; do sleep 0.5; done
echo "outside writer holds the session at $(date +%T)" | tee -a "$RES/lease.txt"
"$X" send dsh-1 "Sent while another dsh process holds your session: reply LEASE-OK to human with xmuse_send, then xmuse_done." \
  > "$RES/sent.json"
wait $outside
echo "outside writer: $(cat "$RES/outside.jsonl") ended at $(date +%T)" | tee -a "$RES/lease.txt"
"$X" wait --timeout 600 --settle 5
"$PY" - "$STATE" "$sid" "${DSH_HOME_WSL:-/mnt/c/Users/$USER/.dsh}" <<'PY' | tee -a "$RES/lease.txt"
import glob, json, sqlite3, sys
from pathlib import Path
import zstandard
state, sid, home = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
c = sqlite3.connect(state / "hub.db")
for t in c.execute("select id, state, error from turns order by id"):
    print("hub turn", t)
refusals = sum('already owned' in l for l in (state / "runs" / "turn-2.jsonl").open())
print("hub run refusals for turn 2:", refusals)
print("reply:", c.execute("select body from messages where sender='dsh-1' and kind='message' order by id desc").fetchone())
[log] = glob.glob(f"{home}/sessions/*/{sid}/session.v4.jsonl.zstd")
recs = [json.loads(x) for x in zstandard.ZstdDecompressor().stream_reader(open(log, "rb")).read().decode().splitlines()]
ends = [r["data"].get("reason", {}).get("kind") for r in recs if r["type"] == "turn/end"]
print("session log turn/end:", len(ends), ends)
PY
"$X" log > "$RES/log.txt"
"$X" usage > "$RES/usage.txt"
"$X" hub stop
