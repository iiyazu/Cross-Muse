# xmuse Room-first frontend

The browser Workroom consumes bounded Room projections and durable invalidation events. It
is never authority for messages, Agent outcomes, attempts, or controls.

## Status: the presentation layer was removed on purpose

The components, the styles and the UI end-to-end specs were deleted (last commit that still has
them: `1eb3337`) so the presentation can be rebuilt from a clean base. `/` and
`/rooms/{conversation_id}` serve a placeholder (`src/app/reset-notice.tsx`). What stays is the
adaptation layer, and it is the contract the new UI builds on:

| Path | Role |
| --- | --- |
| `src/lib` | API clients, projection normalizers (defence-in-depth sanitising of `AgentText`), view models, label tables, the board/review/integration/grant types |
| `src/store` | the zustand store, sync coordination, persistence, caches |
| `src/app/api` | fixed same-origin routes that add the server-only operator token; the browser never holds it |
| `e2e/room-first-real.spec.ts`, `room-soak-real.spec.ts`, `playwright*.config.ts` | the backend's real-acceptance harness: keep the prompts and the acceptance contract; the selectors encode the removed UI and must be rewritten with the new one |
| `src/app/globals.css` | kept as a path (backend tooling names it); its content is a placeholder |

Rules the rebuilt UI must keep (they are product invariants, not styling):

- `accepted` is the only completion value. A module the owner calls `done` is a claim and must
  never look like a verified one; verification, review and integration are separate axes.
- Agent-authored text arrives as `AgentText` (`untrusted: true`): render it as plain text, label
  it as the agent's own words, and never put it in a title, `aria-label`, toast, status line or
  `document.title`.
- Operator decisions (split approval, review verdicts, execution decisions, runtime recovery) go
  through the fixed Next routes only. Material patches and integration details are read in the
  Web only; plugins and the CLI never read them.
- The shared timeline stays primary; the Workbench is a progressive dock, not a Dashboard.
- Capability gating comes from `capabilities.*` of the projection, never from display hints.
- Keep the accessibility behaviour the previous UI had: focus return after dialogs, `aria-live`
  that never announces secrets (pairing codes), axe-clean pages.

`npm run test:e2e` currently runs one smoke spec; the Room flows return with the new UI.

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
embedded in the build. Room creation, human messages, cancel/retry, native Codex Agent
Console actions, and Runtime recovery go through fixed same-origin Next routes that validate
Origin/Host, JSON type and size, fixed
upstream paths, timeouts, response bounds, and redirect behavior before adding the token
server-side.

The right-side Workbench separates three evidence domains instead of combining them in one
Inspector: `Agent` presents one participant-bound Codex App Server session, `Room` presents
shared turn/execution/memory evidence, and `Runtime` presents process-level health and guarded
recovery. The Agent tab exposes discovered Goal lifecycle, model/effort, one-turn Plan mode,
steer, interrupt, compact, review, bounded native events, and Room observation-frontier
evidence. Sending from its Console is not Room speech, although actions such as Goal and
interrupt can still affect that participant's runtime state.
`/goal`, `/plan`, and the other listed aliases are shortcuts for those descriptors, not a raw
CLI or RPC surface. Shared Room messages never parse slash commands, and native progress never
becomes Agent speech in the Room timeline.

New Room setup choices come from the bounded, read-only
`GET /api/chat/room-setup-options` projection. The browser displays server-authored roster
names and collaboration roles; it does not hard-code provider bindings or expose free-form
persona and permission editing.

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
