# xmuse quickstart

## Prerequisites

- Linux or WSL. Native Windows and macOS lifecycle support is not yet provided;
- Python 3.11+, `uv`, Git, and Bubblewrap (`bwrap`) for source development;
- an authenticated Codex CLI on `PATH` for real Agent turns;
- Node.js 20.9+ and npm when running the browser Workroom.

MemoryOS is optional. The v0.4.0 release companion packages `memoryos-lite 0.2.1` from clean
source SHA `26a77ece3bfe865169890a7dd49b5076c13ab723`, including its offline FastEmbed cache;
source development may instead point xmuse at a real external `memoryos` executable.

Backend entrypoints read the process environment directly. They do not automatically load a
repository `.env` file.

## Install a release

Linux x86_64 / WSL release assets are self-contained and offline after download:

```bash
python3.11 xmuse-setup.pyz install --bundle xmuse-0.4.0-linux-x86_64.tar.gz
python3.11 xmuse-setup.pyz install-memory \
  --bundle xmuse-memoryos-companion-0.4.0-linux-x86_64.tar.gz  # optional
export PATH="$HOME/.local/share/xmuse/active/.venv/bin:$PATH"
xmuse-setup verify
xmuse-workroom launch
```

The bootstrap validates Linux/x86_64, the exact CPython ABI, normalized archive paths and all
file digests. `launch` uses the installed Next standalone assets, starts one detached instance
of the existing Workroom manager, waits for real readiness and opens the browser. Use
`xmuse-workroom status` and `xmuse-workroom stop` for the same runtime generation. With the
optional companion installed, plain `xmuse-workroom launch` automatically selects it. Use
`launch --no-memory` to opt out; `launch --memory` remains the explicit compatibility alias
for `--memory-mode on`.

## Build the local application

Install the Python and frontend dependencies, then create the Next standalone production
build. Run this once after checkout and again whenever frontend dependencies or source
change:

```bash
uv sync --frozen --all-groups
cd frontend
npm ci
NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL=http://127.0.0.1:8201/api/chat npm run build
cd ..
```

The browser API coordinate is intentionally compiled into the frontend build. The default
local application uses fixed loopback endpoints: Workroom `http://127.0.0.1:3000` and Chat
API `http://127.0.0.1:8201`. It does not fall back to a public interface or a different port.

## Default Workroom path

Use the unified lifecycle command from the repository root:

```bash
export XMUSE_ROOT=/tmp/xmuse-local
uv run xmuse-workroom doctor
uv run xmuse-workroom start
```

`doctor` checks the built frontend, Node runtime, local data directory, and fixed ports before
startup. `start` supervises the Chat API and built Next server; in this managed mode the Chat
API starts, reconciles, and stops the Room-only MCP server and isolated Room Runner. Open
`http://127.0.0.1:3000`; `/` enters the most recent room and durable room links use
`/rooms/{conversation_id}`.

Inspect or stop the same local generation with:

```bash
uv run xmuse-workroom status
uv run xmuse-workroom stop
```

The launcher creates and injects the local operator token into the Chat API and Next server
processes. In managed mode every default write uses it: Room creation and human speech go
through `/api/rooms` and `/api/rooms/{conversation_id}/messages`; cancel/retry and guarded
Runtime recovery use their own fixed Next routes. The token must never use a `NEXT_PUBLIC_*`
name, enter browser storage, or be copied into frontend build files.

Starting `xmuse-chat-api` manually without a token remains an explicit trusted-loopback
debugging mode. Managed startup fails closed when its operator token is absent; neither mode
is remote multi-user authentication.

This remains a loopback-only, single-user local application. Do not expose either fixed port
to the LAN or Internet.

## Optional source-backed memory

Start the same Workroom with MemoryOS explicitly enabled. Full-local hybrid retrieval is the
default profile; archive-only remains available only as a compatibility profile. The normal
`auto` mode trusts only an installer-owned, digest-verified companion and otherwise leaves the
Room available with memory marked as not installed:

```bash
uv run xmuse-workroom start \
  --memory-mode on \
  --memoryos-executable /absolute/path/to/memoryos
```

The `--memory` flag is a compatibility alias for `--memory-mode on`; `--no-memory` is the
explicit `off` shortcut. `--memoryos-executable` is accepted only for `on`. Workroom binds MemoryOS to `127.0.0.1:8301`, gives it a
random server-only API key and a private `<XMUSE_ROOT>/runtime/memoryos-derived` directory,
and starts it with v3 memory/v2 recall. Full-local uses offline BM25, FastEmbed and RRF while
xmuse retains external governance of durable memory candidates in `chat.db`. The key is never
put in argv, the browser, the Room MCP process, or a Codex session.

MemoryOS is a rebuildable index. `chat.db` remains authority for source activities, pending
and approved memory candidates, delivery state, and recall receipts. If the sidecar is slow
or unavailable, Inspector reports memory degradation while Agent turns continue with their
durable Room causal context. Stop Workroom before changing this opt-in mode.

## Manual runtime debugging

The unified lifecycle command is the default. For explicit backend debugging only, first run
`xmuse-workroom stop`, then use separate terminals and keep the same `XMUSE_ROOT`. Do not
start these commands beside an already supervised generation:

```bash
uv run xmuse-mcp-server --xmuse-root "$XMUSE_ROOT" --port 8100
```

```bash
uv run xmuse-room-runner \
  --xmuse-root "$XMUSE_ROOT" \
  --generation manual-debug \
  --worktree "$PWD" \
  --max-concurrent-rooms 4 \
  --mcp-port 8100 \
  --delivery-timeout-s 180 \
  --cleanup-grace-s 8
```

Those runner settings match the Chat API's supervised Workroom defaults.

## Health and checks

```bash
uv run xmuse-workroom doctor
uv run xmuse-workroom status
curl http://127.0.0.1:8201/health
curl http://127.0.0.1:8201/api/chat/runtime/operations
curl http://127.0.0.1:8100/health
uv run xmuse-room-runner --help
```

With memory enabled, `xmuse-workroom status` lists MemoryOS separately; its degraded state
does not make the required Chat API, Room Runner, Room MCP, or frontend unready.

```bash
TMPDIR=/tmp uv run pytest -q
uv run ruff check .
cd frontend
npm run typecheck && npm test && npm run lint && npm run build
npm run test:e2e
```

For bounded production-path load and recovery checks, use the standalone lab from a clean
checkout. It writes no production telemetry and requires its result file to be outside the
repository:

```bash
uv run python scripts/room_soak_chaos.py ci-sim --result /tmp/xmuse-ci-soak.json
uv run python scripts/room_soak_chaos.py live-short --result /tmp/xmuse-live-short.json
```

`memory-recovery` additionally requires `--memoryos-executable` and uses two phases
(nine warm-up turns plus one post-recovery turn per Room) so recalled evidence is older
than the default recent Room burst; `live-soak` requires
`--confirm-provider-cost` and runs for at least 60 minutes. All live profiles start an
isolated Workroom, use fixed same-origin Next writes, inject identity-fenced faults, refresh
every Room in a real browser, verify SQLite and process/resource residue, then stop what they
started. Preflight or startup failures emit a separate bounded CLI error instead of
manufacturing a complete soak receipt.

The v0.4.0 release qualification additionally uses a 45-minute multi-Room soak
and a separate `room_memory_diversity_result/v1` run. Both publish only safe counts,
opaque source references, reason codes, and digests; they never publish Room/provider text,
MemoryOS internal IDs, paths, keys, or traces.

Do not commit runtime databases, JSONL logs, PID files, `.next`, `node_modules`, or caches.
