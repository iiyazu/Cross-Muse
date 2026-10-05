# xmuse-ctl — read-only command line for the xmuse board

`xmuse-ctl` is the third host of the board (after the Claude Code mod and
the OpenCode plugin). It prints structured text only. It never writes:
every command is a loopback `GET` to the rooms list, the board summary,
the board projection or the board events feed. Decisions stay in the Web —
approvals, review verdicts and every other write happen in the browser UI,
never here.

## Install

From the repository root (Python 3.12, standard library only):

```
pip install ./integrations/xmuse-ctl
```

or run without installing from `integrations/xmuse-ctl/`:

```
PYTHONPATH=integrations/xmuse-ctl python -m xmuse_ctl status --line
```

## Env vars

| var | default | meaning |
| --- | --- | --- |
| `XMUSE_API_BASE` | `http://127.0.0.1:8201` | xmuse chat API (loopback only) |
| `XMUSE_WEB_BASE` | `http://127.0.0.1:3000` | Workroom web UI, for approval links |
| `XDG_CONFIG_HOME` | `~/.config` | selects where `xmuse-ctl/bindings.json` lives |

A base URL whose host is not `127.0.0.1`, `localhost` or `[::1]`
(http only) is refused before anything is sent (exit 2,
`base URL must be loopback`).

## Commands

All commands print structured text only; `--json` prints a stable JSON
object instead (same structured fields, same filtering).

- `rooms` — list rooms, newest first: `short_id  updated  title-safe`.
  The title is agent/user text: it is sanitized and capped at 60 characters.
- `attach [PREFIX]` — bind the current working directory to a room by
  unique id prefix; with no argument, the most recent room that has
  modules (as the mod auto-binds). Ambiguous or unknown prefix exits 4
  with the matches listed by short id. Bindings live in
  `${XDG_CONFIG_HOME:-~/.config}/xmuse-ctl/bindings.json`
  (`{cwd: conversation_id}`, written atomically, mode 0600, directory 0700).
- `detach` — remove the entry for the cwd.
- `where` — print the bound room, or exit 4 with `not bound`.
- `status` — one line like the mod's status text, e.g.
  `看板 3 模块 · ✓1 …1 ✗1 · 待你处理 1`. The ✓ count is
  `accepted_total`, never the verified count. `--line` prints only that
  line (for hooks), no trailing text. Offline prints `xmuse 离线`, exit 3.
  Not bound and no `--room` exits 4.
- `board` — a table of modules
  (`module_id  owner  [provider]  state  review  accepted`
  plus `报告n/通过n/失败n/返工n`), the attention list with fixed
  reason-code words (unknown codes render as `未知原因（code）`),
  proposed splits as `待审批 <split_id>` with the Web link, and a final
  line `在 Web 打开：<link>`. The review column appears only when
  `capabilities.reviews == 1` (`待复核`/`待你复核`/`已背书`/`已驳回`,
  plus `已升级`); with reviews on, `已验收` shows only when `accepted` is
  true and a verified-but-not-accepted module keeps `✓ 已验证` and gains
  the review word (`· 待复核`). With reviews off the rows are the
  pre-review form (like the mod and the Web).
- `watch` — long-poll `board/events` forever, one line per new event:
  `#seq  kind  module_id  <fixed-word summary>`. The summary is built
  only from structured fields, never from agent text. Errors back off
  (1, 2, 4 … 30 s); Ctrl-C stops cleanly with exit 0. `--once` prints
  events after the current `board_seq` once and exits (for tests).
- `hook --host agy|dsh [--event EVENT]` — one structured status line
  for opt-in command hooks (see `hook` below). Reads one JSON object
  from stdin, prints exactly one JSON object on stdout, always exits 0.

## Integration

When the room integrates (`capabilities.integrations == 1`) the CLI shows
fixed words and counts only:

- `status --line` appends ` · 已集成 N` (when `integrated_total > 0`)
  and the job word when the latest job did not integrate (`排队集成` /
  `集成中` / `集成冲突` / `集成门禁失败` / `集成异常`).
- `status` adds `集成分支 <8 hex>` when the green head exists.
- `board` adds a room line like `已验收 N · 已集成 M · 集成分支 <head>`
  (`已验证` while reviews are off) and one `集成` word per module row
  (`排队集成` / `集成中` / `已集成` / `等待依赖集成` /
  `集成冲突 N 路径` / `门禁失败·嫌疑` / `集成异常·自动重试`,
  plus `·分支为旧版本` or `·未入分支`).
- `watch` summarizes `integration` events from structured fields only
  (`已集成 N 个模块`, `嫌疑 a、b`, `m1 冲突 N 路径（已回退）`).

Conflict detail is Web-only: conflicting paths and gate output tails leave
only through `GET …/board/integrations/{id}` (§5.3), which plugins, the CLI
and the mod never call — paths and gate output would reach a model's
context. `--json` carries `integrated_total`, `integrations` and
`integration: {status, green_head}` (8 hex), never paths or job ids.

Common options: `--room ID|PREFIX` (overrides the binding), `--json`,
`--api-base`.

## `hook` (opt-in status line for agy/dsh)

`xmuse-ctl hook --host agy|dsh [--event EVENT]` feeds the agy
`PreInvocation` hook and the dsh bridge (`UserPromptSubmit` /
`SessionStart`). It is off unless the host enables it; there is no
band or pane. It resolves the room from the binding of the working
directory the payload names (dsh: the payload's `cwd`; agy: the first
of `workspacePaths`; otherwise the process cwd). Unbound means `{}`.

What it can say: exactly the `status` one-line text prefixed `[xmuse] `,
plus up to 3 operator attention entries (`label target` with fixed
reason-code words and sanitized ids), total length ≤ 300 characters.
That is the only content it can emit: counts, state codes, labels and
ids only. Module titles, review summaries, finding text, event snippets
and gate output stay on the server — the hook never injects agent text.

When it speaks: only when the operator attention set changed since the
last emission for this room, only when at least one operator item
exists, and at most once per 30 seconds. Otherwise it prints `{}`.
Emission state lives in
`${XDG_STATE_HOME:-~/.local/state}/xmuse-ctl/hook-state.json`
(`{conversation_id: {"signature": ..., "at": epoch}}`, written
atomically, file 0600, directory 0700).

Output shapes: `--host agy` prints
`{"injectSteps":[{"ephemeralMessage":"<line>"}]}`; `--host dsh` prints
`{"hookSpecificOutput":{"hookEventName":"<EVENT>","additionalContext":"<line>"}}`
(`--event` accepts `UserPromptSubmit` and `SessionStart` only, default
`UserPromptSubmit`). stdin is capped at 64 KiB and its content is
ignored except for the directory hints; malformed or oversized input
counts as `{}`. Every failure (offline, unbound, bad shape, refused
base URL, unwritable state) prints `{}` with exit 0 and empty stderr.

## Exit codes

| code | meaning |
| --- | --- |
| 0 | ok |
| 2 | usage error, or the base URL was refused (`base URL must be loopback`) |
| 3 | server unreachable (`xmuse 离线`) |
| 4 | not bound / unknown room (`not bound`, `xmuse 未绑定房间`, …) |
| 5 | unexpected response shape |

## Read-only guarantee

- Only the `GET` method exists in this package; there is no `POST`,
  `PUT`, `DELETE` or `PATCH` anywhere in the source.
- No token is ever read (no `XMUSE_OPERATOR_TOKEN`, no other secret env
  var), no `Authorization` header and no `Cookie` are ever sent, and no
  request carries a body.
- The package never imports the server (`xmuse`, `xmuse_core`); it only
  speaks the public loopback HTTP contract, using the standard library.
- No agent-authored text is ever printed or handed to a model: module
  titles, review summaries, finding text, event snippets and gate output
  stay on the server. Output holds counts, state codes, ids, reason-code
  labels and short ids only, every server string sanitized (no ANSI
  escapes, no C0/C1 controls, no Unicode format characters).

## Layout

```
xmuse_ctl/
  __init__.py      package marker
  __main__.py      python -m xmuse_ctl entry point
  api.py           GET client + tolerant normalizers
  sanitize.py      safe()/safe_id()/short_room()/short_rev()
  labels.py        fixed state/review/reason/event words
  binding.py       cwd <-> room bindings file
  render.py        structured text + JSON builders
  hook.py          opt-in status line for agy/dsh hooks (always exit 0)
  cli.py           argument parsing + commands (main)
README.md          this file
```
