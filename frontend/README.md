# xmuse Room-first frontend

The browser Workroom consumes bounded Room projections and durable invalidation events. It
is never authority for messages, Agent outcomes, attempts, or controls.

The unified local lifecycle currently supports Linux and WSL and requires Node.js 20.9+ and
npm. Backend setup is in
[QUICKSTART.md](../QUICKSTART.md); the current wire contract is in
[FRONTEND_API.md](../docs/xmuse/frontend/FRONTEND_API.md).

## Build and run

Create the standalone production build after checkout and whenever frontend dependencies or
source change:

```bash
cd frontend
npm ci
NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL=http://127.0.0.1:8201/api/chat npm run build
cd ..
```

Then use the repository-level lifecycle command:

```bash
export XMUSE_ROOT=/tmp/xmuse-local
uv run xmuse-workroom doctor
uv run xmuse-workroom start
```

Open `http://127.0.0.1:3000`. `/` enters the most recent room and stable room links use
`/rooms/{conversation_id}`. The launcher consumes the Next standalone output and supervises
it alongside the Chat API. Check or stop that generation with:

```bash
uv run xmuse-workroom status
uv run xmuse-workroom stop
```

The local application deliberately uses fixed loopback endpoints: the frontend binds
`127.0.0.1:3000` and browser Chat REST targets `127.0.0.1:8201`. A port collision is a local
configuration error, not a reason to bind a public interface or silently select another
port.

`xmuse-workroom status` also verifies that the current generation's Chat API-supervised
Runner and MCP processes are live; stale PID files or processes from another generation do
not count as ready.

The launcher injects the local `XMUSE_OPERATOR_TOKEN` only into the Chat API and Next server
processes. The browser never receives it, and it must never use a `NEXT_PUBLIC_*` name or be
embedded in the build. Room creation, human messages, cancel/retry, and Runtime recovery go
through fixed same-origin Next routes that validate Origin/Host, JSON type and size, fixed
upstream paths, timeouts, response bounds, and redirect behavior before adding the token
server-side.

This is a loopback-only, single-user local application. Native Windows and macOS lifecycle
support is not yet provided; Windows users should run it inside WSL.

## Verify

```bash
npm ci
npm run typecheck
npm test
npm run lint
npm run build
npx playwright install chromium
npm run test:e2e
```
