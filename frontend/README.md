# xmuse Room-first frontend

The browser Workroom consumes bounded Room projections and durable invalidation events. It
is never authority for messages, Agent outcomes, attempts, or controls.

## Status

The presentation layer was rebuilt (design: timeline first, trust-first board, one decision
queue). Its place in the product is the **evidence layer**: the human glances and decides in a
pane inside the agent app (the Claude Code mod's status line and `/xmuse pane`, the OpenCode
plugin), and that pane links here for what only the Web reads: review material, integration
and verification detail, the full timeline, runtime recovery.

| Path | Role |
| --- | --- |
| `src/components/ui` | primitives: `cx`, buttons, `AgentQuote`, avatars, Sheet/Dialog/ConfirmDialog, diff view |
| `src/components/shell` | the persistent shell (root layout): room rail, header, room view, new-room dialog, theme |
| `src/components/room` | timeline, composer, turn status, agent preview, plain-text-safe Markdown |
| `src/components/board` | status strip, work panel (view stack), module rows and file, integration, verification gates, contracts, splits, events, deep links |
| `src/components/decisions` | review dialog, execution view, decision-queue cards |
| `src/components/system` | system sheet (runtime and recovery, execution policy, plugin grants) |
| `src/lib` | API clients, projection normalizers (defence-in-depth sanitising of `AgentText`), view models, label tables, the board/review/integration/verification/grant types |
| `src/store` | the zustand store, sync coordination, persistence, caches |
| `src/app/api` | fixed same-origin routes that add the server-only operator token; the browser never holds it |
| `e2e/` | `workroom.spec.ts` and `smoke.spec.ts` run against fixtures (`e2e/fixtures/workroom`, captured from the chat API, and `docs/contracts/fixtures/board_v2`); `room-first-real.spec.ts` and `room-soak-real.spec.ts` are the backend's real-acceptance harness |

UI copy lives in the components that show it; status words come from the `src/lib/*-labels.ts`
tables shared with the Claude Code mod and `xmuse-ctl`. Styling is Tailwind v4, CSS-first:
the tokens are in `src/app/globals.css` (`@theme`, OKLCH, light and dark under `data-theme`).

Deep links: `/rooms/{conversation_id}?module=…` (or `split`, `integration`, `execution`,
`contract` with an optional `v`) opens the work panel on that view; `?review={module_id}` opens
the operator review while it is still pending. The address follows the panel.

Plugin grants are listed and revoked here; pairing is terminal-only
(`xmuse-workroom pair --host … --room …`, `main_window_control_v1.md` §3), so no pairing code
reaches the browser.

Not built yet: the native Codex Agent Console (`room-soak-real.spec.ts` lines 324–330 wait for
it), a command palette, board event cards in the timeline, the lessons view (waits for
`capabilities.lessons`).

Rules the UI keeps (they are product invariants, not styling):

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
- Accessibility: focus returns after dialogs, `aria-live` never announces secrets, pages are
  axe-clean (the e2e specs check both themes).

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
