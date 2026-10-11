#!/usr/bin/env bash
# Human-present test, setup half: e2e/presence-setup.sh <name>
# Builds e2e/ws-<name> (textkit seed), starts the hub with claude-1 + opencode-1 and lets the hub run one
# headless turn for each agent, so each has a session the human can then open in its native UI.
set -eu
E2E="$(cd "$(dirname "$0")" && pwd)"
X="$E2E/../bin/xmuse"
name=$1
WS="$E2E/ws-$name"
export XMUSE_STATE_ROOT="$E2E/state-$name"
rm -rf "$WS" "$XMUSE_STATE_ROOT" "$E2E/results/$name"
mkdir -p "$E2E/results/$name"
cp -r "$E2E/seeds/textkit" "$WS"
git -C "$WS" init -q && git -C "$WS" add -A && git -C "$WS" -c user.name=e2e -c user.email=e2e@local commit -qm seed
cd "$WS"
"$X" init . >/dev/null
"$X" agent add claude-1 --vendor claude >/dev/null
"$X" agent add opencode-1 --vendor opencode >/dev/null
"$X" hub start
"$X" send claude-1 "Warm-up: read SPEC.md and send human a one-sentence summary of it with xmuse_send."
"$X" send opencode-1 "Warm-up: read SPEC.md and send human a one-sentence summary of it with xmuse_send."
"$X" wait --timeout 600 --settle 5
"$X" hub status
