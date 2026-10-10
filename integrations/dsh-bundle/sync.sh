#!/usr/bin/env bash
# Copy the bundle (no tests / node_modules) to the Windows-side install dir.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/"
DEST="${1:-/mnt/c/Users/user/dsh-work/xmuse-bundle}"
mkdir -p "$DEST"
# bindings.json is runtime state written next to index.js; keep it across syncs.
rsync -rt --delete --exclude test/ --exclude node_modules/ --exclude sync.sh --exclude README.zh.md \
  --exclude bindings.json --exclude .gitignore "$SRC" "$DEST/"
echo "synced to $DEST"
ls -la "$DEST"
