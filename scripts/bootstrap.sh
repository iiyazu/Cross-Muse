#!/usr/bin/env bash
# One-step setup for a fresh clone: check python/node/uv, sync the hub venv, install the shim's node deps,
# then run `xmuse doctor`. Safe to re-run; changes nothing outside this checkout (uv's and npm's caches aside).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_MIN=3.12
NODE_MIN=20
fail=0
say() { printf '%s\n' "$*"; }
need() { say "FAIL $1"; say "     fix: $2"; fail=1; }

# uv (manages the hub's Python and venv)
if command -v uv >/dev/null 2>&1; then
  say "ok   uv: $(uv --version)"
else
  need "uv not found" "curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# node (runs the MCP shim)
if command -v node >/dev/null 2>&1; then
  v="$(node --version)"; major="${v#v}"; major="${major%%.*}"
  if [ "$major" -ge "$NODE_MIN" ]; then say "ok   node: $v"; else need "node $v < $NODE_MIN" "install node >= $NODE_MIN"; fi
else
  need "node not found" "install node >= $NODE_MIN (e.g. via nvm or your package manager)"
fi
command -v npm >/dev/null 2>&1 || need "npm not found" "install npm (ships with node)"

if [ "$fail" -ne 0 ]; then
  say "fix the items above, then re-run $0"; exit 1
fi

# hub venv: uv picks a Python >= $PY_MIN (downloads one if the system has none)
say "---- uv sync (hub)"
uv sync --project "$ROOT/hub" --python "$PY_MIN"
py="$ROOT/hub/.venv/bin/python"
"$py" -c "import sys; assert sys.version_info >= (3, 12), sys.version" \
  || { need "hub venv python is older than $PY_MIN" "rm -rf $ROOT/hub/.venv && $0"; exit 1; }

# shim deps: exactly the lockfile
say "---- npm ci (shim)"
(cd "$ROOT/shim" && npm ci --no-audit --no-fund)

say "---- xmuse doctor"
# doctor exits 1 on FAIL items; a fresh clone without a workspace only warns
"$py" -m xmuse doctor || true
say ""
say "done. Put the hub on PATH with:  export PATH=\"$ROOT/hub/.venv/bin:\$PATH\""
