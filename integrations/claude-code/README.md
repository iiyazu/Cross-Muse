# xmuse — board status mod for Claude Code

A Claude Code plugin of function hooks (a *mod*) that surfaces the xmuse
room board as a status line, toasts and a pane. Reads are free; the only
writes it can ever perform are split approve/reject decisions the human
presses through, under a short-lived plugin grant (see 授权 below).

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
  Review attention uses fixed labels: `待你复核`
  (`board_attention_review_operator_pending`) and `复核被驳回待返工`
  (`board_attention_review_objected`).
- State badges: `verified` = `✓ 已验证`, `done_claimed` = `◌ 自称完成·未验证`,
  `verification_failed` = `✗`, `verifying` = `…`,
  `waiting_for_provider` = `⧗`, `verification_error` = `‼`.
  The `✓` count in the status line counts accepted modules (`accepted_total`),
  never merely verified ones.
- The pane shows structured fields only. Agent-authored text appears solely in
  the expanded module detail as plain `Text` labelled `agent 自述 · 未验证`,
  never as Markdown or links. Split approvals happen in the pane once the
  human pairs a grant (see 授权), otherwise the pane links
  to the room page (`在 Web 审批`).

## 复核 (reviews, read-only)

Reviews are read-only here; verdicts belong to Room agents and the human in the Web.

When the room runs cross-family reviews (`capabilities.reviews == 1`), each
pane module row gains one fixed-word review part, counts only:

- `待复核` — review pending with a participant reviewer.
- `待你复核` — review pending with the operator (you). The row also gains a
  `在 Web 复核` link to the room page, same style as the `在 Web 审批` link.
  The link carries no review id and no patch reference.
- `已背书` — review endorsed. The module is accepted and its state badge
  reads `✓ 已验收`.
- `已驳回` — review objected; the owner reworks.
- ` · 已升级` is appended when the review was escalated to the operator
  (the assigned reviewer did not answer).
- `阻塞 N 主要 N 次要 N` finding counts appear only when any of them is
  non-zero.
- An unknown review status renders as `?value`, never hidden.

`已验收` appears only when the module is accepted. A module with
`state == verified` that is not accepted shows `已验证 · 待复核`, never
`已验收`. While reviews are off (`capabilities.reviews == 0`) rows render
exactly as before, with no review part.

What the mod never does with reviews:

- No review summary or finding text is ever read, shown, toasted, or handed
  to the model — only the structured state (`status`, `reviewer_kind`,
  escalation presence, finding counts) and the attention reason codes.
- No review verdict channel exists here: no command, no tool, no extra
  Button or Input, no new HTTP method or URL. The mod only reads the board
  summary and projection it already reads.
- The short-lived plugin grant (`board.split.decide`) covers proposed splits
  only and can never record a review verdict.

## 授权 (pairing flow)

1. In the Web board's "插件授权" panel, generate a pairing code for this
   room. The code looks like `ABCD-EFGH` and expires 120 seconds after
   issue; it is shown once, in the browser only.
2. In the pane's 授权 section, type the code into the 配对码 field
   (Enter: 配对). The mod normalises it locally (trim, upper-case) and
   rejects anything outside the grant alphabet without a network call.
3. On success the pane shows `已授权 · 剩余 mm:ss` with a 撤销授权 button,
   and each proposed split of the bound room gains 批准 / 拒绝 buttons.
   Pressing one only arms a confirm step: type the first 6 hex characters
   after `sha256:` of that split's digest (shown nowhere near the control)
   into the 输入摘要前 6 位以确认 field. A mismatch sends nothing; a match
   sends the decision with the split's full digest as `expected_digest`,
   then refetches the board.
4. `撤销授权` and `/xmuse detach` revoke the grant best-effort and drop it
   locally regardless of the response.

What the authorization can and cannot do:

- It covers exactly one scope, `board.split.decide`: approve or reject a
  proposed split of the paired room. Nothing else.
- It can never record review verdicts, touch any other operator route,
  memory, execution or runtime recovery; routes that need the operator
  token refuse a grant.
- It expires at `expires_at` (the pane counts down and then returns to the
  pairing view). The token lives in memory only, in the hooks module: it is
  never written to the store, an atom, a toast, a status line, a command
  result or the pane text, and a plugin reload loses it (re-pair to
  continue).
- Residual risk, accepted: anyone or anything that can drive this UI
  (accessibility tools, UI automation) can press the same buttons the human
  presses. The digest confirm and the short lifetime bound the damage; when
  in doubt, revoke the grant in the Web panel and pair again.

## Limits

- Model access stays Read-only: the only thing the model gets is
  `mcp__xmuse__status` (counts, state codes, attention codes). Human-pressed
  pane buttons may exchange a pairing code, decide a proposed split, or
  revoke the grant; nothing else writes, and no command or tool takes a code
  or a token.
- The mod never holds the operator token (no operator token in the plugin):
  grant routes authenticate with the short-lived Bearer token only, and the
  operator header is never read on them.
- Agent text never reaches the status line, toasts, command output or the
  model tool — only counts, codes and ids do.
- WSL: the mod talks to the loopback API of the machine it runs on. When
  Claude Code runs on Windows and the xmuse backend runs inside WSL, point
  `baseUrl` at the address where the backend listens on loopback; LAN
  hostnames are refused by the API's host guard.

## Safety rules (enforced by tests)

- No `$.process`, `$.fs`, `$.model`, `$.agent`, `$.prompt.*`,
  `$.session.*`, `$.mcp`, `$.config.set`, no operator routes, no
  `PUT`/`DELETE` — the source is grepped for these. `POST` and the Bearer
  header appear only in `src/grant_api.ts` (pure, injected transport).
- No `XMUSE_OPERATOR_TOKEN` / `X-Xmuse-Operator-Token` anywhere in the mod.
  The grant token is memory-only and never enters toasts, status lines,
  command/tool results or pane text.
- Writes run only from human-pressed pane `Button`/`Input` handlers
  (plus the pre-existing `/xmuse detach`, which revokes best-effort).
  Nothing is registered as a model-callable tool besides
  `mcp__xmuse__status`.
- `tests/fixtures.generated.ts` is generated from
  `docs/contracts/fixtures/board_v2/*.json` via
  `python tools/sync_fixtures.py`; never hand-edit it
  (`--check` fails CI when stale).

## Layout

```
.claude-plugin/plugin.json      manifest (name xmuse, userConfig)
.claude-plugin/marketplace.json marketplace listing (source ./)
hooks/hooks.json                module wiring (./register.tsx)
hooks/register.tsx              thin wiring only (the only $ user)
src/text.ts                     safe()/safeId()/shortRoom()/link helpers
src/labels.ts                   state badges
src/api.ts                      GET client + normalizers
src/grant_api.ts                grant writes (only POST/Bearer file)
src/grant_state.ts              pairing/expiry/confirm/toast mapping
src/board_state.ts              poll state atom, status/toast builders
src/poll.ts                     tick, auto-bind, attach/detach
src/pane.tsx                    pane nodes + tree
types/index.d.ts                PluginState contract
tests/*.test.ts                 claude plugin test suites
tests/grant_golden.generated.ts backend plugin_grant_v1 golden (tools/sync_fixtures.py)
tests/fixtures.generated.ts     generated fixtures (do not edit)
tools/sync_fixtures.py          fixture generator (stdlib only)
```
