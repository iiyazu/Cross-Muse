#!/usr/bin/env bash
# Copy the bundle (no tests / node_modules) to the Windows-side install dir.
# Default destination: <Windows user home>/dsh-work/xmuse-bundle (XMUSE_WIN_HOME, else %USERPROFILE% via cmd.exe).
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"
if [ $# -ge 1 ]; then
  DEST="$1"
else
  WIN_HOME="${XMUSE_WIN_HOME:-}"
  if [ -z "$WIN_HOME" ]; then
    prof="$(cd /mnt/c 2>/dev/null && cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r' || true)"
    [ -n "$prof" ] && WIN_HOME="$(wslpath -u "$prof" 2>/dev/null || true)"
  fi
  if [ -z "$WIN_HOME" ] || [ ! -d "$WIN_HOME" ]; then
    echo "cannot find the Windows user's home: pass the destination dir, or set XMUSE_WIN_HOME=/mnt/c/Users/<name>" >&2
    exit 1
  fi
  DEST="$WIN_HOME/dsh-work/xmuse-bundle"
fi
mkdir -p "$DEST"
# bindings.json is runtime state written next to index.js; keep it across syncs.
rsync -rt --delete --exclude test/ --exclude node_modules/ --exclude sync.sh --exclude README.zh.md \
  --exclude bindings.json --exclude .gitignore "$SRC" "$DEST/"
echo "synced to $DEST"
ls -la "$DEST"
