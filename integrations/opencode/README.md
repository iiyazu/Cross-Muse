# xmuse — read-only board status plugin for the OpenCode TUI

An OpenCode TUI plugin that surfaces the xmuse room board as a footer status
line, toasts and `/xmuse` slash commands. It is strictly read-only: the
OpenCode twin of the Claude Code mod in `integrations/claude-code/`.

## Install

From a checkout of this repository:

```
opencode plugin add git+file://<repo>
```

Then register it under `plugins` in `opencode.jsonc`. Fetched plugin code
lives in the npm cache at `~/.cache/opencode/npm`.

Configuration is by environment only:

| variable         | default                | meaning                              |
| ---------------- | ---------------------- | ------------------------------------ |
| `XMUSE_BASE_URL` | `http://127.0.0.1:8201` | xmuse chat API (loopback only)      |

## Commands

- `/xmuse` or `/xmuse status` — compact structured block (counts + attention codes).
- `/xmuse attach [<room id or unique prefix>]` — bind this working directory
  to a room (no argument: most recently updated room). Without a binding the
  plugin auto-binds to the most recently updated room that has board modules.
- `/xmuse detach` — clear the binding.

Every command runs local code only (no model involvement) and reports its
result as a toast built from structured fields only.

## Behaviour

- Polls `GET …/board/summary` every 5 s; honours `If-None-Match`/304, ticks
  never overlap, failures back off (interval ×2, capped at 60 s).
- Status line, e.g. `看板 3 模块 · ✓1 …1 ✗1 · 待你处理 1` (zero parts
  omitted). Offline: `xmuse 离线`. Unbound: `xmuse 未绑定房间`.
- Toasts (at most one per tick, never on the first poll) when operator
  attention gains an item or the verified / failed counts grow.
- State badges: `verified` = `✓ 已验证`, `done_claimed` = `◌ 自称完成·未验证`,
  `verification_failed` = `✗`, `verifying` = `…`,
  `waiting_for_provider` = `⧗`, `verification_error` = `‼`.
- The base URL must be a loopback host (`127.0.0.1`, `localhost`, `::1`);
  anything else is rejected before any request and reported in a toast.
- Split approvals are web actions: there are no approve/reject controls here.

## Limits

- Read-only: only `GET /api/chat/rooms` and the board summary route. No room
  creation, no decisions, no token handling, no `context.client` use.
- Agent text never reaches the status line, toasts or command output — only
  counts, codes and ids do.
- WSL: the plugin talks to the loopback API of the machine it runs on. LAN
  hostnames are refused by the API's host guard.

## Safety rules (enforced by tests)

- No `context.client`, no `session.*`, no model-callable tool registration,
  no operator routes, no `POST`/`PUT`/`DELETE` — the source is grepped.
- No `XMUSE_OPERATOR_TOKEN` / `X-Xmuse-Operator-Token` anywhere in the plugin.
- `src/core/*` is regenerated from the Claude mod via
  `python tools/sync_core.py` (only the `./types` import path differs);
  never hand-edit it (`--check` fails CI when stale).
- `tests/fixtures.generated.ts` is generated from
  `docs/contracts/fixtures/board_v2/*.json` via
  `python tools/sync_fixtures.py`; never hand-edit it
  (`--check` fails CI when stale).

## Layout

```
package.json                  manifest (exports "." server entry, "./tui")
tsconfig.json                 bundler resolution, @opentui/solid jsx
src/index.ts                  server entry (dependency-free)
src/tui.tsx                   thin TUI glue only (slot, keymap, timer)
src/host.ts                   context bridge + pure logic (poll, commands)
src/core/text.ts              safe()/safeId()/shortRoom()/link helpers
src/core/labels.ts            state badges
src/core/api.ts               GET parsing + normalizers
src/core/board_state.ts       status/toast builders
src/core/poll.ts              binding helpers, backoff, attach picking
src/core/types.ts             shared shapes (copy of the Claude mod's)
tests/board.test.ts           bun suites (no OpenCode needed)
tests/fixtures.generated.ts   generated fixtures (do not edit)
tools/sync_core.py            core generator (stdlib only)
tools/sync_fixtures.py        fixture generator (stdlib only)
```
