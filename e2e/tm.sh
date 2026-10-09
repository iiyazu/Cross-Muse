#!/usr/bin/env bash
# tmux helpers for the human-present tests (ported from spikes/tm.sh, plus wait-for-text).
#   tm.sh cap <session> <file>          capture the pane (+300 lines scrollback)
#   tm.sh wait <session> <regex> [sec]  wait until the pane shows <regex> (exit 1 on timeout)
#   tm.sh type <session> <text>         type literal text, then Enter (call `wait` for readiness first)
#   tm.sh keys <session> <keys...>      raw tmux keys (Enter, Down, Escape, C-c ...)
cmd=$1 s=$2; shift 2
case $cmd in
  cap)  tmux capture-pane -p -J -S -300 -t "$s" > "$1" ;;
  wait) end=$((SECONDS + ${2:-60}))
        until tmux capture-pane -p -J -t "$s" | grep -Eq "$1"; do
          [ $SECONDS -ge $end ] && { echo "timeout waiting for /$1/ in $s" >&2; exit 1; }
          sleep 0.5
        done ;;
  type) tmux send-keys -t "$s" -l "$*"; sleep 0.5; tmux send-keys -t "$s" Enter ;;
  keys) tmux send-keys -t "$s" "$@" ;;
esac
