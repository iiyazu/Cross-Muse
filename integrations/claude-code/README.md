# xmuse — read-only board status mod for Claude Code

A Claude Code plugin of function hooks (a *mod*) that surfaces the xmuse
room board as a status line, toasts and a pane. It is strictly read-only.

## Install

```
claude plugin marketplace add ./integrations/claude-code/.claude-plugin
claude plugin install xmuse@xmuse-marketplace
```

Or load once from disk:

```
claude --plugin-dir integrations/claude-code
```

Options (`userConfig`, see `.claude-plugin/plugin.json`):

| key | default | meaning |
| --- | --- | --- |
| `baseUrl` | `http://127.0.0.1:8201` | xmuse chat API (loopback only) |
| `webUrl` | `http://127.0.0.1:3000` | Workroom web UI, for approval links |
| `pollSeconds` | `5` | board summary poll interval |

## Commands and tool

- `/xmuse` or `/xmuse pane` — open the board pane.
- `/xmuse status` — compact structured block (counts + attention codes).
- `/xmuse attach [<room id or unique prefix>]` — bind this working directory
  to a room (no argument: most recently updated room). Without a binding the
  mod auto-binds to the most recently updated room that has board modules.
- `/xmuse detach` — clear the binding.
- `mcp__xmuse__status` — the same block as `/xmuse status`. This is the only
  thing the mod gives the model.

## Behaviour

- Polls `GET …/board/summary` every `pollSeconds`; on a revision change it
  refreshes the status line and, only while the pane is open, fetches the
  full `GET …/board` projection. `If-None-Match`/304 is honoured, ticks never
  overlap, failures back off (interval ×2, capped at 60 s).
- Status line, e.g. `看板 3 模块 · ✓1 …1 ✗1 · 待你处理 1` (zero parts
  omitted). Offline: `xmuse 离线`. Unbound: `xmuse 未绑定房间`.
- Toasts (at most one per tick, never on the first poll) when operator
  attention gains an item or a module becomes verified / fails verification.
- State badges: `verified` = `✓ 已验证`, `done_claimed` = `◌ 自称完成·未验证`,
  `verification_failed` = `✗`, `verifying` = `…`,
  `waiting_for_provider` = `⧗`, `verification_error` = `‼`.
- The pane shows structured fields only. Agent-authored text appears solely in
  the expanded module detail as plain `Text` labelled `agent 自述 · 未验证`,
  never as Markdown or links. Split approvals are web actions: the pane links
  to the room page (`在 Web 审批`) and offers no approve/reject controls.

## Limits

- Read-only: only `GET /api/chat/rooms` and the board routes. No room
  creation, no decisions, no token handling.
- Agent text never reaches the status line, toasts, command output or the
  model tool — only counts, codes and ids do.
- WSL: the mod talks to the loopback API of the machine it runs on. When
  Claude Code runs on Windows and the xmuse backend runs inside WSL, point
  `baseUrl` at the address where the backend listens on loopback; LAN
  hostnames are refused by the API's host guard.

## Safety rules (enforced by tests)

- No `$.process`, `$.fs`, `$.model`, `$.agent`, `$.prompt.submit`,
  `$.session.append/send`, `$.mcp`, `$.config.set`, no operator routes, no
  `POST`/`PUT`/`DELETE` — the source is grepped for these.
- No `XMUSE_OPERATOR_TOKEN` / `X-Xmuse-Operator-Token` anywhere in the mod.
- `tests/fixtures.generated.ts` is generated from
  `docs/contracts/fixtures/board_v2/*.json` via
  `python tools/sync_fixtures.py`; never hand-edit it
  (`--check` fails CI when stale).

## Layout

```
.claude-plugin/plugin.json      manifest (name xmuse, userConfig)
.claude-plugin/marketplace.json marketplace listing (source ./)
hooks/hooks.json                module wiring (./register.tsx)
hooks/register.tsx              thin wiring only
src/text.ts                     safe()/safeId()/shortRoom()/link helpers
src/labels.ts                   state badges
src/api.ts                      GET client + normalizers
src/board_state.ts              poll state atom, status/toast builders
src/poll.ts                     tick, auto-bind, attach/detach
src/pane.tsx                    pane nodes + tree
types/index.d.ts                PluginState contract
tests/*.test.ts                 claude plugin test suites
tests/fixtures.generated.ts     generated fixtures (do not edit)
tools/sync_fixtures.py          fixture generator (stdlib only)
```
