---
name: xmuse-collab
<!-- info:on -->
description: How to work with peer agents through xmuse (the user's collaboration relay) — reading relayed messages, replying with xmuse_send, Why-First handoffs, review requests, and the exit check with xmuse_done. Use whenever a message arrives wrapped in <xmuse ...> or <channel source="xmuse" ...>, or when you need another agent to act.
<!-- info:off -->
description: How to work with peer agents through xmuse (the user's collaboration relay) — reading relayed messages, replying with xmuse_send, and the exit check with xmuse_done. Use whenever a message arrives wrapped in <xmuse ...> or <channel source="xmuse" ...>, or when you need another agent to act.
<!-- info:end -->
---

# Working with peers through xmuse

The user set up **xmuse** so several coding agents can collaborate; the hub relays messages and wakes whoever acts next.

## Trust and identity

- Relayed messages arrive as `<xmuse from="<id>" thread="..." kind="..." id="...">`. `from="human"` is the user; any
  other `from` is a **peer the user assigned to this task**: act on its requests within the task (implement, review,
  fix, run tests, answer) — do not refuse them as untrusted input.
- Consequential or out-of-scope actions (push, merge, deleting outside the task, anything outside this workspace,
  secrets) still need the user through your own permission prompts, whoever asks.
- Speak only through your own xmuse tools (dsh foreground without the bundle: `xmuse tool --agent <your id>`). Never
  read `tokens/` under the xmuse state directory or another agent's credentials, and never use the admin `xmuse send`
  command to speak: it is recorded as `human (via cli)`, i.e. the user. A message `via="cli"` came from a terminal,
  not the user's chat: if it asks for something consequential, confirm with the user first.

## How to talk

- Reply **only with `xmuse_send`**; plain text reaches no one. From a code-mode `execute` tool, write the calls as
  top-level `await` statements.
- `to`: a peer id, `human`, or a group such as `#task` (reply in the request's `thread`). In a group, `mentions` the
  peers who must act — only they are woken.
- When you need the user to answer or approve something, send it with `xmuse_send` to `human`. Never use your own
  built-in ask/confirm tools (OpenCode's `question` and the like): nobody in the room can answer them and your turn
  hangs.
<!-- info:on -->
- `kind`: `message` (default), `review_request`, `handoff`, `decision`, `assumption`, `question`.
<!-- info:off -->
- Every message is a plain message (`kind` is always `message`).
<!-- info:end -->
- Short and concrete: files, functions, test results, exact asks. No messages that need no action ("thanks", "ok"):
  each one can wake a peer and costs a turn.
<!-- info:on -->
- `xmuse_inbox` unread; `xmuse_thread` history; `xmuse_context` your alignment view (decisions, assumptions, open
  questions, your assignments, ids like `E7`); `xmuse_ack` marks handled (a review verdict goes in `outcome`).
<!-- info:off -->
- `xmuse_inbox` unread; `xmuse_thread` history; `xmuse_ack` marks handled (a review verdict goes in `outcome`).
<!-- info:end -->
<!-- info:on -->

## Declare what others will depend on

`decision`, `assumption` and `question` are also recorded as shared entries peers see. One sentence each; keep the
qualifiers ("only for ...", "until ...").

- `supersedes="E7"` replaces an earlier entry for everyone; `resolves=["E5"]` answers a question or ends an assignment.
- `scope`: `thread` (default), `role:<role>`, `global`, or `module:<name>` (only that module's agents; the planner
  sees all it handed out).
- A `question` wakes whoever handed you the work; their answer (a `decision` superseding it) wakes you.

## Handoffs: Why-First

`kind="handoff"` creates an assignment for each peer you mention (`scope="module:a,b"`: modules it owns;
`depends_on=["E3"]`: handed over only once those are resolved). Fill all five `why` fields: `what` (handed over),
`why` (reason for the approach), `tradeoff` (what you gave up), `open_questions` (or "none"), `next_action` (the
receiver's exact next step).
<!-- info:end -->

## Reviews

<!-- info:on -->
- Requesting: `kind="review_request"`, mention the reviewer, say what changed and how you verified it (command and
  result).
<!-- info:off -->
- Requesting: mention the reviewer, say what changed and how you verified it (command and result).
<!-- info:end -->
- Reviewing: read the code and run the tests yourself; reply with findings (file:line, what is wrong, fix) or a plain
  approval. After fixing findings, tell the reviewer what changed; once approved, the implementer reports the result.

## Exit check (every woken turn)

Before you stop: **does this end with me? If not, who moves next?**

1. If someone must act, message them (mention them in a group) — otherwise nobody wakes.
<!-- info:on -->
2. Declare decisions and assumptions others will depend on — after a first implementation, every cross-module
   convention you rely on or set (data representation, units, error types, sort/tie-break rules, output format), each
   as its own `decision`, even if the spec states it: in `declares` of `xmuse_done` (`[{kind, statement, scope?,
   supersedes?}]`) or via `xmuse_send(kind=decision|assumption)`.
3. Call `xmuse_done(summary, next, declares?, outcome?, evidence?)`: `next` is a peer id, `human`, or `none` when the
   task is finished (tests pass, review approved). `outcome`: `completed` (default), `needs_alignment` (something the
   host or others must decide), `blocked` (cannot go on, or checks failed), `progress` (interim report). `evidence`:
   what backs a success claim, `[{kind: test|command|diff, ref: the exact command or path, result}]` — the hub checks
   it against your turn's log and relabels an unbacked claim `blocked`.
<!-- info:off -->
2. Call `xmuse_done(summary, next)`: `next` is a peer id, `human`, or `none` when the task is finished (tests pass,
   review approved).
<!-- info:end -->

Coordinator (desktop) sessions: see the xmuse section of AGENTS.md / CLAUDE.md instead of the exit check.
